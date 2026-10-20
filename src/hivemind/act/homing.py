"""Walk to YOUR hive by looking, not by timing.

THE OWNER NAMED THE FLAW. Watching the bot all day on 2026-09-22: it found
the target once and then ran a fixed movement, so anything that knocked the
player off course wasted the whole walk; it needs to keep looking and lining
the player up. They are right,
and the measurement agrees with them: the recorded walk home reached the hive
**0 times in 52 attempts**, and every bank the project has ever made came from
rejoining the server instead.

A recorded route is open-loop -- hold these keys for these seconds and hope.
This is closed-loop: look, correct, step, look again. Nothing here is walked
for longer than one step without looking at the screen first.

THE TWO LANDMARKS, both measured rather than assumed:

  * THE HIVE WALL IS YELLOW, and nothing else the bot goes near is. Counting
    saturated-yellow pixels (act/hive.hive_bearing) gave 400,142 / 458,766 /
    522,511 standing on the hive, 256,579 walking up to a pad, 106,447 a step
    off it, and 8,837 / 11,840 in a field -- ten to fifty times apart. That
    is a compass to the hive ROW that costs nothing and needs no model.

  * YOUR NAME IS WRITTEN ON YOUR HIVE, in large letters, twice: above the
    honeycomb wall and printed on the white base plate. The owner pointed
    this out themselves -- "it should tell which hive is mine by seeing username
    at the top" -- with screenshots. Once the row is in view, asking the
    vision model where the name is says which way along the row to go. This
    is what tells their pad from the five beside it, and it needs no slot
    number.

  * THE PANEL IS GROUND TRUTH. Standing on your own pad it reads "Make
    Honey" (six reads over fifteen seconds, all identical, 2026-09-20). It is
    the only thing that ends this successfully.

WHAT IT PRESSES: w, a, s, d to move and comma/period to turn the camera.
Nothing else -- no interact key, no Enter, no clicks. The username is READ
off the screen and never typed; `safety.never_chat` is untouched.
"""
from __future__ import annotations

import pathlib
import time
from typing import Callable

from . import motion

from .hive import (ClaimResult, SlotState, _encode_png, _state_of,
                   hive_bearing)

# ---- the numbers, and where each one comes from ---------------------------

