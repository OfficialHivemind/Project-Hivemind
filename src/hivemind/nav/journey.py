"""Going somewhere and KNOWING whether you got there.

Every recorded route in this project is a list of timed key holds. A timed hold
can report exactly one thing: that the timer ran out. `RouteResult.ok` has
always meant "no step raised", and `brain/farm._leg` turned that straight into
"arrived". On 2026-09-21 that chain ran a route to the Pine Tree, pressed E to
board a cannon the character was not standing at, waited eight seconds for a
flight that did not happen, and handed the hive pads to the gatherer as if
they were a field. The owner watched it: "which wont help if its in the wrong
area to begin with".

This module is what sits between a route and a claim of arrival. It does four
things a bare route runner cannot, and each one is here because its absence
has been watched costing a trip:

  1. SQUARE UP FIRST. Recorded routes assume spawn heading and shift lock off.
     The camera gets turned by the hive sweep, the box search and every TURN
     recovery, and nothing turned it back -- so routes ran 45 or 180 degrees
     wrong. `Bearings` counts the taps; this undoes them before a route runs.

  2. NEVER PRESS E AT A BLANK PANEL. `interact` is the key that boards
     cannons, opens shops and starts NPC dialogues. The rest of this project
     already refuses to press it at a screen it cannot read (act/errands,
     act/hive, act/quests); the route runner did not. Now a route that reaches
     an `interact` step reads the panel first, and if the panel does not name
     a landmark the route is REFUSED with a reason that says so -- which is a
     far better outcome than a silent eight-second wait at the wrong place.

  3. VERIFY BEFORE HANDING OVER. After the routes run it looks at the panel.
     Still at the hive means the travel failed, whatever the routes said. A
     field cannot be positively confirmed from the panel -- fields have no
     prompt -- so for a field the claim is the honest one: "left the hive,
     arrival unconfirmed", and the gatherer's first pollen rise or reward-feed
     line is what confirms it.

  4. RETRY ONCE, FROM A SQUARED-UP POSITION. Then stop and say so. Not jump,
     not turn -- those fix a character stuck on terrain, and a character on
     the wrong side of the map is not stuck.

`Outcome.ok` means "not demonstrably in the wrong place". `Outcome.confirmed`
means "the game said we are there". The two are kept apart because the whole
failure this module exists to stop was treating the first as the second.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

import math

from ..act.routes import (CAMERA_KEYS, CANNON_MISS, HELD_BACK, SLOT_ROUND_UP,
                         UNWALKED)

# Let the panel settle after the last step before believing what it says.
SETTLE_SECONDS = 0.8

# Camera taps per direction word, as the route steps spell them.
TAP_DELTA = {"right": +1, "left": -1}

# WHEN A ROUTE'S FIRST WALK SPENDS THIS MUCH OF ITSELF GOING NOWHERE, THE
# CHARACTER WAS FACING A WALL BEFORE IT STARTED.
#
# MEASURED 2026-09-21, straight off a freshly claimed hive pad:
#
#     from_hive_to_rose_field: w for 64 studs: pushed against something
#       for 1.9 of 2.3s        -- 83% of the leg
#     from_hive_to_rose_field: d for 212 studs: pushed against something
#       for 5.1 of 7.6s
#
# Every recorded route out of the hive opens by walking forward, and the hive
# claim arrives at its pad by walking forward into it -- so the character
# finishes the claim facing the honeycomb wall, which is where "forward" now
# points. The frames show it:
# `var/incidents/233113-refused/000_t+00.0s.jpg` and
# `var/incidents/234206-refused/149_t+12.7s.jpg`, the second of which is the
# character wedged in the slot between two hive bases.
#
# HALF A TURN IS THE RESPONSE, and it is a response to a measurement
# rather than a belief about the map: the bot does not know which way the
# wall is, only that forward did not work, and the opposite of a wall is open
# ground. If it is wrong the retry measures that too and nothing is lost but
# one attempt. 0.5 is the trigger because half a leg spent standing still
# cannot be the "leaning on a wall to square up" that some recorded routes do
# on purpose -- those lean for a fraction of a short leg, not for most of the
# first one.
BLOCKED_TO_TURN_AROUND = 0.5
HALF_TURN_TAPS = 4

# SEARCHING FOR THE HEADING THE ROUTES WERE RECORDED AT.
#
# `square_up` restores "spawn heading", and every recorded route assumes it.
# MEASURED 2026-09-21/22, that reference is wrong on this account: the routes
# leave the character wedged between two hive bases
# (`var/incidents/234206-refused/149_t+12.7s.jpg`) and 31-83% of every walk is
# spent against a wall, in both directions. The most likely cause needs one
# fact from the owner -- which hive slot he owns -- but the heading is the part
# the bot can settle by itself, because ARRIVAL IS SELF-CONFIRMING: the game's
# own panel says when the cannon has been reached.
#
# So a failed attempt rotates the reference by a quarter turn and tries again.
# Three attempts sample 0, 90 and 180 degrees; the offset that arrives is kept
# for the rest of the session, so one success fixes every later trip. After a
# whole turn without arriving it resets to 0 and says so, because by
# then the heading is not what is wrong.
#
# A quarter turn rather than an eighth because the routes' own camera steps
# are 45 degrees each and a route that is 45 degrees out still walks roughly
# the right way; being 90 or 180 out is what puts the character in a wall.
QUARTER_TURN_TAPS = 2
TAPS_PER_FULL_TURN = 8

# AND WHICH HIVE SLOT IT OWNS, which is the other half of the same problem and
# is now a number in a formula rather than a guess.
#
# MEASURED 2026-09-22 01:33: all four starting headings were tried on a live
# account and none of them arrived, so the bot ruled the heading out itself.
# What was left was the starting POSITION -- and Natro Macro's paths say
# exactly what that is. Every one of them opens with `nm_gotoRamp()`:
#
#     nm_Walk(5, FwdKey)
#     nm_Walk(9.2*HiveSlot - 4, RightKey)
#
# So the pad is 9.2 tiles apart per slot, 36.8 studs, and the whole difference
# between slots is one integer. `act.routes._hive_offset` turns that integer
# into the sideways walk and REFUSES when it is unset, because a guessed
# sideways walk is worse than none.
#
# The owner can settle it in ten seconds (the Movement panel's hive-slot box).
# Until he does, the bot searches the six of them by ARRIVING, which is the
# only evidence it can get on its own.
HIVE_SLOTS = 6
# How many ramp readings are averaged before the slot is trusted (`go`).
SLOT_READS_TO_TRUST = 2

# A POSE THAT HAS WORKED IS NOT THROWN AWAY FOR ONE BAD WALK (DESIGN 8dw).
# MEASURED 2026-09-26: attempts 425-437 all left the hive from spawn heading
# at slot 3; one walk out in attempt 438 failed, the search moved to 90 degrees,
# and every attempt after it (438-442) started 90, 180 or 270 degrees off and
# failed at once -- the cannon approach saw nothing (best template 0.23) and
# natro_out_strawberry's leg 3 read 0% path -- each failure moving it again.
# So once the current pose has arrived POSE_TRUSTED_WINS times, it has to fail
# POSE_FAILS_TO_DOUBT walks in a row before the search moves; an untried or
# new pose moves on the first failure, as before.
POSE_TRUSTED_WINS = 3
POSE_FAILS_TO_DOUBT = 3
# A PRESS THE PANEL READER COULD NOT CHECK SAYS NOTHING ABOUT THE POSE.
# MEASURED 2026-09-26, attempts 461-464: the vision model had no room to load
# beside the owner's programs, and three walks from the spawn-heading pose --
# 55 arrivals on record -- ended "the route wanted to press E here and could
# not read the panel". Counted as the pose's failures, they moved the search
# to 90° (19:06), whose first walk "left the hive, arrival unconfirmed" and was
# kept as the correction, so every later flight hopped from the wrong heading
# (best template score 0.25-0.36). A blind read is exempt, as a mob's cut is.
PANEL_UNREAD = "could not read the panel"


@dataclass
class Homeward:
    """Which recorded route home to walk, and why."""
    routes: list[str]
    why: str
    # True when the aim's route is being walked from somewhere it does not
    # start -- the caller should expect it to miss and have the closer ready.
    doubtful: bool = False


def slot_from(settings) -> int:
    """Which hive pad the owner says is theirs, or 0 for "work it out".

    IN THE LIBRARY, NOT IN THE SCRIPT, AND THAT IS THE POINT. This setting
    was read in `scripts/run_farm.py` and nowhere else, so by this project's
    own standard -- the one written on `brain.decide.from_settings` -- it was
    wired into one script rather than into the system, and
    `tests/unit/test_settings.py` scans `src/` for exactly that reason. It
    was still sitting in `world/settings.NOT_WIRED` under a note calling it
    "the biggest blocker in the project", which had been true and was not any
    more: the live logs say "running this as hive slot 3".

    WHY THE NUMBER MATTERS. Every Natro path opens with `nm_gotoRamp()`, a
    sideways walk of `9.2 * HiveSlot - 4` tiles, so this one integer is the
    whole difference between arriving and being 36.8 studs out per slot. The
    claimer can find a PAD but cannot name WHICH -- walking the row gives no
    slot number -- so the owner's word is the only fact available. Measured
    when it was missing: 31% to 83% of every walk spent against a wall, in
    both directions (DESIGN 8k).

    0 means "not set", which is not slot 0: the pose search then hunts for it
    and `Journey` feels for the ramp wall instead of walking the formula.
    """
    # Broad on purpose, as the sibling helpers are (`farm.gather_tilt_from`,
    # `routes.walkspeed_from`): an optional setting that cannot be read must
    # never be the thing that stops the loop earning. 0 is the honest answer
    # to "I could not find out", and 0 makes the search do the work.
    try:
        slot = int(settings.int("move.hive_slot") or 0)
    except Exception:
        return 0
    return slot if 0 < slot <= HIVE_SLOTS else 0


# R10 (docs/pending/brain-backlog.md): RELOCALISE BY THE FEED WHERE IT STILL
# KNOWS -- AT THE WALK HOME'S START -- NOT AFTER THE CHARACTER IS LOST. When a
# gather was credited a neighbour last but the aim this trip too, run_farm's
# border rule (2026-10-07, run-743 on) walks the AIM's route home; this switch
# walks the route of the field the feed named LAST, `route_home`'s own rule.
#
# MEASURED 2026-10-12 over the run logs (scratchpad relocal_border.py): such
# trips landed 13 of 55 on the aim's route (24%) and 29 of 46 on the
# last-credited field's (63%) -- 12 of 14 in the same runs, 743-898, so not a
# period effect (trips that stayed in their aim: 96% before 743, 88% after).
# By pair: Mushroom <- Sunflower 0/7 against 2/2, Mountain Top <- Pineapple
# 0/6 against 2/2, Bamboo <- Mushroom or Sunflower 0/6 against 2/2, Rose <-
# Pumpkin 7/12 against 4/4. And they are the W3 misses: 28 of the 50 "turned a
# full circle" after a walked route home since run-743, ended by 10 rejoins,
# 10 small-bag respawns, 4 Micro-Converters and 3 Whirligigs.
#
# WHY NOT AFTER IT IS LOST, as R10 was first written. At the full circle
# nothing knows where the character is: over the 34 misses since run-800 with
# look-round frames (var/homing) fieldsense named a place 90%-sure in 6, the
# flower bed was under 10% in most (walls and corners, off any field), and a
# landmark class (red cannon, black bear, ticket shop, shop counter) topped 13
# -- the spawn area, hive occluded. The saved route frames (19,116, attempts
# 820-899, fieldsense's descriptor) put 418 held-out home-route frames on the
# right route 93% but on the right leg (+-1) only 49%, too coarse to resume a
# route; and a recorded walk from a place the PANEL named (natro_back_*)
# landed 0 of 8 in every log. A learned descriptor is R8's job.
#
# "on" (coordinator, 2026-10-12): 13 of 55 vs 29 of 46 is already a wide
# gap, and an odd-hours arm would tangle with HOME_UNSTICK / HOME_ALIGN's
# even-hours A/B (each arm would differ in two things). On in every hour it
# leaves theirs clean. "ab" (odd hours) / "off" are still there.
HOME_FROM_FIX = "on"


def home_from_fix(hour: int | None = None) -> bool:
    """Is R10's switch on (`hour` for tests; now by default)? See HOME_FROM_FIX."""
    if HOME_FROM_FIX == "ab":
        return (time.localtime().tm_hour if hour is None else hour) % 2 == 1
    return HOME_FROM_FIX == "on"


