"""The Commando Chick: Natro's fight from the edge of its hideout's last stair,
and the captures counted toward its milestones.

WHY (feature-gap research 2026-10-12, gap #3). Its milestones are progress no
gathering buys: Glue at the 5th capture, a Gold Egg at the 10th, a Star Jelly
at the 15th, 3 Blue Extract at the 20th, 100 tickets at the 25th, a Mythic
Egg at the 50th (wiki Commando_Chick rev 448352, Commando_Chick/Drops rev
446860). It starts at 150 HP (level 3) and is under 300,000 HP for the first
36 captures (the Levels table), it comes back 30 minutes after a capture, and
its HP is SAVED when it flees -- a fight cut short is not lost. Every player
has their own. The vines in front of its hideout are cut on this account (the
owner, 2026-10-12 20:50); the wiki: "they will never regrow back".

WHERE. The Commando_Chick's_Hideout page (rev 449613): past the obby "between
the Blue HQ and the Wealth Clock". NATRO'S WALK (submacros/natro_macro.ahk
15642-15919, read 2026-10-12, MoveMethod "Walk"): nm_gotoRamp, then 44.75
tiles back-left, 42.5 left, 8.5 back, 22.5 left, RotLeft 2 -- the very opening
of Natro's own Brown Bear walk (paths/gtq-brown.ahk), which landed 1 of 49
for this bot (scripts/transpile_natro.py DERIVED_ROUTES "brown_bear": its
frames stand against a green wall, var/routes/attempt-469 leg 08). The Wealth
Clock's walk (gtc-clock.ahk) reaches the same 22.5-tile left leg ("ladder 2")
and RotLeft 2 by corner aligns, and from there both of Natro's walks go on
with the same 40 tiles forward; the bot's natro_out_wealth_clock landed 182
of 197 (var/skill_stats.json, the last 10 all landed), and after its 20th
step the frame stands in the Clover Field facing the Brown Bear, the Wealth
Clock and, on the left, the Blue HQ (var/routes/attempt-899/152603-*-20-
camera-left.jpg). So the walk here is that route up to VIA_UPTO, then
Natro's own legs from its `nm_Walk(27, FwdKey)` on: START.

THE FIGHT, Natro's way, which is the wiki's (Commando_Chick's_Hideout,
"Strategy"): on the edge of the last stair, "where one of your body parts is
inside of the hideout", the chick does not flee "and the player's bees can
defeat the Commando Chick whilst they take no damage" -- the Glitches page
(rev 448373): there it cannot touch the player; its grenades still can (50
each, contact 20; wiki Commando_Chick). That matters here: the Tunnel Bear
killed this character 6 s after arrival (var/tunnelbear/20261012-172215).
Natro walks in 5 tiles and back 9, waits 4 s, hops and steps half a tile
back (ENTER); when the feed says the chick fled it walks ENTER again, four
times at most (15782-15810). Then twenty quarter-second looks for its health
bar (15819-15828), and the fight: the tool swinging, the character still,
until the feed's capture, a death, ChickTime (15 minutes, Natro's default,
15860-15865), or its health bar unseen for a twelfth five-second spell
(15874-15896: over 10 strikes, counted from 0, Natro takes for a capture).

SKIPPED, with the reason. Natro's `loop 4 {Send ZoomIn}` before the looks:
it zooms OUT five after every reset (natro_macro.ahk:11287-11288, 11347),
so its four in come back near the default zoom this bot never leaves --
the view vision/nameplate is measured on. Its kill-time estimate
(nm_KillTimeEstimation) only feeds its GUI. No loot walk: "Commando Chick
tokens will be automatically collected when they fade away" (the wiki).

COUNTED. A capture is counted only when the feed says so ("Defeated ...",
"Captured ...": the Mondo Chick, the other chick that fights, prints both,
wiki Mondo_Chick rev 448404; the Commando's own words are unmeasured). A bar
lost for good is scheduled like a capture, as Natro does, but kept out of the
count ("gone"). Captures before this bot are not known: `captures` in
var/commando.json can be set by hand.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from ..brain import blenderplan
from ..brain import value
from ..brain import mobtable

TILE = 4.0                        # studs in one of Natro's tiles (lib/Walk.ahk)

COOLDOWN_S = mobtable.respawn("commando_chick")  # 30 min (wiki; Natro's LastCommando, natro_macro.ahk:15643); mobs.yaml via brain/mobtable (K7)
MAX_FIGHT_S = 900.0               # Natro's ChickTime default, 15 minutes (natro_macro.ahk:597)
# A LOSS WAITS NATRO'S 30 MINUTES, doubling each time in a row, a week at most
# (act/tunnelbear's back-off). NOT ABSENT HERE: the chick is always there
# unless captured in the last 30 minutes, so no bar on arrival is the walk's
# or the eye's failure, and it is backed off like one.
LOST_RETRY_S = 1800.0
LOST_RETRY_MAX_S = 7 * 86400.0
LOOKS, LOOK_EVERY_S = 20, 0.25    # Natro's search for its health bar (15819-15828)
ENTER_TRIES = 4                   # Natro's walks in again after "fled" (A_Index = 5 gives up)
STRIKE_S, STRIKES = 5.0, 11       # 20 looks of 250 ms unseen is a strike; the 12th is "gone"
GONE_LOOKS = 6                    # ...then 3 s of the feed for its "Captured" (run_farm)
CHECK_EVERY_S = 1.0               # a look at the bar and the feed while it fights
KEEP_EVERY = 5                    # ...and every 5th kept as a frame
# THE KNOCK-OUTS ARE NOT THE STAND SPOT. MEASURED 2026-10-14, the three fights
# that ended "died" (var/commando/20261013-205404, 20261014-062525, -163325)
# against the six that ended "killed"/"gone": the corridor's blue walls about
# the doorway sit at the same depth in every "arrived" frame (the doorway's
# centre 776-926 px across in both groups), and within each fight they do not
# move a pixel from "arrived" to the last frame before the death: the character
# never left the stair's edge. Each death was its own bar (vision/hurt.
# own_health) draining from about full to nothing in 6-15 s -- 16:35 0.91 at
# 97.7 s, 0.09 at 109.6, out at 113; 20:56 0.99 -> 0.81 (154.5) -> 0.22 (160.2);
# 06:29 0.51 at 216, out by 223 -- while the chick's white BLOCK egg sat in the
# doorway on top of it (0103.2-fight, 0154.5-fight, 0216.0-fight). In the 47
# fighting minutes of the other six the bar only stepped down 20-25% at a time
# (its grenades) and grew back, 0.40 at the lowest. The 5-s frames never caught
# the egg arriving, so under FILM_BELOW every look is kept ("hurtN.NN").
# ponytail: filmed, not fought: a step back from the stair is unmeasured (the
# obby's lava is behind it); choose one from those frames.
FILM_BELOW = 0.6

# THE WAY THERE: the Wealth Clock's route through its 20th step (index 19,
# the second RotLeft), where Natro's Brown Bear, Clock and Commando walks meet.
VIA = "natro_out_wealth_clock"
VIA_UPTO = 19

# A STRONG HASTE IS WAITED OUT AT VIA'S LAST WALL, not only at the obby's edge.
# MEASURED 2026-10-14 over the 14 tries on these OBBY legs (var/routes attempts
# 964-1003, the "-commando_start-11-pause" frame just before the first jump):
# all 9 that crossed stood at the "?" circle's front rim, the lava's red line at
# the character's feet; all 5 that died there (23:05, 01:58, 07:45, 10:25, 15:10)
# stood in the circle's middle with brown floor between it and the first step,
# jumped a step short and were in the lava by -15..-19. All 5 walked VIA under
# Haste x10 ("walking 2.0x", 01:57 2.25x with a polar morph; 10:23 x10 since
# 10:22:00); of the 9, eight at 1.1-1.57x, one 2.02x (06:26, x8 + a bear). Haste x10
# walks ~1.68x (vision/buffs' measured 6.8% a stack), so a leg divided by 2.0 is
# ~16% short, and after VIA's RotLeft 2 its last legs ARE the obby's forward
# axis: the d7 and the a90 ("ladder 2", ~3.6 tiles short at x10) after the a30
# into the hedge, dead reckoning nothing in OBBY aligns (only sideways). The
# obby-edge wait (run_farm, 2026-10-14 10:35) comes after that error is made:
# 15:10 died behind it. So VIA's d7 (CALM_AT) is a `calm: "always"` leg
# (act/routes): standing at the hedge, keys up, until the factor is
# GLIDE_CALM_FACTOR (1.25) or less, GLIDE_CALM_MAX_S (35 s since 2026-10-21)
# at most -- by the buff lines, those five would have stood about 6 s or less.
# Not GLIDE_CALM_STRICT's 1.05 A/B: 8 of the 9 that crossed walked at 1.1-1.57x.
CALM_AT = 15


def via(steps) -> list[dict]:
    """VIA's steps through VIA_UPTO, copied, with its d7 after the hedge calm."""
    out = [dict(x) for x in (steps or ())][:VIA_UPTO + 1]
    if len(out) > CALM_AT and out[CALM_AT].get("op") == "walk":
        out[CALM_AT]["calm"] = "always"
    return out


