"""The Tunnel Bear: Natro's fight, via the ramp into the White Tunnel behind
the Brave Bee Gate (data/knowledge/quests.yaml `science_bear_detail`: "up the
ramp... bees_required: 10" -- the same gate and the same ramp).

NATRO'S FIGHT (submacros/natro_macro.ahk ~15174-15322, read 2026-10-12,
MoveMethod "walk" branch): `nm_gotoRamp()` is nothing more than the hive's own
exit (`nm_Walk(5, FwdKey)` then the hive-slot offset -- the same first two
steps every `natro_out_*` route in data/world/natro_paths.yaml already opens
with), so there is no existing *field* route that gets partway to the tunnel:
its own walk from there goes back-and-left, the opposite way to Blue
Flower/Pineapple/Stump, through a jump-glide, to the tunnel mouth. That whole
walk is transcribed below as START rather than split against an existing
route (deliberately -- see docs/pending/integration.md); the hive exit is
included so the route starts clean from the hive. Natro's `tunnelbearconfirm`
image check and its baby-love buff wait have no vision helper here and are
skipped, same as act/crab.py skips what it cannot see. The fight (10,000 HP,
wiki) is a short back-nudge while the tool swings, repeated until the feed
says it is beaten, a death, or MAX_FIGHT_S; a kill walks the loot forward and
back (`nm_Move(12000*MSF, FwdKey)`, `nm_Move(18000*MSF, BackKey)`).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np

from ..vision import nameplate
from ..brain import mobtable

TILE = 4.0                        # studs in one of Natro's tiles (lib/Walk.ahk)
# nm_Move(ms*MoveSpeedFactor, key) always covers ms*18/1000 studs, whatever the
# character's real speed (MoveSpeedFactor := 18/MoveSpeedNum cancels it out --
# scripts/transpile_natro_patterns.py's STUDS_PER_NATRO_UNIT, same formula).
STUDS_PER_MS = 18.0 / 1000.0

COOLDOWN_S = mobtable.respawn("tunnel_bear")  # 48h (Natro's LastTunnelBear; data/world/timers.yaml); mobs.yaml via brain/mobtable (K7)
MAX_FIGHT_S = 180.0               # safety cap over Natro's own ~120 one-second loops
ABSENT_OPEN_S = 7200.0            # not there: Natro looks again in 2 hours (its own "+7200")
# ponytail: same reasoning as act/beetle.py LOST_RETRY_S -- Natro has no
# back-off of its own for a lost (not absent) fight
LOST_RETRY_S = 7200.0
LOST_RETRY_MAX_S = 7 * 86400.0
LOOKS, LOOK_EVERY_S = 20, 0.25    # Natro's search for its health bar
MIN_BEES = 10                     # the Brave Bee Gate (data/knowledge/quests.yaml:65)


def _walk(keys: str, studs: float) -> dict:
    return {"op": "walk", "keys": keys, "studs": round(studs, 2)}


def _tile(keys: str, tiles: float) -> dict:
    return _walk(keys, tiles * TILE)


def _ms(keys: str, ms: float) -> dict:
    return _walk(keys, ms * STUDS_PER_MS)


# THE WALK IN: the hive's own exit (nm_gotoRamp, shared with every
# natro_out_* route), then Natro's own path to the tunnel mouth
# (natro_macro.ahk:15179-15213, the "walk" MoveMethod). The jump-glide
# (`Space`+`FwdKey` held across `Walk(12)`) is `jump_hold`/`coast`/
# `jump_release`, the same ops data/world/natro_paths.yaml already uses for
# Natro's own held jumps. Its `tunnelbearconfirm` image check and baby-love
# wait are skipped (no helper); the two final legs are Natro's own approach to
# where it stands and looks for the bear (`nm_Move(6000*MSF, BackKey)`,
# `nm_Move(550*MSF, LeftKey)`).
START = (
    _walk("w", 5 * TILE),                                  # nm_gotoRamp: nm_Walk(5, FwdKey)
    {"op": "hive_offset", "keys": "d", "tiles_per_slot": 9.2,
     "tiles_offset": -4.0, "studs_per_tile": 4.0},          # nm_gotoRamp: 9.2*HiveSlot-4
    _tile("sa", 67.5),                                      # nm_Walk(67.5, BackKey, LeftKey)
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "right"},
    _tile("w", 23.5),                                       # nm_Walk(23.5, FwdKey)
    _tile("wd", 31.5),                                      # nm_Walk(31.5, FwdKey, RightKey)
    _tile("d", 10),                                         # nm_Walk(10, RightKey)
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "right"},
    _tile("w", 28),                                         # nm_Walk(28, FwdKey)
    _tile("a", 13),                                         # nm_Walk(13, LeftKey)
    _tile("d", 25),                                         # nm_Walk(25, RightKey)
    {"op": "jump_hold"},                                    # Space down
    {"op": "key_down", "keys": "w"},                        # FwdKey down
    {"op": "coast", "studs": 12 * TILE},                    # Walk(12)
    {"op": "jump_release"},
    {"op": "key_up", "keys": "w"},
    {"op": "camera", "direction": "left"},
    {"op": "camera", "direction": "left"},
    _tile("w", 35),                                         # nm_Walk(35, FwdKey)
    _tile("d", 25),                                         # nm_Walk(25, RightKey)
    _tile("w", 12),                                         # nm_Walk(12, FwdKey)
    _tile("d", 3.5),                                        # nm_Walk(3.5, RightKey)
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "right"},
    _tile("w", 37),                                         # nm_Walk(37, FwdKey)
    _tile("wa", 10),                                        # nm_Walk(10, FwdKey, LeftKey)
    _tile("s", 5),                                           # nm_Walk(5, BackKey)
    _tile("d", 15),                                         # nm_Walk(15, RightKey)
    _tile("s", 10),                                          # nm_Walk(10, BackKey)
    {"op": "pause", "seconds": 3.0},                        # Sleep(3000)
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "up"},
    {"op": "camera", "direction": "up"},
    {"op": "camera", "direction": "up"},
    # (tunnelbearconfirm image check skipped: no helper for it)
    {"op": "camera", "direction": "left"},
    {"op": "camera", "direction": "left"},
    {"op": "camera", "direction": "down"},
    {"op": "camera", "direction": "down"},
    {"op": "camera", "direction": "down"},
    {"op": "pause", "seconds": 2.0},                        # DllCall Sleep 2000
    # (baby-love buff wait skipped: no helper)
    _ms("s", 6000),                                         # nm_Move(6000*MSF, BackKey)
    _ms("a", 550),                                          # nm_Move(550*MSF, LeftKey)
)

# THE FIGHT (natro_macro.ahk:15295-15313): stand, look up, and nudge back if
# its health bar is lost, checking the feed/nameplate each second the way
# run_farm's outcome() already does for the crab and the beetle.
CYCLE = (
    (0.0, ({"op": "camera", "direction": "up"}, {"op": "camera", "direction": "up"},
           {"op": "camera", "direction": "up"}, _ms("s", 200))),
    (1.0, (_ms("s", 200),)),
)
CYCLE_S = 2.0

# THE LOOKS DODGE FROM THE FIRST ONE: one back-nudge (Natro's own 200 ms unit,
# the fight's) after every look. MEASURED 2026-10-12/13, the 5 tries in
# var/tunnelbear/<stamp>/ (92 frames, looked at): the bear walks from the dark
# end onto the character in ~5 s, and the character stood still through all
# twenty looks (LOOKS x LOOK_EVERY_S) before any move -- 4 of the 5 died in
# them ("You died!" at look 15-18), the 5th (075847) was called "absent".
DODGE = (_ms("s", 200),)

# A HOLD AFTER HOLD_DEATHS DEATHS with these moves, like act/commando's obby
# hold: `held` is keyed to FIGHT_ID (a hash of START, DODGE and CYCLE), so a
# change to the fight clears it, and to the bees read when it was set, so a
# bigger hive clears it too; or a person deletes "held" from
# var/tunnelbear.json. MEASURED 2026-10-12 17:23 to 2026-10-13 12:48: 4 deaths
# in 5 tries, retried every 2-4 h ("absent" resets the doubling).
HOLD_DEATHS = 3
FIGHT_ID = hashlib.sha1(json.dumps([START, DODGE, CYCLE]).encode()).hexdigest()[:8]

# ITS BAR AT THE TOP EDGE: the bear stands over the character, so its full
# "HP: 10,000" bar sits at y 0-15, between and above the Honey and Pollen pills
# -- above nameplate's WORLD_TOP (100), so `find` never sees it, and full, so
# `hurt_bars` (a red end) never does either. MEASURED on the 92 frames: the bar
# shows in looks 01-04 of every try, 0.4-1.5 s after arrival (10 frames,
# 075847's "absent" included), then rises out of view. Every one of the 10 has
# >= 2 rows whose longest green run (nameplate's BAR_* green) inside TOP_X is
# TOP_MIN_RUN..TOP_MAX_RUN px (the rows under its text: 85-152), and none of the
# other 82 has a run over 10. act/crab.bar (find_all with the pills blanked)
# sees 2 of the 10: the rest are cut off by the screen's top edge. ONLY IN THE
# TUNNEL: on 12,000 frames sampled from var/ elsewhere 58 pass (grass, cactus).
TOP_ROWS = 24
TOP_X = (900, 1220)
TOP_MIN_RUN, TOP_MAX_RUN = 45, 200
TOP_MIN_ROWS = 2


def bar_at_top(frame) -> bool:
    """The Tunnel Bear's bar cut off at the screen's top edge (see TOP_*)."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return False
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[:TOP_ROWS, TOP_X[0]:TOP_X[1], :3]),
                       cv2.COLOR_BGR2HSV)
    lo, hi = nameplate.BAR_HUE
    green = ((hsv[:, :, 0] >= lo) & (hsv[:, :, 0] <= hi)
             & (hsv[:, :, 1] >= nameplate.BAR_MIN_SATURATION)
             & (hsv[:, :, 2] >= nameplate.BAR_MIN_VALUE))
    rows = 0
    for row in green:
        a, b = nameplate._longest_run(row)
        rows += TOP_MIN_RUN <= b - a <= TOP_MAX_RUN
    return rows >= TOP_MIN_ROWS