# The camera is the steering wheel: MEASURED 8 taps is one full turn, so one
# tap is 45 degrees. A full scan for the hive is therefore 8 looks.
TAPS_PER_FULL_TURN = 8
# Yellow centred within this many pixels of the frame's middle counts as
# "facing the hive row".
#
# MEASURED ON THE FIRST LIVE RUN, 2026-09-22 18:38, and the first value (240)
# was wrong in a way the log made obvious: one camera tap swings the yellow's
# centroid by roughly 800 px (+481 -> -315 -> +484 -> -378 ...), so a deadband
# narrower than half a tap can never be satisfied, and the loop spun left,
# right, left for twenty looks with the hive wall filling a third of the
# screen and never took the step forward. 420 is a little over half the
# measured swing, so a single correcting tap lands inside it. The sign-flip
# rule in the loop is the real fix; this is the deadband it settles into.
FACING_PX = 420
# WHAT THE COUNTS MEAN NOW. hive_bearing counts only honeycomb yellow that
# reaches the top of the world (see it for why), so every figure below was
# re-measured under that rule on 2026-09-22 20:00-20:15:
#
#     standing on our own pad (fixture at_own_hive)        167,686
#     wedged in the corner of Hive 1 and the ramp (run 237) 158,597
#     one step off a pad (fixture stepped_off_hive)          82,941
#     the hive from the field, at the horizon (run 240)   22,000 - 54,000
#     on a pad at an EMPTY slot (fixture slot_3)             21,025
#     fields with no hive in view (run 240, 250 incidents)  0 - 15,000
#
# Two things follow. The hive is IN VIEW above 20,000 -- above the worst
# field reading, under the weakest horizon reading; thin margins, and the
# per-look frames in var/homing are what will widen them. And there is NO
# count that says "at the row": our own pad and the corner read the same.
# So the row is recognised by what happens, not by how much yellow there is
# -- the panel showing a hive prompt (we are on a pad), or forward steps
# that stop raising the count while it is high (we are against the wall).
IN_VIEW_YELLOW = 20_000
NEAR_YELLOW = 50_000
# BUT A FLAT YELLOW WALL CLOSE UP IS NOT THE ROW (DESIGN 8dx). The fields'
# boundary walls are the hive's yellow too, and at arm's length they fill
# the view. MEASURED 2026-09-26 with hive_bearing over 2,944 saved frames
# (every walk-home leg in var/routes, every homing look in var/homing):
#   * our pad's prompt showing, 38 frames: 107,310-207,132 px, and one lit
#     one 403,170;
#   * the 16 looks since attempt 359 that declared "this is the row", as the
#     live loop logged them (up to attempt 445): the eight at a hive
#     138,340-328,930, the eight against a field's wall (Blue Flower,
#     Strawberry, Mushroom; attempts 363 twice, 364, 365, 371, 381, 392, 440)
#     576,037-989,628 -- and those eight walked the wall and found nothing;
#   * all 177 frames above 450,000, looked at: five show a honeycomb face,
#     479,756-531,335, every one a turning look with the hive 470-610 px off
#     centre; the rest are flat walls, and so are all 142 from this line up.
# So a forward walk that stalls at or above this line has met a wall, not
# the hives, and the search stops there instead of walking along it. It
# stops only some walls: the 27 older at-row looks on disk (attempts
# 246-320), by eye, are 19 at the hives, 106,179-345,977, and 8 at a field's
# wall, seven of them 589,532-1,210,476 and attempt 300's look05 at 391,004,
# which this line does not stop -- a wall that low still gets a row search.
# The line cannot come down to it: the honeycomb itself reads up to 531,335.
FLAT_WALL_YELLOW = 560_000
# One step of walking. The same size sweep_and_claim uses, and the panel is
# read after every one -- that is the closed loop.
STEP_SECONDS = 1.0
SIDESTEP_SECONDS = 0.7
# The whole attempt is bounded. Twenty-four looks is roughly a minute, which is
# already longer than a rejoin, so past this the caller's fallback is the
# better use of time.
MAX_LOOKS = 24
# WALKING INTO A WALL. MEASURED 2026-09-22 19:46 (run 237) and again 19:50
# (run 238), homing from the Dandelion field floor: look 0 read 88,338 yellow
# px, look 1 read 144,603, and looks 2..23 read 146,056-151,645 -- twenty-two
# forward steps that moved the count by under 4% while the character stood
# wedged in the corner between Hive 1's honeycomb wall and the side of the
# ramp (the live frame is var/homing/237-stuck-194703.jpg; Natro Macro's own
# path notes call this "corner (Hive 1 and ramp) where character gets stuck").
# Approaching the hive, the yellow count rises steeply (+64% on the first
# step above); a step that raises it by less than PROGRESS_MIN is a step that
# went nowhere. Three of those in a row and the forward walk is over: with a
# high count that means the wall is reached and the row is to be walked;
# with a low one something else is in the way, and the honest thing is to
# say so at once -- the rejoin banks the backpack in about 45 s, which those
# twenty wasted looks cost on top. A step the ground odometer measured as
# moving nothing counts as stalled straight away.
STALLED_STEPS = 3
PROGRESS_MIN = 0.03
# Walking the row: a sidestep that moved nothing means the row is blocked
# that way (a wall, a decoration, the ramp's side), so the walk turns round.
# Blocked both ways and there is no row to walk.
MAX_ROW_REVERSALS = 2
# A DARK LOOK RIGHT AFTER A STEP AT THE HIVE IS A GAP, NOT A LOST HIVE. The
# hives stand side by side with a narrow slot between each pair (and one
# between the end hive and the ramp); a step toward the yellow's centroid
# from a hive's face can carry the character into it, and in there the
# camera sees the slot's dark sides -- under IN_VIEW_YELLOW -- so the loop
# used to start a "no hive in view" scan, turn a full circle inside the slot
# and report "too far from the hive". MEASURED 2026-10-13 over every walk
# home since run 831 that read 20,000+ px and still missed (31, var/night,
# frames in var/homing): 7 ended in such a slot, and 4 of them by exactly
# this look -- attempt-948/look06-step-y307489 then look07-scan-y000000
# (05:50), attempt-907/look08-step-y327204 then look09-scan-y000000 (17:28),
# attempt-868 look 9 182,895 then 0 (06:12), attempt-894 look 5 78,235 then
# 0 (01:26). A forward step at NEAR_YELLOW+ followed by a look under
# IN_VIEW_YELLOW happened in 7 sight homings since run 831, all 7 failed,
# and in none of the 9 that landed. So the step is undone (its keys
# reversed, the same length) and the look is taken as "at the row": the
# row search runs from the hive face the step left -- how 7 of this loop's
# 9 landings since run 831 came (attempts 832, 863, 894 x2, 898, 904, 940,
# each from a stall at 90,861-272,446 px). Not below a
# FLAT_WALL_YELLOW step: that was a field's wall (attempt 875, 807,648).
# "on"; "ab" = on in hours 0-1, 4-5, 8-9, ... (each pair of hours), so each
# arm holds as many even as odd hours and HOME_UNSTICK / HOME_ALIGN (even
# hours) and HOME_BUFF_REARM (odd) stay clean; "off" = the scan as before.
# On, not "ab": the scan after such a look closed 0 of 7, and the look never
# came up in a landing, so the off arm could only re-measure a zero.
# ponytail: undoes one step only; a slot entered over two steps (attempt
# 891, 24,485 px on the way in) or declared "the row" inside (865, 894
# 06:11) is not caught.
GAP_BACK_OUT = "on"


