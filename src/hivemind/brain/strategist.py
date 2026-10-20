"""G5 long-term strategist: a weeks-ahead plan of what to buy next, when, and why.

LOOK-ONLY: it buys, clicks and changes nothing. It walks brain/roi's ranking
(the open goals and progression goals of brain/goals' plan, by payback) on a
clock of FARMING hours at the bot's MEASURED honey/h (goals.balance_rate):

  - each purchase whose honey is the only thing short is scheduled when the
    bank reaches its cost; the rate then grows by the gain's CENTRAL estimate
    (data/knowledge/gains.yaml, research, ESTIMATED -- an upper estimate), so
    later ETAs are ESTIMATED too and say so;
  - a purchase that is short of materials nothing prices in honey, or blocked /
    waiting (a quest, a bee gate), is listed under "first" with what stands in
    the way -- no ETA is guessed for it;
  - a purchase with no gain estimate is listed apart, never ranked.

Days are FARMING hours / hours_per_day; hours_per_day is the caller's figure
(24 = run around the clock), not a measured uptime.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import goals as goals_mod
from .roi import _short

HORIZON_HOURS = 24 * 14          # two weeks of farming


@dataclass
class Step:
    label: str
    at_hours: float              # farming hours from now when it is bought
    rate_after: float            # honey/h after it (ESTIMATED from the gain)
    why: str


@dataclass
class Strategy:
    steps: list = field(default_factory=list)
    first: list = field(default_factory=list)     # (label, what stands in the way)
    unranked: list = field(default_factory=list)  # labels with no gain estimate
    beyond: list = field(default_factory=list)    # buyable, past the horizon
    rate: float | None = None
    note: str = ""

    def text(self, hours_per_day: float = 24.0) -> str:
        if not self.rate:
            return "Strategist: no honey rate measured yet, so no timeline."
        out = [f"Strategist (look-only), from the measured {_short(self.rate)}/h; "
               "ETAs after the first are ESTIMATED (gains from gains.yaml):"]
        for i, s in enumerate(self.steps, 1):
            day = s.at_hours / hours_per_day
            out.append(f"{i}. day {day:.1f} ({goals_mod.hours_text(s.at_hours)} farming): "
                       f"{s.label} -> ~{_short(s.rate_after)}/h. {s.why}")
        if not self.steps:
            out.append("(nothing buyable with honey alone fits the horizon)")
        if self.beyond:
            out.append("Later: " + ", ".join(self.beyond))
        if self.first:
            out.append("Needs something first: "
                       + "; ".join(f"{l} ({w})" for l, w in self.first))
        if self.unranked:
            out.append("No gain estimate, not ranked: " + ", ".join(self.unranked))
        return "\n".join(out)


def plan(ranking, honey: int | None, horizon_hours: float = HORIZON_HOURS) -> Strategy:
    """The timeline over a brain/roi.Ranking from `honey` banked now. Pure."""
    rate = ranking.known[0].rate if ranking.known else None
    out = Strategy(rate=rate, unranked=[o.label for o in ranking.unknown])
    bank, t, now_rate = float(honey or 0), 0.0, rate
    for opt in ranking.known:
        if opt.unpriced or opt.blocked:
            out.first.append((opt.label, "; ".join(
                ([f"short: {', '.join(opt.unpriced)}"] if opt.unpriced else [])
                + ([opt.blocked] if opt.blocked else []))))
            continue
        if not now_rate:
            continue
        # MULTIPLICATIVE: every gain is a % of the rate, so payback order holds
        # as the rate grows; ponytail: no material-farming time is modelled
        wait = max(0.0, opt.cost - bank) / now_rate
        if t + wait > horizon_hours:
            out.beyond.append(opt.label)
            continue
        t += wait
        bank += wait * now_rate - opt.cost
        now_rate *= 1 + opt.gain[1] / 100.0
        out.steps.append(Step(opt.label, t, now_rate, opt.reason()))
    return out


def from_files(var_root, settings=None, horizon_hours: float = HORIZON_HOURS) -> Strategy:
    """The strategy for the live account. Reads, never writes."""
    from . import roi
    goal_plan = goals_mod.from_files(var_root=var_root, settings=settings)
    return plan(roi.from_files(var_root, settings, plan=goal_plan),
                goal_plan.honey, horizon_hours)
