"""The farm loop: the thing that actually earns honey while nobody is watching.

Everything else in this project is scaffolding for one cycle:

    travel to the field -> gather -> come home -> convert -> repeat

It is deliberately the dumbest loop that can survive eight unattended hours,
because the failure that matters overnight is not "it picked a slightly worse
field". It is "the character ground against a rock from 01:00 until morning and
the summary said everything was fine". So this module is dominated by the ways a
farm loop stops being useful WITHOUT stopping, and by the difference between a
number that was read and a number that was assumed.

WHAT IT REFUSES TO GUESS

The Pollen pill is the only truth about the backpack, and reading it fails in
four distinct ways that must never be collapsed into each other:

    OK              the pill parsed; current and capacity are both known
    NO_HUD          the pills are not on screen -- a menu, a loading screen, a
                    disconnect. This is NOT "the backpack is empty"
    UNREADABLE      the pills are there and the glyphs did not parse. Also NOT
                    "the backpack is empty"
    NO_TEMPLATES    no digit templates are loaded, so nothing can be read

An empty backpack is a fifth thing: `OK` with a value of 0. MEASURED precedent
for why this matters (docs/DESIGN.md 8a): a real frame whose Pollen was 445,372
read back as "445,3?2" because the glyph 7 had never been seen, and
`digits.to_int` returns None on any "?" precisely so a caller cannot turn a
misread into a confident 44,532. This loop keeps that promise one level up: an
unreadable counter never becomes a percentage, a verdict or a honey figure. It
becomes a *count of unreadable reads* in the report, and the cycle falls back to
the clock.

HOW IT CANNOT GET PERMANENTLY STUCK

Four independent brakes, because any one of them can be the one that fails:

    1  the gather has a hard time cap    (FARM_SECONDS, BeeTuxMacro config.sh:64)
    2  a pollen counter that stops rising escalates a recovery ladder and then
       goes home, rather than farming into a wall
    3  a convert that the counter never confirms is reported as "this is not a
       hive we can convert on" instead of sleeping 100 s and calling it done
    4  consecutive cycles in which NOTHING was measured stop the loop outright
       and say a human is needed

SAFETY, which outranks all of the above

  * no key is ever left held: every movement goes through RouteRunner, which
    holds keys with `vin.held()`, and `run()` releases everything in a finally
    that also covers KeyboardInterrupt and the panic key
  * this loop presses exactly three keys of its own: `e` to convert (BeeTuxMacro
    `convert()`, stuff/utils.sh), `space` to jump and `period` to turn the
    camera. It never presses Escape and never presses Return -- Escape opens the
    in-game menu that carries **Leave**, and the respawn confirmation is a
    different screen (docs/DESIGN.md 8a). Resetting is RouteRunner's job, where
    it is gated on `screenstate.reset_dialog_present`
  * it never types anything. There is no chat path in this project and there
    must not be one
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence

from ..act.orient import SETTLE_SECONDS
from ..act.routes import CAMERA_KEYS, RouteResult
from ..telemetry.events import (Level, Log, Metric, StatusUpdate, TaskUpdate,
                                Thought)
from ..platform.current import memory
from .alive import (DEATH_LEAVES_MAX, LINK_KEEPS_SHARE, honey_says_converted,
                    rise_past_trickle)
from ..telemetry import readhealth
from ..vision import digits
from ..vision import screenstate as ss

# --- numbers, and where every one of them came from -------------------------
#
# CONVERT_TIME=100, BeeTuxMacro config.sh:66, commented "Approximate time to
# convert full backpack". It is a DWELL, not a measurement of this account's
# hive, which is why the loop watches the counter fall rather than trusting it.
CONVERT_SECONDS = 100.0

# FARM_SECONDS=420, BeeTuxMacro config.sh:64, "Set maximum seconds you can
# farm". config.sh:56-62 documents BACKPACK_DETECTION_MODE=1 as "backpack
# detection + farm seconds for maximum time", which is exactly the arrangement
# here: read the counter, and fall back to the clock when the read fails.
FARM_CAP_SECONDS = 420.0

# world/settings.py ships the Gathering section's "Convert at backpack %"
# control at 90, and explains why it is below 100: pollen gathered above
# capacity is discarded, so the last stretch of a fill returns nothing. The
# same default lives here so the engine is usable before the settings file is.
FULL_AT = 0.90

# The owner's own BeeTuxMacro config has FIELD="pine" (config.sh), and the
# transpiled graph carries exactly one route out to it and one back.
OUT_ROUTES: tuple[str, ...] = ("from_hive_to_pine_tree_with_red_cannon",)
HOME_ROUTES: tuple[str, ...] = ("from_pine_tree_to_hive",)
# These are TUPLES rather than single names on purpose. BeeTuxMacro's
# after_farm.sh follows `back_to_hive` with `from_corner_to_hive <slot>`,
# because the return route lands at the corner of the hive row rather than on
# your own hive. That second leg is NOT in the default: The owner's correction is
# that you do not own a hive until you claim an empty one after joining, so
# there is no fixed slot to walk to and RouteRunner's hop is skipped (and said
# to be skipped) until `hive_slot` is known. Once it is, the caller appends
# "from_corner_to_hive" here and nothing else changes.

# The gathering pattern. The shipped graph now carries four movement-only
# loops: `collect_around` (80.7 studs) and BeeTuxMacro's three field patterns,
# farm_square (64.4), farm_snake (231.6) and farm_better_snake (124.0), which
# the transpiler reads from stuff/utils.sh:710-848.
#
# `collect_around` stays the default because it is the only one of the four
# that this project has ever run. The owner's BeeTuxMacro config selects
# farm_better_snake (config.sh:47) and farm.sh:11 loops it forever, so it is
# the obvious candidate -- but nobody has compared pollen-per-second between
# them here, and picking on the macro's say-so would be a guess wearing a
# citation. Switching is one name, and the routine is already in the graph.
# A missing pattern STOPS the loop rather than standing still all night.
PATTERN = "collect_around"

# TOKENS LOOKED FOR WITHIN A PASS, NOT ONLY AFTER IT. The owner, 2026-10-07: "it
# rarely EVER chases tokens". MEASURED: one decision a pass -- ~17 s apart on
# the field patterns -- held 574 times to 24 chases in run-722, while the same
# brain deciding at every look of the ten newest recorded token incidents chased
# 402 times in 750 (scripts/replay_brain.py --in-view): the tokens are there,
# the look is not. So the chase is offered every CHASE_EVERY_S of the pattern
# too, between its steps; each detour walks back to where it began, as ever.
# 2.5 s: the owner, 20:2x, "keep going, make it chase more tokens" (4 s at first).
CHASE_EVERY_S = 2.5

# How long the gather may run with a flat pollen counter before calling itself
# stuck. This is a BOUND, not a measurement, and it is not presented as one --
# nobody has measured how long a working gather can legitimately show no rise.
# What is measured are the two numbers it sits between: one pass of
# `collect_around` is 80.7 studs, i.e. 2.9 s at the owner's WALKSPEED=28
# (config.sh), so the window must be far longer than a single slow pass; and
# the farm cap is 420 s, so it must be well short of that or the cycle would
# always end first and the check would never fire at all. A quarter of the cap
# catches a stall while three quarters of the trip is still recoverable.
STALL_SECONDS = FARM_CAP_SECONDS / 4

# A RISE SINCE THE LAST LOOK IS A RISE (W6, 2026-10-12), not only one past the
# trip's best: in the field the bag also FALLS, turned to honey where it stands
# (a Conversion Link, Coin Scatter -- brain/alive), and a fall under DEATH_DROP
# books nothing, so a refilling bag read "has not risen" until it passed its
# old peak. MEASURED, runs 800-916 (scratchpad w6/): of the 41 gathers whose
# counter went flat, the 20 with the feed naming a field had the bot's own
# HudReader, over the 150 frames saved at their first rung (var/incidents
# *-stall), reading the pollen RISING 824-8,415/s in 15 of the 17 legible
# clips (0 dips), and falling with the honey up 8,742 and 455,640/s in the
# other two -- the character gathering all along; the 21 off every field read
# exactly 0/s in all 15 legible. The clips nearest an onset show the fall:
# 20261011-112543 / -054930 / -104124 (runs 879, 868, 878, 4 s after, during,
# 29 s before), the bag -449, -5,341, -8,016/s while the honey rose 18,984,
# 12,143, 23,803/s. 19 of the 20 ended at the jump only because the refill
# passed the old peak; the ladder also turned the camera 45 degrees on 5 and
# walked home early on 1 (run-868 05:54:35, with 86 s of its stay left). Over
# 4,162 legible reads of 40 stall clips one read sat alone under both
# neighbours, so a misread faking this rise is about one look in 4,000.
# "on"; "ab" = on in ODD hours (HOME_UNSTICK / HOME_ALIGN's A/B uses the even
# ones); "off" = only a new best stops the clock, as before. Read it off the
# logs: "rose since the last look", and no "has not risen" with the feed
# naming a field.
RISE_SINCE_LAST_LOOK = "on"


def rise_since_last_look(hour: int | None = None) -> bool:
    """Does a reading above the LAST one stop the stall clock too, while
    RISE_SINCE_LAST_LOOK is on (now, or at `hour`)?"""
    if RISE_SINCE_LAST_LOOK == "ab":
        return (time.localtime().tm_hour if hour is None else hour) % 2 == 1
    return RISE_SINCE_LAST_LOOK == "on"

# EVERY LOOK BOOKS ITS RISE, A FALL IS BELIEVED ON A SECOND LOOK (W7,
# 2026-10-12). `pollen_gathered` was the high-water mark (`best - baseline`,
# and the Links): a bag that fell in the field -- a Honey Mark's conversion
# links, Coin Scatter (brain/alive) -- and refilled under its best booked
# nothing for the refill, and the planner ranks fields on what is booked
# (brain/ledger.pollen_by_field, decide `_rate_source`). MEASURED (scratchpad
# pb/: table.py, recover.py, replay.py) on the 303 in-gather incident clips of
# runs 783-915 the counter did not choose (mob sightings, tokens; 2,832 s):
# 61 falls of 10,000 or more, every one with the honey up by at least as much
# inside the second -- conversions, not misreads -- taking 1,167 pollen/s in
# Mushroom (30% of what the bag took in), 1,212 in Rose (20%), 3,314 in Pine
# Tree (21%, six falls), 716 in Blue Flower (6%), 467 in Pumpkin (5%), 750 in
# Mountain Top (3%), 118 in Sunflower (3%); Bamboo 32%, nearly all one Honey
# Mark of 2.9M on a full bag. Most are pulses of 10,000-90,000 that refill in
# seconds, so a look a pass (15-23 s apart) takes back 0-11% of them and a
# look between steps too (`between`, ~3 s apart: the token-brain lines)
# 46-73%. The trips agree: of the gathers the clock ended, Rose 6 of 17 and
# Mushroom 3 of 17 ended over 5% under their best (enddip.py). A second look
# before a fall counts is DeathWatch's own rule; lone misreads in those clips
# were 12 in 13,304 legible reads (spikes.py).
# "on"; "off" = the high-water mark, as before. No "ab": an hour split would
# put two measures of one field in the same ledger window. Read it off the
# logs: "refilled the bag after it fell in the field" on the cycle line, and
# the ledger's `refilled` (the old booking is `pollen - refilled`).
POLLEN_BOOKING = "on"

# AND A FULL BAG IS SEEN BETWEEN A PASS'S STEPS, not only at its end: a
# legible counter at `full_at` ends the pass where it stands and the top of
# the loop ends the gather (W7). A pass stretched by token chases and a mob
# runs for minutes: run-877 09:52:19-09:54:20 was one pass (no read between:
# the stall line's 121 s; 34 token-brain looks, 11 chases, a Mantis) while
# the bag went from 85% (var/incidents/20261011-095202-mob-sighting, last
# frame) to 99.75% (-095420-stall, frame 030); a Honey Mark then turned 3.8M
# of it to honey, the read at the pass's end saw 47%, called it a 121 s flat
# and jumped, and the gather ran on to 09:55:43. Since run-800, 31 of the 192
# gathers that ended on the bag ended at 99% or more (trips.jsonl, endfill.py)
# and a Bamboo clip (20261011-031450) shows 6,937,734 of 6,937,734 mid-gather.
# Natro looks every second, mid-pattern (natro_macro.ahk 16690-16706,
# BackpackPercentFiltered >= FieldUntilPack-2). "on"; "off" = a pass's end
# only. Read it off the logs: "between two steps of ... (brain/farm
# FULL_MID_PASS)".
FULL_MID_PASS = "on"

# AND WHEN THE GAME HAS SAID THIS IS NO FIELD (`Cycle.off_field`), how long a
# flat counter is given before the gather ends: one pass is 2.9 s, so about
# seven passes for a landing at a field's edge to walk onto the flowers.
OFF_FIELD_STALL_S = 20.0

# AND OFF THE FLOWERS WITH THE COUNTER FLAT (ROADMAP A8/A21): when the walk
# back into the flowers (`stay_in_field`) has run and still left no bed, a
# flat counter is a character standing off the field, not one stuck on an
# ankle-high bump. MEASURED 2026-10-15 04:33-04:44 (run-1013): a Blue Flower
# gather on the red cannon's platform, flat for 11 min; the ladder's jump came
# every ~110 s and a misread rise reset it to the jump each time, so it never
# reached go_home, and the gather ran to its cap. So: one jump at
# STUCK_JUMP_S (the cheap step, kept), and at STUCK_FLAT_S the gather ends,
# bag kept, and goes home the way a ladder's go_home does
# (run_farm `ended_off_the_field`). Bounds, not measurements: under the
# ladder's STALL_SECONDS (105 s) so it comes first, and a pass is 15-20 s.
STUCK_FLAT_S = 60.0
STUCK_JUMP_S = STUCK_FLAT_S / 2

# Same status: a bound between measured numbers. A full backpack takes about
# 100 s to convert, so 15 s into a WORKING conversion the counter has already
# fallen by roughly a seventh of capacity -- orders of magnitude more than a
# glyph misread. If it has not moved at all by then, the `e` did nothing.
CONVERT_CONFIRM_SECONDS = CONVERT_SECONDS * 0.15
CONVERT_PROMPTS = 2          # the first `e`, and one retry before giving up

# Capture is 13.3 ms/frame and a glyph read is sub-millisecond (docs/DESIGN.md
# 8a), so polling costs nothing measurable; 2 s keeps the convert dwell
# responsive to a stop request without spinning.
POLL_SECONDS = 2.0

# THE PAD'S OWN PROMPT HIDES THE HONEY UNTIL E IS PRESSED. MEASURED 2026-09-26
# (attempt 480, var/routes/attempt-480/233917-natro_home_pine_tree-21.01-walk
# -s10.jpg): standing on the pad, the game's "E  Make Honey" prompt sits over
# the lower half of the honey digits, so the read `_convert` takes before the
# press fails while the pollen pill, right of the prompt, still reads. Every
# convert of that attempt then ran the whole 100 s ceiling and ended
# unconfirmed -- the settle test needed that starting value -- so every errand
# after it was skipped, though the HUD honey rose 12.0M -> 22.4M over those
# trips. The prompt goes when E is pressed, and the counter holds its old value
# for the first seconds after the press (var/diag_convert frames 000-004 read
# 7,842,263 unchanged, over 2 s, before it began to roll), so a read at once
# after the press IS the starting value. BASELINE_READS of them, BASELINE_GAP
# apart -- at +0, +0.5 and +1 s, all inside that window -- because the prompt
# may take a moment to leave after the key.
BASELINE_READS = 3
BASELINE_GAP = 0.5

# MEASURED: joining the private server through the app's own server browser
# reached the world in 39.5 s (docs/DESIGN.md 8a). A HUD that has not come back
# within 60 s is therefore not a join in progress.
HUD_WAIT_SECONDS = 60.0
# When `_wait_for_hud` keeps a frame (seconds into the wait; ROADMAP A25).
HUD_MISSING_MARKS = (0.0, 10.0, 30.0, 55.0)

# How many consecutive reads may come back with no HUD at all before the loop
# decides it is no longer in the world. Reads during a gather are one pattern
# pass apart -- about 3 s at WALKSPEED=28 for `collect_around`'s 80.7 studs --
# and capture runs at 75 fps behind a deadline, so three in a row is several
# seconds of absence rather than one dropped frame. A disconnect dialog, a
# respawn or the app UI all look like this, and none of them is a screen to
# press keys at.
BLIND_READS_ALLOWED = 3

# A choice, stated as one: three consecutive cycles that measured NOTHING --
# no pollen rise and no honey -- is roughly half an hour of nothing at the
# 420 s cap. Long enough to rule out one bad read, short enough not to waste a
# night pretending to farm.
MAX_BARREN_CYCLES = 3

# A fall to below this fraction of the best reading is a death rather than a
# misread. Pollen only rises while gathering, so the margin is wide. A
# Conversion Link falls below it too, and no fraction tells the two apart (a
# real death was confirmed at 0.497); the honey does -- brain/alive
# DEATH_DROP and CONVERSION_HONEY_SHARE, measured on the saved death clips.
DEATH_DROP = 0.5
# How long a fall the honey does not explain yet is watched before it is
# believed to be a death (the Link's honey lags it; see the farm loop).
DEATH_CONFIRM_S = 10.0
# WHAT THE POLLEN BAR LOOKS LIKE EMPTY, and how much of it has to drain
# before the convert counts as having started. The bar is the fallback the
# convert dwell uses when the digits are illegible, which at seven figures is
# most converts. Measured against known frames in
# `vision/screenstate.pollen_bar_fill`: 100.0, 95.0, 27.5, 4.1 and 0.0 per
# cent. 2% is below the lowest non-empty reading that file records, and 5% of
# drain is more than the frame-to-frame wobble on a still screen.
# HOW MANY TOKENS ONE DETOUR MAY TAKE before going back to the pattern.
#
# MEASURED 2026-09-23 over 1,587 chases: the median frame has 16 tokens in
# view and the detour took one. The chase lands 93% of the time (498 of 533
# walked onto their token -- by the chase's own verdict, which until
# 2026-09-26 called a token it lost sight of "walked onto"; act/chase
# REFIND_CONFIDENCE), so the limit was never the chase -- it was that it
# got a single turn per pattern pass. `chase()` refuses when nothing is worth
# walking to, so the chain stops on its own; this only stops one rich frame
# eating a whole pass. Each link is at most four steps, so three is about 120
# studs against the pattern's 231.
CHASE_CHAIN = 3

BAR_EMPTY = 0.02
BAR_MOVED = 0.05

DEATH_MIN_POLLEN = 1_000


class Read(str, Enum):
    """Why a HUD reading is or is not a number. See the module docstring."""
    OK = "ok"
    NO_HUD = "no_hud"
    UNREADABLE = "unreadable"
    NO_TEMPLATES = "no_templates"
    NO_FRAME = "no_frame"


@dataclass(frozen=True)
class Reading:
    """One HUD reading, carrying WHY it failed when it did.

    `value` is None unless `state` is OK. That is the whole contract: there is
    no fallback value, no last-known-good and no zero, because every one of
    those turns "I could not see it" into a number that reads as a measurement.
    """
    state: Read
    value: int | None = None
    capacity: int | None = None
    text: str = ""
    score: float = 0.0
    # HOW FULL THE BAR LOOKS, 0..1, measured from the pill's own colours with
    # no digits at all (vision/screenstate.pollen_bar_fill). Set on every
    # pollen reading, legible or not, because it is the only thing that still
    # works when the counter has seven digits either side of the slash --
    # which is exactly when the backpack is full and converting matters.
    bar_fill: float | None = None

    @property
    def ok(self) -> bool:
        return self.state is Read.OK

    @property
    def fill(self) -> float | None:
        """Backpack fill in 0..1, or None when it is not known.

        From the numbers when they were legible, and from the BAR when they
        were not -- the bar is a measurement too, and a coarser one is better
        than none: without it a full backpack whose counter cannot be parsed
        never converts (see vision/screenstate.pollen_bar_fill).
        """
        if self.value is not None and self.capacity:
            return self.value / self.capacity
        return self.bar_fill

    @property
    def fill_measured_by(self) -> str:
        """Where `fill` came from: the counter, the bar, or nothing."""
        if self.value is not None and self.capacity:
            return "the counter"
        return "the bar" if self.bar_fill is not None else "nothing"

    def describe(self) -> str:
        if self.ok and self.capacity:
            return f"{self.value:,}/{self.capacity:,} ({self.fill:.0%})"
        if self.ok:
            return f"{self.value:,}"
        if self.state is Read.UNREADABLE:
            said = (f"unreadable — read {self.text!r} at confidence "
                    f"{self.score:.2f}")
            if self.bar_fill is not None:
                # The bar is still a measurement; saying so is the difference
                # between "we are blind" and "we cannot read the digits".
                said += f", but the bar looks {self.bar_fill:.0%} full"
            return said
        if self.state is Read.NO_HUD:
            return "the HUD pills are not on screen"
        if self.state is Read.NO_TEMPLATES:
            return "no digit templates are loaded, so nothing can be read"
        return "no frame from the capture"


def _health(kind: str, r: Reading) -> Reading:
    """S3 (telemetry/readhealth): a digit read is OK or UNREADABLE; no HUD,
    no frame and no templates are the world guard's, not a read's failure."""
    if r.state in (Read.OK, Read.UNREADABLE):
        readhealth.note(kind, r.ok, r.score)
    return r


class HudReader:
    """The loop's only window onto the game: frames in, Readings out.

    Kept as its own object so the farm loop can be driven by a fake in tests
    while this class is tested against REAL captures -- `tests/unit/test_farm.py`
    reads `tests/fixtures/screens/in_game.png` with the shipped templates and
    asserts the actual values in it. A seam that is never exercised against real
    pixels is how a vision bug reaches an overnight run.

    `hud_present` runs FIRST and needs no templates. That ordering is what
    separates "not in the game" from "in the game and the glyphs did not
    parse", and it is the check that stopped the Bee Swarm store page being
    classified as in-game (see vision/screenstate.py).
    """

    def __init__(self, frames: Callable[[], Any],
                 templates: digits.TemplateSet | None = None,
                 honey_region: tuple[int, int, int, int] = ss.HONEY_REGION,
                 pollen_region: tuple[int, int, int, int] = ss.POLLEN_REGION):
        self.frames = frames
        self.templates = templates
        self.honey_region = honey_region
        self.pollen_region = pollen_region
        self.frame_errors = 0
        self.last_error = ""
        # The last capacity read in full, as its digit string; see
        # `_capacity_from`.
        self._capacity: str | None = None
        self.capacity_filled = 0      # reads the fallback completed

    def pollen(self) -> Reading:
        """The backpack, as `current/capacity`.

        Parsed with `digits.parse_fraction`, never `to_int`: MEASURED on the
        real fixture frame, `to_int` reads the Pollen pill "445,372/660,000" as
        445,372,660,000 because it simply drops the slash.
        """
        return _health("pollen digits", self._read(self.pollen_region, fraction=True))

    def honey(self) -> Reading:
        return _health("honey digits", self._read(self.honey_region, fraction=False))

    # ---- internals --------------------------------------------------------
    def _frame(self):
        try:
            return self.frames()
        except Exception as exc:          # a capture timeout must not end the night
            self.frame_errors += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    def _read(self, region: tuple[int, int, int, int], fraction: bool) -> Reading:
        frame = self._frame()
        if frame is None:
            return Reading(Read.NO_FRAME)
        try:
            present = ss.hud_present(frame, (self.honey_region, self.pollen_region))
        except Exception as exc:          # a malformed frame, not a missing HUD
            self.frame_errors += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            return Reading(Read.NO_FRAME)
        if not present:
            return Reading(Read.NO_HUD)
        if self.templates is None or not self.templates.chars:
            return Reading(Read.NO_TEMPLATES)

        x, y, w, h = region
        roi = frame[y:y + h, x:x + w]
        if getattr(roi, "size", 0) == 0:
            return Reading(Read.NO_HUD)
        # THE BAR, ON EVERY POLLEN READ. It needs no digits, so it is what
        # survives a counter with seven digits either side of the slash.
        bar = None
        if fraction:
            try:
                bar = ss.pollen_bar_fill(frame)
            except Exception:
                bar = None
        text, score = digits.read(roi, self.templates)
        if fraction:
            parsed = digits.parse_fraction(text) or self._capacity_from(text)
            if parsed is None:
                return Reading(Read.UNREADABLE, text=text, score=score, bar_fill=bar)
            self._capacity = str(parsed[1])
            return Reading(Read.OK, parsed[0], parsed[1], text, score, bar_fill=bar)
        value = digits.to_int(text)
        if value is None:
            return Reading(Read.UNREADABLE, text=text, score=score)
        return Reading(Read.OK, value, None, text, score)

    def _capacity_from(self, text: str) -> tuple[int, int] | None:
        """(value, capacity) when only ONE glyph of the capacity failed and
        the rest is the last capacity read in full, digit for digit; else
        None. The capacity changes rarely and the value every second, so the
        value side stays strict (`digits.to_int`). MEASURED over 775 saved
        route frames of attempts 340-407 (DESIGN 8ds): with the small-font
        '2' and '9' cut, one read in 775 still failed on the capacity alone,
        '24/1,21?,000' against the 1,215,000 read before it; the rest failed
        on the value or the slash, which this leaves alone. And over 4,933
        saved frames, every third of var/routes and the first frame of every
        incident (DESIGN 8dt): 37 readings failed on the capacity alone --
        '11?7281', '1,324?350', '1369?12' -- against a capacity that does not
        move within a trip, and driven in time order over the 2,687 route
        frames among them a match on the capacity's text recovered 3 (the rest
        had no legible capacity earlier in the same attempt). Digits only
        here, so a capacity read once with its commas and once without still
        matches -- and so does one with NO failed glyph whose comma was lost:
        MEASURED 2026-10-22 (vision review), "5045,625" is refused by
        `to_int`'s group check, yet its digits are the capacity read before."""
        if self._capacity is None or text.count("/") != 1:
            return None
        left, right = text.split("/", 1)
        value = digits.to_int(left)
        cap = "".join(c for c in right if c.isdigit() or c == "?")
        if (value is None or cap.count("?") > 1 or len(cap) != len(self._capacity)
                or any(c != k for c, k in zip(cap, self._capacity) if c != "?")):
            return None
        self.capacity_filled += 1
        return value, int(self._capacity)


