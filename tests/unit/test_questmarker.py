"""The "!" over a quest giver (vision/questmarker), on drawn frames."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from hivemind.vision import questmarker as qm

SKY = (235, 200, 120)            # BGR: the light blue behind the Panda's marker
ORANGE = (40, 150, 252)          # BGR: hue 19, saturation 179, value 252 (the module note)
PLATFORM = (35, 185, 203)        # BGR: hue 24, value 203 -- his platform's face
OUTLINE = (40, 40, 40)


def frame(bg=SKY):
    img = np.zeros((1080, 1920, 3), np.uint8)
    img[:] = bg
    return img


def draw(img, x, y, w=15, bar=44, gap=5, dot=12, colour=ORANGE, outline=True):
    """A marker: a bar `bar` tall over a dot, its top left at (x, y)."""
    dx = x + (w - dot) // 2
    if outline:
        cv2.rectangle(img, (x - 3, y - 3), (x + w + 2, y + bar + 2), OUTLINE, -1)
        cv2.rectangle(img, (dx - 3, y + bar + gap - 3),
                      (dx + dot + 2, y + bar + gap + dot + 2), OUTLINE, -1)
    cv2.rectangle(img, (x, y), (x + w - 1, y + bar - 1), colour, -1)
    cv2.rectangle(img, (dx, y + bar + gap), (dx + dot - 1, y + bar + gap + dot - 1), colour, -1)
    return img


def test_the_drawn_marker_is_found_where_it_is():
    found = qm.find(draw(frame(), 1013, 96))
    assert len(found) == 1
    m = found[0]
    assert abs(m.x - (1013 + 7.5)) <= 1 and m.y == 96
    assert m.w == 15 and m.h == 44 + 5 + 12
    assert "quest marker at (1020, 96)" in m.describe()


def test_an_empty_frame_and_no_frame_have_none():
    assert qm.find(frame()) == []
    assert qm.find(None) == []
    assert qm.find(np.zeros((0, 0, 3), np.uint8)) == []


def test_two_markers_come_left_to_right():
    img = draw(draw(frame(), 1500, 300), 335, 65)
    assert [m.x for m in qm.find(img)] == [342, 1507]


def test_the_platforms_yellow_is_not_its_orange():
    assert qm.find(draw(frame(), 1013, 96, colour=PLATFORM)) == []


def test_a_bar_without_its_dot_is_not_one():
    img = frame()
    cv2.rectangle(img, (1010, 93), (1027, 142), OUTLINE, -1)
    cv2.rectangle(img, (1013, 96), (1027, 139), ORANGE, -1)
    assert qm.find(img) == []


def test_without_the_dark_outline_it_is_not_one():
    assert qm.find(draw(frame(), 1013, 96, outline=False)) == []


def test_orange_text_with_neighbours_on_its_line_is_not_one():
    """The Ant Challenge meter's digits: shapes beside the bar at its height."""
    img = draw(frame(), 1013, 96)
    cv2.rectangle(img, (1040, 96), (1068, 150), ORANGE, -1)       # "8,000"'s next glyph
    assert qm.find(img) == []


def test_in_the_hud_band_or_the_hotbar_it_is_not_looked_for():
    assert qm.find(draw(frame(), 1013, 5, bar=22, gap=2, dot=6)) == []
    assert qm.find(draw(frame(), 1013, 975)) == []


@pytest.mark.parametrize("w,bar,dot", [(13, 34, 10), (25, 60, 20)])
def test_the_sizes_it_was_seen_at(w, bar, dot):
    """13-25 px wide at 1920x1080 near his platform (the module note)."""
    assert len(qm.find(draw(frame(), 900, 200, w=w, bar=bar, dot=dot))) == 1


def test_a_half_size_frame_keeps_its_band():
    img = cv2.resize(draw(frame(), 1013, 300, w=26, bar=88, dot=24), (960, 540),
                     interpolation=cv2.INTER_NEAREST)
    assert len(qm.find(img)) == 1
