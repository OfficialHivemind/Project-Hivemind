"""Vic hop, our way (ROADMAP M5): the pieces glued into one loop.

THE LOOP. A night (vision/night) in the server the bot is in -- its private
one, or a public one brain/hop picked off the server list -- then the
lookout over the night fields of act/vicious `tour` (the level gate), the
spike by sight (vision/vicspike), a walk to the spike that looks again after
every step, the fight with act/vicious's 16-stud dodge square until a kill, a
death or MAX_FIGHT_S (vicious.record backs off after a loss), then brain/hop
decides: hop on, go home or stay. This module holds what is new in that
loop -- when a seen spike is worth walking to, the walk to it, and the
counters -- and every step that moves is LOOK-ONLY while VIC_HOP_LIVE is
False: the run log says "vic hop would: ..." and the hunt walks as before.

WHY A NIGHT GATE ON THE SPIKE. MEASURED 2026-10-27 over the 37 kept hunts
(var/vicious, 878 frames; docs/pending/hopvic.md; the
replay in tests/unit/test_vichunt.py): vicspike.find hits a frame in 15 of
the 37 hunts, and only 2 of those hold a real spike (2026-10-15 07:05,
2026-10-23 20:42; scripts/score_vicspike.py SPIKES). The hunts run on past
dawn, and most false hits stand in day frames. Walking only to a spike seen
in a frame that is itself night (vision/night is_night: the sky, else the
floor) keeps both real ones and leaves 2 false hunts of 35 (a player's name over
the grass, a 16 px glint), from 13. The spike is a night thing (wiki
Rogue_Vicious_Bee: "a high chance to spawn when it turns nighttime").

WHY NOT "HOP UNTIL IT IS NIGHT". Night is ~10% of the clock (MEASURED,
vision/night: 406 of 3,957 pad frames; 265 of 2,209 cannon-flight skies), a
fresh join takes 42 s (MEASURED, median "in game after" of 667 joins in
var/night/run-*.log). Modelled with the wiki's 2:35 night and a 10-30 min day
(ASSUMED uniform; docs/pending/hopvic.md, model off-repo): hopping on at
once from every day server costs ~13 hops per usable night, and with the 3 hops a night
(server.hop_per_night) finds one 21% of the time; waiting in the server
for its night (server.hop_minutes) finds one 75% of the time at 6 min and
99% at 15 min. So a day server is waited in, as brain/hop already does.
"""
from __future__ import annotations

from pathlib import Path

from ..brain import hop

# act/chase (numpy, cv2) is imported where the walk needs it: the counters
# below are read by Telegram /report, a long-lived process that stays small.

# LOOK-ONLY: the walk to a seen spike is said ("vic hop would: ..."), not done.
VIC_HOP_LIVE = False
# One step of the walk to the spike, a look after each. ASSUMED: a third of
# a token chase step's ground at 28 studs/s (act/chase STEP_SECONDS 0.35 =
# ~10 studs) -- the spike is touched, not passed; a calibration knob.
STEP_STUDS = 3.5
STEPS = 10                         # act/chase MAX_STEPS, its ceiling on one detour
# Looks in a row without the spike before the walk gives up on it (act/chase
# gives a lost token two looks too).
MISSES = 2


def nearest(spikes, x: float, y: float):
    """The spike nearest (x, y), or None. ponytail: no distance bound -- one
    spike stands in a field a night; add one if the live walks chase a glint."""
    return min(spikes, key=lambda s: (s.x - x) ** 2 + (s.y - y) ** 2, default=None)


def towards(spike, width: int, height: int) -> tuple[str, float]:
    """(keys, px from the character): act/chase's own steering rule."""
    from .chase import anchor_of, keys_towards
    ax, ay = anchor_of(width, height)
    dx, dy = spike.x - ax, spike.y - ay
    return keys_towards(dx, dy), (dx * dx + dy * dy) ** 0.5


