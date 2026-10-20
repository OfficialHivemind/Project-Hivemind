"""One subsystem owning every resource that decays.

The beequip inbox, the nectar condense window, the Wealth Clock, field boosters,
sticker stacks: these look like five different problems and are one. Each is a
resource that disappears on a timer, with no in-game warning, and a human player
loses them constantly for exactly that reason.

THE VERIFIED / UNVERIFIED SPLIT

Every duration in `data/economy/expiries.yaml` is marked, and the split is not
bookkeeping -- it changes what the bot is allowed to do:

    verified      may drive an automated irreversible action
    unverified    is SURFACED to you, uncertainty stated, but never used to
                  justify the bot spending or consuming anything by itself

That asymmetry is deliberate. Telling someone "your beequip inbox may lapse in
about five hours" costs nothing if the real figure is four or six. Condensing
their nectar on a guessed deadline does not have that property. So an unverified
deadline can raise a warning and can raise a QUESTION, but it cannot authorise
an action -- `actionable` is the method that encodes that, and it is the only
one a task should call before acting.

Every duration currently in the file is unverified, which is why the Sentinel
presently warns and asks but never acts alone.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..datapaths import data

DEFAULT_PATH = data("economy", "expiries.yaml")


@dataclass(frozen=True)
class ExpiryKind:
    """A class of decaying thing, loaded from the data file."""
    id: str
    what: str
    detail: str
    duration_s: float
    verified: bool
    severity: str = "warn"
    lead_s: float = 600.0
    check_every_s: float = 900.0
    note: str = ""


@dataclass
class Tracked:
    """A specific instance, started at a specific moment."""
    kind: ExpiryKind
    started_at: float
    instance: str = ""
    value: float = 0.0            # what losing it would cost, in honey

    @property
    def key(self) -> str:
        return f"{self.kind.id}:{self.instance}" if self.instance else self.kind.id

    def deadline(self) -> float:
        return self.started_at + self.kind.duration_s

    def remaining(self, now: float | None = None) -> float:
        return self.deadline() - (time.time() if now is None else now)

    def lapsed(self, now: float | None = None) -> bool:
        return self.remaining(now) <= 0

    def due(self, now: float | None = None) -> bool:
        """Inside the lead window: the point at which it is worth doing something."""
        return self.remaining(now) <= self.kind.lead_s

    def actionable(self, now: float | None = None) -> bool:
        """May the bot act on this DEADLINE by itself?

        Only when the duration has been measured. An unverified deadline can
        raise a warning and can raise a question for the owner; it cannot
        authorise the bot to consume anything on its own schedule.
        """
        return self.kind.verified and self.due(now)

    def describe(self, now: float | None = None) -> str:
        left = self.remaining(now)
        if left <= 0:
            when = "lapsed"
        elif left < 3600:
            when = f"{int(left // 60)}m"
        else:
            when = f"{left / 3600:.1f}h"
        hedge = "" if self.kind.verified else " (not sure of the time, so it asks you)"
        return f"{self.kind.what}: {when}{hedge}"


def load_kinds(path: Path | str = DEFAULT_PATH) -> dict[str, ExpiryKind]:
    try:
        data = yaml.safe_load(Path(path).read_text())
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, ExpiryKind] = {}
    for row in (data or {}).get("expiries", []):
        try:
            out[row["id"]] = ExpiryKind(
                id=row["id"], what=row["what"], detail=row.get("detail", ""),
                duration_s=float(row["duration_s"]),
                verified=bool(row.get("verified", False)),
                severity=row.get("severity", "warn"),
                lead_s=float(row.get("lead_s", 600)),
                check_every_s=float(row.get("check_every_s", 900)),
                note=row.get("note", ""))
        except (KeyError, TypeError, ValueError):
            continue          # a malformed row must not lose the rest of the file
    return out


class Sentinel:
    """Tracks every live expiry and says what needs attention."""

    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.kinds = load_kinds(path)
        self._tracked: dict[str, Tracked] = {}

    def start(self, kind_id: str, at: float | None = None, instance: str = "",
              value: float = 0.0) -> Tracked | None:
        """Begin tracking. Returns None for an unknown kind rather than raising."""
        kind = self.kinds.get(kind_id)
        if kind is None:
            return None
        tracked = Tracked(kind=kind, instance=instance, value=value,
                          started_at=time.time() if at is None else at)
        self._tracked[tracked.key] = tracked
        return tracked

    def clear(self, key: str) -> None:
        """Stop tracking -- the thing was collected, or is gone."""
        self._tracked.pop(key, None)

    def all(self) -> list[Tracked]:
        return sorted(self._tracked.values(), key=lambda t: t.deadline())

    def due(self, now: float | None = None) -> list[Tracked]:
        """Inside the lead window, soonest first. Includes unverified ones."""
        return [t for t in self.all() if t.due(now)]

    def actionable(self, now: float | None = None) -> list[Tracked]:
        """What the bot may act on ALONE. Verified deadlines only."""
        return [t for t in self.all() if t.actionable(now)]

    def needs_asking(self, now: float | None = None) -> list[Tracked]:
        """Due, but on an unverified timing -- so it becomes a question, not an act."""
        return [t for t in self.due(now) if not t.kind.verified]

    def at_risk_value(self, now: float | None = None) -> float:
        return sum(t.value for t in self.due(now))

    def __len__(self) -> int:
        return len(self._tracked)
