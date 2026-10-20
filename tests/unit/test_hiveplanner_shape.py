"""The Hive Planner's grid has the game's shape (gui/panels/hiveplanner): a
honeycomb of cells wider than a regular hexagon, in the proportions measured
in the game (vision/hivecell: columns 55.5 px apart, rows 53.5). The owner,
2026-10-26: a full hive's hexagons are laid out differently."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hivemind.gui.panels import hiveplanner as panel   # noqa: E402


def test_columns_and_rows_are_spaced_as_measured_in_the_game():
    one, right, up = panel._centre(1), panel._centre(2), panel._centre(6)
    col_step = right.x() - one.x()
    row_step = one.y() - up.y()
    assert abs(col_step / row_step - 55.5 / 53.5) < 1e-6
    assert abs((one.y() - right.y()) - row_step / 2) < 1e-6      # the 2nd column half higher


def test_three_cells_along_the_bottom_and_two_along_the_top():
    """The owner, 2026-10-26: three cells along the bottom, not two."""
    ys = {s: panel._centre(s).y() for s in range(1, 51)}
    lowest, highest = max(ys.values()), min(ys.values())
    assert sorted(s for s, y in ys.items() if abs(y - lowest) < 1e-6) == [1, 3, 5]
    assert sorted(s for s, y in ys.items() if abs(y - highest) < 1e-6) == [47, 49]


def test_the_cells_nest_like_a_honeycomb_and_are_wider_than_regular():
    cell = panel._hexagon(panel._centre(1), panel.R)
    xs = [cell.at(k).x() for k in range(6)]
    ys = [cell.at(k).y() for k in range(6)]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    col_step = panel._centre(2).x() - panel._centre(1).x()
    assert abs(col_step - 0.75 * width) < 1e-6          # nested: 3/4 of a width apart
    assert abs(height - math.sqrt(3) * panel.R) < 1e-6  # a row apart top to bottom
    assert width / height > 2 / math.sqrt(3) + 0.1      # wider than a regular hexagon


def test_every_slot_is_clicked_at_its_own_centre():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    grid = panel.HiveGrid(panel=None)
    for slot in range(1, 51):
        assert grid.slot_at(panel._centre(slot)) == slot
    last = max(panel._centre(s).x() for s in range(1, 51))
    assert last + panel.RX <= grid.width()
