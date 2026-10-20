"""The gifted Basic Bee grinder (ROADMAP H16, the owner 2026-10-16: "basic egg
then jelly then basic egg and cycle till they get a basic bee gifted... u get
to choose where u want it").

In ONE slot the owner picks (setting hive.grind_slot, or the Hive Planner's
slot picker): a Basic Egg hatched there, the Basic Bee it gives jellied (a
Basic Egg "cannot be used on a Basic Bee", data/knowledge/items.yaml), a Basic
Egg on whatever the jelly made, and round again -- until the slot holds a
GIFTED BASIC BEE. Then it stops and says so (scripts/telegram_alerts pings).

RULES. Basic Eggs only (goals.egg_may_hatch: Star/Silver/Gold/Diamond/Mythic
stay saved); Royal Jelly only, never the Star Jelly; honey only, never Robux.
ANY gifted bee or any Mythic in the slot stops it at once -- the Royal Jelly
stop rule -- so a lucky roll is kept, not overwritten; an event bee is never
replaced either. A budget per session (hive.grind_max_honey, _max_jellies) and
the switch hive.grind_basic, DEFAULT OFF.

LIVE ONLY THROUGH TESTED PATHS (`next_step`'s `live`): the egg bought at the
Basic Egg Shop (bought live 6 times, 10,000,000 honey read in its window); the
hatch only when the slot is the ONE empty cell (today's hatch, "hatch basic
egg" answered Yes live 6 times); the jelly only when the slot's Basic Bee is
the hive's ONLY one (found by its card, the jelly errand's scan). The rest is
look-only and says "gifted basic grinder would: ...": the aimed hatch (H13d
HATCH_AIM_LIVE), the aimed jelly (H13b SLOTS_ROLL_LIVE), and a Basic Egg on a
full slot (`replace_live`: whether it replaces the bee, and the question it
asks, are NOT measured).

PURE but for `load`/`save`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# one key a line: tests/unit/test_settings_effect follows NAME = "key"
ON = "hive.grind_basic"
SLOT = "hive.grind_slot"
MAX_HONEY = "hive.grind_max_honey"
MAX_JELLIES = "hive.grind_max_jellies"
STATE_FILE = "grinder.json"            # under var/
BASIC = "basic"
EMPTY = "empty"
NEVER_REPLACE = ("event", "mythic")
LINE = "gifted basic grinder"          # every narrated line starts so
STOPPED = f"{LINE}: STOPPED — "         # scripts/telegram_alerts pings on it


@dataclass
class Step:
    """`do`: off | stop | wait | buy_egg | hatch | jelly | replace.
    `live` False: say "would", press nothing."""
    do: str
    why: str
    live: bool = False

    def said(self, slot) -> str:
        if self.do in ("off", "wait"):
            return f"{LINE}: not now — {self.why}"
        if self.do == "stop":
            return f"{LINE}: stopped in slot {slot} — {self.why}"
        verb = {"buy_egg": "buy a Basic Egg", "hatch": f"hatch a Basic Egg in slot {slot}",
                "jelly": f"roll Royal Jelly on slot {slot}'s Basic Bee",
                "replace": f"drop a Basic Egg on slot {slot}"}[self.do]
        return (f"{LINE}: {verb} — {self.why}" if self.live
                else f"{LINE} would: {verb} — look-only: {self.why}")


def load(path: Path | str) -> dict:
    try:
        body = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def save(path: Path | str, state: dict) -> None:
    from ..files import atomic_write
    atomic_write(path, json.dumps(state, indent=1) + "\n")


def spent(state: dict, session: str) -> dict:
    """{"honey", "jellies", "eggs"} spent this session (0s for a new one)."""
    s = state.get("session") or {}
    if s.get("id") != session:
        return {"honey": 0, "jellies": 0, "eggs": 0}
    return {k: int(s.get(k) or 0) for k in ("honey", "jellies", "eggs")}


def add_spend(state: dict, session: str, **amounts) -> dict:
    now = spent(state, session)
    for k, v in amounts.items():
        now[k] = now.get(k, 0) + int(v)
    state["session"] = dict(now, id=session)
    return state


def seen(state: dict, slot: int, bee, gifted: bool, rarity: str, at: float) -> str:
    """The slot's bee as a card just read it, kept in `state`; the stop
    reason ("" to go on). `bee` None (a card not read) stops too: the next
    drop would be on a bee nobody saw."""
    state.update(slot=slot, bee=bee, gifted=bool(gifted), at=at)
    done = ""
    if bee is None:
        done = "a card it could not read — check the slot by eye"
    elif gifted and bee == BASIC:
        done = f"DONE: a GIFTED BASIC BEE in slot {slot}"
    elif gifted:
        done = f"a gifted {bee} bee in slot {slot} — kept, not overwritten"
    elif rarity == "mythic":
        done = f"a Mythic {bee} bee in slot {slot} — kept, not overwritten"
    if done:
        state.update(done=done, done_at=at)
    return done


def slot_now(slot: int, state: dict, read: dict, read_gifted, read_at: float,
             owned: int, bees: int) -> tuple:
    """(bee slug | EMPTY | None, gifted, the only empty cell?, where from).
    Never a guess: the slot is EMPTY only when it is the one slot bought and
    not filled (owned - bees == 1, the newest) or a per-slot read made after
    the grinder's last look names exactly the bees counted without it."""
    only = owned - bees == 1 and slot == owned
    if only:
        return EMPTY, False, True, "the one slot bought and still empty"
    mine = state.get("slot") == slot and "bee" in state
    if read and read_at >= (float(state.get("at") or 0.0) if mine else 0.0):
        if slot in read:
            return read[slot], slot in set(read_gifted), False, "the per-slot hive read"
        if len(read) == bees and slot <= owned:
            return EMPTY, False, owned - bees == 1, "the per-slot hive read (not filled)"
    if mine:
        return state.get("bee"), bool(state.get("gifted")), False, "the grinder's own last card"
    return None, False, False, ""


