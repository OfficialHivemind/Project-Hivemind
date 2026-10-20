"""ROADMAP AI-N3 token weight presets: the setting's checks
(world/settings.token_presets) and the preset row on Settings > Token
priority (gui/panels/tokenprio), offscreen."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels import tokenprio  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402

APP = QApplication.instance() or QApplication([])


def test_default_is_none_and_bad_rows_are_dropped_and_said():
    assert schema.defaults()["gather.token_presets"] == []
    assert "gather.token_presets" in schema.LISTS
    good = {"name": "Boosts", "kind": "haste", "weight": 90}
    got, why = schema.token_presets([
        good, {**good, "name": ""}, {**good, "name": "x" * 41}, {**good, "hive": "blue"},
        {**good, "weight": 1001}, {**good, "kind": "Haste!"}, "haste",
        {**good, "weight": 70, "off": True}])                  # replaces the first
    assert got == [{"name": "Boosts", "kind": "haste", "weight": 70, "off": True}]
    assert len(why) == 6 and all("left out" in w for w in why)
    assert schema.token_presets({"Boosts": []})[0] == []


def panel(values=None):
    saved = {}
    p = tokenprio.TokenPriority({"progression.hive": "blue", **(values or {})},
                                lambda k, v: saved.__setitem__(k, v))
    return p, saved


def test_save_then_use_a_preset_on_another_hive_then_delete_it():
    p, saved = panel()
    assert not p.preset_apply.isEnabled()
    p.move(-1, p.shown[1]["kind"])                    # make blue's table its own
    blue = {e["kind"]: (e["weight"], e["off"]) for e in p.shown}
    p.save_preset("  Mine  ")
    assert p.preset_names() == ["Mine"] and p.preset.currentText() == "Mine"
    assert schema.token_presets(saved["gather.token_presets"])[1] == []
    p.hive.setCurrentIndex(schema.TOKEN_HIVES.index("red"))
    assert not p.is_custom()
    p.apply_preset("Mine")
    assert p.is_custom()
    assert {e["kind"]: (e["weight"], e["off"]) for e in p.shown} == blue
    assert {r["hive"] for r in saved["gather.token_priority"]} == {"blue", "red"}
    p.delete_preset("Mine")
    assert saved["gather.token_presets"] == [] and not p.preset_delete.isEnabled()


def test_presets_saved_elsewhere_are_shown():
    p, _ = panel({"gather.token_presets": [{"name": "A", "kind": "honey", "weight": 5,
                                            "off": False}]})
    assert p.preset_names() == ["A"]
    p.show_presets([{"name": "B", "kind": "honey", "weight": 5, "off": False}])
    assert p.preset_names() == ["B"]