def gap_back_out_on(hour: int | None = None) -> bool:
    """Is the gap back-out on (`hour` for tests; now by default)? See GAP_BACK_OUT."""
    if GAP_BACK_OUT == "ab":
        return ((time.localtime().tm_hour if hour is None else hour) // 2) % 2 == 0
    return GAP_BACK_OUT == "on"


_REVERSE = str.maketrans("wsad", "swda")     # a step undone: w<->s, a<->d
# Prompts that mean "standing on the hive platform, at the row's end". MEASURED
# 2026-09-22 20:27 (run 244, var/homing/attempt-244/look06): the panel read
# "E Open Beequip Storage" with the pads in plain view to the right, and the
# compass spent the next eighteen looks turning toward the storage's own wall
# (413,760 yellow px). The storage stands at the end of the row; a prompt
# from it is a position fix, and the pads are found by walking the row.
ROW_LANDMARK_WORDS = ("beequip storage",)
# The world, without the HUD: the notification panel lives above row 170 and
# the hotbar below row 900 (same crop hive_bearing uses).
WORLD_ROWS = (170, 900)

# Asked of the vision model only once the row is near. One word back, so the
# answer parses without guessing at prose.
NAME_QUESTION = (
    "This is a Roblox Bee Swarm Simulator screen showing a row of beehives. "
    "Is the player name \"{name}\" written anywhere in the image? It would be "
    "in large letters above a honeycomb wall or on a white circular plate. "
    "Answer with exactly ONE word: LEFT if the name is left of the image "
    "centre, RIGHT if it is right of centre, CENTRE if it is roughly in the "
    "middle, or NO if it is not visible.")


_NEGATIONS = ("not visible", "isn't visible", "is not", "cannot see",
              "can't see", "don't see", "do not see", "no,", "no.", "none")
_SIDES = (("left", "LEFT"), ("right", "RIGHT"), ("centre", "CENTRE"),
          ("center", "CENTRE"), ("middle", "CENTRE"))


def username_from(settings) -> str:
    """`account.username`, the name written on the owner's hive, or "".

    Read here rather than in the script so the settings wiring test can see
    that the control is live. Empty means "unknown": homing then finds the
    ROW from the yellow alone and walks it until the panel speaks, which
    works but cannot tell their pad from a neighbour's at a glance.
    """
    try:
        value = settings.get("account.username")
    except Exception:
        return ""
    return str(value or "").strip()


def _direction(answer: str | None) -> str | None:
    """LEFT / RIGHT / CENTRE / NO, or None when the model said nothing usable.

    NEGATION IS CHECKED FIRST, and it has to be. The question asks for one
    word, but a vision model will happily answer "I do not see the name on
    the left side", and a parser that scans for side words first reads that
    as LEFT -- and the character sidesteps toward a pad that is not there.
    So: any phrasing of "not visible" is NO, whatever else the sentence says;
    otherwise the EARLIEST side word wins, so "right of centre" is RIGHT and
    not CENTRE.
    """
    if not answer:
        return None
    low = " ".join(answer.strip().lower().split())
    if low == "no" or low.startswith("no ") or any(n in low for n in _NEGATIONS):
        return "NO"
    found = [(low.find(word), out) for word, out in _SIDES if word in low]
    if not found:
        return None
    return min(found)[1]


class _FrameKeeper:
    """Writes each look's frame to `save_dir` as `lookNN-<action>-yNNNNNN-b+NNN.jpg`.

    A record, not a feature: the name says what the loop measured and did, so
    a directory listing reads as the loop's own account of the walk, and the
    picture says what the numbers could not. Never raises -- a failed save
    must not cost a step.
    """

    def __init__(self, save_dir):
        self.where = pathlib.Path(save_dir) if save_dir else None
        self.frame = None
        self._yellow: int | None = None
        self._bearing: int | None = None

    def tag(self, yellow: int, bearing: int) -> None:
        self._yellow, self._bearing = int(yellow), int(bearing)

    def save(self, look: int, action: str) -> None:
        if self.where is None or self.frame is None:
            return
        try:
            import cv2
            self.where.mkdir(parents=True, exist_ok=True)
            tag = ""
            if self._yellow is not None:
                tag = f"-y{self._yellow:06d}-b{self._bearing:+05d}"
            name = f"look{look:02d}-{action}{tag}.jpg"
            cv2.imwrite(str(self.where / name), self.frame[:, :, :3],
                        [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        except Exception:
            pass
        finally:
            self._yellow = self._bearing = None


def home_by_sight(vin, frames, read_panel, model=None, username: str = "", *,
                  sleep=time.sleep, stopped: Callable[[], bool] = lambda: False,
                  on_note=None, max_looks: int = MAX_LOOKS,
                  save_dir=None, odometer=None, on_landmark=None,
                  row_search=None) -> ClaimResult:
    """Find the owner's own hive pad and stand on it. Presses no interact key.

    `frames()` -> a frame; `read_panel(frame)` -> the top-centre panel's text
    ("" for no panel, None for could-not-look); `model.ask(png, question)` ->
    an Answer with `.text`, or None. `username` is what is written on the
    hive; with it empty the name step is skipped and the loop homes on the
    yellow alone, which finds the ROW but cannot pick the pad. `odometer` is
    a `vision.flow.Odometer`; with it every step is measured off the ground
    and a step that moved nothing is known at once (act/motion).

    Returns a ClaimResult: `ok` only when the panel read "Make Honey", `hops`
    is how many looks it took, `taps` the net camera turns (right positive)
    so the compass can follow, `reason` why it stopped otherwise.

    `save_dir`, when given, receives every look's frame as a small JPEG named
    for what the loop saw and did -- the record that turned run 237's
    "stepping forward" x22 into a picture of a corner. Saving never raises.

    `on_landmark(text) -> bool` is offered the panel's words whenever they are
    not a hive prompt. MEASURED 2026-09-22 22:54 (attempt 253): while walking
    the row the panel said "at the honey dispenser" -- a place with a recorded
    route back to the pad (187 studs, `natro_back_honey_dispenser`) -- and the
    loop walked past it and spent the rest of its budget. A caller that can
    use such a place walks it and returns True, and the loop stops there.

    `row_search() -> result with .ok and .describe()` is Natro's row search
    from the face (act/hiverow.search_from_the_face), run ONCE when the loop
    first knows it is at the row; the panel then says whether it landed, and
    a search that did not land ends the homing, because it has already held
    along the whole row both ways. Without it the row is walked with the
    vision model's answer about the name, as before. MEASURED since attempt
    340 (DESIGN 8dx): that walk found the pad 0 times, from real hive rows
    (attempts 404, 409, 410, 432, 438) as well as from walls.
    """
    note = on_note or (lambda text: None)
    result = ClaimResult()
    name = (username or "").strip()
    scanned = 0          # camera taps spent looking for yellow with none in view
    strongest = 0        # the most yellow seen during a scan, for the give-up line
    best = 0             # ... and over every look of this homing, for the same line
    last_forward = "w"   # the keys of the last forward step, for the gap back-out
    last_side = "d"      # which way along the row to drift when the name is unseen
    # The bearing before the last camera tap. If the next bearing has the
    # OPPOSITE sign, the tap overshot: the hive is now bracketed between two
    # camera headings and turning again would only swing back. That is the
    # moment to stop turning and walk. See FACING_PX for the measurement.
    last_bearing: int | None = None
    last_tap_key = "period"
    # Did the previous look end in a correcting tap? MEASURED 2026-09-22
    # 18:55 (run 224), a second way to spin that the sign-flip rule cannot
    # see: the hive read -730 px, a left tap swung it clean OUT of view, the
    # "not in view" scan tapped right and brought it back to -730, and so on
    # for eighteen looks. The two in-view readings never had opposite signs,
    # so nothing bracketed. The rule that ends both spins is the same: NEVER
    # TWO CORRECTING TAPS WITHOUT A STEP BETWEEN THEM. Tap once, then walk a
    # step whatever the next look says (unless the hive has gone), then look
    # again. Walking while 25 degrees off still closes the distance, and the
    # next look corrects again -- a pursuit curve rather than a pendulum.
    tapped_last_look = False
    # THE SIDE A CORRECTING TAP LOST THE HIVE ON (-1 left, +1 right; 0 none),
    # kept until the hive is seen on the other side, near the middle, or not
    # at all. MEASURED, a third way to spin (DESIGN 8dx): the tap-back branch
    # below forgets the bearing, so the next look tapped the same way again
    # and lost it again -- attempt 362 looks 1-20 (the hive at -768..-866 px,
    # 138,000-280,000 px of it), attempt 437 looks 5-23 (-445..-471 px, wedged
    # against a hive's side), ten taps each and no forward progress. A side
    # that one tap has already lost is walked toward, never tapped toward.
    lost_side = 0
    # The yellow count before the last forward step, and how many forward
    # steps in a row have failed to raise it by PROGRESS_MIN. See STALLED_STEPS.
    yellow_before_step: int | None = None
    stalled = 0
    # At the row: forward progress is over and the pads are found by walking
    # sideways along the wall. Entered by the panel showing a hive prompt or
    # by the forward walk stalling against a high count; never by a count.
    at_row = False
    row_reversals = 0
    keep = _FrameKeeper(save_dir)

    def step(keys: str, seconds: float) -> bool | None:
        """Hold `keys` for `seconds`. True if the ground says nothing moved,
        False if it moved, None if it could not be measured."""
        return motion.stuck(motion.hold_measuring(vin, keys, seconds, sleep,
                                                  frames, odometer))

    for look in range(max_looks):
        if stopped():
            result.reason = "stop requested"
            break
        result.hops = look + 1
        try:
            frame = frames()
        except Exception as exc:
            note(f"capture failed ({exc}); looking again")
            sleep(0.3)
            continue
        if frame is None:
            sleep(0.3)
            continue
        keep.frame = frame

        # 1. GROUND TRUTH FIRST. If the panel already says we are on the pad,
        #    nothing else matters. Any other hive prompt says we are on SOME
        #    pad -- the row is found, whatever the yellow count thinks.
        try:
            text = read_panel(frame)
        except Exception as exc:
            note(f"could not read the panel ({exc})")
            text = None
        state = _state_of(text) if text else None
        if state is SlotState.MINE:
            result.ok = True
            result.confirmed_by = f"the panel read {text!r}"
            note(f"on our own pad after {look} look(s): {text!r}")
            keep.save(look, "on-our-pad")
            break
        if state is SlotState.EMPTY and not at_row:
            at_row = True
            note(f"look {look}: the panel reads {text!r} — on a pad, so this "
                 f"is the row; walking it to find ours")
        elif text and on_landmark is not None and _state_of(text) is not SlotState.EMPTY:
            # A PLACE THE GAME NAMES, and the caller may know the way back
            # from it. See on_landmark.
            try:
                went = bool(on_landmark(text))
            except Exception as exc:
                went = False
                note(f"look {look}: the landmark rescue failed ({exc})")
            if went:
                result.ok = True
                result.confirmed_by = (f"walked the recorded route back from "
                                       f"{text.strip()!r}")
                note(f"home from a named landmark after {look} look(s): "
                     f"{text.strip()[:40]!r}")
                keep.save(look, "landmark-rescue")
                break
        if (text and not at_row and _state_of(text) is not SlotState.MINE
                and any(word in text.lower() for word in ROW_LANDMARK_WORDS)):
            at_row = True
            note(f"look {look}: the panel reads {text.strip()[:40]!r} — that "
                 f"stands at the end of the hive row; walking the row to find "
                 f"our pad")

        # 2. THE YELLOW WALL: is the hive row in view, and which way is it?
        bearing, yellow = hive_bearing(frame)
        keep.tag(yellow, bearing)
        best = max(best, yellow)
        gap = (yellow < IN_VIEW_YELLOW and not tapped_last_look and not at_row
               and yellow_before_step is not None
               and NEAR_YELLOW <= yellow_before_step < FLAT_WALL_YELLOW
               and gap_back_out_on())
        if gap:
            # INTO THE SLOT BETWEEN TWO HIVES: undo the step, then the row
            # search from the face it left. See GAP_BACK_OUT.
            back = last_forward.translate(_REVERSE)
            note(f"look {look}: gap back-out — {yellow:,} yellow px right after a "
                 f"step at {yellow_before_step:,}: a slot beside the hive, not a "
                 f"lost hive; stepping back ({back}) and searching the row from there")
            keep.save(look, "gap-back-out")
            step(back, STEP_SECONDS)
            sleep(0.4)
            at_row = True
            stalled = 0
            yellow_before_step = None
        elif yellow < IN_VIEW_YELLOW and tapped_last_look:
            # The correcting tap swung the hive OUT of the frame -- that IS an
            # overshoot. Undo it and walk; do not begin a fresh scan from a
            # heading that was already known to be wrong by one tap.
            back = "comma" if last_tap_key == "period" else "period"
            vin.tap(back)
            result.taps += 1 if back == "period" else -1
            tapped_last_look = False
            yellow_before_step = None          # the view changed, not the place
            # MEASURED 2026-09-22 20:27 (run 244): the hive read -578 px, a
            # left tap lost it, the tap back found it at -578 again, and a
            # straight step forward left it at -578 -- twelve looks of that.
            # Walking straight never changes a bearing to something BESIDE
            # you. So the step is diagonal, toward the side the hive was on.
            toward = "a" if (last_bearing or 0) < 0 else "d"
            lost_side = -1 if toward == "a" else 1
            last_bearing = None
            note(f"look {look}: the last tap swung the hive out of view "
                 f"({yellow} yellow px) — tapping back and walking "
                 f"{'left' if toward == 'a' else 'right'}-forward")
            keep.save(look, "tap-back-and-walk")
            sleep(0.5)
            step("w" + toward, STEP_SECONDS)
            sleep(0.4)
            continue
        elif yellow < IN_VIEW_YELLOW:
            # Not in view. Turn and look again, up to one full turn --
            # then STOP, because walking toward field yellow is how the second
            # live run spent twenty steps going nowhere. The rejoin banks the
            # backpack in about 45 s; this must not cost more than that.
            strongest = max(strongest, yellow)
            at_row = False
            lost_side = 0
            if scanned >= TAPS_PER_FULL_TURN:
                # "most" is the whole homing's, not this last circle's:
                # attempt 948 05:50 reported "most was 7,760 px" two looks
                # after reading 307,489 at a hive's face.
                result.reason = (f"turned a full circle and never saw the "
                                 f"hive's yellow wall (most was {best:,} px over "
                                 f"all {look + 1} looks, {strongest:,} in this last "
                                 f"circle; the wall reads {IN_VIEW_YELLOW:,}+ when in "
                                 f"view)" + (" — too far from the hive to home by sight"
                                             if best < IN_VIEW_YELLOW else
                                             " — it was in view earlier and was lost"))
                break
            vin.tap("period")
            result.taps += 1
            scanned += 1
            yellow_before_step = None
            note(f"look {look}: no hive in view ({yellow} yellow px), turning")
            keep.save(look, "scan")
            sleep(0.5)
            continue
        scanned = 0
        strongest = 0

        # 4. AT THE ROW. Which pad is ours? Ask where the name is, then walk
        #    that way along the wall; without an answer, keep walking the way
        #    we were. A sidestep the ground says moved nothing means the row
        #    is blocked that way, so turn round.
        if at_row and row_search is not None:
            # NATRO'S ROW SEARCH, ONCE, instead of the model-guided sidesteps
            # below (see `row_search`). Its hold releases on the pad's own
            # prompt, the template MEASURED with no false positive over 4,049
            # frames (vision/screenstate.make_honey_present, DESIGN 8cb), so
            # a landing is taken as it stands.
            keep.save(look, "row-search")
            note(f"look {look}: at the row — Natro's row search from here "
                 f"(onto the face, back to the search line, left then right)")
            try:
                row = row_search()
            except Exception as exc:
                row = None
                note(f"look {look}: the row search failed ({exc})")
            if bool(getattr(row, "ok", False)):
                result.ok = True
                described = getattr(row, "describe", None)
                result.confirmed_by = ("the row search saw the pad's prompt: "
                                       + (described() if callable(described)
                                          else "found"))
                note(f"on our own pad after {look} look(s) and the row search")
                break
            described = getattr(row, "describe", None)
            result.reason = ("at the row, and Natro's row search from it did not "
                             "find the pad: "
                             + (described() if callable(described) and row is not None
                                else "it could not run"))
            break
        if at_row:
            side = None
            if name and model is not None and getattr(model, "available", lambda: False)():
                top, bottom = WORLD_ROWS
                try:
                    answer = model.ask(_encode_png(frame[top:bottom, :, :3]),
                                       NAME_QUESTION.format(name=name))
                    side = _direction(getattr(answer, "text", None))
                    note(f"look {look}: the model says the name is {side or 'unreadable'}"
                         + (f" ({answer.text.strip()[:60]!r})" if answer else ""))
                except Exception as exc:
                    note(f"look {look}: asking about the name failed ({exc})")
            key = {"CENTRE": "w", "LEFT": "a", "RIGHT": "d"}.get(side, last_side)
            if key in ("a", "d"):
                last_side = key
            if side is None or side == "NO":
                note(f"look {look}: at the row, name not placed — walking the row "
                     f"({'right' if key == 'd' else 'left'})")
            keep.save(look, f"row-{(side or 'unplaced').lower()}-{key}")
            blocked = step(key, SIDESTEP_SECONDS)
            if blocked and key in ("a", "d"):
                # BACK OUT FIRST. MEASURED 2026-09-22 22:25-22:30 (runs 246 and
                # 247, var/homing): the name read LEFT nine looks running and
                # every step left moved nothing -- the character had walked
                # forward into the gap between two hive structures, so the
                # pad was to the left of a wall, not along a row. One step
                # back leaves the gap; only if the sidestep is still blocked
                # after that is the direction turned round.
                note(f"look {look}: that sidestep moved nothing — stepping back "
                     f"out of whatever this is and trying again")
                backed = step("s", STEP_SECONDS)
                blocked = True if backed else step(key, SIDESTEP_SECONDS)
            if blocked and key in ("a", "d"):
                row_reversals += 1
                last_side = "a" if key == "d" else "d"
                note(f"look {look}: still blocked to the {'right' if key == 'd' else 'left'} "
                     f"after backing out; walking the row the other way")
                if row_reversals > MAX_ROW_REVERSALS:
                    result.reason = (f"blocked both ways along the hive row "
                                     f"({row_reversals} reversals) without the panel "
                                     f"ever reading 'Make Honey'"
                                     + (f"; the frames are in {keep.where}" if keep.where else ""))
                    break
            sleep(0.4)
            continue

        # 3. NOT YET AT THE ROW. First the verdict on the last forward step:
        #    a measured "moved nothing", or three flat counts, ends the
        #    forward walk BEFORE any turning -- MEASURED 2026-09-22 20:27
        #    (run 244): "that step moved nothing" against the storage's wall
        #    at 88,789 px, and the next look tapped the camera instead of
        #    acting on it, then the one after tapped back, for twelve looks.
        if (yellow_before_step is not None
                and yellow < yellow_before_step * (1 + PROGRESS_MIN)):
            stalled += 1
        if stalled >= STALLED_STEPS:
            if yellow >= FLAT_WALL_YELLOW:
                result.reason = (
                    f"the forward walk ended against a flat yellow wall "
                    f"({yellow:,} px, more than our pad has ever read, "
                    f"{FLAT_WALL_YELLOW:,}+) — a field's boundary, not the hive "
                    f"row, so it is not walked along"
                    + (f"; the frames are in {keep.where}" if keep.where else ""))
                note(f"look {look}: {result.reason}")
                keep.save(look, "flat-wall")
                break
            if yellow >= NEAR_YELLOW:
                at_row = True
                stalled = 0
                yellow_before_step = None
                note(f"look {look}: the forward walk is over against the hive's "
                     f"yellow at {yellow:,} px — this is the row, walking it to "
                     f"find our pad")
                keep.save(look, "at-row")
                continue
            result.reason = (
                f"blocked walking at the hive: the last forward steps did not "
                f"raise its yellow ({yellow_before_step or yellow:,} → "
                f"{yellow:,} px, hive {bearing:+d} px off centre) — a wall "
                f"or ledge stands between here and the pads"
                + (f"; the frames are in {keep.where}" if keep.where else ""))
            note(f"look {look}: {result.reason}")
            keep.save(look, "blocked")
            break
        bracketed = (last_bearing is not None
                     and (bearing > 0) != (last_bearing > 0))
        if lost_side and (abs(bearing) <= FACING_PX
                          or (bearing > 0) != (lost_side > 0)):
            lost_side = 0                        # seen elsewhere: taps may turn again
        lost_there = bool(lost_side) and abs(bearing) > FACING_PX
        if (abs(bearing) > FACING_PX and not bracketed and not tapped_last_look
                and not lost_there):
            key = "period" if bearing > 0 else "comma"
            vin.tap(key)
            result.taps += 1 if bearing > 0 else -1
            last_bearing = bearing
            last_tap_key = key
            tapped_last_look = True
            yellow_before_step = None          # the view changed, not the place
            note(f"look {look}: hive is {bearing:+d}px off centre "
                 f"({yellow} yellow px), turning {'right' if bearing > 0 else 'left'}")
            keep.save(look, "turn-right" if bearing > 0 else "turn-left")
            sleep(0.5)
            continue
        forward = "w"
        if abs(bearing) > FACING_PX:
            why = ("the last tap swung it across — bracketed"
                   if bracketed else
                   "a tap that way has already lost it" if lost_there else
                   "one tap was already spent on it")
            # Toward its side, not straight: see the tap-back branch above.
            forward = "w" + ("a" if bearing < 0 else "d")
            note(f"look {look}: hive is {bearing:+d}px off centre but {why}, "
                 f"so walking {'left' if bearing < 0 else 'right'}-forward "
                 f"rather than turning again")
        last_bearing = None
        tapped_last_look = False
        last_forward = forward

        if yellow_before_step is not None and yellow >= yellow_before_step * (1 + PROGRESS_MIN):
            stalled = 0                          # the count rose: progress
        near = "near" if yellow >= NEAR_YELLOW else "ahead"
        note(f"look {look}: hive {near} ({yellow} yellow px), stepping forward")
        keep.save(look, "step")
        yellow_before_step = yellow
        if step(forward, STEP_SECONDS):
            # The ground did not move: the wall is already here, measured. The
            # verdict is taken at the top of the next look, before any turn.
            stalled = STALLED_STEPS
            note(f"look {look}: that step moved nothing")
        sleep(0.4)
    else:
        result.reason = (f"looked {max_looks} times without the panel ever "
                         f"reading 'Make Honey'")

    if not result.ok and not result.reason:
        result.reason = "stopped before the panel read 'Make Honey'"
    return result
