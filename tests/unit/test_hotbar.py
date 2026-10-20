"""The hotbar, read from the game's own key hints.

MEASURED 2026-09-23 from `var/places/honey_dispenser-041002.jpg`: slot 1 holds
a sprinkler and draws the hint `[One]`, slot 2 holds gumdrops `x283` with the
hint `[Two]` and `AUTO: OFF` printed underneath, slots 3-7 are empty. The
hints are drawn by the game, so the slot-to-key mapping is read rather than
assumed. `gather.use_sprinklers` had been a switch wired to nothing under the
note "the bot has never seen the sprinkler placement UI".
"""
from __future__ import annotations

import pathlib

import cv2
import numpy as np
import os

import pytest

from hivemind.act import hotbar as H

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRAME = ROOT / "var/places/honey_dispenser-041002.jpg"


class Vin:
    def __init__(self):
        self.taps = []

    def tap(self, key):
        self.taps.append(key)


def _frames(*images):
    it = iter(images)
    return lambda: next(it)


def test_the_strip_is_cut_out_of_a_real_frame():
    if not FRAME.exists():
        pytest.skip("the hotbar frame is not in the repo")
    strip = H.strip(cv2.imread(str(FRAME)))
    assert strip is not None
    rows, cols = strip.shape[:2]
    assert 60 < rows < 200, rows
    assert 500 < cols < 1000, cols


def test_pressing_a_slot_sends_exactly_one_key():
    vin = Vin()
    blank = np.zeros((1080, 1920, 3), np.uint8)
    out = H.press_slot(vin, _frames(blank, blank), 1, sleep=lambda s: None)
    assert vin.taps == ["1"], vin.taps
    assert out.pressed and out.slot == 1
    assert out.holds == "sprinkler"


def test_the_owners_consumables_are_never_pressed():
    """Slot 2 is 283 gumdrops with AUTO: OFF beside them. Spending someone's
    consumables unasked is not this bot's to do."""
    vin = Vin()
    blank = np.zeros((1080, 1920, 3), np.uint8)
    out = H.press_slot(vin, _frames(blank, blank), 2, sleep=lambda s: None)
    assert vin.taps == [], vin.taps
    assert not out.pressed
    assert "owner's to spend" in out.reason


def test_a_slot_the_game_does_not_draw_is_refused():
    vin = Vin()
    blank = np.zeros((1080, 1920, 3), np.uint8)
    out = H.press_slot(vin, _frames(blank, blank), 9, sleep=lambda s: None)
    assert vin.taps == [] and not out.pressed
    assert "no slot 9" in out.reason


def test_a_change_in_the_hotbar_is_measured_not_assumed():
    before = np.zeros((1080, 1920, 3), np.uint8)
    after = before.copy()
    strip = H.strip(after)
    strip[:, :] = 255
    assert H.changed_fraction(H.strip(before), H.strip(after)) > 0.9
    assert H.changed_fraction(H.strip(before), H.strip(before)) == 0.0


def test_no_frames_is_not_a_crash():
    vin = Vin()
    out = H.press_slot(vin, lambda: None, 1, sleep=lambda s: None)
    assert out.pressed and out.changed == 0.0


# ---- did the game take the press ------------------------------------------------
# The owner, 2026-09-28: "its placing sprinklers wrong it isnt placing them in
# the field". 11 of the last 40 presses left slot 1 as it was -- the game had
# not heard the key -- and each was logged "placed". The slot dims (and shows
# "0s") when the game takes it: MEASURED V drop 41-46 taken, 0-3 not.
import pathlib as _pathlib

_HOTBAR = _pathlib.Path(__file__).resolve().parents[2] / "var" / "hotbar"


def _pair(before, after):
    import cv2
    b = cv2.imread(str(_HOTBAR / f"hotbar-slot1-before-{before}.jpg"))
    a = cv2.imread(str(_HOTBAR / f"hotbar-slot1-after-{after}.jpg"))
    if a is None or b is None:
        import pytest
        pytest.skip("the saved press frames are not on this machine")
    return b, a


def test_a_press_the_game_took_dims_the_slot():
    from hivemind.act import hotbar
    assert hotbar.slot_used(*_pair("201636", "201637"), 1) is True


def test_a_press_the_game_did_not_take_leaves_the_slot_as_it_was():
    from hivemind.act import hotbar
    assert hotbar.slot_used(*_pair("174807", "174808"), 1) is False
    assert hotbar.slot_used(*_pair("132327", "132328"), 1) is False


def test_without_a_frame_nothing_is_claimed():
    import numpy as np
    from hivemind.act import hotbar
    frame = np.zeros((1080, 1920, 3), np.uint8)
    assert hotbar.slot_used(None, frame, 1) is None
    assert hotbar.slot_used(frame, None, 1) is None


# ---- the press that became a screenshot ------------------------------------------------
# The owner, 2026-09-29: "when it trys placing sprinklers it takes a screen shot".
# Roblox's Capture is Alt+1; 72 of 658 kept slot-1 presses show its toast.
def _after(stamp):
    import cv2
    a = cv2.imread(str(_HOTBAR / f"hotbar-slot1-after-{stamp}.jpg"))
    if a is None:
        import pytest
        pytest.skip("the saved press frames are not on this machine")
    return a


def test_the_capture_toast_is_seen_and_a_taken_press_is_not_one():
    from hivemind.act import hotbar
    assert hotbar.saw_capture(_after("131709")) is True
    assert hotbar.saw_capture(_after("201637")) is False


def test_letting_go_of_alt_is_one_tap_of_alt_and_says_when_it_was_held_back():
    from hivemind.act import hotbar
    vin = Vin()
    assert hotbar.release_alt(vin) is True and vin.taps == ["alt", "rightalt"]

    class Paused:
        def tap(self, key):
            return False
    assert hotbar.release_alt(Paused()) is False


@pytest.mark.skipif(os.name == "nt", reason="the Wayland virtual keyboard (pywayland) is Linux")
def test_the_bots_keyboard_can_press_alt():
    from hivemind.platform.wl.vkeyboard import KEYS
    assert KEYS["alt"] == 56                        # KEY_LEFTALT


def test_a_press_that_became_a_capture_is_marked_so():
    from hivemind.act import hotbar
    before, after = _pair("132327", "132328")
    out = hotbar.press_slot(Vin(), _frames(before, after), 1, sleep=lambda s: None)
    assert out.used is False
    assert out.captured is hotbar.saw_capture(after)
    if out.captured:
        assert "Capture" in out.describe()


def test_a_reasoned_use_may_spend_the_gumdrops():
    """The owner, 2026-10-02: the items are the bot's to use when they pay --
    gumdrops only where a quest wants goo (run_farm throw_a_gumdrop)."""
    vin = Vin()
    blank = np.zeros((1080, 1920, 3), np.uint8)
    out = H.press_slot(vin, _frames(blank, blank), 2, sleep=lambda s: None, spend=True)
    assert vin.taps == ["2"] and out.pressed
