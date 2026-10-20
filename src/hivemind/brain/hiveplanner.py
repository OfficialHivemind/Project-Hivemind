"""The owner's hive planner (ROADMAP H13, their idea): the bee they want in each
of the hive's 50 slots, set in the GUI (gui/panels/hiveplanner) and kept in
var/hive_plan.json, and what Royal Jelly does about it (`plan_targets`, which
scripts/run_farm's jelly errand consults before brain/hivejudge's guide rule).

THE BEE MENU READS COUNTS, NOT POSITIONS (var/bees.json, act/beemenu), and
the jelly errand finds its cell by the bee card it reads there. So a plan is
matched BY COUNT: a planned slot "matches" while the hive holds at least as
many of that bee as the plan puts down, and a roll goes only on a bee the hive
holds MORE of than the plan wants -- never on one every copy of which the plan
still needs.

PER SLOT WHEN THE HIVE IS READ CELL BY CELL (ROADMAP H13b, the owner: any bee
can be chosen for any slot, and the AI works towards that): run_farm's jelly
errand clicks each owned cell's face and reads its
card (vision/hivecell.slot_point) into var/hive_slots.json. While that read is
`trusted` against the bee menu's counts, a slot matches only when ITS bee is
the planned one, and Royal Jelly goes on exactly the cells whose bee is not --
never a gifted cell, an event bee or a Mythic. No read: the count match above.

SLOT NUMBERS, the game's hive seen from the pad: slot 1 bottom left, each row
of 5 left to right, upward (slot 6 is row 2's leftmost); odd columns (the 2nd
and 4th) sit half a cell lower. gui/panels/hiveplanner draws the same.

PURE but for `load`/`save`/`load_read`/`save_read`.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .hivejudge import JELLY_RARITIES

SLOTS = 50
PLAN_FILE = "hive_plan.json"          # under var/, beside bees.json and jelly.json
SLOTS_FILE = "hive_slots.json"        # the per-slot read, {"slots": {slot: bee}, ...}
COLS = 5
# Never rolled AWAY by the plan: Royal Jelly never rolls an event bee back,
# and a Mythic is the top of the table.
NEVER_ROLL_AWAY = ("event", "mythic")


def load(path: Path | str, follow: bool = True) -> dict:
    """{slot 1..50: bee slug} from the plan file; {} when there is none, or
    when `follow` is off (setting hive.follow_plan: the plan is only a picture)."""
    if not follow:
        return {}
    try:
        body = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    raw = (body or {}).get("slots") if isinstance(body, dict) else None
    out = {}
    for k, v in (raw or {}).items():
        try:
            slot = int(k)
        except (TypeError, ValueError):
            continue
        if 1 <= slot <= SLOTS and v:
            out[slot] = str(v)
    return out


def save(path: Path | str, slots: dict) -> None:
    from ..files import atomic_write
    body = {"slots": {str(s): b for s, b in sorted(slots.items()) if b}}
    atomic_write(path, json.dumps(body, indent=1) + "\n")


def cell_of(slot: int) -> tuple:
    """(column 0..4 from the left, row 1.. from the bottom) of a slot."""
    return (slot - 1) % COLS, (slot - 1) // COLS + 1


def load_read(path: Path | str, have: dict | None = None) -> tuple:
    """({slot: bee}, {gifted slots}) of the last per-slot read, or ({}, set())
    when there is none or it is not `trusted`: a read naming more of a bee than
    the bee menu counts (`have`, var/bees.json) is stale -- the hive changed
    since, or one cell was read twice. Unread slots are simply absent."""
    try:
        body = json.loads(Path(path).read_text())
        slots = {int(k): str(v) for k, v in (body.get("slots") or {}).items() if v}
        gifted = {int(k) for k in (body.get("gifted") or ())}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}, set()
    if not slots or not trusted(slots, have):
        return {}, set()
    return slots, gifted


def trusted(slots: dict, have: dict | None) -> bool:
    """Whether no bee is read in more slots than the bee menu counts."""
    if have is None:
        return True
    have = Counter({b: int(n) for b, n in have.items()})
    return not (Counter(slots.values()) - have)


def save_read(path: Path | str, slots: dict, gifted=(), **extra) -> None:
    from ..files import atomic_write
    body = dict(extra, slots={str(s): b for s, b in sorted(slots.items()) if b},
                gifted=sorted(int(s) for s in gifted))
    atomic_write(path, json.dumps(body, indent=1) + "\n")


def match_slots(plan: dict, read: dict) -> dict:
    """{planned slot: True/False}, by the bee read in that very slot; a slot
    not read is left out (neither matches nor is to do)."""
    return {s: read[s] == b for s, b in plan.items() if s in read}


def slot_targets(plan: dict, read: dict, types: dict, gifted=()) -> list:
    """[(slot, bee there, bee planned)] Royal Jelly should roll, the cheapest
    bee first: a read slot whose bee is not the planned one, the planned bee
    one jelly can roll (rare to mythic), never a gifted cell, an event bee or
    a Mythic rolled away. A matching slot is never a target."""
    rarity = lambda b: str((types.get(b) or {}).get("rarity") or "")  # noqa: E731
    order = {r: i for i, r in enumerate(("common",) + JELLY_RARITIES)}
    out = [(s, read[s], want) for s, want in plan.items()
           if s in read and read[s] != want and s not in set(gifted)
           and rarity(want) in JELLY_RARITIES and rarity(read[s]) not in NEVER_ROLL_AWAY]
    return sorted(out, key=lambda t: (order.get(rarity(t[1]), 9), t[0]))


def match(slots: dict, have: dict) -> dict:
    """{slot: True if it matches, False if still to do}, by count, the lowest
    slots of a bee claiming the copies held first."""
    left = Counter({b: int(n) for b, n in (have or {}).items()})
    out = {}
    for slot in sorted(slots):
        bee = slots[slot]
        out[slot] = left[bee] > 0
        if out[slot]:
            left[bee] -= 1
    return out


def fill_from_comp(comp_bees: dict) -> dict:
    """A plan from the guide's stage comp ({bee: [least, most]}, blue_hive_plan
    .yaml), the most of each, biggest group first from slot 1."""
    slots, n = {}, 1
    for bee, (_least, most) in sorted(comp_bees.items(), key=lambda kv: -int(kv[1][1])):
        for _ in range(int(most)):
            if n <= SLOTS:
                slots[n] = bee
                n += 1
    return slots


def plan_targets(slots: dict, have: dict, types: dict, guide_jelly_on=(),
                 read: dict | None = None, gifted=()) -> tuple | None:
    """(hits, jelly_on) for the jelly errand, or None when there is no plan.

    hits: the planned bees the hive is short of that Royal Jelly can roll
    (rare to mythic) -- a roll stops on one. jelly_on: the bees the hive holds
    more of than the plan wants (never an event bee or a Mythic). Where the plan
    covers fewer slots than the hive has bees, the bees in the slots it leaves
    open cannot be told apart, so only the surplus the guide would roll anyway
    (`guide_jelly_on`, hivejudge's) is offered.
    With a per-slot `read` (load_read): hits are the planned bees of the
    target cells (slot_targets), jelly_on the bees in them."""
    if not slots:
        return None
    if read:
        targets = slot_targets(slots, read, types, gifted)
        return (tuple(sorted({w for _s, _b, w in targets})),
                tuple(dict.fromkeys(b for _s, b, _w in targets)))
    rarity = lambda b: str((types.get(b) or {}).get("rarity") or "")  # noqa: E731
    want = Counter(slots.values())
    hits = tuple(b for b in sorted(want)
                 if want[b] > int(have.get(b, 0)) and rarity(b) in JELLY_RARITIES)
    if not hits:
        return (), ()
    surplus = [b for b, n in sorted(have.items())
               if int(n) > want[b] and rarity(b) not in NEVER_ROLL_AWAY]
    if len(slots) < sum(int(n) for n in have.values()):
        surplus = [b for b in surplus if b in set(guide_jelly_on)]
    # the guide's own unwanted bees first, then the cheapest rarity
    order = {r: i for i, r in enumerate(("common",) + JELLY_RARITIES)}
    surplus.sort(key=lambda b: (b not in set(guide_jelly_on), order.get(rarity(b), 9), b))
    return hits, tuple(surplus)


# WHERE NEW BEES GO (ROADMAP H13d, the owner 2026-10-16): setting
# hive.new_bees. "any empty slot" is today's hatch (the one empty cell in
# view) and the default (U15b: optional features off). "follow the Hive
# Planner" picks the empty slot the plan wants filled next. PLAN ORDER is slot
# order: the planner fills from slot 1 down its priority (fill_from_comp puts
# the biggest group first), so the lowest planned empty slot is next.
HATCH_ANY, HATCH_PLAN = "any empty slot", "follow the Hive Planner"


def hatch_slot(plan: dict, read: dict, read_at: float, owned: int, bees: int,
               last_hatch_at: float = 0.0) -> tuple:
    """(slot, why) the plan wants the next egg in, or (None, why not) -- and
    then the hatch stays "any empty slot". NEVER A GUESS: the empty slots are
    known only from a per-slot read (load_read) made after the last hatch that
    names exactly as many bees as the bee menu counts (`bees`), every one in
    the `owned` slots (1..owned, bought); the rest of 1..owned are empty."""
    if not plan:
        return None, "there is no Hive Plan"
    if not read or not read_at:
        return None, "no per-slot hive read (var/hive_slots.json) to tell the empty slots"
    if read_at < last_hatch_at:
        return None, "the per-slot read is older than the last hatch"
    if len(read) != bees or any(s > owned for s in read):
        return None, (f"the per-slot read names {len(read)} bees in slots up to "
                      f"{max(read)}, the bee menu counts {bees} in {owned} slots bought")
    empty = [s for s in range(1, owned + 1) if s not in read]
    if not empty:
        return None, "no empty slot"
    planned = [s for s in empty if s in plan]
    if not planned:
        return None, f"no empty slot ({', '.join(map(str, empty))}) is in the Hive Plan"
    return planned[0], f"planned: {plan[planned[0]]}, next in plan order"
