"""One order that reaches SEVERAL one-click targets fastest (ROADMAP G12).

THE OWNER, 2026-10-26: options for an automatic Fuzzy alt and Tad alt, or a
hybrid that picks the fastest way to all of it.

The targets are data/knowledge/progression/alt_goals.yaml (Fuzzy alt, Tad alt,
Tide Popper, Diamond Mask, Supreme Star Amulet). `merge` takes any of them and
gives one list of steps:

  * SHARED ONCE. A step two targets both name (the Porcelain Dipper, the
    Supreme Star Amulet) is in the list once, "for" both. Hive slots are one
    step to the biggest `hive_size`. Mythic Eggs are one step for every wanted
    Mythic type together: one egg is any of the six, so 18 Tadpoles and 13
    Fuzzies cost about 6 x 18 eggs, not 6 x 31.
  * THE HIVE HOLDS 50. Wanted bees over that are cut down in proportion and
    the plan says so.
  * CHEAPEST FIRST WHERE ORDER IS FREE. Only `after:` / a `requires` naming
    another step's id ties two steps; among the free ones the cheapest in honey
    goes first (tickets priced as brain/value.PRICES).
  * ETA FROM MEASURED RATES ONLY. Honey from session_goals.rates_from_files
    (the benchmark, else the trips), tickets and materials from the inventory's
    own reads (goals.material_rates). Each step's ETA is when the slowest input
    of everything up to it is in; an input with no rate is named, never guessed.

Nothing here buys, walks or clicks: it decides an order and says it.
"""
from __future__ import annotations

import heapq
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import progression as prog

FILE = ("knowledge", "progression", "alt_goals.yaml")
# MEASURED (alt_goals.yaml w_slots, the wiki's Hive Slot page): 25 free, 50 at most.
HIVE_MAX = 50
HIVE_FREE = 25
EGGS_ID = "mythic_eggs"


