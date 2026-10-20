"""A giver's pad found in the view (vision/questmarker.pad_x): MEASURED
2026-10-07 15:47, the Spirit Bear's prompt shows only on her white pad."""
from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")


def _field():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[:] = (40, 160, 60)                              # green ground
    return frame


def test_a_white_pad_low_in_the_view_is_found_where_it_is():
    from hivemind.vision import questmarker
    frame = _field()
    cv2.ellipse(frame, (1500, 750), (400, 180), 0, 0, 360, (200, 90, 40), 30)   # blue rim
    cv2.ellipse(frame, (1500, 750), (380, 165), 0, 0, 360, (245, 245, 245), -1)  # white
    assert abs(questmarker.pad_x(frame) - 1500) < 10


def test_no_pad_from_small_white_things_the_sky_or_pale_colour():
    from hivemind.vision import questmarker
    frame = _field()
    cv2.rectangle(frame, (700, 600), (800, 700), (250, 250, 250), -1)       # a card, 10,000 px
    assert questmarker.pad_x(frame) is None
    frame[:300] = (255, 255, 255)                                          # sky, above the band
    assert questmarker.pad_x(frame) is None
    frame = _field()
    cv2.ellipse(frame, (960, 750), (400, 180), 0, 0, 360, (240, 240, 180), -1)  # pale blue, not white
    assert questmarker.pad_x(frame) is None
    assert questmarker.pad_x(None) is None
