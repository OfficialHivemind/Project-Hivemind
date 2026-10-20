"""The Gear plan page (gui/panels/gearplan): pick gear, order it, save it into
`goals.order` in the form brain/goals reads (the owner, 2026-10-20)."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import hivemind  # noqa: E402
from hivemind.brain import goals as goals_plan  # noqa: E402
from hivemind.gui.panels import gearplan  # noqa: E402

APP = QApplication.instance() or QApplication([])
REPO = Path(hivemind.__file__).resolve().parents[2]
# KEPT ALIVE TO THE END: a parentless panel collected by Python's cycle GC
# crashes PySide 6.12 at QApplication teardown (in the window it is parented)
KEEP: list = []
SHOT = Path("/tmp/hivemind-diag")


def _panel(tmp_path, **values):
    saved = []
    panel = gearplan.GearPlanPanel(dict(values), save=saved.append, var_root=tmp_path)
    KEEP.append(panel)
    return panel, saved


def test_order_round_trips_through_order_from(tmp_path):
    panel, saved = _panel(tmp_path, **{"goals.order": "Porcelain Dipper"})
    for key in ("golden_rake", "mondo_belt_bag", "beekeepers_boots", "hive_slot"):
        panel.add_item(key)
    panel.save()
    assert saved == [panel.text()]
    keys = panel.keys()
    assert keys == ["porcelain_dipper", "golden_rake", "mondo_belt_bag",
                    "beekeepers_boots", "hive_slot"]
    # what from_files does with their text: gear made goals, then the order read
    names = goals_plan._names(saved[0])
    data = goals_plan.with_gear(dict(goals_plan.load(), default_order=names), saved[0])
    order, unknown = goals_plan.order_from(saved[0], data)
    assert unknown == ["hive_slot"]                   # with_next_slot's to replace
    assert order == keys[:-1]
    # and the whole plan follows it, the hive slot as the next slot
    plan = goals_plan.from_files(settings={"goals.order": saved[0]}, var_root=tmp_path,
                                 first=[])
    got = [r.key for r in plan.rows if not r.origin]
    assert got[:4] == keys[:4]
    assert not plan.unknown_names
    belt = plan.row("mondo_belt_bag")
    assert belt.cost == 12_400_000 and {n.material for n in belt.needs} >= {"soft_wax", "stinger"}


def test_owned_gear_is_greyed_and_not_addable(tmp_path):
    panel, _ = _panel(tmp_path, **{"goals.owned": "Golden Rake", "goals.order": "Jar"})
    assert "golden_rake" in panel.owned
    panel.add_item("golden_rake")
    assert "golden_rake" not in panel.keys()
    card = next(panel.grid.item(n) for n in range(panel.grid.count())
                if panel.grid.item(n).data(gearplan.Qt.UserRole) == "golden_rake")
    assert not card.flags() & gearplan.Qt.ItemIsEnabled and "owned" in card.text()


def test_missing_picture_draws_initials():
    pix = gearplan.picture("no_such_item", "Mystery Hat", 40)
    assert not pix.isNull() and pix.width() == 80


def test_reorder_changes_the_saved_order(tmp_path):
    panel, saved = _panel(tmp_path, **{"goals.order": "porcelain_dipper, honey_mask, jar"})
    assert panel.keys() == ["porcelain_dipper", "honey_mask", "jar"]
    panel.move(1, row=2)                              # jar can go no lower
    panel.move(-1, row=2)
    panel.remove(row=0)
    panel.save()
    assert saved == ["jar, honey_mask"]
    assert "Next the bot saves for:" in panel.preview.text()


def test_empty_order_loads_the_default_and_every_item_has_its_picture(tmp_path):
    panel, _ = _panel(tmp_path)
    assert panel.keys() == [str(k) for k in goals_plan.load()["default_order"]]
    wiki = REPO / "data" / "knowledge" / "gear" / "wiki"
    sources = (wiki / "SOURCES.md").read_text()
    for key in gearplan.catalogue():
        if (wiki / f"{key}.png").exists():
            assert f"`{key}.png`" in sources          # every picture credited
    assert "CC BY-SA 3.0" in sources and "Onett" in sources
    panel.resize(1180, 760)
    SHOT.mkdir(parents=True, exist_ok=True)
    panel.grab().save(str(SHOT / "gearq_panel.png"))


def test_pro_testers_order_fills_the_list_and_plans(tmp_path):
    from hivemind.brain import protips
    panel, saved = _panel(tmp_path, **{"progression.hive": "blue"})
    panel.use_pro_order()
    want = [k for k, _e in protips.suggested_order("blue")]
    assert panel.keys() == want and "tide_popper" in want
    panel.save()
    plan = goals_plan.from_files(settings={"goals.order": saved[0]}, var_root=tmp_path,
                                 first=[])
    assert [r.key for r in plan.rows][:len(want)] == want
    assert not plan.unknown_names
    # the pro's own recipe, not the bare price-table entry
    assert plan.row("petal_wand").needs


def test_catalogue_has_the_tools_first():
    keys = list(gearplan.catalogue())
    assert keys[0] == "rake" and "porcelain_dipper" in keys and "golden_rake" in keys


def test_up_down_and_remove_wait_for_a_chosen_row(tmp_path):
    panel, _ = _panel(tmp_path, **{"goals.order": "porcelain_dipper, honey_mask, jar"})
    assert not panel.up_button.isEnabled() and not panel.down_button.isEnabled()
    assert not panel.remove_button.isEnabled()
    panel.order.setCurrentRow(0)
    assert not panel.up_button.isEnabled() and panel.down_button.isEnabled()
    assert panel.remove_button.isEnabled()
    panel.order.setCurrentRow(2)
    assert panel.up_button.isEnabled() and not panel.down_button.isEnabled()
