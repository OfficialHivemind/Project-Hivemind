"""The bot looking back at its own last hour: what it made, and what cost it.

WHY. The owner, 2026-10-11: the AI felt like a plain bot, not an AI; it should
think more and want to get better. Every number here was already measured, trip
by trip, in
var/trips.jsonl (brain/ledger) -- honey, seconds, deaths, how each route out and
home ended, why each gather ended. Nothing read it back. This does, once an
hour: the honey rate, and the LEAKS -- the time and trips that made nothing --
ranked by the minutes they cost, the biggest named as the thing to fix next.

WHAT IT REFUSES. A cost that was not measured is not invented: a missed walk
home costs the seconds of that walk, measured; a trip that gathered nothing
costs all its seconds; nothing else is priced.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

WINDOW_S = 3600.0
STALL_WORDS = "has not risen"
MISSED = ("elsewhere", "missed")


@dataclass
class Leak:
    what: str                 # "the walk home from blue flower"
    times: int = 0            # how often it happened
    minutes: float = 0.0      # seconds of trips that made no honey, where it happened
    # The field it happened IN, for a leak the planner prices nowhere else
    # (`field_minutes`): gathering off the flowers, a trip that gathered
    # nothing. None for route misses (decide prices them by route odds) and
    # deaths (decide prices them by survival).
    field: str | None = None

    def describe(self) -> str:
        cost = f", {self.minutes:.0f} min for nothing" if self.minutes >= 1 else ""
        return f"{self.what} x{self.times}{cost}"


@dataclass
class Review:
    trips: int = 0
    converted: int = 0
    honey: int = 0
    pollen: int = 0
    honey_read: int = 0       # trips whose honey was measured
    hours: float = 0.0
    leaks: list = field(default_factory=list)      # Leak, worst first

    @property
    def per_hour(self) -> float:
        return self.honey / self.hours if self.hours > 0 else 0.0

    @property
    def focus(self) -> Leak | None:
        return self.leaks[0] if self.leaks else None

    def describe(self) -> str:
        rate = self.pollen / self.hours if self.hours > 0 else 0.0
        head = (f"{self.trips} trip(s), {self.converted} converted, "
                f"{self.pollen / 1e6:.1f}M pollen ({rate / 1e6:.1f}M/h); honey measured on "
                f"{self.honey_read}: {self.honey / 1e6:.1f}M")
        if not self.leaks:
            return head + "; nothing went wrong that I measured"
        return (head + "; what cost me: " + "; ".join(l.describe() for l in self.leaks[:3])
                + f" -- the one to fix next: {self.focus.what}")


def _pretty(name) -> str:
    return str(name or "somewhere").replace("_", " ")


# PREDICTION ERROR (backlog B2, brain-research-3 section 3 step 5). A place's
# honey is PRICED twice: once by value.payout() (the formula, or the
# discounted mean of past payouts) before the errand runs, once by what the
# HUD actually paid (var/payouts.jsonl, value.record_payout). When those two
# disagree by more than PRED_ERROR_FACTOR, the price fed to the scorer is
# wrong and every Q it ever produced for that place was wrong too -- that is
# as real a leak as a wasted walk, just priced in honey instead of minutes.
PRED_ERROR_FACTOR = 2.0       # a ratio outside [1/this, this] gets called out
MIN_ERROR_ROWS = 3            # fewer measured payouts and the mean is noise


def review(rows, now: float, window: float = WINDOW_S) -> Review:
    """The trips that ended in the last `window` seconds, looked back on."""
    recent = [r for r in rows if isinstance(r, dict)
              and now - float(r.get("at") or 0.0) <= window
              and float(r.get("seconds") or 0.0) > 0]
    out = Review(trips=len(recent))
    if not recent:
        return out
    # THE RATE OVER THE TIME IT WORKED: the trips' own seconds, not the wall
    # clock -- an hour the owner had it stopped is not an hour it made nothing
    out.hours = max(1e-6, sum(float(r.get("seconds") or 0.0) for r in recent) / 3600.0)
    leaks: dict = defaultdict(lambda: Leak(""))

    def leak(key: str, minutes: float, where: str | None = None) -> None:
        got = leaks[key]
        got.what = key
        got.times += 1
        got.minutes += minutes
        got.field = where

    for r in recent:
        made = int(r.get("honey") or 0) if r.get("converted") else 0
        out.honey += made
        out.honey_read += int(made > 0)
        out.pollen += int(r.get("pollen") or 0)
        out.converted += int(bool(r.get("converted")))
        # A TRIP THAT MADE NOTHING: no honey AND no pollen read (an unmeasured
        # honey after a convert is not nothing -- "honey not measured, left at
        # the empty bag" trips gathered millions)
        gathered = made > 0 or int(r.get("pollen") or 0) > 0
        wasted = 0.0 if gathered else float(r.get("seconds") or 0.0) / 60.0
        raw_field = r.get("credited") or r.get("aimed_at")
        field_ = _pretty(raw_field)
        for step in r.get("routes") or ():
            # a route that ENDED SOMEWHERE ELSE: its own walking seconds were for
            # nothing ("unknown" is not judged a miss)
            if not isinstance(step, dict) or step.get("outcome") not in MISSED:
                continue
            kind = step.get("kind")
            target = _pretty(step.get("target"))
            what = (f"the walk home from {target}" if kind == "home"
                    else f"the errand walk to {target}" if kind == "errand"
                    else f"the {'flight' if kind == 'flight' else 'walk'} to {target}")
            leak(what, float(step.get("seconds") or 0.0) / 60.0 + wasted)
            wasted = 0.0                 # the trip's minutes are counted once
        if int(r.get("deaths") or 0):
            leak(f"dying in {field_}", wasted)
            wasted = 0.0
        if STALL_WORDS in str(r.get("gather_ended") or ""):
            leak(f"gathering off the flowers in {field_}", wasted, raw_field)
            wasted = 0.0
        if wasted >= 1.0 and r.get("gather_seconds"):
            leak(f"a trip to {field_} that gathered nothing", wasted, raw_field)
    out.leaks = sorted(leaks.values(), key=lambda l: (-l.minutes, -l.times, l.what))
    return out


def field_minutes(got: Review) -> dict:
    """{field: minutes lost there} from the leaks that carry a field: what
    decide.Planner.leak_minutes reads when LEAK_FEEDBACK is on."""
    out: dict = {}
    for leak in got.leaks:
        if leak.field and leak.minutes > 0:
            out[leak.field] = out.get(leak.field, 0.0) + leak.minutes
    return out


@dataclass
class PredictionError:
    name: str
    measured: float            # mean honey actually paid, this window
    predicted: float           # the V it was priced at
    ratio: float                # predicted / measured
    rows: int                   # payouts the mean is over

    def describe(self) -> str:
        pretty = _pretty(self.name)
        if self.ratio >= 1:
            return f"I overvalued {pretty} {self.ratio:.0f}x"
        return f"I undervalued {pretty} {1.0 / self.ratio:.0f}x"


def prediction_errors(payout_rows, predicted: dict, now: float,
                       window: float = WINDOW_S) -> list:
    """Each place with `MIN_ERROR_ROWS`+ payouts in the last `window` seconds,
    its measured mean against `predicted[name]` (value.payout's V, or
    value.score(...).v) -- worst-mispriced first. A place missing from
    `predicted`, or priced None (unpriced, B1's rule), is left out."""
    by_name: dict = defaultdict(list)
    for r in payout_rows:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        if now - float(r.get("at") or 0.0) > window:
            continue
        by_name[r["name"]].append(float(r.get("honey") or 0))
    out = []
    for name, paid in by_name.items():
        v = predicted.get(name)
        if not v or len(paid) < MIN_ERROR_ROWS:
            continue
        measured = sum(paid) / len(paid)
        if measured <= 0:
            continue
        out.append(PredictionError(name, measured, float(v), float(v) / measured, len(paid)))
    out.sort(key=lambda e: max(e.ratio, 1.0 / e.ratio), reverse=True)
    return out


def describe_errors(errors: list) -> str:
    """One line for the hourly review: the worst mispriced place, only when
    it is off by more than PRED_ERROR_FACTOR (a close guess is not a leak)."""
    bad = [e for e in errors if e.ratio >= PRED_ERROR_FACTOR or e.ratio <= 1.0 / PRED_ERROR_FACTOR]
    return bad[0].describe() if bad else ""


# LESSONS (backlog 7; Reflexion/ExpeL): what keeps going wrong, remembered across
# sessions -- each hour's leaks counted under their own words in var/lessons.json,
# so the review can say "my top leak 5 times since 10 Oct" and the owner (and the
# next build) sees which problems recur rather than one hour's noise.
def remember(path, got: Review, now: float) -> str:
    """Fold this hour's leaks into the lessons at `path`; a sentence on the focus.

    7b (Reflexion/ExpeL rows): a row is {signature, change, support,
    contradiction, first, last} plus the old {hours, top, minutes} this
    function already kept -- an old file with only the old fields still loads
    (every read below is .get() with a default) and keeps folding as before.
    Once record_change() notes a fix for a signature, each later hour either
    repeats it (contradiction: the fix didn't hold) or doesn't (support: it
    did) -- checked over EVERY tracked signature, not just this hour's top 5,
    so a fix that held (no leak at all) still counts."""
    import json
    import time as _time
    from pathlib import Path
    path = Path(path)
    try:
        body = json.loads(path.read_text())
        body = body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        body = {}
    leaked_this_hour = {leak.what for leak in got.leaks}
    for sig, row in body.items():
        if not isinstance(row, dict) or not row.get("change"):
            continue
        if float(row.get("change_at") or 0.0) > now:
            continue                   # the change isn't in effect yet
        key = "contradiction" if sig in leaked_this_hour else "support"
        row[key] = int(row.get(key, 0)) + 1
    for i, leak in enumerate(got.leaks[:5]):
        row = body.get(leak.what) or {"hours": 0, "top": 0, "minutes": 0.0, "first": now}
        row["hours"] = int(row.get("hours", 0)) + 1
        row["top"] = int(row.get("top", 0)) + (1 if i == 0 else 0)
        row["minutes"] = round(float(row.get("minutes", 0.0)) + leak.minutes, 1)
        row["last"] = now
        row.setdefault("signature", leak.what)
        row.setdefault("change", "")
        row.setdefault("support", 0)
        row.setdefault("contradiction", 0)
        body[leak.what] = row
    tmp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(body, indent=1))
    tmp.replace(path)
    if not got.focus:
        return ""
    row = body[got.focus.what]
    since = _time.strftime("%d %b", _time.localtime(float(row.get("first", now))))
    return (f" (a leak in {row['hours']} hour(s) since {since}, the top one {row['top']} "
            f"time(s), {row['minutes']:.0f} min in all)")