def _walk(keys: str, tiles: float) -> dict:
    return {"op": "walk", "keys": keys, "studs": round(tiles * TILE, 2)}


def _pause(seconds: float) -> dict:
    return {"op": "pause", "seconds": seconds}


JUMP = {"op": "jump"}             # Natro's Space down, HyperSleep(50), Space up

# IN AND BACK OUT ONTO THE STAIR'S EDGE (natro_macro.ahk:15719-15727, and the
# same walk again at 15793-15801 after "fled").
ENTER = (
    _walk("w", 5), _pause(0.05),                         # nm_Walk(5, FwdKey)
    _walk("s", 9), _pause(4.0),                          # nm_Walk(9, BackKey), Sleep 4000
    JUMP, _walk("s", 0.5), _pause(1.5),                  # hop, nm_Walk(0.5, BackKey)
)

# FROM THE CLOVER FIELD (VIA_UPTO) TO THE STAIR: Natro's legs after RotLeft 2
# (15658-15660), its corner align against the hideout's wall and its obby for
# MoveSpeedNum < 34 (15687-15718: move.walkspeed is 28, 32.2 with a gifted
# Hasty), then ENTER.
OBBY = (
    _walk("w", 27), _walk("aw", 12), _walk("w", 11),     # nm_Walk 27 Fwd, 12 Left+Fwd, 11 Fwd
    _walk("a", 10), _pause(0.05),                        # corner align: 10 left,
    _walk("d", 6), _pause(0.05),                         # 6 right,
    _walk("a", 2), _pause(0.05),                         # 2 left
    # TO THE PIT'S EDGE: 2.5 tiles, not Natro's 7. MEASURED 2026-10-13 05:12
    # (var/routes/attempt-946/051222-commando_start-09, -10, -11): after the
    # align the character stood on the white "?" circle with the pit's near
    # edge about 3 tiles ahead (by eye), and Natro's 7 walked it into the lava
    # (try 1, 03:58, died at the same point in the legs). This bot reaches the align
    # by the Wealth Clock's route, not Natro's own walk, and stands about
    # 4 tiles further on; 0.5 tile is left as margin before the first jump.
    # AN EXPERIMENT: a death here holds the fight again (OBBY_ID).
    # 2.5 TRIED 2026-10-13 11:18 (var/routes/attempt-958/111842-commando_start-10
    # to -16): it stopped at the pit's edge, the lava just ahead, but the jump
    # from there landed in it. Natro walks right to the edge; 3 tiles now.
    _walk("w", 3), _pause(0.75),
    JUMP, _walk("w", 5.5), _pause(0.75),
    JUMP, _walk("w", 6), _pause(0.75),                   # Loop 3
    JUMP, _walk("w", 6), _pause(0.75),
    JUMP, _walk("w", 6), _pause(0.75),
    _walk("w", 1),
    JUMP, _walk("w", 6), _pause(0.75),
)
START = OBBY + ENTER

