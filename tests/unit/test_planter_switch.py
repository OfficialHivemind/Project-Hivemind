"""The Manage planters switch (economy.planters) is real: act/planter.
switched_off is what run_farm's planter errand, its tend and its Paper
Planter buy ask, and the settings say so. Nectar vials stay honestly unbuilt."""
from pathlib import Path

import yaml

from hivemind.act import planter
from hivemind.world import settings as schema

RUN_FARM = (Path(__file__).resolve().parents[2] / "scripts" / "run_farm.py").read_text()


class Fake:
    def __init__(self, **off):
        self.off = {k.replace("_", ".", 1) for k in off}

    def bool(self, key):
        return key not in self.off


def test_the_switch_gates_the_planter_errand():
    assert planter.switched_off(Fake()) == ""
    assert planter.switched_off(Fake(economy_planters=1)) == "economy.planters is off"
    assert planter.switched_off(Fake(economy_use_items=1)) == "economy.use_items is off"
    # a settings object that cannot answer leaves them as they were: on
    assert planter.switched_off(object()) == ""


def test_the_real_settings_file_turns_it_off(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"economy.planters": False}))
    assert planter.switched_off(schema.Settings(path)) == "economy.planters is off"
    # no file: the shipped default, off since U15b
    assert planter.switched_off(schema.Settings(tmp_path / "none.yaml")) == "economy.planters is off"
    path.write_text(yaml.safe_dump({"economy.planters": True, "economy.use_items": True}))
    assert planter.switched_off(schema.Settings(path)) == ""


def _body(name: str) -> str:
    start = RUN_FARM.index(f"        def {name}(")
    return RUN_FARM[start:RUN_FARM.index("\n        def ", start + 1)]


def test_run_farm_asks_it_before_walking_tending_or_buying():
    assert "planter_mod.switched_off(settings)" in _body("planter_errand")
    assert "planter_mod.switched_off(settings)" in _body("tend_the_planter")
    assert 'settings.bool("economy.planters")' in _body("paper_planters_due")


def test_the_settings_say_what_it_does():
    assert schema.wired("economy.planters") and not schema.blocked_by("economy.planters")
    assert schema.takes_effect("economy.planters") == "at its next use"
    assert "Off, the bot places, harvests and buys none" in schema.describe("economy.planters")
    # nectar vials: nothing condenses anything, and the label says so
    assert not schema.wired("economy.nectar_vials")
    assert "nothing condenses" in schema.blocked_by("economy.nectar_vials")
    label = next(e[1] for _, es in schema.SECTIONS for e in es if e[0] == "economy.nectar_vials")
    assert "not built" in label