def route_home(aimed: str | None, credited: str | None,
               planned: Sequence[str], recorded) -> Homeward:
    """Walk home from where the game says it IS, not from where it aimed.

    The route home is chosen at the same moment as the route out, from the
    AIM -- and the aim is regularly not where the trip ended up, because a
    field has no landmark prompt and "left the hive" is the most the walk out
    can honestly claim (DESIGN 8b, 8k).

    MEASURED 2026-09-22 04:48, and it cost a full backpack: the trip aimed at
    Sunflower, farmed DANDELION for 1,209 s over 91 passes, filled the bag to
    965,753 pollen, then walked home along `natro_home_sunflower` from a field
    that was not Sunflower. It arrived at the TICKET SHOP, the box search
    could not close the gap, the convert correctly refused to press E with no
    hive in front of it, and the trip banked +227 honey. (The bag was not
    lost -- the rejoin preserved it and the next cycle converted 1,019,114
    honey -- but a whole trip's walk home was spent finding that out.)

    The reward feed names the field on every pickup and is the one position
    signal measured to be reliable, so when it disagrees with the aim, IT
    wins. Only if there is a RECORDED way home from there, though: a guessed
    walk is worse than the wrong recorded one, because the wrong recorded one
    at least ends somewhere known.

    `recorded(field)` returns the route home from that field, or None.
    """
    planned = list(planned)
    if not credited:
        return Homeward(planned, "the feed never named a field on this trip")
    if credited == aimed:
        return Homeward(planned, f"it farmed {credited}, which is what it "
                                 f"aimed at")
    instead = recorded(credited)
    if instead:
        return Homeward(list(instead),
                        f"walking home from {credited}, not "
                        f"{aimed or 'the aim'} — the feed named the field it "
                        f"actually farmed")
    return Homeward(planned,
                    f"it farmed {credited} but aimed at "
                    f"{aimed or 'nowhere recorded'}, and there is no recorded "
                    f"route home from {credited} — walking the aim's route, "
                    f"which may not start here",
                    doubtful=True)


def errand_home(stood, routes_run: int, died_at: float, recorded):
    """(field, Homeward) for the walk home from where an errand left the
    character standing, or None when that no longer holds.

    `stood` is run_farm's stamp (field, routes run, monotonic time) from the
    moment an errand stood at a field's gather spot (the planter errand's
    `stand_where_the_gather_stands`). It holds while no route has run since
    and no death came after it; then the field's own recorded walk home
    (`recorded(field)`) starts where the character is, as it does for a trip
    that gathered there. MEASURED 2026-10-14 00:07-00:10 (var/night/run-984.log):
    a Paper Planter placed in Bamboo, the errand's respawn refused for a
    647,939 bag, and the guard, taking the character for "in the hive area",
    found no row (0 px of wall), homed by sight into a field's wall and
    respawned anyway -- 554,477 pollen and about 2 minutes, standing where
    natro_home_bamboo begins.
    """
    if not stood:
        return None
    name, routes, at = stood
    if routes != routes_run or died_at >= at:
        return None
    legs = list(recorded(name) or ())
    if not legs:
        return None
    return name, Homeward(legs, (
        f"the errand stood at {name.replace('_', ' ')}'s gather spot and no "
        f"route or death has moved the character since — walking its own "
        f"recorded route home, as a trip that gathered there does"))


class Refused(RuntimeError):
    """A route step was refused. The message is the reason, for the log."""


# How many of a route's per-leg notes a journey line quotes.
NOTES_SHOWN = 8