def steer(spike, size: tuple[int, int], look, walk, steps: int = STEPS) -> tuple[str, int]:
    """Walk to `spike` (seen in a frame of `size`, width x height) a step at
    a time, looking after each: ("arrived" | "lost" | "steps", steps walked).
    `look()` -> (the spikes seen now, that frame's size); `walk(keys)` one step."""
    from .chase import ARRIVED_PIXELS
    w, h = size
    misses = 0
    for n in range(steps + 1):
        keys, far = towards(spike, w, h)
        if far <= ARRIVED_PIXELS or not keys:
            return "arrived", n
        if n == steps:
            break
        walk(keys)
        seen, (w, h) = look()
        found = nearest(seen, spike.x, spike.y)
        if found is None:
            misses += 1
            if misses >= MISSES:
                return "lost", n + 1
        else:
            spike, misses = found, 0
    return "steps", steps


def would_line(spike, width: int, height: int, field: str, fight_s: float, top: int | None) -> str:
    keys, far = towards(spike, width, height)
    return (f"vic hop would: walk '{keys or '-'}' to the spike at ({spike.x}, {spike.y}) in the "
            f"{field}, {far:.0f} px from the character, a look after every {STEP_STUDS:g}-stud "
            f"step ({STEPS} at most), touch it, then fight with the 16-stud dodge square "
            f"until it is beaten, a death or {fight_s / 60:.0f} min (level {top} at most) -- "
            f"look-only: VIC_HOP_LIVE off")


def plan_line(fields: list[str], public: bool, top: int | None) -> str:
    """The loop said once a hunt."""
    where = "this public server" if public else "the private server"
    return (f"vic hop would: night in {where} -- look out over the {', '.join(fields)} "
            f"(level {top} at most), walk to a spike seen at night, fight it, then "
            f"brain/hop's stay / hop on / home")


# THE COUNTERS: in var/vicious.json "count" (lifetime; "tries" keeps 20) and
# var/hop.json "arrivals". Read by the Bosses card and Telegram /report.


def counted(state: dict, result: str, spiked: bool, public: bool) -> dict:
    """The lifetime counts after one hunt (`result` as vicious.record takes
    it). A state from before the counts is seeded from its kept tries."""
    out = dict(state.get("count") or _tally(state.get("tries")))
    _add(out, result, spiked, public)
    return out


def _tally(tries) -> dict:
    out: dict = {}
    for t in tries or []:
        _add(out, str((t or {}).get("result") or ""), False, False)
    return out


def _add(out: dict, result: str, spiked: bool, public: bool) -> None:
    fought = result in ("killed", "died", "time")
    for key, on in (("hunts", True), ("public", public), ("spikes", spiked),
                    ("fights", fought), ("killed", result == "killed"),
                    ("lost", fought and result != "killed")):
        out[key] = int(out.get(key) or 0) + bool(on)


def summary(vicious_state: dict, hop_state: dict, hop_live: bool) -> str:
    """One line for the Bosses card and /report; "" before the first hunt."""
    c = vicious_state.get("count") or _tally(vicious_state.get("tries"))
    if not c.get("hunts"):
        return ""
    servers = int(hop_state.get("arrivals") or 0)
    return (f"Vicious Bee: {c['hunts']} hunts, {c.get('public', 0)} of them in public "
            f"servers. A spike seen at night in {c.get('spikes', 0)}. Fights: "
            f"{c.get('fights', 0)} ({c.get('killed', 0)} won, {c.get('lost', 0)} lost). "
            f"Public servers joined: {servers}"
            + ("" if hop_live else " (server hopping is watch only)") + "."
            + ("" if VIC_HOP_LIVE else " Walking to a seen spike is watch only."))


def summary_of(var) -> str:
    """`summary` from the bot's own files under `var` (var/vicious.json,
    var/hop.json)."""
    return summary(hop.load(Path(var) / "vicious.json"), hop.load(Path(var) / "hop.json"),
                   hop.HOP_LIVE)
