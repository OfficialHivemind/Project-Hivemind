"""What each purchase is worth: payback time, cost / honey-an-hour gained.

THE OWNER, 2026-10-20: progress felt slow. The plan (brain/goals)
buys in THEIR order -- the guides' order they approved -- and never says what a
purchase returns. This says it, for every purchase the account could make
next: the open gear goals, the next hive slot, a Basic Egg for a slot standing
empty. LOOK-ONLY: it buys, clicks and changes nothing; scripts/progress_report
and anyone else may print it.

  cost   = the honey price (goals.yaml / hive_slots.yaml, the wiki's)
         + the Royal Jelly its short materials take in the Blender, bought at
           buyer.JELLY_PRICE_PLANNED (the Royal Jelly Shop's cap: an ASSUMPTION
           that can only be too high) -- the same recipe reading the Blender
           errand makes (buyer.crafting_from_files), with the materials held
           counted for THIS item alone, not after the goals above it;
         + anything nothing prices in honey (Glitter's Moon Charms and Magic
           Beans, Diamond Eggs, Stingers, a vial) is named, and the cost is
           then a floor ("at least").
  gain   = a percentage of the bot's MEASURED honey/h (goals.balance_rate),
           low / central / high from data/knowledge/gains.yaml, each with the
           research it came from. No entry there: "unknown", ranked apart.
  payback = cost / gain, in hours of farming at the measured rate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

from . import goals as goals_mod
from .buyer import JELLY_PRICE_PLANNED, crafting_from_files

# A BASIC EGG, when none is held to hatch into the new slot: 10,000,000 honey,
# MEASURED -- var/purchases.json, "Basic Egg | 10.000.000 Honey" bought ok
# 2026-10-15 (the shop's price rises from 1,000 to this cap, items research).
BASIC_EGG_HONEY = 10_000_000
SLOT_KEY = "hive_slot"


def load_gains(path: str | Path | None = None) -> dict:
    """data/knowledge/gains.yaml: {"gains": {key: {low, central, high, vs, why}},
    "source": ...}, or {} when it cannot be read."""
    import yaml
    if path is None:
        from ..datapaths import data
        path = data("knowledge", "gains.yaml")
    try:
        body = yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return body if isinstance(body, dict) else {}


def _gain_for(key: str, gains: dict):
    """(low, central, high, note) in % for a goal key, or None."""
    table = gains.get("gains") or {}
    g = table.get(key) or (table.get(SLOT_KEY) if key.startswith(SLOT_KEY) else None)
    if not g or g.get("low") is None or g.get("high") is None:
        return None
    lo, hi = float(g["low"]), float(g["high"])
    mid = g.get("central")
    note = f"vs {g.get('vs')}: {g.get('why')}" if g.get("vs") else str(g.get("why") or "")
    if mid is None:
        mid = (lo + hi) / 2
        note += " (central = the range's midpoint, an assumption)"
    return lo, float(mid), hi, note


@dataclass
class Option:
    key: str
    label: str
    honey: int = 0                 # the price itself
    jelly: int = 0                 # Royal Jelly to buy for its Blender crafts
    unpriced: list = field(default_factory=list)   # short, and no honey figure for them
    gain: tuple | None = None      # (low, central, high) % of the honey rate
    gain_note: str = ""
    rate: float | None = None      # the measured honey/h it is a share of
    blocked: str = ""              # what stands in the way of buying it at all
    plan_next: bool = False

    @property
    def cost(self) -> int:
        return self.honey + self.jelly * JELLY_PRICE_PLANNED

    @property
    def per_hour(self) -> float | None:
        if self.gain is None or not self.rate:
            return None
        return self.gain[1] / 100.0 * self.rate

    def payback(self, which: int = 1) -> float | None:
        """Hours to earn its cost back: 0 low gain, 1 central, 2 high."""
        if self.gain is None or not self.rate or self.gain[which] <= 0:
            return None
        return self.cost / (self.gain[which] / 100.0 * self.rate)

    def sort_key(self) -> float:
        """Payback hours; without a rate, cost per % (the same order)."""
        if self.gain is None:
            return float(self.cost)
        return self.payback() if self.rate else self.cost / max(self.gain[1], 1e-9)

    def brief(self) -> str:
        """The short line, for Telegram: "Cobalt Guard: ~21.1 h payback,
        +9.48M/h for >=200M (short: 232 moon charm)"."""
        pay = self.payback()
        cost = ("≥" if self.unpriced else "") + _short(self.cost)
        out = (f"{self.label}: ~{goals_mod.hours_text(pay)} payback, "
               f"+{_short(self.per_hour)}/h (+{self.gain[1]:g}%) for {cost} honey"
               if pay is not None else f"{self.label}: {cost} honey, gain "
               + (f"+{self.gain[1]:g}%" if self.gain else "unknown"))
        if self.unpriced:
            out += f" (short: {', '.join(self.unpriced[:2])})"
        return out

    def reason(self) -> str:
        """One line: payback, gain and its source, cost, and what is short."""
        floor = "at least " if self.unpriced else ""
        cost = f"{floor}{_short(self.cost)} honey" + (
            f" ({_short(self.honey)} + {self.jelly:,} Royal Jelly at "
            f"{_short(JELLY_PRICE_PLANNED)} each)" if self.jelly else "")
        if self.gain is None:
            head = f"{self.label}: gain unknown (no estimate in gains.yaml); costs {cost}"
        else:
            lo, mid, hi = self.gain
            pay = self.payback()
            head = (f"{self.label}: "
                    + (f"pays back in ~{goals_mod.hours_text(pay)} "
                       f"({goals_mod.hours_text(self.payback(2))}-"
                       f"{goals_mod.hours_text(self.payback(0))}); "
                       if pay is not None else "no honey rate measured; ")
                    + f"+{mid:g}% ({lo:g}-{hi:g}%)"
                    + (f" = +{_short(self.per_hour)}/h" if self.per_hour else "")
                    + f" {self.gain_note} [research 2026-10-13]; costs {cost}")
        if self.unpriced:
            head += "; not priced in honey: " + ", ".join(self.unpriced)
        if self.blocked:
            head += f"; {self.blocked}"
        return head