# A DEATH IN THE OBBY HOLDS THE FIGHT until a person deletes "held" from
# var/commando.json, or OBBY's legs change (a fix: the hold is keyed to them).
# MEASURED 2026-10-13, two tries, two deaths before the stair:
# - 05:11 (var/routes/attempt-946, a frame after every leg): step 06 (d 6) ends
#   against the stone wall on the right and step 04 (a 10) against the blue
#   wall on the left, so the corner align works SIDEWAYS. Step 09 (its end)
#   stands on the white "?" circle, and the pit's near edge is just past the
#   circle -- by eye some 3 tiles ahead, where Natro's next leg walks 7. Step 10
#   (w 7) ends IN the lava, against the first step's face; step 11 (0.75 s)
#   is the body in it with "You died!" in the feed. It died walking, before
#   any jump, so Natro's 750 ms and keyless Space (c) are not it.
# - 03:58 (run-945.log): the Haste was waited out before VIA, "buff bar: no
#   haste" at 03:58:49 and no other buff line until the death (lines are
#   narrated on change); the mob-sighting frames (var/incidents/20261013-
#   035919-mob-sighting) show a bar with no Haste icon. So a Haste count
#   misread (b) is not needed for it; at 05:12 the bar read Haste x1 and the
#   odometer walked 1.1x, as Natro's Walk() would.
# - Nothing in OBBY aligns FORWARD: w 27, aw 12 and w 11 are dead reckoning
#   from VIA's RotLeft, which is the Wealth Clock's (after its own corner
#   aligns and "ladder 2", cut by a mob in both tries: a ladder leg resumed),
#   not Natro's Commando walk's (no aligns, the one gtq-brown shares, 1 of 49
#   for this bot). Why the obby begins some 4 tiles too far forward is NOT
#   proven (a); so no leg is re-tuned blind, and the fight is held instead of
#   walking into the lava every hour.
OBBY_ID = hashlib.sha1(json.dumps(OBBY).encode()).hexdigest()[:8]


