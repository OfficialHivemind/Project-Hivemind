"""Executing a recorded route the way the working Linux macro does.

Every Bee Swarm macro that actually works on any platform moves open-loop: hold
a key for a measured time and trust it. That is what BeeTuxMacro's 25 routes
are, and transpiling them gave us 17,599 studs of real recorded travel. This
module runs them.

WHY OPEN-LOOP IS THE RIGHT FIRST LAYER

It needs no calibration, no homography and no ground plane, so it works today.
The closed-loop walker is strictly better -- it measures actual displacement, so
lag, haste, slopes and knockback self-correct -- but it depends on a calibration
that needs open ground to fit. Making navigation wait on that would be putting
the upgrade before the thing it upgrades.

The SAME route data drives both. A step carries a distance in studs; the only
question is whether that distance is converted back into seconds here or
measured as it is walked. When a calibration exists, `walk_studs` replaces the
body of `_walk` and nothing else changes.

HOW THE RECORDINGS STAY WALKSPEED-INDEPENDENT

BeeTuxMacro's `wait()` scales every hold by `BASE_SPEED / WALKSPEED`, so a
recorded hold covers `seconds x 32.2` studs whatever walkspeed the recorder had.
Going the other way, holding for `studs / walkspeed` seconds covers the recorded
distance at ours. `walkspeed` is the one number this layer cannot derive, and it
is a parameter rather than a constant: a measured value from the odometer beats
the default, which is why the default is the recording speed and not a guess at
the owner's.

WHAT MAKES A ROUTE REPEATABLE

Not the distances -- the STARTING STATE. Three primitives do that work, and all
three were silently dropped by the first transpiler because they looked like
calls to routes that did not exist:

    reset        respawn at the hive, which fixes position AND heading
    shift_lock   locks the character to face the camera, so the movement keys
                 mean the same thing every run
    camera       counted taps, which set the heading before a walk

54 jumps went the same way. They are not decoration; they clear obstacles.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from ..vision.flow import BLOCKED_FLOW_PX
from ..vision.screenstate import RED_CANNON_THRESHOLD

# HOW MANY TIMES ONE WALK MAY BE RESUMED after a mob cut it short, and how
# long to wait for the coast to clear before giving up on the remainder.
#
# WHY THIS EXISTS. `watch` ends a key hold when a mob appears -- the owner
# asked for that ("i keep dying to the mantis ... when i die i loose all
# pollen") -- and the unwalked distance used to be simply lost. Every
# following step of the route then ran from the wrong place. MEASURED
# 2026-09-22: 15 to 22 walks cut short PER RUN, against recorded routes whose
# whole design is exact distances; the walk home missed the hive every time
# and a 656,538-pollen backpack had to be banked by rejoining instead.
#
# Natro's own paths make this worse to get wrong, not better: they deliberately
# OVERSHOOT into walls to normalise position ("nm_Walk(35, RightKey) ;walk to
# ramp"), so a walk that stops early does not just fall short, it lands
# somewhere the rest of the path was never written for.
#
# The wait is a little longer than `brain.threat.COOLDOWN_SECONDS` (8.0), so a
# single sighting has stopped firing before the remainder is walked.
RESUME_ATTEMPTS = 3
# THE WORDS A ROUTE STOPS WITH WHEN A MOB LEFT PART OF A LEG UNWALKED, as a
# name other modules can test for, the way CANNON_MISS is. The remainder used
# to be noted and dropped while the route walked on from the wrong place.
# MEASURED (audit 2026-09-25, var/night): natro_out_strawberry's `a` leg left
# 1.1-1.4 s of 4.8 s unwalked in runs 337, 338, 339 and 344, and those trips
# "left the hive" into the Spider (run-338 23:11:17, then died there) or the
# Dandelion field (run-339 23:34:14). And `coast` never resumed at all: the
# 432-stud coast of natro_home_pine_tree (15.4 s at walkspeed 28) took 5, 16,
# 16, 2, 2 and 1 s between its frames in var/routes/attempt-363..366, and the
# three cut ones ended in a rejoin with a full bag. So the route now stops
# with this reason, and nav.journey does not blame the pose for it.
UNWALKED = "left unwalked"
# AND THE WORDS WHEN THE OWNER'S TAKE OVER ENDED IT: his hands moved the
# character, so where the route stopped says nothing about the route
# (brain/controls.GuardedInput; nav.journey does not blame the pose for it).
OWNER_TOOK = "the owner took the controls"
# AND WHEN A PAUSE HELD BACK AN E the route meant to press: GuardedInput
# drops a waited E (brain/controls.STALE_AFTER_A_WAIT), because the panel the
# guard read for it is from before the Pause, and the owner may have walked
# the character anywhere since. The route stops there rather than fly or walk
# on as if it had boarded, and nav.journey retries it without moving the pose.
HELD_BACK = "a Pause held back its E"
# Escapes for the menu under the confirmation, each one only while the HUD
# reads absent. Two, so one pressed on a false "absent" is undone by the next.
MENU_EXTRA_ESCAPES = 2
# Six hive pads in the row. See _hive_offset.
MAX_HIVE_SLOT = 6
# A RAMP READING ROUNDS UP FROM .2, because the two errors are not alike. A slot
# one too big walks 36.8 studs more into the ramp corner it was walking to
# anyway -- Natro's own walks home push 35 tiles into it to square up -- and
# stops in the same place; one too small stops short of the corner, and every
# route out begins from there (2026-10-08 03:05: slot 2 trusted, the leg
# stopped in front of the honeycomb, var/routes/attempt-754 against -681).
# MEASURED: one pad read 2.4, 2.7, 2.9, 3.0, 3.2, 3.3 at the ramp.
SLOT_ROUND_UP = 0.8
SETTLE_TIMEOUT = 9.0
SETTLE_POLL = 0.25

BASE_SPEED = 32.2          # studs per recorded second (BeeTuxMacro utils.sh)

# Timings copied from BeeTuxMacro's utils.sh rather than invented.
SHIFT_LOCK_BEFORE, SHIFT_LOCK_AFTER = 0.3, 0.1
CAMERA_GAP = 0.1
RESET_SETTLE = 7.5         # it waits this long for the respawn to finish
MENU_SETTLE = 0.5          # for the menu or the confirmation to appear
# THE STREAM'S HEAD START over the menu (`_say_menu`, DESIGN 8ec). With the
# stream's own picture the word always wins: it crosses the GUI socket in
# about a millisecond, and a captured frame is shown 25 ms after its capture
# at the soonest (DESIGN 8eb, MEASURED over 3,313 frames). With the key
# colour, OBS shows the game live, so the stream window has to have painted
# its cover, and OBS captured it, before Roblox draws the menu: a repaint and
# a window capture are a 60 Hz frame each, and Roblox draws the menu a frame
# or two after the key. NOT MEASURED end to end; 100 ms is about three times
# that sum, and costs a reset 0.1 s.
MENU_WARN_S = 0.1
HOP_RISE, HOP_SETTLE = 0.56, 1.0   # BeeTuxMacro's slot-hop timings
# THE RED CANNON, Natro Macro's way: `nm_gotoCannon` as its field paths run it
# (submacros/natro_macro.ahk, GPLv3, pinned 094f9c7b: the gtf-*.ahk paths are
# built by `nm_createPath` with `nm_PathVars`, :20353, whose copy is
# :20371-20433). From the ramp corner `nm_gotoRamp` leaves it at, it hops ONCE
# -- space and right down, 100 ms, space up (:20381-20383), right for two
# tiles (:20384), forward and right for a tile and a half (:20385) -- then
# HOLDS RIGHT and looks for the prompt the whole time (:20386-20401), for
# CANNON_HOLD_SECONDS. Right comes up the moment it shows, and then the
# overrun check: half a second, look again, else a tile and a half left, nine
# times (:20403-20423; `hiverow.find_along_row` looks once more after the
# ninth step, which Natro does not). The figures are Natro's; the looking is
# ours, in the same place: Natro searches the top-centre 400x125 of the
# window (:20392), and the template's box (vision/screenstate.RED_CANNON_AT)
# is x 841-1148, y 0-134 of 1920x1080.
#
# THIS USED TO HOP TEN TIMES, AND THAT IS WHY IT STOPPED WORKING. The first
# reading (2026-09-22) took Natro's outer `Loop 10` -- ten ATTEMPTS, each
# failure followed by a reset and `nm_gotoRamp` (:20379, :20425-20429) -- for
# ten hops, and its 10-second timer for a 2-second wait standing still with
# every key up. Each extra hop is another diagonal forward, so the approach
# worked only while hop 3 happened to land on the pad: MEASURED in
# var/night/run-*.log, 26 of the 27 approaches that ever reached the cannon
# did it "after 3 hop(s)" (one, run-364, after 2), and since the last of those
# (run-306, 09-23 07:04) it reached the cannon once in 14 tries, to run-407's
# miss at 2026-09-25 23:46. The frames show how thin that was: the pad's blue
# ring tops out at y 774-836 in the hop-2 frames of every success and at
# 841-891 in every clean-start miss (salvage/cannon_investigation.json). A
# hold that ends on sight does not care where the hops land. DESIGN 8dl.
TILE_STUDS = 4.0
CANNON_HOP_JUMP_S = 0.1           # Sleep 100 (:20382)
CANNON_HOP_RIGHT_TILES = 2.0      # nm_Walk(2, RightKey) (:20384)
CANNON_HOP_FWD_TILES = 1.5        # nm_Walk(1.5, FwdKey, RightKey) (:20385)
CANNON_HOLD_KEY = "d"             # Send "{" RightKey " down}" (:20386); RightKey is d (:154)
# `f := s+100000000` (:20389) in GetSystemTimeAsFileTime's 100 ns units: ten
# seconds, the same reading as act/hiverow.HOLD_SECONDS. (The macro's own
# copy, :11560, allows twenty; the field paths run this one.)
CANNON_HOLD_SECONDS = 10.0
# How often the prompt is looked for while right is held: the age at which
# run_farm's `cached_capture` takes a new frame (`now - recent["at"] > 0.04`),
# so a faster poll only re-reads the same picture. Natro's loop has no sleep
# at all; one look costs 1.55-1.59 ms (vision/screenstate.RED_CANNON_TEMPLATE).
CANNON_POLL_S = 0.04
CANNON_OVERRUN_CHECKS = 9         # Loop 10 with `if (A_Index = 10)` giving up (:20405-20410)
CANNON_OVERRUN_SETTLE_S = 0.5     # Sleep 500 (:20412)
CANNON_OVERRUN_STEP_TILES = 1.5   # nm_Walk(1.5, LeftKey) (:20420)
CANNON_PROMPT_WORD = "cannon"
# THE RESPAWN'S RETURN IS CHECKED, NOT ASSUMED. MEASURED 2026-09-26 20:12:09,
# attempt 469 (var/respawn/201209-unknown.jpg): after Return and the whole
# RESET_SETTLE the confirmation "Are you sure you want to respawn your
# character?" was still on screen, the bot took itself to be "at the spawn
# point", the dialog hid the HUD, and 60 s later the run stopped.
#
# ...BUT ONLY ONCE THE RESPAWN HAS HAD ITS TIME. The first version looked
# again 0.6 s after Return, and at 23:02:51 and 23:02:58 (attempt 478) it
# "backed out of the menu rather than believe it respawned" twice in a row --
# while the single Return and RESET_SETTLE had confirmed the pad 58 times in
# 63 (docs/pending/resources.md). A dialog seen that soon is most likely still
# on its way out. So the look is after RESET_SETTLE, as the 20:12 frame was;
# still verifiably up then, Return is pressed once more (exactly as safe as
# the first) and the settle waited again, and only then is the menu backed
# out of. The frame it was still up on is kept (`snapshot`, reset-stuck).
RESET_ENTER_RETRIES = 1
# AND THAT ONCE MORE IS A CLICK on the Respawn button when it can be found
# (vision/screenstate.respawn_button_point). 2026-09-27 11:18, attempt 493:
# the confirmation stayed up through both Returns, twice running, as it had in
# pairs at 21:11, 22:45 and 23:02 the night before -- a second Return has
# never got one through. A respawn the click got through carries this note.
RESPAWN_CLICKED = ("the respawn went through on a click of its Respawn button, "
                   "after Return had not taken — the next respawn clicks first")
# AND THE WAY THAT WORKED GOES FIRST NEXT TIME (RouteRunner.click_first).
# MEASURED 2026-09-27: Return took on all six respawns of attempt 494 and on
# none of the four of attempt 495 (11:49-11:50), each of those going through
# on the click 7.5 s later -- the refusal comes in runs, so a failed Return is
# not paid for again on every respawn of a run. A click that does not take
# with Return then taking switches back.
RESPAWN_CLICKED_FIRST = ("clicked the respawn confirmation's Respawn button first "
                         "— Return had not taken on an earlier respawn")
RESPAWN_RETURNED = ("the respawn went through on Return after the click had not "
                    "taken — the next respawn presses Return first")
CONFIRM_NAMES = {"enter": "Return", "click": "a click on its Respawn button"}
RESPAWN_CONFIRM_NOTES = (RESPAWN_CLICKED_FIRST, RESPAWN_CLICKED, RESPAWN_RETURNED)
# WHEN THE PANEL READER CANNOT LOOK, THE TEMPLATE IS THE READ. The reader is
# the vision model, and with the owner's own programs open beside the bot
# there is not always room to load it (platform/memory MODEL_LOAD_GB): 18:06
# and 18:25 on 2026-09-26, attempt 458, the cannon's banner matched 0.88 both
# times and "the panel reader could not look, so nothing was pressed" -- every
# flight to Pine Tree a miss. The template is a pixel match of the words "Fire
# the Red Cannon" in their own box (vision/screenstate.RED_CANNON_TEMPLATE),
# MEASURED over 18,819 saved frames: the 119 that scored 0.829-1.000 are all
# that banner, checked by eye, and the best of the other 18,700 scored 0.443
# ("Talk to Black Bear", who stands beside the cannon). A look standing still
# at or above this line, inside that gap, is the cannon's prompt; a prompt
# with other words -- a till, a hive to claim -- cannot reach it.
CANNON_TEMPLATE_CONFIRMS = 0.80
# WHICH APPROACH A MISS WAS COUNTED AGAINST. run_farm keeps the cannon's own
# record (var/cannon.json, CANNON_RECORD_FILE) and grounds every flight for
# CANNON_RETRY_SECONDS x misses after a miss, up to six hours. MEASURED
# 2026-09-25 23:50, var/cannon.json: misses 4, last_try 23:45:30, all of them
# the ten hops, so the cannon would stay grounded until 05:45 the next
# morning whatever this approach can do. A record written under another
# approach is not evidence against this one, so run_farm's
# `_load_cannon_record` starts it afresh when this name differs: after a
# deploy the old approach's misses ground nothing, and the next trip that
# `nav.router.fly_this_time` sends by cannon flies. Change the name whenever
# the approach itself changes.
CANNON_APPROACH_VERSION = "one-hop-hold-right"
# HOW LONG TO HOLD ONE KEY LOOKING FOR THE CANNON after the approach got near
# it and lost it: the hold saw the prompt and the overrun check did not find
# it again, it was up as the hop landed and gone half a second later, or the
# template matched and the panel named something else (before DESIGN 8dl,
# after the hops). A hold that runs out without ever seeing it is not
# searched after; see `_cannon_approach`. MEASURED from the run logs:
# `natro_out_strawberry_via_red_cannon` reported "never stood at the red
# cannon: 10 hops toward it without its prompt staying on the panel" five
# times, and the spider route twice. The hops went RIGHT and FORWARD, as the
# hop and the hold still do, so a character that arrived on the far side of
# the ramp is moving away from the cannon and no amount of it helps. Five
# seconds a side at ~29 studs/s is about 145 studs, and the trip it saves is
# a failed journey plus a rejoin.
CANNON_SEARCH_SECONDS = 5.0
# THE WORDS A MISSED APPROACH ENDS WITH, as a name other modules can test
# for. `nav.journey.Journey.go` walks the field's own route for the rest of
# the trip when a failure contains them (DESIGN 8de): MEASURED in the run
# logs, every cannon approach since attempt 320 missed -- 0 for 6, in 323
# (twice: the retry from the pad missed again at 19:27:12), 324, 327, 330 and
# 334. The phrase is the one scripts/night_report.py already counts, so the
# night report is unchanged.
CANNON_MISS = "never stood at the red cannon"

# A DOOR THAT IS READ BEFORE IT IS OPENED.
#
# Natro's walks home from Bamboo and the Blue Flower Field do not walk all
# the way home: both cross the map to a portal, press E, and finish with the
# same seven legs on the other side. Until now this project refused both
# routes whole rather than emit that press (`transpile_natro.presses_e`),
# because an E press the bot cannot see the target of is a press at whatever
# happens to be in reach -- and one of the things in reach, four steps off
# the pad, is a shop till (`act/errands.NEVER_PRESS`).
#
# Refusing cost those two fields their walk home, so every trip to either
# ended in a rejoin, and a rejoin is the one thing the owner asked to stop:
# "rejoining is slow and also it resets wealth clock which is so important".
# Bamboo is also where this account's biggest quest sits (1,525,325 more
# pollen as of attempt 335), so it is the field the bot most needs to leave
# properly.
#
# So the press is kept and given a precondition it can check. MEASURED
# 2026-09-23: the portal's panel reads "Enter the Portal". Read by the local
# model off the frames three separate attempts saved at the portal --
# var/routes/attempt-275, -276 and -277, leg 06 and 07 of
# `natro_home_blue_flower`, back when the press was dropped and the route
# walked past it. Three attempts, five readable frames, the same four words.
PORTAL_WAIT_SECONDS = 6.0        # how long to wait for the panel to appear
PANEL_POLL_SECONDS = 0.15        # and how often to look while waiting

# P1: A PORTAL PROMPT THAT NEVER SHOWED IS LOOKED FOR, A STEP LEFT AT A TIME.
# MEASURED 2026-10-13 over runs 831-954 (91 walks home on natro_home_bamboo
# and natro_home_blue_flower, var/night + var/routes): every walk whose panel
# said "Enter the Portal" was pressed and went through (83 of 83; no E was
# pressed out of range; 81 then reached the pad, 859's row search and 875's
# death coming after the portal). The 7 whose panel never said it in the 6 s
# (866 03:15, 884 14:58, 889 21:59, 898 10:04, 937 23:54, 943 03:23, 944
# 03:47) ALL missed -- the route stops at the door and the sight homing from
# there ends against the Blue Flower field's yellow wall or turns a full
# circle; 0 of 7 reached the pad. Two of them stood beside the portal: in the
# interact_when frame (camera after the route's two right taps) the Blueberry
# Dispenser's left edge is at x 0.485 and 0.471 of the width
# (attempt-889/220002-natro_home_bamboo-17-interact_when-.jpg,
# attempt-898/100506-natro_home_blue_flower-10-interact_when-.jpg) against
# 0.509-0.609 (median 0.577) in all 83 that pressed, at the same size (0.096-
# 0.100 wide, median 0.107): the same distance, a stud or few to the RIGHT,
# just past where the prompt still shows -- and 889's a12 frame
# shows "Use the Blueberry Dispenser" where the landings show the portal's.
# So once the wait runs out, the runner walks PORTAL_SEARCH_STUDS left ("a")
# at most PORTAL_SEARCH_STEPS times, reading the panel PORTAL_SEARCH_LOOK_S
# after each, and presses only on the portal's words as before. The other
# five stood 30+ studs off (in the Blue Flower field, by HQ) or dying; for
# them it costs ~10 s before the same miss. Pinned "on": the old way failed 7
# of 7, and only a walk that has already failed ever reaches it. "off" = stop
# at the door as before.
# ponytail: one direction, fitted on 2 frames; search both sides if a timeout
# with the portal in view ever stands LEFT of it.
PORTAL_SEARCH = "on"
PORTAL_SEARCH_KEY = "a"
PORTAL_SEARCH_STUDS = 3.0
PORTAL_SEARCH_STEPS = 4
PORTAL_SEARCH_LOOK_S = 2.5

# A PAUSE BETWEEN STEPS, because the recording has one and we did not.
#
# BeeTuxMacro drives every keypress by spawning `wtype`, so there is tens of
# milliseconds of process overhead between one step and the next -- implicit
# timing that is part of the recording whether anyone meant it to be. This
# executor sends the next key the instant the last one is released, which is
# not the same walk.
#
# MEASURED, and this is what led here: the ONE run where the cannon route
# worked end to end was the one with a screenshot hook between steps. Every
# run without it walked into the sand. Same route, same reset, same camera --
# the hook was the only difference, and what the hook mostly did was take time.
STEP_GAP = 0.12

# ...BUT NOT INSIDE A GATHER PATTERN, whose recording has no pause at all.
#
# Natro's patterns (data/world/natro_patterns.yaml, from patterns/*.ahk)
# change keys inside one `send`: CornerXSnake.ahk:3 is
# `{TCLRKey up}{TCFBKey down}`, and the file contains no Sleep. The 0.12 s
# above emulates BeeTuxMacro's process per keypress, which a Natro pattern
# never had. So before each of a pass's 24 legs it put 0.12 s of standing
# with no key down.
#
# MEASURED:
# * 2026-09-23, loss audit of attempts 300-336 (var/trips.jsonl `passes`,
#   var/night/attempts.log exits): 483 CornerXSnake passes x 24 legs x
#   0.12 s = 1,391 s of standing in 21,373 s of session, which is 234 s/h.
# * 2026-09-24 00:30, every trip in var/trips.jsonl against its run log: a
#   pass with no threat in it, timed between "token brain:" blocks, takes
#   24.97 s on natro_pattern_strawberry (n=307) and natro_pattern_spider
#   (n=445). The holds are 20.4 s (570.7 studs at walkspeed 28), and the gaps
#   are 2.88 s of the 4.6 s left over.
#
# Which routes this covers: at depth 0, a name starting with PATTERN_PREFIX
# where every step is a `walk` (RouteRunner.run). Every other route keeps
# STEP_GAP: travel routes, the cannon, and paths.yaml routines such as
# `farm_mobs`, which calls the red-cannon route and jumps.
#
# NOT MEASURED ON SOBER: every CornerXSnake pattern has one pair of legs that
# shares a key (strawberry: `a` 28 studs, then `aw` 12). That key now comes up
# and goes down again within a millisecond, where Natro holds it down. If
# pattern legs come out short (DESIGN 8dg says how to tell from the logs),
# set this to 0.02.
PATTERN_PREFIX = "natro_pattern_"
PATTERN_STEP_GAP = 0.0

# How often a watcher gets to look during a held key. 10 Hz: a nameplate check
# costs about 7 ms, so this is ~7% of one core of sixteen, and it bounds how
# stale the world can be when something needs reacting to.
# STEP_GAP MUST NOT APPLY TO THESE.
#
# MEASURED BY THE OWNER WATCHING A GLIDE FAIL: "oh it was so close gliding
# back, the second jump button to activate the parachute was justa bit too
# late". He is exactly right, and the lateness is mine.
#
# `from_pine_tree_to_hive` deploys the glider with jump, pause 0.5275, jump.
# With a 0.12 s gap inserted before every step that 0.5275 became roughly
# 0.77 -- 46% late, which for a parachute window is the difference between
# gliding home and hitting the ground. The gap was added for a good reason
# (BeeTuxMacro spawns a process per keypress, so its recordings contain that
# overhead) but it belongs between WALKS, where a few tens of milliseconds
# change nothing, and never inside a sequence whose whole point is its timing.
TIMED_OPS = frozenset({"jump", "jump_hold", "jump_release", "pause", "hold", "coast"})

# THE CANNON GLIDE, HELD AS LONG AS IT IS MEASURED TO LAND. GLIDES names a
# flight's glide -- the pause after its double jump, Natro's HyperSleep(4500)
# in gtf-pinetree.ahk, held with the steering keys down -- and the runner's
# `glide_scale()` (the owner's move.glide_scale, read at every glide)
# multiplies it; 1.0 is Natro's own timing. MEASURED 2026-10-01 over the
# saved landing frames (var/routes/attempt-511..553, each flight's
# `-20-pause-` frame): every Pine Tree flight comes down in the same place, a
# corner of plain grass under a blue wall beside the field's pine trees, and
# over runs 520-553 all 72 of them had the start spot's sprinkler refused
# ("You must be standing in a field") -- while the 3 trips whose cannon missed
# and that walked in had it placed. (An earlier note here read those 3 as
# flights with Haste and scaled the glide by the buff bar's speed: wrong, and
# taken out.) And a longer glide is no cure: run-553 (2026-10-01) flew the
# scaled holds and the feed credited each trip -- 4.91 s at 1.10x, the
# corner, then Pumpkin; 4.72 s at 1.14x, the edge of the Pine Tree flowers
# (15% flower bed; that trip gathered 3.65 million in 264 s); 5.40 s at base
# speed twice, the Pumpkin Patch's flowers (60% and 48%; the sprinkler placed
# at once -- in the wrong field). From the corner Natro's 4.5 s goes on into
# Pine Tree: its flights were credited there 9 times in 10 (brain/skills).
# The test flights of run-554 slid the landing along the field's edge, not
# onto it (0.9 beside the pine tree, 0.8 the grass strip between Pine Tree's
# flowers and Pumpkin's, 0.7 the pumpkins) -- see GLIDE_SIDES for what put it
# on the flowers. The owner's settings default to that pair, 0.8 and 2.0.
# THE SIDEWAYS FINISH: the pause after the glide's back key comes up, with
# only the side key held (Natro's HyperSleep(500) with RightKey down), is held
# for `glide_side_scale()` times as long. MEASURED 2026-10-01 (run-554, the
# landing frames at move.glide_scale 0.8): the flight comes down on the grass
# strip between Pine Tree's flowers and the Pumpkin Patch's, Pine Tree's on
# the side that key steers toward once the camera has turned round, and the
# start walk's 22 studs that way reached them on one landing of three. At
# glide 0.8 with this at 2.0 (a whole second), run-555's first three flights
# came down on Pine Tree's flowers (70%, 82% and 50% flower bed), each trip
# credited Pine Tree, the sprinkler placed at the first press or already
# standing from the trip before (vision/notices.kind_of).
GLIDES = {"natro_out_pine_tree_via_red_cannon": 4.5}
GLIDE_SIDES = {"natro_out_pine_tree_via_red_cannon": 0.5}
GLIDE_SCALE_BOUNDS = (0.3, 1.5)
GLIDE_SIDE_BOUNDS = (0.5, 4.0)

# AND THE WALK HOME'S GLIDE IS NO FASTER UNDER A BUFF. GLIDE_COASTS names a
# route's coast that is a glide -- natro_home_pine_tree's 432 studs after its
# jump, held with W down -- and with `glide_at_base()` true (the owner's
# move.home_glide_at_base) it is timed at base speed whatever the buff bar
# says, where every other coast is divided by the movespeed factor
# (`_hold_seconds`). MEASURED 2026-10-01 over runs 555-557: 17 of the 31
# Pine Tree flights left the cannon under Haste (x1 to x7, 1.1-1.7x) or a
# bear morph, held the same fixed glide, and all 31 were credited Pine Tree
# -- the glide does not speed up with the buffs. And the 2026-09-26 review of
# the walk home (run_farm `wait_out_the_morph`): 7 of 7 glides begun without
# a buff landed on the pad, 3 of 3 begun under one came down short of the
# fence, every frame up to the jump matching the landings -- the coast
# divided by the buff lets W up early. Off, the walk waits the buff out first
# (2% of runs 555-557's session: 20 of 30 walks home, 303 s). CONFIRMED LIVE
# (run-562, 2026-10-01 19:24): a polar bear morph picked up 7 s into the walk
# home ran through the glide, which "coasted 432 studs for 15.43s at base
# speed, not 13.64s at the buff bar's 1.14x", and the walk arrived on the pad
# -- a buff the wait could not have waited out, since it came after the walk
# began; and five walks home begun under one went at once and arrived.
GLIDE_COASTS = {"natro_home_pine_tree": 432.0}
# THE GLIDE'S OWN SPEED, NOT move.walkspeed. A glider ignores movespeed (the
# buffs above, and the gifted Hasty Bee's +15% hive bonus too), so the coast
# is timed at the 28 studs/s it was proven at (15.43 s, 31 of 31 credited)
# even now move.walkspeed is 32.2 for the Hasty (2026-10-09).
GLIDE_BASE_SPEED = 28.0
# BUT NOT UNDER A STRONG HASTE: THE RUN-UP WAITS FOR IT (W4). With the glide
# timed at base speed, MEASURED 2026-10-12 over runs 813-900 (walkspeed 32.2,
# the Hasty): every walk home that reached the jump with the buff bar at
# 1.25x or less landed (33 of 33; one held 1.12x for the whole coast), and
# both that jumped under Haste x10 (2.00x; 2.6 and 3.4 s of it left) came
# down in the white field in front of the picket fence below the hives, the
# hive row in view behind it (attempt-832/072537-natro_home_pine_tree-19-
# coast-432.jpg, attempt-891/233248-...) -- the same place as 2026-09-26's
# three, every frame up to the jump matching the landings (-13-, -15-, -18-).
# So the hold time is not it: the flight itself goes elsewhere under that
# speed. The run-up (the route's `key_down` before the glide, standing on the
# Polar Bear's ledge) therefore waits, keys up, until the factor is down to
# GLIDE_CALM_FACTOR, at most GLIDE_CALM_MAX_S (Haste ends ~16 s after the last
# token, run_farm `wait_out_the_morph`), and then jumps as before. Only with
# move.home_glide_at_base on: off, `wait_out_the_morph` already waited in the
# field. GLIDE_CALM "on"; "ab" = on in even hours (HOME_UNSTICK's style),
# "off" = today's jump at once.
# ponytail: one factor threshold fitted on 2 misses and 7 buffed landings;
# a per-buff-seconds rule ((factor-1) x seconds left) if 1.3-1.9x ever miss.
# MEASURED 2026-10-21 (runs 1100-1172, natro_home_pine_tree, counted once per
# walk home: a miss also writes a "could not reach the hive" line with the
# same coast text, so counting lines doubles the misses): 1.00x landed 104 of
# 107, 1.05-1.25x 37 of 41. Of those 4 misses 1101 02:58 was a 20 s cap wait
# (2.14x), 1155 and 1159 were the feed-override walks that missed at their
# first legs (run_farm FEED_OVERRIDE_LOOK), and only 1164 18:09 fits a small
# buff; 1.12x stayed up for hours (1140 03:31-05:05, all landed), so a 1.05
# bar would stand the whole cap on every walk home under it. So the bar stays
# 1.25 (1.05 is GLIDE_CALM_STRICT's A/B arm). All 4 waits that hit the 20 s
# cap missed (1101 2.14x, 1140, 1152 2.00x, 1161 1.40x), so the cap is 35 s
# (Haste ends ~16 s after the last token: room for one refresh). Waiting is
# the tested path (keys up), only longer.
# ponytail: the jump-anyway at the cap stays; a different way home if 35 s
# caps keep missing.
GLIDE_CALM = "on"
GLIDE_CALM_FACTOR = 1.25
GLIDE_CALM_MAX_S = 35.0
GLIDE_CALM_POLL_S = 0.25
# GLIDE_STEADY: AND NOT WHILE A BUFF IS ABOUT TO RUN OUT. MEASURED 2026-10-21
# over runs 1101-1167 (the to-hive notes of 151 Pine Tree walks home that
# reached the glide): 4 of the 7 whose calm wait hit GLIDE_CALM_MAX_S and
# "jumped anyway" missed, against 4 of the other 144. In 3 of those 4 the
# buff bar said a buff ended within seconds of the jump (1101 02:56 brown
# bear morph "about 1s left", 1152 10:18 black bear morph 1s, 1140 03:49
# Haste ending :38, jump :40) and the glide's own read just after was down
# at 1.00-1.12x; the 3 that landed had nothing ending inside 12 s (Haste
# x9-x10 "about 16s left", 1101 06:04 x5 12s) and read the same or higher
# at the glide. A buff ending around the jump goes with misses; the cause is
# unknown: the 24-stud run-up is a `coast` whose hold `_hold_seconds` already
# splits across each buff's clock (~0.4-0.7 s at 1.1-2.0x), and the 432-stud
# glide is timed at base speed (home_glide_at_base), so a buff ending under
# the run-up cannot by itself make it take off early. The 5 s window is an
# empirical fit. And 1140's Haste had already ended (:38) at its jump (:40),
# so the forecast would not have noted it: at most 2 of the 8 misses, not 3.
# Morph clocks are noisy too (run-1152 10:15:48 "5s left", 28s one second
# later), so expect some false "would wait" notes on landings. So the run-up
# waits, keys up, until no change the buff bar predicts falls inside
# GLIDE_STEADY_S, at most GLIDE_STEADY_MAX_S, then waits the calm bar again
# if Haste rose meanwhile. LOOK-ONLY (GLIDE_STEADY_LIVE False): notes "would
# wait" and jumps as today. The 4th miss (1161 16:10) was Haste RISING
# (Hasty bees, x4 to x8 while it stood), which no forecast sees.
# ponytail: 5 s is the run-up, the jump and the first seconds of the glide,
# fitted on 3 misses and 3 landings; widen it if the "would" notes show
# misses with a change 5-16 s out.
GLIDE_STEADY_LIVE = False
GLIDE_STEADY_S = 5.0
GLIDE_STEADY_MAX_S = 6.0
# GLIDE_CALM_LEG: AND ONE LEG EARLIER, on the step the route marks `calm: true`.
# MEASURED 2026-10-14 (agent study of the 10 Pine Tree misses, runs 940-994):
# 5 were a buff running out while the 8-stud "a" on the Polar Bear's ledge
# walked. The hold was planned for the buff's predicted end, but the
# character was still fast, and it walked ~13-19 studs. The take-off then
# sat 12-20 px right of every landing's (-4..+10), and the glide came down
# short of the fence (948 05:49, 958 11:04, 975 21:03, 992 10:53, and 940
# 01:52 in the run-up). The d40 before it, pressed to the snow ramp, squares
# every walk, so waiting there leaves both of the last legs at a steady
# speed, as in the 63 unbuffed walks that all landed.


# GLIDE_CALM_STRICT: AND THE SMALL BUFFS 1.25 LETS THROUGH STILL MISS. MEASURED
# 2026-10-21 (226 Pine Tree walks home, runs 1040-1172, the buff factor at
# the jump from the step notes): 1.00x landed 154 of 167 (92%), 1.05-1.15x
# 33 of 41 (80%), 1.15-1.25x 12 of 13; the misses at 1.10-1.24x (1046, 1067,
# 1155, 1159, 1164; not 1101, a 20 s cap wait at 2.14x) came down at the picket fence below the hives, as
# the 2.00x ones above did (attempt-1164/180756-...-19-coast-432 at 1.12x
# against 175557's landing, both -02- frames pressed into the same rock).
# "ab" = GLIDE_CALM_STRICT_FACTOR in hours 2-3, 6-7, 10-11... ((h // 2) % 2,
# so HOME_ALIGN's and HOME_UNSTICK's even/odd split stays clean in each arm),
# GLIDE_CALM_FACTOR in the others; "on"/"off" pin it. Only the glide's waits
# (the run-up and its calm leg), not Commando's CALM_AT. The wait's cost is
# its note's seconds (GLIDE_CALM_MAX_S at most).
# ponytail: a constant 1.1x buff (gifted Hasty refreshing Haste) never clears,
# so the strict arm waits the full cap each walk; the note's seconds show it.
GLIDE_CALM_STRICT = "ab"
GLIDE_CALM_STRICT_FACTOR = 1.05


def _glide_calm_on() -> bool:
    if GLIDE_CALM == "ab":
        return time.localtime().tm_hour % 2 == 0
    return GLIDE_CALM == "on"


def glide_calm_factor(hour: int | None = None) -> float:
    """The factor the glide's run-up waits down to now (`hour` for tests).
    See GLIDE_CALM_STRICT."""
    h = time.localtime().tm_hour if hour is None else hour
    strict = ((h // 2) % 2 == 1 if GLIDE_CALM_STRICT == "ab"
              else GLIDE_CALM_STRICT == "on")
    return GLIDE_CALM_STRICT_FACTOR if strict else GLIDE_CALM_FACTOR


# W5: A WALK HOME'S BUFF WAIT LASTS UNTIL THE BAR IS CLEAR (at most run_farm
# BEAR_WAIT_MAX_S), not the seconds left read once when it began: standing in
# the field the character keeps picking up Haste tokens, so the read goes
# stale. MEASURED 2026-10-13 over runs 324-944 (1,228 walks home, var/night):
# of the walks that waited on a clean start (no chase give-up, no off-flowers
# flag), those still buffed when the old wait ran out landed 101 of 119 (85%),
# those it cleared 335 of 365 (92%); 43 of the still-buffed cleared within 32 s
# of the wait's start. Attempt 943 03:23:20: "about 16s", walked at 03:23:37
# under Haste x10 + a brown morph (2.25x), ended at the Blue Flower field's
# yellow wall; the bar was clear by about 03:23:51. "ab" = on in ODD hours
# (W3/R4 hold the even ones), "on"/"off" pin it.
# ponytail: a fixed cap; a Hasty Bee that refreshes Haste for good still walks buffed.
# PINNED "on" 2026-10-13 18:45 (the owner: "do whatever"): its A/B since the
# 04:06 install, walks home that landed -- odd hours (on) 22 of 24, even hours
# (off) 25 of 31, the three Blue Flower wall misses (09:46, 14:28, 18:41) all
# even-hour walks that set off still buffed. Small, but the same way as the
# 1,228-walk analysis above; a miss is a rejoin and a Wealth Clock streak.
HOME_BUFF_REARM = "on"


def home_buff_wait_s(left: float | None, cap: float, hour: int | None = None) -> float:
    """The longest run_farm's `wait_out_the_morph` stands before a walk home;
    the wait itself still ends the moment the bar reads clear."""
    once = min(cap, (left if left is not None else cap) + 1.0)
    h = time.localtime().tm_hour if hour is None else hour
    on = h % 2 == 1 if HOME_BUFF_REARM == "ab" else HOME_BUFF_REARM == "on"
    return cap if on else once

# LEAN LEGS: a recorded walk whose purpose is to reach a wall (the transpiler
# marks them from Natro's own comments, scripts/transpile_natro.LEAN_WORDS).
# Held until the flow has read blocked for this long without a break -- a
# tile edge stumbles for a fraction of a second, a wall does not -- and never
# longer than the cap. MEASURED 2026-09-23 (DESIGN 8cq): Strawberry's
# rear-wall lean is 12 tiles and the field is deeper than that, so from a
# start past it the recorded hold ended short of the wall and the walk home
# missed twice in three. Three times the recording covers the whole field.
LEAN_STOP_SECONDS = 1.0
LEAN_CAP_FACTOR = 3.0
# A block read before this share of the recorded time is a stumble on the
# way, not the wall: the lean keeps going.
LEAN_EARLIEST = 0.5
# LEANS LOOKED AT, NOT WALKED (docs/pending/reliability-2026-10-19.md): route ->
# how many of its first steps are judged as a lean would judge them, while the
# recorded timed walk still runs. Each such walk notes whether it ENDED against
# a wall (the flow blocked for LEAN_STOP_SECONDS at its end) or still moving,
# and how long a lean would have held on. MEASURED 17-19 Oct (var/routes,
# attempts 1045-1067): the Pine Tree walk home's d300 ended pressed into the
# corner rock in 6 of 7 landings looked at, and short of it -- a gap of open
# floor to the rock -- in 6 of 8 misses; from there the glide came down wide
# (no "Talk to Polar Bear" at the run-up in 11 of 13 misses, but in 46 of 53
# landings). Look-only until the notes confirm it live; then the route moves to
# act/home_align.ALIGN_FIRST, which walks those legs as leans.
LEAN_LOOK: dict[str, int] = {"natro_home_pine_tree": 2}
# AND THE LAST SECOND OF EACH SUCH WALK IS KEPT, frame by frame, its flow
# reading in the name (<route>-NN-tail-KK-pxP.P.jpg), so the wall check can
# be replayed offline. MEASURED 2026-10-21 (226 Pine Tree walks home, runs
# 1040-1172): d300 read "ended against the wall" in 10 of 150 landings and 1
# of 12 misses, yet attempt-1164/180731-...-02-walk-d300 (missed) and
# 175532-...-02 (landed) both show the character pressed into the rock; the
# GROUND_ROI is mostly bees, bubbles and the character over plain marble, so
# its median motion stays over BLOCKED_FLOW_PX. One step frame cannot be
# replayed, so a lower band (about y 820-960) is untested until these exist.
# 0 = off. Recording only: the frames are kept in memory during the hold and
# written after it, keys up (`_flush_tail`), so no jpg write delays the
# hold's deadline check or the odometer's flow samples.
# ponytail: ~10 frames a leg (~80 MB of 1080p) held until the keys come up;
# storage.frames_allowed still gates the writes.
LEAN_LOOK_TAIL_S = 1.0

# A hold has to spend at least this long going nowhere before the route says
# so. Half a second of zero flow is a stumble on a tile edge; two is a wall.
BLOCKED_NOTE_SECONDS = 1.5
# How long the flow must read blocked before "we have met the wall" is
# believed: shorter than this is a doorway, a bee, a lag spike. Half a second
# at WALKSPEED 28 is 14 studs, which is far finer than the 36.8 studs between
# hive pads, so it cannot mistake one pad for the next.
BLOCKED_ONSET_SECONDS = 0.5

WATCH_HZ = 10.0

# A measured walk still stops eventually. If the expected flow never arrives
# -- because the character is against a wall, which the owner watched happen
# -- the key must not stay down indefinitely. Twice the recorded time is
# generous enough for a genuine slowdown and short enough to notice.
WALK_TIME_CEILING = 2.0

CAMERA_KEYS = {"left": "comma", "right": "period",
               "up": "pageup", "down": "pagedown"}

# HOW FAR INTO AN APPROACH ARRIVAL-BY-SIGHT IS ALLOWED TO FIRE.
#
# Arrival exists to cure OVERSHOOT, and overshoot happens at the end: the
# measured failure was the cannon route's last 0.75 s of a 323-stud approach,
# about 2% of the distance. So the measurement leaves this free anywhere below
# about 0.95, and the value is a choice rather than a reading. It is set well
# back from 1.0 because a walkspeed buff makes every leg run long -- the
# prompt can appear a whole leg early -- and well above 0 because the route
# passes other landmarks on the way, and stopping at the first prompt it sees
# is how it ended up at Black Bear instead of the cannon.
#
# With an unknown approach length the gate cannot be applied and arrival is
# live throughout, which is the old behaviour and is still better than a bare
# timer.
ARRIVE_AFTER = 0.6


# W3 (see Runner._unstick): a natro_home_* leg blocked this share of at least
# this long is walked round; the back-off, side-step and retry holds; "ab" = on
# in even hours (the A/B), "on" / "off" pin it.
UNSTICK_SHARE = 0.85
UNSTICK_MIN_S = 3.0
UNSTICK_BACK_S = 0.5
UNSTICK_SIDE_S = 0.8
UNSTICK_RETRY_MAX_S = 8.0
UNSTICK_SIDES = {"w": ("a", "d"), "s": ("d", "a"), "a": ("s", "w"), "d": ("w", "s")}
HOME_UNSTICK = "ab"


def _unstick_on() -> bool:
    if HOME_UNSTICK == "ab":
        return time.localtime().tm_hour % 2 == 0
    return HOME_UNSTICK == "on"


@dataclass
class RouteResult:
    """What actually happened, including what was refused."""
    name: str
    steps_run: int = 0
    studs: float = 0.0
    seconds: float = 0.0
    skipped: list[str] = field(default_factory=list)
    ok: bool = True
    reason: str = ""
    # TIME SPENT GOING NOWHERE while a movement key was held, and a note per
    # step it happened on. A timed hold cannot fail, so this is the only way a
    # route can report that the character spent six of a step's seven seconds
    # pressed against a wall -- which is exactly what the cannon route did on
    # 2026-09-21 while reporting `ok`. Recorded, never acted on here: some
    # routes walk into a wall on purpose to square themselves up.
    blocked_seconds: float = 0.0
    # Which hive slot the walk to the ramp implied, when the slot was not
    # configured and the ramp was felt for instead. None when not measured.
    learned_slot: int | None = None
    learned_slot_raw: float | None = None   # the unrounded reading
    notes: list[str] = field(default_factory=list)
    # WHY THE RUNNER'S `abandon` HOOK ENDED THE ROUTE, "" when it did not --
    # a death, not a route that went wrong. A caller that would treat a
    # failed route as fatal (the gather pattern, brain/farm) reads this.
    abandoned: str = ""
    # THE FIRST WALK ONLY, as (seconds blocked, seconds planned). It gets its
    # own field because it answers a different question from the total: a
    # route whose FIRST leg went nowhere was pointed at a wall before it
    # started, and that is a heading problem, not a route problem. MEASURED
    # 2026-09-21: `from_hive_to_rose_field` reported "w for 64 studs: pushed
    # against something for 1.9 of 2.3s" straight off a freshly claimed hive
    # pad -- 83% of the first leg spent standing still.
    first_walk: tuple[float, float] = (0.0, 0.0)
    # WHICH WAY EACH `slot_switch` WENT, one line per switch: the branch and
    # the slot it was chosen for. Kept apart from `notes`, which the journey
    # quotes for wall time, so a branch line never displaces a blocked-leg
    # report in the log.
    branches: list[str] = field(default_factory=list)
    # WHAT EACH `check:` READ, passed or failed, one line per check, so a
    # route that arrived also says how close its checks came to stopping it
    # -- which is how a threshold set on saved frames gets re-measured live.
    # Its own list for the reason `branches` has one.
    checks: list[str] = field(default_factory=list)

    @property
    def first_walk_blocked(self) -> float:
        """What fraction of the first walk moved nothing. 0.0 if unmeasured."""
        blocked, planned = self.first_walk
        return (blocked / planned) if planned > 0 else 0.0

    def describe(self) -> str:
        head = (f"{self.name}: {self.steps_run} steps, {self.studs:,.0f} studs "
                f"in {self.seconds:.1f}s")
        if self.skipped:
            head += f" — skipped {len(self.skipped)}: {', '.join(self.skipped[:4])}"
        if not self.ok:
            head += f" — STOPPED: {self.reason}"
        return head


def walkspeed_from(settings, fallback: float = 28.0) -> float:
    """`move.walkspeed`, read HERE rather than in a script, and why that matters.

    Every open-loop route in this project is a timed key hold, and the time
    comes from `studs / walkspeed`. Set it wrong and every single route
    overshoots or stops short -- it is the one number that silently breaks
    navigation everywhere at once.

    It was listed in NOT_WIRED as "read by scripts/test_navigate.py, not yet by
    a running bot", and that stopped being true once the farm loop read it. But
    `tests/unit/test_settings.py` scans `src/` on purpose: a setting only a
    script honours is not wired into the system, because nothing else can
    honour it. So the read lives here.

    A missing or nonsensical value falls back to Bee Swarm's base walkspeed
    rather than to zero, because zero would make every hold instantaneous.
    """
    try:
        value = float(settings.float("move.walkspeed"))
    except Exception:
        return fallback
    return value if value > 0 else fallback


class RouteRunner:
    """Runs transpiled routes. Open-loop, with the safety rules kept.

    `confirm_menu` is what makes `reset` safe to automate and is required for
    it. See `_reset`.
    """

    def __init__(self, vin, router, walkspeed: float = BASE_SPEED,
                 confirm_menu=None, on_step=None, hive_slot: int | None = None,
                 step_gap: float = STEP_GAP, watch=None, settle=None,
                 watch_hz: float = WATCH_HZ, pace=None, flow=None,
                 on_motion=None, arrive=None,
                 arrive_after: float = ARRIVE_AFTER, snapshot=None,
                 panel_text=None, movespeed_factor=None, checkpoints=None,
                 abandon=None, movespeed_changes=None, glide_scale=None,
                 glide_side_scale=None, glide_at_base=None):
        self.vin = vin
        self.router = router
        # `glide_at_base() -> bool`: whether a walk home's glide (GLIDE_COASTS)
        # is timed at base speed -- the owner's move.home_glide_at_base, read
        # at every glide. Unset or unreadable: no, the buffed timing as before.
        self.glide_at_base = glide_at_base
        # `glide_scale() -> float`: what a flight's glide (GLIDES) is held for,
        # as a multiple of Natro's -- the owner's move.glide_scale, read at
        # every glide. Unset or unreadable: 1.0, Natro's own timing.
        self.glide_scale = glide_scale
        # `glide_side_scale() -> float`: the same for the side key's finish
        # (GLIDE_SIDES) -- the owner's move.glide_side_scale.
        self.glide_side_scale = glide_side_scale
        # `movespeed_factor() -> float`: how much faster than `walkspeed` the
        # character is moving right now, read off the buff bar
        # (vision/buffs: Natro's `1 + 0.1 x Haste stacks`). Every timed hold
        # is divided by it, so a route recorded at base speed still covers
        # the recorded distance under Haste instead of overshooting -- the
        # owner's "heavily to the right ... maybe since it picked up a haste
        # token". Unreadable or absent: 1.0, said in `factor_notes`.
        self.movespeed_factor = movespeed_factor
        # `movespeed_changes() -> [(seconds, factor), ...]`: how that factor
        # changes as its buffs run out, asked right after it: `seconds` from
        # now it becomes `factor`, soonest first (vision/buffs
        # `speed_changes`: a Haste and a bear morph each run out on their own
        # clock, their drain lines). Empty or unset: the factor lasts for any
        # hold. A leg longer than a buff has left is walked at its factor
        # only while it lasts (`_hold_seconds`), as Natro's Walk() does by
        # re-reading.
        self.movespeed_changes = movespeed_changes
        # (read at, value, its changes as counted from then)
        self._factor_cache: tuple[float, float, list] = (0.0, 1.0, [])
        self.last_factor = 1.0
        # THE HOLD IN PROGRESS AS A DISTANCE (`_odometer_deadline`): [studs
        # to walk, studs walked, when last counted, the factor since then],
        # or None when the hold is only timed. `_odo_left` is what a hold a
        # mob stopped still had to walk, for `_walk`'s resume.
        self._odo: list | None = None
        self._odo_left: float | None = None
        # `panel_text() -> str | None`: the top-centre panel's words right now
        # ("" for no panel, None for could-not-look). The cannon approach
        # needs it to know it has arrived; without it the approach refuses.
        self.panel_text = panel_text
        # `cannon_prompt() -> float | None`: how well the red cannon's own
        # template matches right now (vision/screenstate
        # .red_cannon_prompt_score; None for could-not-look). It is the stop
        # signal for the approach's held key, about 1.5 ms a look; the panel
        # read above takes seconds and confirms once, standing still. Unset,
        # nothing stops the hold on sight, so it runs out and the approach
        # misses (see `_cannon_seen`). run_farm wires it beside `panel_text`.
        self.cannon_prompt = None
        # `checkpoints[name]() -> (ok, why)`: a check a step can ask for by
        # name (`check:` in the route data), run right after that step. A
        # failed one ends the route there with the check's reason, which is
        # how a walk that has visibly gone wide stops before the legs that
        # would carry it further off (DESIGN 8dk). An unknown name is noted
        # and ignored: the check is a guard, not part of the walk.
        self.checkpoints = dict(checkpoints or {})
        # Keys put down by `key_down` and not yet lifted by `key_up`. A route
        # that ends, or dies, with one still down has it lifted in `run`.
        self._down: list[str] = []
        # Set per top-level run: the route finds its own landmark, so the
        # arrival watcher stands down. See _may_arrive.
        self._own_arrival = False
        # What `_cannon_search` did, for the refusal to quote.
        self._cannon_searched = ""
        # What the approach's template saw, for its notes: the best score of
        # the approach so far, the score when it fired, and whether the
        # 'cannon-seen' frame has been kept. Reset per approach.
        self._cannon_best: float | None = None
        self._cannon_score: float | None = None
        self._cannon_snapped = False
        # And how many of its looks got no score at all (`_cannon_seen`).
        self._cannon_unscored = 0
        # `snapshot(label)` is called before a route's first step and after
        # every step, so whoever wires it can keep a frame per leg. It exists
        # because 2026-09-22's walks home from Dandelion ended in the
        # Sunflower Field (run 240) and against the ramp (runs 170-224) and
        # nothing had photographed a single leg; the geometry of a failed
        # route is otherwise reconstructed from prose. Never raises.
        self.snapshot = snapshot
        # `pattern_snaps_left`: how many legs of the next gather pattern to
        # photograph -- a pattern is otherwise never photographed (`_snap`).
        # run_farm sets it as a trip arrives, to see where the first strokes
        # go (ARRIVAL_PATTERN_SNAPS).
        self.pattern_snaps_left = 0
        # `grab_frame() -> frame`: the current game frame, set after
        # construction by whoever has the capture. LEAN_LOOK_TAIL_S keeps its
        # frames with it during a hold and writes them once the keys are up
        # (`_flush_tail`), so no jpg write lands inside the timed loop.
        self.grab_frame = None
        self._tail: list[tuple[str, object]] = []
        self.walkspeed = max(1.0, float(walkspeed))
        self.confirm_menu = confirm_menu
        # `in_world() -> bool`: are the game's HUD pills on screen? Set after
        # construction by whoever has the capture. `_leave_menu` asks it once
        # the confirmation is gone, so it can Escape the menu underneath.
        self.in_world = None
        # `respawn_button() -> (x, y) | None`: where the respawn confirmation's
        # Respawn button is on screen right now (vision/screenstate
        # .respawn_button_point), for a confirmation that did not take Return.
        # Set like `in_world`; unset, `_reset` presses Return again instead.
        self.respawn_button = None
        # Whether `_reset` clicks that button before trying Return: set by the
        # respawn a click got through, unset by one only Return did (see
        # RESPAWN_CLICKED_FIRST). Per process; each session starts on Return.
        self.click_first = False
        # `on_menu(up)`: told before `_reset` opens Roblox's menu and after it
        # is shut, for the stream window's cover (DESIGN 8ec). Set after
        # construction by whoever has the GUI socket; never stops a reset.
        self.on_menu = None
        # `between_legs()`: asked after each leg of a gather pattern
        # (natro_pattern_*, walked in the field as a trip's own route) and
        # after no other step, for stream chat's jump (DESIGN 8ef). It may
        # tap a key; it never stops the pattern. Set like `on_menu`.
        self.between_legs = None
        # `before_route(name)`: asked once as a route starts at depth 0,
        # before its first step (run_farm waits out a bear morph before a walk
        # home there, BEAR_WAIT_MAX_S). It may wait; a str it returns stops the
        # route before its first step, with that reason (run_farm: a respawn
        # that left the camera off, act/respawn.view_verdict).
        self.before_route = None
        self.on_step = on_step or (lambda *_: None)
        # which of the six hive slots the account owns; see _hop_to_slot
        self.hive_slot = hive_slot
        self.step_gap = max(0.0, float(step_gap))
        # `watch()` is called REPEATEDLY DURING a hold, and returning True
        # stops that hold immediately. See `_sleep_watching`.
        self.watch = watch
        self.watch_interval = 1.0 / max(1.0, float(watch_hz))
        self.interrupted = 0
        self._last_first_blocked_at: float | None = None
        # `settle() -> bool` says the reason `watch` stopped a walk has
        # passed. With it, a walk cut short is FINISHED rather than abandoned;
        # without it, behaviour is exactly as before. See RESUME_ATTEMPTS.
        self.settle = settle
        self.resumed = 0
        self.airborne = False             # inside a glide coast (run_farm watch reads it)
        # `abandon() -> str | None`: a reason the REST OF THE ROUTE must not
        # be walked from here at all, asked when a watched hold was cut
        # short. A death is the case: the character is back at the spawn
        # point, and dropping only the cut leg walked every later leg of the
        # route from there (MEASURED run-351.log 04:16:15-21, DESIGN 8ds). A
        # reason fails the route (`RouteResult.abandoned`, `_abandon_route`)
        # so the caller's own retry or closer takes over, even inside a
        # gather pattern. None, or no hook, leaves a leg that cannot be
        # finished to `_unwalked`.
        self.abandon = abandon
        # The seconds the owner's Pause held the last `_sleep_watching` or
        # `_hold_plain`, which extended its own deadline by them: a caller
        # working out what a mob left unwalked from the wall clock takes
        # them off, or a Pause then a cut counts the pause as walked.
        self._paused_s = 0.0
        # `pace` is a nav.pace.PaceMeter and `flow()` returns how many pixels
        # the world has slid since it was last called. With both, a walk stops
        # when the world has moved the expected amount instead of when a timer
        # runs out -- which is the difference between covering a distance and
        # hoping. Without either, the recorded timing is used unchanged.
        self.pace = pace
        self.flow = flow
        self.paced_walks = 0
        # `on_motion(keys, flow_px)` is told, at the watch rate, how much the
        # world slid while `keys` were held. world/bearings listens, so the
        # compass can say "pushing against something" while it is happening
        # rather than after the route has finished not arriving.
        self.on_motion = on_motion
        # ARRIVAL BY SIGHT. `arrive()` is asked at the watch rate during every
        # walk step; when it says True the hold ends and every further `walk`
        # before the next `interact` is skipped, so the route stops where the
        # thing IS rather than where the timer thought it would be. The
        # journey sets it to "the top-centre panel is showing" for routes that
        # end in a press. MEASURED 2026-09-21: the cannon route overshot the
        # cannon into the honeycomb wall behind it by its last 0.75 s, three
        # runs out of three, having worked 41 of 47 times the night before
        # from the same start -- a timed hold covers a different distance
        # the day the walkspeed changes, and a hold that ends at the prompt
        # does not care.
        self.arrive = arrive
        # The fraction of the approach that must be behind us before `arrive`
        # is consulted at all. See ARRIVE_AFTER.
        self.arrive_after = min(1.0, max(0.0, float(arrive_after)))
        # Set by whoever knows the whole journey -- `nav.journey` -- because a
        # journey can be a LIST of routes and only the caller knows where the
        # approach ends. None means "not known", and then the gate is off.
        self.approach_total: float | None = None
        self._approach_done = 0.0
        self._leg_studs = 0.0
        self._leg_started = 0.0
        self._leg_seconds = 0.0
        self._approach_armed = False
        # The op before this one, so the gap can stay off BOTH sides of a
        # timing-critical step. See `_run_step`.
        self._last_op = ""
        # True while `run` has a gather pattern at depth 0: the gap between
        # its legs is PATTERN_STEP_GAP, not `step_gap`. `_run_step` never sees
        # the route's name, so `run` sets this and clears it in its `finally`.
        self._gapless = False
        # THE ROUTE BEING WALKED, by name: the depth-0 route while `run` has
        # one, "" otherwise. A `call` inside it keeps the caller's name. The
        # threat watch asks for it, because on a natro_out_* walk with the bag
        # read empty only a bar near the character counts (brain/threat
        # OUTBOUND_BAR_RADIUS_PX, DESIGN 8di).
        self.current_route = ""
        # The depth-0 step `run` is on (1-based), and the continuous blocked
        # flow at the end of the last hold, None with no reading (LEAN_LOOK).
        self._step_idx = 0
        self._last_trail: float | None = None
        # HOW MANY ROUTES HAVE BEGUN AT DEPTH 0, counted as each one starts
        # its first step. run_farm's errand guard (DESIGN 8dh) compares it
        # before and after an errand that raised: once a route has begun, the
        # character may be anywhere between the pad and the errand, and the
        # next errand's route starts from the pad, so the guard respawns home
        # instead of trying that route from wherever this one left off.
        self.routes_run = 0
        # EVERY ROUTE WALKED, TOLD AS IT ENDS: `on_run(result)` gets each
        # depth-0 run's RouteResult (its name, seconds, ok and reason), which
        # is how run_farm knows which route a trip actually took -- the flight,
        # or the walk its miss fell back to -- and how long it took, for the
        # route's skill record (brain/skills, DESIGN 8dy). A `call` inside a
        # route is part of that route and is not told on its own.
        self.on_run = None
        self._arrived = False
        # ONCE THE PRESS HAS HAPPENED, THE ROUTE IS LEAVING. Every walk after
        # the `interact` is the departure -- `from_hive_to_pine_tree` walks
        # `a` 22.5 studs off the cannon platform after boarding -- and the
        # prompt it was approaching is often still on screen. Watching for
        # arrival there would cut the departure short at the very place the
        # route is trying to get away from. Caught by a test: arrivals came
        # out 2 instead of 1.
        self._approach_over = False
        self.arrivals = 0

    # ---- the approach -----------------------------------------------------
    def approach_studs(self, names) -> float | None:
        """Planned walking distance from the start of `names` to the press.

        Follows `call` steps and stops at the first `interact`, because that
        press is what the approach is FOR. A route list with no press has no
        press to approach, so the whole thing counts.

        None when a route name is unknown, which is the only honest answer --
        a partial total would put the gate in the wrong place.
        """
        total = 0.0

        def tally(step: dict, depth: int) -> bool:
            """Add one step's distance. True when it ended the approach."""
            nonlocal total
            op = step.get("op", "")
            if op in ("interact", "cannon_approach"):
                return True
            if op in ("walk", "coast"):
                total += max(0.0, float(step.get("studs", 0.0) or 0.0))
            elif op == "hive_offset" and self.hive_slot is not None:
                total += max(0.0, (
                    float(step.get("tiles_per_slot", 9.2) or 9.2)
                    * int(self.hive_slot)
                    + float(step.get("tiles_offset", -4.0) or -4.0))
                    * float(step.get("studs_per_tile", 4.0) or 4.0))
            elif op == "slot_switch":
                # The branch that WILL run, not every branch: the gate is a
                # fraction of the distance actually walked.
                for part in self._branch_of(step)[0]:
                    if tally(part, depth):
                        return True
            elif op == "call":
                return walk(str(step.get("route", "")), depth + 1)
            return False

        def walk(name: str, depth: int = 0) -> bool:
            """Returns True when an `interact` ended the approach."""
            if depth > 6:
                return True
            steps = self._steps_for(name)
            if steps is None:
                raise LookupError(name)
            for step in steps:
                if tally(step, depth):
                    return True
            return False

        try:
            for name in ([names] if isinstance(names, str) else list(names)):
                if walk(str(name)):
                    break
        except LookupError:
            return None
        return total

    def route_names(self, names) -> list[str]:
        """Every route these ones run, `call` steps followed.

        WHY THIS IS NEEDED. `nav.journey` works out which landmark a route's
        `interact` is for by looking for a landmark's router node in the route
        NAMES. That works for `from_hive_to_pumpkin_with_red_cannon` and fails
        for `from_hive_to_rose_field`, which reaches the very same cannon
        through `{"op": "call", "route": "from_hive_to_red_cannon"}` and says
        nothing about it in its own name. MEASURED live 2026-09-21 23:27:58:
        the rose route walked its full 323.5 studs, found no prompt, and was
        refused without the nearby search ever running, three attempts in a
        row -- because the search is only offered when a landmark is named.
        """
        out: list[str] = []
        seen: set[str] = set()

        def walk(name: str, depth: int = 0) -> None:
            if depth > 6 or name in seen:
                return
            seen.add(name)
            out.append(name)
            for step in self._flat_steps(name):
                if step.get("op") == "call":
                    walk(str(step.get("route", "")), depth + 1)

        for name in ([names] if isinstance(names, str) else list(names)):
            walk(str(name))
        return out

    def route_start(self, names) -> str | None:
        """Where the first of these routes was recorded from, or None.

        The route graph carries it: `from_hive_to_rose_field` has
        `start: hive`. Every route out of the hive assumes the character is
        standing on its own pad, and until 2026-09-21 nothing checked.
        """
        first = (names if isinstance(names, str)
                 else next(iter(names), "")) or ""
        for edge in self.router.edges:
            if edge.name == first:
                return getattr(edge, "start", None) or None
        return None

    def begin_approach(self, total: float | None) -> None:
        """Arm a journey that may span several routes. See approach_total."""
        self.approach_total = None if total is None else max(0.0, float(total))
        self._approach_done = 0.0
        self._leg_studs = self._leg_seconds = self._leg_started = 0.0
        self._arrived = False
        self._approach_over = False
        self._approach_armed = True

    def end_approach(self) -> None:
        self._approach_armed = False
        self.approach_total = None

    def approach_fraction(self) -> float | None:
        """How much of the approach is behind us, 0..1, or None if unknown.

        Includes the leg being walked right now, pro rata by time, because the
        gate is asked DURING a hold and a leg can be 212 studs on its own --
        two thirds of the cannon approach. Counting only finished legs would
        keep the gate shut across the whole of the leg that matters.
        """
        total = self.approach_total
        if total is None or total <= 0:
            return None
        done = self._approach_done
        if self._leg_studs > 0 and self._leg_seconds > 0:
            elapsed = max(0.0, time.monotonic() - self._leg_started)
            done += self._leg_studs * min(1.0, elapsed / self._leg_seconds)
        return min(1.0, done / total)

    def _may_arrive(self) -> bool:
        if self.arrive is None or self._arrived or self._approach_over:
            return False
        if self._own_arrival:
            # A route that finds its landmark itself (`cannon_approach` holds
            # right until the cannon's prompt shows) must not have its walks cut
            # short by the first prompt that drifts past -- an empty pad's
            # "Claim Hive" on the way along the row would end the approach
            # at the wrong pad.
            return False
        fraction = self.approach_fraction()
        return fraction is None or fraction >= self.arrive_after

    # ---- one route --------------------------------------------------------
    def run(self, name: str, depth: int = 0,
            result: RouteResult | None = None) -> RouteResult:
        result = result or RouteResult(name)
        if depth == 0:
            self._own_arrival = self._has_op(name, "cannon_approach")
        if depth == 0 and not self._approach_armed:
            # Standalone use: this route IS the whole journey, so its own
            # approach is the one to measure.
            self.begin_approach(self.approach_studs(name))
            self._approach_armed = False
        steps = self._steps_for(name)
        if steps is None:
            result.ok, result.reason = False, f"no route named {name!r}"
            return result
        if depth > 6:
            result.ok, result.reason = False, "route nesting too deep"
            return result

        if depth == 0 and self.before_route is not None:
            try:
                refused = self.before_route(name)
            except Exception:
                refused = None
            if isinstance(refused, str) and refused:
                result.ok, result.reason = False, refused
                return result
        started = time.monotonic()
        self._snap(f"{name}-00-start")
        # Put back in the `finally`, so a depth-0 route started from inside
        # another one hands the name back rather than blanking it.
        outer_route = self.current_route
        if depth == 0:
            # A gather pattern walks its legs back to back. See
            # PATTERN_STEP_GAP. Walks only: a routine that also calls a route,
            # jumps or resets keeps the gap, because those steps are what the
            # gap was measured on.
            self._gapless = (name.startswith(PATTERN_PREFIX)
                             and all(s.get("op") == "walk" for s in steps))
            self.routes_run += 1
            self.current_route = name
        try:
            for idx, step in enumerate(steps, start=1):
                if not result.ok:
                    break
                if step.get("op") == "slot_switch":
                    self._run_switch(step, result, depth, name, idx)
                    self._owner_took(result)
                    continue
                if depth == 0:
                    self._step_idx = idx
                self._run_step(step, result, depth)
                result.steps_run += 1
                self._owner_took(result)
                if (depth == 0 and result.ok and self.between_legs is not None
                        and name.startswith(PATTERN_PREFIX)):
                    self._between_legs()
                self._snap(self._leg_label(name, idx, step))
                check = step.get("check")
                if check and result.ok:
                    test = self.checkpoints.get(str(check))
                    if test is None:
                        result.skipped.append(f"check {check} (no such check)")
                    else:
                        try:
                            passed, why = test()
                        except Exception as exc:
                            passed, why = True, f"the check itself failed ({exc})"
                        result.checks.append(
                            f"leg {idx} {check}: {'passed' if passed else 'FAILED'}"
                            f" — {why}")
                        if not passed:
                            result.ok = False
                            result.reason = f"{name} leg {idx}: {why}"
        finally:
            if depth == 0:
                self._gapless = False
                self.current_route = outer_route
            if depth == 0 and self._down:
                # No route leaves a key down, whatever ended it.
                left = "".join(self._down)
                for key in list(self._down):
                    try:
                        self.vin.release(key)
                    except Exception:
                        pass
                self._down.clear()
                result.notes.append(f"released {left!r}, still down at the end")
        result.seconds = time.monotonic() - started
        if depth == 0 and self.on_run is not None:
            try:
                self.on_run(result)
            except Exception:
                pass                  # bookkeeping never ends a route
        return result

    @staticmethod
    def _leg_label(name: str, idx: int, step: dict, sub: int | None = None) -> str:
        """`natro_home_spider-07-walk-w256`, or `-12.03-` for the third leg of
        the switch that is step 12. One naming scheme for every saved frame."""
        part = f"{idx:02d}" if sub is None else f"{idx:02d}.{sub:02d}"
        return (f"{name}-{part}-{step.get('op', '')}-"
                f"{step.get('keys', step.get('direction', ''))}"
                f"{int(float(step.get('studs', 0) or 0)) or ''}")

    def _branch_of(self, step: dict) -> tuple[list[dict], str]:
        """The steps a `slot_switch` takes for this account, and which branch.

        Natro's walks home end in `switch HiveSlot`: `case 3` stops on pad 3,
        because the paths were recorded aligned with the default spawn, and
        `default` walks on to the ramp corner for `nm_findHiveSlot` to search
        the row from. The transpiler keeps both (scripts/transpile_natro
        .slot_switch). This takes the case named for the slot the runner was
        given, and `default` -- the general path -- when the slot is unknown
        or has no case of its own.

        MEASURED 2026-09-23: this account owns slot 3, the transpiler used to
        keep only `default`, and the frames under var/routes/attempt-296 show
        `natro_home_spider` standing on the owner's pad after leg 09 with the
        "Make Honey" prompt matching at 0.839 -- then walking 140 studs to
        the ramp and losing it. 114 of 170 trips rejoined for that.
        """
        cases = step.get("cases") or {}
        slot = self.hive_slot
        if slot is not None and int(slot) > 0 and str(int(slot)) in cases:
            return list(cases[str(int(slot))] or []), f"case {int(slot)}"
        return list(step.get("default") or []), "default"

    @staticmethod
    def _all_branches(step: dict) -> list[dict]:
        """Every step in every branch, for questions about what a route
        CONTAINS rather than what it will run."""
        out: list[dict] = []
        for body in list((step.get("cases") or {}).values()):
            out.extend(body or [])
        out.extend(step.get("default") or [])
        return out

    def _run_switch(self, step: dict, result: RouteResult, depth: int,
                    name: str, idx: int) -> None:
        branch, which = self._branch_of(step)
        slot = "unknown" if self.hive_slot is None or int(self.hive_slot) <= 0 \
            else str(int(self.hive_slot))
        result.branches.append(
            f"{name or 'route'}: took the {which} branch for hive slot {slot} "
            f"({len(branch)} step(s))")
        for sub, part in enumerate(branch, start=1):
            if not result.ok:
                break
            self._run_step(part, result, depth)
            result.steps_run += 1
            self._owner_took(result)
            if name:
                self._snap(self._leg_label(name, idx, part, sub))

    def _owner_took(self, result: RouteResult) -> None:
        """Fail the route where the owner took the controls (see
        `_owner_hold`): nothing after this step would reach the game, and a
        route that ran on pressing nothing would report "ok" from wherever
        his hands left the character."""
        if result.ok and self._taken():
            result.ok, result.reason = False, OWNER_TOOK

    def _snap(self, label: str, frame=None) -> None:
        if self.snapshot is None:
            return
        # Routes only, never the gather PATTERNS: a pattern is a routine run
        # every 13 s with 24 legs, and photographing each leg wrote 24 frames
        # a pass (MEASURED 2026-09-22 22:23: 300 frames in the first minute
        # of attempt 246). The walks whose geometry is in question are the
        # routes between places.
        if label.split("-", 1)[0] in self.router.routines:
            if self.pattern_snaps_left <= 0:
                return
            self.pattern_snaps_left -= 1
        try:
            if frame is None:
                self.snapshot(label)
            else:
                self.snapshot(label, frame)
        except Exception:
            pass

    def _flush_tail(self) -> None:
        """Write the LEAN_LOOK_TAIL_S frames a hold kept, keys up."""
        tail, self._tail = self._tail, []
        for label, frame in tail:
            self._snap(label, frame)

    def _has_op(self, name: str, op: str, depth: int = 0) -> bool:
        """Does this route, or anything it calls, contain `op`?"""
        if depth > 6:
            return False
        for step in self._flat_steps(name):
            if step.get("op") == op:
                return True
            if step.get("op") == "call" and self._has_op(str(step.get("route", "")), op, depth + 1):
                return True
        return False

    def _flat_steps(self, name: str) -> list[dict]:
        """The route's steps with every `slot_switch` opened out -- all of its
        branches, because "does this route contain an interact" has to be
        answered for whichever branch might run."""
        out: list[dict] = []
        for step in self._steps_for(name) or ():
            out.append(step)
            if step.get("op") == "slot_switch":
                out.extend(self._all_branches(step))
        return out

    def _steps_for(self, name: str) -> list[dict] | None:
        for edge in self.router.edges:
            if edge.name == name:
                return edge.steps
        routine = self.router.routines.get(name)
        return routine.steps if routine is not None else None

    def _run_step(self, step: dict, result: RouteResult, depth: int) -> None:
        op = step.get("op", "")
        if self._approach_over and op == "walk":
            pass                               # departing; timers are correct
        elif self._arrived and op == "walk":
            # We are already at the thing; the rest of the approach would
            # walk us past it. Said in the result, not silently dropped.
            result.skipped.append(f"walk {step.get('keys')} {step.get('studs')} "
                                  f"(already arrived)")
            return
        if op == "interact":
            # The press consumes the arrival, and the rest of the route is
            # the departure.
            self._arrived = False
            self._approach_over = True
        self.on_step(op, step)
        # NOT BEFORE A TIMING-CRITICAL STEP, AND NOT AFTER ONE EITHER.
        #
        # THE SECOND HALF OF THAT RULE WAS MISSING and the owner found it by
        # watching: "the bot is missing the jumps to the cannon". The cannon
        # route ends
        #
        #     walk a 4.8 · jump · pause 0.1 · walk d 22.5 · jump · walk d 19.3
        #
        # and those walks are what carry the character ONTO the platform while
        # it is in the air. `jump` is in TIMED_OPS so no gap is inserted before
        # it -- but the walk that follows got the full 0.12 s, on top of the
        # recorded pause. The second jump has no recorded pause at all, so its
        # walk started 0.12 s after take-off instead of immediately, which is a
        # quarter of the rise spent standing still on the platform edge.
        #
        # It is the same fault as the glider, in the same file, found the same
        # way: "the second jump button to activate the parachute was just a bit
        # too late". The gap exists to emulate BeeTuxMacro spawning a process
        # per keypress, and that overhead belongs between WALKS, where tens of
        # milliseconds change nothing -- never on either side of a jump, a
        # pause or a hold, whose whole point is when they happen.
        #
        # Inside a gather pattern the gap is PATTERN_STEP_GAP, because Natro's
        # patterns have no pause between legs. It is never longer than the
        # runner's own gap, so `step_gap=0` still means no sleep anywhere.
        gap = (min(self.step_gap, PATTERN_STEP_GAP) if self._gapless
               else self.step_gap)
        if gap and op not in TIMED_OPS and self._last_op not in TIMED_OPS:
            time.sleep(gap)                # see STEP_GAP, PATTERN_STEP_GAP
        self._last_op = op

        if op == "walk":
            studs = float(step.get("studs", 0.0))
            # A `calm: true` leg waits out a strong buff first, as the run-up
            # does (GLIDE_CALM_LEG): the walk home's last leg before its glide.
            # `calm: "always"` waits on any route, no glide or setting behind
            # it: act/commando.CALM_AT, the leg after the Commando walk's last wall.
            calm = step.get("calm")
            if calm == "always" and not self._down:
                self._calm_before_glide(result, "calm", f"before the {step.get('keys')} leg")
            elif calm and self._glide_calm_due():
                # its own words, so landings can be counted by which wait it was
                self._calm_before_glide(result, where="before the calm leg")
            if step.get("lean"):
                self._lean(str(step.get("keys", "")), studs, result)
            else:
                self._last_trail = None
                self._walk(str(step.get("keys", "")), studs, result)
                if self._step_idx <= LEAN_LOOK.get(self.current_route, 0):
                    self._lean_look(str(step.get("keys", "")), studs, result)
            result.studs += studs
        elif op == "slot_switch":
            self._run_switch(step, result, depth, "", 0)
        elif op == "pause":
            seconds = float(step.get("seconds", 0.0))
            route = getattr(self, "current_route", None) or ""
            glide, side = GLIDES.get(route), GLIDE_SIDES.get(route)
            if glide is not None and abs(seconds - glide) < 1e-6:
                scale = self._glide_scale(self.glide_scale, GLIDE_SCALE_BOUNDS)
                if scale != 1.0:
                    result.notes.append(f"glide: held {seconds * scale:.2f}s, not Natro's "
                                        f"{seconds:.2f}s (move.glide_scale {scale:g})")
                    seconds *= scale
            elif side is not None and abs(seconds - side) < 1e-6 and self._down:
                scale = self._glide_scale(self.glide_side_scale, GLIDE_SIDE_BOUNDS)
                if scale != 1.0:
                    result.notes.append(f"glide: side held {seconds * scale:.2f}s, not Natro's "
                                        f"{seconds:.2f}s (move.glide_side_scale {scale:g})")
                    seconds *= scale
            time.sleep(seconds)
        elif op == "camera":
            key = CAMERA_KEYS.get(str(step.get("direction", "")))
            if key is None:
                result.skipped.append(f"camera {step.get('direction')!r}")
            else:
                self.vin.tap(key)
                time.sleep(CAMERA_GAP)
        elif op == "hold":
            # A hold measured in SECONDS rather than studs, and the only place
            # that is the honest unit.
            #
            # BeeTuxMacro's `wait` scales by walkspeed, which is what makes
            # every other walk transferable between players. Two holds in
            # paths.sh have no `wait` at all -- `from_pine_tree_to_hive` holds
            # W across `sleep 4`, and `from_rose_field_to_hive` across
            # `sleep 0.1` -- so no distance can be derived from them, and the
            # transpiler used to emit a `raw` note instead.
            #
            # The four-second one IS THE GLIDE HOME. The route jumps off the
            # pine tree and holds forward while falling, and dropping it is
            # exactly what the owner watched: "when it went to jump and glide
            # down to the hive it jumped behind the ledge so id didnt even
            # glide down". Falling speed is not walkspeed, so converting it to
            # studs would have been the guess; holding for the recorded time
            # is the recording.
            seconds = float(step.get("seconds", 0.0))
            keys = str(step.get("keys", ""))
            if keys and seconds > 0:
                # Cut short by a mob, it is finished the way a walk is.
                self._sleep_resuming(f"hold {keys}", seconds, result, keys=keys)
        elif op == "jump":
            self.vin.tap("space")
        elif op == "key_down":
            # Held across whatever follows -- a cannon's steering keys go
            # down before the shot and come up seconds into the flight.
            # In a walk home with a glide it is the run-up: see GLIDE_CALM.
            if self._glide_calm_due():
                self._calm_before_glide(result)
                self._steady_before_glide(result)
            for key in str(step.get("keys", "")):
                if self._held_back(self.vin.press(key), key, result):
                    break
                if key not in self._down:
                    self._down.append(key)
        elif op == "key_up":
            for key in str(step.get("keys", "")):
                self.vin.release(key)
                if key in self._down:
                    self._down.remove(key)
        elif op == "cannon_approach":
            self._cannon_approach(result)
        elif op == "jump_hold":
            self.vin.press("space")
        elif op == "jump_release":
            self.vin.release("space")
        elif op == "coast":
            # COVER A DISTANCE WITH THE KEYS ALREADY DOWN. Natro's `Walk(n)`
            # between a `{FwdKey down}` and a `{FwdKey up}`: the character is
            # moving under a `key_down` and this is how long that takes at
            # our speed, buffs included. The keys are not touched -- a `walk`
            # here would release the held key at its end and cut the hop
            # short.
            #
            # A MOB THAT CUTS IT SHORT gets what it gets in `_walk`: the held
            # keys come up, the coast waits for `settle`, and the rest is
            # coasted with the same keys put back down. Only the distance
            # actually covered is counted. See UNWALKED.
            studs = float(step.get("studs", 0.0) or 0.0)
            planned = self._hold_seconds(studs)
            glide = GLIDE_COASTS.get(getattr(self, "current_route", None) or "")
            if (glide is not None and abs(studs - glide) < 1e-6
                    and self._flag(self.glide_at_base)):
                at_base = studs / GLIDE_BASE_SPEED
                if abs(at_base - planned) >= 0.05:
                    result.notes.append(
                        f"glide: coasted {studs:.0f} studs for {at_base:.2f}s at base "
                        f"speed, not {planned:.2f}s at the buff bar's "
                        f"{self.last_factor:.2f}x (move.home_glide_at_base)")
                planned = at_base
            # A GLIDE IS NOT CUT FOR A MOB (`airborne`, which run_farm's watch
            # reads): lifting the keys mid-air drops the character, and the
            # rest is then walked on the ground from somewhere else. MEASURED
            # 2026-10-08 01:22: natro_home_pine_tree's glide "cut short by a
            # mob, finishing the last 14.0s of 15.4s", the row search found no
            # pad, a 7,487,485 bag went to a Micro-Converter.
            self.airborne = glide is not None and abs(studs - glide) < 1e-6
            try:
                left = self._sleep_resuming(f"coast {studs:.0f}", planned, result)
            finally:
                self.airborne = False
            covered = studs * (1.0 - left / planned) if planned > 0 else studs
            result.studs += covered
            if not self._approach_over:
                # `approach_studs` counts coasts, so the gate must too.
                self._approach_done += covered
        elif op == "hive_offset":
            self._hive_offset(step, result)
        elif op == "shift_lock":
            self._shift_lock()
        elif op == "hop_to_slot":
            self._hop_to_slot(int(step.get("from_slot", 5)), result)
        elif op == "zoom":
            self.vin.tap("o")            # BeeTuxMacro's zoom_out
            time.sleep(0.05)
        elif op == "interact":
            self._held_back(self.vin.tap("e"), "e", result)
        elif op == "interact_when":
            self._interact_when(step, result)
        elif op == "release_all":
            self.vin.release_all()
        elif op == "reset":
            self._reset(result)
        elif op == "call":
            target = str(step.get("route", ""))
            if self._steps_for(target) is None:
                # Not a failure: BeeTuxMacro delegates to helpers we did not
                # transpile. Recorded rather than silently swallowed.
                result.skipped.append(f"call {target}")
            else:
                self.run(target, depth + 1, result)
        elif op == "raw":
            # Shell bookkeeping from the original macro (writing timestamp
            # files, loops). Nothing to do, but say so rather than pretend.
            result.skipped.append(f"raw {step.get('text', '')[:24]}")
        else:
            result.skipped.append(f"unknown op {op!r}")

    # ---- primitives -------------------------------------------------------
    def _hold_seconds(self, studs: float) -> float:
        """How long to hold a key to cover `studs` at our walkspeed -- the speed
        the character HAS, buffs included, not the base figure.

        The inverse of the transpiler's `studs = seconds x 32.2`, which is what
        makes the recordings transferable between players at all; the factor
        is what makes them transferable between a character with Haste and
        one without (Natro's Walk() does the same, continuously).

        AND ONLY FOR AS LONG AS THE BUFF LASTS. The factor is read once, at
        the leg's start, and a Haste runs out on its own clock: MEASURED
        (DESIGN 8dx), attempt 437's 288-stud leg home from Mushroom began
        with a Haste x3 that had about 3 s left, and held the whole leg at
        1.3x -- 7.9 s, some 40 studs short. When the leg at base speed (T0)
        is longer than the factor F covers in the r seconds it has left, it
        is r s at F and the rest at base: T0 - (F - 1) x r. With a bear morph
        up as well there are two clocks (`movespeed_changes`), and the hold
        is walked through each change in turn: r1 s at F, then at what is
        left of it until the next, and so on.
        """
        base = studs / self.walkspeed
        factor = self._speed_factor()
        held = 0.0
        for at, then in self._factor_changes():
            if base <= factor * (at - held):
                break
            base -= factor * (at - held)
            held, factor = at, then
        return held + base / factor

    @staticmethod
    def _flag(read) -> bool:
        """`read()` as a yes or no; no when unset or unreadable."""
        if read is None:
            return False
        try:
            return bool(read())
        except Exception:
            return False

    def _glide_calm_due(self) -> bool:
        """A walk home with a glide, no key held, GLIDE_CALM on and the
        owner's move.home_glide_at_base: the run-up may wait (GLIDE_CALM)."""
        return (GLIDE_COASTS.get(getattr(self, "current_route", None) or "") is not None
                and not self._down and _glide_calm_on()
                and self._flag(self.glide_at_base))

    def _calm_before_glide(self, result: RouteResult, what: str = "glide",
                           where: str = "at the run-up") -> None:
        """Stand at the glide's run-up, keys up, until the buff bar's factor is
        GLIDE_CALM_FACTOR or less, for at most GLIDE_CALM_MAX_S (then it jumps
        as before). Said in the notes when it waited. See GLIDE_CALM."""
        calm_at = glide_calm_factor() if what == "glide" else GLIDE_CALM_FACTOR
        first = factor = self._speed_factor()
        if factor <= calm_at:
            if what == "glide" and factor > 1.0:     # the A/B's other arm, in the log
                result.notes.append(f"{what}: {factor:.2f}x {where}, at or under "
                                    f"{calm_at:.2f}x: jumped at once")
            return
        waited = 0.0
        # Counted in polls, not by the clock: the cap holds however long a
        # sleep really took.
        while factor > calm_at and waited < GLIDE_CALM_MAX_S:
            if self._abandoned() or self._taken():
                return
            time.sleep(GLIDE_CALM_POLL_S)
            waited += GLIDE_CALM_POLL_S
            factor = self._speed_factor()
        went, anyway = (("at the jump", "jumped") if what == "glide"
                        else ("when it walked on", "walked on"))
        result.notes.append(
            f"{what}: waited {waited:.1f}s {where} for the buff bar's {first:.2f}x "
            f"to drop -- {factor:.2f}x {went}"
            + ("" if factor <= calm_at else f" (GLIDE_CALM_MAX_S, {anyway} anyway)")
            + f" [calm at {calm_at:.2f}x]")

    def _buff_ends_soon(self) -> tuple[float, float] | None:
        """The last (seconds, factor) change the buff bar predicts inside
        GLIDE_STEADY_S, freshly read; None when nothing ends that soon."""
        self._speed_factor()
        soon = [c for c in self._factor_changes() if c[0] < GLIDE_STEADY_S]
        return soon[-1] if soon else None

    def _steady_before_glide(self, result: RouteResult) -> None:
        """Stand at the run-up until no buff runs out inside GLIDE_STEADY_S,
        for at most GLIDE_STEADY_MAX_S; look-only unless GLIDE_STEADY_LIVE.
        See GLIDE_STEADY."""
        soon = self._buff_ends_soon()
        if soon is None:
            return
        at, then = soon
        first = self.last_factor
        if not GLIDE_STEADY_LIVE:
            result.notes.append(
                f"glide steady look-only: would wait {min(at, GLIDE_STEADY_MAX_S):.1f}s at the "
                f"run-up -- the buff bar's {first:.2f}x becomes {then:.2f}x in {at:.1f}s, "
                f"inside the {GLIDE_STEADY_S:.0f}s run-up and jump; jumped as before")
            return
        waited = 0.0
        while soon is not None and waited < GLIDE_STEADY_MAX_S:
            if self._abandoned() or self._taken():
                return
            time.sleep(GLIDE_CALM_POLL_S)
            waited += GLIDE_CALM_POLL_S
            soon = self._buff_ends_soon()
        result.notes.append(
            f"glide steady: waited {waited:.1f}s at the run-up for the buff bar's {first:.2f}x "
            f"to run out -- {self.last_factor:.2f}x at the jump"
            + ("" if soon is None else " (GLIDE_STEADY_MAX_S, jumped anyway)"))
        # A Haste that rose while it stood (1161 16:10, Hasty bees) is over
        # the calm bar again: wait that out once more, as the run-up does.
        if self.last_factor > glide_calm_factor():
            self._calm_before_glide(result, where="after the steady wait")

    @staticmethod
    def _glide_scale(read, bounds) -> float:
        """`read()` within `bounds`; 1.0 when unset or unreadable."""
        if read is None:
            return 1.0
        try:
            value = float(read())
        except Exception:
            return 1.0
        if not value > 0:
            return 1.0
        low, high = bounds
        return min(high, max(low, value))

    def _speed_factor(self) -> float:
        """The buff bar's movespeed factor, re-read at most every quarter
        second; 1.0 without a reader or when it fails."""
        if self.movespeed_factor is None:
            return 1.0
        now = time.monotonic()
        read_at, value, _ = self._factor_cache
        if now - read_at < 0.25:
            return value
        try:
            value = float(self.movespeed_factor())
            if not (0.5 <= value <= 4.0):
                value = 1.0
        except Exception:
            value = 1.0
        changes: list = []
        if self.movespeed_changes is not None and value != 1.0:
            try:
                for at, then in self.movespeed_changes() or []:
                    then = float(then)
                    changes.append((max(0.0, float(at)),
                                    then if 0.5 <= then <= 4.0 else 1.0))
                changes.sort()
            except Exception:
                changes = []
        self._factor_cache = (now, value, changes)
        self.last_factor = value
        return value

    def _odometer_deadline(self, deadline: float) -> float:
        """The hold's deadline, moved to where the distance it has left ends
        at the movespeed factor as re-read now. None `_odo`: unchanged.

        THE HOLD IS A DISTANCE, AND A BUFF TAKEN DURING IT CHANGES THE TIME.
        `_hold_seconds` plans the hold once, at its start, and allows for a
        buff running OUT; a Haste stack or a bear morph picked up mid-hold is
        walked at the old speed's timing, so the leg overshoots by the gain.
        MEASURED 2026-09-27 (attempts 503-505): the Brown Bear walk -- the
        Wealth Clock walk's first 24 steps, which landed the clock at 09:36
        and 13:03 with no Haste taken before the ladder -- missed the ladder
        climb at its 17th step 3 times of 3, a ladder-width to the right,
        each time with Haste gained or changed during the walk (14:18:06 x4
        then x5; 14:34:21 x1 at the ladder; 14:48:20 x1 then x2), because the
        bees keep dropping Haste tokens at the hive and the wait for a clear
        bar timed out. So the studs walked are counted as they go, at the
        factor read each tick, and the end moves with it -- what Natro's
        Walk() does by re-reading."""
        odo = self._odo
        if odo is None:
            return deadline
        now = time.monotonic()
        target, walked, last, factor = odo
        walked += self.walkspeed * factor * max(0.0, now - last)
        factor_now = self._speed_factor()
        odo[1], odo[2], odo[3] = walked, now, factor_now
        return now + self._hold_seconds(max(0.0, target - walked))

    def _odometer_remaining(self) -> float:
        """Studs the counted hold still has to walk, as of now."""
        odo = self._odo
        if odo is None:
            return 0.0
        walked = odo[1] + self.walkspeed * odo[3] * max(0.0, time.monotonic() - odo[2])
        return max(0.0, odo[0] - walked)

    def _odometer_pause(self) -> None:
        """The keys were up: nothing was walked since the last count."""
        if self._odo is not None:
            self._odo[2] = time.monotonic()

    def _odometer_stop(self) -> None:
        """End the count; what it had left is kept for a resume."""
        self._odo_left = (self._odometer_remaining() if self._odo is not None
                          else None)
        self._odo = None

    def _factor_changes(self) -> list:
        """`_speed_factor`'s changes, (seconds from now, factor), counted
        down from its read; empty: the factor lasts for any hold."""
        read_at, _, changes = self._factor_cache
        gone = time.monotonic() - read_at
        return [(max(0.0, at - gone), then) for at, then in changes]

    def _sleep_watching(self, seconds: float) -> bool:
        """Sleep, but LOOK while doing it. True if the watcher said stop.

        THIS IS THE CHANGE THAT MAKES REACTING POSSIBLE AT ALL.

        Every walk used to be `time.sleep(distance / walkspeed)` inside a key
        hold, and the gather loop only read the screen after a WHOLE pattern
        pass returned. The default pattern is `farm_snake`, 231.6 studs, which
        at walkspeed 28 is about 8.3 seconds with not one frame examined. Any
        detector wired in above that layer -- a mob, a token, an arrival --
        would be answering a question about a screen from eight seconds ago.

        So the hold is now sliced. The keys stay down exactly as before, the
        total time is unchanged when nothing happens, and between slices the
        watcher gets a look. A mantis nameplate check costs about 7 ms, so at
        10 Hz this spends roughly 7% of one core and buys the ability to stop
        mid-walk.

        Returning True aborts the hold. The caller is inside `vin.held()`, so
        the keys come up on the way out however it exits.
        """
        self._paused_s = 0.0
        if seconds <= 0:
            return False
        if self.watch is None and not self._owner_watched() and self._odo is None:
            time.sleep(seconds)
            return False
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(self.watch_interval, remaining))
            deadline = self._odometer_deadline(deadline)
            if self._odo is not None and deadline <= time.monotonic():
                return False
            if self.watch is None and not self._owner_watched():
                continue
            held = self._owner_hold()
            if held is None:
                return True               # a Take Over: this hold is over
            if held:
                self._odometer_pause()
                deadline += held          # a Pause: carry on mid-stride
                self._paused_s += held
                continue
            if self.watch is None:
                continue
            try:
                if self.watch():
                    self.interrupted += 1
                    return True
            except Exception:
                # A watcher that throws must not strand a held key or end the
                # route. It is an observer; the walk is the job.
                pass

    # ---- the owner's buttons, inside a hold --------------------------------
    def _owner_watched(self) -> bool:
        """Does the input carry the owner's Pause / Take Over?"""
        return callable(getattr(self.vin, "hold_point", None))

    def _owner_hold(self) -> float | None:
        """Called every slice of every hold. The seconds the owner's Pause (or
        a Take Over he has not yet passed back) held the bot here -- the keys
        came up at once and go back down now, so the caller adds them to its
        deadline -- or 0.0 when nothing did, or None when he has taken the
        controls since this cycle began: the hold is over and so is the route
        (`_taken`, OWNER_TOOK).

        WHY THE HOLDS ASK AND NOT ONLY THE PRESSES (audit 2026-09-26, brain
        F2). brain/controls.GuardedInput gates every press, but a press is
        made once and then held: `coast` sleeps 15.4 s with W down, a gather
        leg up to 8 s, so a Pause landed mid-hold kept the character walking
        until the hold ended. At WATCH_HZ the keys come up within a tenth of
        a second. The input is brain/controls.GuardedInput in run_farm; any
        other input has no `hold_point`, and this is 0.0.
        """
        point = getattr(self.vin, "hold_point", None)
        if not callable(point):
            return 0.0
        try:
            held = point()
        except Exception:
            return 0.0
        if held is None:
            return None
        return float(held) if isinstance(held, (int, float)) else 0.0

    def _taken(self) -> bool:
        """Has the owner taken the controls since the cycle began? Then no
        key this route sends reaches the game (GuardedInput.stale)."""
        return getattr(self.vin, "stale", False) is True

    def _held_back(self, sent, key: str, result: RouteResult) -> bool:
        """True when `key` is an E the input did not send after a Pause, and
        the route has been failed with HELD_BACK. A raw input returns None,
        so this is never true without GuardedInput; after a Take Over it is
        left to `_owner_took`, which fails the route as OWNER_TOOK."""
        if sent is not False or str(key).lower() != "e" or self._taken():
            return False
        if result.ok:
            result.ok, result.reason = False, HELD_BACK
        return True

    def _sleep_resuming(self, what: str, seconds: float,
                        result: RouteResult | None,
                        keys: str | None = None) -> float:
        """`_sleep_watching` that FINISHES what a mob interrupted, the way
        `_walk` does. Returns the seconds never walked (0.0 when finished).

        `keys` None is a `coast`: the keys are the ones `key_down` put down
        (`self._down`), lifted while waiting for `settle` and put back down
        for the rest. `keys` given is a `hold`, held here for each pass.
        """
        left = seconds
        for attempt in range(RESUME_ATTEMPTS + 1):
            if keys is None:
                began = time.monotonic()
                stopped = self._sleep_watching(left)
            else:
                with self.vin.held(*keys):
                    # Inside the hold: a Pause the press itself waited out
                    # at the gate is not walking either.
                    began = time.monotonic()
                    stopped = self._sleep_watching(left)
            if not stopped:
                return 0.0
            # The wall clock less what a Pause held (`_paused_s`).
            left = max(0.0, left - (time.monotonic() - began - self._paused_s))
            if left <= 0.0:
                return 0.0
            if self._taken():
                return left                # the route fails at the step's end
            if self.settle is None:
                # No settle: behaviour as before (see `settle`), but said.
                if result is not None:
                    result.notes.append(f"{what}: cut short by a mob, {left:.1f}s "
                                        f"of {seconds:.1f}s not walked")
                return left
            # A death ends the route here, as in `_walk` (`abandon`).
            why = self._abandoned()
            if why is None and attempt >= RESUME_ATTEMPTS:
                self._unwalked(result, what, left, seconds,
                               f"cut short {attempt + 1} times")
                return left
            down = list(self._down) if keys is None else []
            for key in down:
                self.vin.release(key)
            if why is not None or not self._wait_to_settle():
                for key in down:           # up, and no longer ours to lift
                    if key in self._down:
                        self._down.remove(key)
                why = why or self._abandoned()
                if why is not None:
                    self._abandon_route(result, what, left, seconds, why)
                else:
                    self._unwalked(result, what, left, seconds,
                                   "not safe to finish (mob/death/dialogue)")
                return left
            for key in down:
                self.vin.press(key)
            self.resumed += 1
            if result is not None:
                result.notes.append(f"{what}: cut short by a mob, finishing the "
                                    f"last {left:.1f}s of {seconds:.1f}s")
        return left

    def _unwalked(self, result: RouteResult | None, what: str, left: float,
                  planned: float, why: str) -> None:
        """A leg a mob cut short and nothing could finish: say it, and stop
        the route there (see UNWALKED) -- except inside a gather pattern,
        where a short leg is a slightly different lap of the same field and
        ending the pass would end the whole trip (brain/farm `_gather_loop`
        breaks on a pass that is not ok).

        A GATHER PATTERN BY ROLE, NOT BY NAME: any ROUTINE, as `_snap` has
        it. The pattern is `natro_pattern_*` only where Natro has one; for
        the other fields, and always under --no-brain, it is `--pattern`
        (`farm_snake`), and the name test failed that pass and ended the
        trip on one short leg."""
        if result is None:
            return
        text = (f"{what}: {left:.1f}s of {planned:.1f}s {UNWALKED} — {why}")
        result.notes.append(text)
        name = self.current_route
        if (name.startswith(PATTERN_PREFIX)
                or name in getattr(self.router, "routines", {}) or not result.ok):
            return
        result.ok = False
        result.reason = text

    def _walk(self, keys: str, studs: float, result: RouteResult | None = None) -> None:
        """Hold the movement keys for as long as that distance takes.

        `held()` rather than press/release so the keys come up on any
        exception, including a panic.
        """
        if not keys or studs <= 0:
            return
        planned = self._hold_seconds(studs)
        # Tell `approach_fraction` which leg is running, so the gate can count
        # the leg in progress instead of only the finished ones.
        self._leg_studs = studs if not self._approach_over else 0.0
        self._leg_seconds = planned
        self._leg_started = time.monotonic()
        try:
            remaining = planned
            # WHAT THE NEXT HOLD WALKS, AS A DISTANCE (`_odometer_deadline`):
            # the leg, then whatever a stopped hold still had left. Only with a
            # movespeed reader; without one there is no factor to change.
            to_walk = studs if self.movespeed_factor is not None else None
            for attempt in range(RESUME_ATTEMPTS + 1):
                # THE KEYS COME UP WHILE WE WAIT. `held` is a context manager
                # per attempt rather than around the whole loop, so the
                # character is standing still during the settle -- walking on
                # would defeat the reaction that stopped it.
                with self.vin.held(*keys):
                    if self.pace is None or self.flow is None:
                        self._odo = ([float(to_walk), 0.0, time.monotonic(),
                                      self._speed_factor()]
                                     if to_walk else None)
                        try:
                            left = self._hold_watching(keys, studs, remaining,
                                                       result)
                        finally:
                            self._odometer_stop()
                        if self._odo_left is not None:
                            to_walk = self._odo_left
                    else:
                        self._walk_measured(keys, remaining)
                        left = 0.0
                self._flush_tail()             # keys up: LEAN_LOOK_TAIL_S's frames
                if left <= 0.0 or self.settle is None or self._taken():
                    break
                # A DEATH ENDS THE ROUTE HERE (`abandon`), asked before the
                # wait for `settle` as well as after it, so a death does not
                # first cost SETTLE_TIMEOUT of standing still.
                why = self._abandoned()
                # THE LAST PASS DOES NOT PROMISE A FINISH IT CANNOT WALK: it
                # used to note "finishing the last Xs" and then leave the loop.
                if why is None and attempt >= RESUME_ATTEMPTS:
                    self._unwalked(result, keys, left, planned,
                                   f"cut short {attempt + 1} times")
                    break
                settled = why is None and self._wait_to_settle()
                if not settled:
                    why = why or self._abandoned()
                    if why is not None:
                        self._abandon_route(result, keys, left, planned, why)
                    else:
                        self._unwalked(result, keys, left, planned,
                                       "not safe to finish (mob/death/dialogue)")
                    break
                self.resumed += 1
                if result is not None:
                    result.notes.append(
                        f"{keys}: cut short by a mob, finishing the last "
                        f"{left:.1f}s of {planned:.1f}s")
                remaining = left
            self._unstick(keys, result)
        finally:
            if not self._approach_over:
                self._approach_done += studs
            self._leg_studs = self._leg_seconds = 0.0

    def _unstick(self, keys: str, result: RouteResult | None) -> None:
        """W3: A WALK HOME WEDGED INTO A WALL GOES ROUND IT. MEASURED
        2026-10-12 (backlog W3): the misses begin with an early leg blocked for
        nearly all of it -- "natro_home_cactus: w for 360 studs: pushed against
        something for 10.6 of 10.8s" -- because the gather ended away from the
        route's start; the rest of the route then runs blind from the wrong
        place. So on a natro_home_* route, a single-key leg blocked for
        UNSTICK_SHARE of at least UNSTICK_MIN_S backs off, side-steps (the side
        alternates) and walks its blocked part once more. Hour-block A/B
        (HOME_UNSTICK "ab": even hours on) so the landing rates can be compared."""
        try:
            blocked, seconds = getattr(self, "_last_blocked", (0.0, 0.0))
            self._last_blocked = (0.0, 0.0)
            if (not str(self.current_route).startswith("natro_home_") or len(keys) != 1
                    or keys not in UNSTICK_SIDES or seconds < UNSTICK_MIN_S
                    or blocked < UNSTICK_SHARE * seconds or not _unstick_on()):
                return
            if self._taken():
                return
            self._unstick_n = getattr(self, "_unstick_n", 0) + 1
            side = UNSTICK_SIDES[keys][self._unstick_n % 2]
            back = {"w": "s", "s": "w", "a": "d", "d": "a"}[keys]
            with self.vin.held(back):
                time.sleep(UNSTICK_BACK_S)
            with self.vin.held(side):
                time.sleep(UNSTICK_SIDE_S)
            with self.vin.held(keys):
                time.sleep(min(blocked, UNSTICK_RETRY_MAX_S))
            if result is not None:
                result.notes.append(f"{keys}: wedged ({blocked:.1f} of {seconds:.1f}s) -- "
                                    f"backed off, stepped {side}, walked {min(blocked, UNSTICK_RETRY_MAX_S):.1f}s more")
        except Exception:
            pass

    def _abandoned(self) -> str | None:
        """The `abandon` hook's reason, or None. A hook that raises is None:
        it is an observer, and the walk is the job."""
        if self.abandon is None:
            return None
        try:
            why = self.abandon()
        except Exception:
            return None
        return str(why) if why else None

    def _abandon_route(self, result: RouteResult | None, what: str, left: float,
                       planned: float, why: str) -> None:
        """Fail the route where `abandon` said the rest of it must not be
        walked (`why`, a death). Unlike `_unwalked` this stops a gather
        pattern too -- `abandoned` is what brain/farm reads to end the trip
        rather than the loop -- and the reason carries UNWALKED, so
        nav.journey retries a walk out from the pad with the same pose: a
        death says no more about the pose than a mob that cut a leg."""
        if result is None:
            return
        result.ok = False
        result.abandoned = why
        result.reason = (f"{what}: cut short with {left:.1f}s of {planned:.1f}s "
                         f"{UNWALKED}, and {why} — the rest of the route is "
                         f"not walked from here")

    def _wait_to_settle(self) -> bool:
        """Wait for `settle()` to say the coast is clear. False on timeout."""
        if self.settle is None:
            return False
        deadline = time.monotonic() + SETTLE_TIMEOUT
        while time.monotonic() < deadline:
            try:
                if self.settle():
                    return True
            except Exception:
                return False
            time.sleep(SETTLE_POLL)
        return False

    def _hold_plain(self, keys: str, seconds: float,
                    result: RouteResult | None) -> bool:
        """The timed hold with `watch` and `arrive` but no flow meter."""
        self._paused_s = 0.0
        if seconds <= 0:
            return False
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(self.watch_interval, remaining))
            deadline = self._odometer_deadline(deadline)
            if self._odo is not None and deadline <= time.monotonic():
                return False
            held = self._owner_hold()
            if held is None:
                return True
            if held:
                self._odometer_pause()
                deadline += held
                self._paused_s += held
                continue
            if self._may_arrive():
                try:
                    if self.arrive():
                        self._arrived = True
                        self.arrivals += 1
                        if result is not None:
                            result.notes.append(
                                f"{keys}: stopped early — the target is in view")
                        return False
                except Exception:
                    pass
            if self.watch is not None:
                try:
                    if self.watch():
                        self.interrupted += 1
                        return True
                except Exception:
                    pass

    def _hold_watching(self, keys: str, studs: float, seconds: float,
                       result: RouteResult | None) -> float:
        """`_sleep_watching`, plus: notice when the held keys are moving nothing.
        Returns the seconds a mob left unwalked (0.0 when the hold finished).

        With no `flow` this is exactly `_sleep_watching`. With one, the world's
        motion is sampled at the watch rate and the seconds below
        BLOCKED_FLOW_PX are added up. `flow()` returning None means "could not
        tell" -- a featureless floor gives the tracker nothing to hold on to --
        and is NOT counted as blocked; only a real reading below the threshold
        is. The hold is NEVER cut short for being blocked: BeeTuxMacro's routes
        lean on walls deliberately to square up, and ending such a hold early
        would break the alignment it exists for. The time is written to the
        result instead, so whoever reads it knows the difference between
        "walked 212 studs" and "walked 30 and leaned on a wall for the rest".
        """
        if self.flow is None:
            # SECONDS, NOT THE BOOL: `_walk` resumes this many, and True used
            # to resume exactly 1.0 s whatever the mob had left.
            began = time.monotonic()
            if self.arrive is None:
                stopped = self._sleep_watching(seconds)
            else:
                stopped = self._hold_plain(keys, seconds, result)
            if not stopped:
                return 0.0
            if self._odo is not None:
                # what is left of the DISTANCE: the plan's seconds no longer
                # say, once a buff has moved the end (`_odometer_deadline`)
                return self._hold_seconds(self._odometer_remaining())
            return max(0.0, seconds - (time.monotonic() - began - self._paused_s))
        if seconds <= 0:
            return 0.0
        try:
            self.flow()                        # prime: the previous frame may be old
        except Exception:
            pass
        deadline = time.monotonic() + seconds
        began = last = time.monotonic()
        blocked = 0.0
        trail = None                           # blocked seconds without a break, to now
        stopped = False
        # Seconds of this hold that were never walked, so `_walk` can finish
        # them once the coast is clear. See RESUME_ATTEMPTS.
        left = 0.0
        # WHEN the wall was first met, as seconds into the hold. `_hive_offset`
        # turns that into a distance and the distance into which hive slot
        # this is -- see its docstring. None until the flow first reads
        # blocked for a sustained stretch.
        first_blocked_at: float | None = None
        tail = (LEAN_LOOK_TAIL_S > 0 and self.snapshot is not None
                and self.grab_frame is not None
                and self._step_idx <= LEAN_LOOK.get(self.current_route, 0))
        tail_n = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self.watch_interval, remaining))
            deadline = self._odometer_deadline(deadline)
            if self._odo is not None and deadline <= time.monotonic():
                break
            held = self._owner_hold()
            if held is None:
                stopped = True
                left = max(0.0, deadline - time.monotonic())
                break
            if held:
                # Paused with the keys up: not walked, and not blocked either.
                self._odometer_pause()
                deadline += held
                began += held
                last = time.monotonic()
                continue
            now = time.monotonic()
            px = None
            try:
                px = self.flow()
            except Exception:
                pass
            if px is not None:
                px = float(px)
                if px < BLOCKED_FLOW_PX:
                    blocked += now - last
                    trail = (trail or 0.0) + (now - last)
                    if first_blocked_at is None and blocked >= BLOCKED_ONSET_SECONDS:
                        first_blocked_at = (now - began) - blocked
                else:
                    trail = 0.0
                if self.on_motion is not None:
                    try:
                        self.on_motion(keys, px)
                    except Exception:
                        pass
                if tail and deadline - now <= LEAN_LOOK_TAIL_S:     # LEAN_LOOK_TAIL_S
                    tail_n += 1
                    try:
                        self._tail.append((f"{self.current_route}-{self._step_idx:02d}"
                                           f"-tail-{tail_n:02d}-px{px:.1f}", self.grab_frame()))
                    except Exception:
                        pass
            last = now
            if self._may_arrive():
                try:
                    if self.arrive():
                        self._arrived = True
                        self.arrivals += 1
                        if result is not None:
                            result.notes.append(
                                f"{keys}: stopped early — the target is in view")
                        break
                except Exception:
                    pass
            if self.watch is not None:
                try:
                    if self.watch():
                        self.interrupted += 1
                        stopped = True
                        left = max(0.0, deadline - time.monotonic())
                        break
                except Exception:
                    pass
        self._last_first_blocked_at = first_blocked_at
        self._last_blocked = (blocked, seconds)
        self._last_trail = trail
        if result is not None:
            if result.first_walk == (0.0, 0.0):
                result.first_walk = (blocked, seconds)
            if blocked >= BLOCKED_NOTE_SECONDS:
                result.blocked_seconds += blocked
                result.notes.append(
                    f"{keys} for {studs:.0f} studs: pushed against something "
                    f"for {blocked:.1f} of {seconds:.1f}s")
        return left if stopped else 0.0

    def _lean_look(self, keys: str, studs: float, result: RouteResult | None) -> None:
        """LEAN_LOOK: say whether the timed walk just run ended against a wall,
        as `_lean` would judge it, and what a lean would have done -- nothing
        walked differently."""
        trail = self._last_trail
        if result is None or trail is None:
            return
        cap = self._hold_seconds(studs) * LEAN_CAP_FACTOR
        if trail >= LEAN_STOP_SECONDS:
            said = f"ended against the wall ({trail:.1f}s blocked at the end)"
        else:
            said = (f"ended still moving ({trail:.1f}s blocked at the end) -- a lean "
                    f"would have held on toward the wall, up to {cap:.1f}s")
        result.notes.append(f"{keys} for {studs:.0f} studs, lean look-only: {said}")

    def _lean(self, keys: str, studs: float, result: RouteResult | None) -> None:
        """Walk INTO the wall this leg is for, and stop when the flow says
        we are against it -- however far away it was.

        The recorded hold is Natro's estimate of the distance from the
        pattern's end to the wall; ours can be anywhere in the field. So the
        key is held past the recording while the world still slides, and
        released after LEAN_STOP_SECONDS of continuous blocked flow, or at
        LEAN_CAP_FACTOR times the recording. Without a flow reader there is
        nothing to watch and the recording is walked as written. A mob ends
        the hold like any other (`watch`); the remainder is not resumed,
        because a lean has no remainder -- it is done when the wall is.
        """
        seconds = self._hold_seconds(studs)
        if self.flow is None or seconds <= 0:
            self._walk(keys, studs, result)
            return
        cap = seconds * LEAN_CAP_FACTOR
        earliest = seconds * LEAN_EARLIEST
        try:
            self.flow()                        # prime: the previous frame may be old
        except Exception:
            pass
        began = last = time.monotonic()
        blocked_run = 0.0
        outcome = "ran to the cap without meeting a wall"
        with self.vin.held(*keys):
            while True:
                now = time.monotonic()
                elapsed = now - began
                if elapsed >= cap:
                    break
                time.sleep(min(self.watch_interval, cap - elapsed))
                held = self._owner_hold()
                if held is None:
                    outcome = f"ended by the owner's Take Over after {elapsed:.1f}s"
                    break
                if held:
                    began += held
                    last = time.monotonic()
                    continue
                now = time.monotonic()
                px = None
                try:
                    px = self.flow()
                except Exception:
                    pass
                if px is not None:
                    if float(px) < BLOCKED_FLOW_PX:
                        blocked_run += now - last
                    else:
                        blocked_run = 0.0
                    if self.on_motion is not None:
                        try:
                            self.on_motion(keys, px)
                        except Exception:
                            pass
                last = now
                elapsed = now - began
                if blocked_run >= LEAN_STOP_SECONDS and elapsed >= earliest:
                    outcome = (f"reached the wall after {elapsed:.1f}s "
                               f"(recorded {seconds:.1f}s)")
                    break
                if self.watch is not None:
                    try:
                        if self.watch():
                            self.interrupted += 1
                            outcome = f"cut short by a mob after {elapsed:.1f}s"
                            break
                    except Exception:
                        pass
        if result is not None:
            result.notes.append(f"{keys} lean for {studs:.0f} studs: {outcome}")

    def _walk_measured(self, keys: str, planned: float) -> None:
        """Hold until the world has slid the expected distance.

        THE DRIFT THIS FIXES was spotted by the owner watching a live run:
        "on the field it was heavily to the right that could be maybe sinceit
        picked up a haste token here and there". A timed hold assumes a fixed
        walkspeed, so every speed buff makes every leg overshoot, and the
        error accumulates over a route until the character is somewhere else
        entirely -- up a ramp, into a wall, inside the trophy store.

        Flow gives the ratio without any calibration: if the world is sliding
        1.4x faster than this kind of step usually makes it slide, the
        character is going 1.4x as fast and the hold should end that much
        sooner. `nav.pace.PaceMeter` learns the usual rate per key
        combination and refuses to answer until it has enough samples, so the
        first walks of a session run on the recorded timing and teach it.

        The timer does not go away -- it becomes a CEILING. A walk that never
        accumulates its expected flow (blocked by a wall, which is exactly
        what the owner watched happen) must not hold the key forever, so it
        stops at `WALK_TIME_CEILING` times the planned time regardless.
        """
        usual = self.pace.baseline(keys)
        target = None if usual is None else usual * planned
        deadline = time.monotonic() + planned * WALK_TIME_CEILING
        started = time.monotonic()
        moved = 0.0
        while True:
            now = time.monotonic()
            elapsed = now - started
            if target is None and elapsed >= planned:
                break                      # no baseline: recorded timing
            if now >= deadline:
                break                      # blocked, or the measurement lied
            slice_for = min(self.watch_interval, deadline - now)
            time.sleep(max(0.0, slice_for))
            held = self._owner_hold()
            if held is None:
                break
            if held:
                deadline += held
                started += held
                continue
            try:
                moved += max(0.0, float(self.flow() or 0.0))
            except Exception:
                target = None              # lost the measurement; fall back
            if self.watch is not None:
                try:
                    if self.watch():
                        self.interrupted += 1
                        break
                except Exception:
                    pass
            if target is not None and moved >= target:
                self.paced_walks += 1
                break
        self.pace.observe(keys, moved, max(1e-6, time.monotonic() - started))

    def _hive_offset(self, step: dict, result: RouteResult) -> None:
        """Walk from the ramp to the pad this account owns, and refuse to guess.

        THE ONE NUMBER EVERY ROUTE OUT OF THE HIVE DEPENDS ON. Natro Macro's
        paths all open with `nm_gotoRamp()`, which is
        `nm_Walk(5, Fwd)` then `nm_Walk(9.2*HiveSlot-4, Right)` -- so the hive
        slot is a NUMBER in a linear formula and a path can be run from any
        slot by supplying it. That is exactly what BeeTuxMacro's routes could
        not express: they bake the recorder's own slot in, which is why
        31-83% of every walk on this account was measured going nowhere
        (docs/DESIGN.md 8k).

        With `hive_slot` unset this SKIPS and says so, rather than walking a
        guessed distance sideways. `nav.journey` searches the six slots by
        arriving, which is the only way the bot can learn it without being
        told -- and being told takes ten seconds in the Movement panel.
        """
        per_slot = float(step.get("tiles_per_slot", 9.2) or 9.2)
        offset = float(step.get("tiles_offset", -4.0) or -4.0)
        per_tile = float(step.get("studs_per_tile", 4.0) or 4.0)
        keys = str(step.get("keys", "d"))
        if self.hive_slot is not None:
            studs = (per_slot * int(self.hive_slot) + offset) * per_tile
            if studs <= 0:
                return
            self._walk(keys, studs, result)
            result.studs += studs
            return

        # SLOT UNKNOWN: OVERSHOOT TO THE RAMP AND MEASURE THE SLOT ON THE WAY.
        #
        # The ramp is a corner -- Natro's own comment calls it "corner (Hive 1
        # and ramp)", and Natro's return paths deliberately walk 35 tiles INTO
        # it to normalise position. So walking the distance slot 6 would need
        # reaches the ramp from any pad; the wall stops the character where
        # the formula would have. The hold is never cut short for being
        # blocked (see _hold_watching), which is exactly what makes this work.
        #
        # And the wall says which pad we left from: `nm_gotoRamp` walks
        # 9.2*slot-4 tiles, so the distance walked before the flow first read
        # blocked, inverted, IS the slot. Ten seconds of the owner's time
        # replaced by one measurement the bot was already able to take. It is
        # reported, not silently adopted: `learned_slot` on the result, for
        # the caller to confirm against later trips before trusting it.
        farthest = (per_slot * MAX_HIVE_SLOT + offset) * per_tile
        if not self.flow:
            result.skipped.append(
                "hive_offset (the hive slot is not configured and there is no "
                "flow reading to feel for the ramp with, so a sideways walk "
                "would be a guess)")
            return
        self._last_first_blocked_at = None
        self._walk(keys, farthest, result)
        result.studs += farthest
        onset = self._last_first_blocked_at
        if onset is None:
            result.notes.append(
                f"hive_offset: walked the full {farthest:.0f} studs toward the "
                f"ramp without meeting a wall — either the ramp is further than "
                f"slot {MAX_HIVE_SLOT}'s formula or the flow could not see it")
            return
        walked = onset * self.walkspeed
        slot = (walked / per_tile - offset) / per_slot
        result.learned_slot = int(math.floor(slot + SLOT_ROUND_UP))
        result.learned_slot_raw = float(slot)
        result.notes.append(
            f"hive_offset: met the ramp after {walked:.0f} studs, which is "
            f"slot {slot:.1f} by Natro's formula — learned slot "
            f"{result.learned_slot}")

    def _shift_lock(self) -> None:
        time.sleep(SHIFT_LOCK_BEFORE)
        self.vin.tap("shift")
        time.sleep(SHIFT_LOCK_AFTER)

    def _hop_to_slot(self, from_slot: int, result: RouteResult) -> None:
        """Hop sideways along the hive slots to the one the player owns.

        THIS IS WHY THE RECORDED ROUTES WORK. Every route out of the hive
        assumes the character starts at ITS OWN SLOT, and this is how
        BeeTuxMacro gets there: `for ((i=0; i<5-$1; i++)); do jump; sleep
        0.56; jump; sleep 1; done`, where `$1` is the slot number.

        Transpiled as an opaque shell line the hop vanished, and the first
        live run duly ended on sand beside slot 5 instead of at Pine Tree.

        `hive_slot` cannot be derived from anything here -- it is which of the
        six slots the account owns -- so it is a setting, and when it is unset
        the hop is skipped and SAID to be skipped rather than guessed at.
        """
        if self.hive_slot is None:
            result.skipped.append("hop_to_slot (hive slot not configured)")
            return
        for _ in range(max(0, from_slot - self.hive_slot)):
            self.vin.tap("space")
            time.sleep(HOP_RISE)
            self.vin.tap("space")        # the second jump carries it across
            time.sleep(HOP_SETTLE)

    # ---- a press with a precondition ---------------------------------------
    def _interact_when(self, step: dict, result: RouteResult) -> None:
        """Press E only once the panel says what this step expects.

        The difference from `interact` is the reading. `interact` taps E where
        the route says to, which is right at the red cannon because
        `_cannon_approach` has already read "Fire the Red Cannon" off the
        panel before it gets there. This op is for a press in the MIDDLE of a
        route, where nothing else has looked: the blue portal on the way home
        from Bamboo and the Blue Flower Field. See PORTAL_WAIT_SECONDS.

        It refuses rather than presses when there is no panel reader, when the
        words never appear, and when the panel says one of
        `act/errands.NEVER_PRESS` whatever else it also says. A refusal stops
        the route (`run` breaks on `ok`), which is right: the legs after a
        door are a route from the other side of it.
        """
        from .errands import NEVER_PRESS            # local: keeps act/ acyclic

        want = [str(w).lower() for w in (step.get("expect") or ()) if str(w).strip()]
        why = str(step.get("why") or "").strip()
        where = f" at {why}" if why else ""
        if not want:
            result.ok = False
            result.reason = (f"a press{where} with nothing to check for is a "
                             f"blind press, so nothing was pressed")
            return
        if self.panel_text is None:
            result.ok = False
            result.reason = (f"the press{where} needs a panel reader "
                             f"(RouteRunner.panel_text) to see {want[0]!r}")
            return
        waited = max(0.0, float(step.get("wait", PORTAL_WAIT_SECONDS) or 0.0))
        saw = ""

        def look(seconds: float) -> bool:
            """Read the panel for `seconds`; True once the step is settled
            (pressed, refused, or the owner took over)."""
            nonlocal saw
            deadline = time.monotonic() + seconds
            while True:
                try:
                    text = self.panel_text()
                except Exception:
                    text = None
                words = " ".join(str(text or "").lower().split())
                if words:
                    saw = words
                    refused = next((bad for bad in NEVER_PRESS if bad in words), "")
                    if refused:
                        result.ok = False
                        result.reason = (f"the panel{where} says {words!r} — "
                                         f"{refused!r} is not something this bot "
                                         f"presses, so nothing was pressed")
                        return True
                    if all(word in words for word in want):
                        if self.vin.tap("e") is False:
                            if self._taken():
                                return True     # `_owner_took` fails the route
                            # A Pause held it back: read the panel again, and
                            # press only on what it says now.
                            result.notes.append(f"{HELD_BACK}{where} — reading "
                                                f"the panel again")
                            continue
                        result.notes.append(
                            f"pressed E{where}: the panel said {words!r}")
                        return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(min(PANEL_POLL_SECONDS, max(0.0, deadline - time.monotonic())))

        if look(waited):
            return
        # P1 (PORTAL_SEARCH): the door's words never showed -- step left and
        # read again, a few times, before giving the walk up.
        if PORTAL_SEARCH == "on" and "portal" in want:
            before = saw or "no panel"
            for n in range(1, PORTAL_SEARCH_STEPS + 1):
                self._walk(PORTAL_SEARCH_KEY, PORTAL_SEARCH_STUDS, result)
                if self._taken() or not result.ok:
                    return              # the owner, or a death (`abandon`)
                if look(PORTAL_SEARCH_LOOK_S):
                    result.notes.append(
                        f"P1 portal search: no {want[0]!r} in {waited:.0f}s "
                        f"({before}); read it after {n} step(s) of "
                        f"{PORTAL_SEARCH_STUDS:.0f} studs {PORTAL_SEARCH_KEY}")
                    self._snap(f"{self.current_route}-portal-search-found")
                    return
            result.notes.append(
                f"P1 portal search: no {want[0]!r} in {waited:.0f}s ({before}), nor "
                f"after {PORTAL_SEARCH_STEPS} steps of {PORTAL_SEARCH_STUDS:.0f} studs "
                f"{PORTAL_SEARCH_KEY} (last: {saw or 'no panel'})")
            self._snap(f"{self.current_route}-portal-search-missed")
        result.ok = False
        result.reason = (
            f"nothing was pressed{where}: {waited:.0f}s without a panel saying "
            + " and ".join(repr(word) for word in want)
            + (f", and it said {saw!r}" if saw else ", and there was no panel"))

    # ---- the red cannon ----------------------------------------------------
    def _cannon_seen(self) -> bool:
        """The stop signal for a key held near the cannon.

        The cannon's own template when `cannon_prompt` is wired: about 1.5 ms
        a look, and specific to the RED cannon (vision/screenstate
        .RED_CANNON_THRESHOLD, measured against every other panel saved). The
        first time it fires in an approach, that frame is kept as
        'cannon-seen', so the next live run shows where the character stood
        when the key came up (the frame is the one just matched; encoding it
        at run_farm's JPEG q70 took 2.7 ms for a saved 1920x1080 frame, 2026-
        09-25, to tmpfs -- a tenth of a stud of extra hold).

        NO SCORE IS NOT THERE -- nothing wired, the file missing, no frame --
        the rule `vision/screenstate.make_honey_present` keeps for the hive
        pad's held key: "I cannot tell" must never read as "we are there".
        The panel read is no stand-in. run_farm's `read_panel` asks the model
        once `banner.find` sees the banner, and MEASURED in run-267 that read
        took three seconds (hop frame 00:32:55, "I am at the red cannon"
        00:32:58): 84 studs of a key held at 28 studs/s, past the 54 studs
        the overrun check can walk back (CANNON_OVERRUN_CHECKS x
        CANNON_OVERRUN_STEP_TILES tiles). Each such look is counted, and the
        approach says so, so the hold runs out and the trip walks (8de).
        """
        score = None
        if self.cannon_prompt is not None:
            try:
                score = self.cannon_prompt()
            except Exception:
                return False
        if score is None:
            self._cannon_unscored += 1
            return False
        score = float(score)
        if self._cannon_best is None or score > self._cannon_best:
            self._cannon_best = score
        if score < RED_CANNON_THRESHOLD:
            return False
        self._cannon_score = score
        if not self._cannon_snapped:
            self._cannon_snapped = True
            self._snap("cannon-seen")
        return True

    def _cannon_look(self) -> float | None:
        """One template score of the banner right now, or None when there is
        no template look to take. Unlike `_cannon_seen` it only looks."""
        if self.cannon_prompt is None:
            return None
        try:
            score = self.cannon_prompt()
        except Exception:
            return None
        return None if score is None else float(score)

    def _cannon_note(self, result: RouteResult):
        """`find_along_row`'s notes, filed under the cannon. Its words are the
        hive's ("without the hive prompt"), and run-398 logged "cannon: held
        left for 5s without the hive prompt" for the cannon search."""
        return lambda text: result.notes.append(
            "cannon: " + str(text).replace("the hive prompt", "the cannon's prompt"))

    def _cannon_hold(self, result: RouteResult):
        """Natro's hold: right down until the prompt shows, then the overrun
        check (`hiverow.find_along_row`, which walks the overrun back with
        the opposite key: left, Natro's LeftKey). Its RowResult, or None when
        no hold was possible."""
        if not hasattr(self.vin, "held"):
            result.notes.append("cannon: no hold was possible — this input "
                                "cannot hold a key down")
            return None
        try:
            from . import hiverow
        except Exception:
            return None
        try:
            return hiverow.find_along_row(
                self.vin, lambda: True, lambda _frame: self._cannon_seen(),
                walkspeed=max(1.0, self.walkspeed * self._speed_factor()),
                holds=((CANNON_HOLD_KEY, "right", CANNON_HOLD_SECONDS),),
                poll=CANNON_POLL_S, settle=CANNON_OVERRUN_SETTLE_S,
                overrun_tiles=CANNON_OVERRUN_STEP_TILES,
                tries=CANNON_OVERRUN_CHECKS,
                sleep=time.sleep, clock=time.monotonic,
                on_note=self._cannon_note(result))
        except Exception as exc:
            result.notes.append(f"cannon: the hold itself failed ({exc})")
            return None

    def _cannon_template_said(self) -> str:
        if self._cannon_score is not None:
            return f"template {self._cannon_score:.2f}"
        if self._cannon_best is not None:
            return f"template best {self._cannon_best:.2f}"
        return "no template"

    def _cannon_confirmed(self, result: RouteResult, how: str) -> bool:
        """ONE PANEL READ, STANDING STILL, and it must name the cannon.

        The template stopped the key; this is the read the E press has always
        waited for, and the press itself is still the route's own step after
        the approach returns. True: at the cannon, noted with what the next
        live run needs to measure. False with `result.ok` False: the reader
        could not look, so nothing is pressed and the trip is a miss. False
        with `result.ok` still True: the panel says something else, and the
        caller searches on.

        When the reader cannot look (None: the vision model has no room to
        load, or no server), one template look standing still decides
        instead: at or above CANNON_TEMPLATE_CONFIRMS the banner says "Fire
        the Red Cannon" (see there); below it the trip is a miss, as before.
        """
        try:
            text = self.panel_text()
        except Exception:
            text = None
        if text is None:
            still = self._cannon_look()
            if still is not None and still >= CANNON_TEMPLATE_CONFIRMS:
                result.notes.append(
                    f"at the red cannon after {how}: the panel reader could "
                    f"not look, and the banner's template reads {still:.2f} "
                    f"standing still -- the words 'Fire the Red Cannon' "
                    f"(CANNON_TEMPLATE_CONFIRMS {CANNON_TEMPLATE_CONFIRMS:.2f})")
                return True
            result.ok = False
            result.reason = (f"{CANNON_MISS}: after {how} the cannon's "
                             f"{self._cannon_template_said()}, but the panel "
                             f"reader could not look, so nothing was pressed"
                             + (f" (standing still the template reads "
                                f"{still:.2f}, under "
                                f"{CANNON_TEMPLATE_CONFIRMS:.2f})"
                                if still is not None else ""))
            return False
        words = " ".join(str(text).lower().split())
        if CANNON_PROMPT_WORD in words:
            result.notes.append(f"at the red cannon after {how}, "
                                f"{self._cannon_template_said()}, panel {words!r}")
            return True
        result.notes.append(f"cannon: after {how} the "
                            f"{self._cannon_template_said()} but the panel "
                            f"says {words!r} — not the cannon")
        return False

    def _cannon_approach(self, result: RouteResult) -> None:
        """Natro's nm_gotoCannon as its field paths run it: one hop, then hold
        right until the prompt shows, then make sure the hold did not carry
        us past it. See CANNON_HOLD_SECONDS.

        The template ends the hold (`_cannon_seen`); one panel read standing
        still must then name the cannon (`_cannon_confirmed`). Refuses without
        `panel_text`: an approach that cannot read the prompt would press E
        somewhere and call it the cannon.
        """
        if self.panel_text is None:
            result.ok = False
            result.reason = ("the cannon approach needs a panel reader "
                             "(RouteRunner.panel_text) to see 'Fire the Red Cannon'")
            return
        self._cannon_best = self._cannon_score = None
        self._cannon_snapped = False
        self._cannon_unscored = 0
        # THE HOP, ONCE.
        try:
            self.vin.press("space")
            self.vin.press("d")
            time.sleep(CANNON_HOP_JUMP_S)
            self.vin.release("space")
            time.sleep(self._hold_seconds(CANNON_HOP_RIGHT_TILES * TILE_STUDS))
            self.vin.press("w")
            time.sleep(self._hold_seconds(CANNON_HOP_FWD_TILES * TILE_STUDS))
        finally:
            for key in ("w", "d", "space"):
                try:
                    self.vin.release(key)
                except Exception:
                    pass
        # A frame after the hop: attempt 250 (2026-09-22 22:37) ended pressed
        # against a green wall on sand, with nothing to say where the hops had
        # gone. See RouteRunner.snapshot.
        self._snap("cannon-hop01")
        speed = max(1.0, self.walkspeed * self._speed_factor())
        # HOLD RIGHT UNTIL THE PROMPT SHOWS.
        found = self._cannon_hold(result)
        if found is not None and found.ok and found.already:
            # Up the moment the hop landed, so no hold ran and no overrun
            # check either: Natro's half second, then look again.
            time.sleep(CANNON_OVERRUN_SETTLE_S)
            if not self._cannon_seen():
                found.ok = False
                found.reason = ("the prompt showed as the hop landed and was "
                                "gone half a second later")
        # What the hold did, for the refusal if nothing after it works.
        held = "one hop and no hold (see the notes)"
        if found is not None and found.ok:
            self._snap("cannon-settled")
            # WHAT THE NEXT LIVE RUN MEASURES: the seconds of the hold are the
            # real distance from the hop's landing to the pad (DESIGN 8dl).
            how = ("1 hop, the prompt up as it landed" if found.already else
                   f"1 hop and {found.seen_after:.2f}s holding right "
                   f"(~{found.seen_after * speed:.0f} studs), "
                   f"{found.corrections} step(s) back")
            if self._cannon_confirmed(result, how):
                return
            if not result.ok:
                return
            held = (f"{how}; the template matched but the panel did not "
                    f"name the cannon")
        elif found is not None:
            self._snap("cannon-hold-end")
            held = found.reason or "the hold did not find the prompt"
            result.notes.append(
                f"cannon: {held}"
                + (f"; best template score {self._cannon_best:.2f} "
                   f"(it needs {RED_CANNON_THRESHOLD:.2f})"
                   if self._cannon_best is not None else "")
                + (f"; {self._cannon_unscored} look(s) had no template "
                   f"score, and counted as not there"
                   if self._cannon_unscored else ""))
        # THE HOLD MISSED. Before giving the trip up, walk and look -- the
        # same closed loop the hive pad and the quest givers get
        # (act/hiverow), left first -- but only from near the cannon: the
        # prompt was up as the hop landed, the hold saw it and the overrun
        # check lost it, or the template matched and the panel named
        # something else. A hold that RAN OUT never saw it, and after
        # ten seconds of right (~280 studs at 28 studs/s) a search's 5 s left
        # ends ~135 studs short of the landing and its 10 s right re-walks
        # the hold and goes further out (the offline drive ended it at
        # (435, -136) studs from the ramp corner after 30.7 s, the hold at
        # (295, 4) after 10.7). MEASURED: the run logs hold
        # that search at 11 distinct times ("held left 5s and right 10s",
        # runs 341-407), after the ten hops, and it found the cannon at none.
        # Natro does not search after its hold either -- it resets and goes
        # back to the ramp (:20425-20429) -- so this misses straight away and
        # the journey walks the trip (8de) 20 s sooner, from where the hold
        # ended.
        if (found is not None and not found.ok and not found.already
                and not found.direction):
            self._cannon_searched = ("no search: the hold ran out, and a "
                                     "search from there only re-walks it")
            result.notes.append(f"cannon: {self._cannon_searched}")
        elif self._cannon_search(result):
            self._snap("cannon-settled-search")
            if self._cannon_confirmed(result, f"1 hop and the search "
                                              f"({self._cannon_searched})"):
                return
            if not result.ok:
                return
        result.ok = False
        if not held.startswith(("1 hop", "one hop")):
            held = f"one hop, then {held}"
        result.reason = (f"{CANNON_MISS}: {held}"
                         + (f" (best template score {self._cannon_best:.2f})"
                            if self._cannon_best is not None else
                            " (no template score to stop on)"
                            if self._cannon_unscored else "")
                         + (f", and {self._cannon_searched}"
                            if self._cannon_searched else ""))

    def _cannon_search(self, result: RouteResult) -> bool:
        """Hold a key along the ramp until the cannon's prompt shows.

        True when it is showing now. The prompt is READ, never pressed, here:
        the press is the route's own `interact` step, which runs after this
        returns. Needs a `vin` that can hold a key down (`vin.held`); without
        one it says so and changes nothing.
        """
        self._cannon_searched = ""
        if not hasattr(self.vin, "held"):
            self._cannon_searched = ("no search was possible — this input "
                                     "cannot hold a key down")
            return False
        try:
            from . import hiverow
        except Exception:
            return False
        try:
            found = hiverow.find_along_row(
                self.vin, lambda: True,
                lambda _frame: self._cannon_seen(),
                walkspeed=max(1.0, self.walkspeed * self._speed_factor()),
                holds=(("a", "left", CANNON_SEARCH_SECONDS),
                       ("d", "right", CANNON_SEARCH_SECONDS * 2),
                       ("s", "back", CANNON_SEARCH_SECONDS)),
                poll=CANNON_POLL_S,
                sleep=time.sleep, clock=time.monotonic,
                on_note=self._cannon_note(result))
        except Exception as exc:
            self._cannon_searched = f"the search itself failed ({exc})"
            return False
        self._cannon_searched = found.describe().replace(
            "the pad", "the red cannon")
        result.notes.append(f"cannon: {self._cannon_searched}")
        return bool(found.ok)

    def _reset(self, result: RouteResult) -> None:
        """Respawn at the hive: Escape, R, Return.

        THE RETURN IS NOT PRESSED BLIND. Escape opens Roblox's in-game menu,
        and that menu carries **Log Out** and **Leave/Exit** as ordinary
        activatable tiles. If the menu is not showing the reset confirmation
        when Return lands -- because the menu opened on a different page, or
        did not open at all, or something else took focus -- the same keystroke
        logs the owner out of their account or quits the game.

        So this refuses unless a `confirm_menu` callback has looked at the
        screen and confirmed the reset dialog is up. Without one it does
        nothing and says why: a route that does not reset merely ends up
        somewhere unexpected, which the navigator can recover from. A route
        that logs the account out cannot be undone by anything here.
        """
        if self.confirm_menu is None:
            result.skipped.append("reset (no menu confirmation available)")
            return

        # THE STREAM IS TOLD FIRST (DESIGN 8ec): the menu opens on People,
        # which lists every player's display name and @username, the owner's
        # included, and the stream window covers its panel from this word.
        self._say_menu(True)
        try:
            self.vin.tap("escape")           # opens the in-game menu
            time.sleep(MENU_SETTLE)
            self.vin.tap("r")                # opens the respawn confirmation
            time.sleep(MENU_SETTLE)

            if not self._confirmed():
                self._leave_menu(result)
                result.ok = False
                result.reason = ("the respawn confirmation is not on screen — "
                                 "refusing to press Return, which on the menu "
                                 "underneath would hit Leave or Resume")
                return
            kind, sent = self._confirm_press(click=self.click_first)
            if not sent:
                # NOT SENT: the owner paused or took the controls between the
                # look and the press (brain/controls STALE_AFTER_A_WAIT), so the
                # confirmation it was checked against is not this screen. Back
                # out of whatever is up rather than believe it was confirmed.
                self._leave_menu(result)
                result.ok = False
                result.reason = (f"the respawn's {CONFIRM_NAMES[kind]} was held "
                                 f"back by the owner's Pause or Take Over — backed "
                                 f"out instead")
                return
        finally:
            self._say_menu(False)
        if kind == "click":
            result.notes.append(RESPAWN_CLICKED_FIRST)
        time.sleep(RESET_SETTLE)
        tried = [kind]
        for press in range(RESET_ENTER_RETRIES + 1):
            if not self._confirmed():
                self._learn_confirm(tried, result)
                return                       # the dialog went: the respawn is on
            self._snap("reset-stuck")
            if press == RESET_ENTER_RETRIES:
                break
            # THE OTHER WAY, NOT THE SAME AGAIN: no second Return has ever got
            # a stuck confirmation through, and the button is clicked where it
            # can be found (vision/screenstate.respawn_button_point).
            self._say_menu(True)
            try:
                kind, sent = self._confirm_press(click=tried[-1] != "click")
            finally:
                self._say_menu(False)
            if not sent:
                break
            result.notes.append(
                f"the respawn confirmation was still up {RESET_SETTLE:.1f}s after "
                f"{CONFIRM_NAMES[tried[-1]]} — trying {CONFIRM_NAMES[kind]}")
            tried.append(kind)
            time.sleep(RESET_SETTLE)
        self._leave_menu(result)
        result.ok = False
        said = (f"{len(tried)} Return(s)" if set(tried) == {"enter"}
                else " and ".join(CONFIRM_NAMES[k] for k in tried))
        result.reason = (f"the respawn confirmation stayed up after "
                         f"{said}, {RESET_SETTLE:.1f}s apart — backed "
                         f"out of the menu rather than believe it respawned")

    def _confirm_press(self, click: bool) -> tuple[str, bool]:
        """Confirm the respawn: its Respawn button clicked when `click` and
        the button can be found, Return otherwise. Which one it was, and
        whether it was sent (False: held back by the owner's controls)."""
        point = self._respawn_point() if click else None
        if point is not None:
            return "click", self.vin.click(*point) is not False
        return "enter", self.vin.tap("enter") is not False

    def _learn_confirm(self, tried: list[str], result: RouteResult) -> None:
        """The way that got the confirmation through is the one tried first
        next time (`click_first`); one that took first time changes nothing."""
        if len(tried) < 2:
            return
        if tried[-1] == "click":
            self.click_first = True
            result.notes.append(RESPAWN_CLICKED)
        else:
            self.click_first = False
            result.notes.append(RESPAWN_RETURNED)

    def _respawn_point(self) -> tuple[int, int] | None:
        """`respawn_button()`, None when unset or when the look failed."""
        if self.respawn_button is None:
            return None
        try:
            point = self.respawn_button()
        except Exception:
            return None
        return (int(point[0]), int(point[1])) if point else None

    def _between_legs(self) -> None:
        """`between_legs()`, which never stops a pattern."""
        try:
            self.between_legs()
        except Exception:
            pass

    def _say_menu(self, up: bool) -> None:
        """`on_menu(up)`, which never stops a reset. Before the menu opens it
        waits MENU_WARN_S, so the stream's cover is up before the menu is."""
        if self.on_menu is None:
            return
        try:
            self.on_menu(up)
        except Exception:
            return
        if up:
            time.sleep(MENU_WARN_S)

    def respawn(self) -> RouteResult:
        """The guarded reset as a standalone step, for coming home from an
        errand (act/respawn). Same keys, same refusal: nothing is pressed on
        the menu unless the respawn confirmation is on screen. The result's
        `ok` is False, with the reason, when it refused."""
        result = RouteResult("respawn")
        self._reset(result)
        if result.skipped and not result.ok:
            return result
        if result.skipped:
            result.ok, result.reason = False, result.skipped[-1]
        return result

    def _confirmed(self) -> bool:
        """`confirm_menu()`, with a look that failed counted as "not up": a
        capture that raised used to escape `_reset` with the dialog open."""
        try:
            return bool(self.confirm_menu())
        except Exception:
            return False

    def _leave_menu(self, result: RouteResult | None = None) -> None:
        """Back out to the world, verifying rather than assuming.

        MEASURED: Escape from the respawn confirmation does NOT return to the
        game -- it goes back to the in-game menu, which is the screen carrying
        **Leave** (DESIGN 8a: "the dark overlay is still present after one
        Escape"). So one Escape leaves the bot sitting on the dangerous
        screen. This presses Escape until the confirmation is gone and then
        for the menu, and never presses anything else.

        THE MENU ESCAPE IS ASKED FOR, NOT ASSUMED. It used to stop as soon as
        the confirmation was gone, which is ON the menu. Now `in_world` is
        asked, and only a positive "the HUD is not there" earns another
        Escape, twice at most -- so a false "not there" that opens the menu
        is closed again by the second. NOT MEASURED: no saved frame shows the
        menu, so whether hud_present reads False on it is unknown; each Escape
        is noted and the frame after it kept (`snapshot`), for the next run.
        """
        for _ in range(3):
            self.vin.tap("escape")
            time.sleep(MENU_SETTLE)
            if not self._confirmed():
                break
        if self.in_world is None:
            return
        for extra in range(1, MENU_EXTRA_ESCAPES + 1):
            try:
                back = self.in_world()
            except Exception:
                back = None            # could not look: press nothing
            if back is not False:
                if result is not None and extra > 1:
                    result.notes.append(f"left the menu: {extra - 1} more "
                                        f"Escape(s), the HUD is back")
                return
            self.vin.tap("escape")
            time.sleep(MENU_SETTLE)
            self._snap(f"leave-menu-escape{extra}")
            if result is not None:
                result.notes.append(f"left the menu: the HUD was not on screen "
                                    f"after the confirmation closed, Escape {extra}")

    # ---- multi-leg --------------------------------------------------------
    def travel(self, start: str, end: str) -> RouteResult:
        """Walk a routed path, leg by leg."""
        route = self.router.route(start, end)
        if route is None:
            return RouteResult(f"{start}->{end}", ok=False,
                               reason=f"no known way from {start} to {end}")
        combined = RouteResult(f"{start}->{end}")
        for leg in route.legs:
            self.run(leg.name, result=combined)
            if not combined.ok:
                break
        return combined
