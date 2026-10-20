"""The pro tester's round-1 answers (19 Oct 2026) as rules: brain/protips and
where it is wired. One small test per rule."""
from __future__ import annotations

import json
from pathlib import Path

import hivemind
from hivemind.brain import protips, questneeds
from hivemind.brain.decide import Planner, Situation
from hivemind.brain.fieldnotes import FieldNotes, Note
from hivemind.world.settings import MACRO_ENTRY, defaults

ROOT = Path(hivemind.__file__).resolve().parents[2]
FIELDS = {
    "sunflower": {"bees_required": 0, "flowers": 660, "mobs": [], "safe": True},
    "pine_tree": {"bees_required": 0, "flowers": 713, "mobs": [], "safe": True},
    "rose": {"bees_required": 0, "flowers": 620, "mobs": [], "safe": True},
}


def paid(**rates):
    notes = FieldNotes()
    for name, rate in rates.items():
        notes.notes[name] = Note(field=name, pollen=rate * 600, seconds=600.0,
                                 paid_pollen=rate * 600, paid_seconds=600.0)
    return notes


def best(notes, **kw):
    return Planner(FIELDS, notes, **kw).rank(Situation(pollen=0))[0].field


# 1 -----------------------------------------------------------------------
def test_pine_tree_breaks_a_close_tie_but_not_a_clear_measurement():
    assert best(paid(sunflower=1000, pine_tree=950, rose=100)) == "pine_tree"
    assert best(paid(sunflower=1000, pine_tree=800, rose=100)) == "sunflower"


def test_pine_tree_never_passes_a_field_a_quest_names():
    from hivemind.brain.decide import QUEST_BONUS
    needs = questneeds.from_lines(["Collect 9,000,000 Pollen from the Sunflower Field. 0/9,000,000"])
    close = 1000 * (1 + QUEST_BONUS) * 0.95          # within the tie of the quest-tilted lead
    assert best(paid(sunflower=1000, pine_tree=close, rose=100), quest_needs=needs) == "sunflower"
    assert best(paid(sunflower=1000 * (1 + QUEST_BONUS), pine_tree=close, rose=100)) == "pine_tree"


# 2 -----------------------------------------------------------------------
def test_convert_at_defaults_to_95():
    assert defaults()["gather.convert_at"] == protips.CONVERT_AT == 95
    assert MACRO_ENTRY["convert_at"] == 95


# 3 -----------------------------------------------------------------------
def test_a_weak_field_a_quest_needs_still_goes_first_with_quests_first():
    needs = questneeds.from_lines(["Collect 9,000,000 Pollen from the Rose Field. 0/9,000,000"])
    p = Planner(FIELDS, paid(sunflower=1000, pine_tree=1000, rose=100), quest_needs=needs)
    p.quest_first = True
    assert p.rank(Situation(pollen=0))[0].field == "rose"


# 4 -----------------------------------------------------------------------
def test_the_pattern_centre_is_the_middle_of_its_path():
    square = [{"op": "walk", "keys": "w", "studs": 10}, {"op": "walk", "keys": "d", "studs": 6},
              {"op": "walk", "keys": "s", "studs": 10}, {"op": "walk", "keys": "a", "studs": 6}]
    assert protips.pattern_centre(square) == (3.0, 5.0)
    turned = [{"op": "camera", "direction": "right"}] * 2 + [{"op": "walk", "keys": "w", "studs": 8}]
    dx, dy = protips.pattern_centre(turned)            # two right taps: w walks right
    assert round(dx, 6) == 4.0 and round(dy, 6) == 0.0
    assert protips.SPRINKLER_AT_PATTERN_CENTRE_LIVE is False


# 5 + 6 -------------------------------------------------------------------
def test_giver_order_mother_black_polar_and_the_panda_unrushed():
    walk = ("bucko_bee", "black_bear", "brown_bear", "polar_bear", "mother_bear",
            "spirit_bear", "panda_bear")
    assert protips.giver_order(walk, mains_done=False) == (
        "mother_bear", "black_bear", "polar_bear", "spirit_bear",
        "bucko_bee", "brown_bear", "panda_bear")
    assert protips.giver_order(walk, mains_done=True)[0] == "polar_bear"