def seen(frame) -> bool:
    """Its bar anywhere: at the top edge, hurt, or whole in the world band."""
    return bool(frame is not None and (bar_at_top(frame) or nameplate.hurt_bars(frame)
                                       or nameplate.find(frame)))


def loot_steps() -> list[dict]:
    """Natro's loot: `nm_Move(12000*MSF, FwdKey)` then `nm_Move(18000*MSF, BackKey)`."""
    return [_ms("w", 12000), _ms("s", 18000)]


def defeated(feed_text: str) -> bool:
    """The feed's word that it is beaten. Both "tunnel" and "bear" are
    required -- Brown/Black/Polar/Mother/Spirit/Panda Bear are all defeated
    elsewhere in this hive, and "bear" alone would misread one of those."""
    said = "".join(str(feed_text or "").lower().split())
    return "defeated" in said and "tunnel" in said and "bear" in said


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


def record(state: dict, result: str, now: float, bees: int = 0) -> dict:
    """The state after a try: "killed", "absent", or a lost fight ("died",
    "time"). The HOLD_DEATHS-th death with this FIGHT_ID holds it at `bees`."""
    out = dict(state)
    out["tries"] = (list(state.get("tries") or [])
                    + [{"at": now, "result": result, "fight": FIGHT_ID}])[-20:]
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
        if result == "died" and deaths(out) >= HOLD_DEATHS:
            out["held"] = {"at": now, "fight": FIGHT_ID, "bees": int(bees or 0)}
    return out


