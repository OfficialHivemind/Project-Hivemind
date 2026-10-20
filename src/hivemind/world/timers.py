"""Recurring deadlines, and the boss semantics that change how they are scheduled.

Two things here that existing macros get wrong.

**UTC.** Every hardcoded boss clock written in local time drifts by an hour twice
a year when daylight saving moves, and then sends the bot to an empty field for
six months without ever reporting an error. Nothing in this module touches local
time; `time.time()` is an epoch and stays one.

**Bosses are not interchangeable.** If a boss SAVES damage between visits, the
right behaviour is to chip at it whenever you pass. If it RESETS when you leave,
the right behaviour is never to start unless you can finish. Same UI, opposite
rules, and the flag that separates them is unverified for every boss we know of.

So `preemptable()` returns False for anything unverified. That is the asymmetric
choice again: treating a persistent boss as resetting merely forgoes an
optimisation, while treating a resetting boss as persistent wastes whole fights.

**What "learning a cooldown" actually means here.** The engine prefers a
measured period over the data file's guess, but only from a signal that
measures the period. The gap between consecutive SIGHTINGS is not one: a window
stays open until the thing is collected, so re-checking an uncollected Wealth
Clock every five minutes measures the polling cadence, not the hour. The signal
is USE -> first sighting of readiness, and even that is only an upper bound, so
each measurement is kept as a bracket (`Observation`) between the last "not yet"
and the first "there it is". A wide bracket is itself useful: it means look
sooner.

And a sighting outranks arithmetic. If the bot is looking at a respawned boss,
it is ready — whatever an unverified two-day guess in the data file says.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..datapaths import data

DEFAULT_PATH = data("world", "timers.yaml")
MIN_OBSERVATIONS = 3          # before an observed cooldown overrides the file
# HOW FAR A COUNTDOWN READ CAN BE FROM THE TRUTH, in seconds. MEASURED
# 2026-09-23: two frames of the Wealth Clock's panel saved 17 s apart
# (var/routes/attempt-333/210634-*-26-walk-w60.jpg and
# var/places/wealth_clock-210651.jpg) read "(57:36)" and "(57:22)" -- 14 s
# of countdown. The 3 s is the gap between when a frame is captured, when it
# is named, and when the model has read it; the timer itself has one-second
# resolution. See `TimerState.observe_countdown`.
COUNTDOWN_SLACK_S = 3.0


@dataclass(frozen=True)
class TimerKind:
    id: str
    name: str
    category: str
    cooldown_s: float
    persistent_hp: bool
    verified: bool
    note: str = ""


@dataclass
class Observation:
    """One measurement of a cooldown, kept as a BRACKET rather than a number.

    `upper` is the gap from a use to the first sighting of readiness. It is an
    upper bound, not the period: the thing may have become ready while nobody
    was looking. `lower` is the gap from that same use to the last sighting of
    it still being unavailable, which is a genuine lower bound.

    Keeping both is what stops a slow polling cadence from being mistaken for a
    long cooldown. A bot that only looks every three hours cannot learn a
    one-hour timer from sightings alone -- but it knows the answer lies between
    the last "not yet" and the first "there it is", and it can say so.
    """
    lower: float
    upper: float

    @property
    def estimate(self) -> float:
        return (self.lower + self.upper) / 2.0

    @property
    def uncertainty(self) -> float:
        return self.upper - self.lower


@dataclass
class TimerState:
    """One tracked deadline, plus what we have observed about its period."""
    kind: TimerKind
    last_ready_at: float | None = None
    last_used_at: float | None = None
    last_absent_at: float | None = None
    observations: list[Observation] = field(default_factory=list)
    # WHEN THE MACHINE ITSELF SAYS IT WILL BE READY, read off its own
    # countdown. See observe_countdown.
    countdown_ready_at: float | None = None
    # The use the last cooldown observation was taken from, so re-reading the
    # same countdown does not count one use several times.
    _counted_use_at: float | None = None

    # ---- period -----------------------------------------------------------
    @property
    def observed_cooldown(self) -> float | None:
        """Median of the bracketed measurements, once there are enough."""
        if len(self.observations) < MIN_OBSERVATIONS:
            return None
        return float(statistics.median(o.estimate for o in self.observations))

    @property
    def cooldown_uncertainty(self) -> float | None:
        """How wide the brackets are. A large value means: go and look sooner."""
        if len(self.observations) < MIN_OBSERVATIONS:
            return None
        return float(statistics.median(o.uncertainty for o in self.observations))

    @property
    def cooldown(self) -> float:
        """What the scheduler should use: observed beats the data file's guess."""
        observed = self.observed_cooldown
        return observed if observed is not None else self.kind.cooldown_s

    @property
    def cooldown_is_measured(self) -> bool:
        return self.observed_cooldown is not None

    # ---- availability -----------------------------------------------------
    @property
    def seen_ready_since_use(self) -> bool:
        """Have we looked at it and found it available since we last used it?"""
        if self.last_ready_at is None:
            return False
        if self.last_used_at is None:
            return True
        return self.last_ready_at > self.last_used_at

    def ready_at(self) -> float | None:
        """When it next becomes available, or None if we have never seen it."""
        # DIRECT EVIDENCE BEATS ARITHMETIC. A sighting after the last use means
        # it is ready now, whatever the cooldown says.
        #
        # Without this, observe_ready() had no effect at all once a timer had
        # been used once: the bot could be looking straight at a respawned boss
        # while an unverified two-day guess from the data file insisted it was
        # two days away. Worse, it was self-reinforcing -- the scheduler would
        # not go and look until the wrong cooldown elapsed, so the estimate
        # could never be corrected by observation.
        if self.seen_ready_since_use:
            return self.last_ready_at
        # AND THE MACHINE'S OWN COUNTDOWN BEATS THE DATA FILE'S GUESS, for
        # the same reason: it is a direct reading of the deadline rather than
        # a use plus an unverified period. Only a countdown read after the
        # last use counts -- one from before it is about a window already
        # spent.
        if (self.countdown_ready_at is not None
                and (self.last_used_at is None
                     or self.countdown_ready_at > self.last_used_at)):
            return self.countdown_ready_at
        if self.cooldown <= 0:
            return self.last_ready_at          # always-present things
        if self.last_used_at is None:
            return self.last_ready_at
        return self.last_used_at + self.cooldown

    def ready(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        deadline = self.ready_at()
        return deadline is not None and deadline <= now

    def remaining(self, now: float | None = None) -> float | None:
        deadline = self.ready_at()
        if deadline is None:
            return None
        return max(0.0, deadline - (time.time() if now is None else now))

    # ---- the semantics that matter ---------------------------------------
    def preemptable(self) -> bool:
        """May the bot start this, wander off, and come back to it?

        Only when persistence has been MEASURED. An unverified boss is treated
        as resetting, because treating a persistent one as resetting costs an
        optimisation while the reverse costs whole fights.
        """
        return self.kind.persistent_hp and self.kind.verified

    def explain_preemption(self) -> str:
        if self.preemptable():
            return "saves damage between visits — safe to chip at in passing"
        if self.kind.persistent_hp and not self.kind.verified:
            return ("may save damage, but nobody has checked — so it is only started "
                    "when it can be finished")
        return "resets when you leave the field — once started, it won't stop this fight"

    # ---- observation ------------------------------------------------------
    def observe_ready(self, at: float | None = None) -> None:
        """Record that it is available NOW.

        What gets LEARNED is the gap from a use to the FIRST sighting of
        readiness after it -- never the gap between consecutive sightings.

        A window stays open until the thing is collected, and the bot re-checks
        on its own cadence (check_every_s is 600-3600s in the expiries data),
        so sighting-to-sighting gaps measure the POLLING INTERVAL rather than
        the period. That is not hypothetical: six sightings of one uncollected
        Wealth Clock five minutes apart taught a 300-second cooldown for an
        hourly machine, and cooldown_is_measured then reported True, so the
        scheduler trusted the fabricated figure over the data file.
        """
        at = time.time() if at is None else at
        if (self.last_used_at is not None and at > self.last_used_at
                and not self.seen_ready_since_use):
            # lower bound: the last time we looked and it was NOT there
            lower = 0.0
            if (self.last_absent_at is not None
                    and self.last_absent_at > self.last_used_at):
                lower = self.last_absent_at - self.last_used_at
            self.observations.append(Observation(lower, at - self.last_used_at))
        self.last_ready_at = at

    def observe_absent(self, at: float | None = None) -> None:
        """Record that it is NOT available right now.

        This is what turns an upper bound into a bracket. Without it the only
        measurement available is "it was ready by the time I looked", which
        over-estimates every cooldown by however long the bot took to look
        again -- and an over-estimate costs whole windows.
        """
        self.last_absent_at = time.time() if at is None else at

    def observe_used(self, at: float | None = None) -> None:
        at = time.time() if at is None else at
        self.last_used_at = at
        # Using it consumes the window: it is no longer available, and the
        # next sighting starts a fresh measurement.
        self.last_absent_at = at
        self.countdown_ready_at = None

    def observe_countdown(self, seconds: float, at: float | None = None) -> None:
        """Record that the machine's panel shows `seconds` left on its timer.

        MEASURED 2026-09-23: the Wealth Clock's prompt carries its cooldown as
        a live countdown, "Use the Wealth Clock (57:22)", in a red panel
        (var/places/wealth_clock-210651.jpg). That is three facts at once:

          * it is NOT available now, which is `observe_absent`;
          * it WILL be at `at + seconds`, which is a deadline read directly
            rather than inferred from a use and an unverified period;
          * and if this bot's own press started that timer, the period is
            `(at - last_used_at) + seconds` to within the read's slack --
            a measurement of the cooldown, bracketed by COUNTDOWN_SLACK_S,
            that no polling cadence can distort. Taken once per use.

        The observation is only recorded from a use this bot SAW happen
        (`observe_used`). A countdown on a machine someone else used says
        when it will be ready, and nothing about how long it takes.
        """
        at = time.time() if at is None else at
        seconds = max(0.0, float(seconds))
        self.last_absent_at = at
        self.countdown_ready_at = at + seconds
        used = self.last_used_at
        if (used is not None and at >= used
                and self._counted_use_at != used):
            period = (at - used) + seconds
            self.observations.append(Observation(
                max(0.0, period - COUNTDOWN_SLACK_S), period + COUNTDOWN_SLACK_S))
            self._counted_use_at = used


def load_kinds(path: Path | str = DEFAULT_PATH) -> dict[str, TimerKind]:
    try:
        data = yaml.safe_load(Path(path).read_text())
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, TimerKind] = {}
    for row in (data or {}).get("timers", []):
        try:
            out[row["id"]] = TimerKind(
                id=row["id"], name=row["name"],
                category=row.get("category", ""),
                cooldown_s=float(row.get("cooldown_s", 0)),
                persistent_hp=bool(row.get("persistent_hp", False)),
                verified=bool(row.get("verified", False)),
                note=row.get("note", ""))
        except (KeyError, TypeError, ValueError):
            continue
    return out