def record_change(path, signature: str, change: str, now: float) -> None:
    """Note that `signature`'s leak got a fix (free text) at `now`; later
    remember() calls count each hour after this as support or contradiction."""
    import json
    from pathlib import Path
    path = Path(path)
    try:
        body = json.loads(path.read_text())
        body = body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        body = {}
    row = body.get(signature) or {"hours": 0, "top": 0, "minutes": 0.0, "first": now}
    row["signature"] = signature
    row["change"] = change
    row["change_at"] = now
    row.setdefault("support", 0)
    row.setdefault("contradiction", 0)
    row["last"] = now
    body[signature] = row
    tmp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(body, indent=1))
    tmp.replace(path)


def recurring(path, n: int = 3) -> list:
    """The `n` lessons that cost the most minutes, worst first: [(what, row)]."""
    import json
    from pathlib import Path
    try:
        body = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    rows = [(k, v) for k, v in (body.items() if isinstance(body, dict) else ()) if isinstance(v, dict)]
    return sorted(rows, key=lambda kv: (-float(kv[1].get("minutes", 0)), -int(kv[1].get("top", 0))))[:n]


# HONEY BY NECTAR (backlog 5): the ledger's trips carry the nectar levels they ran
# under; the honey a second of trips with a nectar over half full against under it.
def nectar_effect(rows, nectar: str, field=None):
    """(honey/s with `nectar` >= 50%, honey/s below it, trips each) over converted
    trips (in `field` when given), or None when either side has under 3 trips."""
    hi, lo = [], []
    for r in rows:
        if not isinstance(r, dict) or not r.get("converted") or not r.get("honey"):
            continue
        if field and (r.get("credited") or r.get("aimed_at")) != field:
            continue
        level = (r.get("nectar") or {}).get(nectar)
        sec = float(r.get("seconds") or 0)
        if level is None or sec <= 0:
            continue
        (hi if level >= 50 else lo).append(float(r["honey"]) / sec)
    if len(hi) < 3 or len(lo) < 3:
        return None
    return sum(hi) / len(hi), sum(lo) / len(lo), len(hi), len(lo)


