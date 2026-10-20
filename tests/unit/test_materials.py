"""AI Progress > Materials (gui/panels/materials, ROADMAP G11) on made-up
goals: have / need from the plan, "?" never 0, where from `Need.where`, and an
ETA only from the Blender's own crafts."""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.brain.goals import DOES, HONEY_READY, Need, Plan, Row  # noqa: E402
from hivemind.gui.panels.materials import MaterialsPage, craft_rates  # noqa: E402

APP = QApplication.instance() or QApplication([])


def plan() -> Plan:
    blender = [{"kind": "blender", "now": DOES}]
    return Plan(rows=[
        Row(key="porcelain_dipper", label="Porcelain Dipper", owned=True,
            needs=[Need("glitter", "Glitter", 5, have=0)]),
        Row(key="cobalt_guard", label="Cobalt Guard", shop_label="Blue HQ", state=HONEY_READY,
            needs=[Need("blue_extract", "Blue Extract", 100, have=73, have_from="the inventory",
                        sources=blender),
                   Need("enzymes", "Enzymes", 50, have=50, sources=blender),
                   Need("glitter", "Glitter", 25, have=None,
                        sources=[{"kind": "quest", "giver": "panda_bear", "now": DOES}])]),
        Row(key="honey_mask", label="Honey Mask", needs=[])])


def test_the_checklist(tmp_path):
    now = time.time()
    (tmp_path / "blender.json").write_text(json.dumps(
        {"made": [[now - 3600 * k, "blue_extract", 1] for k in range(14)]   # 2 a day
                 + [[now - 30 * 86400, "enzymes", 9]]}))                    # too old
    assert craft_rates(tmp_path, now) == {"blue_extract": 2.0}
    page = MaterialsPage(var_root=tmp_path)
    page.show_plan(plan())
    assert len(page.cards) == 1                               # owned and empty goals left out
    rows = {r["material"]: r for r in page.rows}
    assert rows["Blue Extract"]["mark"] == "○" and rows["Blue Extract"]["amount"] == "73 / 100"
    assert rows["Blue Extract"]["eta"].startswith("about 14 days (Blender, 2.0/day)")
    assert "Blender" in rows["Blue Extract"]["where"]
    assert rows["Enzymes"]["mark"] == "✓" and rows["Enzymes"]["eta"] == ""
    assert rows["Glitter"]["mark"] == "?" and rows["Glitter"]["amount"] == "? / 25"
    assert rows["Glitter"]["eta"] == "count unknown" and "panda bear quests" in rows["Glitter"]["where"].lower()
    page.show_plan(Plan(rows=[]))
    assert page.cards == [] and "None of your open gear goals" in page.head.text()


def test_no_blender_record_means_no_rate(tmp_path):
    assert craft_rates(tmp_path) == {}
    page = MaterialsPage(var_root=tmp_path)
    page.show_plan(plan())
    assert {r["material"]: r["eta"] for r in page.rows}["Blue Extract"] == "no rate measured"
