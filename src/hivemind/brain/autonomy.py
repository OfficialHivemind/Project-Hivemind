"""Deciding whether to decide: the autonomy gate and the irreversibility firewall.

The owner's request was "a option to toggle where the ai can ask me what paths i
want to take and if thats off then it chooses for me". This is that toggle, and
it turned out to have more structure than a checkbox.

Three modes, because "ask me" is not one behaviour:

    AUTOPILOT       decides everything, never interrupts
    ASK_STRATEGY    asks about builds and large spends, handles the rest alone
    ASK_NOTABLE     asks before anything irreversible or expensive

But the mode is only half of it. There is a second, independent gate that
applies in EVERY mode including autopilot:

**The irreversibility firewall.** An action that cannot be undone may not run on
a belief the bot is not confident in. Spending 3,333 royal jelly on a
forty-minute-old inventory reading is the exact failure this project keeps
guarding against, and no autonomy setting should be able to permit it. In
autopilot a stale belief does not produce a question -- it produces an
OBSERVATION: go and look, then decide. That keeps the promise of never
interrupting while refusing to act blind.

So a proposal resolves to one of four outcomes:

    ACT       do it now
    OBSERVE   go and refresh a belief first, then re-propose
    ASK       hand it to the owner with the numbers
    REFUSE    the option is not permitted at all (a locked setting)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..telemetry.events import Autonomy, Option
from ..world.beliefs import BeliefStore


class Outcome(str, Enum):
    ACT = "act"
    OBSERVE = "observe"
    ASK = "ask"
    REFUSE = "refuse"


@dataclass
class Proposal:
    """Something the planner wants to do, with everything needed to judge it."""
    question: str
    options: list[Option]
    chosen: str
    reversible: bool = True
    cost_honey: float = 0.0
    strategic: bool = False          # a build/direction choice, not a chore
    depends_on: tuple[str, ...] = ()  # beliefs this relies on being accurate
    context: str = ""

    @property
    def best(self) -> Option | None:
        return max(self.options, key=lambda o: o.score) if self.options else None


@dataclass
class Ruling:
    outcome: Outcome
    reason: str
    proposal: Proposal
    observe: tuple[str, ...] = ()     # beliefs to refresh, when OBSERVE
    chosen: str = ""

    @property
    def acted(self) -> bool:
        return self.outcome is Outcome.ACT


@dataclass
class Arbiter:
    """Applies the autonomy mode and the firewall to each proposal."""

    beliefs: BeliefStore
    mode: Autonomy = Autonomy.ASK_STRATEGY
    max_spend: float = 5_000_000.0
    min_confidence: float = 0.9
    # Settings that lock an action out entirely, whatever the mode says.
    forbidden: set[str] = field(default_factory=set)

    def judge(self, proposal: Proposal, now: float | None = None) -> Ruling:
        if proposal.chosen in self.forbidden:
            return Ruling(Outcome.REFUSE,
                          f"{proposal.chosen!r} is switched off in settings",
                          proposal)

        # --- the firewall, applied in every mode including autopilot -------
        if not proposal.reversible and proposal.depends_on:
            stale = tuple(name for name in proposal.depends_on
                          if self.beliefs.confidence(name, now) < self.min_confidence)
            if stale:
                return Ruling(
                    Outcome.OBSERVE,
                    "irreversible, and " + ", ".join(stale) +
                    f" {'is' if len(stale) == 1 else 'are'} below "
                    f"{self.min_confidence:.0%} confidence — looking first",
                    proposal, observe=stale)

        # --- the mode -----------------------------------------------------
        if self.mode is Autonomy.AUTOPILOT:
            return Ruling(Outcome.ACT, "autopilot", proposal, chosen=proposal.chosen)

        expensive = proposal.cost_honey > self.max_spend

        if self.mode is Autonomy.ASK_STRATEGY:
            if proposal.strategic:
                return Ruling(Outcome.ASK, "a strategy choice", proposal)
            if expensive:
                return Ruling(Outcome.ASK,
                              f"costs {proposal.cost_honey:,.0f}, above your "
                              f"{self.max_spend:,.0f} limit", proposal)
            return Ruling(Outcome.ACT, "routine", proposal, chosen=proposal.chosen)

        # ASK_NOTABLE
        if not proposal.reversible:
            return Ruling(Outcome.ASK, "cannot be undone", proposal)
        if proposal.strategic:
            return Ruling(Outcome.ASK, "a strategy choice", proposal)
        if expensive:
            return Ruling(Outcome.ASK,
                          f"costs {proposal.cost_honey:,.0f}, above your "
                          f"{self.max_spend:,.0f} limit", proposal)
        return Ruling(Outcome.ACT, "routine and reversible", proposal,
                      chosen=proposal.chosen)

    def apply_settings(self, settings) -> "Arbiter":
        """Take mode and limits from the shared settings schema."""
        raw = str(settings.get("autonomy.mode", "ask_strategy"))
        try:
            self.mode = Autonomy(raw)
        except ValueError:
            self.mode = Autonomy.ASK_STRATEGY
        self.max_spend = float(settings.int("autonomy.max_spend"))
        self.min_confidence = float(settings.float("autonomy.min_confidence"))

        # Settings that switch a whole behaviour off become refusals.
        locks = {
            "economy.wind_shrine": "offer at the Wind Shrine",
            "combat.vicious": "engage the Vicious Bee",
            "economy.early_harvest": "harvest early",
        }
        self.forbidden = {label for key, label in locks.items()
                          if not settings.bool(key)}
        return self
