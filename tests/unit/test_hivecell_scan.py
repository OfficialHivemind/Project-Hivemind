"""A wide scan over the hive's cells in view (vision/hivecell.hive_box,
scan_points): the box of the bees' colours, and points from its middle out."""
from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")


def test_the_box_is_where_the_bee_colours_are_and_the_scan_starts_in_its_middle():
    from hivemind.vision import hivecell
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[:, :] = (40, 160, 200)                    # gold-ish: not a bee
    frame[100:300, 800:1300] = (230, 120, 30)       # a saturated blue: bees
    box = hivecell.hive_box(frame)
    assert box is not None
    x0, y0, x1, y1 = box
    assert 795 <= x0 <= 815 and 1285 <= x1 <= 1305 and 95 <= y0 <= 110 and 285 <= y1 <= 300
    pts = hivecell.scan_points(box)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    d = [abs(x - cx) + abs(y - cy) for x, y in pts]
    assert d == sorted(d) and all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in pts)


def test_no_bees_no_box():
    from hivemind.vision import hivecell
    assert hivecell.hive_box(np.zeros((1080, 1920, 3), np.uint8)) is None


def test_the_whole_hive_is_walked_down_its_columns_top_rows_first():
    # MEASURED var/shoplook/20261006-053827-hatch-before-z3.jpg: hive_box
    # (799, 65, 1120, 524); the faces' columns at x 845, 900, 955, 1011, 1067;
    # the top row's Basic Bees at (845, 197), (900, 170), (955, 197)
    from hivemind.vision import hivecell
    pts = hivecell.column_points((799, 65, 1120, 524))
    xs = sorted({x for x, _y in pts})
    assert [abs(a - b) <= 3 for a, b in zip(xs, (845, 900, 955, 1011, 1067))] == [True] * 5
    assert pts[0][1] == min(y for _x, y in pts)                  # the top rows first
    for face in ((845, 197), (900, 170), (955, 197)):
        assert any(abs(x - face[0]) <= 3 and abs(y - face[1]) <= 14 for x, y in pts), face