def deaths(state: dict) -> int:
    """Deaths with these moves (FIGHT_ID) since the last kill."""
    n = 0
    for t in reversed(list(state.get("tries") or [])):
        if t.get("result") == "killed":
            break
        n += t.get("result") == "died" and t.get("fight") == FIGHT_ID
    return n


def held(state: dict, bees: int = 0) -> bool:
    """Held after HOLD_DEATHS deaths, until the fight changes or `bees` (0 =
    unread) grows past the count it was held at."""
    h = state.get("held")
    return (isinstance(h, dict) and h.get("fight") == FIGHT_ID
            and int(bees or 0) <= int(h.get("bees") or 0))


def due(state: dict, now: float, bees: int = 0) -> bool:
    return not held(state, bees) and now >= float(state.get("next_at", 0.0) or 0.0)


if __name__ == "__main__":
    # ponytail: the smallest check that fails if the pure logic breaks.
    now = 1_000_000.0
    assert due({}, now)
    killed = record({}, "killed", now)
    assert killed["next_at"] == now + COOLDOWN_S
    assert not due(killed, now + 10)
    assert due(killed, now + COOLDOWN_S + 1)
    absent = record({}, "absent", now)
    assert absent["next_at"] == now + ABSENT_OPEN_S
    lost = record({}, "died", now)
    assert lost["next_at"] == now + LOST_RETRY_S
    again = record(lost, "died", now)
    assert again["next_at"] == now + 2 * LOST_RETRY_S
    assert record(record(again, "absent", now), "died", now)["next_at"] == now + LOST_RETRY_S
    assert defeated("Defeated Tunnel Bear!")
    assert defeated("defeatedtunnelbear")         # tesseract runs words together
    assert not defeated("Defeated Brown Bear!")   # must not match another bear
    assert not defeated("Defeated Tunnel Snake!")
    assert loot_steps() == [{"op": "walk", "keys": "w", "studs": 216.0},
                            {"op": "walk", "keys": "s", "studs": 324.0}]
    assert sum(s.get("studs", 0.0) for _, steps in CYCLE for s in steps) > 0
    two = record(record({}, "died", now, 41), "died", now, 41)
    assert not held(two, 41)
    three = record(record(two, "absent", now, 41), "died", now, 41)
    assert held(three, 41) and held(three) and not due(three, now + LOST_RETRY_MAX_S, 41)
    assert not held(three, 42)                    # the hive grew
    assert not held(dict(three, held=dict(three["held"], fight="older")), 41)
    print("tunnelbear: ok")
