"""The Coconut Crab: Natro's fight, and when the Coconut Field is open.

WHY. The crab holds the Coconut Field (data/world/timers.yaml coconut_crab):
both trips that reached the field on 2026-10-06 died within seconds of
landing. A quest wants 2.2M pollen there (the Brown Bear's
Coco-Mount-Cact-Rose) and the field leans blue, which suits this hive. Beaten,
the crab stays away for 1.5 days (Natro's timer) and the field can be farmed.

NATRO'S FIGHT (submacros/natro_macro.ahk, the `;crab` block of the bug run,
read 2026-10-06): reset, walk to the field, the sprinkler, 1.4 s right and 1 s
back, twenty looks a quarter-second apart for its health bar, then a 24 s
cycle walked over and over with the tool clicking -- 4 tiles forward; twice:
1 tile forward and 14 moves of 2 tiles left, one every 0.31 s, then 1 tile back
and 14 moves right; 6.5 tiles back at 19 s; still until 24 s. Each move is
timed from the cycle's start, not from the last move's end, so a faster or
slower character keeps the crab's rhythm (`CYCLE` keeps those start times). It
ends on the crab's defeat in the feed, a death, or 15 minutes; then it walks
the loot up.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..vision import nameplate
from ..vision.screenstate import HONEY_REGION, POLLEN_REGION, hud_region
from ..brain import mobtable

TILE = 4.0                       # studs in one of Natro's tiles (lib/Walk.ahk)
COOLDOWN_S = mobtable.respawn("coconut_crab")  # beaten, back in 1.5 days (Natro's LastCocoCrab); mobs.yaml via brain/mobtable (K7)
MAX_FIGHT_S = 900.0              # Natro's limit, 15 minutes
ABSENT_OPEN_S = 7_200.0          # not there: Natro looks again in 2 hours
# ponytail: a fixed back-off after a lost fight (Natro tries again in 30 min,
# which would spend half the farming on a crab this hive cannot beat yet);
# scale it by the crab's measured health drop once a fight has been read
LOST_RETRY_S = 6 * 3600.0
LOST_RETRY_MAX_S = 7 * 86400.0
LOOKS, LOOK_EVERY_S = 20, 0.25   # Natro's search for its health bar
MIN_BEES = 35                    # the Coconut Field's gate

START = ({"op": "hold", "keys": "d", "seconds": 1.4},
         {"op": "hold", "keys": "s", "seconds": 1.0})

_SWEEP = 28 * TILE               # 14 moves of 2 tiles


def _walk(keys: str, tiles: float) -> dict:
    return {"op": "walk", "keys": keys, "studs": round(tiles * TILE, 1)}


# ONE CYCLE as (seconds from its start, steps): the moves' start times from
# Natro's sleeps (0.5 s, then 14 x 0.31 s a sweep).
CYCLE = (
    (0.0, (_walk("w", 4),)),
    (0.5, (_walk("w", 1), _walk("a", 28))),
    (4.84, (_walk("s", 1), _walk("d", 28))),
    (9.18, (_walk("w", 1), _walk("a", 28))),
    (13.52, (_walk("s", 1), _walk("d", 28))),
    (19.0, (_walk("s", 6.5),)),
)
CYCLE_S = 24.0


def loot_steps() -> list[dict]:
    """Natro's walk over the field after a kill: nm_loot(9, 4, side) six
    times, right and left in turn."""
    out: list[dict] = []
    for side in ("d", "a") * 3:
        for _ in range(4):
            out += [_walk("w", 9), _walk(side, 1.5), _walk("s", 9), _walk(side, 1.5)]
    return out


# ---- seeing it ----------------------------------------------------------------
# WHAT THE 18 TRIES OF 2026-10-07..12 SHOWED (var/crab/<stamp>/, 359 frames,
# every one looked at; the pollen read by brain/farm.HudReader). The crab is
# never "absent" here: no try beat it (its 36 h only follows a kill), mobs are
# each player's own, and it comes out of its cave whenever the player stands in
# its field (wiki Coconut_Crab).
#   14 "absent": the character was never in the field. The pollen counter read
#      0 on all 294 of their frames (the bees gather only in a field): 7 walks
#      stopped on the grass by the palm tree at the field's edge (Spirit Bear's
#      side) and Natro's start holds carried them further out, 5 ended in the
#      dark approach before the field, 2 elsewhere. The crab is in none of them.
#   4 deaths: in the field (pollen 176-3,286 from the arrival), the crab beside
#      the character, dead 4-8 s after landing. In 3 its bar was above the top
#      of the screen; in 20261012-115104 it was ON screen at y 7-30 ("HP:
#      250,000" under "Time: 1:59:5x") in looks 01-16 -- whole in 03-06, partly
#      behind the Roblox buttons or the Honey pill in the rest -- above
#      nameplate's WORLD_TOP, and read as a planter's (no white label above,
#      its text across 0.61 of it), so nameplate.find saw it in none.
HUD_PILLS = (HONEY_REGION, POLLEN_REGION)


def bar(frame) -> list:
    """Its health bar wherever it is on screen: nameplate.find_all's own tests
    from the top row down with the HUD pills blanked, and only a Bloom's bar
    refused -- the crab's reads as a planter's. Only worth asking in its field
    (`reached`): elsewhere any mob's or planter's bar answers. MEASURED on the
    359 frames: looks 03-06 of 20261012-115104 (112x16 at y 14), none of the
    other 355."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    view = frame[:, :, :3].copy()
    for x, y, w, h in (hud_region(frame, r) for r in HUD_PILLS):
        view[y:y + h, x:x + w] = 0
    return [p for p in nameplate.find_all(view, world_top=0) if p.kind != "bloom"]