def next_step(*, on: bool, slot: int, max_honey: int, max_jellies: int, state: dict,
              session: str, read: dict, read_gifted, read_at: float, owned: int,
              bees: int, have: dict, types: dict, stale: str, eggs_held: int,
              jelly_spare: int, honey: int | None, egg_price: int | None,
              may_buy: bool, replace_live: bool) -> Step:
    """What the grinder does next. `stale`: why the bee/inventory reads are
    out of date ("" when fresh). `jelly_spare`: Royal Jelly held over the
    Blender's share. `egg_price`: the Basic Egg Shop's window, read live."""
    if not on:
        return Step("off", "the switch is off")
    if not 1 <= int(slot or 0) <= 50:
        return Step("off", "no slot chosen (hive.grind_slot is 0)")
    if state.get("done") and state.get("slot") == slot:
        return Step("stop", str(state["done"]))
    if slot > owned:
        return Step("wait", f"slot {slot} is not bought ({owned} bought)")
    if stale:
        return Step("wait", stale)
    bee, gifted, only, source = slot_now(slot, state, read, read_gifted, read_at, owned, bees)
    if bee is None:
        return Step("wait", f"slot {slot}'s bee is not known: no per-slot hive read "
                            f"(H13b) names it and the grinder has not seen it")
    rarity = str((types.get(bee) or {}).get("rarity") or "")
    label = str((types.get(bee) or {}).get("label") or bee)
    if gifted and bee == BASIC:
        return Step("stop", f"DONE: a GIFTED BASIC BEE in slot {slot} ({source})")
    if gifted or rarity in NEVER_REPLACE:
        what = "gifted" if gifted else rarity
        return Step("stop", f"slot {slot} holds a {what} {label} ({source}) — never "
                            f"rolled or replaced")
    used = spent(state, session)
    if bee == BASIC:
        if used["jellies"] >= max_jellies:
            return Step("stop", f"the session's Royal Jelly budget is spent "
                                f"({used['jellies']} of {max_jellies})")
        if jelly_spare <= 0:
            return Step("wait", "no Royal Jelly held beyond the Blender's share")
        n = int(have.get(BASIC, 0) or 0)
        if n == 1:
            return Step("jelly", "the hive's only Basic Bee, found by its card", True)
        return Step("jelly", f"{n} Basic Bees in the hive: the jelly would need aiming at "
                             f"slot {slot} (SLOTS_ROLL_LIVE, not checked live)")
    if bee == EMPTY:
        do, live = "hatch", only
        why = (f"slot {slot} is the one empty cell" if only else
               f"{owned - bees} empty slots: the hatch would need aiming (HATCH_AIM_LIVE, "
               f"not checked live)")
    else:
        do, live = "replace", replace_live and int(have.get(bee, 0) or 0) == 1
        why = (f"the hive's only {label}, found by its card" if live else
               f"a Basic Egg on a full slot ({label}) is not measured: does it replace "
               f"the bee, and what does it ask?" if not replace_live else
               f"{have.get(bee, 0)} {label}s in the hive: the egg would need aiming")
    if eggs_held > 0:
        return Step(do, why, live)
    # NO EGG HELD: one is bought, but only for a step that will act
    if not live:
        return Step("buy_egg", f"for the next step, itself look-only ({why})")
    if not may_buy:
        return Step("wait", "economy.buy is off")
    if not egg_price:
        return Step("wait", "the Basic Egg's price has not been read in its shop's window")
    if used["honey"] + egg_price > max_honey:
        return Step("stop", f"the session's honey budget is spent ({used['honey']:,} of "
                            f"{max_honey:,}; an egg is {egg_price:,})")
    if honey is None or honey < egg_price:
        return Step("wait", f"an egg is {egg_price:,} honey and the HUD reads "
                            f"{'?' if honey is None else f'{honey:,}'}")
    return Step("buy_egg", f"{egg_price:,} honey ({used['honey'] + egg_price:,} of "
                           f"{max_honey:,} this session), for the {do} after", True)