def load() -> dict:
    """alt_goals.yaml, or {} when it cannot be read."""
    import yaml
    from ..datapaths import data
    try:
        body = yaml.safe_load(data(*FILE).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return body if isinstance(body, dict) else {}


def targets(data: dict | None = None) -> dict:
    """{target id: target} in file order."""
    data = load() if data is None else data
    return {str(t["id"]): t for t in data.get("targets") or [] if isinstance(t, dict) and t.get("id")}


def _find(gid: str, hive: str) -> dict | None:
    """A progression goal by id: the target's hive first, then the others."""
    for h in dict.fromkeys((hive,) + prog.HIVES):
        for _i, goal in prog._goals(prog.load(h)):
            if str(goal.get("id")) == gid:
                return goal
    return None


def _slot_honey(have: int, want: int) -> int:
    """Honey for the slots that take a hive from `have` to `want` bees
    (hive_slots.yaml, the wiki's table)."""
    from .knowledge import _load
    table = _load("hive_slots.yaml").get("honey_for_bees") or {}
    return int(sum(int(table.get(n) or 0) for n in range(max(have, HIVE_FREE) + 1, want + 1)))


def steps(target_id: str, data: dict | None = None) -> list:
    """The target's gear / quest steps as goal dicts, `ref`s filled in from
    the progression files. A ref that is in no file is left out."""
    tgt = targets(data).get(target_id) or {}
    hive = str(tgt.get("hive") or prog.DEFAULT_HIVE)
    out = []
    for raw in tgt.get("steps") or []:
        if raw.get("ref"):
            base = _find(str(raw["ref"]), hive)
            if base is None:
                continue
            goal = dict(base, **{k: v for k, v in raw.items() if k != "ref"})
        else:
            goal = dict(raw)
        out.append(goal)
    return out


# ---- the plan ---------------------------------------------------------------
@dataclass
class Step:
    id: str
    label: str
    cost: dict                      # {"honey": n, "tickets": n, "items": {slug: n}}
    targets: list = field(default_factory=list)
    after: set = field(default_factory=set)
    why: str = ""
    done: str = ""                  # why it needs nothing more, "" while open
    eta_h: float | None = None      # hours from now until it can be had
    waits_on: list = field(default_factory=list)   # inputs with no measured rate

    def price(self) -> float:
        """Honey worth, for the cheapest-first order only."""
        from .value import PRICES
        return float(self.cost.get("honey") or 0) + PRICES["ticket"] * float(self.cost.get("tickets") or 0)


@dataclass
class Plan:
    targets: list
    steps: list
    notes: list = field(default_factory=list)

    @property
    def open(self) -> list:
        return [s for s in self.steps if not s.done]

    @property
    def eta_h(self) -> float | None:
        last = self.open[-1:] or [None]
        return 0.0 if last[0] is None else last[0].eta_h

    def say(self) -> str:
        """Plain words, one step a line."""
        from .goals import hours_text
        from .session_goals import short_number
        names = ", ".join(self.targets)
        lines = [f"Plan for: {names}"] + [f"Note: {n}" for n in self.notes]
        for i, s in enumerate(self.open, 1):
            cost = [f"{short_number(s.cost[k])} {k}" for k in ("honey", "tickets") if s.cost.get(k)]
            cost += [f"{n:,} {k.replace('_', ' ')}" for k, n in (s.cost.get("items") or {}).items()]
            more = f" and {len(s.waits_on) - 3} more" if len(s.waits_on) > 3 else ""
            when = (f"in about {hours_text(s.eta_h)}" if s.eta_h is not None
                    else "time not known yet (not measured: " + ", ".join(s.waits_on[:3]) + more + ")")
            lines.append(f"{i}. {s.label} (for {', '.join(s.targets)})"
                         + (f" - {', '.join(cost)}" if cost else "") + f" - {when}")
        if not self.open:
            lines.append("Everything is done.")
        return "\n".join(lines)


def _bee_counts(tgts: list, notes: list) -> tuple[dict, dict]:
    """(wanted bees by type, wanted gifted by type), cut to fit HIVE_MAX."""
    want: dict = {}
    gifted: dict = {}
    for t in tgts:
        for bee, n in (t.get("bees") or {}).items():
            want[bee] = max(want.get(bee, 0), int(n))
        for bee, n in (t.get("gifted") or {}).items():
            gifted[bee] = max(gifted.get(bee, 0), int(n))
    total = sum(want.values())
    if total > HIVE_MAX:
        # ponytail: a straight proportional cut; a weighting by what each
        # bee does for the main would need a measured honey/h per bee type.
        cut = {b: n * HIVE_MAX // total for b, n in want.items()}
        for b in sorted(want, key=lambda b: -want[b])[:HIVE_MAX - sum(cut.values())]:
            cut[b] += 1
        notes.append(f"these want {total} bees but a hive holds {HIVE_MAX}, so the mix is "
                     + ", ".join(f"{n} {b.title()}" for b, n in cut.items() if n))
        want = cut
        gifted = {b: min(n, want.get(b, n)) for b, n in gifted.items()}
    return want, gifted


def merge(target_ids, data: dict | None = None, acct: prog.Account | None = None,
          have: dict | None = None, rates=None, item_rates: dict | None = None) -> Plan:
    """One order for all `target_ids`. `acct` (progression.Account) marks
    owned gear and the bee count; `have` is {"bees": {type: n}, "gifted":
    {type,...}, "honey": n, "tickets": n, slug: n}; `rates` is a
    session_goals.Rates, `item_rates` {slug: per hour} (tickets included)."""
    data = load() if data is None else data
    all_t = targets(data)
    ids = [t for t in dict.fromkeys(target_ids) if t in all_t]
    tgts = [all_t[t] for t in ids]
    have = dict(have or {})
    plan = Plan([str(t.get("label") or t["id"]) for t in tgts], [])
    by_id: dict = {}

    def add(gid, label, cost, tlabel, why="", after=(), goal=None):
        s = by_id.get(gid)
        if s is None:
            s = by_id[gid] = Step(gid, label, cost, why=" ".join(str(why).split()))
            if goal is not None and acct is not None:
                s.done = prog.done(acct, goal, prog.load(str(goal.get("_hive") or prog.DEFAULT_HIVE)))
        if tlabel not in s.targets:
            s.targets.append(tlabel)
        s.after |= {str(a) for a in after}

    for t in tgts:
        tl = str(t.get("label") or t["id"])
        for g in steps(str(t["id"]), data):
            cost = {k: v for k, v in (g.get("cost") or {}).items() if v}
            gid = str(g["id"])
            add(gid, str(g.get("label") or gid), cost, tl, g.get("why", ""),
                list(g.get("after") or []) + [r for r in g.get("requires") or [] if isinstance(r, str)],
                dict(g, _hive=t.get("hive")))
            if g.get("kind") == "quest":
                # no quest-chain rate is measured yet: its time is not known
                by_id[gid].waits_on = [by_id[gid].label]

    # HIVE SLOTS: one step, to the biggest hive any target wants
    size = max([min(HIVE_MAX, int(t.get("hive_size") or 0)) for t in tgts] or [0])
    bees_now = (acct.bees if acct is not None and acct.bees is not None else HIVE_FREE)
    if size > HIVE_FREE:
        gid = f"hive_slot<={size}"
        honey = _slot_honey(bees_now, size)
        for t in tgts:
            if t.get("hive_size"):
                add(gid, f"Hive slots up to {size}", {"honey": honey} if honey else {},
                    str(t.get("label") or t["id"]), "Room for the bees these targets want.")
        if bees_now >= size:
            by_id[gid].done = f"{bees_now} bees"

    # BEES: Mythic Eggs for every wanted Mythic type together, then Star Treats
    want, gifted = _bee_counts(tgts, plan.notes)
    src = data.get("bee_sources") or {}
    egg, treat = src.get("mythic_egg") or {}, src.get("star_treat") or {}
    kinds = list(egg.get("hatches") or [])
    owned_bees = have.get("bees") or {}
    short = {b: max(0, n - int(owned_bees.get(b) or 0)) for b, n in want.items() if b in kinds}
    if short and kinds:
        eggs = len(kinds) * max(short.values())
        price = int((egg.get("cost") or {}).get("tickets") or 0)
        for t in tgts:
            if any(b in short for b in t.get("bees") or {}):
                add(EGGS_ID, f"{eggs} Mythic Eggs" if eggs else "Mythic Eggs",
                    {"tickets": eggs * price} if eggs else {}, str(t.get("label") or t["id"]),
                    "Hatch them for " + ", ".join(f"{n} {b.title()}" for b, n in want.items() if b in kinds)
                    + f" (about 1 egg in {len(kinds)} is each kind). An egg can hatch on top of a bee,"
                    " so it needs no free slot (wiki Egg page).")
        if not eggs:
            by_id[EGGS_ID].done = "the hive has them"
    got_gifted = set(have.get("gifted") or ())
    t_price = int((treat.get("cost") or {}).get("tickets") or 0)
    for bee, n in gifted.items():
        # ponytail: the bee menu's stars give gifted TYPES, not counts; one
        # gifted of a type read counts as one Star Treat already fed.
        n_left = max(0, n - (1 if bee in got_gifted else 0))
        gid = f"star_treats_{bee}"
        for t in tgts:
            if bee in (t.get("gifted") or {}):
                add(gid, f"{n_left} Star Treat{'s' * (n_left != 1)} for {bee.title()} Bees",
                    {"tickets": n_left * t_price} if n_left else {}, str(t.get("label") or t["id"]),
                    "Makes them gifted. Feed after the egg, never before.",
                    [EGGS_ID] if bee in short else [])
        if not n_left:
            by_id[gid].done = "already gifted"

    # LEVELS: a target's bee level, no cost and no rate to give an ETA
    lvl = max([int(t.get("level") or 0) for t in tgts] or [0])
    if lvl:
        for t in tgts:
            if t.get("level"):
                add(f"bee_level>={lvl}", f"Bees to level {lvl}", {}, str(t.get("label") or t["id"]),
                    "Treats and bond; alts work much better at level 20.",
                    [g for g in (EGGS_ID,) if g in by_id])
        by_id[f"bee_level>={lvl}"].waits_on = ["bee levels"]

    plan.steps = _order(list(by_id.values()))
    _etas(plan, have, rates, item_rates or {})
    return plan


def _order(items: list) -> list:
    """Topological order; among the steps free to go, the cheapest first
    (then file order). An `after` naming no step here is ignored."""
    ids = {s.id: i for i, s in enumerate(items)}
    deps = {s.id: {a for a in s.after if a in ids and a != s.id} for s in items}
    heap = [(s.price(), ids[s.id], s.id) for s in items if not deps[s.id]]
    heapq.heapify(heap)
    out, placed = [], set()
    while heap:
        _p, _i, gid = heapq.heappop(heap)
        out.append(items[ids[gid]])
        placed.add(gid)
        for s in items:
            if s.id not in placed and gid in deps[s.id]:
                deps[s.id].discard(gid)
                if not deps[s.id]:
                    heapq.heappush(heap, (s.price(), ids[s.id], s.id))
    # a loop in the file: the rest in file order rather than lost
    out += [s for s in items if s.id not in placed]
    return out


def _etas(plan: Plan, have: dict, rates, item_rates: dict) -> None:
    """Each open step's eta_h. Honey, tickets and materials are SHARED: a step
    is paid after every step before it, so its inputs are the running sums
    of the inputs IT spends (they come in side by side; the slowest
    decides): the Gold Star Amulet waits on the honey the Bubble Mask took
    first, not on the mask's blueberries. A gate with no cost (a
    quest chain, bee levels) only holds back the steps `after` it."""
    need: dict = {}
    honey_h = getattr(rates, "honey_h", None)
    by_id = {s.id: s for s in plan.open}
    for s in plan.open:
        need["honey"] = need.get("honey", 0) + int(s.cost.get("honey") or 0)
        need["tickets"] = need.get("tickets", 0) + int(s.cost.get("tickets") or 0)
        for slug, n in (s.cost.get("items") or {}).items():
            need[slug] = need.get(slug, 0) + int(n)
        etas, unknown = [], list(s.waits_on)
        own = [k for k in ("honey", "tickets") if s.cost.get(k)] + list(s.cost.get("items") or {})
        for slug in own:
            left = need[slug] - int(have.get(slug) or 0)
            if left <= 0:
                continue
            rate = honey_h if slug == "honey" else item_rates.get(slug)
            if not rate:
                unknown.append(slug.replace("_", " "))
            else:
                etas.append(left / rate)
        for gate in (by_id[a] for a in s.after if a in by_id):   # placed earlier: done
            unknown += gate.waits_on
            etas.append(gate.eta_h or 0.0)
        s.waits_on = list(dict.fromkeys(unknown))
        s.eta_h = None if s.waits_on else max(etas, default=0.0)


def from_files(target_ids, var_root=None, settings=None) -> Plan:
    """`merge` on the bot's own reads: owned gear and bee count
    (progression.account_from_files), the hive's bees (var/bees.json), the
    held counts and their rates (var/inventory.json), the honey rate
    (session_goals). Read-only, never raises on a missing file."""
    from . import session_goals
    from .goals import material_rates
    var = session_goals._var(var_root)
    acct = prog.account_from_files(var, settings)
    have: dict = {}
    try:
        bees = json.loads((Path(var) / "bees.json").read_text(encoding="utf-8"))
        have["bees"] = {k: int(v) for k, v in (bees.get("bees") or {}).items() if isinstance(v, int)}
        have["gifted"] = list(bees.get("gifted") or [])
    except (OSError, ValueError, AttributeError):
        pass
    try:
        inv = json.loads((Path(var) / "inventory.json").read_text(encoding="utf-8"))
        reads = inv.get("reads") or []
        item_rates = material_rates(reads)
        if reads:
            have.update({k: v for k, v in (reads[-1][1] or {}).items() if isinstance(v, int)})
    except (OSError, ValueError, AttributeError, IndexError, TypeError):
        item_rates = {}
    return merge(target_ids, acct=acct, have=have,
                 rates=session_goals.rates_from_files(var), item_rates=item_rates)
