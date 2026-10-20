"""What the hive is, against the blue guide the owner follows, and what to do next.

THE OWNER, 2026-10-01: "the ai should be able to tell whats good bees in my
hive and follow that original blue bee guid and try get me the hive by using
jellys buying even bees and items". act/beemenu reads the hive (types and
counts); this holds it against data/knowledge/blue_hive_plan.yaml (the guide,
quoted) and data/knowledge/items.yaml (Royal Jelly's odds and its rule), and
says, the way the planner says why it picked a field:

  * what the hive is: bees by colour and rarity;
  * where it stands on the guide: the stage its bee count puts it in, and
    that stage's comp (`comp_bees`) against what it has;
  * what the guide says never to run, and which bees are here anyway;
  * what Royal Jelly goes on -- the bees the guide does not want, where a
    roll can only help (items.yaml's rule, the owner's of 2026-10-02) -- how
    many are held, the chance one roll lands a bee the plan wants, and what
    that costs in honey at the Royal Jelly Shop and in tickets at the
    dispenser, beside what Diamond Eggs cost for the same bee;
  * the next hive slot's price (data/knowledge/hive_slots.yaml), the guide's
    other road to its bee count.

Nothing here acts. It reads two files and two counts and returns sentences
and numbers, so it is tested on its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Royal Jelly never gives a Common or an Event bee (items.yaml's chances;
# the wiki's Royal_Jelly module), so a roll's rarity is one of these and its
# type is uniform within the rarity: the wiki's own module draws the rarity,
# then a type of it.
JELLY_RARITIES = ("rare", "epic", "legendary", "mythic")


@dataclass
class Judgement:
    total: int | None = None
    verified: bool = False
    by_colour: dict = field(default_factory=dict)
    by_rarity: dict = field(default_factory=dict)
    stage: int | None = None
    stage_name: str = ""
    comp: dict = field(default_factory=dict)        # bee -> (least, most, have)
    never_run: dict = field(default_factory=dict)   # bee -> count, in the hive
    red: dict = field(default_factory=dict)         # red bees in a blue hive
    jelly_on: dict = field(default_factory=dict)    # bee -> count jelly may go on
    jelly_kept: dict = field(default_factory=dict)  # unwanted, but jelly never rolls it back
    jelly_held: int | None = None
    jelly_hit: float = 0.0       # chance one roll lands a bee the stage wants
    jelly_hits_for: list = field(default_factory=list)
    next_slot: tuple | None = None                  # (bees after, honey)
    # whether the per-type counts were believed (act/beemenu's sum check);
    # without them only the header's total is said, and what follows from it
    rows_known: bool = True
    # THE WAYS TO THE BEES THE STAGE STILL WANTS: (what, cost, chance a use
    # lands one, held) for Royal Jelly and each egg, best chance first
    routes: list = field(default_factory=list)
    tickets: int | None = None
    # WHAT ONE WANTED BEE COSTS BY JELLY (items.yaml's prices): rolls, the
    # honey for them at the Royal Jelly Shop (from a fresh price to the cap),
    # and the tickets at the dispenser; and by each egg, in tickets
    jelly_rolls: float | None = None
    jelly_honey: tuple | None = None
    jelly_tickets: float | None = None
    egg_tickets: dict = field(default_factory=dict)
    # settings eggs.save_diamond (brain/goals.diamond_saved): a Diamond Egg
    # is never hatched for a bee, so its price is said to be a saved egg's
    diamond_saved: bool = True

    def lines(self, labels: dict) -> list[str]:
        """The judgement in sentences, most useful first."""
        def name(k, n=None):
            label = str((labels.get(k) or {}).get("label") or k)
            return label if n is None else f"{n} {label}{'' if n == 1 else 's'}"
        out = []
        if not self.rows_known:
            if self.total is not None:
                out.append(f"the hive: {self.total} bees by the bee menu's own "
                           f"header — which bees they are is not believed yet "
                           f"(the rows' counts did not add up to it)"
                           + (f"; by that count it is the guide's "
                              f"{self.stage_name or f'stage {self.stage}'}"
                              if self.stage is not None else ""))
            if self.next_slot:
                bees, honey = self.next_slot
                out.append(f"the next hive slot (bee {bees}) costs {honey:,} "
                           f"honey at the Mountain Top Shop, plus an egg")
            return out
        if self.total is not None:
            colours = ", ".join(f"{n} {c}" for c, n in sorted(
                self.by_colour.items(), key=lambda kv: -kv[1]))
            out.append(f"the hive: {self.total} bees ({colours})"
                       + ("" if self.verified else
                          " — the rows read do not add up to the header yet"))
        if self.stage is not None and self.comp:
            parts = []
            for bee, (least, most, have) in self.comp.items():
                want = f"{least}" if least == most else f"{least}-{most}"
                parts.append(f"{name(bee)} {have}/{want}")
            short = [b for b, (least, _m, have) in self.comp.items() if have < least]
            out.append(f"the guide's {self.stage_name or f'stage {self.stage}'}: "
                       + ", ".join(parts)
                       + (f" — short of {', '.join(name(b) for b in short)}"
                          if short else " — its comp is in"))
        if self.never_run:
            out.append("the guide says never to run "
                       + ", ".join(name(b, n) for b, n in self.never_run.items())
                       + " (\"A Diamond will always provide more honey for that "
                         "slot\")")
        wants = " or ".join(name(b) for b in self.jelly_hits_for)
        if self.jelly_on:
            held = (f"{self.jelly_held} Royal Jelly held"
                    if self.jelly_held is not None else "Royal Jelly not counted")
            out.append(f"Royal Jelly goes on {', '.join(name(b, n) for b, n in self.jelly_on.items())} "
                       f"— bees the guide does not want, so a roll can only help: "
                       f"it lands {wants or 'a bee the plan wants'} "
                       f"{self.jelly_hit:.2%} of the time and anything else is "
                       f"rolled again; {held}")
        elif self.total is not None:
            out.append("no bee in the hive the guide does not want, so nothing for "
                       "Royal Jelly to go on")
        if self.jelly_kept:
            out.append(f"no jelly on {', '.join(name(b, n) for b, n in self.jelly_kept.items())}: "
                       f"event bees, which Royal Jelly never rolls back")
        if self.jelly_on and self.jelly_rolls:
            bits = [f"about {self.jelly_rolls:,.0f} rolls a {wants}"]
            if self.jelly_honey:
                lo, hi = self.jelly_honey
                bits.append(f"{lo / 1e6:,.0f}-{hi / 1e6:,.0f}M honey at the Royal Jelly "
                            f"Shop by the Pine Tree Forest (250,000 a jelly, rising "
                            f"10,000 a purchase to 1,000,000) — the owner's way, honey "
                            f"being what the hive makes")
            if self.jelly_tickets:
                bits.append(f"or {self.jelly_tickets:,.0f} tickets at the Royal Jelly "
                            f"Dispenser (6 a jelly)")
            eggs = "; ".join(f"{egg} {t:,.0f}"
                             + (" (saved for recipes, never hatched)"
                                if egg == "Diamond Egg" and self.diamond_saved else "")
                             for egg, t in self.egg_tickets.items())
            out.append("by jelly: " + ", ".join(bits)
                       + (f" — against eggs, tickets a {wants}: {eggs} (eggs are not "
                          f"bought: the owner's call, 2026-10-02)" if eggs else ""))
        if self.red:
            out.append("red bees in a blue hive (the guide's rule: rerolled "
                       "out, and last): "
                       + ", ".join(name(b, n) for b, n in self.red.items()))
        if self.next_slot:
            bees, honey = self.next_slot
            out.append(f"the next hive slot (bee {bees}) costs {honey:,} honey at "
                       f"the Mountain Top Shop, plus an egg")
        return out


def stage_for(plan: dict, bees: int | None) -> dict | None:
    """The guide's stage for `bees`: the first whose bee target is above it."""
    stages = list(plan.get("stages") or [])
    if bees is None:
        return None
    for stage in stages:
        targets = [int(item.get("target") or 0) for item in stage.get("progression") or []
                   if (item or {}).get("needs") == "bees"]
        if targets and bees < max(targets):
            return stage
    return stages[-1] if stages else None