# BUFF UPTIME (backlog 5b, brain-research.md item 5): same question as
# nectar_effect -- honey/s (or pollen/s where honey wasn't measured, a
# dispenser left at an unmeasured bag reads millions of pollen) with a buff
# mostly up against mostly not, over the same trip-ledger rows.
#
# EXPECTED LEDGER FIELD (not yet written -- for brain/ledger to add): each
# trip row should carry row["buffs"] = {"haste": seconds_up, "focus":
# seconds_up, ...}, the seconds that buff showed on the buff bar during the
# trip (sampled StatMonitor-style, every ~6 s) -- the same shape as
# row["nectar"] above, just seconds instead of a level.
BUFF_UP_FRACTION = 0.5     # counted "up" for the trip at >= half its seconds


def buff_effect(rows, buff: str, field=None):
    """(rate with `buff` up, rate without, trips each) over converted trips (in
    `field` when given); None when either side has under 3 trips."""
    hi, lo = [], []
    for r in rows:
        if not isinstance(r, dict) or not r.get("converted"):
            continue
        if field and (r.get("credited") or r.get("aimed_at")) != field:
            continue
        sec = float(r.get("seconds") or 0)
        if sec <= 0:
            continue
        honey = float(r.get("honey") or 0)
        rate = honey / sec if honey > 0 else float(r.get("pollen") or 0) / sec
        if rate <= 0:
            continue
        up = float((r.get("buffs") or {}).get(buff) or 0)
        (hi if up >= sec * BUFF_UP_FRACTION else lo).append(rate)
    if len(hi) < 3 or len(lo) < 3:
        return None
    return sum(hi) / len(hi), sum(lo) / len(lo), len(hi), len(lo)


