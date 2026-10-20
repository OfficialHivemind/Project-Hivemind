"""What the bot knows, how sure it is, and when it should go and look again.

The owner's requirement was that the bot works out its own progress rather than
being told -- it should check how far the account has already progressed.
This module is how that is possible without the bot ever acting on a guess.

Nothing here is a variable. Every fact is a `Belief` carrying the value, WHEN it
was observed, and how much that is still worth. Confidence decays from the moment
of observation at a rate that depends on the fact:

    bee count        changes maybe once an hour      -> decays slowly
    pollen           changes every second you gather -> decays in seconds
    owned tools      changes almost never            -> barely decays

That single idea does a surprising amount of work:

  * it turns "do I know X?" into a number rather than a yes/no, so the planner
    can weigh looking against acting
  * it makes observation a SCHEDULABLE ACTION with a cost, so the bot only opens
    the hive when something actually depends on knowing
  * it lets an irreversible action demand a minimum confidence, which is what
    stops the bot spending 3,333 royal jelly on a forty-minute-old inventory read

The decay curve is exponential with a per-fact half-life. Exponential because
the question "how likely is this still true" compounds: two minutes of staleness
is not twice as bad as one, and a fact is never *certainly* wrong, just
progressively less worth betting on.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

# Half-lives in seconds: after this long, confidence in an unre-observed fact
# has fallen by half. Chosen from how fast the underlying thing actually moves.
DEFAULT_HALF_LIFE = 600.0

HALF_LIVES: dict[str, float] = {
    # changes continuously while playing
    "pollen": 20.0,
    "honey": 60.0,
    "position": 5.0,
    "backpack_fraction": 20.0,
    # changes on a slow timer
    "field_health": 1800.0,
    "planter_growth": 300.0,
    "nectar": 900.0,
    # changes rarely
    "bees": 3600.0,
    "bee_types_discovered": 7200.0,
    "royal_jelly": 1800.0,
    # effectively permanent once true
    "tool": 86400.0,
    "badge": 86400.0,
    "quest_unlocked": 86400.0,
}


def half_life_for(name: str) -> float:
    """Longest matching prefix wins, so 'tool:golden_rake' inherits 'tool'."""
    best, best_len = DEFAULT_HALF_LIFE, -1
    for prefix, value in HALF_LIVES.items():
        if (name == prefix or name.startswith(prefix + ":")) and len(prefix) > best_len:
            best, best_len = value, len(prefix)
    return best


@dataclass
class Belief:
    """One fact, with its provenance."""
    name: str
    value: Any
    observed_at: float
    source: str = ""
    initial_confidence: float = 1.0
    half_life: float = DEFAULT_HALF_LIFE

    def age(self, now: float | None = None) -> float:
        return max(0.0, (time.time() if now is None else now) - self.observed_at)

    def confidence(self, now: float | None = None) -> float:
        """Exponential decay from `initial_confidence` with `half_life`."""
        if self.half_life <= 0:
            return self.initial_confidence
        return self.initial_confidence * math.pow(0.5, self.age(now) / self.half_life)


class BeliefStore:
    """Every belief the bot holds, and the rules for trusting them.

    Deliberately NOT a dict of values. Reading a fact goes through `get`, which
    can return None when the fact is too stale to use -- forcing every caller to
    decide what to do about not knowing, rather than silently using a stale value.
    """

    def __init__(self, on_change: Callable[[Belief], None] | None = None):
        self._beliefs: dict[str, Belief] = {}
        self._on_change = on_change

    # ---- writing ----------------------------------------------------------
    def observe(self, name: str, value: Any, source: str = "",
                confidence: float = 1.0, at: float | None = None) -> Belief:
        """Record something actually seen."""
        belief = Belief(name=name, value=value,
                        observed_at=time.time() if at is None else at,
                        source=source, initial_confidence=confidence,
                        half_life=half_life_for(name))
        self._beliefs[name] = belief
        if self._on_change:
            self._on_change(belief)
        return belief

    def invalidate(self, name: str) -> None:
        """Mark a fact as certainly unknown -- e.g. after spending the thing."""
        self._beliefs.pop(name, None)

    # ---- reading ----------------------------------------------------------
    def raw(self, name: str) -> Belief | None:
        return self._beliefs.get(name)

    def confidence(self, name: str, now: float | None = None) -> float:
        belief = self._beliefs.get(name)
        return belief.confidence(now) if belief else 0.0

    def get(self, name: str, min_confidence: float = 0.0,
            default: Any = None, now: float | None = None) -> Any:
        """The value, or `default` when it is not known well enough.

        `min_confidence` is the caller's stake. A cosmetic read passes 0; an
        irreversible spend passes something high and gets None if the bot has
        not looked recently enough, which is the whole safety property.
        """
        belief = self._beliefs.get(name)
        if belief is None or belief.confidence(now) < min_confidence:
            return default
        return belief.value

    def knows(self, name: str, min_confidence: float = 0.5,
              now: float | None = None) -> bool:
        return self.confidence(name, now) >= min_confidence

    def stale(self, min_confidence: float = 0.5,
              now: float | None = None) -> list[Belief]:
        """Everything that has decayed below a threshold, worst first."""
        out = [b for b in self._beliefs.values() if b.confidence(now) < min_confidence]
        return sorted(out, key=lambda b: b.confidence(now))

    def __contains__(self, name: str) -> bool:
        return name in self._beliefs

    def __iter__(self) -> Iterator[Belief]:
        return iter(self._beliefs.values())

    def __len__(self) -> int:
        return len(self._beliefs)


@dataclass
class Observation:
    """An action that would refresh some beliefs, and what it costs to run.

    This is the piece that makes the whole design work. Observing is not free --
    opening the hive means walking there and losing gathering time -- so the
    planner needs to compare "go and look" against "keep working" on the same
    scale. Cost is in seconds; value is computed from how much the stale facts
    matter to whatever is being decided.
    """
    name: str
    refreshes: tuple[str, ...]
    cost_s: float
    run: Callable[[], None] | None = None
    requires_screen: str = "in_game"

    def value(self, store: BeliefStore, weights: dict[str, float] | None = None,
              now: float | None = None) -> float:
        """How much confidence this would buy, weighted by how much each fact matters."""
        weights = weights or {}
        total = 0.0
        for name in self.refreshes:
            missing = 1.0 - store.confidence(name, now)
            total += missing * weights.get(name, 1.0)
        return total

    def worth_it(self, store: BeliefStore, weights: dict[str, float] | None = None,
                 seconds_per_point: float = 30.0, now: float | None = None) -> bool:
        """True when the confidence gained is worth the seconds it costs.

        `seconds_per_point` is the exchange rate: how many seconds of doing
        nothing else we are willing to spend to fully refresh one unit-weighted
        fact. It is a policy knob, not a fact about the game.
        """
        return self.value(store, weights, now) * seconds_per_point >= self.cost_s


def choose_observation(observations: list[Observation], store: BeliefStore,
                       weights: dict[str, float] | None = None,
                       seconds_per_point: float = 30.0,
                       now: float | None = None) -> Observation | None:
    """The best-value observation worth running, or None to keep working."""
    candidates = [o for o in observations
                  if o.worth_it(store, weights, seconds_per_point, now)]
    if not candidates:
        return None
    return max(candidates,
               key=lambda o: o.value(store, weights, now) / max(o.cost_s, 1e-6))
