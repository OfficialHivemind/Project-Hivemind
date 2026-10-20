"""$11 hotbar rules: the setting's checks (world/settings.hotbar_rules), the
trigger timing and the gates (brain/hotbarrules), and the Boosting tab's card
(gui/panels/boosting.HotbarRules), offscreen."""
from __future__ import annotations

import os
from types import SimpleNamespace as S

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml  # noqa: E402

from hivemind.brain import hotbarrules as hr  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402

SLOT = S(slot=4, greyed=False)


def rule(**kw):
    return {"item": "coconut", **schema.HOTBAR_ENTRY, **kw}


# ---- the setting ---------------------------------------------------------------
def test_default_is_no_rules():
    assert schema.defaults()["hotbar.rules"] == []
    assert schema.hotbar_rules(None) == ([], [])


def test_a_rule_takes_the_defaults_and_bad_ones_are_dropped_and_said():
    got, why = schema.hotbar_rules([
        {"item": "coconut"},
        {"item": "glitter"},                                   # no hotbar picture
        {"item": "whirligig", "trigger": "sometimes"},
        {"item": "jelly_beans", "minutes": 0},                 # under 1
        {"item": "gumdrops", "field": "Atlantis"},
        {"item": "sprinkler", "over_ai": "yes"},
        {"item": "field_dice", "colour": "red"},
        {"item": "micro_converter", "keep": True},
        "coconut",
    ])
    assert got == [rule()]
    assert len(why) == 8 and all("left out" in w for w in why)


def test_at_most_seven_rules():
    got, why = schema.hotbar_rules([{"item": "coconut"}] * 9)
    assert len(got) == schema.HOTBAR_MAX and len(why) == 2


def test_the_settings_file_is_checked_on_load(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"hotbar.rules": [
        {"item": "coconut", "trigger": "gathering", "seconds": 20, "field": "Pine Tree",
         "keep": 5}, {"item": "nope"}]}))
    s = schema.Settings(path)
    assert s.get("hotbar.rules") == [rule(trigger="gathering", seconds=20,
                                          field="Pine Tree", keep=5)]
    assert any("hotbar.rules" in p for p in s.problems)
    assert "hotbar.rules" in schema.READ_AT_EVERY_USE


# ---- the triggers ---------------------------------------------------------------
def test_every_n_minutes_fires_at_any_hook_once_the_time_is_up():
    r = rule(trigger="every", minutes=5)
    assert hr.due(r, "tick", 1000.0, {})                  # never pressed: now
    assert not hr.due(r, "convert", 1299.0, {"last": 1000.0})
    assert hr.due(r, "convert", 1300.0, {"last": 1000.0})
    tied = rule(trigger="every", minutes=5, field="Pine Tree")
    assert not hr.due(tied, "convert", 1300.0, {"last": 1000.0})    # the pad is no field
    assert hr.due(tied, "tick", 1300.0, {"last": 1000.0})


def test_at_each_convert_only_at_the_convert():
    r = rule(trigger="convert")
    assert hr.due(r, "convert", 5.0, {"last": 4.0})
    assert not hr.due(r, "tick", 5000.0, {})


def test_while_gathering_every_n_seconds_on_the_passes_only():
    r = rule(trigger="gathering", seconds=30)
    assert hr.due(r, "tick", 100.0, {"last": 70.0})
    assert not hr.due(r, "tick", 99.0, {"last": 70.0})
    assert not hr.due(r, "convert", 1000.0, {})


def test_boost_start_fires_once_per_boost_in_the_boosted_field():
    r = rule(trigger="boost")
    kw = dict(boost_at=500.0, boost_field="pine_tree", field="pine_tree")
    assert hr.due(r, "tick", 600.0, {}, **kw)
    assert not hr.due(r, "tick", 600.0, {"boost": 500.0}, **kw)     # fired for it
    assert hr.due(r, "tick", 900.0, {"boost": 500.0}, **{**kw, "boost_at": 880.0})
    assert not hr.due(r, "tick", 600.0, {}, **{**kw, "field": "rose"})
    assert not hr.due(r, "tick", 600.0, {}, **{**kw, "boost_at": None})
    assert not hr.due(r, "convert", 600.0, {}, **kw)


