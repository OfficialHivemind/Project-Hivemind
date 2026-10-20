"""eggs.save_diamond (the owner, 2026-10-14): Diamond Eggs are kept for recipes."""
from hivemind.brain import goals, hivejudge
from hivemind.world.settings import Settings, defaults


def test_on_by_default_and_wired():
    assert defaults()["eggs.save_diamond"] is True
    assert goals.diamond_saved(Settings("/nonexistent/settings.yaml")) is True


def test_the_setting_gates_the_hatch(monkeypatch):
    on, off = {"eggs.save_diamond": True}, {"eggs.save_diamond": False}
    # the alt hatches any egg -- but not a Diamond while the setting is on
    monkeypatch.setattr(goals, "ROLE", "alt")
    assert goals.egg_may_hatch("Diamond Egg", on) is False
    assert goals.egg_may_hatch("Diamond Egg", off) is True
    assert goals.egg_may_hatch("Gold Egg", on) is True
    # the main: Basic and event eggs only, whatever the setting
    monkeypatch.setattr(goals, "ROLE", "main")
    assert goals.egg_may_hatch("Diamond Egg", off) is False
    assert goals.egg_may_hatch("Basic Egg", on) is True


def test_a_new_slot_never_takes_a_saved_diamond(monkeypatch):
    monkeypatch.setattr(goals, "SLOT_EGGS", goals.ALT_SLOT_EGGS)
    held = {"diamond_egg": 5, "basic_egg": 1}
    assert goals.slot_egg_held(held, {"eggs.save_diamond": True})[0] == "basic_egg"
    assert goals.slot_egg_held(held, {"eggs.save_diamond": False})[0] == "diamond_egg"
    assert goals.slot_egg_held({"diamond_egg": 5}, {"eggs.save_diamond": True}) is None


def test_the_hive_judgement_says_a_diamond_egg_is_saved():
    j = hivejudge.Judgement(total=40, jelly_on={"basic": 1}, jelly_rolls=10.0,
                            jelly_hits_for=["diamond"], egg_tickets={"Diamond Egg": 3000.0})
    assert any("Diamond Egg 3,000 (saved for recipes" in line for line in j.lines({}))
    j.diamond_saved = False
    assert not any("saved for recipes" in line for line in j.lines({}))
