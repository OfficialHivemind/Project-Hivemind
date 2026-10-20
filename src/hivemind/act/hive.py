"""Claiming a hive, which is the first thing that must happen after joining.

OWNER'S CORRECTION, 2026-09-20, and it overrides what the rest of the repo
assumed before it: on joining Bee Swarm you own no hive until you claim an
empty one, and the game then loads yours into it.

So there is no fixed slot to walk to. The Movement panel's hive-slot setting
and `RouteRunner._hop_to_slot` both describe a slot the account ALREADY owns --
which is true once a hive has been claimed, and false for every fresh join.
This module covers the step in between: walk the row of slots, look at each
one, and claim the first empty hive. Only after that does "your slot" mean
anything, and the number this returns is what the rest of the navigation layer
has been treating as a configured constant.

HOW A SLOT IS READ

Standing at a hive puts a prompt on screen. BeeTuxMacro finds it with two
white-pixel probes -- claim-hive "C" at (638, 81) and make-honey "H" at
(719, 88), DESIGN section 6 -- and the register is explicit that **either** one
confirms "standing at a hive". So the macro never tells an unclaimed hive from
its own: it ORs the two probes and presses the interact key at whichever it
found. The "C" and "H" are the letters those pixels sit on, not key bindings;
the two probes are 81 px apart on one line of a 768-high screen, which is a
text row, not two separate prompts in two places.

**Those coordinates are not used here.** They sit in the REPORTED tier of the
verification register, they are in 1366x768 reference space while every frame
we capture is 1920x1080, and the register records the trap directly: without
the trade-requests-disabled banner as a disambiguator, a red banner reads as a
hive prompt. A probe that answers "there is something bright here" is exactly
the kind of confident wrong answer this project keeps being bitten by.

What this module needs is the one thing the macro never had: the DISTINCTION
between "empty" and "already ours", because it is deciding whether to claim
rather than confirming it arrived somewhere. Nothing in the repo establishes
that distinction yet, which is why it is injected and why the default refuses.

WHY EVERY EARLIER SEARCH FAILED, AND WHAT REPLACED IT

Two runs looked for the prompt and found nothing: `learn_hive_prompt.py` asked
the vision model at all six slot positions and got "NO" six times
(`var/vlm_cache`, 2026-09-20 00:58:53-00:59:19), and `diag_hive_slot.py`
probed for bright pixels in `PROMPT_REGION = (560, 700, 800, 220)`. Both were
looking at the BOTTOM of the screen.

RESEARCHED 2026-09-20, and confirmed by a second agent told to refute it: on
tablet/iOS/Android the documented way to claim is "tapping the **claim hive**
button", a large button at the TOP of the screen. The `[C]`/`[E]` keyboard
prompt is the PC affordance. Sober runs the ANDROID build, so the mobile UI is
what is on screen. BeeTuxMacro's probes said the same thing all along --
(638, 81) and (719, 88) are at the top of a 768-high screen, y~114-124 once
scaled to our 1920x1080 frames. The searches were in the wrong half of the
picture.

So the missing piece was never a template. It was the region.

WHAT IS BUILT NOW

`vision.banner.find` locates the game's top-centre notification panel by shape
and colour: MEASURED across the twelve real frames in
`tests/fixtures/screens/hive`, present in exactly five at x=784 y=62 352x58,
absent in the other seven, and no false positive on five other real screens
(in_game, reset_dialog, escape_menu, app_home, hive_short_pollen). It rejects
a same-hue patch of sky at x~1240 on aspect (6.1 against 1.4) and on being
centred.

`banner_reader(model)` below reads what that panel SAYS, using the local
vision model. VALIDATED against ground truth: handed the real banner crop it
returned "You've made 73,013,670\nHoney", exact to the commas, and answered NO
on a crop from a frame with no panel.

STILL UNSEEN, and it is the honest gap: no frame on this account has ever
carried the claim-hive prompt itself, because the character never reached an
unclaimed slot -- the hop sequence walks off toward the Shop, which those same
frames show. So the panel detector and the text reader are both validated,
while the specific words the claim button uses are matched on documented
phrasing rather than on a frame we have. `claim()` still refuses on anything
it cannot read, so the cost of that phrasing being wrong is a refusal, not a
wrong key press.

WHY REFUSING IS CHEAPER THAN TRYING

Pressing the claim key at a hive that belongs to somebody else does nothing,
so a blind press is only *nearly* free -- at our OWN hive the same key starts
a honey conversion (BeeTuxMacro's convert() presses it and then sleeps
CONVERT_TIME, ~100 s), which is why this presses only at a slot that read
EMPTY and returns the moment one reads MINE. Reporting a claim we cannot see
is the expensive mistake, because everything downstream -- the slot number,
every recorded route out of the hive, the convert-at-hive step of the farm
loop -- is built on top of the answer. A bot that believes it owns slot 3 and
does not will walk every route from the wrong place and make honey at nobody's
hive. So this module never returns `ok` on a prompt it did not read.

SAFETY

Only two keys are ever sent: `space` (the hop, two jumps, exactly as
BeeTuxMacro does it) and `CLAIM_KEY` (the claim -- `e`, and a `claim_key=`
override cannot be Return or Escape). Both are taps. Nothing is held across a
screen read, and the sweep ends in `release_all()` even when the detector
raises. Return is never pressed by anything here -- that keystroke belongs to
the respawn confirmation, which has its own detector in
`vision.screenstate.reset_dialog_present`, and to the menu underneath it that
carries **Leave**.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from ..vision import templates
from . import hiverow
from .routes import HOP_RISE, HOP_SETTLE

# Six hives in the row, addressed as hops from the left corner with
# `slot = 5 - hops`. DESIGN.md section 6 ("Hive addressing"), ported from
# BeeTuxMacro's `for ((i=0; i<5-$1; i++))` hop loop, and the same arithmetic
# `RouteRunner._hop_to_slot` runs with its `from_slot=5` default.
# `scripts/diag_hive_slot.py` photographs exactly these six positions.
SLOT_COUNT = 6
TOP_SLOT = 5

# The key pressed at an empty hive. `e` is the only key anything in this
# project has been seen to press at a hive, and all three sources agree:
#   * BeeTuxMacro's find_hive presses `e` the instant either hive probe reads
#     white (stuff/utils.sh:140-141) -- that is its claim;
#   * `e()` is `wtype -P E -p E` (stuff/utils.sh:578-580);
#   * convert() presses the same `e` at the owned hive to start making honey
#     and then sleeps CONVERT_TIME (stuff/utils.sh:28, 39), and `RouteRunner`'s
#     `interact` op is the transpiled form of it: `vin.tap("e")`.
# The "C"/"H" in the register's probe names are letters on the screen, not keys
# (see the module docstring), so they are not evidence of a binding.
#
# UNVERIFIED, and it is the one constant here that presses something: the
# prompt's own bracketed key has never been read off a real frame on this
# account. The capture run that builds the detector settles it in the same
# screenshot -- read the letter out of the prompt, and pass `claim_key=` if it
# turns out not to be E.
CLAIM_KEY = "e"

# NOT a measured game timing, and labelled so on purpose: how long we are
# willing to watch for the prompt to turn into "Make Honey" after the claim.
# How long the game takes to load a freshly claimed hive has never been
# measured on this account. If it turns out to be longer than this budget the
# fix is to raise the budget -- never to assume the claim worked.
CONFIRM_POLLS = 10
CONFIRM_INTERVAL = 0.5

# Keys this module refuses to send whatever a caller passes as `claim_key`.
# `enter` activates whatever the in-game menu has selected and that menu
# carries **Leave**; `escape` is what opens it. The respawn confirmation is a
# different screen with its own detector (`screenstate.reset_dialog_present`),
# and `RouteRunner._reset` is the only thing allowed to press Return, only
# after that detector has seen the dialog. Making the claim key overridable
# must not quietly become a second route to those keys. Names are
# `platform.wl.vkeyboard.KEYS` spellings; `act` cannot import `platform` (the
# dependency rule), so they are written out.
FORBIDDEN_KEYS = frozenset({"enter", "return", "escape"})


class SlotState(str, Enum):
    """What the screen says about the slot the character is standing at."""
    EMPTY = "empty"        # the claim-hive prompt: unclaimed, and ours to take
    MINE = "mine"          # the make-honey prompt: already ours
    TAKEN = "taken"        # a hive is there and it is not ours: no prompt
    UNKNOWN = "unknown"    # the screen could not be read. Never acted on.


@dataclass(frozen=True)
class SlotReading:
    """One look at one slot."""
    slot: int
    hops: int
    state: SlotState

    def describe(self) -> str:
        return f"slot {self.slot} (after {self.hops} hops): {self.state.value}"


@dataclass
class ClaimResult:
    """Which slot the account ended up with, and how that was established.

    `confirmed_by` is the point of this type. `ok` alone would let a caller
    treat "I pressed the key and hoped" the same as "I watched the prompt
    change",
    and those are the two outcomes the whole module exists to keep apart.
    """
    ok: bool = False
    slot: int | None = None
    hops: int | None = None
    newly_claimed: bool = False
    confirmed_by: str = ""
    reason: str = ""
    readings: list[SlotReading] = field(default_factory=list)
    # Net camera taps this routine made (right is positive). The camera is the
    # steering wheel for every recorded route, and until 2026-09-21 these
    # routines turned it and told nobody -- the box search alone ends 180
    # degrees off. `world/bearings` consumes this; see nav/journey.square_up.
    taps: int = 0
    # Where another player's trade prompt was read (PLAYER_PROMPT), or "".
    player_at: str = ""

    def describe(self) -> str:
        if not self.ok:
            return f"no hive claimed — {self.reason}"
        what = "claimed" if self.newly_claimed else "already ours"
        return (f"slot {self.slot} after {self.hops} hops, {what} "
                f"— confirmed by {self.confirmed_by}")


def _approach_ok(outcome) -> bool:
    """Did the walk to the first slot succeed?

    `False` means no -- and so does any result object carrying `ok = False`,
    which is what `RouteRunner.run` returns and therefore what a caller is
    most likely to hand over. A `RouteResult` is truthy whether or not the
    route ran, so testing only `is False` would let a walk that stopped
    halfway start the sweep from an unknown position and claim whatever is
    standing there. `None` -- a plain callable that just walks -- stays a
    success, because a function with nothing to report returns it.
    """
    if outcome is False:
        return False
    return bool(getattr(outcome, "ok", True))


def prompt_unavailable(frame: np.ndarray) -> SlotState:
    """The default screen test: it does not exist yet, and says so.

    THIS IS NOT A STUB THAT WILL BE FILLED IN LATER BY GUESSING. There is no
    captured frame of either hive prompt in this repo, so there is no template
    to match and no threshold that could be validated against anything. A
    detector written from the wiki's description of where the prompt appears
    would be a coordinate nobody measured, wired to a key press.

    Returning UNKNOWN makes `claim_hive` refuse and explain, which is the
    correct behaviour for "I cannot see" and matches
    `screenstate.reset_dialog_present`, which returns False when its template
    is missing for exactly the same reason.
    """
    return SlotState.UNKNOWN


# Read by HiveClaimer to refuse before it moves the character. A detector that
# can genuinely answer sets this True (see `template_reader`); anything without
# the attribute is assumed real, so an injected test double or a future
# detector does not have to know about this protocol.
prompt_unavailable.detector_built = False


def template_reader(claim_template: np.ndarray, honey_template: np.ndarray,
                    region: tuple[int, int, int, int] | None = None,
                    threshold: float = 0.75):
    """Build a screen test from two prompt crops the caller captured.

    The templates are REQUIRED arguments with no default and no file lookup:
    there is no path through this function that quietly proceeds without real
    crops of the real prompts. Capture them from
    `scripts/diag_hive_slot.py`'s frames.

    `threshold` defaults to `vision.templates.find`'s own default rather than a
    number invented for these two labels, and it is unvalidated for them.
    Validate it when the crops exist: the register records the "Servers" label
    needing 0.90 instead of 0.75, because a tight crop matched the PREFIX of a
    different row at 0.877. Short words on game UI do that.

    `region` is optional and defaults to the whole frame. `diag_hive_slot.py`
    searches (560, 700, 800, 220), but its own comment calls that generous
    rather than measured, so it is not baked in here.

    Reads MINE before EMPTY deliberately: if both somehow match, the safe
    reading is "this is already a hive", which claims nothing.

    Returns UNKNOWN -- not TAKEN -- when neither matches. No prompt means "no
    prompt", which covers another player's hive AND standing slightly too far
    away, and those are not the same thing. Only a detector that can see the
    hive itself (the VLM panel already asks "are these hive slots empty, or do
    they have hives on them?") can report TAKEN honestly.
    """
    def read(frame: np.ndarray) -> SlotState:
        if templates.find(frame, honey_template, threshold=threshold,
                          region=region) is not None:
            return SlotState.MINE
        if templates.find(frame, claim_template, threshold=threshold,
                          region=region) is not None:
            return SlotState.EMPTY
        return SlotState.UNKNOWN

    read.detector_built = True
    return read


class HiveClaimer:
    """Walks the row of hive slots and claims the first empty one.

    `frames()` returns the current frame; `read_prompt(frame)` returns a
    `SlotState`. Both are injected for the same reason `RouteRunner` takes
    `confirm_menu`: the decision about what is on screen belongs to the vision
    layer, and this layer must be runnable against a fake world.

    `approach` is called once before the sweep to get the character to the
    first slot. It is not written here because it is route data, not logic --
    `scripts/diag_hive_slot.py` reaches the corner with a 16.1-stud walk on `a`
    and two camera-left taps followed by two shift-locks. It aborts the sweep
    by returning `False`, or a result object whose `ok` is false --
    `RouteRunner.run`'s `RouteResult` is the obvious thing to pass, and it is
    truthy even when the route stopped early. A sweep that starts from an
    unknown position reads six wrong slots and claims one of them.
    """

    def __init__(self, vin, frames, read_prompt=prompt_unavailable,
                 slots: int = SLOT_COUNT, top_slot: int = TOP_SLOT,
                 hop_rise: float = HOP_RISE, hop_settle: float = HOP_SETTLE,
                 confirm_polls: int = CONFIRM_POLLS,
                 confirm_interval: float = CONFIRM_INTERVAL,
                 claim_key: str = CLAIM_KEY,
                 approach=None, on_reading=None):
        self.vin = vin
        self.frames = frames
        self.read_prompt = read_prompt
        self.slots = slots
        self.top_slot = top_slot
        self.hop_rise = hop_rise
        self.hop_settle = hop_settle
        self.confirm_polls = confirm_polls
        self.confirm_interval = confirm_interval
        # overridable because CLAIM_KEY is cited, not measured -- see its
        # comment -- but never into a key that can leave the server
        if str(claim_key).strip().lower() in FORBIDDEN_KEYS:
            raise ValueError(
                f"claim_key={claim_key!r} is not a key this module will press: "
                f"Escape opens the in-game menu that carries Leave, and Return "
                f"activates it. No hive prompt uses either")
        self.claim_key = claim_key
        self.approach = approach
        self.on_reading = on_reading or (lambda reading: None)

    # ---- looking ----------------------------------------------------------
    def read_slot(self, hops: int) -> SlotReading:
        """Look at the slot the character is standing at.

        Every look fires `on_reading`, including the repeated looks that
        confirm a claim -- watching the prompt turn into "Make Honey" is the
        interesting part, not just the sweep. `ClaimResult.readings` keeps one
        entry per slot inspected, so the two do not have the same length.
        """
        frame = self.frames()
        state = SlotState.UNKNOWN
        if frame is not None:
            state = self._as_state(self.read_prompt(frame))
        reading = SlotReading(self.top_slot - hops, hops, state)
        self.on_reading(reading)
        return reading

    @staticmethod
    def _as_state(value) -> SlotState:
        """Coerce a detector's answer, reading anything unrecognised as UNKNOWN.

        A detector returning a value this module does not know must read as
        "cannot tell" and never as "empty", because "empty" is the one answer
        that presses a key.
        """
        try:
            return SlotState(value)
        except ValueError:
            return SlotState.UNKNOWN

    # ---- moving -----------------------------------------------------------
    def _hop(self) -> None:
        """One sideways hop along the row: two jumps, as BeeTuxMacro does it.

        `jump; sleep 0.56; jump; sleep 1` -- the second jump is what carries
        the character across the gap. Timings are `routes.HOP_RISE` and
        `routes.HOP_SETTLE` rather than copies, so there is one place to
        correct them if they are ever measured here.

        The macro has the same hop twice with slightly different numbers:
        `from_corner_to_hive` (paths.sh:788-793) waits 0.56/1.0, and
        `find_hive` -- the sweep this module is the descendant of
        (utils.sh:130-152) -- waits 0.53/0.9. We take the longer pair, which
        is the one already in `routes.py`, because settling late costs half a
        second and reading the screen mid-hop costs a wrong slot.
        """
        self.vin.tap("space")
        time.sleep(self.hop_rise)
        self.vin.tap("space")
        time.sleep(self.hop_settle)

    # ---- claiming ---------------------------------------------------------
    def _confirm_claim(self, hops: int) -> SlotState:
        """Watch for the prompt to become "Make Honey", and report what it did.

        Returns the LAST state seen rather than a bool, so a refusal can say
        what it was looking at instead of "it did not work".
        """
        state = SlotState.UNKNOWN
        for poll in range(max(1, self.confirm_polls)):
            if poll:                       # no wait before the first look
                time.sleep(self.confirm_interval)
            state = self.read_slot(hops).state
            if state is SlotState.MINE:
                return state
        return state

    def claim(self) -> ClaimResult:
        """Sweep the row and claim the first empty slot.

        Stops at the first slot that is already ours -- there is nothing to
        claim there and it is the answer the caller wanted anyway.
        """
        result = ClaimResult()
        if not getattr(self.read_prompt, "detector_built", True):
            result.reason = (
                "no hive-prompt detector: the claim-hive and make-honey "
                "prompts have never been captured from a real frame, so "
                "there is nothing to match against. Refusing to press "
                f"{self.claim_key.upper()} blind — run "
                "scripts/learn_hive_prompt.py, crop both prompts out of the "
                "frames it saves, and pass template_reader(claim, honey)")
            return result

        try:
            if self.approach is not None and not _approach_ok(self.approach()):
                result.reason = ("the walk to the first hive slot failed, so "
                                 "the row was never read")
                return result

            for hops in range(self.slots):
                reading = self.read_slot(hops)
                result.readings.append(reading)

                if reading.state is SlotState.MINE:
                    result.ok = True
                    result.slot, result.hops = reading.slot, hops
                    result.confirmed_by = ("the Make Honey prompt — this slot "
                                           "was already ours")
                    return result

                if reading.state is SlotState.EMPTY:
                    return self._claim_here(reading, result)

                if hops < self.slots - 1:
                    self._hop()

            result.reason = self._nothing_found(result)
            return result
        finally:
            # The sweep only taps, so nothing should be down -- but a detector
            # that raises mid-hop must not leave the character jumping into
            # the honeycomb. Same call the panic key makes.
            self.vin.release_all()

    def _claim_here(self, reading: SlotReading, result: ClaimResult) -> ClaimResult:
        """Press the claim key at an empty slot, and believe it only if the
        prompt changes."""
        self.vin.tap(self.claim_key)
        after = self._confirm_claim(reading.hops)
        if after is SlotState.MINE:
            result.ok = True
            result.newly_claimed = True
            result.slot, result.hops = reading.slot, reading.hops
            result.confirmed_by = (f"pressing {self.claim_key.upper()} turned "
                                   f"the prompt into Make Honey")
            return result
        result.reason = (
            f"pressed {self.claim_key.upper()} at slot {reading.slot} and the "
            f"prompt never became Make Honey (last read: {after.value}). Not "
            f"reporting a claim that was not seen — re-run once the screen is "
            f"readable")
        return result

    def _nothing_found(self, result: ClaimResult) -> str:
        """Why the sweep ended empty-handed. Unreadable is not the same as full."""
        unreadable = [r for r in result.readings
                      if r.state is SlotState.UNKNOWN]
        if unreadable:
            where = ", ".join(str(r.slot) for r in unreadable)
            return (f"found no empty hive, but {len(unreadable)} of "
                    f"{len(result.readings)} slots could not be read "
                    f"(slots {where}) — the row may well have one")
        return (f"every one of the {len(result.readings)} slots in the row is "
                f"taken; this server has no free hive")


def claim_hive(vin, frames, read_prompt=prompt_unavailable, **kwargs) -> ClaimResult:
    """Claim a hive after joining. See `HiveClaimer` for the arguments.

    With no `read_prompt` this refuses without moving the character and
    explains what is missing, which is the intended behaviour until the
    prompts have been captured.
    """
    return HiveClaimer(vin, frames, read_prompt, **kwargs).claim()


# ---------------------------------------------------------------------------
# The detector that was missing
# ---------------------------------------------------------------------------
def _encode_png(image: np.ndarray) -> bytes:
    """Encode a crop the way `brain.vlm.VisionModel.ask` wants it."""
    import cv2
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("could not encode the panel crop as PNG")
    return buf.tobytes()


# MEASURED TRAP, and the reason the matching below is as fussy as it is.
# The five real frames that carry a notification panel all say:
#
#     "You've made 70,000,000 Honey"   (figure made up)
#
# A detector that answered MINE on the word "honey" would read that panel --
# which appears on JOIN, nowhere near a hive -- as "this slot is already ours",
# return `ok` without claiming anything, and hand the rest of the navigation
# layer a slot number that means nothing. So MINE requires the verb: "make
# honey" is the hive's prompt, "you've made ... honey" is a receipt, and the
# receipt is explicitly excluded before anything else is considered.
# MEASURED ON A REAL CLAIM, 2026-09-20, `var/claim/` -- these are no longer
# guesses at the wording. Standing on an unclaimed pad the panel reads exactly
#
#     "Claim Hive"          (drawn beside a boxed "E" glyph)
#
# and the instant E is pressed it becomes
#
#     "To Make Honey, Collect Pollen From Flower Fields"
#
# while the pad fills with the account's bees and takes the owner's name. The
# second string is a tutorial hint rather than the hive's own prompt, and it
# matches MINE only because it contains the words "make honey" -- which is
# correct here (it appears only once the hive is ours) but is a thinner reason
# than it looks. The hive's steady-state prompt at an owned hive has still not
# been photographed; when it is, add its exact words here.
# NOT THE BARE WORD "claim". MEASURED over every panel text quoted in
# var/night/run-*.log (audit 2026-09-26): 339 read 'Claim Hive', and the only
# other text with "claim" in it, twice, was the Vicious Bee stand's 'Turn in
# 250 Stingers to Claim a Vicious Bee (52/250)' -- which homing took for an
# empty pad (run-366 00:17:18) and walked a hive row that was not there.
CLAIM_WORDS = ("claim hive", "claim this hive")
MINE_WORDS = ("make honey", "convert")
NOT_A_PROMPT = ("you've made", "youve made", "you have made")
# ANOTHER PLAYER'S PROMPT WHERE THE FREE PAD'S SHOULD BE. MEASURED 2026-10-22
# 20:03-20:35 (var/night/run-1189..1200.log): all twelve claims of that loop
# read "Send Trade Request to <player>" -- ten at step 2, the step a good claim
# reads 'Claim Hive' at (runs 1172, 1180, 1201, 1204, 1210, 1246) -- and no
# 'Claim Hive' anywhere; each miss ended the run and the rejoin met the same
# player. ASSUMED: they stood at the free pad and the game showed their prompt in
# place of the pad's. Still UNKNOWN, never pressed; the miss names it.
PLAYER_PROMPT = "trade request"

TRANSCRIBE = "Transcribe the text in this image exactly. Reply with only the text."


def banner_reader(model, encode=_encode_png, question: str = TRANSCRIBE):
    """Read the hive prompt out of the game's top-centre notification panel.

    HOW IT WORKS, and why each half is the way it is.

    `vision.banner.find` locates the panel by shape and colour -- 12/12 correct
    on the real frames, no false positive on five other real screens. That part
    is deterministic and needs no model.

    What the panel SAYS is then read by a vision-language model, because the
    text varies and no letter templates exist in this repo. VALIDATED against
    ground truth on 2026-09-20: given the real banner crop, qwen2.5vl:7b
    returned "You've made 73,013,670\\nHoney" -- exact, commas and all -- and
    answered NO to the same crop taken from a frame with no panel. So the
    reader is trusted to transcribe, and is NOT trusted to interpret: the
    mapping from text to `SlotState` happens here, in code that can be read.

    `model` is duck-typed (anything with `.ask(png_bytes, question)` returning
    an object with `.text`, or None) so `act` does not import `brain`.

    Anything that is not recognisably one of the two prompts returns UNKNOWN,
    never TAKEN and never EMPTY. UNKNOWN makes the sweep move on and say it
    could not read the slot; EMPTY is the answer that presses a key.
    """
    def read(frame: np.ndarray) -> SlotState:
        from ..vision import banner
        panel = banner.find(frame)
        if panel is None:
            return SlotState.UNKNOWN
        try:
            answer = model.ask(encode(panel.crop(frame)), question)
        except Exception:
            # A model that is down must not stop the sweep with a traceback;
            # it must read as "cannot see", which is what UNKNOWN means.
            return SlotState.UNKNOWN
        text = getattr(answer, "text", answer)
        if not isinstance(text, str) or not text.strip():
            return SlotState.UNKNOWN
        low = " ".join(text.lower().split())
        if any(phrase in low for phrase in NOT_A_PROMPT):
            return SlotState.UNKNOWN          # the join receipt, not a prompt
        if any(phrase in low for phrase in MINE_WORDS):
            return SlotState.MINE
        if any(phrase in low for phrase in CLAIM_WORDS):
            return SlotState.EMPTY
        return SlotState.UNKNOWN

    read.detector_built = True
    return read


# ---------------------------------------------------------------------------
# The sequence that actually worked
# ---------------------------------------------------------------------------
# PROVEN LIVE, 2026-09-20 (`var/claim/`). It is written down as a function
# rather than left in a script because claiming is not a one-off errand -- it
# has to happen on EVERY join, before anything else, or the account has no
# bees and the whole session collects nothing.
#
# Why it looks around instead of walking a recorded route: the recorded
# approach (`from_corner_to_hive` plus a hop per slot) walks off toward the
# Shop, which is what the six sweep frames show. Turning on the spot costs a
# few seconds, needs no map, and cannot drift.
LOOK_STEPS = 8                 # MEASURED: 8 camera taps is one full turn
LOOK_SETTLE = 0.35
WALK_STEP_SECONDS = 1.0
MAX_WALK_STEPS = 14
# HALF A TURN, in camera taps. `.` is RotRight (natro_macro.ahk sc034)
# and eight taps make a full turn -- the same figure `act/homing` and
# `act/bearvisit` measured for the same key. Four of them face the other way,
# which is what the claim sweep's second pass needs.
TAPS_PER_HALF_TURN = 4

CLAIM_CONFIRM_POLLS = 10
CLAIM_CONFIRM_INTERVAL = 0.5


def sweep_and_claim(vin, frames, read_text, *, bearing_hint=None,
                    look_steps: int = LOOK_STEPS,
                    walk_step_seconds: float = WALK_STEP_SECONDS,
                    max_walk_steps: int = MAX_WALK_STEPS,
                    claim_key: str = CLAIM_KEY, claim_if_empty: bool = True,
                    start_taps: int = 0, box_legs: int = 0,
                    row_slots: int = 0, row_step_seconds: float = 1.0,
                    row_live: bool = True, panel_seen=None,
                    sleep=time.sleep, clock=time.monotonic,
                    on_note=None) -> ClaimResult:
    """Find an unclaimed hive pad, walk to it, and claim it.

    `read_text(frame)` returns the text of the top-centre panel, or None when
    there is no panel. `banner_reader`'s two halves are deliberately split
    here: this function needs the WORDS, because it reports them.

    `bearing_hint(frame) -> (pixels_right_of_centre, strength)` is optional
    and is only used to choose which way to look first. `hive_bearing` is the
    one to pass when heading home; the free-pad red beam is the one to pass
    when hunting an unclaimed pad, and it reads 0 once every pad is taken. The game
    marks free pads with a red beam, but a red billboard hangs over the
    character and a decorative fan sits near the hives, so this is a hint and
    never a decision. The panel is the decision.

    `claim_if_empty=False` turns this into "walk to MY hive and confirm it",
    which is what the return leg of a farm cycle needs. MEASURED 2026-09-20:
    the panel reads "Make Honey" while standing on an owned hive -- six reads
    over fifteen seconds, all identical -- disappears when the character steps
    off, and comes back when it steps on. So arrival at the hive is something
    the bot can SEE rather than something a route timing implies.

    That matters because the route does not always land. The owner watched a
    return leg jump behind a ledge and miss the glide down entirely: "it
    jumped behind the ledge so id didnt even glide down". A cycle that cannot
    tell it missed goes on to press the interact key wherever it happens to be
    standing, which is how one of them opened a Polar Bear quest dialogue.

    With claiming off, an empty pad is reported and walked PAST rather than
    taken -- claiming a second hive on the way home is not a recovery.

    `start_taps` turns the camera that many more taps before the walk, so a
    retry walks a different line through the same spawn (`retry_start_taps`).
    `box_legs` > 0 adds a third search when both straight passes miss: a
    widening box like `find_my_hive`'s, reading and claiming exactly as the
    passes do.

    `row_slots` > 0 searches the hive row where the pad should be: when the
    first pass reaches step ROW_AT_STEP with nothing claimed, it holds `a`
    past that many pads, `d` past twice as many and `a` back to the line,
    counting a pad each time the panel goes and comes back (`panel_seen(frame)`,
    the cheap is-there-a-panel test; the words are read only at a pad), and
    claims as the passes do; then the first pass goes on. `row_step_seconds`
    is one slot's walk: a side ends ROW_GAP_SLOTS of them after its last
    panel, and the next side first walks that tail back. Only on the
    unturned line (`start_taps` 0), the one that faces the row.
    `row_live=False` only says what it would do.

    Presses only `period` (camera), `w`/`a`/`d` (walk) and `claim_key`. Never resets:
    a reset is a death and death sends every bee home.
    """
    result = ClaimResult()
    note = on_note or (lambda text: None)
    seen = panel_seen or (lambda frame: bool(read_text(frame)))

    def grab():
        """A frame, or None. Capture failures are transient, not fatal.

        MEASURED, and it ended a live run: `capture failed: compositor offered
        no supported format` came out of screencopy mid-sweep, propagated
        through here and killed the whole session. Screencopy negotiates its
        format per frame, and a frame arriving while the game is changing what
        it presents can fail on its own and succeed on the next one.

        A missing frame already has a meaning everywhere else in this module
        -- it reads as "cannot see", which makes the sweep move on and say so.
        Turning it into a traceback was the only place that disagreed.
        """
        try:
            return frames()
        except Exception as exc:
            note(f"capture failed ({exc}); carrying on")
            return None

    def look() -> tuple[int, int]:
        frame = grab()
        if frame is None or bearing_hint is None:
            return (0, 0)
        return bearing_hint(frame)

    try:
        # ---- one full turn, remembering where the most red was ----------
        best = (-1, 0)
        for step in range(max(1, look_steps)):
            _, red = look()
            if red > best[0]:
                best = (red, step)
            vin.tap("period")
            result.taps += 1
            sleep(LOOK_SETTLE)
        if bearing_hint is None:
            # SAY SO RATHER THAN PRINT A FICTION. With no hint `look()`
            # returns (0, 0) every time, so `best` stays at step 0 and this
            # printed "strongest bearing at 0° (0 px)" in EVERY log all night
            # -- which reads like a measurement of an empty screen and is
            # actually "nothing was measured". `w` is camera-relative, so with
            # no hint the sweep walks wherever the camera happens to point.
            note("no bearing hint wired in, so the direction to walk was not "
                 "measured — going whichever way the camera already faces")
        else:
            note(f"strongest bearing at {best[1] * 45}° ({best[0]} px)")
        for _ in range(best[1]):
            vin.tap("period")
            result.taps += 1
            sleep(LOOK_SETTLE)
        if start_taps:
            note(f"the last claim here missed, so this one starts "
                 f"{start_taps * 45}° round from it")
            for _ in range(start_taps):
                vin.tap("period")
                result.taps += 1
                sleep(LOOK_SETTLE)

        # ---- walk that way, reading the panel every step -----------------
        # ---- walk that way; if nothing, turn round and walk back --------
        #
        # THE SWEEP ONLY EVER WENT ONE WAY, and `w` is camera-relative, so
        # when the hive wall is not in view the direction is whatever the
        # camera happened to face. If the pads are behind the character it
        # walks AWAY from them for fourteen steps and reports that there are
        # none. MEASURED 2026-09-23: 4 of runs 250-309 died this way, each
        # after 42 seconds -- "walked 14 steps without the claim panel
        # appearing" -- and a failed claim ends the whole attempt, because
        # without a hive there are no bees and nothing would be collected.
        # The successful claims find the pad at step 2.
        #
        # The second pass turns 180 degrees and walks twice the budget, which
        # covers the ground it started on and the same distance the other
        # way. It is bounded, it presses only movement and the camera, and it
        # runs only when the first pass has already failed.
        last_text = [""]

        def act_on(text, tag: str, step: int) -> bool:
            """Note one panel read and act on it: True once the claim is
            settled (ours, claimed, or a press that never confirmed)."""
            if not text:
                return False
            state = _state_of(text)
            note(f"{tag}step {step}: panel says {text!r} -> {state.value}")
            if PLAYER_PROMPT in " ".join(str(text).lower().split()):
                result.player_at = result.player_at or f"{tag}step {step}"
            result.readings.append(
                SlotReading(slot=-1, hops=step, state=state))

            if state is SlotState.MINE:
                result.ok = True
                result.hops = step
                result.confirmed_by = f"the panel already read {text!r}"
                return True
            if state is SlotState.EMPTY and not claim_if_empty:
                note(f"{tag}step {step}: an unclaimed pad, walking past it")
                return False
            if state is SlotState.EMPTY:
                if vin.tap(claim_key) is False:
                    # HELD BACK BY THE OWNER'S PAUSE (brain/controls
                    # STALE_AFTER_A_WAIT): this panel is from before it.
                    # Read it again where we stand and press only on what
                    # it says now; anything else walks on, looking.
                    note(f"{tag}step {step}: the {claim_key.upper()} was "
                         f"held back by a Pause — reading the panel again")
                    again = grab()
                    text = read_text(again) if again is not None else None
                    state = _state_of(text) if text else SlotState.UNKNOWN
                    if state is SlotState.MINE:
                        result.ok = True
                        result.hops = step
                        result.confirmed_by = f"the panel already read {text!r}"
                        return True
                    if state is not SlotState.EMPTY or vin.tap(claim_key) is False:
                        return False
                for poll in range(CLAIM_CONFIRM_POLLS):
                    sleep(CLAIM_CONFIRM_INTERVAL)
                    after = grab()
                    later = read_text(after) if after is not None else None
                    if later and _state_of(later) is SlotState.MINE:
                        result.ok = True
                        result.newly_claimed = True
                        result.hops = step
                        result.confirmed_by = (
                            f"pressing {claim_key.upper()} turned the "
                            f"panel into {later!r}")
                        return True
                result.reason = (
                    f"pressed {claim_key.upper()} at a pad reading "
                    f"{text!r} and the panel never confirmed — not "
                    f"reporting a claim that was not seen")
                return True          # settled, even though it failed
            return False

        def one_pass(budget: int, tag: str, key: str = "w",
                     seconds: float = walk_step_seconds, first: int = 1):
            for step in range(first, first + budget):
                with vin.held(key):
                    sleep(seconds)
                sleep(0.4)
                frame = grab()
                if frame is None:
                    continue
                text = read_text(frame)
                last_text[0] = text or ""
                if act_on(text, tag, step):
                    return True
            return False

        # ---- along the row, counting pads by the panel's edges ------------
        # A TIMED SLOT STEP OFTEN STOPS BESIDE THE PAD, NOT ON IT. A pad's
        # prompt shows only a few studs either side of its middle
        # (MEASURED: 140 of 791 holds onto our own pad from the spawn point,
        # var/night/run-*.log, lost the prompt between the sighting and the
        # stop -- hiverow polling every 0.1 s), and the same timed walk from
        # the spawn point to the pad took 1.0-2.6 s, mean 1.8, sd 0.27 (CV
        # 15%, the same runs). A 36.8-stud slot timed at walkspeed scatters
        # about 5.5 studs that way. Replayed (docs/pending/claimedge.md):
        # the timed slots claimed a free pad on 57-64% of the 22 Oct joins at
        # that scatter (97-99% at 5%), the edges on 100% at either.
        # So the key is held and the panel watched (hiverow.find_along_row,
        # the walk home's closed loop): a pad is passed when its panel goes
        # and the next one comes up. MEASURED that the box test sees exactly
        # that: banner.find found the free pad's 'Claim Hive' on
        # var/claim/walk_02.png, nothing on walk_01.png (the step before
        # it) nor on any of the 144 sweep frames of the 22 Oct misses; the
        # 'Claim Hive' and 'Send Trade Request' crops in var/vlm_samples are
        # its boxes (283 px wide); 2.2 ms a 1920x1080 frame. Released on
        # sight, the overrun stepped back (ROW_OVERRUN_TRIES), then the words
        # read and acted on as a pass's are.
        tail = [0.0]           # seconds walked past the last pad by the side before

        def strafe(tag: str, key: str, pads: int) -> bool:
            passed, gone = 0, [False]

            def edge(frame) -> bool:
                here = bool(seen(frame))
                gone[0] = gone[0] or not here
                return gone[0] and here

            # ponytail: a bounded number of holds; a pad lost after the stop
            # or a receipt costs one without counting
            for _ in range(2 * pads + 2):
                if passed >= pads:
                    break
                bound = ROW_GAP_SLOTS * row_step_seconds + tail[0]
                gone[0], tail[0] = False, 0.0
                found = hiverow.find_along_row(
                    vin, grab, edge, walkspeed=ROW_SLOT_STUDS / max(1e-6, row_step_seconds),
                    holds=((key, tag.strip(), bound),), tries=ROW_OVERRUN_TRIES,
                    sleep=sleep, clock=clock)
                if not found.direction:
                    # no panel within the gap: the row ends this way (or
                    # the pads here show nothing); the next side walks
                    # this tail back before its own gap counts
                    tail[0] = bound
                    break
                if not found.ok:
                    # slid past it: the next hold this way meets it again
                    # when the steps back left us short of it, so it is
                    # counted when its words are read
                    note(f"{tag}a panel came up after {found.seen_after:.1f}s "
                         f"and was gone again after the stop — walking on")
                    continue
                frame = grab()
                text = read_text(frame) if frame is not None else None
                low = " ".join(str(text or "").lower().split())
                # ponytail: a join receipt is not a pad, a player's trade
                # prompt counts as one (it stood at their pad on 22 Oct); a
                # taken pad whose owner is away may show nothing [ASSUMED]
                # and is then walked past uncounted, inside the budget.
                if any(p in low for p in NOT_A_PROMPT):
                    note(f"{tag}a panel came up after {found.seen_after:.1f}s "
                         f"that is no pad's: {text!r} — walking on")
                    continue
                passed += 1
                note(f"{tag}pad {passed} after {found.seen_after:.1f}s"
                     + (f" and {found.corrections} correction(s)"
                        if found.corrections else ""))
                if act_on(text, tag, passed):
                    return True
            return False

        # ---- at the row, search along it ----------------------------------
        # THE PAD STRAIGHT AHEAD CAN BE SOMEONE ELSE'S. MEASURED 2026-10-22
        # (runs 1189-1200, one private server, 12 joins in a row): step 2 read
        # "Send Trade Request to <a player>" every time -- another player
        # standing at the pad straight ahead of spawn, which they owned -- and
        # the sweep walked on through it, 14 steps out and 28 back, with no
        # other pad on that line. The spawn frames of those joins
        # (var/badges/20261022-200419) show the two free pads, red arrows on
        # them, either side of theirs. Natro walks the row the same way
        # (nm_claimHiveSlot's old system: 9.2 tiles a slot, `a`/`d`).
        row_here = (row_slots > 0 and not start_taps
                    and max_walk_steps > ROW_AT_STEP)
        if not row_here:
            if one_pass(max_walk_steps, ""):
                return result
        else:
            if one_pass(ROW_AT_STEP, ""):
                return result
            plan = (f"hold left past {row_slots} pad(s), right past "
                    f"{2 * row_slots} and left past {row_slots} back, counting a "
                    f"pad each time the panel goes and comes back, stopping on "
                    f"'Claim Hive'; a side ends "
                    f"{ROW_GAP_SLOTS * row_step_seconds:.1f}s after its last panel")
            if not row_live:
                note(f"claim row would: search the hive row from step "
                     f"{ROW_AT_STEP} — {plan} — the panel here read "
                     f"{last_text[0]!r}")
            else:
                note(f"no free pad and none of ours at step {ROW_AT_STEP} "
                     f"(the panel read {last_text[0]!r}) — searching the hive "
                     f"row: {plan}")
                for tag, key, n in (("row left ", "a", row_slots),
                                    ("row right ", "d", 2 * row_slots),
                                    ("row back ", "a", row_slots)):
                    if strafe(tag, key, n):
                        result.hops = ROW_AT_STEP
                        return result
            if one_pass(max_walk_steps - ROW_AT_STEP, "", first=ROW_AT_STEP + 1):
                return result

        note(f"walked {max_walk_steps} steps and saw no pad — turning round "
             f"and walking back past where we started")
        for _ in range(TAPS_PER_HALF_TURN):
            vin.tap("period")
            result.taps += 1
            sleep(LOOK_SETTLE)
        if one_pass(max_walk_steps * 2, "back "):
            return result

        # ---- a widening box, for pads beside the line ---------------------
        # Each leg turns a quarter first, so the first leg leaves the line the
        # two passes walked.
        if box_legs > 0:
            note(f"no pad on that line either way — walking a {box_legs}-leg box")
            for leg in range(box_legs):
                for _ in range(QUARTER_TURN_TAPS):
                    vin.tap("period")
                    result.taps += 1
                    sleep(LOOK_SETTLE)
                if one_pass(BOX_FIRST_LEG + leg, f"box {leg + 1} "):
                    return result

        result.reason = (f"walked {max_walk_steps} steps one way and "
                         f"{max_walk_steps * 2} back"
                         + (f" and a {box_legs}-leg box" if box_legs > 0 else "")
                         + " without the claim panel appearing"
                         + (f"; another player's trade prompt was read at "
                            f"{result.player_at}, where a free pad's 'Claim Hive' "
                            f"usually is" if result.player_at else ""))
        return result
    finally:
        vin.release_all()


def _state_of(text: str) -> SlotState:
    """Map panel text to a slot state. Same rules as `banner_reader`."""
    low = " ".join(str(text).lower().split())
    if any(p in low for p in NOT_A_PROMPT):
        return SlotState.UNKNOWN
    if any(p in low for p in MINE_WORDS):
        return SlotState.MINE
    if any(p in low for p in CLAIM_WORDS):
        return SlotState.EMPTY
    return SlotState.UNKNOWN


# ---------------------------------------------------------------------------
# After a missed claim: a different line next time, and a box
# ---------------------------------------------------------------------------
# A MISSED CLAIM REPEATS ITSELF. A failed claim ends the run (brain/farm), the
# watchdog rejoins, and a fresh join stands at the same spawn facing the same
# way; the sweep has no hint, so every retry walked the same line and missed
# the same way. MEASURED 2026-10-22: runs 1189-1200 looped on the claim.
#
# So each claim is written down, and while the claims before it missed (within
# RETRY_WINDOW_S), the next one turns first and walks a different line through
# spawn: 0, 90, 45, then 135 degrees, then round again. And a claim whose two
# straight passes both miss walks a widening box (CLAIM_BOX_LEGS).
#
# LOOK-ONLY until CLAIM_RETRY_LIVE: the claim logs what it would do (the
# turn and the box) and walks as before.
CLAIM_RETRY_LIVE = False
RETRY_START_TAPS = (0, 2, 1, 3)        # taps of 45 degrees: four different lines
RETRY_WINDOW_S = 30 * 60
CLAIM_BOX_LEGS = 6
CLAIM_HISTORY_KEEP = 20

# THE ROW SEARCH (sweep_and_claim `row_slots`). LOOK-ONLY until CLAIM_ROW_LIVE:
# it logs "claim row would: ..." at step ROW_AT_STEP and walks as before.
# MEASURED: 621 of 627 fresh-join claims in var/night/run-*.log (to run 1210)
# found the pad at step 2 -- the row is two steps ahead of spawn.
# Natro's slot spacing (natro_macro.ahk nm_claimHiveSlot, nm_Walk(9.2,
# LeftKey) per slot; 4 studs a tile, act/hiverow; read 2026-10-26), timed by
# the caller's walkspeed. Natro's slotMove puts spawn facing slot 3 of 6, two
# slots to its right and three to its left.
# The slot is no longer walked by time: the panel's edges count the pads
# (sweep_and_claim `strafe`), and the timed slot only bounds a side.
# ponytail: 3 pads each way covers either side. ROW_GAP_SLOTS of walk with
# no panel ends a side: 2.5 walks past one pad that shows nothing (a taken
# pad whose owner is away, ASSUMED to show no prompt) and stops a side that
# ran off the row's end before it reaches the pads' far side.
CLAIM_ROW_LIVE = False
ROW_AT_STEP = 2
ROW_SLOT_STUDS = 9.2 * 4.0
CLAIM_ROW_SLOTS = 3
ROW_GAP_SLOTS = 2.5
# The overrun after the stop: Natro's 1.5-tile steps back, at most this many.
# MEASURED (var/night/run-*.log, 794 holds onto our pad from the spawn point,
# hiverow overrun="steps"): 143 lost the prompt after the stop, 136 had it
# back after one step and 4 after two; the other 3 (run-512, 529, 534) never
# had it back in all 10 steps, so more steps would not have saved them. Two
# steps is 12 studs, well short of the pad before (36.8 studs a slot).
ROW_OVERRUN_TRIES = 2


def retry_start_taps(history, now: float) -> int:
    """Camera taps to turn before the next claim's sweep: the misses in a row
    at the end of `history` (newest last), counting only claims within
    RETRY_WINDOW_S of `now`, pick the line."""
    misses = 0
    for row in reversed(list(history or [])):
        try:
            at, ok = float(row["at"]), bool(row["ok"])
        except (KeyError, TypeError, ValueError):
            break
        if ok or now - at > RETRY_WINDOW_S:
            break
        misses += 1
    return RETRY_START_TAPS[misses % len(RETRY_START_TAPS)]


def claim_retry_would(start_taps: int, box_legs: int) -> str:
    """The look-only line for CLAIM_RETRY_LIVE. Both clauses always: run-1250
    logged "claim retry would: and walk a 6-leg box..." when the turn clause
    was dropped for start_taps 0 (also the fourth miss in a row, so 0 does not
    mean "no miss")."""
    turn = (f"start {start_taps * 45}° round (the last claim missed)" if start_taps
            else "start facing the usual way (no turn)")
    return f"claim retry would: {turn}, and walk a {box_legs}-leg box if both passes miss"


# AND THE REJOIN AFTER A MISS IS SPACED OUT (ROADMAP A7). Runs 1189-1200 read
# another player's trade prompt where the pad's is (PLAYER_PROMPT): a new line
# through spawn does not move them, and twelve rejoins in 32 minutes, each one
# a Wealth Clock streak reset, did not either. run_farm waits
# platform/startfails.backoff_s(misses) after a miss before handing back to
# the watchdog, and says it on Telegram once a streak.
def misses_in_a_row(history, now: float, gap_s: float) -> int:
    """The claims that missed in a row at the end of `history` (newest last),
    each within `gap_s` of the one after it and the newest within `gap_s` of
    `now`: a longer gap means the bot was stopped in between, a new streak."""
    misses, later = 0, now
    for row in reversed(list(history or [])):
        try:
            at, ok = float(row["at"]), bool(row["ok"])
        except (KeyError, TypeError, ValueError):
            break
        if ok or later - at > gap_s:
            break
        misses, later = misses + 1, at
    return misses


def load_claim_history(path) -> list:
    """The claims written by `record_claim`, oldest first; [] when there is no
    readable file. A broken file must never stop a claim."""
    import json
    from pathlib import Path
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def record_claim(path, ok: bool, start_taps: int, now: float) -> None:
    """Add one claim to the history, keeping the newest CLAIM_HISTORY_KEEP.
    Errors are swallowed: the record only steers the next retry."""
    import json
    from pathlib import Path
    rows = load_claim_history(path)
    rows.append({"at": round(float(now), 1), "ok": bool(ok),
                 "start_taps": int(start_taps)})
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(rows[-CLAIM_HISTORY_KEEP:]), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Finding the hive when the camera is pointing the wrong way
# ---------------------------------------------------------------------------
# MEASURED 2026-09-20 across real frames, and it is a wide margin:
#
#     standing on the hive        400,142 / 458,766 / 522,511 yellow px
#     stepped off it              106,447
#     walking up to a pad         256,579
#     at spawn, hive off-centre    88,331
#     in the Pine Tree field         8,837 / 11,840
#
# The hive row is walled in saturated yellow honeycomb and nothing else in the
# places this bot goes is. Ten to fifty times the field's yellow is not a
# threshold anyone has to tune.
#
# WHY IT IS NEEDED. A respawn restores the CAMERA as well as the position
# (measured earlier at 0.99 similarity), so resetting home from Pine Tree
# leaves the character standing at the hive still facing Pine Tree -- and `w`
# is camera-relative, so it walks away. The red free-pad beam cannot help once
# every pad is claimed: MEASURED 0 red pixels on exactly those runs. Turning
# to face the most yellow points the character at the hive it is standing next
# to.
# Defined in vision/notice.py, which is where a colour measurement belongs;
# `act` may import `vision` but not the other way round.
HIVE_YELLOW_MIN = 500


# The world crop hive_bearing reads, and the row a yellow blob must reach to
# count as the hive. The hive's walls are the one yellow thing in the game
# tall enough to run off the top of the world at this camera; a honey token,
# a pad, a sunflower or a dandelion sits on the ground and never does.
# MEASURED 2026-09-22 (var/homing/attempt-240): the honey token that read
# 268,855 yellow px had its top at row 438; every hive blob in every hive
# frame starts at row 170, the crop's edge.
WORLD_TOP, WORLD_BOTTOM = 170, 900
REACHES_TOP_BY = 3
# A blob smaller than this touching the top is a stray -- part of the HUD's
# shadow, a sliver of something. MEASURED noise floor with this rule, S <= 240
# and the blob minimum: 0-15,000 px in fields with no hive in view, against
# 22,000-54,000 for the hive at the horizon.
HIVE_BLOB_MIN = 200


def hive_bearing(frame: np.ndarray) -> tuple[int, int]:
    """(pixels right of centre, yellow pixel count) for the hive structure.

    The count is the useful half: it separates "the hive is in view" from "it
    is not". The bearing centres it once it is.

    WHAT IS COUNTED. Honeycomb-coloured pixels (vision/notice.HIVE_YELLOW)
    that belong to a blob reaching the top of the world crop. Colour alone
    could not do it -- MEASURED 2026-09-22 19:46 (run 237) and 20:00 (run
    240): a honey token lying in front of the camera read 268,855 "hive"
    pixels and the loop stepped toward it; sunflowers read 40,000; the
    Pineapple Patch's pineapple 80,000. None of them reaches the top of the
    world. The hive's walls always do (26 frames, 0 exceptions), from the
    field where they show as a band 40-120 px tall along the crop's edge to
    the pad where they fill it. The same rule drops the pad itself, the big
    yellow disc under the character, which is why standing on our own pad now
    reads about 168,000 rather than 522,511: the walls, not the floor.
    """
    import cv2
    from ..vision.notice import HIVE_YELLOW
    if frame is None or frame.size == 0:
        return (0, 0)
    hsv = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2HSV)
    lo, hi = HIVE_YELLOW
    mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
    mask[:WORLD_TOP, :] = 0          # HUD and the notification panel
    mask[WORLD_BOTTOM:, :] = 0       # hotbar and buff icons
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.zeros(mask.shape, dtype=bool)
    for k in range(1, n):
        top, area = int(stats[k, cv2.CC_STAT_TOP]), int(stats[k, cv2.CC_STAT_AREA])
        if top <= WORLD_TOP + REACHES_TOP_BY and area >= HIVE_BLOB_MIN:
            keep |= labels == k
    ys, xs = np.nonzero(keep)
    if len(xs) < HIVE_YELLOW_MIN:
        return (0, int(len(xs)))
    return (int(np.median(xs)) - frame.shape[1] // 2, int(len(xs)))


# ---------------------------------------------------------------------------
# Finding your own hive when the route home missed
# ---------------------------------------------------------------------------
# WHY THIS EXISTS RATHER THAN sweep_and_claim. MEASURED over a full night:
# `sweep_and_claim(claim_if_empty=False)` succeeded **0 times out of 4** on the
# return leg, while the rejoin fallback worked every time it was asked for. So
# every bank all night cost a game relaunch -- about 40 s, plus the launch
# itself failed 8 times in 95 attempts.
#
# The decision rule was never the problem: the panel says "Make Honey" while
# standing on your own hive, and that is ground truth. The SEARCH is the
# problem. `sweep_and_claim` picks one bearing and then walks up to fourteen
# steps in that single direction -- far enough to stride past the pad row and
# keep going -- and the bearing it picks comes from a hint that DESIGN 8a
# records as unreliable (a large yellow blob fires at the hive 24% of the time
# and in the Pineapple Patch 6%). A frame captured mid-failure showed the
# character a few studs from its own hive with the pads plainly in view.
#
# The case that needs covering is "the pad is beside or behind us", and a
# straight line cannot cover it. This walks a widening box instead: a few steps
# forward, quarter turn, a few steps, quarter turn, each leg slightly longer
# than the last, reading the panel after every single step. The same total
# budget therefore sweeps an area rather than a line.
#
# IT PRESSES NOTHING. Movement and camera only -- no interact key, no clicks.
# The panel decides, and the caller decides what to do about it.

QUARTER_TURN_TAPS = 2          # LOOK_STEPS = 8 taps is one full turn
BOX_LEGS = 6                   # four sides plus two, so it overlaps its start
BOX_FIRST_LEG = 2              # steps in the first leg; each leg grows by one


def find_my_hive(vin, frames, read_text, *, walk_step_seconds: float = WALK_STEP_SECONDS,
                 legs: int = BOX_LEGS, first_leg: int = BOX_FIRST_LEG,
                 sleep=time.sleep, on_note=None) -> ClaimResult:
    """Search outward for the pad the panel calls ours. Presses no keys.

    Returns a `ClaimResult` whose `ok` means the panel actually read "Make
    Honey" -- not that the search finished. `hops` is how many steps it took,
    which is the number worth watching: if it is usually large the box is the
    wrong shape, and if it is usually small the route home is nearly landing.
    """
    result = ClaimResult()
    note = on_note or (lambda text: None)

    def look() -> SlotState:
        try:
            frame = frames()
        except Exception as exc:
            note(f"capture failed ({exc}); carrying on")
            return SlotState.UNKNOWN
        if frame is None:
            return SlotState.UNKNOWN
        try:
            text = read_text(frame)
        except Exception as exc:
            note(f"could not read the panel ({exc}); carrying on")
            return SlotState.UNKNOWN
        if not text:
            return SlotState.UNKNOWN
        state = _state_of(text)
        if state is SlotState.MINE:
            result.confirmed_by = f"the panel read {text!r}"
        return state

    steps = 0
    # Check where we already are FIRST. The route home sometimes lands on the
    # pad, and walking away from it to begin a search would be perverse.
    if look() is SlotState.MINE:
        result.ok = True
        result.hops = 0
        note("already standing on it")
        return result

    try:
        for leg in range(legs):
            for _ in range(first_leg + leg):
                with vin.held("w"):
                    sleep(walk_step_seconds)
                sleep(0.25)
                steps += 1
                state = look()
                result.readings.append(
                    SlotReading(slot=-1, hops=steps, state=state))
                if state is SlotState.MINE:
                    result.ok = True
                    result.hops = steps
                    note(f"found it after {steps} step(s)")
                    return result
            for _ in range(QUARTER_TURN_TAPS):
                vin.tap("period")
                result.taps += 1
                sleep(LOOK_SETTLE)
            note(f"leg {leg + 1}/{legs} done ({steps} steps so far); turning")
    except Exception as exc:                 # a search must not end a run
        result.reason = f"the search stopped early: {exc}"
        return result

    result.reason = (f"walked a {legs}-leg box, {steps} steps, without the "
                     f"panel ever reading 'Make Honey'")
    return result
