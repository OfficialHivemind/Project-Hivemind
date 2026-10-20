"""Measuring whether fields actually degrade, from ordinary play.

The planter engine refuses to harvest early because field degradation is
unverified. This module is how that question gets answered without a dedicated
experiment: every harvest the bot performs is recorded, and the evidence
accumulates until it is decisive one way or the other.

The claim under test:

    harvesting a field repeatedly reduces its yield, and it recovers over
    roughly 48 hours

Which makes a testable prediction. Normalise each harvest by its growth (so a
60%-grown planter is comparable to a full one) and you get yield-per-unit-growth
for that field. If the claim is true, that number should FALL as recent harvest
count rises. If fields do not degrade, the slope is flat and the variation is
just noise.

So: ordinary least squares of normalised yield against recent harvests, plus a
t-statistic on the slope. The bot does not get to conclude anything until the
sample is big enough and the slope clears the threshold -- an underpowered study
that concludes "no effect" is exactly as wrong as one that invents an effect,
and `verdict` says "not enough data" rather than picking a side.

Deliberately NOT a neural net or anything clever. One slope, one t-statistic,
and an honest count of how many observations back it.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

MIN_SAMPLES = 24          # below this, no verdict is offered at all
MIN_FIELDS = 2            # a single field could be confounded by anything
T_THRESHOLD = 2.5         # roughly 99% against the no-effect null at this n
RECOVERY_WINDOW_S = 48 * 3600.0


@dataclass(frozen=True)
class Harvest:
    """One harvest, recorded as it happens."""
    field: str
    seed: str
    growth: float                 # 0..1 at the moment of harvest
    yield_honey: float
    at: float
    recent_harvests: int          # harvests of THIS field in the last 48h

    @property
    def normalised(self) -> float:
        """Yield per unit of growth, so partial harvests are comparable."""
        return self.yield_honey / self.growth if self.growth > 0 else 0.0


@dataclass
class Evidence:
    samples: int
    fields: int
    slope: float                  # change in normalised yield per recent harvest
    intercept: float
    t_statistic: float
    verdict: str                  # "degrades" | "no effect" | "not enough data"

    @property
    def decisive(self) -> bool:
        return self.verdict in ("degrades", "no effect")

    def summary(self) -> str:
        if self.verdict == "not enough data":
            return (f"{self.samples}/{MIN_SAMPLES} harvests across "
                    f"{self.fields}/{MIN_FIELDS} fields — no verdict yet")
        direction = "falls" if self.slope < 0 else "rises"
        return (f"{self.verdict}: normalised yield {direction} by "
                f"{abs(self.slope):,.0f} per recent harvest "
                f"(t={self.t_statistic:.1f}, n={self.samples})")


def analyse(harvests: list[Harvest]) -> Evidence:
    """Within-field least squares of normalised yield against recent harvests.

    FIXED EFFECTS, not a pooled regression. Fields have wildly different base
    yields -- Pineapple and Dandelion differ by an order of magnitude -- and
    are harvested at different cadences, so `recent_harvests` is correlated
    with WHICH field a sample came from. Pooled, the slope measures that
    between-field difference rather than degradation. Measured: 14 Pineapple
    harvests at ~1,000,000 honey with recent_harvests in {0,1} plus 14
    Dandelion harvests at ~100,000 with recent_harvests in {4,5}, with NEITHER
    field degrading at all, produced verdict "degrades" at t = -21.9.

    MIN_FIELDS made that worse rather than safer: it required the confound to
    be present before any verdict could be reached.

    Subtracting each field's own mean from both x and y removes the per-field
    level, so the slope can only come from variation WITHIN a field -- which is
    the question actually being asked.
    """
    usable = [h for h in harvests if h.growth > 0 and h.yield_honey > 0]
    by_field: dict[str, list[Harvest]] = {}
    for harvest in usable:
        by_field.setdefault(harvest.field, []).append(harvest)
    fields = len(by_field)

    if len(usable) < MIN_SAMPLES or fields < MIN_FIELDS:
        return Evidence(len(usable), fields, 0.0, 0.0, 0.0, "not enough data")

    # A field with one harvest carries no within-field variation: de-meaned it
    # contributes exactly (0, 0), which would be fake precision in the dof.
    groups = [rows for rows in by_field.values() if len(rows) >= 2]
    n = sum(len(rows) for rows in groups)
    grand_mean = sum(h.normalised for h in usable) / len(usable)
    if len(groups) < MIN_FIELDS or n < MIN_SAMPLES:
        return Evidence(len(usable), fields, 0.0, grand_mean, 0.0,
                        "not enough data")

    dx: list[float] = []
    dy: list[float] = []
    for rows in groups:
        mean_x = sum(float(h.recent_harvests) for h in rows) / len(rows)
        mean_y = sum(h.normalised for h in rows) / len(rows)
        for h in rows:
            dx.append(float(h.recent_harvests) - mean_x)
            dy.append(h.normalised - mean_y)

    sxx = sum(x * x for x in dx)
    if sxx == 0:
        # within every field, every harvest happened at the same recent-count,
        # so there is no within-field variation to fit
        return Evidence(n, fields, 0.0, grand_mean, 0.0, "not enough data")

    slope = sum(x * y for x, y in zip(dx, dy)) / sxx
    intercept = grand_mean            # the level; the fit itself is within-field

    residuals = [y - slope * x for x, y in zip(dx, dy)]
    # one dof per estimated field mean, plus one for the slope
    dof = n - len(groups) - 1
    if dof <= 0:
        return Evidence(n, fields, slope, intercept, 0.0, "not enough data")
    residual_var = sum(r * r for r in residuals) / dof

    if residual_var > 0:
        t = slope / math.sqrt(residual_var / sxx)
    elif slope != 0.0:
        # A PERFECT FIT IS THE STRONGEST EVIDENCE, not the weakest. The old
        # code emitted t = 0 here, which fell into the `abs(t) < T_THRESHOLD`
        # branch and returned the decisive verdict "no effect" -- so the most
        # conclusive dataset available produced the opposite conclusion.
        # Verified: 24 harvests with yield = 100000 - 5000*recent_harvests,
        # an exact 5% loss per harvest, reported as "no effect". Zero residual
        # with a non-zero slope is an infinite t; yields are quantised game
        # numbers, so a noiseless sample is not exotic.
        t = math.copysign(math.inf, slope)
    else:
        t = 0.0                       # genuinely flat, with no scatter at all

    if t <= -T_THRESHOLD:
        verdict = "degrades"
    elif abs(t) < T_THRESHOLD:
        verdict = "no effect"
    else:
        # significantly POSITIVE: yield rises with recent harvests. That
        # contradicts the hypothesis rather than supporting it, and most likely
        # means something else is confounded (a buff, a better field). Do not
        # dress it up as a result.
        verdict = "not enough data"

    return Evidence(n, fields, slope, intercept, t, verdict)


class HarvestLog:
    """Append-only record of harvests, persisted as JSON lines."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._records: list[Harvest] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text().splitlines():
            try:
                self._records.append(Harvest(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue          # a corrupt line must not lose the whole log

    def recent_harvests(self, field: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        return sum(1 for r in self._records
                   if r.field == field and now - r.at <= RECOVERY_WINDOW_S)

    def record(self, field: str, seed: str, growth: float, yield_honey: float,
               at: float | None = None) -> Harvest:
        at = time.time() if at is None else at
        harvest = Harvest(field=field, seed=seed, growth=growth,
                          yield_honey=yield_honey, at=at,
                          recent_harvests=self.recent_harvests(field, at))
        self._records.append(harvest)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(json.dumps(asdict(harvest)) + "\n")
        return harvest

    def evidence(self) -> Evidence:
        return analyse(self._records)

    def __len__(self) -> int:
        return len(self._records)
