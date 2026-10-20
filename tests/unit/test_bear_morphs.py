"""The bear-morph reader (vision/buffs `bear`) knows the Science and Mother Bear
morphs as well as the four it had, and a Puppy Love beside them is not a bear.

MEASURED 2026-10-14: a gifted Bear Bee's rare morphs were on the bar uncounted
from attempt 850 on (e.g. Science at 970 18:40:57-18:41:04, Mother on 975's
Blender walk 20:39:03-20:39:29). The fixtures are the buff bar rows (58..96,
x 0..456) of var/routes/attempt-<N>/<stamp>-*.jpg as the names say:
987 05:48:56 natro_home_mountain_top-03 (Science, just applied), 970 18:41:01
natro_home_bamboo-02 (Science, 3 s left), 975 20:39:03 to_the_blender-00 and
20:39:16 -10 (Mother, full and 13 s left), 983 23:24:15 to_the_blender-01
(Mother beside a Puppy Love), 994 12:41:35 to_the_blender-03 (a drained Puppy
Love alone: Puppy Bee's buff, the bees' movespeed, not a morph); 979 22:56:41,
988 06:59:06, 967 15:06:41 and 986 02:45:54 (brown, black, polar beside a
Puppy Love, panda).
"""
from __future__ import annotations

import pathlib

import cv2
import numpy as np
import pytest

from hivemind.vision import buffs

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures/bearmorph"


def frame(name):
    out = np.full((1080, 1920, 3), (150, 120, 90), np.uint8)
    strip = cv2.imread(str(FIX / name))
    out[buffs.BAR_TOP:buffs.BAR_BOTTOM, :strip.shape[1]] = strip
    return out


@pytest.mark.parametrize("name,kind,left", [
    ("science-full-054856-attempt987.png", "science", 29.7),
    ("science-3s-184101-attempt970.png", "science", 3.1),
    ("mother-full-203903-attempt975.png", "mother", 29.7),
    ("mother-13s-203916-attempt975.png", "mother", 13.3),
    ("mother-puppy-232415-attempt983.png", "mother", None),
    ("brown-225641-attempt979.png", "brown", None),
    ("black-065906-attempt988.png", "black", None),
    ("polar-puppy-150641-attempt967.png", "polar", None),
    ("panda-024554-attempt986.png", "panda", None),
])
def test_each_morph_reads_as_itself(name, kind, left):
    b = buffs.bear(frame(name))
    assert b.present and b.kind == kind and b.score >= 0.9, b
    assert b.factor(28.0) == pytest.approx(32.0 / 28.0)
    if left is not None:
        assert b.remaining_s == pytest.approx(left, abs=0.1)


def test_a_puppy_love_is_not_a_bear():
    assert not buffs.bear(frame("puppy-124135-attempt994.png")).present


def test_without_the_new_kinds_the_rare_morphs_were_missed(monkeypatch):
    monkeypatch.setattr(buffs, "BEAR_KINDS", ("brown", "black", "polar", "panda"))
    for name in ("science-full-054856-attempt987.png", "mother-full-203903-attempt975.png"):
        assert not buffs.bear(frame(name)).present