# 7 -----------------------------------------------------------------------
def test_gummy_gear_unknown_is_not_owned(tmp_path):
    assert protips.gummy_owned(tmp_path) == ""
    assert protips.gummy_owned(tmp_path, {"gummy_boots": 1}) == "Gummy Boots"
    (tmp_path / "bees.json").write_text(json.dumps({"bees": {"gummy": 1}}))
    assert protips.gummy_owned(tmp_path) == "Gummy Bee"


def test_dropping_goo_keeps_a_bigger_goo_fields_pollen_step():
    needs = questneeds.from_lines([
        "Collect 13,000,000 Goo from the Bamboo Field. 0/13,000,000",
        "Collect 50,000,000 Pollen from the Bamboo Field. 45,000,000/50,000,000"])
    assert needs.field_remaining("bamboo") == 13_000_000          # the goo, the larger
    needs.goo_fields_dropped()
    assert needs.field_remaining("bamboo") == 5_000_000           # the pollen step stays


# 8 -----------------------------------------------------------------------
def test_starter_fields_are_the_zero_bee_ones():
    assert protips.starter_field({"bees_required": 0})
    assert not protips.starter_field({"bees_required": 25})
    assert not protips.starter_field(None)


# 9 -----------------------------------------------------------------------
def test_materials_boost_only_from_hive_level_16():
    assert protips.material_boost_ok("material", None)[0] is False      # unknown
    assert protips.material_boost_ok("material", 15)[0] is False
    assert protips.material_boost_ok("material", 16)[0] is True
    assert protips.material_boost_ok("bee_boost", None)[0] is True       # not a material
    assert protips.hive_level({"hive": {"bees": 42}}) is None
    assert protips.hive_level({"hive": {"level": 17}}) == 17.0


# 10 ----------------------------------------------------------------------
def test_the_big_combo_is_said_not_done():
    said = protips.big_combo("pine_tree", {"loaded_dice": 1, "glitter": 3,
                                           "super_smoothie": None, "purple_potion": 2})
    assert "Loaded Dice now on pine tree" in said and "+5:00" in said and "purple potion" in said
    assert "not now" in protips.big_combo("pine_tree", {"glitter": 3})


def test_the_safe_first_run_preset_converts_at_95():
    preset = ROOT / "data" / "presets" / "safe-first-run.yaml"
    assert "gather.convert_at: 95" in preset.read_text()


# ===================== ROUND 2 (20 Oct 2026, answers 11-20) =====================
from types import SimpleNamespace as NS  # noqa: E402


# 11 ----------------------------------------------------------------------
def test_the_pro_gear_order_is_offered_not_applied():
    from hivemind.brain import goals
    data = goals.load()
    blue = [k for k, _e in protips.suggested_order("blue", data)]
    assert blue == ["petal_belt", "crimson_guard", "coconut_clogs", "coconut_canister",
                    "petal_wand", "supreme_saturator", "tide_popper"]
    assert protips.suggested_order("red", data)[-1][0] == "dark_scythe"
    entries = dict(protips.suggested_order("blue", data))
    assert entries["petal_belt"]["honey"] == 15_000_000_000          # wiki rev 448413
    assert entries["petal_belt"]["materials"]["spirit_petal"] == 1
    assert entries["supreme_saturator"]["honey"] == 55_555_555_555   # wiki rev 441788
    assert entries["crimson_guard"] is data["goals"]["crimson_guard"]
    merged, order = protips.with_suggested(data, "blue")
    assert order == blue and "petal_belt" in merged["goals"]
    assert "petal_belt" not in data["goals"]                          # data untouched
    assert "petal_belt" not in data["default_order"]                  # his order untouched
    plan = goals.build(merged, order=order, honey=0)
    assert [r.key for r in plan.rows] == blue


