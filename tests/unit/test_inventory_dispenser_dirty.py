"""A dispenser collect marks the inventory dirty; the skip is 3 h (ROADMAP P17)."""
from pathlib import Path

import hivemind
from hivemind.act import inventory

ROOT = Path(hivemind.__file__).resolve().parents[2]


def test_item_dispensers_move_the_inventory():
    for name in ("treat_dispenser", "blueberry_dispenser", "strawberry_dispenser",
                 "coconut_dispenser", "glue_dispenser", "royal_jelly_dispenser"):
        assert inventory.moved_by_place(name), name
    for name in ("honey_dispenser", "wealth_clock", "blue_field_booster"):
        assert not inventory.moved_by_place(name), name


def test_mark_dirty_round_trip(tmp_path):
    path = tmp_path / "inventory.json"
    assert inventory.dirty(path) == ""
    inventory.mark_dirty(path, "the treat dispenser used", clock=lambda: 0.0)
    assert inventory.dirty(path).startswith("the treat dispenser used at ")


def test_run_farm_wires_it():
    text = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert "\nINVENTORY_SKIP_SECONDS = 3 * 60 * 60.0\n" in text
    assert "if inventory_mod.moved_by_place(name):" in text
