"""A drained Haste x10 is read (vision/buffs: A TWO-DIGIT COUNT).

MEASURED 2026-10-13 19:04:58: the Blender's walk set off under Haste x10 that
the reader called "no haste" (its 'x10' reaches into the figure's columns), so
the walk was not waited out and its 270-stud diagonal ended in the Blue Flower
field. The fixtures are the buff bar rows (58..96, x 0..304) of
var/routes/attempt-971/190458-to_the_blender-00-start.jpg (drain line 18),
190504-...-02-hive_offset-d.jpg (line 28), 190512-...-03-walk-sa270.jpg (the
Haste gone) and attempt-900/152959-natro_out_mountain_top-00-start.jpg.
"""
from __future__ import annotations

import pathlib

import cv2
import numpy as np
import pytest

from hivemind.vision import buffs

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures/haste"


def frame(name):
    out = np.full((1080, 1920, 3), (150, 120, 90), np.uint8)
    strip = cv2.imread(str(FIX / name))
    out[buffs.BAR_TOP:buffs.BAR_BOTTOM, :strip.shape[1]] = strip
    return out


@pytest.mark.parametrize("name,slot,left", [
    ("x10-190458-line18.png", 5, 10.5),
    ("x10-190504-line28.png", 5, 5.3),
    ("x10-152959-attempt900.png", 4, 11.6),
])
def test_a_drained_x10_is_haste_at_2x(name, slot, left):
    h = buffs.haste(frame(name))
    assert h.present and h.stacks == 10 and h.factor == pytest.approx(2.0), h
    assert buffs.find(frame(name), "haste").slot == slot
    assert h.remaining_s == pytest.approx(left, abs=0.1)


def test_the_old_box_missed_it_and_the_bar_after_has_none():
    real = buffs._count_left
    try:
        buffs._count_left = lambda icon: buffs.DRAIN_TEXT_BOX[1]
        assert not buffs.haste(frame("x10-190458-line18.png")).present
    finally:
        buffs._count_left = real
    assert not buffs.haste(frame("none-190512.png")).present
