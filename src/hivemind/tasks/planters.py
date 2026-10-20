"""When to harvest a planter.

The interesting version of this question is "is it ever right to harvest before
100%?", and the answer depends on a game mechanic this project has NOT yet
verified: whether repeatedly harvesting a field degrades its yield, and whether
that recovers over roughly 48 hours.

So the model is built with that mechanic behind a switch, and the switch is OFF.

    degradation unverified (default)
        harvest at 100%. This is correct if fields do not degrade, and merely
        leaves a little on the table if they do.

    degradation confirmed
        trade a few percent of growth against keeping the field healthy, which
        is where the real gain is if the mechanic is real.

That asymmetry is the whole point. Turning the feature on before measuring it
would mean the bot harvests early for a benefit that might not exist -- losing
real yield chasing an imagined one. Leaving it off costs at most a few percent.

`scripts/measure_degradation.py` is the experiment that settles it; until its
result is recorded in docs/DESIGN.md 8a, `DEGRADATION_VERIFIED` stays False.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

# Set to True ONLY when the experiment in docs/DESIGN.md 8a has been run and
# recorded. Flipping this without measuring is exactly the mistake it exists to
# prevent.
DEGRADATION_VERIFIED = False

# Used only when DEGRADATION_VERIFIED is True.
HEALTH_FLOOR = 0.50          # below this, replanting the field stops paying
RECOVERY_HOURS = 48.0        # claimed cap on how long a field takes to recover


@dataclass
class PlanterState:
    """What we believe about one planted seed."""
    id: str
    seed: str
    field_name: str
    planted_at: float
    grow_seconds: float
    field_health: float = 1.0
    nectar: str = ""
    base_yield: float = 0.0          # honey at 100% growth on a healthy field

    def growth(self, now: float | None = None) -> float:
        """0..1. Growth is linear in time and caps at full."""
        now = time.time() if now is None else now
        if self.grow_seconds <= 0:
            return 1.0
        return max(0.0, min(1.0, (now - self.planted_at) / self.grow_seconds))

    def ready_at(self) -> float:
        return self.planted_at + self.grow_seconds

    def expected_yield(self, now: float | None = None) -> float:
        """Honey if harvested right now."""
        return self.base_yield * self.growth(now) * self.field_health


@dataclass
class HarvestDecision:
    harvest: bool
    reason: str
    growth: float
    wait_seconds: float = 0.0
    yield_now: float = 0.0
    yield_if_waited: float = 0.0

    @property
    def gain_from_waiting(self) -> float:
        return self.yield_if_waited - self.yield_now


def decide(planter: PlanterState, now: float | None = None,
           degradation_verified: bool | None = None) -> HarvestDecision:
    """Harvest now, or wait?

    Deliberately returns the reasoning, not just a boolean: this decision shows
    up in the GUI's think pane and the user should be able to see why.
    """
    now = time.time() if now is None else now
    verified = (DEGRADATION_VERIFIED if degradation_verified is None
                else degradation_verified)
    growth = planter.growth(now)
    yield_now = planter.expected_yield(now)
    yield_full = planter.base_yield * planter.field_health
    wait = max(0.0, planter.ready_at() - now)

    if growth >= 1.0:
        return HarvestDecision(True, "fully grown", growth, 0.0,
                               yield_now, yield_full)

    if not verified:
        # The conservative branch. Waiting is never wrong when we do not know
        # that waiting costs anything.
        return HarvestDecision(
            False,
            "waiting for 100% — field degradation is unverified, so early "
            "harvesting has no demonstrated benefit",
            growth, wait, yield_now, yield_full)

    # --- only reachable once the mechanic has been measured -----------------
    if planter.field_health < HEALTH_FLOOR:
        return HarvestDecision(
            True,
            f"field at {planter.field_health:.0%} is below the {HEALTH_FLOOR:.0%} "
            "floor; harvesting now and letting it recover beats another cycle",
            growth, wait, yield_now, yield_full)

    if growth >= 0.9 and planter.field_health < 0.75:
        return HarvestDecision(
            True,
            f"{yield_full - yield_now:,.0f} honey more from waiting {wait / 60:.0f}m "
            "does not pay for another degradation tier on a field already at "
            f"{planter.field_health:.0%}",
            growth, wait, yield_now, yield_full)

    return HarvestDecision(False, "growing, field healthy", growth, wait,
                           yield_now, yield_full)


def rank_by_urgency(planters: list[PlanterState],
                    now: float | None = None) -> list[PlanterState]:
    """Ready planters first, then by how soon they will be ready."""
    now = time.time() if now is None else now
    return sorted(planters, key=lambda p: (p.growth(now) < 1.0, p.ready_at()))