def test_never_is_never():
    assert not hr.due(rule(trigger="never"), "tick", 1e9, {})


# ---- the gates and vetoes -------------------------------------------------------
def go(r=None, **kw):
    args = dict(field="pine_tree", hive_level=10, role="field_boost", count=20,
                slot=SLOT, keeper_on=False)
    args.update(kw)
    return hr.check(r or rule(), **args)


def test_all_clear_presses():
    assert go() == (True, "")


def test_field_condition_by_the_field_table_name():
    assert go(rule(field="Pine Tree"))[0]
    ok, why = go(rule(field="Rose"))
    assert not ok and "only in Rose" in why


def test_hive_level_condition():
    assert go(rule(hive_level=10))[0]
    assert not go(rule(hive_level=11))[0]
    assert not go(rule(hive_level=5), hive_level=None)[0]


def test_materials_are_for_crafting_below_hive_level_16():
    ok, why = go(role="material", hive_level=10)
    assert not ok and "crafting" in why
    assert go(role="material", hive_level=16)[0]


def test_the_reserve_is_kept():
    assert go(rule(keep=5), count=6)[0]
    ok, why = go(rule(keep=5), count=5)
    assert not ok and "5 kept back" in why
    assert not go(count=0)[0]                       # none left at all
    assert go(count=None)[0]                        # not counted, no reserve asked
    assert not go(rule(keep=1), count=None)[0]      # not counted, a reserve asked


def test_not_on_the_hotbar_or_greyed_is_skipped():
    ok, why = go(slot=None)
    assert not ok and "cooling down" in why
    ok, why = go(slot=S(slot=3, greyed=True))
    assert not ok and "greyed" in why


def test_the_keeper_decides_unless_rule_over_ai():
    dice = rule(item="field_dice")
    ok, why = go(dice, keeper_on=True)
    assert not ok and "rule over AI" in why
    assert go({**dice, "over_ai": True}, keeper_on=True)[0]
    assert go(dice, keeper_on=False)[0]
    assert go(keeper_on=True)[0]                    # not an item the keeper uses


def test_the_boost_ai_veto_always_stands():
    dice = {**rule(item="field_dice"), "over_ai": True}
    ok, why = go(dice, keeper_on=True, vetoed=lambda: True)
    assert not ok and "vetoed" in why
    assert go(dice, vetoed=lambda: False)[0]


# ---- the Boosting tab's card ----------------------------------------------------
def test_the_card_adds_edits_and_removes_rules():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from hivemind.gui.panels.boosting import HotbarRules
    saved = []
    card = HotbarRules({"hotbar.rules": []}, lambda k, v: saved.append((k, v)))
    assert not card.empty.isHidden() and card.rows == []
    card.add()
    card.add()
    assert [r["item"] for r in card.rules] == ["coconut", "field_dice"]
    assert not card.rows[0].over_ai.isEnabled()        # the keeper never uses coconuts
    row = card.rows[1]
    assert row.over_ai.isEnabled()
    row.trigger.setCurrentIndex(row.trigger.findData("gathering"))
    assert row.minutes.isHidden() and not row.seconds.isHidden()
    row.seconds.setValue(45)
    row.field.setCurrentIndex(row.field.findData("Blue Flower"))
    row.keep.setValue(3)
    row.over_ai.setChecked(True)
    key, value = saved[-1]
    assert key == "hotbar.rules"
    assert value[1] == {**rule(item="field_dice"), "trigger": "gathering", "seconds": 45,
                        "field": "Blue Flower", "keep": 3, "over_ai": True}
    assert schema.hotbar_rules(value)[1] == []         # what it saves, the bot takes
    card.remove(0)
    assert [r["item"] for r in saved[-1][1]] == ["field_dice"]
    for _ in range(9):
        card.add()
    assert len(card.rules) == schema.HOTBAR_MAX and not card.add_button.isEnabled()
    card.show_rules([])
    assert card.rows == [] and card.add_button.isEnabled()