def _short(n) -> str:
    n = float(n or 0)
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= size:
            return f"{n / size:.3g}{unit}"
    return f"{n:.0f}"


def _alone(row, held: dict):
    """`row` with each material's count as held, for THIS item alone (the
    plan's counts are what the goals above it leave)."""
    needs = [replace(n, have=held.get(n.material)) for n in row.needs]
    return replace(row, needs=needs)


def option_for(row, held: dict, gains: dict, rate: float | None,
               crafting=crafting_from_files) -> Option:
    """One open plan row as an Option. `held` is {material: count} (the
    inventory read; a material it has not counted is absent: unknown)."""
    alone = _alone(row, held)
    opt = Option(key=row.key, label=row.label, honey=int(row.cost or 0), rate=rate)
    got = _gain_for(row.key, gains)
    if got:
        opt.gain, opt.gain_note = got[:3], got[3]
    missing = list(alone.missing)
    if missing:
        made = crafting(SimpleNamespace(rows=[alone]), held)
        crafted = {label for label, _n in (made.crafts if made else ())}
        if made is not None:
            opt.jelly = max(0, made.jelly - int(held.get("royal_jelly") or 0))
            opt.unpriced += [f"{n:,} {s.replace('_', ' ')}" for s, n in made.lacking.items()]
        opt.unpriced += [f"{n.label} {'?' if n.have is None else f'{n.have:,}'}/{n.need:,}"
                         for n in missing if n.label not in crafted]
    if row.key.startswith(SLOT_KEY) and int(held.get("basic_egg") or 0) < 1:
        opt.honey += BASIC_EGG_HONEY
        opt.gain_note += f"; +{_short(BASIC_EGG_HONEY)} for the Basic Egg to fill it"
    if getattr(row, "gate_ok", None) is False:
        opt.blocked = f"blocked: {row.gate}"
    elif getattr(row, "waits", ""):
        opt.blocked = f"waits: {row.waits}"
    return opt


@dataclass
class Ranking:
    known: list = field(default_factory=list)      # by payback, best first
    unknown: list = field(default_factory=list)    # no gain estimate, cheapest first
    plan_next: Option | None = None
    rate_text: str = ""
    why_differ: str = ""

    @property
    def pick(self) -> Option | None:
        return self.known[0] if self.known else None

    def lines(self, top: int = 0) -> list[str]:
        known = self.known[:top] if top else self.known
        return [f"{i}. {o.reason()}" for i, o in enumerate(known, 1)]

    def text(self, top: int = 5) -> str:
        out = [f"What I'd buy next, by payback (cost ÷ honey/h gained; {self.rate_text}):"]
        out += self.lines(top) or ["(nothing with a gain estimate is open)"]
        if self.unknown:
            out.append("No gain estimate, so not ranked: "
                       + "; ".join(f"{o.label} ({_short(o.cost)}"
                                   + (" + materials" if o.unpriced else "") + ")"
                                   for o in self.unknown))
        if self.why_differ:
            out.append(self.why_differ)
        out.append("Gains are upper estimates (research 2026-10-13, bag honey only); "
                   f"Royal Jelly priced at the {_short(JELLY_PRICE_PLANNED)} cap.")
        # PRO RULES 19-20 (round 2): what this ranking cannot see
        from .protips import EFFICIENCY_NOTE
        out.append(EFFICIENCY_NOTE)
        return "\n".join(out)