def jelly_chance(wanted: list, types: dict, chances: dict) -> float:
    """The chance one Royal Jelly roll lands one of `wanted`: its rarity's
    chance over that rarity's number of types, summed."""
    per = {r: sum(1 for v in types.values() if v.get("rarity") == r)
           for r in JELLY_RARITIES}
    hit = 0.0
    for bee in wanted:
        rarity = (types.get(bee) or {}).get("rarity")
        if rarity in per and per[rarity]:
            hit += float(chances.get(rarity) or 0.0) / per[rarity]
    return hit


def routes_to(wanted: list, types: dict, items: dict, *,
              jelly_held: int | None = None, tickets: int | None = None,
              jelly_ok: bool = False) -> list:
    """(what, cost, chance one use lands one of `wanted`, held) for every egg
    priced in tickets -- and Royal Jelly when `jelly_ok`, a Basic bee there to
    put it on (items.yaml's rule) -- best chance first."""
    out = []
    rj = (items.get("royal_jelly") or {}).get("chances") or {}
    if rj and jelly_ok:
        out.append(("Royal Jelly", "a jelly", jelly_chance(wanted, types, rj), jelly_held))
    for key, egg in ((items.get("eggs") or {}).items()):
        if not isinstance(egg, dict) or not egg.get("tickets"):
            continue
        chance = jelly_chance(wanted, types, egg.get("chances") or {})
        if chance > 0:
            out.append((key.replace("_", " ").title(), f"{int(egg['tickets']):,} tickets",
                        chance, tickets))
    return sorted(out, key=lambda r: -r[2])