class Rung(str, Enum):
    """One recovery step, cheapest first. See LADDER."""
    JUMP = "jump"
    TURN = "turn"
    GO_HOME = "go_home"


# Ordered cheapest-first and escalating, the same rule nav/recovery.py arrived
# at: retrying the rung that just failed is how a bot spends an hour jumping.
#
#   JUMP     most obstacles in this game are ankle height (nav/recovery.py)
#   TURN     one camera tap is 45 degrees, MEASURED by closure (act/orient.py).
#            Every movement key is camera-relative, so turning the camera is
#            what redefines "forward" when forward is into a wall
#   GO_HOME  abandon the gather and run the return route. It costs the trip, so
#            it is last -- but it re-establishes position at the hive, which is
#            the only place an open-loop route can start from
LADDER: tuple[Rung, ...] = (Rung.JUMP, Rung.TURN, Rung.GO_HOME)


def stuck_off_the_flowers(off_bed: bool, flat_for: float, jumped: bool) -> Rung | None:
    """The gather's stuck rule (STUCK_FLAT_S): GO_HOME when off the flowers
    and flat for STUCK_FLAT_S, one JUMP at STUCK_JUMP_S when this flat spell
    has not had it, else None. On the flowers it never fires: a flat counter
    there is the ladder's."""
    if not off_bed:
        return None
    if flat_for >= STUCK_FLAT_S:
        return Rung.GO_HOME
    if flat_for >= STUCK_JUMP_S and not jumped:
        return Rung.JUMP
    return None
# How `_stall` begins a flat counter's line and `Cycle.gather_ended` when the
# ladder ends the trip: a counter that READ, and did not rise. run_farm's
# walk home reads it (`ended_off_the_field`): that is a gather that ended off
# its field, where the field's route home cannot start (DESIGN 8dx).
FLAT_COUNTER = "the pollen counter has not risen"


@dataclass
class Cycle:
    """One trip: out, gather, back, convert. Every field is measured or None."""
    number: int
    started_at: float = 0.0
    seconds: float = 0.0
    gather_seconds: float = 0.0
    pattern_passes: int = 0
    # Why the game says this is no field, when it has: run_farm's
    # before-gather step sets it when the sprinkler is refused "You must be
    # standing in a field" (see OFF_FIELD_STALL_S). Empty when it has not.
    off_field: str = ""
    studs: float = 0.0
    # how many times the collecting tool was swung during this cycle; 0 means
    # the bees did all of it, which costs roughly two thirds of the income
    clicks: int = 0
    # deaths seen during this cycle, each one emptying the backpack
    deaths: int = 0
    # token detours walked between pattern passes; 0 means none were taken,
    # which is the default until the owner switches chasing on
    tokens_chased: int = 0
    # CAMERA SWEEPS FOR BUBBLES made between passes (act/camsweep); None while
    # gather.rotate_camera is "never", so a trip's line says "camera sweep: N"
    # only when the switch is on and the A/B can be read off pollen/s
    camera_sweeps: int | None = None
    pollen_gathered: int | None = None    # measured rise, None when never read
    # the part of it the bag gathered back under its best after it fell in
    # the field, which the high-water mark never saw (POLLEN_BOOKING)
    pollen_refilled: int = 0
    honey_earned: int | None = None       # measured delta, None when never read
    # THE BAG THE CONVERT TOOK, read just before E; None when the counter did
    # not read. The pollen price is honey over THIS (run_farm `_finished`,
    # DESIGN 8ds): `pollen_gathered` is only the trip's rise.
    bag_at_convert: int | None = None
    converted: bool = False
    # the convert ended at the empty bag (gather.leave_at_empty_bag), so its
    # honey was still rolling onto the counter and is not measured
    left_at_empty: bool = False
    # bags converted where the character stood (`convert_in_field`: a
    # Micro-Converter), each one a walk home and back not walked
    field_converts: int = 0
    lost_hud: bool = False                # the world left the screen mid-cycle
    # HOW OFTEN THE POLLEN COUNTER COULD NOT BE READ during this trip. Counted
    # because it decides how long the trip runs: an unreadable counter used to
    # leave the stall clock running and the ladder walked home out of a field
    # that was earning. See `_gather_loop`.
    unreadable_pollen: int = 0
    gather_ended: str = ""
    # WHICH GATHER PATTERN THIS TRIP WALKED. Recorded because the pattern is
    # now per field (Natro's, data/world/natro_patterns.yaml) and the only
    # honest way to compare it with `farm_snake` is pollen per second over
    # real trips.
    pattern: str = ""
    travel_note: str = ""                 # what the journey established
    retravel: bool = False                # the stint was at the hive; go again
    convert_note: str = ""
    honey_note: str = ""
    recoveries: list[str] = field(default_factory=list)
    ok: bool = True
    reason: str = ""

    @property
    def measured_nothing(self) -> bool:
        """True when this cycle produced no evidence of any progress at all."""
        # A convert that left at the empty bag emptied a bag: progress, even
        # with its honey unmeasured and a trip whose rise never read.
        return (not self.pollen_gathered and not self.honey_earned
                and not self.left_at_empty)

    def describe(self) -> str:
        honey = (f"{self.honey_earned:+,} honey" if self.honey_earned is not None
                 else "honey not measured (left at the empty bag)" if self.left_at_empty
                 else "honey not measured")
        pollen = (f"{self.pollen_gathered:,} pollen" if self.pollen_gathered
                  is not None else "pollen not measured")
        head = (f"cycle {self.number}: {pollen}, {honey}, "
                f"{self.gather_seconds:.0f}s gathering over "
                f"{self.pattern_passes} passes")
        if self.recoveries:
            head += f" — recovered {len(self.recoveries)}x ({', '.join(self.recoveries)})"
        if self.pollen_refilled:
            head += (f" — {self.pollen_refilled:,} of it refilled the bag after it "
                     f"fell in the field (POLLEN_BOOKING)")
        if self.field_converts:
            head += (f" — {self.field_converts} bag(s) converted in the field "
                     f"(Micro-Converter)")
        if not self.pattern_passes and self.gather_ended:
            # WHICH OF THE GATHER'S EXITS FIRED. A trip that walked nothing at
            # all used to print "0s gathering over 0 passes" and no reason,
            # which made attempt 283 unanswerable from its own log.
            head += f" — gathered nothing: {self.gather_ended}"
        if self.camera_sweeps is not None:
            head += f" — camera sweep: {self.camera_sweeps}"
        if self.unreadable_pollen:
            # SAID, because it is what decides how long a trip runs. An
            # unreadable counter used to leave the stall clock running and the
            # ladder walked home out of a field that was earning.
            head += (f" — the pollen counter was unreadable "
                     f"{self.unreadable_pollen}x")
        if not self.ok:
            head += f" — STOPPED: {self.reason}"
        return head


@dataclass
class Report:
    """What the night actually produced. Nothing in here is an estimate."""
    started_at: float = 0.0
    ended_at: float = 0.0
    cycles: list[Cycle] = field(default_factory=list)
    reads: dict[Read, int] = field(default_factory=dict)
    stalls: int = 0
    recoveries: int = 0
    telemetry_errors: int = 0
    stopped_because: str = ""
    error: str = ""
    # THE BALANCE AT EACH CONVERT'S START, (clock, honey): read after E, before
    # this convert's honey has reached the counter, so consecutive marks differ
    # by a whole cycle's honey -- the convert before and whatever the trip
    # picked up. `honey_per_hour` prefers their rise (see there).
    honey_marks: list = field(default_factory=list)

    def count(self, reading: Reading) -> Reading:
        self.reads[reading.state] = self.reads.get(reading.state, 0) + 1
        return reading

    @property
    def elapsed(self) -> float:
        return max(0.0, self.ended_at - self.started_at)

    @property
    def cycles_done(self) -> int:
        return len(self.cycles)

    @property
    def honey_earned(self) -> int:
        """Sum of the MEASURED per-cycle deltas. Unmeasured cycles add nothing."""
        return sum(c.honey_earned for c in self.cycles if c.honey_earned is not None)

    @property
    def cycles_measured(self) -> int:
        return sum(1 for c in self.cycles if c.honey_earned is not None)

    @property
    def cycles_unmeasured(self) -> int:
        return self.cycles_done - self.cycles_measured

    @property
    def honey_per_hour(self) -> float | None:
        """None until there is measured honey over measured time.

        THE BALANCE'S RISE FIRST: from the first convert's start to the last
        one's (`honey_marks`), once they span BALANCE_SPAN_S and the balance
        did not fall (a purchase between them). It is a reading of the counter
        at both ends, so it holds when a convert's own honey was not measured
        -- which, since a convert may leave at the empty bag
        (gather.leave_at_empty_bag), is three converts in four -- where the
        sum of measured cycles over the run's elapsed time would read a
        quarter of the truth. That sum is the fallback.

        A rate computed from zero measured cycles is a made-up number that
        happens to be 0.0, and a panel showing it cannot be told from a real
        reading of nothing.
        """
        rate = _balance_rate(self.honey_marks)
        if rate is not None:
            return rate
        if self.cycles_measured == 0 or self.elapsed <= 0:
            return None
        return self.honey_earned * 3600.0 / self.elapsed

    @property
    def barren_streak(self) -> int:
        streak = 0
        for cycle in reversed(self.cycles):
            if not cycle.measured_nothing:
                break
            streak += 1
        return streak

    def describe(self) -> str:
        rate = self.honey_per_hour
        rate_text = f" ({rate:,.0f} honey/hr)" if rate is not None else ""
        parts = [f"{self.cycles_done} cycles in {self.elapsed / 60:.1f} min",
                 f"{self.honey_earned:,} honey measured{rate_text}"]
        if self.cycles_unmeasured:
            parts.append(f"{self.cycles_unmeasured} cycles could not be measured")
        blind = (self.reads.get(Read.UNREADABLE, 0)
                 + self.reads.get(Read.NO_TEMPLATES, 0))
        if blind:
            parts.append(f"{blind} unreadable counter reads")
        if self.reads.get(Read.NO_HUD, 0) or self.reads.get(Read.NO_FRAME, 0):
            parts.append(f"{self.reads.get(Read.NO_HUD, 0)} reads with no HUD, "
                         f"{self.reads.get(Read.NO_FRAME, 0)} with no frame")
        if self.stalls:
            parts.append(f"{self.stalls} stalls, {self.recoveries} recovery steps")
        if self.stopped_because:
            parts.append(f"stopped: {self.stopped_because}")
        return " — ".join(parts)


