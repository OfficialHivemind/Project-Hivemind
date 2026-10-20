"""U6: each open gear goal draws a progress ring (gui/panels/gear), and a
refresh -- which rebuilds every row -- carries the ring on from its last value
instead of sweeping up from 0 again."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.brain import goals as goals_plan  # noqa: E402
from hivemind.gui.panels import gear  # noqa: E402

APP = QApplication.instance() or QApplication([])
KEEP: list = []                 # parentless widgets kept to the end (PySide teardown)


def _row(**kw):
    return goals_plan.Row(key=kw.pop("key", "mask"), label="Honey Mask", cost=1000, **kw)


def test_fraction_counts_the_goals_above_and_unknown_is_none():
    assert gear.honey_fraction(_row(honey=None)) is None
    assert gear.honey_fraction(_row(honey=300, queue_short=700)) == 0.3
    assert gear.honey_fraction(_row(honey=5000, queue_short=0)) == 1.0


def test_row_ring_shows_value_unknown_and_owned():
    r = gear.GearRow(_row(honey=250, queue_short=750))
    KEEP.append(r)
    assert r.ring._value == 0.25
    unknown = gear.GearRow(_row(honey=None))
    KEEP.append(unknown)
    assert unknown.ring._label == "?"            # never drawn as 0%
    owned = gear.GearRow(_row(owned=True, owned_why="you said so"))
    KEEP.append(owned)
    assert not hasattr(owned, "ring")


def test_refresh_carries_the_ring_on_from_last_value():
    panel = gear.GearGoalsPanel()
    KEEP.append(panel)

    def plan(honey):
        return SimpleNamespace(rows=[_row(honey=honey, queue_short=1000 - honey)],
                               honey=honey, honey_at=0, honey_from="test", rate=None,
                               unknown_names=[], unread_counts=[], progress=None,
                               ready=lambda: [])
    panel.show_plan(plan(200))
    assert panel._was["mask"] == 0.2
    panel.show_plan(plan(600))
    ring = panel._rows[0].ring
    assert ring._value == 0.6 and panel._was["mask"] == 0.6