def jelly_honey(rolls: float, prices: dict) -> tuple | None:
    """(from a fresh price, all at the cap): the honey for `rolls` Royal Jelly
    at the Royal Jelly Shop (items.yaml `prices.royal_jelly_shop`). How many
    the account has bought -- where the price stands -- is not read yet."""
    shop = prices.get("royal_jelly_shop") or {}
    try:
        start = float(shop["honey_from"])
        step = float(shop["honey_step"])
        cap = float(shop["honey_cap"])
    except (KeyError, TypeError, ValueError):
        return None
    n = max(0, int(round(rolls)))
    fresh = sum(min(start + step * k, cap) for k in range(n))
    return fresh, n * cap


def judge(bees: dict, total: int | None, *, types: dict, plan: dict,
          items: dict, verified: bool = False, jelly_held: int | None = None,
          slots: dict | None = None, rows_known: bool = True,
          tickets: int | None = None) -> Judgement:
    """`bees` {type: count} from act/beemenu; `types` bee_types.yaml's;
    `plan` blue_hive_plan.yaml; `items` items.yaml; `slots` hive_slots.yaml's
    {bees: honey} for the slot that brings the hive to that many."""
    out = Judgement(total=total, verified=verified, jelly_held=jelly_held,
                    rows_known=rows_known)
    for bee, n in bees.items():
        info = types.get(bee) or {}
        out.by_colour[info.get("colour", "unknown")] = out.by_colour.get(
            info.get("colour", "unknown"), 0) + int(n)
        out.by_rarity[info.get("rarity", "unknown")] = out.by_rarity.get(
            info.get("rarity", "unknown"), 0) + int(n)
    count = total if total is not None else (sum(bees.values()) or None)
    stage = stage_for(plan, count)
    if stage is not None:
        out.stage = int(stage.get("id") or 0)
        out.stage_name = str(stage.get("name") or "")
        for bee, (least, most) in (stage.get("comp_bees") or {}).items():
            out.comp[bee] = (int(least), int(most), int(bees.get(bee, 0)))
    for bee in plan.get("never_run") or []:
        if bees.get(bee):
            out.never_run[bee] = int(bees[bee])
    for bee, n in sorted(bees.items()):
        if (types.get(bee) or {}).get("colour") == "red" and bee not in out.never_run:
            out.red[bee] = int(n)
    # ROYAL JELLY GOES ON THE BEES THE GUIDE DOES NOT WANT (items.yaml's
    # rule). THE OWNER, 2026-10-02: "diamond eggs arnt worth it it should buy
    # roysal jellys with honey instead". A roll's odds are the same whatever
    # the bee is, so on a bee the plan wants it is a 70% chance of worse --
    # but on one it does not (never-run, a red bee in a blue hive, a Basic)
    # it can only help: it lands a wanted bee, or another unwanted one that is
    # rolled again. Never a bee the stage's comp counts.
    #
    # NEVER AN EVENT BEE (2026-10-02). Royal Jelly rolls rare to mythic bees
    # and never an event bee back, and a roll's odds are the same on any cell
    # -- so a cell of a Demon or a Riley does everything a Cobalt's would, and
    # loses nothing that cannot be had again. The owner holds a Cobalt and a
    # Crimson Bee Jelly (inventory 2026-10-02), the only way back to one.
    #
    # EXCEPT THE EVENT BEES THE OWNER NAMED (blue_hive_plan.yaml
    # `jelly_event_ok`). THE OWNER, 2026-10-21, YES to "use Royal Jelly to swap
    # the Basic, Crimson and Cobalt bees for blue ones".
    #
    # THE ORDER THE ROLLS GO IN (jelly_on's order, run_farm's targets): Basic
    # first, then the red and colourless misfits, then the blue ones (Cobalt)
    # last -- a blue misfit at least helps a blue hive while it waits.
    wanted_by_comp = set(out.comp)
    event_ok = set(plan.get("jelly_event_ok") or ())
    colour_rank = {"blue": 1}
    misfits = set(out.never_run) | set(out.red) | ({"basic"} if bees.get("basic") else set())
    for bee in sorted(misfits, key=lambda b: (b != "basic", colour_rank.get(
            (types.get(b) or {}).get("colour"), 0), b)):
        if bee in wanted_by_comp or not bees.get(bee):
            continue
        if (types.get(bee) or {}).get("rarity") == "event" and bee not in event_ok:
            out.jelly_kept[bee] = int(bees[bee])
        else:
            out.jelly_on[bee] = int(bees[bee])
    # WHAT A ROLL IS FOR: the stage's comp where it is short, then the
    # guide's standing want (blue_hive_plan.yaml `jelly_targets`: "push to add
    # as many Diamonds as possible").
    short = [b for b, (least, _m, have) in out.comp.items() if have < least]
    out.jelly_hits_for = short + [b for b in (plan.get("jelly_targets") or [])
                                  if b not in short]
    rj = items.get("royal_jelly") or {}
    out.jelly_hit = jelly_chance(out.jelly_hits_for, types, rj.get("chances") or {})
    out.tickets = tickets
    if out.jelly_hits_for:
        out.routes = routes_to(out.jelly_hits_for, types, items,
                               jelly_held=jelly_held, tickets=tickets,
                               jelly_ok=bool(out.jelly_on))
    if out.jelly_on and out.jelly_hit > 0:
        out.jelly_rolls = 1.0 / out.jelly_hit
        prices = rj.get("prices") or {}
        out.jelly_honey = jelly_honey(out.jelly_rolls, prices)
        per = (prices.get("dispenser") or {}).get("tickets")
        if per:
            out.jelly_tickets = float(per) * out.jelly_rolls
        for what, cost, chance, _held in out.routes:
            if what != "Royal Jelly" and chance > 0:
                try:
                    out.egg_tickets[what] = float(cost.split()[0].replace(",", "")) / chance
                except (ValueError, IndexError):
                    pass
    if slots and count is not None and count < 50:
        honey = slots.get(count + 1)
        if honey:
            out.next_slot = (count + 1, int(honey))
    return out