class _StopRequested(Exception):
    """Raised from the route runner's step hook to abort a route in progress."""


class _BagFull(Exception):
    """Raised from the step hook when the bag reads full mid-pass (FULL_MID_PASS)."""


# THE MOST ZOOM-OUT TAPS A GATHER VIEW MAY ASK FOR. Natro's own most is 8
# (natro_macro.ahk 11202, at the spawn check); after every reset and hive check
# it presses 5 (11288, 11347). Past the camera's far limit a tap does nothing
# while its undo still zooms in, so the ceiling is the source's, not ours.
GATHER_ZOOM_MOST = 8
# The spacing between zoom taps, as `forage.unblind` measured it working.
GATHER_ZOOM_GAP_S = 0.15


def gather_zoom_from(settings, fallback: int = 0) -> int:
    """`gather.camera_zoom_out`: `o` taps for the gather view, 0 to leave it.

    Natro Macro zooms out five taps after every reset (natro_macro.ahk 11288
    and 11347) and gathers from that view; the owner asked for the same
    ("should the ai zoom the screen out more", 2026-09-28, and "its pretty
    zoomed in", 2026-09-22). Unmeasured on this bot's own pixel readings, so
    the shipped default is 0 and the number is read here rather than trusted.
    """
    try:
        return max(0, min(GATHER_ZOOM_MOST, int(settings.int("gather.camera_zoom_out"))))
    except Exception:
        return fallback


def gather_tilt_from(settings, fallback: int = 0) -> int:
    """`gather.camera_tilt`: PageUp taps for the gather view, 0 to leave it.

    A popular macro's documented setting is 1 for a blue hive and 2 for a
    red one (DESIGN 8ad). Unmeasured on this bot's own detectors, so the
    shipped default is 0 and the number is read here rather than trusted.
    """
    try:
        return max(0, int(settings.int("gather.camera_tilt")))
    except Exception:
        return fallback


def errand_is_safe(cycle) -> bool:
    """May an errand run now? Only after a CONFIRMED convert.

    The errand hook (`FarmLoop.after_convert`) exists because there is one
    cheap moment to walk somewhere else: the bag is empty and the character is
    standing on its own pad. Both of those are established by a convert having
    happened, and by nothing else.

    IT USED TO ACCEPT A HONEY RISE AS WELL, and honey rises on its own -- the
    hive makes a trickle from the bees whatever the character is doing.
    MEASURED 2026-09-23 04:04 (attempt 292): the walk home failed ("turned a
    full circle and never saw the hive's yellow wall"), the convert correctly
    REFUSED to press E because nothing confirmed a hive in front of the
    character, and the errand ran anyway -- announcing "the backpack is empty
    and we are on our own pad" while its own saved frame
    (`var/bears/bucko_bee-040516.jpg`) shows the HUD reading
    1,092,706/1,113,750, 98% full, and the character wedged against a fence.
    It then walked `natro_out_bucko_bee` from there and read an empty panel.
    """
    return bool(getattr(cycle, "converted", False))


# LEAVING AT THE EMPTY BAG (gather.leave_at_empty_bag) KEEPS EVERY Nth CONVERT
# WAITING, so the honey a trip banks is still measured on that one and the
# rates read from it (honey per pollen, honey per hour) stay measured. The
# rest leave with their honey unmeasured -- said so, never estimated.
LEAVE_CALIBRATE_EVERY = 4
# AND ONLY ON A BAG READ EMPTY THIS MANY POLLS RUNNING: one false 0 (the
# dwell's own note records one at +0.6 s) or one bar at its 2% would
# otherwise walk away from pollen still in the bag.
LEAVE_EMPTY_POLLS = 2
# How long the balance marks must span before their rise is the run's rate.
BALANCE_SPAN_S = 600.0