def _explain(pick: Option | None, nxt: Option | None, known: list,
             order_from: str) -> str:
    if nxt is None:
        return "The plan has no open goal."
    if pick is None:
        return f"The plan's next goal is the {nxt.label}; nothing open has a gain estimate."
    if pick.key == nxt.key:
        return f"The plan's next goal is the same: the {nxt.label}."
    rank = next((i for i, o in enumerate(known, 1) if o.key == nxt.key), None)
    why = (f"The plan's next goal is the {nxt.label}, not the {pick.label}: the plan "
           f"follows {order_from}, not payback")
    if rank is None:
        why += f", and the {nxt.label} has no gain estimate"
    else:
        pay = nxt.payback()
        why += (f" (the {nxt.label} ranks {rank} by payback"
                + (f", ~{goals_mod.hours_text(pay)}" if pay is not None else "") + ")")
    if pick.unpriced or pick.blocked:
        why += (f"; the {pick.label} also cannot be bought yet ("
                + "; ".join(([f"short: {', '.join(pick.unpriced)}"] if pick.unpriced else [])
                            + ([pick.blocked] if pick.blocked else [])) + ")")
    return why + "."


def rank(plan, held: dict, gains: dict, *, empty_slots: int = 0,
         order_from: str = "the goal order", crafting=crafting_from_files) -> Ranking:
    """Every open goal of `plan` (brain/goals.Plan), plus a Basic Egg for each
    slot standing empty, ranked by payback. Pure but for the recipe files
    `crafting` reads."""
    rate = plan.rate.per_hour if getattr(plan, "rate", None) else None
    opts = [option_for(r, held, gains, rate, crafting) for r in plan.rows if not r.owned]
    if empty_slots > 0:
        egg = Option(key="basic_egg", label=f"Basic Egg for the empty slot{'s' if empty_slots > 1 else ''}",
                     honey=0 if int(held.get("basic_egg") or 0) else BASIC_EGG_HONEY, rate=rate)
        got = _gain_for(SLOT_KEY, gains)
        if got:
            egg.gain, egg.gain_note = got[:3], got[3]
        opts.append(egg)
    first = plan.first_open() if hasattr(plan, "first_open") else None
    nxt = next((o for o in opts if first is not None and o.key == first.key), None)
    if nxt is not None:
        nxt.plan_next = True
    known = sorted((o for o in opts if o.gain is not None), key=Option.sort_key)
    unknown = sorted((o for o in opts if o.gain is None), key=lambda o: o.cost)
    out = Ranking(known=known, unknown=unknown, plan_next=nxt,
                  rate_text=(f"honey/h measured {_short(rate)}" if rate
                             else "no honey rate measured yet, ranked by cost per %"))
    out.why_differ = _explain(out.pick, nxt, known, order_from)
    return out


def from_files(var_root, settings=None, plan=None, gains: dict | None = None) -> Ranking:
    """The ranking for the live account: brain/goals' own plan and the last
    inventory read. Reads, never writes."""
    from . import owned as owned_mod
    var_root = Path(var_root)
    if settings is None:
        from ..world.settings import Settings
        settings = Settings()
    plan = plan or goals_mod.from_files(var_root=var_root, settings=settings)
    held, _where = owned_mod.inventory(var_root)
    try:
        bees = int(json.loads((var_root / "bees.json").read_text()).get("total") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        bees = 0
    empty = max(0, goals_mod.slots_bought(var_root) - bees) if bees else 0
    order_from = ("your order in Settings > Goals" if (settings.get("goals.order") or "").strip()
                  else "goals.yaml's default order (the guides' order, approved 2026-10-13)")
    return rank(plan, held, load_gains() if gains is None else gains,
                empty_slots=empty, order_from=order_from)