# THE WORDS SIDE BY SIDE, not anywhere in the strip: the feed is read as one
# line of every pill (vision/feed.read_text), and the walk through the Clover
# Field leaves "Defeated Rhino Beetle!" in it beside "Commando Chick fled!".
# "commando" is the chick's own (the Commander Bee is "commander").
CAPTURED = re.compile(r"(defeated|captured).{0,3}commando|commando.{0,14}captured")
FLED = re.compile(r"commando.{0,8}(fled|gotaway)")


def _said(feed_text: str) -> str:
    return "".join(str(feed_text or "").lower().split())   # tesseract runs words together


def defeated(feed_text: str) -> bool:
    """The feed's word that it is captured; a flee is never a capture."""
    return bool(CAPTURED.search(_said(feed_text)))


def fled(feed_text: str) -> bool:
    """"Commando Chick fled! (HP Saved)", or the glitch's "Commando Chick got
    away!" (wiki Commando_Chick, Trivia): out of reach, its HP kept."""
    return bool(FLED.search(_said(feed_text)))


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


def record(state: dict, result: str, now: float, took: float | None = None) -> dict:
    """The state after a try: "killed" (the feed's capture, counted), "gone"
    (its bar lost for good: Natro's capture, not counted), or a loss
    ("absent", "fled", "died", "time", "walk", "obby": died in OBBY, which
    holds the fight when the try before died there too). `took`: the
    visit's seconds."""
    out = dict(state)
    row = {"at": now, "result": result}
    if took is not None:
        row["took"] = round(float(took), 1)
    out["tries"] = (list(state.get("tries") or []) + [row])[-20:]
    # THE HOLD NEEDS TWO OBBY DEATHS IN A ROW: one is a slip, two are the legs.
    # MEASURED 2026-10-13: the hold came in when these legs' forerunners died
    # 2 of 2; after the leg fixes 4 of the next 5 tries crossed (3 captures),
    # and the 23:05 death alone (var/commando/20261013-230357) held the fight
    # for the night.
    prev = list(state.get("tries") or [])[-1:]
    if result == "obby" and prev and prev[-1].get("result") == "obby":
        out["held"] = {"at": now, "obby": OBBY_ID}
    if result in ("killed", "gone"):
        out["killed_at"] = now
        out["next_at"] = now + COOLDOWN_S
        if result == "killed":
            out["captures"] = int(state.get("captures") or 0) + 1
        return out
    lost = 0
    for t in reversed(out["tries"]):
        if t.get("result") in ("killed", "gone"):
            break
        lost += 1
    out["next_at"] = now + min(LOST_RETRY_S * 2 ** (lost - 1), LOST_RETRY_MAX_S)
    return out


