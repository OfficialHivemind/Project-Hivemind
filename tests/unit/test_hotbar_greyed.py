"""A greyed hotbar tile still names its item (audit 2026-10-13 #3).

MEASURED: at 13:31:41 and 14:05:27 on 2026-10-13 the bar showed Whirligig and
Micro-Converter greyed with x2/x3 on them; the bright templates scored them
0.65-0.68 and the rescue said "no Whirligig on the hotbar". The fixtures are
the hotbar strips (x 680-1240, y 960-1060) of var/shoplook/20261013-140527-
jelly-roll9.jpg (greyed), var/hotbar/20261013-110630-stack1.jpg (the
Whirligig's cooldown, "2:17") and 20261013-101910-stack1.jpg (bright).
"""
from __future__ import annotations

import pathlib

import cv2
import numpy as np

import hivemind
from hivemind.act import hotbar as H
from hivemind.brain import stash as st
from hivemind.vision import hotbar_items as hi

FIX = pathlib.Path(hivemind.__file__).resolve().parents[2] / "tests" / "fixtures" / "hotbar"


def frame(name):
    out = np.zeros((1080, 1920, 3), np.uint8)
    out[960:1060, 680:1240] = cv2.imread(str(FIX / name))
    return out


def test_a_greyed_tile_names_its_item_and_says_greyed():
    grey = hi.read(frame("greyed-140527.png"))
    assert (grey[2].item, grey[2].greyed) == ("whirligig", True), grey[2]
    assert (grey[4].item, grey[4].greyed) == ("micro_converter", True), grey[4]
    assert hi.slot_of(frame("greyed-140527.png"), "whirligig") == 3
    bright = hi.read(frame("bright-101910.png"))[2]
    assert (bright.item, bright.greyed) == ("whirligig", False), bright
    # every other slot is named as before, none of them greyed
    for s in grey[:2] + grey[3:4] + grey[5:]:
        assert s.item and not s.greyed, s


def test_a_cooldown_tile_is_not_a_greyed_one():
    assert hi.identify(frame("cooldown-110630.png"), 3).item is None


def test_a_greyed_press_is_judged_by_its_cooldown_not_by_dimming():
    grey, cool = frame("greyed-140527.png"), frame("cooldown-110630.png")

    class Vin:
        def tap(self, key):
            pass
    took = H.press_slot(Vin(), iter([grey, cool]).__next__, 3, sleep=lambda s: None)
    assert took.greyed and took.used is True, took.describe()
    kept = H.press_slot(Vin(), iter([grey, grey]).__next__, 3, sleep=lambda s: None)
    assert kept.greyed and kept.used is False, kept.describe()


def test_a_rescue_presses_a_greyed_tile_unless_none_are_counted():
    """Counted: pressed. Not counted yet: pressed too, since 2026-10-13 19:30
    (a refused press costs a second, a rejoin the streak). Counted 0: not."""
    cat = {"whirligig": {"label": "Whirligig", "role": "time_saver", "cap": 100}}
    for counts in ({"whirligig": 2}, {}):
        assert st.Stash(catalogue=cat, counts=counts).rescue_use(
            "whirligig", on_hotbar=True, greyed=True).use, counts
    v = st.Stash(catalogue=cat, counts={"whirligig": 0}).rescue_use(
        "whirligig", on_hotbar=True, greyed=True)
    assert not v.use and "none counted" in v.why, v.why


def test_greyed_field_dice_and_coconut_name_their_items():
    """MEASURED 2026-10-22 on 1,100 var/hotbar frames (the 3 template sources
    left out): slot 4 unknown 376 -> 7, slot 7 258 -> 112 (the rest empty
    tiles, 0.34 at most), no tile named another item. Fixtures: the strips of
    hotbar-slot1-after-153725.jpg (light dice, coconut x0) and -080230.jpg
    (dark dice)."""
    s = hi.read(frame("greyed-dice-coconut-153725.png"))
    assert (s[3].item, s[3].greyed) == ("field_dice", True), s[3]
    assert (s[6].item, s[6].greyed) == ("coconut", True), s[6]
    d = hi.read(frame("greyed-dice-dark-080230.png"))[3]
    assert (d.item, d.greyed) == ("field_dice", True), d
