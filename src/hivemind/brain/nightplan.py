"""The night plan (ROADMAP B6): what a night is spent on, in what order,
LOOK-ONLY.

WHY A PLAN. A night is short and rare: ~10% of the clock (MEASURED,
vision/night: 406 of 3,957 pad frames; act/vichunt), 2:35 a night on the
wiki. Each night job has its own gate today (run_farm vicious_due,
memorymatch_due, the bug runs), each deciding alone. This module puts them
in one ordered list and says it ("night plan would: ..."); it moves nothing
and presses nothing. NIGHT_PLAN_LIVE stays False until the order is seen
live against what the gates actually ran.

THE ORDER, AND WHY.
  1. VICIOUS BEE -- the only job here bound to the night (wiki
     Rogue_Vicious_Bee; mobs.yaml rogue_vicious_bee) with a live act
     (act/vicious), spaced by var/vicious.json `next_at`.
  2. WEREWOLF -- NOT a night mob: mobs.yaml `night: both`, respawn 3630 s
     (MEASURED median 3734 s). Listed so a night that finds it up says so;
     the bug runs take it day or night (combat.bug_werewolf).
  3. NIGHT MEMORY MATCH -- 8 h cooldown (brain/calendar), but no route to it
     and no frame of its panel (act/memorymatch LEFT OFF): never planned.
  4. WILD WINDY BEE -- no row in mobs.yaml, no reader for it: never planned.
No honey price is put on any of them: none is measured (calendar.py leaves
the Vicious Stinger and Memory Match prizes unpriced too).
"""
from __future__ import annotations

from .calendar import RESPAWN_SECONDS

# LOOK-ONLY: the plan is said, the existing gates still decide what runs.
NIGHT_PLAN_LIVE = False
WEREWOLF_RESPAWN_S = RESPAWN_SECONDS["werewolf"]


def plan(now: float, vicious_state: dict, werewolf_last: float,
         mm_state: dict) -> list:
    """[(job, would-line)] for a night that is up now, in THE ORDER above.
    `vicious_state` is var/vicious.json, `werewolf_last` the latest kill or
    visit the bug-run log holds over its three fields (0 = never),
    `mm_state` var/memorymatch.json."""
    out = []
    nxt = float((vicious_state or {}).get("next_at") or 0.0)
    out.append(("vicious_bee",
                "hunt the Vicious Bee (its hunt is due)" if now >= nxt else
                f"leave the Vicious Bee (next hunt in {(nxt - now) / 60:.0f} min)"))
    if not werewolf_last:
        out.append(("werewolf", "werewolf: no kill booked, its timer is unknown"))
    else:
        left = float(werewolf_last) + WEREWOLF_RESPAWN_S - now
        out.append(("werewolf",
                    "werewolf is up (respawned), a bug run's job day or night" if left <= 0
                    else f"werewolf up in {left / 60:.0f} min (day or night)"))
    played = ((mm_state or {}).get("last_play") or {}).get("night")
    out.append(("night_memory_match",
                "skip night Memory Match: no route, its panel never seen"
                + (f" (last played {(now - float(played)) / 3600:.1f} h ago)" if played else "")))
    out.append(("wild_windy_bee", "skip Wild Windy Bee: no reader, not in mobs.yaml"))
    return out


def would(steps: list) -> str:
    """One log line for the plan."""
    return "night plan would: " + "; ".join(line for _job, line in steps)
