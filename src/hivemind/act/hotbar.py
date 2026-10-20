"""The hotbar: which slot holds what, and pressing one of them.

WHAT IT IS FOR. `gather.use_sprinklers` has been a switch wired to nothing
since the beginning, under the note "the bot has never seen the sprinkler
placement UI". It has now seen it, in a frame it had already saved.

MEASURED 2026-09-23 from `var/places/honey_dispenser-041002.jpg`, the hotbar
across the bottom of the screen at 1920x1080:

    slot 1   a sprinkler -- a canister with water spraying from it,
             drawn with the key hint `[One]` in its corner
    slot 2   gumdrops, `x283`, key hint `[Two]`, with `AUTO: OFF`
             printed underneath
    slots 3-7  empty

The key hints are DRAWN ON THE SLOTS by the game, so the mapping from slot to
key is read rather than assumed. `data/knowledge/account.yaml` already
recorded `sprinkler_builder: true` from an inventory screenshot on 2026-09-20;
this is where it lives on screen.

WHAT THIS PRESSES AND WHAT IT DOES NOT. A hotbar number equips or uses the
item in that slot and nothing else -- it cannot open a menu, leave the game or
spend honey. This module will press a slot it has been told to press and
photograph what happened. It will NOT touch slot 2: gumdrops are a consumable
the player may hold hundreds of, its `AUTO: OFF` is the player's setting, and spending someone's
consumables unasked is not this bot's to do.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field

from ..vision import screen

# Where the hotbar sits at 1920x1080 (x0, y0, x1, y1). Measured from the frame
# above: the row of slots spans roughly y 950-1050 and starts at x 690. It was
# kept as fractions of the frame (0.35-0.72 across, 0.88-0.97 down: these same
# pixels at 1920x1080), but the bar does not stretch with the frame: it hangs
# from the bottom middle at a fixed size (vision/screen, MEASURED at 1280x720).
HOTBAR_BOX = (672, 950, 1382, 1047)

# Slot -> the key that selects it, exactly as the game draws the hint.
SLOT_KEYS = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7"}

# What each slot held when it was last looked at. Kept here rather than
# guessed at the call site, and deliberately sparse: a slot nobody has read is
# absent, not empty.
KNOWN_SLOTS = {1: "sprinkler", 2: "gumdrops"}

# Slots this will never press on its own. Gumdrops are the owner's
# consumable; `AUTO: OFF` beside them is their setting.
NEVER_PRESS_SLOTS = (2,)

SETTLE_SECONDS = 1.0

# A SLOT THE GAME TOOK DIMS, AND SHOWS ITS COUNTDOWN ("0s"). A slot it did not
# take is drawn as it was. MEASURED 2026-09-28 on the last 40 sprinkler presses
# (var/hotbar, the before/after frame of each): the mean brightness (HSV V,
# 0-255) inside slot 1 fell 41-46 on the 29 presses the game took, and 0-3 on
# the 11 it did not -- 9 of those 11 with Roblox's own "Capture saved" toast on
# screen after the press, and none of the 29. `changed_fraction` could not tell
# them apart: 22 of the presses logged "placed" had moved 0-3% of the strip.
SLOT1_INNER = (712, 985, 752, 1035)      # x0, y0, x1, y1 at 1920x1080
SLOT_PITCH = 76                          # slot n is (n-1) of these to the right
FRAME_SIZE = (1920, 1080)
USED_MIN_DROP = 20.0


# ROBLOX'S CAPTURES SHORTCUT IS ALT+1 ("The default keybind for taking screenshots
# using Roblox Capture is Alt + 1", robloxden.com/guides/roblox-screenshot, read
# 2026-09-29), and slot 1 is the sprinkler. The owner, 2026-09-29: placing a
# sprinkler took a screenshot instead. A Roblox that still believes Alt is
# down -- it saw an Alt go down while its window had the keyboard (an Alt+Tab
# away) and never saw it come up -- turns every "1" into a Capture. MEASURED on
# the kept presses (var/hotbar): 72 of 658 slot-1 presses have its "Capture
# saved" toast after them, in runs -- every press 13:08-15:00 of run-520 until a
# rejoin restarted Roblox, and three at a time 23:45:56-23:46:04 (a press and its
# two re-presses) -- while the bot's own keyboard has no Alt to hold. The toast
# is a dark bar at the top middle, its words at (784-895, 102)
# (hotbar-slot1-after-131709.jpg); the "View" button beside them is never
# clicked.
CAPTURE_TOAST_BOX = (740, 80, 1180, 130)
CAPTURE_WORD = "capture"
TESSERACT, LANGUAGE, OCR_TIMEOUT_S = "tesseract", "afr", 8.0


def saw_capture(frame, run=subprocess.run) -> bool:
    """Is Roblox's "Capture saved" toast on this frame?"""
    import cv2
    if frame is None or getattr(frame, "size", 0) == 0:
        return False
    h, w = frame.shape[:2]
    sx, sy = w / FRAME_SIZE[0], h / FRAME_SIZE[1]
    x0, y0, x1, y1 = CAPTURE_TOAST_BOX
    crop = frame[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx), :3]
    if crop.size == 0:
        return False
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    grey = cv2.resize(grey, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    ok, png = cv2.imencode(".png", grey)
    if not ok:
        return False
    try:
        out = run([TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "7"],
                  input=png.tobytes(), capture_output=True, timeout=OCR_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return False
    text = out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes) else str(out.stdout)
    return CAPTURE_WORD in text.lower()


def release_alt(vin) -> bool:
    """Tap Alt once, so a Roblox holding an Alt it never saw let go lets go of it.
    The nested session binds nothing to Alt (platform/session CONFIG has no
    binds), and Roblox's own Alt shortcuts need a second key with it."""
    # BOTH ALTS: 2026-10-05 22:47 three presses stayed Captures after a tap of
    # the left one, so the held one may be the right.
    try:
        left = vin.tap("alt") is not False       # False: held back by the owner's Pause
        right = vin.tap("rightalt") is not False
        return left and right
    except Exception:
        return False


@dataclass
class Press:
    """What happened when a slot was pressed."""
    slot: int = 0
    holds: str = ""
    pressed: bool = False
    changed: float = 0.0        # fraction of the hotbar strip that moved
    # did the game take it: the slot dimmed (`slot_used`); None when a frame
    # was missing and nothing can be said
    used: bool | None = None
    # the press became Roblox's Capture (Alt+1): its toast was on screen after
    captured: bool = False
    # the tile was greyed before the press (vision/hotbar_items GREYED TILES),
    # so `used` says whether it turned to its cooldown, not whether it dimmed
    greyed: bool = False
    reason: str = ""
    frames: list = field(default_factory=list)

    def describe(self) -> str:
        if not self.pressed:
            return f"slot {self.slot}: pressed nothing — {self.reason}"
        what = self.holds or "whatever is in it"
        took = ("" if self.used is None else
                ", and the greyed tile turned to its cooldown: the game took it"
                if self.used and self.greyed else
                ", but the greyed tile stayed greyed: the game did not take the key"
                if self.greyed else
                ", and the slot dimmed: the game took it" if self.used else
                ", but the slot did not dim: the game did not take the key")
        if self.captured:
            took += (" -- Roblox took a Capture instead (its Alt+1): it is holding "
                     "an Alt it never saw let go")
        return (f"slot {self.slot} ({what}): pressed, "
                f"{self.changed:.0%} of the hotbar changed after{took}")


def strip(frame):
    """The hotbar strip out of a frame, or None."""
    if frame is None:
        return None
    left, top, right, bottom = screen.box(frame, HOTBAR_BOX, screen.BOTTOM)
    left, top = max(left, 0), max(top, 0)
    if bottom <= top or right <= left:
        return None
    return frame[top:bottom, left:right, :3]


def changed_fraction(before, after) -> float:
    """How much of the hotbar strip differs, 0..1. Evidence that a press did
    something, and never proof that it did not: plenty of things in this game
    happen without the hotbar redrawing."""
    import cv2
    import numpy as np
    if before is None or after is None or before.shape != after.shape:
        return 0.0
    a = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    return float((np.abs(a.astype(int) - b.astype(int)) > 24).mean())


def press_slot(vin, frames, slot: int, *, sleep=time.sleep,
               settle: float = SETTLE_SECONDS, on_note=None,
               keep=None, spend: bool = False) -> Press:
    """Press one hotbar slot and photograph what it did.

    Refuses a slot in `NEVER_PRESS_SLOTS` unless `spend` -- a caller that has
    reasoned the use out (run_farm throws gumdrops only where a quest wants
    goo; the owner, 2026-10-02: the items are the bot's to use when they pay)
    -- and a slot number the game does not draw. Presses exactly one key.
    """
    note = on_note or (lambda text: None)
    out = Press(slot=int(slot), holds=KNOWN_SLOTS.get(int(slot), ""))
    if int(slot) in NEVER_PRESS_SLOTS and not spend:
        out.reason = (f"slot {slot} holds {out.holds or 'a consumable'}, "
                      f"which is the owner's to spend")
        return out
    key = SLOT_KEYS.get(int(slot))
    if key is None:
        out.reason = f"there is no slot {slot} on the hotbar"
        return out

    before = _look(frames)
    if keep is not None:
        _keep(keep, before, f"slot{slot}-before", out)
    greyed = greyed_item(before, int(slot))
    out.greyed = bool(greyed)
    try:
        vin.tap(key)
    except Exception as exc:
        out.reason = f"could not press {key} ({exc})"
        return out
    out.pressed = True
    sleep(settle)
    after = _look(frames)
    if keep is not None:
        _keep(keep, after, f"slot{slot}-after", out)
    out.changed = changed_fraction(strip(before), strip(after))
    out.used = slot_used(before, after, int(slot))
    if greyed:
        # A GREYED TILE CANNOT DIM BY USED_MIN_DROP: it is already dim.
        # MEASURED 2026-10-13 (USED_MIN_DROP's own box, 10-12/10-13 frames):
        # greyed tiles read V 89-150, the cooldown after a press 109-132. A
        # press the game took shows the cooldown, which reads as no item
        # (vision/hotbar_items: 0.33 at most); one it did not take stays the
        # same greyed tile.
        out.used = None if after is None else greyed_item(after, int(slot)) != greyed
    if out.used is not True:
        out.captured = saw_capture(after)
    note(out.describe())
    return out


def greyed_item(frame, slot: int) -> str:
    """The item a greyed tile in `slot` shows (vision/hotbar_items), or ''."""
    if frame is None:
        return ""
    try:
        from ..vision import hotbar_items
        found = hotbar_items.identify(frame, int(slot))
    except Exception:
        return ""
    return str(found.item) if found.greyed and found.item else ""


def slot_brightness(frame, slot: int) -> float | None:
    """Mean brightness inside `slot`, 0-255, or None without a frame."""
    import cv2
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    x0, y0, x1, y1 = SLOT1_INNER
    dx = SLOT_PITCH * (int(slot) - 1)
    fx0, fy0, fx1, fy1 = screen.box(frame, (x0 + dx, y0, x1 + dx, y1), screen.BOTTOM)
    box = frame[max(fy0, 0):fy1, max(fx0, 0):fx1, :3]
    if box.size == 0:
        return None
    return float(cv2.cvtColor(box, cv2.COLOR_BGR2HSV)[:, :, 2].mean())


def slot_used(before, after, slot: int) -> bool | None:
    """Did the game take the press: the slot dimmed by USED_MIN_DROP or more.
    None when either frame is missing."""
    a, b = slot_brightness(before, slot), slot_brightness(after, slot)
    if a is None or b is None:
        return None
    return (a - b) >= USED_MIN_DROP


def _look(frames):
    try:
        return frames()
    except Exception:
        return None


def _keep(save_dir, frame, tag, out) -> None:
    if frame is None:
        return
    try:
        import cv2
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / f"hotbar-{tag}-{time.strftime('%H%M%S')}.jpg"
        cv2.imwrite(str(path), frame[:, :, :3],
                    [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        out.frames.append(str(path))
    except Exception:
        pass