def held(state: dict) -> bool:
    """A death in these OBBY legs, not yet cleared (see OBBY_ID)."""
    h = state.get("held")
    return isinstance(h, dict) and h.get("obby") == OBBY_ID


def due(state: dict, now: float) -> bool:
    return not held(state) and now >= float(state.get("next_at", 0.0) or 0.0)


# ---- what a capture is worth ------------------------------------------------
# THE DROPS, capture by capture (wiki Commando_Chick/Drops rev 446860,
# "Captures 1-50"; one player's reads -- Honey From Tokens scales the honey).
# Every capture gives a ticket but the 5th (none) and the 25th (a hundred);
# its treats, seeds, pineapples and bitterberries are left out (unpriced).
HONEY = (
    2_400, 1_500, 6_500, 10_000, 13_000, 25_000, 35_000, 28_000, 42_000, 300_000,
    100_000, 120_000, 135_000, 170_000, 100_000, 130_000, 150_000, 200_000, 250_000, 1_000_000,
    1_100_000, 900_000, 1_800_000, 2_000_000, 2_300_000, 2_700_000, 3_000_000, 4_000_000,
    4_500_000, 5_000_000, 5_750_000, 7_400_000, 7_400_000, 9_000_000, 10_500_000, 10_200_000,
    11_000_000, 14_500_000, 13_500_000, 55_000_000, 12_500_000, 19_000_000, 21_000_000,
    22_000_000, 25_000_000, 28_750_000, 38_000_000, 25_000_000, 25_000_000, 25_000_000,
)
TICKETS = {5: 0, 25: 100}
EXTRA = {3: {"stinger": 1}, 5: {"glue": 1}, 9: {"red_extract": 2}, 10: {"gold_egg": 1},
         12: {"stinger": 3}, 15: {"star_jelly": 1}, 20: {"blue_extract": 3},
         27: {"ant_pass": 1}, 30: {"stinger": 10}, 35: {"ant_pass": 1}, 36: {"ant_pass": 1},
         40: {"stinger": 10, "ant_pass": 10}, 46: {"ant_pass": 1}, 50: {"mythic_egg": 1}}

# HONEY A UNIT, brain/value's (honey; a ticket at the Ticket Shop's 100,000)
# and what the rest would cost to get another way, from data/knowledge:
# a Gold Egg is 100 tickets at the Ticket Tent and a Stinger 10 at the Stinger
# Shop (goals.yaml gold_egg, stinger); Glue and the extracts are a Blender
# craft of 10 Royal Jelly (blenderplan.RECIPES) at the Royal Jelly Shop's
# opening 250,000 (items.yaml royal_jelly_shop) -- the berries or gumdrops on
# top unpriced, so a floor. The Star Jelly, the Mythic Egg and Ant Passes no
# shop sells for honey or tickets: UNPRICED, named, never 0 (value.py's rule).
PRICES = dict(value.PRICES, royal_jelly=250_000.0)
PRICES.update(gold_egg=100 * PRICES["ticket"], stinger=10 * PRICES["ticket"],
              **{x: 10 * PRICES["royal_jelly"] for x in ("glue", "red_extract", "blue_extract")})


def drops(n: int) -> dict:
    """Capture `n`'s goods; {} past the table."""
    if not 1 <= n <= len(HONEY):
        return {}
    return {"honey": HONEY[n - 1], "ticket": TICKETS.get(n, 1), **EXTRA.get(n, {})}


def worth(first: int, last: int) -> tuple[float, list[str]]:
    """Captures `first`..`last` in honey (PRICES), and the goods left unpriced."""
    total, unpriced = 0.0, []
    for n in range(first, last + 1):
        for good, k in drops(n).items():
            if good in PRICES:
                total += PRICES[good] * k
            elif k and good not in unpriced:
                unpriced.append(good)
    return total, unpriced