def _balance_rate(marks) -> float | None:
    """Honey per hour from the balance marks, or None.

    THE MEDIAN OF THE CYCLES' OWN RISES once there are three, so one misread
    mark -- a wrong leading digit -- moves one rise up and the next down and
    neither the rate; with fewer, the first-to-last rise. A fall (a purchase,
    or a misread) is never a rate."""
    if len(marks) < 2:
        return None
    (t0, h0), (t1, h1) = marks[0], marks[-1]
    if t1 - t0 < BALANCE_SPAN_S:
        return None
    if len(marks) >= 4:
        slopes = sorted((b[1] - a[1]) / (b[0] - a[0])
                        for a, b in zip(marks, marks[1:]) if b[0] > a[0])
        if slopes:
            mid = slopes[len(slopes) // 2] if len(slopes) % 2 else \
                (slopes[len(slopes) // 2 - 1] + slopes[len(slopes) // 2]) / 2.0
            return mid * 3600.0 if mid >= 0 else None
    if h1 < h0:
        return None
    return (h1 - h0) * 3600.0 / (t1 - t0)


class FarmLoop:
    """Travel, gather, return, convert, repeat -- with the brakes on.

    Every dependency is injected so the whole loop runs in a test with no game,
    no compositor and no clock:

        routes   a RouteRunner (or anything with .run(name) -> RouteResult,
                 .vin and an .on_step hook)
        hud      a HudReader (or anything with .pollen() / .honey() -> Reading)
        stop     a threading.Event, or anything with .is_set()
        clock    a monotonic seconds source; `sleep` its matching delay
        emit     where telemetry events go; None to run silently

    THE STEP HOOK, and why this mutates its dependency. RouteRunner calls
    `on_step` before every step of a route. The return leg from Pine Tree is
    1,068 studs -- 38 s at WALKSPEED=28 -- so without a hook, "stop" would sit
    unacknowledged for most of a minute, and the reason someone presses stop is
    usually that something is wrong. So each route call installs a hook that
    chains the runner's own and raises `_StopRequested`, and restores the
    previous hook in a finally. The raise is safe by construction: `on_step`
    fires BEFORE the step, and every key a route holds is held through
    `vin.held()`, which releases on the way out of any exception.
    """

    def __init__(self, routes, hud, *, vin=None, stop=None, gate=None,
                 plan=None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 emit: Callable[[Any], None] | None = None,
                 on_travel=None,
                 on_cycle=None,
                 out_routes: Sequence[str] = OUT_ROUTES,
                 home_routes: Sequence[str] = HOME_ROUTES,
                 pattern: str = PATTERN,
                 full_at: float = FULL_AT,
                 farm_seconds: float = FARM_CAP_SECONDS,
                 convert_seconds: float = CONVERT_SECONDS,
                 convert_confirm_seconds: float = CONVERT_CONFIRM_SECONDS,
                 convert_prompts: int = CONVERT_PROMPTS,
                 stall_after: float = STALL_SECONDS,
                 poll_seconds: float = POLL_SECONDS,
                 hud_wait_seconds: float = HUD_WAIT_SECONDS,
                 max_barren_cycles: int = MAX_BARREN_CYCLES,
                 blind_reads_allowed: int = BLIND_READS_ALLOWED,
                 clicker=None, claim=None, confirm_hive=None, go_home=None,
                 converting=None, chase=None, before_cycle=None,
                 wrong_field=None, stay_in_field=None, quest_step_done=None,
                 bearings=None, journey=None,
                 supervisor=None, incidents=None,
                 ladder: Sequence[Rung] = LADDER,
                 gather_tilt: int = 0, after_convert=None,
                 before_gather=None, gather_zoom: int = 0,
                 leave_at_empty=None, convert_in_field=None):
        # `clicker` swings the collecting tool while gathering. MEASURED
        # 2026-09-20 in the Pine Tree field: bees alone gave +780 pollen/sec,
        # bees plus the tool gave 2,193/sec over two minutes. Not swinging it
        # throws away nearly two thirds of the income, and the owner spotted
        # that before any number did -- "its not using pollon collecting
        # tool". See act/clicker.py for why it is not a 0.3 s metronome.
        self.clicker = clicker
        # `chase()` walks to a token that `vision/tokens` can see and walks
        # back. It is called BETWEEN pattern passes and never during one: a
        # pass is a sequence of blind timed holds that only works from a known
        # start, so interrupting one leaves the character somewhere the rest of
        # the pass does not expect. None means the owner has it switched off,
        # which is the default -- see act/chase.wanted.
        self.chase = chase
        # THE COMPASS AND THE MAP PIN. `bearings` is a world.bearings.Bearings
        # and `journey` a nav.journey.Journey. With them the travel leg is
        # verified rather than assumed, the stall ladder knows the difference
        # between "stuck on a rock" and "never left the hive", and a token is
        # only chased in a field. Without them (tests, and the first runs)
        # the loop behaves exactly as it did before 2026-09-21.
        self.bearings = bearings
        self.journey = journey
        # `claim()` must return something truthy before the first cycle. Bees
        # only exist once a hive is claimed, and a hive must be claimed on
        # EVERY join -- an unclaimed session walks perfect routes to perfect
        # fields and collects zero, which is what a whole night measured.
        self.claim = claim
        # `confirm_hive()` must say the character is standing at ITS OWN hive
        # before the convert key is pressed.
        #
        # MEASURED THE EMBARRASSING WAY, 2026-09-20: a cycle returned from the
        # field, pressed `e` where it believed the hive was, and opened a
        # QUEST DIALOGUE WITH POLAR BEAR. The owner watched it happen. `e` is
        # the universal interact key -- it converts at a hive, claims an empty
        # one, opens shops and starts NPC conversations -- so pressing it on
        # faith is the same mistake as pressing Return on an unseen menu, and
        # it has the same fix: look first.
        #
        # Without a confirmation this now refuses and says so, rather than
        # pressing a key into whatever happens to be in front of it.
        self.confirm_hive = confirm_hive
        # SAY WHEN WE ARE CONVERTING, because from the pollen counter alone a
        # convert and a death are the same event: the backpack empties. The
        # death watcher cannot tell them apart and should not try to guess --
        # this loop is the only thing that knows, so it says so. Called with
        # True when the convert key is pressed and False when the dwell ends,
        # on every path out including a failure. See brain/alive.DeathWatch.
        self.converting = converting or (lambda active: None)
        # `go_home()` replaces the walked return leg when supplied.
        #
        # WHY THERE IS AN ALTERNATIVE AT ALL. The recorded return route does
        # not reliably land. The owner watched one: "when it went to jump and
        # glide down to the hive it jumped behind the ledge so id didnt even
        # glide down". The cycle then stood somewhere near the hive, pressed
        # the interact key, and opened a Polar Bear quest dialogue.
        #
        # A reset lands at the spawn platform beside the hive row EXACTLY,
        # every time, with no drift, no ledge and no glide -- and the claim
        # runs have measured that the hive is two walking steps from there.
        #
        # The reason resets were banned was that death sends every bee home
        # to rest for about 30 s. That cost is real DURING A GATHER and is
        # what kept the swarm down all night. Returning home to convert is
        # the one moment it is free: the convert dwell is 100 s of standing
        # at the hive doing nothing else, so the bees finish resting inside
        # it and are out again before the next leg starts.
        self.go_home = go_home
        # An observer, never a decider. When a gather stalls it looks at the
        # screen and says what it sees, which is how every failure today was
        # actually diagnosed -- by a human reading a screenshot. Its answers
        # go into the event stream as Thoughts; nothing here acts on them.
        self.supervisor = supervisor
        # The black box: a bounded rolling window of frames, written out when
        # something goes wrong. See telemetry/incidents.py.
        self.incidents = incidents
        self.routes = routes
        self.hud = hud
        self.vin = vin if vin is not None else getattr(routes, "vin", None)
        if self.vin is None:
            # Converting presses `e` and recovering taps `space` / `period`, so
            # there is no useful degraded mode without a keyboard. Failing here
            # beats failing two hours in with an AttributeError.
            raise ValueError("the farm loop needs an input client: pass vin=, "
                             "or a route runner that carries one")
        self.stop = stop
        # `gate()` is called at the top of every cycle and may BLOCK. That is
        # how Pause and Take Over reach a loop that is otherwise only
        # interruptible between steps -- see brain/controls.Controls.check.
        # Defaulting to None leaves the loop exactly as it was, so a caller
        # that does not pass one is unaffected.
        self.gate = gate
        # `interrupted() -> bool`: the owner took the controls during this
        # cycle (brain/controls.GuardedInput.stale). From then on nothing the
        # cycle sends reaches the game, so it is ended at the next boundary
        # -- no walk home, no convert, no errand, no travel verdict recorded
        # -- and the gate at the top of the next cycle starts it fresh. Set
        # by the caller after construction; None leaves the loop as it was.
        self.interrupted = None
        # `go_back_out() -> bool`: the going back out of a field that
        # `wrong_field` (below) said is not worth staying in, pressed at the
        # verdict and with the swing off (`_swing`): True once the character
        # is out of the field, False when it is still standing in it -- and
        # then the gather carries on, as it does on a "stay". Set by the
        # caller; None leaves a verdict to leave said and not acted on.
        self.go_back_out = None
        self._swinging = False
        # `plan(pollen, capacity) -> dict | None` decides where this trip goes,
        # or that it should not go anywhere. The loop used to walk to a single
        # hardcoded field forever; see brain/decide.Planner and the owner's
        # verdict on the old behaviour: "it feels as if it has no brain".
        # None keeps the old fixed routes, so nothing changes for a caller
        # that does not pass one.
        self.plan = plan
        self.plans = 0
        self.clock = clock
        self.sleep = sleep
        self.emit = emit
        # `on_travel(field, arrived)` is told whether a trip got there. It
        # feeds `brain.fieldnotes.travel_failed`/`arrived`, which is what stops
        # the planner choosing the same unreachable field for ever -- see
        # `decide.TRAVEL_FAILURES_TO_GIVE_UP`.
        self.on_travel = on_travel
        # `on_cycle(cycle)` is handed every COMPLETED trip, in order, so the
        # caller can write it down somewhere that outlives this process. The
        # GUI's live event stream cannot answer "what did you do all night"
        # because it restarts with the run, and the night of 2026-09-21
        # restarted 134 times -- see brain/ledger.Ledger and the owner's ask,
        # "link stats in hive mind so i can see what u did".
        self.on_cycle = on_cycle
        # `before_cycle(cycle)`: called first thing in every cycle, before the
        # planner or the bar-full shortcut. It is where the caller forgets the
        # last trip's per-trip state -- MEASURED in run-364.log:737,
        # run-370.log:942 and run-398.log:829: the route guard's homing read
        # the PREVIOUS trip's credit, because only the planner's gather path
        # reset it (DESIGN 8ds). Anything it raises is reported, never fatal.
        self.before_cycle = before_cycle
        # `wrong_field(reading) -> str | None`: asked after every pattern pass;
        # a reason means the trip landed somewhere not worth staying, and the
        # loop leaves it there and then (`go_back_out`, above; see
        # `_go_back_out` for why not at the walk home). MEASURED in
        # var/trips.jsonl: the seven Pine Tree trips credited Blue Flower
        # (attempts 371-420) gathered there for 483-1,207 s each, at about a
        # seventh of Pine Tree's rate (DESIGN 8ds). None leaves the loop as
        # it was.
        self.wrong_field = wrong_field
        # `quest_step_done(reading) -> str | None`: asked after every pattern
        # pass like `wrong_field`; a reason means the quest step this trip was
        # sent for is gathered, and the trip goes home now rather than at a
        # full bag (run_farm `quest_step_done`, `quests.first`).
        self.quest_step_done = quest_step_done
        # THE LATEST MOMENT THIS TRIP'S GATHER MAY STILL BE RUNNING, on
        # `self.clock`, and the words for ending it there: a field its guard
        # arrives on (world/timers FieldGuard) is left before it comes, however
        # long the walk out took. Set per plan from the choice's `leave_in`
        # (seconds from the plan); None has no such moment.
        self.leave_at: float | None = None
        self.leave_why = ""
        # `stay_in_field() -> act.drift.Steer | None`: asked after every
        # pattern pass, like `wrong_field`; the caller decides whether the
        # pass ended off the flowers and, if so, walks back into them there
        # and then -- or, with the owner's switch off, only says which way
        # it would have (act/drift, DESIGN 8dz). None when it did not look or
        # had nothing to say; a result is logged whether or not it walked.
        # None leaves the loop as it was.
        self.stay_in_field = stay_in_field
        self.out_routes = tuple(out_routes)
        self.home_routes = tuple(home_routes)
        # THE WALK TO USE WHEN THE FLIGHT MISSES. The planner sets it beside a
        # cannon route out (`out_fallback`) and `_travel` hands it to the
        # journey, which walks it for the rest of the trip after a missed
        # approach instead of flying again. Empty means there is none, and
        # the journey is then called exactly as before. See DESIGN 8de.
        self.out_fallback: tuple[str, ...] = ()
        # The capacity last read off a legible counter, so a bar-only fill can
        # be turned back into a number of pollen. None until one is read.
        self._last_capacity: int | None = None
        # `before_gather(cycle)`: one thing to do on arriving in a field,
        # before the first pattern pass. Placing a sprinkler is what it is
        # for -- the sprinkler is hotbar slot 1 (act/hotbar) and it works
        # where you stand, so the only moment it can be placed is this one.
        # Anything it raises is reported, never fatal: the trip still
        # gathers.
        self.before_gather = before_gather
        # `after_convert(cycle)`: an errand to run while standing on the pad
        # with an empty bag, which is the only cheap moment there is. See
        # `_after_convert`.
        self.after_convert = after_convert
        # PageUp taps applied for the gather and undone after it. A popular
        # macro's documented view is 1 for a blue hive, 2 for a red one; the
        # owner: "with the current veiw the bot wont be able to see things
        # behind it clearly or around it, its pretty zoomed in". Undone before
        # the walk home because the hive compass was measured at tilt 0.
        self.gather_tilt = max(0, int(gather_tilt or 0))
        # `o` taps applied for the gather and undone (`i`) after it, the same
        # way and for the same reason as the tilt: Natro gathers zoomed out
        # (gather_zoom_from), and everything the walk home reads -- the hive
        # compass, the claim sweep -- was measured at the zoom the session
        # joined with. A new attempt joins afresh, which resets the camera, so
        # a run that dies zoomed out does not hand the view to the next one.
        self.gather_zoom = max(0, min(GATHER_ZOOM_MOST, int(gather_zoom or 0)))
        # Which field the current trip is for, by the knowledge base's name.
        # Set by the planner each cycle; None means "whatever the routes say".
        # The journey needs it to know what "arrived" would even mean.
        self.field: str | None = None
        self.pattern = pattern
        self.full_at = min(1.0, max(0.0, float(full_at)))
        self.farm_seconds = float(farm_seconds)
        self.convert_seconds = float(convert_seconds)
        # `leave_at_empty() -> bool`: end the convert the moment the backpack
        # reads empty, without waiting for the honey counter to settle -- the
        # owner's gather.leave_at_empty_bag, a test of whether the honey still
        # rising then is credited or only drawn (see the dwell). Unset: wait.
        self.leave_at_empty = leave_at_empty
        # `convert_in_field(reading) -> bool`: asked when the bag reads full
        # mid-gather; True when it emptied the bag where the character stands
        # (a Micro-Converter, run_farm `micro_convert`), and the gather goes
        # on with the pollen before it booked the way a Conversion Link's is.
        # None leaves the loop as it was.
        self.convert_in_field = convert_in_field
        self._dwells = 0                      # converts dwelt in this loop
        self.convert_confirm_seconds = float(convert_confirm_seconds)
        self.convert_prompts = int(convert_prompts)
        self.stall_after = float(stall_after)
        self.poll_seconds = float(poll_seconds)
        self.hud_wait_seconds = float(hud_wait_seconds)
        self.max_barren_cycles = int(max_barren_cycles)
        self.blind_reads_allowed = max(1, int(blind_reads_allowed))
        self.ladder = tuple(ladder)

    # ---- the loop ---------------------------------------------------------
    def run(self, cycles: int | None = None,
            max_seconds: float | None = None) -> Report:
        """Farm until asked to stop, and report only what was measured.

        Exceptions are CAUGHT, recorded on the report and emitted as an ERROR
        log rather than raised. An unattended run wants the night's numbers and
        a named failure, not a traceback into a supervisor that may restart
        straight back into it. The loop still ENDS -- it never continues past an
        unknown failure -- and `report.error` is what the GUI shows.

        BaseException (KeyboardInterrupt, SystemExit, the panic path) is left
        alone deliberately: those mean "stop now", and the finally below still
        releases every key before they travel on.
        """
        report = Report(started_at=self.clock())
        # Exposed so a planner can read what the last cycles actually cost.
        # `brain/decide.best_trip_seconds` needs the MEASURED round-trip
        # overhead to decide how long the next trip should be, and inventing
        # that number would defeat the point of computing it at all.
        self.report = report
        # Watch our own footprint, not the machine's. See platform/memory.py:
        # three runs were OOM-killed holding 16-25 GB and the cause is still
        # unknown, so the loop carries its own ceiling until it is found.
        watch = memory.SelfWatch()
        self._emit(StatusUpdate(running=True, note="farm loop starting"))
        # A STOP ALREADY ASKED FOR IS NOT A REASON TO CLAIM. MEASURED in
        # run-310.log:48-76: the quest menu would not close, the run asked to
        # stop, and the claim sweep still walked 14 steps one way and 28 back
        # behind the open menu for 66 s (DESIGN 8ds). And the GUI hears that
        # the loop is not running, as it does from the `finally` below.
        if self._stopped():
            report.stopped_because = "stop requested"
            report.ended_at = self.clock()
            self._emit(StatusUpdate(running=False, uptime_s=report.elapsed,
                                    note=report.stopped_because))
            return report
        if self.claim is not None:
            claimed = self.claim()
            if (not bool(getattr(claimed, "ok", claimed))
                    and self._interrupted() and self.gate is not None):
                # THE OWNER TOOK THE CONTROLS DURING THE CLAIM, so its keys
                # stopped reaching the game (see `interrupted`). That is not a
                # failed claim: wait out his turn at the gate, which starts the
                # next attempt fresh, and claim once more.
                #
                # OUTSIDE THE LOOP'S `try`, so a Stop pressed while he holds
                # the controls -- the gate raises it (controls.check) -- ends
                # the run here, said and with every key up, not as a traceback
                # out of `run`.
                #
                # And the GUI hears that the loop is not running, as it does
                # for a stop before the claim.
                try:
                    self.gate()
                    if not self._stopped():
                        claimed = self.claim()
                except Exception as exc:
                    self.vin.release_all()
                    if self._stopped():
                        report.stopped_because = "stop requested"
                    else:
                        report.error = f"{type(exc).__name__}: {exc}"
                        report.stopped_because = f"stopped by an error: {report.error}"
                    report.ended_at = self.clock()
                    self._emit(StatusUpdate(running=False, uptime_s=report.elapsed,
                                            note=report.stopped_because))
                    return report
                if self._stopped():
                    report.stopped_because = "stop requested"
                    report.ended_at = self.clock()
                    self._emit(StatusUpdate(running=False, uptime_s=report.elapsed,
                                            note=report.stopped_because))
                    return report
            ok = bool(getattr(claimed, "ok", claimed))
            detail = getattr(claimed, "describe", lambda: str(claimed))()
            self._emit(Log(message=f"hive: {detail}",
                           level=Level.INFO if ok else Level.ERROR,
                           source="farm"))
            if not ok:
                report.stopped_because = (
                    f"could not claim a hive, so there are no bees and "
                    f"nothing would be collected: {detail}")
                report.ended_at = self.clock()
                return report
        self._emit(Thought(topic="farm", text=self._opening_line(),
                           detail=self._plan()))
        try:
            while True:
                if self._stopped():
                    report.stopped_because = "stop requested"
                    break
                if self.gate is not None:
                    # Blocks while paused or while the owner has the controls.
                    # Deliberately BEFORE the cycle rather than inside it: a
                    # handover half way through a walk would hand over a
                    # character mid-stride with the backpack still filling.
                    self.gate()
                    if self._stopped():
                        report.stopped_because = "stop requested"
                        break
                grew = watch.check(f"cycle {report.cycles_done + 1}")
                if grew is not None:
                    report.stopped_because = grew
                    self._emit(Log(message=grew, level=Level.ERROR,
                                   source="farm"))
                    break
                if cycles is not None and report.cycles_done >= cycles:
                    report.stopped_because = f"finished the {cycles} cycles asked for"
                    break
                if max_seconds is not None and \
                        self.clock() - report.started_at >= max_seconds:
                    report.stopped_because = \
                        f"reached the {max_seconds:.0f}s session limit"
                    break
                if not self._wait_for_hud(report):
                    report.stopped_because = (
                        "stop requested" if self._stopped() else
                        f"the game HUD did not appear within "
                        f"{self.hud_wait_seconds:.0f}s — not in the world, so "
                        f"there is nothing safe to press")
                    break

                cycle = self.cycle(report.cycles_done + 1, report)
                report.cycles.append(cycle)
                self._report_cycle(cycle, report)

                if not cycle.ok:
                    report.stopped_because = cycle.reason
                    break
                if report.barren_streak >= self.max_barren_cycles:
                    report.stopped_because = (
                        f"{report.barren_streak} cycles in a row measured "
                        f"nothing — no pollen rise and no honey. Something is "
                        f"wrong that walking cannot fix; this needs a human")
                    self._emit(Log(message=report.stopped_because,
                                   level=Level.WARN, source="farm"))
                    break
        except Exception as exc:
            report.error = f"{type(exc).__name__}: {exc}"
            report.stopped_because = f"stopped by an error: {report.error}"
            self._emit(Log(message=report.stopped_because, level=Level.ERROR,
                           source="farm"))
        finally:
            # Guarantee 2 from platform/input.py: release_all between tasks.
            # It runs on the clean path, the stop path, the error path and on
            # the way out of a KeyboardInterrupt.
            self.vin.release_all()
            report.ended_at = self.clock()
            self._emit(StatusUpdate(running=False, uptime_s=report.elapsed,
                                    note=report.stopped_because))
            self._emit(Thought(topic="farm", text=report.describe()))
            rate = report.honey_per_hour
            if rate is not None:
                self._emit(Metric(name="honey_per_hour", value=rate,
                                  unit="honey/hr"))
        return report

    def cycle(self, number: int, report: Report) -> Cycle:
        """One full trip. Sets `ok` False only when the loop must not continue."""
        cycle = Cycle(number=number, started_at=self.clock())
        try:
            if self.before_cycle is not None:
                try:
                    self.before_cycle(cycle)
                except Exception as exc:
                    self._emit(Log(message=(f"the before-cycle step failed "
                                            f"({exc}) — carrying on"),
                                   level=Level.WARN, source="farm"))
            if self.plan is not None and not self._choose(cycle):
                # The planner said not to travel -- almost always because the
                # backpack is worth more than the trip. Convert where we stand
                # rather than carrying it past a mantis.
                self._convert(cycle, report)
                return cycle
            if not self._travel(cycle):
                return cycle
            if self._stopped():
                cycle.ok, cycle.reason = False, "stop requested"
                return cycle

            self._gather(cycle, report)
            if cycle.retravel:
                # We never left. There is nothing to convert and nowhere to
                # walk home from; the next cycle travels again, squared up.
                return cycle
            if not cycle.ok or cycle.lost_hud:
                # `lost_hud` leaves `ok` True on purpose: the trip is abandoned,
                # not the run. The next pass of the loop waits for the world to
                # come back, and if it does not, THAT is what stops the loop --
                # with a message about the HUD rather than about a route.
                return cycle
            if self._stopped():
                # Deliberately does NOT walk home first. Whatever is in the
                # backpack stays there and converts on the next run; a stop
                # request is not an invitation to do another 38 s of walking.
                cycle.ok, cycle.reason = False, "stop requested"
                return cycle
            if self._interrupted():
                # The owner moved the character: the next cycle plans from
                # wherever he left it (a full bag plans a convert).
                cycle.retravel = True
                cycle.gather_ended = cycle.gather_ended or "the owner took the controls"
                return cycle

            if self.go_home is not None:
                outcome = self.go_home()
                if not bool(getattr(outcome, "ok", outcome)):
                    cycle.ok = False
                    cycle.reason = (
                        f"could not get back to the hive: "
                        f"{getattr(outcome, 'reason', outcome)}")
                    return cycle
            elif not self._leg("return to the hive", self.home_routes, cycle):
                return cycle
            self._convert(cycle, report)
            return cycle
        finally:
            cycle.seconds = self.clock() - cycle.started_at

    def _after_convert(self, cycle: Cycle) -> None:
        """The one moment an errand is cheap: the bag is empty and the
        character is standing on its own pad, confirmed by the honey counter
        settling. `after_convert(cycle)` is the caller's hook and runs at most
        once per call; anything it raises is reported, never fatal.

        WHY HERE AND NOWHERE ELSE. The quest-giver recon (act/bearvisit) was
        wired at session start on 2026-09-22 and cost attempt 256 its whole
        session: it walked 162 studs to the Black Bear, the reversed route
        back did not land, and the claim sweep -- which starts from the spawn
        point -- then walked fourteen steps without finding a pad, with a full
        backpack waiting. From here a failed walk back costs one trip, which
        the route-out guard and the rejoin both already recover from.
        """
        # NOT AFTER A STOP. An errand is a walk and a respawn; a stop asked for
        # during the convert (the owner, the watchdog, a quest menu that would
        # not close) means no more of either (DESIGN 8ds). Nor after the
        # owner took the controls (`interrupted`): nothing it pressed would
        # reach the game.
        if self.after_convert is None or self._stopped() or self._interrupted():
            return
        try:
            self.after_convert(cycle)
        except Exception as exc:
            # WHERE, not just what. MEASURED 2026-09-23 23:10:33: "the
            # after-convert errand failed ('float' object is not iterable)"
            # named no line, and the cause -- a name clobbered in
            # run_farm's `main` -- took reading half the script to find. The
            # innermost frames of the traceback are cheap and say it at once.
            import traceback
            frames = traceback.extract_tb(exc.__traceback__)[-3:]
            where = " < ".join(f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno} {f.name}"
                               for f in reversed(frames))
            self._emit(Log(message=f"the after-convert errand failed ({exc}) at "
                                   f"{where} — carrying on",
                           level=Level.WARN, source="farm"))

    def _choose(self, cycle: Cycle) -> bool:
        """Ask the planner where to go. False means "do not travel at all".

        A planner that fails or says nothing leaves the configured routes
        alone, because a broken brain must not stop the loop earning -- the
        old fixed behaviour is the fallback, not an error.
        """
        reading = self.hud.pollen()
        # A BAR-ONLY READING IS STILL A READING. MEASURED 2026-09-22 23:37 to
        # 2026-09-23 00:22: with the backpack full the counter reads
        # "11?0?46/111???0" at 0.49 and `value` is None, so the planner saw no
        # backpack at all, never chose to convert, and six attempts in a row
        # gathered into a full bag with the honey stuck at 7,256,845. The bar
        # says 100% without any digits (vision/screenstate.pollen_bar_fill),
        # so when the counter cannot be parsed the planner is handed the
        # CAPACITY it last knew and the bar's share of it -- an estimate,
        # named as one in the log, and enough to decide to go and convert.
        pollen, capacity = getattr(reading, "value", None), getattr(reading, "capacity", None)
        # FULL IS FULL, EVEN WITH NO NUMBER. MEASURED 2026-09-23 00:32: at
        # session start the counter read "1?0?419/111???0" and the bar said
        # 100%, but no legible capacity had been read yet this session, so
        # the planner was handed nothing, chose to travel, flew to Stump, and
        # turned straight round because the gather's own check DID see the
        # bar. One trip's walk out and back for nothing. A bar at or above
        # the convert threshold is enough on its own to say "do not travel,
        # convert" -- it needs no capacity and invents no number.
        if (pollen is None and reading.bar_fill is not None
                and reading.bar_fill >= self.full_at):
            cycle.reason = (f"not travelling: the pollen counter is unreadable "
                            f"but the bar looks {reading.bar_fill:.0%} full, "
                            f"which is past the {self.full_at:.0%} it converts at")
            self._emit(Log(message=cycle.reason, source="farm"))
            return False
        if pollen is None and reading.bar_fill is not None and self._last_capacity:
            capacity = self._last_capacity
            pollen = int(round(reading.bar_fill * capacity))
            self._emit(Log(message=(
                f"the pollen counter is unreadable, but the bar looks "
                f"{reading.bar_fill:.0%} full — planning against about "
                f"{pollen:,} of {capacity:,}"), source="farm"))
        elif capacity:
            self._last_capacity = int(capacity)
        # Every plan says its own leave-by; one trip's never carries over.
        self.leave_at, self.leave_why = None, ""
        try:
            choice = self.plan(pollen, capacity)
        except Exception as exc:
            self._emit(Log(message=f"the planner failed ({exc}) — "
                                   "using the configured route",
                           level=Level.WARN, source="farm"))
            return True
        if not choice:
            return True

        self.plans += 1
        why = str(choice.get("why", ""))
        self._emit(Thought(topic="plan", text=why,
                           detail=str(choice.get("detail", ""))))
        if choice.get("action") == "convert":
            cycle.reason = f"not travelling: {why}"
            return False
        # THE FIELD'S OWN GATHER PATTERN. `farm_snake` was walked on every
        # trip regardless of field; Natro ships one per field at the width
        # its community settled on (data/world/natro_patterns.yaml). Named in
        # the log because the two are compared on pollen per second.
        pattern = choice.get("pattern")
        if pattern and pattern != self.pattern:
            self._emit(Log(message=(f"gathering with {pattern} instead of "
                                    f"{self.pattern}"), source="farm"))
            self.pattern = str(pattern)
        out, home = choice.get("out"), choice.get("home")
        if out:
            # A route home is optional (`go_home` walks from where the game
            # says we are); a route OUT is not.
            self.out_routes, self.home_routes = tuple(out), tuple(home or ())
            # Belongs to THIS route out, so it is replaced with it -- a walk
            # kept from an earlier plan would send a miss to the wrong field.
            self.out_fallback = tuple(choice.get("out_fallback") or ())
            self._no_route_out = False
        elif choice.get("field") and choice.get("field") != self.field:
            # A NEW FIELD WITH NO ROUTE OUT IS NOT TRAVELLED TO ON THE OLD
            # ONE. MEASURED run-319: the plan named stump with no routes, and
            # the trip walked from_hive_to_pine_tree_with_red_cannon "to
            # stump", landed in Pine Tree and filed the miss against Stump.
            self.out_routes, self.out_fallback = (), ()
            self._no_route_out = True
        self.field = choice.get("field") or self.field

        # HOW LONG TO STAY, decided per trip rather than inherited as a
        # constant. The planner works it out from the round-trip overhead and
        # from how often this particular field has actually killed us; see
        # brain/decide.best_trip_seconds. A field that has never killed us
        # earns a trip long enough to fill the backpack, and one that kills
        # often earns a raid. `FARM_SECONDS=420` was neither, and MEASURED it
        # was ending trips at 47% full while paying the whole round trip.
        stay = choice.get("farm_seconds")
        if stay:
            try:
                stay = float(stay)
            except (TypeError, ValueError):
                stay = 0.0
            if stay > 0 and stay != self.farm_seconds:
                self._emit(Thought(
                    topic="plan",
                    text=f"staying up to {stay:.0f}s this trip",
                    detail=str(choice.get("stay_why", ""))))
                self.farm_seconds = stay
        leave_in = choice.get("leave_in")
        if leave_in is not None:
            try:
                self.leave_at = self.clock() + max(0.0, float(leave_in))
                self.leave_why = str(choice.get("leave_why") or
                                     "past the time this field had to be left by")
            except (TypeError, ValueError):
                self.leave_at = None
        return True

    # ---- phases -----------------------------------------------------------
    def _travel(self, cycle: Cycle) -> bool:
        """Get to the field, and do not hand the gatherer a hive pad.

        With a journey the routes run squared-up and guarded, and the answer
        is checked: still at the hive means the trip failed, however cleanly
        the timers ran. See nav/journey for the run that made this necessary.
        Without one, this is the old timed leg.
        """
        if getattr(self, "_no_route_out", False):
            cycle.reason = (f"no route out to the "
                            f"{(self.field or 'field').replace('_', ' ')} — "
                            f"not walking another field's route under its name")
            cycle.gather_ended = f"did not travel: {cycle.reason}"
            self._emit(Log(message=cycle.reason, level=Level.WARN, source="farm"))
            # AND SAID AS A FAILED TRIP, or the planner chooses the same field
            # every cycle: its travel_failures never rise, and three of these
            # in a row end the run on MAX_BARREN_CYCLES -- runs 149-151's
            # shape (run_farm `plan`). It also files this cycle's ledger row
            # under this field, not the last trip's -- and these words, not
            # the last trip's, are what the cannon's record reads.
            self.last_travel_reason, self.last_fell_back = cycle.reason, False
            self._told_travel(self.field, False)
            return False
        if self.journey is None:
            return self._leg("travel to the field", self.out_routes, cycle)
        destination = self.field or "the field"
        self._emit(TaskUpdate(name="travel to the field", status="running",
                              progress=-1.0,
                              detail=" then ".join(self.out_routes)))
        try:
            # The fallback only when there is one, so a journey that predates
            # it (and the fakes that stand in for one) is called as it was.
            if self.out_fallback:
                outcome = self.journey.go(destination, self.out_routes,
                                          fallback=self.out_fallback)
            else:
                outcome = self.journey.go(destination, self.out_routes)
        except Exception as exc:
            cycle.ok = False
            cycle.reason = f"the journey failed: {exc}"
            self._emit(TaskUpdate(name="travel to the field", status="failed",
                                  detail=cycle.reason))
            return False
        cycle.travel_note = outcome.describe()
        if self._interrupted():
            # NOT A VERDICT ON THE ROUTE: its keys stopped reaching the game
            # when the owner took over, so neither the notes nor the cannon
            # record may learn from how it ended.
            cycle.retravel = True
            cycle.gather_ended = "did not travel: the owner took the controls"
            return False
        # THE REAL FIELD NAME, NEVER THE DISPLAY LABEL. `destination` falls
        # back to "the field" so the log reads well when nothing named it, and
        # passing that on wrote a field called "the field" into the notes --
        # where it absorbed the failures that belonged to the field actually
        # being attempted, so that field was never given up. None here means
        # "nothing to record", which `_told_travel` honours.
        # WHY IT DID OR DID NOT GET THERE, for callers that need the words
        # and not only the verdict: `on_travel` is told a bool, and the red
        # cannon's own record (run_farm, CANNON_RECORD_FILE) needs to know
        # whether the miss was at the cannon.
        self.last_travel_reason = str(getattr(outcome, "reason", "") or "")
        # A missed cannon approach that the same trip then walked round
        # (nav.journey `fell_back`) arrives, so its reason no longer says
        # "never stood at the red cannon" -- but the cannon still missed.
        self.last_fell_back = bool(getattr(outcome, "fell_back", False))
        # A STOP IS NO VERDICT ON THE FIELD. A route refused because a stop was
        # asked (run_farm respawn_before_the_walk_out) never set off; booked as
        # a miss it would count toward the field's ban. MEASURED 2026-10-20
        # 20:17:25, a deploy's stop: "travel failed — to pumpkin ... not walked
        # — stop requested".
        if outcome.ok or "stop requested" not in str(outcome.reason or ""):
            self._told_travel(self.field, bool(outcome.ok))
        if not outcome.ok:
            # NOT `cycle.ok = False`: a failed trip is not a reason to stop
            # the night. The next cycle squares up and tries again, and the
            # journey has already retried once itself.
            cycle.reason = outcome.reason
            cycle.gather_ended = f"did not travel: {outcome.reason}"
            self._emit(TaskUpdate(name="travel to the field", status="failed",
                                  detail=outcome.reason))
            self._emit(Log(message=f"travel failed — {outcome.describe()}",
                           level=Level.WARN, source="journey"))
            return False
        self._emit(TaskUpdate(name="travel to the field", status="done",
                              progress=1.0, detail=outcome.describe()))
        return True

    def _told_travel(self, field: str | None, arrived: bool) -> None:
        """Report the trip's outcome, and never let the report end a cycle.

        `field` is None when nothing named the destination. Nothing is
        reported then: a note filed under a placeholder is worse than no note,
        because it silently absorbs the evidence that belonged elsewhere.
        """
        if self.on_travel is None or not field:
            return
        try:
            self.on_travel(field, arrived)
        except Exception:
            pass

    def _leg(self, label: str, names: Sequence[str], cycle: Cycle) -> bool:
        """Walk a leg, and have the supervisor say where it ended up.

        THE OWNER ASKED FOR THIS DIRECTLY: "is there a way to get the ai to
        tell u wehats happening incase u cant tell because it literally cant
        find how or where to glide".

        He is describing the exact hole. When a leg goes wrong the bot has no
        idea -- the route ran, every step returned, and the character is
        simply somewhere else. The only account of what actually happened has
        come from a human watching: "it took cannon to pine, it immidietly
        went up ramp and tried to glide from ramp which as youwould expected
        did nothing but hit the ground then it walked to the right towards
        pine into a wall", "then made its way inside the trophy store with
        sprinklers". None of that is in any log.

        The model can read a frame and say where the character is, so after
        every leg it is asked. That turns "the route completed" -- which is
        all a timed walk can ever report -- into a sentence about where the
        character actually is.
        """
        self._emit(TaskUpdate(name=label, status="running", progress=-1.0,
                              detail=" then ".join(names)))
        for name in names:
            result = self._run_route(name)
            cycle.studs += result.studs
            if self.supervisor is not None and not result.ok:
                self.supervisor.diagnose_lost(f"{label}: {name} did not finish")
            if not result.ok:
                cycle.ok = False
                cycle.reason = self._route_failure(name, result)
                self._emit(TaskUpdate(name=label, status="failed",
                                      detail=cycle.reason))
                return False
        self._emit(TaskUpdate(name=label, status="done", progress=1.0,
                              detail=f"{cycle.studs:,.0f} studs so far"))
        # "done" here means every step ran, which is NOT the same as arriving.
        # A timed walk cannot tell the two apart, so ask something that can.
        if self.supervisor is not None:
            self.supervisor.diagnose_lost(f"{label}: finished {names[-1]}")
        return True

    def _gather(self, cycle: Cycle, report: Report) -> None:
        """Run the pattern until the backpack is full, the cap hits, or we stall."""
        started = self.clock()
        cycle.pattern = self.pattern
        self._emit(TaskUpdate(
            name="gather", status="running", progress=-1.0,
            detail=f"{self.pattern} until the backpack reads {self.full_at:.0%} "
                   f"or {self.farm_seconds:.0f}s pass"))

        if self.before_gather is not None:
            try:
                self.before_gather(cycle)
            except Exception as exc:
                self._emit(Log(message=(f"the before-gather step failed "
                                        f"({exc}) — gathering anyway"),
                               level=Level.WARN, source="farm"))

        reading = report.count(self.hud.pollen())
        self._report_fill(reading)
        baseline = reading.value if reading.ok else None
        best = baseline
        last_rise_at = started
        rung = 0
        blind = 0

        # Swing the tool for the duration of the gather and stop it on every
        # exit, including the stop request and any exception. It is started
        # HERE rather than for the whole session because a click lands
        # wherever the pointer is, and outside the field the bot is walking
        # routes and passing prompts that a stray click would activate.
        self._swing(True)
        if self.gather_tilt:
            self._emit(Log(message=(f"camera tilted {self.gather_tilt} PageUp "
                                    f"tap(s) for the gather (the common gather view); "
                                    f"undone before the walk home"),
                           source="farm"))
        if self.gather_zoom:
            self._emit(Log(message=(f"camera zoomed out {self.gather_zoom} tap(s) "
                                    f"for the gather (Natro's view); zoomed back "
                                    f"in before the walk home"),
                           source="farm"))
        try:
            self._gather_loop(cycle, report, started, reading, baseline, best,
                              last_rise_at, rung, blind)
        finally:
            self._swing(False)
            if self.clicker is not None:
                cycle.clicks = getattr(self.clicker, "clicks", 0)

    def _swing(self, on: bool) -> None:
        """The gather's tool and view -- the clicker, `gather_tilt` and
        `gather_zoom` -- on
        for the gather and off at every exit from it.

        OFF BEFORE A RESPAWN FROM INSIDE IT, too (`go_back_out`): a click
        lands wherever the pointer is, and on the reset menu that is a button
        (act/clicker), and the tilt is undone so the next trip starts with
        the camera its routes expect. Asked twice for the same state it does
        nothing, so the gather's `finally` never undoes a tilt twice."""
        if on == self._swinging:
            return
        self._swinging = on
        if on:
            if self.clicker is not None:
                self.clicker.start()
            for _ in range(self.gather_tilt):
                self.vin.tap("pageup")
            for _ in range(self.gather_zoom):
                self.vin.tap("o")
                self.sleep(GATHER_ZOOM_GAP_S)
            return
        for _ in range(self.gather_tilt):
            self.vin.tap("pagedown")
        for _ in range(self.gather_zoom):
            self.vin.tap("i")
            self.sleep(GATHER_ZOOM_GAP_S)
        if self.clicker is not None:
            self.clicker.stop()

    def _gather_loop(self, cycle: Cycle, report: Report, started, reading,
                     baseline, best, last_rise_at, rung, blind) -> None:
        # HAS POLLEN GONE UP EVEN ONCE THIS TRIP? It decides whether an
        # unreadable counter is forgiven; see the unreadable branch below.
        # A trip that has never measured a rise has no evidence it is
        # gathering, and a counter it cannot read is no reason to stay.
        rose_at_least_once = False
        # WHAT A CONVERSION LINK TOOK, kept: the Link empties the bag into
        # honey and `baseline` restarts from there, so without this the trip's
        # `pollen_gathered` -- and its ledger row, a ranking source
        # (brain/decide `_rate_source`) -- lost everything before the Link.
        linked = 0
        # AND THE BOOKING THAT SEES A FALL (POLLEN_BOOKING): every look's rise
        # over the last one it believes -- at a pass's end and between its
        # steps -- and what that stood at at the last Link or field convert,
        # which is all a death keeps (it loses the bag after, as `linked` does).
        look, gained, banked = baseline, 0, 0

        def book(seen: Reading) -> Reading:
            """A legible look books its rise over the last believed one. A
            fall is believed on a second look, which stands in for the first
            (DeathWatch's rule: one low read is also what a misread looks
            like); an illegible second look leaves it unbelieved."""
            nonlocal look, gained
            if POLLEN_BOOKING != "on" or not seen.ok:
                return seen
            if look is not None and seen.value < look:
                again = report.count(self.hud.pollen())
                if not again.ok:
                    return seen
                seen = again
            if look is not None:
                gained += max(0, seen.value - look)
            look = seen.value
            return seen

        def between() -> None:
            """Between two steps of a pass: the bag (POLLEN_BOOKING,
            FULL_MID_PASS), then a token. A legible counter at `full_at` ends
            the pass where it stands; the top of the loop ends the gather."""
            if POLLEN_BOOKING == "on" or FULL_MID_PASS == "on":
                bag = book(report.count(self.hud.pollen()))
                if (FULL_MID_PASS == "on" and bag.ok and bag.fill is not None
                        and bag.fill >= self.full_at):
                    raise _BagFull(bag.describe())
            self._chase_a_token(cycle)

        # THE HONEY WHEN `best` WAS SET, the last two readings with when, so a
        # fall can be told from a conversion (brain/alive CONVERSION_HONEY_
        # SHARE, rise_past_trickle). One HUD read on a pass that set `best`.
        best_honey: list[tuple[int, float]] = []
        seen_honey = self._honey_now()
        if seen_honey is not None:
            best_honey.append((seen_honey, self.clock()))
        # THE LAST LEGIBLE READING and when `best` last rose (RISE_SINCE_LAST_LOOK)
        last_seen, best_at, said_refill = best, last_rise_at, False
        # OFF THE FLOWERS after the walk back (`stay_in_field`, STUCK_FLAT_S),
        # and the flat spell (its `last_rise_at`) the stuck jump was spent on
        off_bed, stuck_jumped = False, None
        while True:
            if self._stopped():
                cycle.gather_ended = "stop requested"
                break
            if self._interrupted():
                cycle.gather_ended = ("the owner took the controls — ending "
                                      "this trip; the next cycle starts from "
                                      "wherever he left the character")
                cycle.retravel = True
                break

            # Checked at the TOP so arriving with a full backpack -- which is
            # what a cycle whose convert failed leaves behind -- turns straight
            # round instead of burning a 420 s gather that can collect nothing.
            fill = reading.fill
            if fill is not None and fill >= self.full_at:
                # A BAR-ONLY READING MUST SAY IT TWICE BEFORE IT ENDS A TRIP.
                # The bar is a good measurement of a steady screen and a poor
                # one of a moving character: a frame taken as the cannon's
                # flight lands, or with the pill over a bright field, can read
                # full when the backpack is empty. MEASURED 2026-09-23 02:28
                # (attempt 283): the flight to Cactus landed, the trip ended
                # with "0s gathering over 0 passes" and nothing in the log
                # said which of the three exits fired. Ending a 1,200-second
                # trip on one frame is not worth the 25 ms a second look
                # costs.
                if reading.fill_measured_by == "the bar":
                    again = report.count(self.hud.pollen())
                    second = again.fill
                    if second is None or second < self.full_at:
                        self._emit(Log(message=(
                            f"the bar said {fill:.0%} full and a second look "
                            f"said {'nothing' if second is None else f'{second:.0%}'} "
                            f"— carrying on gathering"), source="farm"))
                        reading = again
                        continue
                    reading = again
                # A BAG CONVERTED WHERE IT STANDS GATHERS ON (a Micro-
                # Converter): what it held is booked as a Conversion Link's
                # is (`linked`), and the counter starts again from the empty
                # bag. Only mid-gather, with passes walked and time left.
                if (self.convert_in_field is not None and cycle.pattern_passes
                        and not self._stopped()
                        and self.clock() - started < self.farm_seconds
                        and (self.leave_at is None or self.clock() < self.leave_at)):
                    try:
                        emptied = bool(self.convert_in_field(reading))
                    except Exception as exc:
                        emptied = False
                        self._emit(Log(message=f"could not convert in the field: {exc}",
                                       level=Level.WARN, source="farm"))
                    if emptied:
                        after = report.count(self.hud.pollen())
                        if baseline is not None and best is not None:
                            linked += max(0, best - baseline)
                        start = after.value if after.ok else 0
                        baseline, best, best_honey = start, start, []
                        look, banked = start, gained
                        last_rise_at, rung = self.clock(), 0
                        cycle.field_converts += 1
                        reading = after
                        continue
                cycle.gather_ended = (
                    f"backpack {reading.describe()}" if cycle.pattern_passes
                    else f"arrived with the backpack already "
                         f"{reading.describe()} — turning straight round")
                break

            if self.clock() - started >= self.farm_seconds:
                cycle.gather_ended = (
                    f"hit the {self.farm_seconds:.0f}s farm cap "
                    f"(BeeTuxMacro FARM_SECONDS)")
                break
            if self.leave_at is not None and self.clock() >= self.leave_at:
                cycle.gather_ended = self.leave_why
                self._emit(Log(message=cycle.gather_ended, source="farm"))
                break

            result = self._run_route(self.pattern, every_s=CHASE_EVERY_S,
                                     between=between)
            cycle.pattern_passes += 1
            cycle.studs += result.studs
            # A PASS THE RUNNER ABANDONED (a death: act/routes `abandon`) IS
            # NOT A ROUTE THAT FAILED, and must not stop the loop the way a
            # broken pattern does. The reading below sees the death and ends
            # the trip as a death; if it cannot read, the trip ends here.
            # NOR IS A PASS THE OWNER'S TAKE OVER ENDED (act/routes
            # OWNER_TOOK): failing it here stopped the whole run, and the
            # relaunch is a rejoin of the server he is playing on. The top of
            # the loop ends the trip for it (`interrupted`) and the run goes on.
            abandoned = str(getattr(result, "abandoned", "") or "")
            if self._interrupted():
                continue
            if not abandoned:
                self._chase_a_token(cycle)
            if not result.ok and not abandoned:
                cycle.ok = False
                cycle.reason = self._route_failure(self.pattern, result)
                cycle.gather_ended = cycle.reason
                break

            reading = report.count(self.hud.pollen())
            if self.bearings is not None:
                self.bearings.saw_pollen(reading)
                # THE BACKSTOP. The journey checks the panel before handing
                # over, but a panel read can miss. If after a whole pass the
                # counter has not moved AND the compass says we are at the
                # hive, this is not a slow field: it is the hive. Stop now,
                # not 108 seconds and three recovery rungs from now.
                if (cycle.pattern_passes >= 1 and reading.ok
                        and best is not None and reading.value <= best
                        and self.bearings.at("hive") is True):
                    cycle.gather_ended = (
                        "the pattern is being walked AT THE HIVE — the compass "
                        f"says {self.bearings.describe()} — ending this trip "
                        "so the next one travels again instead of farming "
                        "the pads")
                    cycle.retravel = True
                    self._emit(Log(message=cycle.gather_ended,
                                   level=Level.WARN, source="farm"))
                    break
            if reading.ok:
                # A DEATH, SEEN FROM THE HUD. Nothing else empties a backpack
                # mid-gather: converting only happens at the hive, at the end
                # of a cycle, and this loop never goes there. The owner named
                # the cause -- "i keep dying to the mantis since im walking in
                # small radius so it jumps on me and when i die i loose all
                # pollen" -- and the collapse is the only evidence the bot
                # itself gets, because the death screen is gone by the time
                # anything asks.
                #
                # Half is a wide margin on purpose: the threshold is there to
                # ignore a single misread digit, not to tune a sensitivity.
                # Pollen only ever rises while gathering EXCEPT at a
                # Conversion Link, which turns part of the bag into honey
                # where the character stands and can fall below half too (a
                # real death was confirmed at 0.497, so no fraction tells the
                # two apart) -- so the honey decides first, by the same test
                # as brain/alive's DeathWatch (honey_says_converted).
                fell = (best is not None and best > DEATH_MIN_POLLEN
                        and reading.value < best * DEATH_DROP)
                rose = (rise_past_trickle(best_honey, self._honey_now(), self.clock())
                        if fell else None)
                # A LINK'S HONEY CAN LAG ITS FALL. MEASURED 2026-10-06 00:34: a
                # fall of 275,860 in Clover ended the trip as a death, and honey
                # stood 233,742 higher at the convert after -- the counter rolls
                # unreadably for seconds after a conversion (alive.CONVERSION_
                # HONEY_SHARE). So a fall the honey does not explain yet is
                # read again, once a second, for DEATH_CONFIRM_S: a real death
                # is back at the hive by then and loses nothing to the wait.
                # AND A DEATH EMPTIES THE BAG (DEATH_LEAVES_MAX). MEASURED
                # 2026-10-06 01:34: Conversion Links in Mushroom left 673,182
                # and 652,047 -- the character alive in every incident frame,
                # the feed reading "Honey from Conversion Link" -- and with the
                # honey unreadable behind the floating numbers this ended the
                # trip anyway. A fall that leaves legibly more is not a death.
                kept = fell and reading.value > max(DEATH_LEAVES_MAX,
                                                   LINK_KEEPS_SHARE * best)
                # AND WHERE WE ARE: a death respawns at the hive -- the compass
                # read "the hive area (spawn)" within the second on all three
                # real deaths of 2026-10-05 (15:20, 16:20, 17:06) -- and a Link
                # leaves us in the field. MEASURED 2026-10-06 02:42: a Link in
                # Cactus took 93% of the bag (515,218 -> 34,774, under any
                # leftover line; honey +376K over the trip) and ended a
                # 1,200 s trip at 140 s, the walk home then starting from the
                # field. So the wait also watches for the hive, which confirms
                # a death at once, and a fall that never sees it while the
                # game still names a field is a Link.
                at_hive = self._at_hive()
                if (fell and not kept and not at_hive
                        and not honey_says_converted(rose, best - reading.value)):
                    for _ in range(int(DEATH_CONFIRM_S)):
                        self.sleep(1.0)
                        rose = rise_past_trickle(best_honey, self._honey_now(), self.clock())
                        if honey_says_converted(rose, best - reading.value):
                            break
                        at_hive = self._at_hive()
                        if at_hive:
                            break
                field_now = (self._named_field() if fell and not kept and not at_hive
                             else None)
                honey_said = honey_says_converted(rose, (best or 0) - reading.value)
                if kept or field_now or honey_said:
                    self._emit(Log(message=(
                        f"pollen fell {best:,} -> {reading.value:,} but "
                        + (f"honey rose {rose:,} past its trickle" if honey_said else
                           f"{reading.value:,} is left, and a death leaves the bag empty"
                           if kept else
                           f"the game still names the {str(field_now).replace('_', ' ')} "
                           f"field and the compass never put us at the hive")
                        + " — a conversion in the field (a Conversion Link), not a death; "
                          "gathering on"),
                        source="farm"))
                    if baseline is not None:
                        linked += max(0, best - baseline)
                    baseline, best, best_honey = reading.value, reading.value, []
                    # the Link's fall is believed already (honey, field, what is left)
                    look = reading.value if look is None else min(look, reading.value)
                    banked = gained
                elif (best is not None and best > DEATH_MIN_POLLEN
                        and reading.value < best * DEATH_DROP):
                    cycle.deaths += 1
                    lost = best - reading.value
                    note = (f"died: pollen fell {best:,} -> {reading.value:,} "
                            f"({lost:,} lost) with no convert in between")
                    self._emit(Log(message=note, level=Level.WARN,
                                   source="farm"))
                    if self.incidents is not None:
                        self.incidents.save("death", note)
                    if self.supervisor is not None:
                        self.supervisor.check_danger(note)
                    baseline, best = reading.value, reading.value

                    # AND STOP GATHERING, because after a death this character
                    # is not in the field any more. Death respawns at the hive
                    # -- the wiki is explicit that the bees go home too -- so
                    # every remaining pass of a field pattern runs on the hive
                    # lawn, where there is nothing to collect.
                    #
                    # MEASURED, 2026-09-20: a cycle that died early reported
                    # "1,861 pollen, 341s gathering over 28 passes". Twenty-odd
                    # of those passes were walking a snake pattern around the
                    # hive. Ending the stint sends the cycle to its convert
                    # step -- which is where it already is -- and the next one
                    # travels out again, which is the only thing that helps.
                    cycle.gather_ended = (
                        f"{note}; ending this trip because a death puts the "
                        f"character back at the hive, where the pattern would "
                        f"be walked over an empty lawn")
                    self._emit(Thought(topic="farm", text=cycle.gather_ended))
                    break
                if baseline is None:
                    baseline = reading.value
                reading = book(reading)
                if best is None or reading.value > best:
                    # A FIRST READING IS NO RISE: the trip's own start could not
                    # be read, and this is where it begins (OFF_FIELD_STALL_S)
                    first = best is None
                    best, last_rise_at, rung = reading.value, self.clock(), 0
                    best_at = last_rise_at
                    seen_honey = self._honey_now()
                    if seen_honey is not None:
                        best_honey = (best_honey + [(seen_honey, self.clock())])[-2:]
                    # EVIDENCE THAT THIS TRIP IS ACTUALLY GATHERING. Until
                    # pollen has risen once, an unreadable counter is not
                    # forgiven below -- a trip with no evidence at all has no
                    # claim on the rest of the cap. See the unreadable branch.
                    rose_at_least_once = rose_at_least_once or not first
                elif (last_seen is not None and reading.value > last_seen
                        and rise_since_last_look()):
                    # UNDER THE TRIP'S BEST, BUT UP: the bag fell in the field
                    # and is refilling (RISE_SINCE_LAST_LOOK)
                    last_rise_at, rung, rose_at_least_once = self.clock(), 0, True
                    if not said_refill and last_rise_at - best_at >= self.stall_after:
                        said_refill = True
                        self._emit(Log(message=(
                            f"pollen {reading.value:,} is under this trip's best of "
                            f"{best:,} from {last_rise_at - best_at:.0f}s ago, but rose "
                            f"since the last look ({last_seen:,}) — the bag fell in "
                            f"the field and is refilling, not a flat counter "
                            f"(brain/farm RISE_SINCE_LAST_LOOK)"), source="farm"))
                last_seen = reading.value
            if abandoned:
                # The death the runner saw, when the reading above did not
                # show it: the character is at the spawn point all the same.
                cycle.gather_ended = (f"{self.pattern}: {abandoned} — ending "
                                      f"this trip")
                self._emit(Thought(topic="farm", text=cycle.gather_ended))
                break
            # THE WRONG FIELD, SEEN WHILE THERE IS STILL A TRIP TO SAVE. See
            # `wrong_field`: the caller decides, and a "leave" is carried out
            # here, at the verdict (`_go_back_out`). Out of the field, the
            # bag is gone and the character is at the hive, so the trip ends
            # with nothing to walk home or convert and the next one travels
            # again; still in it, the gather carries on.
            if self.wrong_field is not None:
                try:
                    leave = self.wrong_field(reading)
                except Exception as exc:
                    leave = None
                    self._emit(Log(message=(f"the wrong-field check failed "
                                            f"({exc}) — gathering on"),
                                   level=Level.WARN, source="farm"))
                if leave and self._go_back_out(str(leave)):
                    cycle.gather_ended = str(leave)
                    cycle.retravel = True
                    self._emit(Log(message=cycle.gather_ended,
                                   level=Level.WARN, source="farm"))
                    break
            # THE QUEST STEP THIS TRIP CAME FOR, GATHERED: home now.
            if self.quest_step_done is not None:
                try:
                    done = self.quest_step_done(reading)
                except Exception as exc:
                    done = None
                    self._emit(Log(message=(f"the quest-step check failed "
                                            f"({exc}) — gathering on"),
                                   level=Level.WARN, source="farm"))
                if done:
                    cycle.gather_ended = str(done)
                    self._emit(Log(message=cycle.gather_ended, source="farm"))
                    break
            # BACK INTO THE FLOWERS, between two passes and never inside one,
            # as Natro's drift compensation does (act/drift). A pass that
            # ended off the field would start the next one off it too.
            if (self.stay_in_field is not None and not self._stopped()
                    and not self._interrupted()):
                try:
                    steered = self.stay_in_field()
                except Exception as exc:
                    steered = None
                    self._emit(Log(message=(f"the walk back into the flowers "
                                            f"failed ({exc}) — gathering on"),
                                   level=Level.WARN, source="farm"))
                off_bed = steered is not None and not getattr(steered, "back", True)
                if steered is not None:
                    if getattr(steered, "walked", False):
                        cycle.studs += float(getattr(steered, "studs", 0.0) or 0.0)
                    self._emit(Log(message=steered.describe(), source="farm"))
            self._report_fill(reading)

            # The HUD going away is not a stall, and the ladder is the wrong
            # answer to it: jumping and turning cannot bring the world back, and
            # walking home from a disconnect dialog just presses keys at a
            # screen we cannot see. Hand it back to the loop, which waits.
            blind = blind + 1 if reading.state in (Read.NO_HUD, Read.NO_FRAME) else 0
            if blind >= self.blind_reads_allowed:
                cycle.lost_hud = True
                cycle.gather_ended = (
                    f"the HUD has been off screen for {blind} reads "
                    f"({reading.describe()}) — stopping this trip rather than "
                    f"pressing keys at a screen we cannot see")
                self._emit(Thought(topic="farm", text=cycle.gather_ended))
                break

            # A COUNTER WE COULD NOT READ IS NOT A COUNTER THAT IS FLAT.
            #
            # `last_rise_at` only moves when a reading is `ok` AND higher than
            # the best so far, so an unreadable one leaves the flat clock
            # running -- and a low-confidence read is not NO_HUD, so the blind
            # guard above does not catch it either. The stall ladder then
            # climbs to its last rung, `go_home`, and ends a trip that was
            # earning perfectly well.
            #
            # MEASURED 2026-09-22: the one trip whose pollen counter read
            # cleanly ran the full 1,200 s, gathered 476,000 pollen over 90
            # passes and earned 156,189 honey. Every trip whose counter read
            # "212?1,072,500 at confidence 0.19" ended at about 237 s over 18
            # passes for roughly 800 honey -- "recovered 2x (jump, go_home)"
            # in the cycle line, which is the ladder walking out of a field it
            # simply could not see.
            #
            # So the flat clock only runs while the counter is readable --
            # BUT ONLY ONCE THIS TRIP HAS SHOWN IT IS WORKING, and that
            # condition was missing from the first version of this fix.
            #
            # Suppressing the ladder on an unreadable counter is a claim that
            # the trip is fine really. That claim needs evidence, and a trip
            # whose counter has never once shown a rise has none: it could be
            # gathering 400 pollen a second or standing in a doorway, and
            # nothing on screen can tell the difference. So the flat clock is
            # only forgiven AFTER pollen has gone up at least once, which is
            # when "unreadable" genuinely does mean a reading problem rather
            # than an unknown trip. Before that, the old behaviour stands.
            #
            # (Not prompted by a measurement. It was prompted by one I got
            # wrong -- I read the planner's cached "carrying 53,656 pollen"
            # as a live backpack and thought a trip had stalled unnoticed for
            # eight minutes. That trip had gathered 442,156 pollen over 76
            # passes. The gate is still right, on the argument above, and it
            # only ever restores the old behaviour.)
            if not reading.ok:
                cycle.unreadable_pollen += 1
                if rose_at_least_once:
                    last_rise_at = self.clock()

            flat_for = self.clock() - last_rise_at
            # THE GAME SAID THIS IS NO FIELD: a jump or a turn does not put a
            # character into a field it missed, so with no rise yet it goes
            # home after OFF_FIELD_STALL_S, the way the ladder's last rung
            # does (run_farm's `ended_off_the_field` reads it). MEASURED
            # 2026-10-06 01:55 (run-664): the Cactus flight landed off the
            # field, the sprinkler was refused at once, and the ladder walked
            # 20 passes over 207 s for nothing.
            if cycle.off_field and not rose_at_least_once and flat_for >= OFF_FIELD_STALL_S:
                cycle.recoveries.append(Rung.GO_HOME.value)
                report.recoveries += 1
                cycle.gather_ended = (f"{FLAT_COUNTER} for {flat_for:.0f}s after "
                                      f"{cycle.off_field} — going home rather than "
                                      f"gathering off the field")
                self._emit(Thought(topic="farm", text=cycle.gather_ended))
                break
            stuck = stuck_off_the_flowers(off_bed, flat_for,
                                          jumped=stuck_jumped == last_rise_at)
            if stuck == Rung.GO_HOME:
                cycle.recoveries.append(Rung.GO_HOME.value)
                report.recoveries += 1
                cycle.gather_ended = (f"{FLAT_COUNTER} for {flat_for:.0f}s off the "
                                      f"flowers, and the walk back did not find "
                                      f"them — going home with the bag rather than "
                                      f"standing off the field (brain/farm STUCK_FLAT_S)")
                self._emit(Thought(topic="farm", text=cycle.gather_ended))
                break
            if stuck == Rung.JUMP:
                stuck_jumped = last_rise_at
                cycle.recoveries.append(Rung.JUMP.value)
                report.recoveries += 1
                self._emit(Thought(topic="farm", text=(
                    f"{FLAT_COUNTER} for {flat_for:.0f}s off the flowers — jump "
                    f"(home at {STUCK_FLAT_S:.0f}s if it stays flat)")))
                self._recover(Rung.JUMP)
            if flat_for >= self.stall_after:
                if self.supervisor is not None:
                    self.supervisor.diagnose_stall(
                        f"{flat_for:.0f}s flat at {reading.describe()}")
                if not self._stall(cycle, report, reading, flat_for, rung):
                    break
                rung += 1
                last_rise_at = self.clock()   # give the recovery its own window

        cycle.gather_seconds = self.clock() - started
        if baseline is not None and best is not None:
            cycle.pollen_gathered = linked + max(0, best - baseline)
            if POLLEN_BOOKING == "on":
                seen_in = banked if cycle.deaths else gained
                cycle.pollen_refilled = max(0, seen_in - cycle.pollen_gathered)
                cycle.pollen_gathered += cycle.pollen_refilled
        self._emit(TaskUpdate(
            name="gather", status="done" if cycle.ok else "failed",
            progress=1.0 if cycle.ok else -1.0,
            detail=f"{cycle.gather_ended}; "
                   + (f"{cycle.pollen_gathered:,} pollen gathered"
                      if cycle.pollen_gathered is not None
                      else "pollen never read, so nothing is claimed")))

    def _report_fill(self, reading: Reading) -> None:
        """Say what the backpack reads -- including when it does not read.

        Progress -1 is the event protocol's "indeterminate", and it is the
        honest value for a counter we could not read: the fill is not 0, it is
        unknown. A 0 on that bar looks exactly like an empty backpack, which is
        the conflation this whole module exists to avoid.
        """
        fill = reading.fill
        self._emit(TaskUpdate(name="gather", status="running",
                              progress=fill if fill is not None else -1.0,
                              detail=reading.describe()))
        if fill is not None:
            self._emit(Metric(name="backpack_fill", value=fill * 100.0,
                              unit="%"))

    def _stall(self, cycle: Cycle, report: Report, reading: Reading,
               flat_for: float, rung: int) -> bool:
        """Take one recovery step. False means the gather must end now."""
        report.stalls += 1
        why = ("the pollen counter has been unreadable"
               if not reading.ok else FLAT_COUNTER)
        detail = (f"{why} for {flat_for:.0f}s. Last read: "
                  f"{reading.describe()}. The ladder is "
                  f"{', '.join(r.value for r in self.ladder)}, escalating "
                  f"rather than repeating (nav/recovery.py's rule).")

        if rung >= len(self.ladder):
            cycle.gather_ended = (f"{why} for {flat_for:.0f}s and every recovery "
                                  f"step has been tried")
            self._emit(Thought(topic="farm", text=cycle.gather_ended,
                               detail=detail))
            return False

        ladder = self._ladder_here()
        if rung >= len(ladder):
            cycle.gather_ended = (f"{why} for {flat_for:.0f}s and every recovery "
                                  f"step has been tried")
            self._emit(Thought(topic="farm", text=cycle.gather_ended,
                               detail=detail))
            return False
        step = ladder[rung]
        cycle.recoveries.append(step.value)
        report.recoveries += 1
        self._emit(Thought(topic="farm",
                           text=f"{why} for {flat_for:.0f}s — {step.value}",
                           detail=detail))
        if step is Rung.GO_HOME:
            cycle.gather_ended = (f"{why} for {flat_for:.0f}s — going home "
                                  f"rather than gathering into a wall")
            return False
        self._recover(step)
        return True

    def _at_hive(self) -> bool:
        """The compass puts us at the hive (a death's respawn), on evidence."""
        if self.bearings is None:
            return False
        try:
            return self.bearings.at("hive") is True
        except Exception:
            return False

    def _named_field(self) -> str | None:
        """The field the game's own feed names us in now, or None."""
        if self.bearings is None:
            return None
        try:
            here = self.bearings.in_field()
        except Exception:
            return None
        return here if isinstance(here, str) and here else None

    def _ladder_here(self) -> Sequence[Rung]:
        """The recovery ladder, given what the compass says about WHERE we are.

        THE OWNER'S POINT, 2026-09-21: "all its doing is literally turning by 1
        and jumping once if its not getting anything ... which wont help if its
        in the wrong area to begin with". Jump and turn fix a character stuck
        on terrain. A character standing on the hive pads is not stuck; it is
        in the wrong place, and the only rung that helps is the one that gets
        it home and sends the next trip out again -- immediately, not after
        two more stalls.

            at the hive / at a landmark   GO_HOME straight away
            in a field                    the full ladder; this is a real stall
            no idea                       JUMP once, then GO_HOME
        """
        if self.bearings is None:
            return self.ladder
        try:
            here = self.bearings.in_field()
            at_hive = self.bearings.at("hive")
        except Exception:
            return self.ladder
        if at_hive is True or here is False:
            return (Rung.GO_HOME,)
        if here:                                   # a named field, or True
            return self.ladder
        return (Rung.JUMP, Rung.GO_HOME)

    def _recover(self, step: Rung) -> None:
        """The physical half of a recovery. Two keys, both taps, never a hold."""
        if step is Rung.JUMP:
            self.vin.tap("space")                  # obstacles here are ankle height
        elif step is Rung.TURN:
            # One tap is 45 degrees, MEASURED by closure (act/orient.py). The
            # camera is the steering wheel: every movement key is relative to it.
            self.vin.tap(CAMERA_KEYS["right"])
            # ...and the compass is told, so the next recorded route squares
            # up first instead of running 45 degrees wrong.
            if self.bearings is not None:
                self.bearings.turned(1)
        self.sleep(SETTLE_SECONDS)

    def _convert(self, cycle: Cycle, report: Report) -> None:
        """Stand on the hive and turn pollen into honey, watching it happen.

        BeeTuxMacro presses `e` and sleeps CONVERT_TIME (stuff/utils.sh). That
        is fine when a human placed the character; it is not fine unattended,
        because it cannot tell converting from standing next to a hive that is
        not yours. The owner's correction is that there is no fixed slot -- you own
        a hive only once you have claimed an empty one -- so the confirmation
        has to come from the game: a conversion makes the pollen counter FALL.
        """
        honey_before = self.hud.honey()
        pollen_before = report.count(self.hud.pollen())
        cycle.bag_at_convert = pollen_before.value if pollen_before.ok else None
        self._emit(TaskUpdate(name="convert", status="running", progress=-1.0,
                              detail=f"pollen {pollen_before.describe()}"))

        nothing_to_convert = pollen_before.ok and pollen_before.value == 0
        if pollen_before.state in (Read.NO_HUD, Read.NO_FRAME):
            cycle.lost_hud = True
            cycle.convert_note = (
                f"{pollen_before.describe()} at the hive — pressing nothing. "
                f"The only keys that do anything on those screens are the ones "
                f"this project refuses to press blind")
            self._emit(Thought(topic="farm", text=cycle.convert_note))
        elif nothing_to_convert:
            cycle.convert_note = ("the backpack read 0/… — nothing to convert. "
                                  "This is an EMPTY backpack, not an unreadable one")
            self._emit(Thought(topic="farm", text=cycle.convert_note))
        else:
            pressed_at = self.clock()
            start = self._convert_dwell(cycle, report, pollen_before, honey_before)
            # The pad's prompt hid the counter before the press
            # (BASELINE_READS); the dwell's read just after it is the start.
            if not honey_before.ok and start is not None:
                honey_before = start
            if honey_before.ok:
                # the balance AT the press, stamped with the press's time
                report.honey_marks.append((pressed_at, honey_before.value))

        # Honey is measured across the WHOLE phase, including the path where
        # there was nothing to convert. Two reasons: tokens picked up on the way
        # home move the counter too, and a cycle that reports "honey: unknown"
        # when the counter was perfectly readable is as dishonest as one that
        # reports a number it never read.
        honey_after = self.hud.honey()
        if cycle.left_at_empty:
            # A READ NOW READS SHORT: the counter is still rolling. MEASURED
            # run-560 18:45:56: +4,670,254 read as the bot left the empty bag,
            # against +5,057,960 once it settled. So none is claimed.
            cycle.honey_note = (
                "honey not measured: the convert left at the empty bag with "
                "the counter still rolling (gather.leave_at_empty_bag) — "
                f"every {LEAVE_CALIBRATE_EVERY}th convert waits and measures it")
        elif honey_before.ok and honey_after.ok:
            delta = honey_after.value - honey_before.value
            # HONEY DOES NOT GO DOWN during a cycle. It rises on a convert and
            # on tokens picked up walking home, and nothing in a cycle spends
            # it. So a negative delta is not a loss, it is a MISREAD -- and a
            # large one is a badly misread leading digit.
            #
            # MEASURED, which is why this guard exists: a live cycle reported
            # "-16,336,006 honey", i.e. it read 16,336,006 before and
            # approximately nothing after. Reporting that as a measurement
            # would put a fabricated number into the night's totals, and this
            # loop's whole claim is that every number it prints is a reading.
            if delta < 0:
                cycle.honey_note = (
                    f"honey read {honey_before.value:,} then "
                    f"{honey_after.value:,}, which would be a loss of "
                    f"{-delta:,} — honey never falls during a cycle, so that "
                    f"is a misread and no honey is claimed for this trip")
                report.count(Reading(Read.UNREADABLE, None, None))
            else:
                cycle.honey_earned = delta
                # Only a MEASURED delta is published. This emit used to sit
                # outside the else, so the misread branch above -- which the
                # comment says was seen live, reading -16,336,006 -- reached
                # float(None) and raised TypeError out of the whole farm loop,
                # ending the run and costing a full game relaunch. A reading
                # we have just refused to believe is not a metric.
                self._emit(Metric(name="honey_earned",
                                  value=float(cycle.honey_earned),
                                  unit="honey"))
        else:
            cycle.honey_note = (
                f"honey not measured: before {honey_before.describe()}, "
                f"after {honey_after.describe()}")

        settled = cycle.converted or nothing_to_convert
        self._emit(TaskUpdate(
            name="convert", status="done" if settled else "failed",
            progress=1.0 if settled else -1.0,
            detail=cycle.convert_note + (f"; {cycle.honey_note}"
                                         if cycle.honey_note else "")))

        # THE ERRAND HOOK LIVES HERE, at the end of the whole convert step,
        # and not in the dwell's "honey settled" branch where it was first
        # written. MEASURED 2026-09-23 01:48: that cycle banked +1,141,497
        # honey and never took the settle branch -- the dwell can also end on
        # the pollen counter falling, or on its own timeout with the honey
        # measured afterwards -- so the errand never ran.
        #
        # `cycle.converted` IS THE WHOLE CONDITION, AND A HONEY RISE IS NOT.
        # It used to be `converted or honey_earned > 0`, and honey rises on
        # its own: the hive makes a trickle from the bees whatever the
        # character is doing. MEASURED 2026-09-23 04:04 (attempt 292): the
        # walk home failed ("turned a full circle and never saw the hive's
        # yellow wall"), the convert correctly REFUSED to press E because
        # nothing confirmed a hive in front of the character -- and the
        # errand ran anyway, announcing "the backpack is empty and we are on
        # our own pad" while standing in a field with a full one, and walked
        # `natro_out_bucko_bee` from the wrong place.
        #
        # The errand's whole premise is "the bag is empty and we are on our
        # own pad". Only a confirmed convert establishes both. The trickle
        # establishes neither.
        if errand_is_safe(cycle):
            self._after_convert(cycle)

    def _leave_at_empty(self) -> bool:
        if self.leave_at_empty is None:
            return False
        try:
            return bool(self.leave_at_empty())
        except Exception:
            return False

    def _convert_dwell(self, cycle: Cycle, report: Report,
                       pollen_before: Reading,
                       honey_before: Reading) -> Reading | None:
        """Press E and watch the counter, rather than trusting the clock.
        Returns the honey reading the convert started from (see `_dwell`),
        None when nothing was pressed or it never read."""
        if self.confirm_hive is not None:
            try:
                at_hive = self.confirm_hive()
            except Exception as exc:
                at_hive = False
                cycle.convert_note = f"could not check for the hive: {exc}"
            seen = getattr(at_hive, "text", None)
            if not bool(getattr(at_hive, "ok", at_hive)):
                cycle.convert_note = (
                    "refused to press E: nothing confirmed a hive in front of "
                    "the character"
                    + (f" (the screen said {seen!r})" if seen else "")
                    + ". E is the interact key for everything — a blind press "
                      "here has already opened a Polar Bear quest dialogue.")
                self._emit(TaskUpdate(name="convert", status="failed",
                                      detail=cycle.convert_note))
                # A TaskUpdate reaches the GUI and nothing else. The live run
                # of 2026-09-21 19:09 reported "+0 honey" from a convert and
                # the log had no line saying why; this is that line.
                self._emit(Log(message=f"convert: {cycle.convert_note}",
                               level=Level.WARN, source="farm"))
                return None
        self.converting(True)
        try:
            return self._dwell(cycle, report, pollen_before, honey_before)
        finally:
            self.converting(False)
            self._say_trail()

    def _say_trail(self) -> None:
        """The dwell's counters as one line: seconds after E, the bag, the
        honey ('-' where a counter did not read). See `convert_trail`."""
        trail = getattr(self, "convert_trail", None) or []
        if not trail:
            return
        def num(v):
            return "-" if v is None else f"{v:,}"
        try:
            self._emit(Log(message="convert trail (s after E: bag / honey): " + "; ".join(
                f"{t:.0f}: {num(bag)} / {num(honey)}" for t, bag, honey in trail),
                source="farm"))
        except Exception:
            pass

    def _dwell(self, cycle: Cycle, report: Report,
               pollen_before: Reading,
               honey_before: Reading) -> Reading | None:
        """The convert itself, once a hive has been confirmed underfoot.

        WHAT THE HUD ACTUALLY DOES, MEASURED 2026-09-21 (scripts/diag_convert
        .py, 88,322 pollen, half-second reads for 25 s after pressing E):

            +0.6 s   pollen reads 0            -- the backpack empties at once
            +6 s     panel: "To Make Honey, Collect Pollen"
            +6.5 s   honey UNREADABLE          -- the counter is rolling
            +11.8 s  honey settles at +92,794  -- ten seconds after the press

        The previous version of this loop returned the moment pollen read 0,
        `_convert` read the honey counter two seconds after the press, and the
        cycle reported "+0 honey". Worse: the next cycle's route walked the
        character off the pad a second later, and stepping off returns the
        unconverted pollen to the backpack. The same 88,322 pollen survived
        three consecutive "converts" that way. The honey exists only once the
        counter has risen and stopped moving, so that is what this waits for.

        Exit conditions, in order of preference:
          1. honey readable, higher than at the start, and unchanged for two
             reads (settled) -- CONVERTED, and the delta is real
          2. the ceiling `convert_seconds` -- CONVERTED only when the backpack
             emptied and still reads empty (the amount is then unknown), and
             reported as such
          3. the counter never moved after several presses -- not our hive

        The start is `honey_before` when it read, else the read taken at once
        after the press (BASELINE_READS), which is returned so `_convert` can
        measure the delta from it.
        """
        if self.vin.tap("e") is False:    # BeeTuxMacro convert(): `e` at the hive
            # HELD BACK BY THE OWNER'S PAUSE OR TAKE OVER (brain/controls
            # STALE_AFTER_A_WAIT): `confirm_hive` looked before it, so this
            # convert ends unpressed rather than watch a counter and press E
            # again, unconfirmed, wherever he left the character. The bag is
            # still full, so the next cycle plans the convert afresh.
            cycle.convert_note = ("the convert's E was held back by the "
                                  "owner's Pause or Take Over — nothing pressed")
            self._emit(Log(message=f"convert: {cycle.convert_note}",
                           level=Level.WARN, source="farm"))
            return None
        started = self.clock()
        # `honey_before` is the reading `_convert` took before anything was
        # pressed -- ONE read, passed down, so the settle test compares
        # against the true starting value rather than a second read taken
        # once the counter may be rolling. When the pad's prompt hid it
        # (BASELINE_READS), the reads at once after the press stand in.
        honey_start = honey_before if honey_before.ok else None
        for n in range(BASELINE_READS if honey_start is None else 0):
            if n:
                self.sleep(BASELINE_GAP)
            first = self.hud.honey()
            if first.ok:
                honey_start = first
                break
        self._emit(Log(message=(
            f"convert: pressed E on the pad with {pollen_before.describe()} — "
            f"watching the counter; honey "
            + (honey_before.describe() if honey_before.ok else
               f"{honey_start.describe()} (read after the press: before it, "
               f"{honey_before.describe()})" if honey_start is not None else
               f"never read (before the press, {honey_before.describe()})")),
            source="farm"))
        prompts = 1
        moved = False                     # pollen ever fell
        flat_reads = 0
        emptied_at = None                 # when pollen first read 0
        bag_empty = False                 # the latest reading, digits or bar
        honey_last = None                 # the last readable value above the start
        honey_same = 0
        honey_seen = None                 # the last readable value at all
        # WHAT THE TWO COUNTERS DID, poll by poll (`convert_trail`), for the
        # question the dwell's length turns on: once the bag reads empty, is
        # the honey still to come, or only still being drawn? ~18 s of every
        # trip is spent waiting for it to settle.
        self.convert_trail = trail = []
        self._dwells += 1
        empties = 0                       # empty reads running (LEAVE_EMPTY_POLLS)

        while True:
            if self._stopped():
                cycle.convert_note = "stop requested during the convert dwell"
                return honey_start
            elapsed = self.clock() - started
            if elapsed >= self.convert_seconds:
                # THE BAG IS WHAT AN ERRAND NEEDS, AND IT IS MEASURED. The
                # ceiling used to end every convert unconfirmed, and with the
                # start unreadable (BASELINE_READS) that was all of them. A
                # backpack that fell to empty after E on a confirmed pad, and
                # still reads empty 100 s later, is converted: the pollen went
                # into the hive, and the character never left it. Only the
                # amount is unknown, and the note says so.
                if emptied_at is not None and bag_empty:
                    cycle.converted = True
                    cycle.convert_note = (
                        f"converted — the backpack emptied "
                        f"{emptied_at - started:.0f}s after the press and still "
                        f"read empty at the {self.convert_seconds:.0f}s "
                        f"ceiling; the honey counter "
                        + (f"last read {honey_seen:,} and "
                           if honey_seen is not None else "")
                        + ("never settled above its start"
                           if honey_start is not None else
                           "never read its start")
                        + ", so how much it credited is not measured")
                    return honey_start
                cycle.convert_note = (
                    f"the {self.convert_seconds:.0f}s convert dwell elapsed"
                    + (" with the backpack refilled after emptying — whether "
                       "it all credited is unknown"
                       if emptied_at is not None else
                       " without the pollen counter ever falling")
                    if (flat_reads or moved) else
                    f"the {self.convert_seconds:.0f}s convert dwell elapsed "
                    "without a single readable pollen counter, so whether it "
                    "converted is unknown")
                return honey_start

            self.sleep(self.poll_seconds)
            reading = report.count(self.hud.pollen())
            try:
                seen_now = self.hud.honey() if emptied_at is None else None
                trail.append((self.clock() - started,
                              reading.value if reading.ok else None,
                              seen_now.value if seen_now is not None and seen_now.ok
                              else None))
            except Exception:
                pass
            if reading.ok:
                bag_empty = reading.value == 0
            elif reading.bar_fill is not None:
                bag_empty = reading.bar_fill <= BAR_EMPTY
            if reading.ok and pollen_before.ok:
                if reading.value < pollen_before.value:
                    moved = True
                    done = 1.0 - (reading.value / max(1, pollen_before.value))
                    self._emit(TaskUpdate(name="convert", status="running",
                                          progress=done,
                                          detail=reading.describe()))
                else:
                    flat_reads += 1
                if reading.value == 0 and emptied_at is None:
                    emptied_at = self.clock()
                    self._emit(Thought(topic="farm", text=(
                        "convert: the backpack emptied — waiting for the honey "
                        "counter to catch up (MEASURED ~10 s)")))
            # THE BAR WATCHES THE CONVERT WHEN THE DIGITS CANNOT.
            #
            # This dwell only ever read the digits, and the digits are
            # illegible at seven figures (DESIGN 8aq) -- which is exactly when
            # a convert happens, because the backpack is full. MEASURED
            # 2026-09-23 05:19 (attempt 297): the convert fired on the BAR
            # ("the bar looks 93% full"), pressed E, banked **1,117,190
            # honey**, and then reported "the convert dwell elapsed without a
            # single readable pollen counter, so whether it converted is
            # unknown". `cycle.converted` stayed False, the ledger recorded a
            # convert it could not confirm, and every errand gated on a
            # confirmed convert (8aw, 8bq) was skipped -- including the two
            # quest hand-ins that were waiting.
            #
            # The planner already falls back to the bar for exactly this
            # (8as). So does this now: the bar's own zero is what "empty"
            # looks like, validated at 100.0/95.0/27.5/4.1/0.0% against known
            # frames (vision/screenstate.pollen_bar_fill).
            elif reading.bar_fill is not None:
                before_bar = getattr(pollen_before, "bar_fill", None)
                if before_bar is not None and reading.bar_fill < before_bar - BAR_MOVED:
                    moved = True
                    self._emit(TaskUpdate(
                        name="convert", status="running",
                        progress=max(0.0, 1.0 - reading.bar_fill / max(1e-6, before_bar)),
                        detail=f"the bar is down to {reading.bar_fill:.0%}"))
                else:
                    flat_reads += 1
                if reading.bar_fill <= BAR_EMPTY and emptied_at is None:
                    emptied_at = self.clock()
                    moved = True
                    self._emit(Thought(topic="farm", text=(
                        f"convert: the bar is down to {reading.bar_fill:.0%}, "
                        f"which is empty — the counter never read, so this is "
                        f"the bar's word for it")))

            # LEAVING AT THE EMPTY BAG (gather.leave_at_empty_bag). MEASURED
            # 2026-10-01 over runs 555-557's 30 converts: the bag reads empty
            # 18-19 s after E and the honey settles 4-9 s later (median 5 s).
            # And that honey arrives whether or not the bot stays: three
            # converts left at the empty bag (run-560, 18:30-18:46) read 1.374,
            # 1.378 and 1.371 honey a pollen on the walk to the cannon, against
            # 1.305-1.422 (median 1.334) over 34 that waited. Every
            # LEAVE_CALIBRATE_EVERY-th convert still waits -- the loop's first
            # among them -- so the honey is measured on it
            # (`cycle.left_at_empty` says which did not).
            empties = empties + 1 if bag_empty else 0
            # A CALIBRATING CONVERT WITH NO STARTING HONEY MEASURES NOTHING: the
            # settle test below compares against `honey_start`, and without it
            # waits out the whole dwell. MEASURED run-565 cycle 5 (22:52:20):
            # the counter read '????,6?????,????0?' before the press, the bag
            # was empty at 11 s and the honey steady from 16 s, and the dwell
            # stood on the pad until 100 s. It leaves at the empty bag like the
            # others, and hands the measuring to the next convert.
            calibrating = (self._dwells - 1) % LEAVE_CALIBRATE_EVERY == 0
            if (emptied_at is not None and empties >= LEAVE_EMPTY_POLLS
                    and self._leave_at_empty()
                    and (not calibrating or honey_start is None)):
                cycle.converted = True
                cycle.left_at_empty = True
                if calibrating:
                    self._dwells -= 1          # the next convert measures
                cycle.convert_note = (
                    f"converted — the backpack emptied {emptied_at - started:.0f}s "
                    f"after the press; left without waiting for the honey "
                    f"counter to settle (gather.leave_at_empty_bag"
                    + ("; this was the convert to measure it, and the honey did "
                       "not read before the press, so the next one measures"
                       if calibrating else "") + ")")
                return honey_start

            # THE HONEY IS THE PROOF. Once the backpack has emptied, watch the
            # honey counter: it is unreadable while it rolls and readable once
            # it lands. Two identical readable values above the starting one
            # is "landed".
            if emptied_at is not None:
                honey = self.hud.honey()
                if trail:
                    t0, bag0, _ = trail[-1]
                    trail[-1] = (t0, bag0, honey.value if honey.ok else None)
                if honey.ok:
                    honey_seen = honey.value
                if (honey.ok and honey_start is not None
                        and honey.value > honey_start.value):
                    if honey_last is not None and honey.value == honey_last:
                        honey_same += 1
                    else:
                        honey_same = 0
                    honey_last = honey.value
                    if honey_same >= 1:
                        cycle.converted = True
                        cycle.convert_note = (
                            f"converted — honey settled at {honey.value:,} "
                            f"({honey.value - honey_start.value:+,}) "
                            f"{self.clock() - started:.0f}s after the press")
                        return honey_start

            # Only conclude "the press did nothing" from readings that actually
            # showed nothing happening. Concluding it from a counter we could
            # not read would be the same mistake as calling an unreadable
            # backpack empty.
            if (not moved and flat_reads
                    and self.clock() - started
                    >= self.convert_confirm_seconds * prompts):
                if prompts >= self.convert_prompts:
                    cycle.convert_note = (
                        f"pressed E {prompts}x at the hive and the pollen "
                        f"counter never moved in "
                        f"{self.clock() - started:.0f}s — this is not a hive we "
                        f"own, or the prompt is not there")
                    self._emit(TaskUpdate(name="convert", status="failed",
                                          detail=cycle.convert_note))
                    self._emit(Log(message=f"convert: {cycle.convert_note}",
                                   level=Level.WARN, source="farm"))
                    return honey_start
                self.vin.tap("e")
                prompts += 1

    def _chase_a_token(self, cycle) -> None:
        """One token detour between passes, if the owner asked for them.

        Anything at all going wrong here is logged and swallowed. A detour is a
        bonus on top of the pattern; a gathering run must never end because the
        token detector had a bad frame.
        """
        if self.chase is None or self._stopped():
            return
        # ONLY IN A FIELD. The live run of 2026-09-21 chased twenty "tokens"
        # standing on the hive pads: the detector fires on the bees' eyes and
        # the white pads, and the owner saw exactly what that was -- "it just
        # accidently walked into them because its trying to farm the spawn
        # area". If the compass cannot put us in a field, no detour.
        if self.bearings is not None and not self.bearings.in_field():
            return
        try:
            result = self.chase()
        except Exception as exc:
            self._emit(Log(message=f"token chase failed, carrying on: {exc}",
                           level=Level.WARN, source="chase"))
            return
        if result is None:
            return
        if not getattr(result, "walked", False):
            return
        cycle.tokens_chased += 1
        cycle.studs += float(getattr(result, "studs", 0.0)) * 2
        self._emit(Log(message=result.describe(), source="chase"))

        # ---- TAKE THE NEXT ONE WHILE IT IS STILL WORTH IT ----------------
        #
        # THE OWNER, 2026-09-23, on what to build: "higher capture rate".
        # MEASURED over 1,587 chases: the median frame has **16 tokens in
        # view** and the detour took exactly one of them before going back to
        # the pattern. The chase itself is not the problem -- 498 of 533
        # chases walked onto their token, 93% -- it simply only ever got one
        # turn per pattern pass.
        #
        # So it gets more turns. `self.chase()` picks the best token on the
        # frame it is looking at and REFUSES when nothing is worth walking to
        # ("hold — at the anchor and nothing worth walking to"), so the chain
        # stops itself as soon as the field is picked clean; the cap is only
        # there so one rich frame cannot eat a whole pattern pass. Each link
        # is at most four steps, so three links is about 120 studs against
        # the pattern's 231.
        for _ in range(max(0, CHASE_CHAIN - 1)):
            if self._stopped():
                return
            try:
                more = self.chase()
            except Exception as exc:
                self._emit(Log(message=f"token chase failed, carrying on: {exc}",
                               level=Level.WARN, source="chase"))
                return
            if more is None or not getattr(more, "walked", False):
                return
            cycle.tokens_chased += 1
            cycle.studs += float(getattr(more, "studs", 0.0)) * 2
            self._emit(Log(message=f"and again: {more.describe()}",
                           source="chase"))

    def _run_route(self, name: str, every_s: float = 0.0, between=None) -> RouteResult:
        """Run one route, abortable between steps. See the class docstring.
        `between`, when given, runs between steps every `every_s` seconds
        (CHASE_EVERY_S), never inside itself."""
        hookable = hasattr(self.routes, "on_step")
        previous = getattr(self.routes, "on_step", None)
        offer = {"at": self.clock(), "busy": False}

        def hook(op, step):
            if callable(previous):
                previous(op, step)
            if self._stopped():
                raise _StopRequested(name)
            if (between is not None and every_s > 0 and not offer["busy"]
                    and self.clock() - offer["at"] >= every_s):
                offer["busy"] = True
                try:
                    between()
                finally:
                    offer["busy"] = False
                    offer["at"] = self.clock()

        if hookable:
            self.routes.on_step = hook
        try:
            return self.routes.run(name)
        except _StopRequested:
            # The abort unwinds through RouteRunner's `held()` blocks, which
            # release as they go; this is the belt to that braces.
            self.vin.release_all()
            return RouteResult(name, ok=False, reason="stop requested mid-route")
        except _BagFull as full:
            self.vin.release_all()
            self._emit(Log(message=(f"the bag read {full} between two steps of {name} "
                                    f"— the pass ends here (brain/farm FULL_MID_PASS)"),
                           source="farm"))
            return RouteResult(name, ok=True, reason=f"the bag read {full} mid-pass")
        finally:
            if hookable:
                self.routes.on_step = previous

    def _route_failure(self, name: str, result: RouteResult) -> str:
        if self._stopped():
            return "stop requested"
        return f"{name}: {result.reason or 'the route did not finish'}"

    def _wait_for_hud(self, report: Report) -> bool:
        """Is the world on screen? Waits for a join, never presses anything.

        There is no key that fixes "not in the game" -- Escape opens the menu
        carrying Leave, and Return on it is the keystroke this project is most
        careful about. So this waits, and if the HUD does not come back it says
        so and the loop stops.
        """
        reading = report.count(self.hud.pollen())
        if reading.state not in (Read.NO_HUD, Read.NO_FRAME):
            return True

        self._emit(Thought(
            topic="farm",
            text=f"{reading.describe()} — waiting up to "
                 f"{self.hud_wait_seconds:.0f}s for the world",
            detail="A measured join through the app's own server browser "
                   "reached the world in 39.5 s (docs/DESIGN.md 8a). Nothing is "
                   "pressed while waiting: Escape opens the menu that carries "
                   "Leave."))
        # FRAMES OF THE WAIT (ROADMAP A25): run-1023 22:57 waited a minute
        # without the HUD after a Glitter use, stopped, and kept nothing to
        # say why. One folder, a frame at each of HUD_MISSING_MARKS.
        folder = f"{time.strftime('%Y%m%d-%H%M%S')}-hud-missing"
        marks = list(HUD_MISSING_MARKS)
        began = self.clock()
        deadline = began + self.hud_wait_seconds
        while True:
            waited = self.clock() - began
            while marks and waited >= marks[0]:
                self._keep_hud_frame(folder, marks.pop(0), reading)
            if self.clock() >= deadline:
                return False
            if self._stopped():
                return False
            self.sleep(self.poll_seconds)
            reading = report.count(self.hud.pollen())
            if reading.state not in (Read.NO_HUD, Read.NO_FRAME):
                return True

    def _keep_hud_frame(self, folder: str, mark: float, reading) -> None:
        if self.incidents is None:
            return
        try:
            kept = self.incidents.keep_newest(
                folder, f"t+{mark:02.0f}s",
                note=f"hud-missing: {reading.describe()} — a frame at each of "
                     f"{', '.join(f'+{m:g}s' for m in HUD_MISSING_MARKS)} "
                     f"while waiting up to {self.hud_wait_seconds:.0f}s for "
                     f"the world (ROADMAP A25)")
        except Exception:
            kept = None
        if kept is not None:
            self._emit(Log(message=f"no HUD: kept the frame at +{mark:g}s "
                                   f"({kept})", source="farm"))

    def _report_cycle(self, cycle: Cycle, report: Report) -> None:
        if self.on_cycle is not None:
            # WRITING THE TRIP DOWN MUST NOT END THE TRIP. Whatever this hook
            # does -- a file, a socket -- it is bookkeeping, and bookkeeping
            # that raises would cost the honey it was recording.
            try:
                self.on_cycle(cycle)
            except Exception as exc:
                self._emit(Log(message=f"could not record the trip ({exc})",
                               level=Level.WARN, source="farm"))
        self._emit(Thought(topic="farm", text=cycle.describe(),
                           detail=f"{cycle.gather_ended}. {cycle.convert_note}"
                                  + (f" {cycle.honey_note}" if cycle.honey_note
                                     else "")))
        self._emit(Metric(name="cycles", value=float(report.cycles_done),
                          unit="cycles"))
        if cycle.pollen_gathered is not None:
            self._emit(Metric(name="pollen_gathered",
                              value=float(cycle.pollen_gathered), unit="pollen"))

    def _stopped(self) -> bool:
        return self.stop is not None and self.stop.is_set()

    def _go_back_out(self, why: str) -> bool:
        """Leave a field `wrong_field` said is not worth staying in, now: the
        swing off, then `go_back_out()`. True once the character is out of it;
        False, with the swing back on, when it still stands in it and the
        gather carries on. `why` is the verdict, said either way.

        CARRIED OUT HERE, AT THE VERDICT, and not left to what follows the
        gather. The next trip's route guard cannot do it: it respawns only
        when it can prove the character is off the pad, and its one panel look
        was at arrival and the feed has invalidated it since (world/bearings
        `saw_feed`), so `on_my_pad()` reads None and the route out was walked
        from inside this field (review of 2026-09-26, checked with the real
        Bearings and Journey 22 s after arrival). And the walk home and
        convert that follow a gather are no fallback either: a leave refused
        there walked home from the wrong field, which from a starter field is
        a rejoin (DESIGN 8dd). The swing comes off first: see `_swing`.
        """
        if self.go_back_out is None:
            self._emit(Thought(topic="farm", text=(
                f"{why} — but nothing here can go back out, so staying")))
            return False
        self._swing(False)
        try:
            out = bool(self.go_back_out())
        except Exception as exc:
            out = False
            why += f" — but going back out failed ({exc})"
        if not out and not (self._stopped() or self._interrupted()):
            # (After a stop or a Take Over the top of the gather ends the
            # trip, so the swing is not put back on for it.)
            self._swing(True)
            self._emit(Thought(topic="farm", text=(
                f"{why} — the respawn did not go through and the character is "
                f"still in this field, so staying")))
        return out

    def _honey_now(self) -> int | None:
        """The honey figure, or None when it cannot be read."""
        try:
            return getattr(self.hud.honey(), "value", None)
        except Exception:
            return None

    def _interrupted(self) -> bool:
        """See `interrupted`. A predicate that fails counts as not."""
        if self.interrupted is None:
            return False
        try:
            return bool(self.interrupted())
        except Exception:
            return False

    def _emit(self, event) -> None:
        """Telemetry must never be able to end the night.

        Failures are counted rather than swallowed silently, so `report`
        can say the GUI link was broken instead of implying it was quiet.
        """
        if self.emit is None:
            return
        try:
            self.emit(event)
        except Exception:
            self._telemetry_errors = getattr(self, "_telemetry_errors", 0) + 1

    @property
    def telemetry_errors(self) -> int:
        return getattr(self, "_telemetry_errors", 0)

    # ---- what it is about to do, in words --------------------------------
    def _opening_line(self) -> str:
        return (f"farming {' then '.join(self.out_routes)}, converting at "
                f"{self.full_at:.0%} of the backpack")

    def _plan(self) -> str:
        return (f"out: {' then '.join(self.out_routes)} · pattern: "
                f"{self.pattern} · home: {' then '.join(self.home_routes)} · "
                f"cap {self.farm_seconds:.0f}s · convert dwell "
                f"{self.convert_seconds:.0f}s · stall after "
                f"{self.stall_after:.0f}s flat")