@dataclass
class Outcome:
    """What a journey established. `confirmed` is the only certain claim."""
    destination: str
    ok: bool = False
    confirmed: bool = False
    where: str = ""
    attempts: int = 0
    squared_taps: int = 0
    shift_reset: bool = False
    refused: str = ""
    reason: str = ""
    routes: list[str] = field(default_factory=list)
    # From the route results: seconds a held key moved nothing, and where.
    blocked_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)
    # Set when the journey had to walk back to the route's own starting point
    # before it could run. See `Journey.go_home`.
    went_home: bool = False
    # Set when the journey changed its starting heading before retrying.
    # See QUARTER_TURN_TAPS.
    turned_around: bool = False
    # The learned correction to "spawn heading" this attempt started from,
    # in camera taps of 45 degrees each, and the hive slot it ran as.
    heading_offset: int = 0
    hive_slot: int = 0
    # The landmark the panel named where a FIELD was expected, if any. Not a
    # failure -- see the note in `go` -- but evidence the pose is wrong.
    landed_at: str = ""
    # Set when a missed cannon approach handed the rest of the trip to the
    # field's walking route. See `go` and act/routes.CANNON_MISS.
    fell_back: bool = False

    def describe(self) -> str:
        head = f"to {self.destination.replace('_', ' ')}: "
        # EVERY LEG'S NOTE, not the first two. MEASURED 2026-09-24: the
        # Strawberry walks home that failed were decided at their fifth and
        # sixth walks, and the log showed only the two leans before them, so
        # the leg that went wrong had to be found from the frames.
        wall = (f" (pushed against something for {self.blocked_seconds:.0f}s: "
                + "; ".join(self.notes[:NOTES_SHOWN]) + ")") if self.notes else ""
        if self.confirmed:
            return head + f"arrived — {self.where}{wall}"
        if self.ok:
            return head + f"left the hive, arrival unconfirmed — {self.where}{wall}"
        return head + f"did not get there — {self.reason}{wall}"