def outlook(state: dict, rho: float) -> str:
    """The plan line: captures the feed has read, the next milestones, and a
    visit priced against gathering (value.q) -- the run to the next milestone
    averaged over its captures, at the visits' measured seconds and share
    captured. Advice only: nothing waits on it (the owner asked for the
    fights, and the unpriced Star Jelly and Mythic Egg are what they are for)."""
    n = int(state.get("captures") or 0)
    ahead = [m for m in sorted(blenderplan.COMMANDO_MILESTONES) if m > n]
    words = f"Commando Chick {n} captured"
    if not ahead:
        return words
    words += ": " + ", ".join(f"{blenderplan.COMMANDO_MILESTONES[m].split(' -- ')[0]} at {m}"
                              for m in ahead[:3])
    v, unpriced = worth(n + 1, ahead[0])
    if not drops(ahead[0]):
        return words
    words += (f"; captures {n + 1}-{ahead[0]} pay >= {v / 1e6:,.1f}M honey"
              + (f" + {', '.join(g.replace('_', ' ') for g in unpriced)}" if unpriced else ""))
    q, _unpriced, took, won = visit_q(state, rho)
    if q is None:
        return words + " (no visit timed yet)"
    return words + f", Q {q / 1000:+,.0f}k a visit ({took:.0f} s, {won:.0%} captured)"


def visit_q(state: dict, rho: float) -> tuple:
    """(Q a visit or None, goods unpriced, median seconds, share captured): the
    run to the next milestone averaged over its captures, priced against
    gathering (value.q). None when nothing is ahead, no visit is timed or no
    gathering rate is known."""
    n = int(state.get("captures") or 0)
    ahead = [m for m in sorted(blenderplan.COMMANDO_MILESTONES) if m > n]
    tries = [t for t in (state.get("tries") or []) if t.get("took")]
    if not ahead or not drops(ahead[0]) or not tries or not rho:
        return None, [], 0.0, 0.0
    v, unpriced = worth(n + 1, ahead[0])
    took = sorted(float(t["took"]) for t in tries)[len(tries) // 2]
    won = sum(t.get("result") in ("killed", "gone") for t in tries) / len(tries)
    return value.q(v / (ahead[0] - n), won, took, rho), unpriced, took, won


if __name__ == "__main__":
    # ponytail: the smallest check that fails if the pure logic breaks.
    now = 1_000_000.0
    assert due({}, now)
    got = record({}, "killed", now, took=95.0)
    assert got["next_at"] == now + COOLDOWN_S and got["captures"] == 1
    assert got["tries"][-1]["took"] == 95.0
    assert "captures" not in record({}, "gone", now) and record({}, "gone", now)["next_at"] == now + COOLDOWN_S
    lost = record({}, "absent", now)
    assert lost["next_at"] == now + LOST_RETRY_S
    assert record(lost, "fled", now)["next_at"] == now + 2 * LOST_RETRY_S
    assert record(record(lost, "killed", now), "died", now)["next_at"] == now + LOST_RETRY_S
    assert defeated("Defeated Commando Chick!") and defeated("capturedcommandochick")
    assert not defeated("Commando Chick fled! (HP Saved)") and fled("Commando Chick fled! (HP Saved)")
    assert fled("Commando Chick got away!") and not defeated("Defeated Mondo Chick!")
    assert not fled("Defeated Commander Bee") and not defeated("Defeated Rhino Beetle!")
    assert not defeated("Defeated Rhino Beetle! (+1 Battle Point) Commando Chick fled! (HP Saved)")
    assert sum(s["op"] == "jump" for s in START) == 6 and START[-len(ENTER):] == ENTER
    slip = record({}, "obby", now)
    assert not held(slip) and due(slip, now + LOST_RETRY_S)
    stuck = record(slip, "obby", now)
    assert held(stuck) and not due(stuck, now + LOST_RETRY_MAX_S)
    assert not held(record(record(slip, "killed", now), "obby", now))
    assert due(dict(stuck, held={"at": now, "obby": "older legs"}), now + 2 * LOST_RETRY_S)
    v, unpriced = worth(1, 10)
    assert v == 463_400 + 9 * 100_000 + 1_000_000 + 2_500_000 + 5_000_000 + 10_000_000 and not unpriced
    assert worth(11, 15)[1] == ["star_jelly"] and drops(51) == {}
    print(outlook({}, 3747.0))
    print(outlook(record({}, "killed", now, took=120.0), 3747.0))
    print("commando: ok")