def keep_roll(bee: str | None, rarity: str, colour: str, gifted: bool, *,
              hits=(), never_run=()) -> str:
    """Why the bee a Royal Jelly roll just landed is KEPT (the rolls stop on
    it), or "" to roll on. THE OWNER, 2026-10-21, a blue hive: swap the
    misfits "for blue ones". Kept: a wanted bee (`hits`, the stage's comp and
    the guide's `jelly_targets`), a Mythic, a gifted bee, any Legendary or
    Event bee, or a blue Epic -- Bubble or better (Bubble is the guide's
    blue fill, Stage 1 comp 13-14). Never kept: a bee judge() would put the
    jelly straight back on -- the guide's never-run list or a red bee --
    unless it is gifted or a Mythic."""
    if bee is None:
        return ""
    if bee in hits:
        return f"rolled the wanted {bee}"
    if rarity == "mythic":
        return f"rolled a Mythic, the {bee}"
    if gifted:
        return f"rolled a gifted {bee}"
    if bee in set(never_run) or colour == "red":
        return ""
    if rarity in ("legendary", "event"):
        return f"rolled a {rarity}, the {bee}"
    if colour == "blue" and rarity == "epic":
        return f"rolled a blue epic, the {bee} (Bubble or better)"
    return ""


def unmissed(targets, state: dict, now: float, rest: float) -> list:
    """The jelly targets no scan missed within `rest` seconds (state is
    var/jelly.json: `missed` {bee: at}; the older single `missed_at` stands
    for every bee without its own). MEASURED 2026-10-20 15:07-18:06 (runs
    1101-1116): one stamp for the whole list, reset whenever the judged list
    changed, let a scan for an absent Rad Bee run every ~15 min."""
    missed = state.get("missed") or {}
    old = float(state.get("missed_at") or 0)
    return [b for b in targets if now - float(missed.get(b, old) or 0) >= rest]
