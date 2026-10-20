"""The Commando Chick's hurt health bar is seen (vision/nameplate.hurt_bars),
on the real frames of 2026-10-13 13:53 (var/commando/20261013-135246), where
`find` saw none and the fight ended "gone" with the chick a fifth alive."""
import shutil
from pathlib import Path

import cv2
import pytest

from hivemind.act import stumpsnail
from hivemind.vision import nameplate

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "commando"

# MEASURED by eye on each frame: the whole bar, green and dark red.
CHICK = {
    "chick-0206.1-end-gone.jpg": (962, 307, 144, 22),   # "HP: 5,812", green 0.20
    "chick-0112.7-fight.jpg": (1076, 317, 161, 24),     # its mint gun touches the bar
    "chick-0157.3-fight.jpg": (1136, 268, 84, 13),      # the smallest, far off
}


@pytest.mark.parametrize("name", sorted(CHICK))
def test_the_chicks_hurt_bar_is_seen(name):
    bars = nameplate.hurt_bars(cv2.imread(str(FIX / name)))
    assert len(bars) == 1, [b.describe() for b in bars]
    got = (bars[0].x, bars[0].y, bars[0].w, bars[0].h)
    assert all(abs(a - b) <= 3 for a, b in zip(got, CHICK[name])), got
    assert bars[0].tail > 0.3                           # red 0.39-0.53 of these


def test_no_bar_where_there_is_no_chick():
    frame = cv2.imread(str(FIX / "no-chick-0053.5-arrived.jpg"))
    assert nameplate.hurt_bars(frame) == []
    assert nameplate.find(frame) == []


@pytest.mark.skipif(shutil.which(stumpsnail.TESSERACT) is None, reason="no tesseract")
def test_its_hp_is_read_off_the_whole_bar():
    frame = cv2.imread(str(FIX / "chick-0206.1-end-gone.jpg"))
    boxes = [(b.x, b.y, b.w, b.h) for b in nameplate.hurt_bars(frame)]
    assert stumpsnail.read_hp(frame, boxes=boxes) == 5812
