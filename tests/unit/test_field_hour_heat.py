"""ROADMAP P13: the per-field, per-hour honey heatmap on CLEARLY FAKE units.
A cell is the trips' own balance rise over their reading seconds; a cell with
under 10 minutes of readings is left out, never drawn as a zero."""
from __future__ import annotations

import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels import graphs  # noqa: E402

APP = QApplication.instance() or QApplication([])


def at(hour: int) -> float:
    return dt.datetime(2026, 1, 5, hour, 30).timestamp()


def unit(field, hour, gain, secs):
    return {"at": at(hour), "field": field, "hgain": gain, "hdt": secs}


def test_cells_are_honey_per_hour_and_thin_cells_are_blank():
    units = [unit("pine_tree", 9, 1_000_000, 400), unit("pine_tree", 9, 2_000_000, 400),
             unit("rose", 9, 5_000_000, 300),          # 5 min: too thin, left out
             unit("rose", 14, 3_000_000, 900),
             unit(None, 9, 9_000_000, 900),            # not a gather trip
             unit("bamboo", 3, 0, 0)]                  # no readings at all
    heat = graphs.field_hour_heat(units)
    assert heat == {"pine_tree": {9: 3_000_000 / 800 * 3600},
                    "rose": {14: 3_000_000 / 900 * 3600}}


def test_the_chart_draws_and_says_not_enough_data_when_empty():
    chart = graphs.HeatChart("t")
    chart.resize(800, 200)
    chart.set_cells({})
    assert chart.is_empty()
    chart.grab()
    chart.set_cells({"pine_tree": {9: 10.0, 10: 5.0}, "rose": {14: 1.0}})
    assert not chart.is_empty()
    chart.grab()
