"""The King Beetle: Natro's fight, in the lair behind the Blue Flower Field.

NATRO'S FIGHT (submacros/natro_macro.ahk ~15323-15479, read 2026-10-12): from
the Blue Flower Field, 90 then 72 studs toward the lair wall, a brief wait, a
short jump through the entrance, two camera turns, then (no helper exists for
Natro's `kingfloor.png` lair check, so this skips straight to looking) twenty
quarter-second looks for its health bar. The fight itself is a trivial one
(2,500 HP wiki, "trivial for 41 bees" -- docs/pending/brain-research-4.md
rec 3): a short back-and-right dodge while the tool swings, repeated until the
feed says it is beaten, a death, or MAX_FIGHT_S. A kill either answers the
amulet table ("Keep Old", run_farm's `answer_the_amulet`) or walks
`nm_loot(13.5, 7, "right", 1)`'s pattern.

Natro's baby-love buff wait and its `kingfloor.png` lair confirm have no
vision helper here and are skipped; the walk proceeds on timing alone, the way
act/crab.py already does for Natro's own pixel checks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from ..brain import mobtable

TILE = 4.0                        # studs in one of Natro's tiles (lib/Walk.ahk)
# nm_Move(ms*MoveSpeedFactor, key) always covers ms*18/1000 studs, whatever the
# character's real speed (MoveSpeedFactor := 18/MoveSpeedNum cancels it out --
# scripts/transpile_natro_patterns.py's STUDS_PER_NATRO_UNIT, same formula).
STUDS_PER_MS = 18.0 / 1000.0

COOLDOWN_S = mobtable.respawn("king_beetle")  # 24h (Natro's LastKingBeetle; data/world/timers.yaml); mobs.yaml via brain/mobtable (K7)
MAX_FIGHT_S = 120.0               # safety cap; Natro's own fight is one pass (loop 1), trivial HP
ABSENT_OPEN_S = 7200.0            # not there: Natro looks again in 2 hours (its own "+7200")
# ponytail: Natro has no back-off for a LOST (not absent) fight here -- a miss
# just falls through to the next 24h cooldown unmarked -- which would retry a
# fight this hive cannot win every cycle; reuse its own 2h constant instead
LOST_RETRY_S = 7200.0
LOST_RETRY_MAX_S = 7 * 86400.0
LOOKS, LOOK_EVERY_S = 20, 0.25    # Natro's search for its health bar
MIN_BEES = 0                      # Blue Flower has no bee gate (data/knowledge/world.yaml:101)


def _walk(keys: str, studs: float) -> dict:
    return {"op": "walk", "keys": keys, "studs": round(studs, 2)}


def _ms(keys: str, ms: float) -> dict:
    return _walk(keys, ms * STUDS_PER_MS)


# THE WALK IN, from the Blue Flower Field's own landing (router: natro_out_blue_flower)
# to the lair, Natro's way (natro_macro.ahk:15330-15360). The baby-love wait and
# the kingfloor.png lair confirm are skipped (no helper).
START = (
    _ms("dw", 5000),                                    # nm_Move(5000*MSF, RightKey, FwdKey)
    _ms("w", 4000),                                      # nm_Move(4000*MSF, FwdKey)
    {"op": "camera", "direction": "right"},
    {"op": "camera", "direction": "right"},
    {"op": "pause", "seconds": 1.0},                     # Natro's Sleep 1000 before the baby-love check
    _walk("d", 5 * TILE),                                # nm_Walk(5, RightKey)
    {"op": "jump"},                                      # Space down 200ms, up (the entrance hop)
    _walk("d", 3 * TILE),                                # nm_Walk(3, RightKey)
    _walk("dw", 5 * TILE),                                # nm_Walk(5, RightKey, FwdKey)
    {"op": "camera", "direction": "left"},
    {"op": "camera", "direction": "left"},
)

# THE FIGHT (natro_macro.ahk:15399-15451): the "keep fighting" leg of each
# check (not the per-check retreat distance, which only matters once the
# health bar is already gone -- run_farm's outcome() plays that part, the way
# it already does for the crab). Repeated until killed, a death, or
# MAX_FIGHT_S.
CYCLE = (
    (0.0, (_ms("s", 2000),)),                            # nm_Move(2000*MSF, BackKey)
    (1.0, (_ms("d", 2000),)),                            # nm_Move(2000*MSF, RightKey)
    (2.0, (_ms("s", 2000),)),                            # nm_Move(2000*MSF, BackKey)
    (3.0, (_ms("d", 2000),)),                            # nm_Move(2000*MSF, RightKey)
    (4.0, (_ms("sd", 2000), _ms("sd", 2000))),           # loop 2: nm_Move(BackKey, RightKey)
    (6.0, ({"op": "camera", "direction": "left"},)),     # Sleep 500, Send RotLeft
)
CYCLE_S = 8.0


def loot_steps() -> list[dict]:
    """Natro's `nm_loot(13.5, 7, "right", 1)`: forward, a side-step, back, a
    side-step, seven times (the same pattern act/crab.py's loot_steps reads
    off nm_loot, length and reps just its own)."""
    out: list[dict] = []
    for _ in range(7):
        out += [_walk("w", 13.5 * TILE), _walk("d", 1.5 * TILE),
                _walk("s", 13.5 * TILE), _walk("d", 1.5 * TILE)]
    return out


def defeated(feed_text: str) -> bool:
    """The feed's word that it is beaten. Both "king" and "beetle" are
    required -- Blue Flower's own Rhino Beetle is defeated constantly while
    gathering there, and "beetle" alone would misread that as the boss."""
    said = "".join(str(feed_text or "").lower().split())
    return "defeated" in said and "king" in said and "beetle" in said


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
    """The state after a try: "killed", "absent", or a lost fight ("died", "time")."""
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
    assert defeated("Defeated King Beetle!")
    assert defeated("defeatedkingbeetle")        # tesseract runs words together
    assert not defeated("Defeated Rhino Beetle!")  # must not match the field's own mob
    assert not defeated("Defeated King Scorpion!")
    assert len(loot_steps()) == 7 * 4
    assert sum(s.get("studs", 0.0) for _, steps in CYCLE for s in steps) > 0
    print("beetle: ok")