class Journey:
    """Travel that consults the compass and checks its own work.

    `runner` is an `act.routes.RouteRunner`. `bearings` is a
    `world.bearings.Bearings`. `read_panel(frame=None)` returns the panel text,
    "" for no panel, None if it could not look. `frames()` returns a frame.
    """

    def __init__(self, runner, bearings, read_panel, frames, *,
                 emit: Callable | None = None, sleep=time.sleep,
                 stopped: Callable[[], bool] | None = None,
                 supervisor=None, retries: int = 1,
                 settle: float = SETTLE_SECONDS, on_refuse=None,
                 seek=None, target_in_view=None, go_home=None,
                 heading_offset: int = 0, heading_tried=(),
                 hive_slot: int = 0, poses_tried=(),
                 on_heading=None, slot_trusted: bool = False,
                 on_slot_learned=None, pose_record=None, on_pose_record=None):
        self.runner = runner
        self.bearings = bearings
        self.read_panel = read_panel
        self.frames = frames
        self.emit = emit
        self.sleep = sleep
        self.stopped = stopped or (lambda: False)
        self.supervisor = supervisor
        # `sight(destination) -> bool`: which field the end of a walk LOOKS
        # like (vision/fieldsense through whereami's `looks_like`), asked
        # before the supervisor's vision model; True when it answered, and
        # then the model is not asked (DESIGN 8dz). Set by the caller; None
        # asks the model as before.
        self.sight = None
        self.retries = max(0, int(retries))
        self.settle = settle
        self.refusals = 0
        # `on_refuse(reason)` is called the moment a press is refused, while
        # the screen still shows WHY -- the runner wires it to the incident
        # recorder so a refusal leaves 150 frames behind it. The first live
        # refusal (2026-09-21 19:09) left only a sentence, and a sentence
        # cannot say whether the character overshot the cannon or never
        # reached it.
        self.on_refuse = on_refuse
        # `seek(place) -> act.seek.Seek` closes the last few studs of a route
        # by walking a small box and reading the panel until it names `place`.
        # With it, a route only has to land CLOSE; without it, a route that
        # lands a stud short of the prompt is refused as if it had gone
        # nowhere. It is a callable rather than the module so the runner can
        # bind the input, the capture and the panel reader once.
        self.seek = seek
        # `target_in_view()` is cheap -- "is the top-centre panel showing" --
        # and is armed as the runner's `arrive` while routes that end in a
        # press are running. The full panel READ still happens at the press.
        self.target_in_view = target_in_view
        # `go_home()` walks back to the hive and returns something with `.ok`.
        # It is here because EVERY RECORDED ROUTE OUT OF THE HIVE ASSUMES IT
        # STARTS ON A HIVE PAD, and nothing checked that.
        #
        # MEASURED live 2026-09-21 23:31:46, the trip to the Rose Field:
        #
        #     from_hive_to_rose_field: w for 64 studs: pushed against
        #       something for 1.9 of 2.3s
        #     from_hive_to_rose_field: d for 212 studs: pushed against
        #       something for 5.1 of 7.6s
        #
        # Seven of the first ten seconds of walking moved the character
        # nowhere, because the previous cycle's box search had left it beside
        # the red cannon rather than on its pad, and from there the route's
        # first two legs walk straight into the cannon's own body. The frames
        # show it: `var/incidents/233113-refused/000_t+00.0s.jpg` is the
        # character on sand at the foot of the cannon at the moment the route
        # begins.
        #
        # The owner had already described the shape of this exactly: "the bot
        # still has no idea where its going and when it trys to figure it out
        # it only spirals deeper into madness and gets even more lost". Each
        # failed trip leaves the character further from the one place every
        # route is written from, so the next trip fails worse.
        self.go_home = go_home
        # How many taps to add after squaring up, learned by arriving. See
        # QUARTER_TURN_TAPS. Zero until a trip fails.
        #
        # IT HAS TO OUTLIVE THE PROCESS. A failed cycle ends in a rejoin, which
        # is a whole new run, and the search samples one heading per cycle --
        # so without somewhere to keep the answer it starts at zero for ever
        # and can never converge. MEASURED 2026-09-22 00:49: the search moved
        # 0° -> 90°, the cycle ended, the process restarted, and the next run
        # began at 0° again. `on_heading(offset)` is how the caller saves it.
        self.heading_offset = int(heading_offset) % TAPS_PER_FULL_TURN
        # WHICH offsets have been tried, not HOW MANY taps have been spent.
        #
        # Counting taps let the search skip one: starting at 0, a blocked
        # first walk adds 4, an unblocked one adds 2, and 0 -> 4 -> 6 -> reset
        # never tries 2 at all. There are only four quarters; each gets one
        # turn.
        #
        # IT PERSISTS TOO. Only the offset used to be written down, so after
        # a rejoin the search could re-offer a quarter it already knew was
        # bad, and the honest "all four have been tried and none arrived"
        # verdict could never be reached at all.
        self.heading_tried: set[int] = {int(t) % TAPS_PER_FULL_TURN
                                        for t in heading_tried or ()}
        # WHICH HIVE SLOT to tell the route runner this account owns. 0 means
        # unknown, and then every Natro path skips its sideways walk and says
        # so rather than walking a guess. See HIVE_SLOTS.
        self.hive_slot = max(0, min(HIVE_SLOTS, int(hive_slot)))
        self.poses_tried: set[tuple[int, int]] = {
            (int(h) % TAPS_PER_FULL_TURN, max(0, min(HIVE_SLOTS, int(p))))
            for h, p in (poses_tried or ())}
        # WINS AND FAILURES OF THE POSE NOW IN USE, kept across attempts by
        # the caller (`on_pose_record`); see POSE_TRUSTED_WINS.
        record = dict(pose_record or {})
        here = (int(self.heading_offset), int(self.hive_slot))
        if tuple(record.get("pose") or ()) != here:
            record = {"pose": list(here), "wins": 0, "fails_in_row": 0}
        self.pose_record = record
        self.on_pose_record = on_pose_record
        self.on_heading = on_heading
        # IS THE SLOT A FACT OR A GUESS? The pose search hands the runner a
        # slot number so Natro's `hive_offset` can be walked -- but a slot the
        # search merely "last arrived with" is not a measurement, and walking
        # its sideways formula from the wrong pad is how every route out of
        # the hive began from the wrong place (DESIGN 8k). Untrusted, the
        # runner is given NO slot, so `_hive_offset` feels for the ramp wall
        # instead and reads the slot off the distance it walked. Once that has
        # happened -- or the owner configured it -- the slot is trusted and
        # the pose search stops moving it. `on_slot_learned(slot)` lets the
        # caller write the measurement down.
        self.slot_trusted = bool(slot_trusted)
        if self.slot_trusted and self.hive_slot:
            self.heading_offset = 0     # see `_poses`: a trusted slot starts at spawn heading
        self._slot_reads: list[float] = []   # ramp readings, newest last
        self.on_slot_learned = on_slot_learned
        # Where a list of routes begins, asked of the route graph. Wired from
        # the runner by default so callers do not have to know.
        self.starts_at: Callable | None = getattr(runner, "route_start", None)
        self._current_routes: list[str] = []
        self.seeks = 0
        self._blocked: float = 0.0
        self._notes: list[str] = []

    # ---- the compass --------------------------------------------------------
    def square_up(self) -> tuple[int, bool]:
        """Bring the camera back to spawn heading and shift lock to off.

        Returns (taps used, shift lock was reset). Taps go the short way
        round: three taps left rather than five taps right.
        """
        taps = self.bearings.taps_to_square()
        if taps:
            key = CAMERA_KEYS["right"] if taps > 0 else CAMERA_KEYS["left"]
            for _ in range(abs(taps)):
                self.runner.vin.tap(key)
                self.sleep(0.25)
            self.bearings.turned(taps)
            self._say(f"squared up: {abs(taps)} tap(s) "
                      f"{'right' if taps > 0 else 'left'} back to spawn heading")
        reset = False
        if self.bearings.shift_lock is True:
            self.runner.vin.tap("shift")
            self.sleep(0.3)
            self.bearings.toggled_shift_lock()
            reset = True
            self._say("shift lock was on from an earlier route — turned it off")
        return abs(taps), reset

    # ---- the guard ----------------------------------------------------------
    def guard(self, op: str, step: dict) -> None:
        """Runs before every route step. Counts turns; refuses blind presses."""
        if self.stopped():
            raise Refused("stop requested mid-route")
        if op == "key_down" and "e" in str(step.get("keys", "")):
            # Natro boards the cannon with E held down for 100 ms rather than
            # tapped -- a press by another name, and guarded the same way: the
            # panel must name the place this press is for.
            op = "interact"
        if op == "camera":
            self.bearings.turned(TAP_DELTA.get(str(step.get("direction", "")), 0))
        elif op == "shift_lock":
            self.bearings.toggled_shift_lock()
        elif op == "interact":
            text = self._look()
            mark = self.bearings.saw_panel(text)
            expected = self._expected_landmark()
            # A PANEL IS NOT ENOUGH; IT HAS TO BE THE RIGHT PANEL.
            #
            # This used to accept ANY recognised landmark, and that is how a
            # trip to Pumpkin pressed E on the hive pad: arrival-by-sight had
            # fired on the pad's own "Make Honey" prompt, every approach walk
            # after it was skipped as "already arrived", and the guard looked
            # at "Make Honey", matched it, and pressed. Pressing E at the hive
            # is converting, which is another module's decision entirely, and
            # the route then ran its post-cannon legs from the hive and ended
            # up at Black Bear. The owner watched it happen.
            #
            # `expected` comes from the route NAMES, so when no route names a
            # landmark there is nothing to check against and any landmark is
            # still accepted -- the honest fallback, and unchanged.
            def _wrong(m) -> bool:
                return bool(expected) and m is not None and m.place != expected

            if (mark is None or _wrong(mark)) and self.seek is not None and expected:
                # NOT THERE YET -- BUT MAYBE NEARLY. Before refusing, look
                # for the landmark this route is heading for, a few steps in
                # each direction. The routes were recorded from one exact
                # start pose and land a little off from any other; the panel
                # is what says when "a little off" has been closed.
                self.seeks += 1
                here = ("no prompt" if mark is None else
                        f"the {mark.place.replace('_', ' ')}'s prompt")
                self._say(f"{here} where the route expected the "
                          f"{expected.replace('_', ' ')} — searching nearby")
                found = self.seek(expected)
                self.bearings.turned(int(getattr(found, "taps", 0) or 0))
                self.bearings.moved("seek")
                self._say(found.describe())
                if getattr(found, "found", False):
                    text = getattr(found, "prompt", "")
                    mark = self.bearings.saw_panel(text)
            if mark is None or _wrong(mark):
                self.refusals += 1
                if mark is not None:
                    shown = (f"the panel says we are at the "
                             f"{mark.place.replace('_', ' ')}, not the "
                             f"{expected.replace('_', ' ')}")
                else:
                    shown = ("no panel" if text is not None and not text.strip()
                             else PANEL_UNREAD if text is None
                             else f"the panel read {text.strip()[:40]!r}")
                if self.on_refuse is not None:
                    try:
                        self.on_refuse(f"refused E: {shown}")
                    except Exception:
                        pass
                raise Refused(
                    f"the route wanted to press E here and {shown} — we are "
                    f"not at the place this press is for, so nothing was "
                    f"pressed and the route was abandoned")
            self._say(f"pressing E {mark.describe()}")

    # ---- travel -------------------------------------------------------------
    def go(self, destination: str, routes, fallback=None) -> Outcome:
        """Run `routes` in order to reach `destination`, then check.

        `fallback` is the field's walking route, given when `routes` is a
        cannon flight. A failure naming `CANNON_MISS` hands every remaining
        attempt to it instead of flying again: MEASURED, the flight's
        approach missed on all 6 tries since attempt 320, while the walk to
        the same field left the hive on every one of its 10 trips in runs
        324-339. See DESIGN 8de.
        """
        out = Outcome(destination=destination, routes=list(routes))
        landmark = destination in self.bearings.table.places()

        for attempt in range(1, self.retries + 2):
            out.attempts = attempt
            if self.stopped():
                out.reason = "stop requested"
                return out
            # A ROUTE ONLY WORKS FROM THE PLACE IT WAS RECORDED FROM. Checked
            # before anything is pressed, because squaring the camera up from
            # the wrong POSITION just points a wrong walk in a tidier
            # direction. See `self.go_home`.
            if self._start_is_wrong(routes):
                self._say("this route starts at the hive and we are not "
                          "there — going back first, because walking it from "
                          "anywhere else is how the last trip spent seven "
                          "seconds pressed against the cannon")
                home = None
                try:
                    home = self.go_home()
                except Exception as exc:
                    self._say(f"could not get back to the hive: {exc}")
                out.went_home = True
                if not bool(getattr(home, "ok", False)):
                    out.reason = ("this route starts at the hive, we are not "
                                  "at the hive, and walking back did not get "
                                  "there either — refusing to run it from the "
                                  "wrong place")
                    self._say(out.describe())
                    if attempt > self.retries:
                        break
                    continue
            taps, reset = self.square_up()
            out.squared_taps += taps
            out.shift_reset = out.shift_reset or reset
            out.heading_offset = self.heading_offset
            out.hive_slot = self.hive_slot
            if self.heading_offset:
                # THE LEARNED CORRECTION to "spawn heading". See
                # QUARTER_TURN_TAPS for why this exists and how it is found.
                for _ in range(self.heading_offset % TAPS_PER_FULL_TURN):
                    self.runner.vin.tap(CAMERA_KEYS["right"])
                    self.sleep(0.25)
                self.bearings.turned(self.heading_offset)
                # A CANDIDATE AND A KNOWN-GOOD ANSWER ARE DIFFERENT THINGS.
                # This said "that is the correction the last arrival was found
                # at" whether or not anything had ever arrived, which is a
                # claim the search has not earned until it succeeds once.
                settled = not self.poses_tried
                self._say(f"starting {self.heading_offset * 45}° right of "
                          + ("spawn heading — the correction that last "
                             "arrived" if settled else
                             f"spawn heading — still searching; "
                             f"{len(self.poses_tried)} of "
                             f"{len(self._poses())} starting poses ruled out "
                             f"so far"))
            # TELL THE RUNNER WHICH SLOT TO WALK TO. Natro's paths open with
            # a sideways walk of `9.2*HiveSlot - 4` tiles, so this one integer
            # is the whole difference between arriving and being 36.8 studs
            # out per slot. See HIVE_SLOTS.
            if self.hive_slot and self.slot_trusted:
                self.runner.hive_slot = self.hive_slot
                self._say(f"running this as hive slot {self.hive_slot}"
                          + ("" if self.poses_tried else
                             " — the slot that last arrived"))
            elif self.hive_slot:
                # A CANDIDATE, NOT A FACT. Named, so the log still says which
                # pose the search is on -- but not handed to the runner. The
                # runner is given no slot, so `_hive_offset` feels for the
                # ramp wall and measures the slot itself (DESIGN 8w).
                self.runner.hive_slot = None
                self._say(f"the pose search is on hive slot {self.hive_slot}"
                          + ("" if self.poses_tried else
                             " — the slot that last arrived")
                          + " — a guess, so the runner will feel for the "
                            "ramp rather than walk its formula")

            failure = self._run_all(routes)
            moved_pose = False             # by `landed_wrong`, below
            out.blocked_seconds += self._blocked
            out.notes += self._notes
            self.bearings.moved(destination)
            self.sleep(self.settle)
            text = self._look()
            self.bearings.saw_panel(text)
            place = self.bearings.where()
            out.where = place.describe() if place else "nowhere I can confirm"
            self._consult_supervisor(f"finished travelling to {destination}",
                                     destination)

            if failure:
                out.refused = failure
                out.reason = failure
            elif landmark:
                out.confirmed = bool(self.bearings.at(destination))
                out.ok = out.confirmed
                if not out.ok:
                    out.reason = (f"the routes ran but the panel does not say "
                                  f"we are at the {destination} — {out.where}")
            else:
                at_hive = self.bearings.at("hive")
                # A FIELD HAS NO PROMPT, SO A PROMPT MEANS THIS IS NOT THE
                # FIELD WE AIMED AT -- BUT IT DOES NOT MEAN THE TRIP WAS
                # WASTED, AND THE DIFFERENCE IS MEASURED.
                #
                # This first aborted the trip, on the reasoning that gathering
                # at a shop counter earns nothing. The logs refuted it within
                # the hour: trips that finished "at the ticket shop (98% sure,
                # panel)" went on to earn 858, 801 and 985 honey, because the
                # gathering pattern walks off the landmark into the field
                # beside it. So the reasoning went and the observation stayed.
                #
                # What the prompt IS good for is the pose search. It is free
                # and always there, unlike the reward feed, which names the
                # field on every pickup but costs a vision-model call and had
                # credited "nothing" on the cycle where the answer was most
                # wanted. Landing on a named landmark says the sideways walk
                # to the owned pad was wrong; the trip carries on regardless.
                landed_at = self.bearings.where()
                elsewhere = (landed_at.name if landed_at is not None
                             and landed_at.name in self.bearings.table.places()
                             and landed_at.name != "hive" else "")
                out.landed_at = elsewhere
                if at_hive is True:
                    out.reason = ("the routes ran and we are STILL AT THE HIVE — "
                                  "the travel did nothing")
                else:
                    out.ok = True
                    if elsewhere:
                        out.reason = (
                            f"left the hive, and the panel says we are at the "
                            f"{elsewhere.replace('_', ' ')} — that is not the "
                            f"{destination}, so the walk to the owned pad was "
                            f"wrong. Gathering anyway: the pattern walks off a "
                            f"landmark into the field beside it, measured "
                            f"worth 800-1,000 honey a trip")
                        moved_pose = self.landed_wrong(destination, elsewhere)
                    elif at_hive is False:
                        out.reason = "left the hive; the field will confirm itself"
                    else:
                        out.reason = ("left the hive as far as anyone can tell; "
                                      "the field will confirm itself")

            self._say(out.describe())
            if (failure and fallback and CANNON_MISS in failure
                    and attempt <= self.retries):
                # THE FLIGHT MISSED; WALK THE REST OF THIS TRIP. Retrying the
                # same approach is what every trip did until now, and the
                # approach went 0 for 6 since attempt 320; the one retry that
                # got to run (run-323, 19:26:37, from the pad -- though 90
                # degrees off, DESIGN 8de) missed again at 19:27:12. The
                # field's walking route starts at the same pad and needs no
                # cannon, so the retry walks it; the route guard at the top
                # of the next attempt gets the character back onto the pad
                # first.
                #
                # NO POSE-SEARCH ADVANCE FOR THIS FAILURE. The hops missing
                # the cannon says nothing about the heading or the slot:
                # MEASURED, Strawberry's walking route left the hive from
                # this same pose 10 times out of 10 in runs 324-339. Moving
                # the pose here would spoil the walk it is about to run.
                routes = list(fallback)
                fallback = None
                out.routes = list(routes)
                out.fell_back = True
                self._say(f"the cannon approach missed — walking {routes[0]} "
                          f"for the rest of this trip")
                continue
            if out.ok and moved_pose:
                # LEFT THE HIVE, BUT ON A LANDMARK, and `landed_wrong` has
                # just moved the search to a pose nobody has run. That pose
                # did not "work" -- it has not been tried -- so it is not
                # kept as the correction and the tried set stays (audit
                # 2026-09-26, senses F3).
                break
            if out.ok and self.poses_tried and not out.confirmed:
                # A SEARCHED POSE IS KEPT ONLY ON A CONFIRMED ARRIVAL (see
                # PANEL_UNREAD): "left the hive" from a pose nobody has run is
                # not evidence that it is the right one. It is neither a win
                # nor a failure; the next trip starts from it again, and the
                # first arrival that is confirmed settles it.
                self._say(f"left the hive from {self.heading_offset * 45}° right "
                          f"of spawn heading, but the arrival is unconfirmed — "
                          f"not keeping that pose until one is")
                break
            if out.ok:
                self._pose_result(True)
                # IT ARRIVED. Whatever correction got it here is now the one
                # every later trip starts from, and the search starts over
                # only if that stops working.
                if self.poses_tried:
                    self._say(f"that worked from {self.heading_offset * 45}° "
                              f"right of spawn heading as hive slot "
                              f"{self.hive_slot} — keeping it")
                    self.poses_tried = set()
                    self.heading_tried = set()
                    self._remember_heading()
                self.poses_tried = set()
                self.heading_tried = set()
                break
            if self.stopped():
                # A stop (or a Take Over) during the attempt is not evidence
                # about the pose either, and must not move it.
                out.reason = out.reason or "stop requested"
                break
            if failure and (UNWALKED in failure or HELD_BACK in failure
                            or PANEL_UNREAD in failure):
                # A MOB CUT THE WALK, NOT THE POSE. The route stopped where
                # the leg was left unwalked (act/routes UNWALKED), which says
                # nothing about the heading or the slot, so the pose search
                # stays put -- as it does for CANNON_MISS. The next attempt
                # starts with the route guard, back onto the pad. The same
                # for an E the owner's Pause held back (act/routes HELD_BACK).
                if attempt > self.retries:
                    break
                self._say(f"{'a mob cut that walk short' if UNWALKED in failure else 'the panel could not be read, which is not the pose' if PANEL_UNREAD in failure else HELD_BACK}"
                          f" — trying the route to {destination} once more "
                          f"from the pad, same pose")
                continue
            # THE HEADING MOVES ON WHETHER OR NOT THERE IS A RETRY LEFT.
            #
            # The search gets one sample per cycle at best, and a failed cycle
            # ends in a rejoin, so the advance must be recorded before this
            # loop gives up -- otherwise a journey configured with no retries
            # never searches at all, and the correction is never written down.
            # THAT HEADING DID NOT WORK, SO TRY THE NEXT ONE. The reference
            # the routes are written from is measurably wrong on this account
            # and arrival is self-confirming, so the bot can find it. See
            # QUARTER_TURN_TAPS.
            #
            # Half a turn when the first walk went NOWHERE -- that is a
            # wall in front of the character and the opposite of a wall is
            # open ground -- and a quarter turn otherwise.
            self._pose_result(False)
            wins = int(self.pose_record.get("wins", 0) or 0)
            fails = int(self.pose_record.get("fails_in_row", 0) or 0)
            if wins >= POSE_TRUSTED_WINS and fails < POSE_FAILS_TO_DOUBT:
                self._say(f"that walk did not arrive, but this pose "
                          f"({self.heading_offset * 45}° right of spawn "
                          f"heading, hive slot {self.hive_slot}) has arrived "
                          f"{wins} time(s) and this is failure {fails} of "
                          f"{POSE_FAILS_TO_DOUBT} in a row — keeping it")
                if attempt > self.retries:
                    break
                self._say(f"trying the route to {destination} once more from "
                          f"the pad, same pose")
                continue
            blocked = self._first_walk_blocked >= BLOCKED_TO_TURN_AROUND
            why = ("the first walk of that route spent "
                   f"{self._first_walk_blocked:.0%} of itself going nowhere, "
                   "so the character was facing a wall before it set off"
                   if blocked else
                   "that heading did not arrive anywhere we can confirm")
            here = (self.heading_offset, self.hive_slot)
            self.poses_tried.add(here)
            self.heading_tried.add(self.heading_offset)
            nextward = self._next_pose(blocked)
            if nextward is not None and self.slot_trusted:
                # A MEASURED SLOT IS NOT A SEARCH VARIABLE. The pose search
                # may still try another heading, but it must not move the pad
                # -- the pad was read off the ramp wall, not guessed.
                nextward = (nextward[0], self.hive_slot)
            if nextward is None:
                self._say(f"{why} — and every starting pose has now been "
                          f"tried: "
                          + (f"all four headings at hive slot "
                             f"{self.hive_slot} (a measured slot, so the "
                             f"pads are not searched)" if self.slot_trusted
                             else f"all four headings and all {HIVE_SLOTS} "
                                  f"pads along the row")
                          + ", none of them arrived. Neither the heading nor "
                            "the pad is what is wrong. Back to the pad we "
                            "claimed, facing spawn heading")
                self.heading_offset = 0
                if not self.slot_trusted:
                    self.hive_slot = 0
                self.poses_tried = set()
                self.heading_tried = set()
                self._remember_heading()
            else:
                self.heading_offset, self.hive_slot = nextward
                out.turned_around = True
                self._remember_heading()
                moved = (f"hive slot {self.hive_slot}" if self.hive_slot
                         else f"{self.heading_offset * 45}° right of spawn "
                              f"heading")
                self._say(f"{why} — trying again from {moved} instead")
            if attempt > self.retries:
                break
            self._say(f"trying the route to {destination} once more, squared up")
        return out

    def home(self, routes, find=None, search_row=None) -> Outcome:
        """Get back onto our own hive pad, and know that we did.

        `search_row()` is act/hiverow's walk along the hive row, Natro's
        `nm_findHiveSlot`: run only when a recorded route ran to its end and
        the prompt is not showing, because that is the one moment the
        character is known to be AT the row (the routes home end on the
        pad or at the ramp corner) and a bounded walk along it is a search
        rather than a wander. It returns something with `.ok` and
        `.describe()`.

        `find()` is the search to run after that -- act/homing's
        `home_by_sight` -- returning something with `.ok` and `.taps`.
        """
        out = Outcome(destination="hive", routes=list(routes))
        if self.bearings.on_my_pad() is True:
            out.ok = out.confirmed = True
            out.where = self.bearings.where().describe()
            out.reason = "already standing on it"
            return out

        out.attempts = 1
        # NO SQUARE-UP BEFORE A RECORDED ROUTE HOME. BeeTuxMacro's routes are
        # a CHAIN: the route out leaves the camera where the field pattern
        # expects it (+2 taps at the Pine Tree), and the route home begins by
        # undoing exactly that. Squaring up first would have the home route
        # undo taps that were already undone and run 90 degrees wrong. Only a
        # route that starts at the hive assumes spawn heading, so only `go`
        # squares up. Shift lock IS checked: no route expects it on at start.
        if self.bearings.shift_lock is True:
            self.runner.vin.tap("shift")
            self.sleep(0.3)
            self.bearings.toggled_shift_lock()
            out.shift_reset = True
        failure = self._run_all(routes) if routes else ""
        out.blocked_seconds += self._blocked
        out.notes += self._notes
        self.bearings.moved("hive")
        self.sleep(self.settle)
        self.bearings.saw_panel(self._look())
        if self.bearings.on_my_pad() is True:
            out.ok = out.confirmed = True
            out.where = self.bearings.where().describe()
            out.reason = "the route home landed on the pad"
            self._say(out.describe())
            return out

        if (search_row is not None and routes and not failure
                and not self.stopped()):
            row = search_row()
            if bool(getattr(row, "ok", False)):
                self.bearings.saw_panel("make honey")
                out.ok = out.confirmed = True
                out.where = self.bearings.where().describe()
                described = getattr(row, "describe", None)
                out.reason = ("the route home stopped short of the pad; "
                              + (described() if callable(described) else
                                 "the row search found it"))
                self._say(out.describe())
                return out
            described = getattr(row, "describe", None)
            out.notes.append("row search: " + (described() if callable(described)
                                               else str(getattr(row, "reason", ""))))

        if find is not None and not self.stopped():
            result = find()
            self.bearings.turned(int(getattr(result, "taps", 0) or 0))
            if bool(getattr(result, "ok", False)):
                self.bearings.saw_panel("make honey")
                out.ok = out.confirmed = True
                out.where = self.bearings.where().describe()
                out.reason = f"found by searching ({getattr(result, 'hops', '?')} steps)"
                self._say(out.describe())
                return out
            out.reason = str(getattr(result, "reason", "") or "the search did not find it")
        else:
            out.reason = failure or "the route home did not land on the pad"
        place = self.bearings.where()
        out.where = place.describe() if place else "nowhere I can confirm"
        self._say(out.describe())
        return out

    # ---- helpers ------------------------------------------------------------
    def _start_is_wrong(self, routes) -> bool:
        """Can we PROVE we are not where this route begins?

        Only `False` from the compass counts -- a positive observation that we
        are somewhere else. `None` means the panel could not say, and a route
        is still attempted then, because refusing to travel whenever the
        compass is unsure would ground the bot for the rest of the night.

        Only the hive is checked, and that is not a shortcut: it is the one
        starting point the bot can confirm from the game's own words, and it
        is where every route out begins.

        `on_my_pad()`, NOT `at("hive")`. They answer different questions and
        only one of them is the question a route asks. `at("hive")` is true of
        the whole hive AREA and is satisfied by the spawn belief for a minute
        and a half after joining -- the live log said "I am in the hive area
        (68% sure, spawn, 36s ago)" at the very moment the character was
        standing on sand at the foot of the red cannon. A route out of the
        hive starts ON THE PAD, and the panel reading "Make Honey" is the only
        thing that has ever established that.
        """
        if self.go_home is None or self.starts_at is None:
            return False
        try:
            start = self.starts_at(routes)
        except Exception:
            return False
        if start != "hive":
            return False
        on_pad = self.bearings.on_my_pad()
        # NO OPINION IS NOT A YES, SO LOOK. MEASURED 2026-09-27 00:01
        # (attempt 481): an errand used the Blue Field Booster, its respawn
        # home was refused because the capture had stopped ("no pollen reading
        # at all"), and a minute without frames let the booster's panel fade
        # from the compass -- so the next trip set off for the red cannon from
        # inside the Blue HQ, its first frame showing "Use the Blue Field
        # Booster (43:34)" (var/routes/attempt-481/000105-...-walk-w20.jpg).
        # One look settles it: the pad's own prompt says yes, any other
        # place's prompt, or none, says no, and a look that cannot be taken
        # changes nothing -- the route is attempted, as before.
        if on_pad is None:
            self.bearings.saw_panel(self._look())
            on_pad = self.bearings.on_my_pad()
        return on_pad is False

    def _expected_landmark(self) -> str | None:
        """Which landmark an `interact` in the current routes is for.

        Derived from the route NAMES: `from_hive_to_pine_tree_with_red_cannon`
        contains the router node `red_cannon`, and that is the landmark whose
        prompt should be showing when the route presses E. The hive is never
        the answer here -- pressing E at the hive is converting, and that is
        `brain/farm._convert`'s decision, not a route's.
        """
        # THE NAMES OF EVERY ROUTE THAT WILL RUN, not just the ones named in
        # the list. `from_hive_to_rose_field` boards the red cannon through a
        # `call` and its own name says nothing about it, so keying on the
        # top-level names alone left `expected` empty, turned off the nearby
        # search, and let the guard accept any landmark at all. Watched live on
        # 2026-09-21 at 23:27:58, three attempts in a row.
        expanded = list(self._current_routes)
        getter = getattr(self.runner, "route_names", None)
        if callable(getter):
            try:
                expanded = list(getter(self._current_routes))
            except Exception:
                pass
        names = " ".join(expanded).lower()
        best, best_len = None, 0
        for place in self.bearings.table.places():
            if place == "hive":
                continue
            mark = self.bearings.table.landmark(place)
            node = getattr(mark, "router_node", None) if mark else None
            if node and str(node).lower() in names and len(str(node)) > best_len:
                best, best_len = place, len(str(node))
        return best

    def run_routes(self, routes) -> str:
        """Run `routes` under the guard and nothing else: an E is pressed
        only when the panel names the place it is for, the camera steps
        reach the compass, and a stop refuses the next step. No start check,
        no retry, no pose search, no arrival verdict -- for an errand that
        walks a trip's route out on its own (run_farm's bug runs, DESIGN
        8do), whose flights hold the cannon's `key_down e`. A failure reason,
        or ""."""
        return self._run_all(list(routes))

    def _run_all(self, routes) -> str:
        """Run the routes under the guard. Returns a failure reason or ""."""
        previous = self.runner.on_step

        def hook(op, step):
            if callable(previous):
                previous(op, step)
            self.guard(op, step)

        self.runner.on_step = hook
        self._current_routes = list(routes)
        self._blocked, self._notes = 0.0, []
        self._first_walk_blocked = 0.0
        previous_arrive = getattr(self.runner, "arrive", None)
        expected = self._expected_landmark()
        armed = False
        if self.target_in_view is not None and expected:
            self.runner.arrive = self.target_in_view
            armed = True
            # THE WHOLE JOURNEY, NOT ONE ROUTE. The runner gates arrival on
            # how far into the approach we are, and only the caller knows
            # that a journey can be a list of routes. An unknown total turns
            # the gate off rather than putting it in the wrong place.
            if hasattr(self.runner, "begin_approach"):
                self.runner.begin_approach(
                    self.runner.approach_studs(routes)
                    if hasattr(self.runner, "approach_studs") else None)
            # AND TELL THE WATCHER WHAT IS ON SCREEN RIGHT NOW. If a prompt is
            # already showing -- the hive pad's own "Make Honey", every single
            # time a route leaves the hive -- then the first prompt the walk
            # sees is not the target and must not stop it. Skipping this arm
            # is the bug that sent the pumpkin trip to Black Bear.
            arm = getattr(self.target_in_view, "arm", None)
            if callable(arm):
                try:
                    arm(expected)
                except Exception:
                    pass
        try:
            for name in routes:
                result = self.runner.run(name)
                learned = getattr(result, "learned_slot", None)
                raw = getattr(result, "learned_slot_raw", None)
                reading = (float(raw) if raw is not None else float(learned)
                           ) if learned and not self.slot_trusted else None
                if reading is not None:
                    self._slot_reads.append(reading)
                # THE MEAN OF THE LAST READINGS, ROUNDED UP FROM .2 (act/
                # routes SLOT_ROUND_UP). Agreement of rounded readings never
                # came: one pad read 3.2 and 2.8 (run-766, 08:28 and 08:50),
                # rounded up 4 and 3, so every walk kept feeling for the ramp
                # and the 08:50 walk out went wide; their mean, 3.0, is 3.
                recent = self._slot_reads[-SLOT_READS_TO_TRUST:]
                agreed = len(self._slot_reads) >= SLOT_READS_TO_TRUST
                if agreed:
                    reading = max(1, min(HIVE_SLOTS, int(math.floor(
                        sum(recent) / len(recent) + SLOT_ROUND_UP))))
                if reading is not None and not agreed:
                    # ONE READING IS NOT A FACT. MEASURED 2026-10-08 03:05
                    # (run-753): one walk to the ramp read slot 2 and was
                    # trusted; the formula's leg then stopped in front of the
                    # honeycomb, short of the corner every landed walk starts
                    # from (var/routes/attempt-754 against attempt-681), and
                    # every walk out after it went wide. The same pad read
                    # 2.4-3.3 at the ramp tonight. Until SLOT_READS_TO_TRUST
                    # readings are averaged, the runner keeps feeling for the
                    # ramp, which reaches the corner from any pad.
                    self._say(f"measured the hive slot at the ramp: slot "
                              f"{reading:.1f} (readings so far "
                              f"{[round(x, 1) for x in self._slot_reads]}) — not "
                              f"trusted until {SLOT_READS_TO_TRUST} are averaged")
                elif reading is not None:
                    # MEASURED, not searched: the walk to the ramp met the wall
                    # after a distance that Natro's own formula maps to one
                    # slot. From here the slot is a fact, the runner walks the
                    # formula, and the pose search leaves it alone.
                    self.hive_slot = reading
                    self.runner.hive_slot = self.hive_slot
                    self.slot_trusted = True
                    self.heading_offset = 0      # see `_poses`
                    self._say(f"measured the hive slot at the ramp: "
                              f"slot {self.hive_slot} (the mean of "
                              f"{[round(x, 1) for x in recent]}) — trusting it "
                              f"from now on")
                    if self.on_slot_learned is not None:
                        try:
                            self.on_slot_learned(self.hive_slot)
                        except Exception:
                            pass
                if self._first_walk_blocked == 0.0:
                    self._first_walk_blocked = float(
                        getattr(result, "first_walk_blocked", 0.0) or 0.0)
                self._blocked += float(getattr(result, "blocked_seconds", 0.0) or 0.0)
                self._notes += [f"{name}: {n}" for n in (getattr(result, "notes", None) or [])]
                if not getattr(result, "ok", False):
                    return f"{name}: {getattr(result, 'reason', 'did not finish')}"
            return ""
        except Refused as exc:
            try:
                self.runner.vin.release_all()
            except Exception:
                pass
            return str(exc)
        finally:
            self.runner.on_step = previous
            if hasattr(self.runner, "arrive"):
                self.runner.arrive = previous_arrive
            if armed:
                if hasattr(self.runner, "end_approach"):
                    self.runner.end_approach()
                disarm = getattr(self.target_in_view, "disarm", None)
                if callable(disarm):
                    try:
                        disarm()
                    except Exception:
                        pass
            self._current_routes = []

    def _look(self) -> str | None:
        try:
            frame = self.frames()
        except Exception:
            return None
        if frame is None:
            return None
        try:
            return self.read_panel(frame)
        except Exception:
            return None

    def _consult_supervisor(self, detail: str, destination: str | None = None) -> None:
        # BY SIGHT FIRST. The model's open "where is the player?" was MEASURED
        # at 44% on which field and takes about 1.6 s of the GPU the game is
        # using; a look at the walk's last frame, 76 of 81 right on unseen
        # nights when it is sure enough to answer (DESIGN 8dz), costs 6 ms.
        # The model still answers when the look will not.
        if self.sight is not None:
            try:
                if self.sight(destination):
                    return
            except Exception:
                pass
        if self.supervisor is None:
            return
        try:
            said = self.supervisor.diagnose_lost(detail)
        except Exception:
            return
        if said:
            self.bearings.heard(said)

    def _poses(self) -> list[tuple[int, int]]:
        """Every starting pose worth trying, cheapest doubt first.

        The four headings at the pad we claimed, and then each pad along the
        row facing spawn heading. Headings first because turning the camera
        costs a second and hopping along the row costs about ten, and because
        the heading was the likelier fault -- the claimer arrives at its pad by
        walking forward into it, so it finishes facing the wall behind.

        It is NOT every combination. Four headings times six pads is
        twenty-four trips, and a trip is a cycle: that is most of a night to
        rule out something the owner can settle by reading one number off his
        own screen (the hive-slot box in the Movement panel). Nine candidates
        is about twenty-five
        minutes.
        """
        quarters = list(range(QUARTER_TURN_TAPS, TAPS_PER_FULL_TURN,
                              QUARTER_TURN_TAPS))
        if self.slot_trusted and self.hive_slot:
            # AND NOT EVEN THE HEADING, MEASURED 2026-10-08. Natro's paths
            # all assume the camera a respawn leaves (nm_Reset before every
            # walk), and every walk that landed starts facing the hive. After
            # the night's wrong slot sent walks wide, the search took the
            # misdeliveries for a heading fault, ruled out 0 and started every
            # walk out 90 degrees round ("starting 90° right of spawn heading
            # — still searching", run-757 04:59; var/routes/attempt-757
            # 045942-natro_out_bamboo-00-start.jpg looks along the row): 5 of
            # 9 first diagonals off the path (0.00-0.01 yellow), against
            # 0.86-0.91 on every walk from 0. A trusted slot starts at spawn
            # heading, always.
            return [(0, int(self.hive_slot))]
        return ([(0, slot) for slot in range(1, HIVE_SLOTS + 1)]
                + [(q, 1) for q in quarters])

    def landed_wrong(self, aimed_at: str, landmark: str) -> bool:
        """A field trip finished on a named landmark, so the pose is suspect.

        The trip is NOT abandoned: measured, it still earns, because the
        gathering pattern walks off the landmark into the field beside it.
        This only moves the search along.

        IT IS THE WEAKER OF THE TWO SIGNALS and it runs before the gather, so
        it cannot know whether the trip will earn. `wrong_place` runs after,
        can, and vetoes a move when the trip paid -- see the note there, which
        cost 378,000 honey an hour to learn.
        """
        here = (self.heading_offset, self.hive_slot)
        self.poses_tried.add(here)
        nextward = self._next_pose(False)
        if nextward is not None and self.slot_trusted:
            # A MEASURED SLOT IS NOT A SEARCH VARIABLE, here as in `go` and
            # `_wrong_place`. This one alone moved it: a trip that finished
            # at "Open Shop" turned the owner's slot 3 into slot 1 and saved
            # it as measured (audit 2026-09-26, senses F3; run-148 03:30:03).
            nextward = (nextward[0], self.hive_slot)
        if nextward is None:
            self.heading_offset = 0
            if not self.slot_trusted:
                self.hive_slot = 0
            self.poses_tried = set()
            self.heading_tried = set()
            self._remember_heading()
            self._say("every starting pose has now been tried and a field "
                      "trip still finishes on a landmark, so the pose is not "
                      "what is wrong")
            return False
        self.heading_offset, self.hive_slot = nextward
        self._remember_heading()
        self._say(f"a trip to the {aimed_at.replace('_', ' ')} finished at "
                  f"the {landmark.replace('_', ' ')} — the walk to the owned "
                  f"pad was wrong, so trying "
                  + (f"{self.heading_offset * 45}° right of spawn heading at "
                     f"hive slot {self.hive_slot}" if self.slot_trusted
                     else f"hive slot {self.hive_slot}")
                  + " next")
        return True

    def wrong_place(self, aimed_at: str, arrived_in: str,
                    earned: bool = False) -> bool:
        """See `_wrong_place`. `earned` vetoes the whole thing -- read on."""
        if earned:
            # A DIFFERENT FIELD THAT PAYS IS NOT A FAILURE, and this cost real
            # honey before it was written down.
            #
            # MEASURED 2026-09-22: at hive slot 1 the bot aimed at the
            # Sunflower Field, was credited the Dandelion Field, and earned
            # **156,189 honey in 25 minutes -- 378,000 an hour**, on a
            # twenty-minute trip that gathered 476,000 pollen over 90 passes.
            # The search saw "wrong field" and moved to slot 2. The next
            # cycles earned **nothing at all**.
            #
            # The goal is honey, not arriving at a named field. A slot that is
            # earning is not a slot to abandon, whatever the feed calls the
            # place. The search now only moves on when the trip came back with
            # nothing, which is the only honest evidence that the pose is bad.
            if self.poses_tried:
                self._say(f"aimed at the {aimed_at.replace('_', ' ')} and the "
                          f"game credited the {arrived_in.replace('_', ' ')} "
                          f"— but the trip EARNED, so this pose stays. A "
                          f"field that pays is not the wrong field")
            self.poses_tried = set()
            self.heading_tried = set()
            self._remember_heading()
            return False
        return self._wrong_place(aimed_at, arrived_in)

    def _wrong_place(self, aimed_at: str, arrived_in: str) -> bool:
        """The game credited a DIFFERENT field than the trip aimed for.

        THE SIGNAL THE SEARCH ACTUALLY NEEDS, and `go` cannot see it. A field
        has no prompt, so the best `go` can honestly say is "left the hive,
        arrival unconfirmed" -- and it says that whether the character is in
        the right field or one along. MEASURED live 2026-09-22 02:06: the trip
        aimed at Sunflower, reported leaving the hive, and the reward feed
        credited **Dandelion** at 378 pollen/s. It farmed happily in the wrong
        field and the pose search never advanced, because nothing had failed.

        The reward feed is the one position signal this project measured to be
        reliable (DESIGN 8b), so it is the right judge. Landing one field over
        is exactly the shape of a missing `hive_offset`: the sideways walk to
        the owned pad is skipped while the slot is unknown, which is 20 to 205
        studs of error.

        Returns True when the pose was advanced.
        """
        if not aimed_at or not arrived_in or aimed_at == arrived_in:
            return False
        here = (self.heading_offset, self.hive_slot)
        self.poses_tried.add(here)
        nextward = self._next_pose(False)
        if nextward is not None and self.slot_trusted:
            # A MEASURED SLOT IS NOT A SEARCH VARIABLE; see `go`.
            nextward = (nextward[0], self.hive_slot)
        if nextward is None:
            self._say(f"aimed at the {aimed_at.replace('_', ' ')} and the "
                      f"game credited the {arrived_in.replace('_', ' ')} — "
                      f"and every starting pose has now been tried, so the "
                      f"pose is not what is wrong")
            self.heading_offset = 0
            if not self.slot_trusted:
                self.hive_slot = 0
            self.poses_tried = set()
            self.heading_tried = set()
            self._remember_heading()
            return False
        self.heading_offset, self.hive_slot = nextward
        self._remember_heading()
        self._say(f"aimed at the {aimed_at.replace('_', ' ')} and the game "
                  f"credited the {arrived_in.replace('_', ' ')} — that is one "
                  f"field over, which is what a missing sideways walk to the "
                  f"owned pad looks like. Trying hive slot {self.hive_slot} "
                  f"next")
        return True

    def _next_pose(self, blocked: bool) -> tuple[int, int] | None:
        """The next pose to try, or None when every one has had a turn.

        A blocked first walk means a wall in front of the character, and the
        opposite of a wall is open ground, so the half turn is offered ahead
        of the rest while it is still untried.
        """
        order = self._poses()
        if blocked:
            opposite = ((self.heading_offset + HALF_TURN_TAPS)
                        % TAPS_PER_FULL_TURN, self.hive_slot)
            if opposite in order:
                order = [opposite] + [p for p in order if p != opposite]
        for pose in order:
            if pose not in self.poses_tried:
                return pose
        return None

    def _pose_result(self, arrived: bool) -> None:
        """Count a walk out for the pose in use; a new pose starts at 0."""
        here = [int(self.heading_offset), int(self.hive_slot)]
        if list(self.pose_record.get("pose") or []) != here:
            self.pose_record = {"pose": here, "wins": 0, "fails_in_row": 0}
        if arrived:
            self.pose_record["wins"] = int(self.pose_record.get("wins", 0) or 0) + 1
            self.pose_record["fails_in_row"] = 0
        else:
            self.pose_record["fails_in_row"] = int(
                self.pose_record.get("fails_in_row", 0) or 0) + 1
        if self.on_pose_record is not None:
            try:
                self.on_pose_record(dict(self.pose_record))
            except Exception:
                pass

    def _remember_heading(self) -> None:
        """Hand the learned correction to whoever can write it down."""
        if self.on_heading is None:
            return
        try:
            self.on_heading(int(self.heading_offset),
                            sorted(self.heading_tried),
                            int(self.hive_slot),
                            sorted(self.poses_tried))
        except TypeError:
            # A caller that only wants the offset. Kept working on purpose:
            # the tried list was added later.
            try:
                self.on_heading(int(self.heading_offset))
            except Exception:
                pass
        except Exception:
            pass

    def _say(self, text: str) -> None:
        if self.emit is None:
            return
        try:
            from ..telemetry.events import Thought
            self.emit(Thought(topic="journey", text=text))
        except Exception:
            pass