@dataclass(frozen=True)
class FieldGuard:
    """A boss that holds a field on the clock, fought or not: it arrives
    `minute` minutes past every hour and leaves `stays_s` seconds later.

    The hour is UTC's, like every clock in this module -- the game keeps the
    full hour, "not in time zones that are a fractional number of hours away
    from UTC" (the wiki, on the Mondo Chick) -- so `now % 3600` is the time
    past it. The Mondo Chick on Mountain Top is the one measured; see its
    entry in data/world/timers.yaml."""
    id: str
    name: str
    field: str
    minute: int
    stays_s: float

    def visit(self, now: float) -> tuple[float, float]:
        """(arrives, leaves) of the visit under way at `now`, else the next."""
        arrives = now - now % 3600.0 + self.minute * 60.0
        if now < arrives - 3600.0 + self.stays_s:
            arrives -= 3600.0          # last hour's visit, not over yet
        elif now >= arrives + self.stays_s:
            arrives += 3600.0          # this hour's is over
        return arrives, arrives + self.stays_s


def load_guards(path: Path | str = DEFAULT_PATH) -> dict[str, FieldGuard]:
    """The timers.yaml rows that hold a field (`guards:`), by that field."""
    try:
        data = yaml.safe_load(Path(path).read_text())
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, FieldGuard] = {}
    for row in (data or {}).get("timers", []):
        if not isinstance(row, dict) or not row.get("guards"):
            continue
        try:
            out[str(row["guards"])] = FieldGuard(
                id=row["id"], name=row["name"], field=str(row["guards"]),
                minute=int(row.get("arrives_at_minute", 0)),
                stays_s=float(row["stays_s"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


class TimerBook:
    """Every deadline the bot tracks."""

    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.kinds = load_kinds(path)
        self.states: dict[str, TimerState] = {
            key: TimerState(kind) for key, kind in self.kinds.items()}

    def get(self, timer_id: str) -> TimerState | None:
        return self.states.get(timer_id)

    def ready(self, now: float | None = None) -> list[TimerState]:
        return [s for s in self.states.values() if s.ready(now)]

    def upcoming(self, now: float | None = None) -> list[TimerState]:
        """Everything with a known deadline, soonest first."""
        known = [s for s in self.states.values() if s.ready_at() is not None]
        return sorted(known, key=lambda s: s.ready_at())

    def unknown(self) -> list[TimerState]:
        """Never observed, so no deadline can be offered. An honest gap."""
        return [s for s in self.states.values() if s.ready_at() is None]

    def preemptable(self) -> list[TimerState]:
        return [s for s in self.states.values() if s.preemptable()]

    def __len__(self) -> int:
        return len(self.states)
