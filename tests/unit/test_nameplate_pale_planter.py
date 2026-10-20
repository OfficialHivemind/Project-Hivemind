"""A growing planter's PALE bar is found (vision/nameplate.find_planter_bars,
PALE_*), on the frame of 2026-10-13 21:29 where the seek saw "no planter's
bar all the way round" with "Blue Clay Planter (81.4%)" in plain view -- and
a pale field strip with white flowers is not."""
from pathlib import Path

import cv2
import numpy as np

import hivemind
from hivemind.vision import nameplate

FIX = Path(hivemind.__file__).resolve().parents[2] / "tests" / "fixtures" / "planter"


def test_the_growing_blue_clay_bar_is_found():
    # var/planters/seek-20261013-212933-turn0.jpg rows 430-620, cols 0-400:
    # the bar at x 26-370, y 544-592 of the frame, its pale fill to x 306;
    # the box takes in the web and black left of it (bar-like to `inked`)
    frame = cv2.imread(str(FIX / "growing-blue-clay-81pct.png"))
    assert nameplate.find_all(frame) == []            # the old passes: blind to it
    assert nameplate.find_planter_bars(frame) == [(0, 114, 306, 48)]


def test_a_pale_field_with_white_flowers_is_not_a_bar(monkeypatch):
    # routes attempt-540/090223-natro_home_pineapple-19-pause-.jpg rows
    # 400-600, cols 950-1250: passes every pale test but the dark letter edges
    frame = cv2.imread(str(FIX / "pale-field-flowers.png"))
    assert nameplate.find_planter_bars(frame) == []
    monkeypatch.setattr(nameplate, "PALE_MIN_DARK", 0.0)
    assert nameplate.find_planter_bars(frame) != []   # the test that refuses it


def test_a_just_placed_planters_unfilled_bar_is_found_only_when_asked():
    # var/planters/place-20261020-022720-unseen.jpg rows 50-300, cols 640-1280
    # (near, "Blue Clay Planter (0.0%)") and place-20261021-090552-unseen.jpg
    # rows 330-500, cols 820-1100 (far): no fill, so no pass but ZERO_* sees it
    near = cv2.imread(str(FIX / "zero-blue-clay-near.png"))
    far = cv2.imread(str(FIX / "zero-blue-clay-far.png"))
    assert nameplate.ZERO_BAR_LIVE is False            # look-only (AGENTS rule 4)
    assert nameplate.find_planter_bars(near) == []
    assert nameplate.find_planter_bars(near, zero=True) == [(56, 140, 528, 68)]
    assert nameplate.find_planter_bars(far, zero=True) == [(74, 123, 132, 18)]


def test_a_part_grown_bars_unfilled_rest_is_not_a_second_bar():
    frame = cv2.imread(str(FIX / "growing-blue-clay-81pct.png"))
    assert nameplate.find_planter_bars(frame, zero=True) == [(0, 114, 306, 48)]
    assert nameplate.find_planter_bars(cv2.imread(str(FIX / "pale-field-flowers.png")),
                                       zero=True) == []


def test_a_small_green_blob_above_the_hotbar_is_not_an_unfilled_bar(monkeypatch):
    # review 2026-10-22: var/hotbar/20261019-204257-stack2.jpg rows 920-1000,
    # cols 600-820, put back where it was: a 55x10 box at (683, 957), far
    # smaller than the smallest real 0.0% bar (132x18)
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[920:1000, 600:820] = cv2.imread(str(FIX / "zero-false-blob-above-hotbar.png"))
    assert nameplate.find_planter_bars(frame, zero=True) == []
    monkeypatch.setattr(nameplate, "ZERO_MIN_W", 0)
    assert nameplate.find_planter_bars(frame, zero=True) == [(683, 957, 55, 10)]