# 12 ----------------------------------------------------------------------
def test_the_slot_rule_is_current_unless_the_owner_picks_pro():
    from hivemind.world.settings import defaults
    assert defaults()[protips.SLOT_RULE_SETTING] == "current"
    rows = [NS(key="hive_slot_43", owned=False, cost=4_000_000_000, label="Hive Slot"),
            NS(key="diamond_mask", owned=False, cost=5_000_000_000, label="Diamond Mask")]
    assert protips.slot_rule(6_000_000_000, rows, "current") == (True, "")
    assert protips.slot_rule(4_000_000_000, rows, "pro")[0] is True
    ok, why = protips.slot_rule(6_000_000_000, rows, "pro")
    assert not ok and "Diamond Mask" in why
    assert protips.slot_rule(6_000_000_000, rows[:1], "pro")[0] is True   # no gear open


# 13 ----------------------------------------------------------------------
def test_a_roll_is_kept_only_for_a_new_gifted_type():
    assert protips.keep_jelly_roll("bucko", True, ["baby", "bubble"])[0] is True
    keep, why = protips.keep_jelly_roll("bubble", True, ["baby", "bubble"])
    assert keep is False and "roll on" in why
    assert protips.keep_jelly_roll("bucko", False, [])[0] is False
    assert protips.JELLY_ROLL_PAST_GIFTED_DUPLICATE_LIVE is False


# 14 ----------------------------------------------------------------------
def test_treats_go_to_an_event_bee_first():
    types = {"bear": {"rarity": "event"}, "cobalt": {"rarity": "event"},
             "bubble": {"rarity": "rare"}}
    assert protips.feed_target({"bubble": 13, "cobalt": 1, "bear": 2}, types) == "bear"
    assert protips.feed_target({"bubble": 13}, types) is None
    assert protips.FEED_EVENT_BEES_LIVE is False


# 15 ----------------------------------------------------------------------
def test_a_boss_measured_to_lose_is_skipped_an_unpriced_one_is_not():
    assert protips.boss_worth(None) == (True, "")
    assert protips.boss_worth(-5000.0, ["star_jelly"])[0] is True
    assert protips.boss_worth(1000.0)[0] is True
    assert protips.boss_worth(-5000.0)[0] is False


def test_the_commando_visit_q_is_none_until_a_visit_is_timed():
    from hivemind.act import commando
    assert commando.visit_q({}, 1000.0)[0] is None
    state = {"captures": 0, "tries": [{"took": 100.0, "result": "killed"}]}
    q, unpriced, took, won = commando.visit_q(state, 1e9)
    assert q is not None and q < 0 and took == 100.0 and won == 1.0


# 16 ----------------------------------------------------------------------
def test_mondo_loot_only_in_an_hour_a_quest_wants_it():
    from hivemind.act import mondo
    on = NS(bool=lambda key: True)
    live, said = mondo.Watch().heard("Defeated Mondo Chick!", "mountain_top", on, 0.0,
                                     quest_wants=0)
    assert not live and "skipped" in said
    live, said = mondo.Watch().heard("Defeated Mondo Chick!", "mountain_top", on, 0.0,
                                     quest_wants=1)
    assert said.startswith("mondo loot would: ")


# 19 + 20 -----------------------------------------------------------------
def test_the_payback_ranking_says_what_it_does_not_price():
    from hivemind.brain import roi
    text = roi.Ranking().text()
    assert protips.EFFICIENCY_NOTE in text and "Baby Love" in text


def test_round_two_rules_are_in_the_playbook():
    from hivemind.brain import knowledge
    knowledge._load.cache_clear()
    ids = {r["id"]: r for r in knowledge.playbook()}
    for rid in ("pro_gear_order", "pro_slots_until_dearer_than_the_gear",
                "pro_keep_a_new_gifted_type", "pro_treats_to_event_bees_first",
                "pro_bosses_not_worth_the_time", "pro_mondo_only_some_hours",
                "pro_robo_bear_challenge", "pro_ant_challenge_dodge",
                "pro_efficiency_buffs_over_gear", "pro_efficiency_before_macroing"):
        assert ids[rid]["confidence"] == "expert" and "round 2" in ids[rid]["source"]
