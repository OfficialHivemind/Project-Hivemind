"""brain/dashboard.publish_planters: the planters out, from act/planter's own
record (var/planters.json) -- the panel said "never seen the planter UI" while
the bot had placed and harvested them since 7 Oct."""
from __future__ import annotations

import json

from hivemind.brain.dashboard import GAPS, Dashboard


def test_the_planters_out_are_published_with_growth_and_due(tmp_path):
    path = tmp_path / "planters.json"
    path.write_text(json.dumps({"out": {"blue_clay_planter": {
        "field": "pine_tree", "at": 1000.0, "grow": 4000.0, "held": 1}}}))
    got = []
    dash = Dashboard(got.append, wall=lambda: 3000.0, planters_path=path)
    assert dash.publish_planters() == 1
    p = got[0]
    assert (p.kind, p.id, p.seed, p.field) == ("planter", "blue_clay_planter",
                                               "Blue Clay Planter", "pine_tree")
    assert abs(p.growth - 0.5) < 1e-9 and p.ready_at > 3000.0 and not p.harvest_now


def test_no_file_no_rows_and_the_stale_gap_is_gone(tmp_path):
    got = []
    assert Dashboard(got.append, planters_path=tmp_path / "none.json").publish_planters() == 0
    assert Dashboard(got.append).publish_planters() == 0 and not got
    assert all(g.panel != "planters" for g in GAPS)


def test_the_planter_row_says_its_verdict_whole_with_a_shape():
    """UI panel round 2 (2026-10-22): the verdict was cut to 22 characters and
    read as "ready" on every row; health was a colour only."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from hivemind.gui.panels.planters import PlanterRow
    from hivemind.telemetry.events import Planter
    why = "Waiting for 100%: field degradation is unverified, so it holds"
    row = PlanterRow(Planter(id="a", seed="Paper", field="Pine Tree", verdict=why, field_health=0.6))
    assert row._verdict.text() == why and row._verdict.wordWrap()
    assert row._health_value.text().startswith("⚠")
    row.update_from(Planter(id="a", seed="Paper", field="Pine Tree", verdict="harvest now",
                            harvest_now=True, field_health=0.9))
    assert row._verdict.text() == "✓ harvest now" and row._health_value.text().startswith("✓")