def reached(start, pollen) -> bool:
    """Standing in a field: the pollen counter above `start` (the bag before
    the walk) on any of `pollen`, the arrival's and the looks' readings (None
    where illegible). The bees gather only round a character in a field."""
    return any(p is not None and p > (start or 0) for p in pollen)


def defeated(feed_text: str) -> bool:
    """The feed's word that it is beaten ("Defeated Coconut Crab!"), read
    loosely: tesseract runs words together."""
    said = "".join(str(feed_text or "").lower().split())
    return "defeated" in said and "crab" in said


# ---- when -------------------------------------------------------------------
def load(path: Path) -> dict:
    try:
        body = json.loads(Path(path).read_text())
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, path)


def record(state: dict, result: str, now: float) -> dict:
    """The state after a try: "killed", "absent" (no crab where it lives),
    or a lost fight ("died", "time")."""
    out = dict(state)
    out["tries"] = (list(state.get("tries") or []) + [{"at": now, "result": result}])[-20:]
    if result == "killed":
        out["killed_at"] = now
        out["next_at"] = now + COOLDOWN_S
    elif result == "absent":
        out["absent_at"] = now
        out["next_at"] = now + ABSENT_OPEN_S
    else:
        # each loss in a row doubles the wait (a fight the swarm cannot win yet
        # must not cost a death every few hours), a week at most
        lost = 0
        for t in reversed(out["tries"]):
            if t.get("result") in ("killed", "absent"):
                break
            lost += 1
        out["next_at"] = now + min(LOST_RETRY_S * 2 ** (lost - 1), LOST_RETRY_MAX_S)
    return out


def due(state: dict, now: float) -> bool:
    return now >= float(state.get("next_at", 0.0) or 0.0)


def field_open(state: dict, now: float) -> bool:
    """Is the Coconut Field free of the crab now: beaten within COOLDOWN_S.
    A look that saw no health bar is not enough -- it only brings the next
    look ABSENT_OPEN_S on, Natro's meaning. MEASURED 2026-10-07 10:23: the
    character died 3.7 s after landing beside it and the twenty looks were
    taken at the hive; a crab off screen reads the same, and an "open" field
    sends every trip there into it."""
    killed = float(state.get("killed_at", 0.0) or 0.0)
    return killed > 0 and now - killed < COOLDOWN_S
