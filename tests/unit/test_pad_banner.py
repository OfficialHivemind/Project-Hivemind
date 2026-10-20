"""On our own pad with an empty bag, the translucent banner over the honeycomb
still says so (vision/screenstate.make_honey_present, empty_bag_banner_says_so).

run-510..531: 107 of 146 respawns kept as "spawn" were ON the pad with an empty
bag; walked forward from, they left it ("could not walk onto the pad", 22 of 39).
"""
from __future__ import annotations

import pathlib

import cv2
import numpy as np
import pytest

from hivemind.act import respawn
from hivemind.vision import screenstate as ss

ROOT = pathlib.Path(__file__).resolve().parents[2]
KEPT = ROOT / "var" / "respawn"


def _frame(name):
    path = KEPT / name
    if not path.exists():
        pytest.skip("the kept respawn frames are not on this machine")
    return cv2.imread(str(path))


@pytest.mark.parametrize("name", ["230544-spawn.jpg", "011716-spawn.jpg", "041800-spawn.jpg",
                                  "041828-spawn.jpg"])
def test_on_the_pad_with_an_empty_bag_is_the_pad(name):
    frame = _frame(name)
    assert ss.empty_bag_banner_says_so(frame)
    assert ss.make_honey_present(frame)


@pytest.mark.parametrize("name", ["163531-spawn.jpg", "011744-spawn.jpg"])
def test_the_real_spawn_point_is_not_the_pad(name):
    frame = _frame(name)
    assert not ss.empty_bag_banner_says_so(frame)
    assert not ss.make_honey_present(frame)


def test_a_blank_frame_is_neither():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    assert not ss.empty_bag_banner_says_so(frame)
    assert not ss.make_honey_present(frame)


def test_the_pad_reads_closer_than_the_spawn_point():
    # MEASURED: on the pad 113,522-134,452 honeycomb px, the spawn point 73,926-83,816
    assert 83_816 < respawn.ON_PAD_YELLOW < 113_522
    assert respawn.ON_PAD_YELLOW > respawn.ROW_IN_VIEW_YELLOW