def describe_buffs(rows, buffs) -> str:
    """One line for the hourly review: the buff with the biggest measured
    lift, among `buffs` with enough trips either side to compare."""
    got = []
    for b in buffs:
        e = buff_effect(rows, b)
        if e and e[1] > 0:
            got.append((b,) + e)
    if not got:
        return ""
    b, hi, lo, n_hi, n_lo = max(got, key=lambda t: t[1] / t[2])
    return f"{_pretty(b)} up made {hi / lo:.1f}x the rate ({n_hi} trip(s) vs {n_lo})"


if __name__ == "__main__":
    import json
    import tempfile
    from pathlib import Path

    # B2: the honey dispenser priced 3x what it actually paid, this hour
    payouts = [{"name": "honey_dispenser", "at": 100.0, "honey": 10_000},
               {"name": "honey_dispenser", "at": 200.0, "honey": 12_000},
               {"name": "honey_dispenser", "at": 300.0, "honey": 11_000}]
    errs = prediction_errors(payouts, {"honey_dispenser": 33_000.0}, now=400.0)
    assert len(errs) == 1 and errs[0].rows == 3
    assert 2.5 < errs[0].ratio < 3.5
    assert "overvalued" in describe_errors(errs)
    assert prediction_errors(payouts[:2], {"honey_dispenser": 33_000.0}, now=400.0) == []
    assert prediction_errors(payouts, {"honey_dispenser": None}, now=400.0) == []
    assert prediction_errors(payouts, {"honey_dispenser": 33_000.0}, now=10_000.0, window=100.0) == []
    assert describe_errors(prediction_errors(payouts, {"honey_dispenser": 15_000.0}, now=400.0)) == ""

    # 7b: an old-format lessons file still loads and folds
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "lessons.json"
        path.write_text(json.dumps({"an old leak": {"hours": 2, "top": 1, "minutes": 5.0,
                                                      "first": 1.0, "last": 2.0}}))
        assert recurring(path, 1)[0][0] == "an old leak"
        remember(path, Review(leaks=[Leak("an old leak", times=1, minutes=3.0)]), now=3.0)
        assert json.loads(path.read_text())["an old leak"]["hours"] == 3

        # a fix recorded, then a recurrence (contradiction), then a quiet hour (support)
        record_change(path, "a new leak", "added a timeout", now=10.0)
        assert json.loads(path.read_text())["a new leak"]["change"] == "added a timeout"
        remember(path, Review(leaks=[Leak("a new leak", times=1, minutes=1.0)]), now=20.0)
        assert json.loads(path.read_text())["a new leak"]["contradiction"] == 1
        remember(path, Review(leaks=[]), now=30.0)
        body = json.loads(path.read_text())
        assert body["a new leak"]["support"] == 1 and body["a new leak"]["contradiction"] == 1

    # 5b: buff up (>= half the trip) against not, honey/s compared
    trips = [{"converted": True, "seconds": 100, "honey": 1000, "buffs": {"haste": 90}},
             {"converted": True, "seconds": 100, "honey": 1100, "buffs": {"haste": 80}},
             {"converted": True, "seconds": 100, "honey": 1050, "buffs": {"haste": 95}},
             {"converted": True, "seconds": 100, "honey": 400, "buffs": {"haste": 0}},
             {"converted": True, "seconds": 100, "honey": 420, "buffs": {"haste": 5}},
             {"converted": True, "seconds": 100, "honey": 380, "buffs": {}}]
    hi, lo, n_hi, n_lo = buff_effect(trips, "haste")
    assert n_hi == 3 and n_lo == 3 and hi > lo
    assert buff_effect(trips, "focus") is None
    assert "haste" in describe_buffs(trips, ["haste", "focus"])

    print("ok")
