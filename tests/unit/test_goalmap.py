"""The goal web must describe the OWNER'S GUIDE, not decorate a plan of ours.

Rewritten 2026-09-21. The previous version tested a `build_order` list that was
this project's own paraphrase of the guide, alongside a wiki ladder drawn as
goals in its own right. The owner looked at the result and said the goals looked
wrong and should follow this guide, so the shape being tested changed:
the guide's stage checklists are the spine, and the ladder is demoted to
supplying prices underneath them. See brain/goalmap.
"""
from __future__ import annotations

import pytest

from hivemind.brain.goalmap import (BLOCKED, DOING, DONE, READY, SKIP,
                                    UNKNOWN, build, current_stage)
from hivemind.brain.progress import Ladder, Standing
from hivemind.brain.questneeds import Need, Needs

PLAN = {
    "baseline": {"comp": "16 Buoyants | 7 Tadpoles", "say": "aim for 16"},
    "standing": {"stage": 1},
    "stages": [
        {"id": 1, "name": "Stage 1 — Earlygame Blue",
         "comp": "13-14 Bubbles | 5 Diamonds", "say": "bubbles stand in",
         "progression": [
             {"say": "Get any SSA with Popstar", "note": "stats don't matter"},
             {"say": "48 Bees", "needs": "bees", "target": 48,
              "serves": ["basic_egg", "hive_slot"]},
             {"say": "Level up to 15", "needs": "level", "target": 15},
         ]},
        {"id": 2, "name": "Stage 2 — Transition Blue", "comp": "10 | 12 | 2",
         "say": "bridge the gap",
         "progression": [
             {"say": "50 Bees", "needs": "bees", "target": 50,
              "serves": ["basic_egg"]},
         ]},
    ],
    "tools": {"named_by_the_guide": ["petal", "tide"],
              "say_overall": "obtained ASAP without a strict timeline"},
    "our_disagreements": {
        "bubble_wand": {"guide_says": "colour-specific collectors ASAP",
                        "verdict": "DO NOT BUY IT YET — 1.02x here"},
    },
}
DATA = {
    "tools": {"order": ["golden_rake", "bubble_wand"],
              "known": {"bubble_wand": {"honey": 3_500_000, "shop": "blue_hq",
                                        "pollen_per_second": 120,
                                        "pollen_per_second_blue": 240},
                        "golden_rake": {"honey": 20_000_000,
                                        "pollen_per_second": 149.33}}},
    "hive": {"base_slots": 25, "max_slots": 50, "slot_cost": "unknown",
             "slots_bought_at": "mountain_top_shop"},
    "bees": {"basic_egg": {"shop": "basic_egg_shop", "honey_from": 1_000,
                           "honey_cap": 10_000_000}},
    "wanted": {"blue_hive": {"quote": "a blue hive",
                             "do_this": ["keep blue bees"]}},
}
WORLD = {"coconut": {"bees_required": 35}}


class Chose:
    action, field, why = "gather", "pineapple", "759 flowers, blue-leaning"


@pytest.fixture
def ladder():
    return Ladder(DATA, WORLD)


@pytest.fixture
def standing():
    return Standing(honey=29_868_790, bees=26, tool="golden_rake",
                    colour="blue", fields_proven=("strawberry", "pineapple"))


# ---------------------------------------------------------------- the spine --
def test_an_empty_plan_makes_an_empty_map():
    assert build(Ladder({}, {}), Standing()).nodes == []


def test_the_spine_is_the_guides_own_checklist(ladder, standing):
    """Verbatim, and in the guide's order. Not a paraphrase of it."""
    m = build(ladder, standing, PLAN)
    spine = [n.label for n in m.ordered() if n.kind == "goal" and n.priority < 40]
    assert spine == ["Get any SSA with Popstar", "48 Bees", "Level up to 15"]


def test_the_checklist_becomes_a_chain(ladder, standing):
    m = build(ladder, standing, PLAN)
    chain = {(e.before, e.after) for e in m.edges if e.why == "comes first"}
    assert ("get_any_ssa_with_popstar", "48_bees") in chain
    assert ("48_bees", "level_up_to_15") in chain


def test_the_chain_ends_at_the_baseline_hive(ladder, standing):
    m = build(ladder, standing, PLAN)
    assert any(e.after == "target" for e in m.edges)
    assert m.node("target").label == "16 Buoyants | 7 Tadpoles"


def test_nothing_the_guide_never_mentions_is_drawn_as_a_goal(ladder, standing):
    """REGRESSION, and the reason this file was rewritten.

    The wiki ladder proposed the Porcelain Dipper at 150,000,000 honey and the
    Coconut Field. Neither appears in the guide, and both were being drawn as
    goals beside it.
    """
    labels = " ".join(n.label.lower() for n in build(ladder, standing, PLAN).nodes)
    assert "porcelain" not in labels
    assert "coconut" not in labels


# ------------------------------------------------------------- which stage --
def test_the_stage_comes_from_the_bee_count(ladder):
    assert current_stage(PLAN, Standing(bees=26))["id"] == 1
    assert current_stage(PLAN, Standing(bees=49))["id"] == 2


def test_no_bee_count_falls_back_to_the_recorded_stage(ladder):
    assert current_stage(PLAN, Standing(bees=None))["id"] == 1


# -------------------------------------------------------- checkable or not --
def test_a_checkable_item_shows_real_progress(ladder, standing):
    node = build(ladder, standing, PLAN).node("48_bees")
    assert node.progress == "26 / 48"
    assert node.state == READY


def test_a_met_item_is_done(ladder):
    standing = Standing(honey=1, bees=60, colour="blue")
    assert build(Ladder(DATA, WORLD), standing, PLAN).node("50_bees").state == DONE


def test_an_uncheckable_item_says_so_rather_than_guessing(ladder, standing):
    """UNKNOWN and BLOCKED are different: blocked means something is in the
    way, unknown means nobody has looked."""
    level = build(ladder, standing, PLAN).node("level_up_to_15")
    assert level.state == UNKNOWN
    assert "cannot read your level" in level.why


# ------------------------------------------------- prices, said honestly ----
def test_a_price_that_is_a_range_is_never_collapsed_to_its_floor(ladder, standing):
    """REGRESSION. The Basic Egg was drawn as "1,000 honey" in green next to
    the word "ready" -- an instruction to buy something whose real price climbs
    to 10,000,000 and can only be read in the shop. The owner caught it:
    the Basic Egg's price changes, so it must not be a set price."""
    egg = build(ladder, standing, PLAN).node("how_basic_egg")
    assert egg is not None
    assert egg.money == "from 1,000 honey, up to 10,000,000"
    assert egg.state == UNKNOWN, "a price we cannot know is never 'ready'"


def test_a_mechanism_hangs_under_the_goal_it_serves(ladder, standing):
    m = build(ladder, standing, PLAN)
    assert ("how_basic_egg", "48_bees") in {(e.before, e.after) for e in m.edges}
    assert m.node("how_basic_egg").kind == "mechanism"


def test_a_cost_we_do_not_know_is_never_shown_as_a_number(ladder, standing):
    assert build(ladder, standing, PLAN).node("how_hive_slot").money == ""


# ----------------------------------------------------------------- quests --
def _needs():
    return Needs(
        pollen={"blue": Need(colour="blue", target=820020, done=820020)},
        fields={"sunflower": Need(colour="sunflower", target=320020, done=158),
                "strawberry": Need(colour="strawberry", target=150000, done=0)},
        fights=["Defeat 15 Scorpions. 0/15"],
        tokens=["Collect 100 Focus Tokens. 12/100"],
        # a finished requirement as the menu words it (questneeds
        # `ready_to_hand_in`, MEASURED 2026-09-23 04:34)
        handed=["Collect 2,000 Honey Tokens. Complete! Talk to Honey Bee."],
        unread=['"Honey Bee\'s Honey Hunt" is ready to turn in!'])


def test_quests_become_goals(ladder, standing):
    """The owner asked for it: read the quests they have, so it knows what goals
    to set next."""
    m = build(ladder, standing, PLAN, quests=_needs())
    assert m.node("quest_field_sunflower") is not None
    assert m.node("quest_field_sunflower").progress == "158 / 320,020"


def test_a_quest_in_a_field_we_cannot_reach_says_exactly_that(ladder, standing):
    m = build(ladder, standing, PLAN, quests=_needs())
    assert m.node("quest_field_sunflower").state == BLOCKED
    assert "NO RECORDED ROUTE" in m.node("quest_field_sunflower").why
    # strawberry IS reachable, so it is actionable today
    assert m.node("quest_field_strawberry").state == READY


def test_a_finished_quest_is_surfaced_as_unclaimed(ladder, standing):
    m = build(ladder, standing, PLAN, quests=_needs())
    node = next(n for n in m.nodes if n.key.startswith("quest_turnin"))
    assert "unclaimed" in node.why.lower() and "honey bee" in node.label


def test_a_completed_requirement_is_not_drawn_as_outstanding(ladder, standing):
    """Blue pollen is done; it must not appear as a goal."""
    m = build(ladder, standing, PLAN, quests=_needs())
    assert m.node("quest_colour_blue") is None


def test_unactionable_quest_steps_say_why(ladder, standing):
    m = build(ladder, standing, PLAN, quests=_needs())
    fight = next(n for n in m.nodes if n.key.startswith("quest_fight"))
    token = next(n for n in m.nodes if n.key.startswith("quest_token"))
    assert "cannot fight" in fight.why
    # the chase prefers a kind a quest wants now (run_farm, Kinds.want)
    assert "token chase" in token.why


def test_no_quests_read_still_draws_the_web(ladder, standing):
    """A goal web that vanishes when a read fails vanishes exactly when
    something is wrong."""
    assert build(ladder, standing, PLAN, quests=None).nodes


# ------------------------------------------------------------- the rest ----
def test_the_current_decision_is_its_own_node(ladder, standing):
    m = build(ladder, standing, PLAN, Chose())
    now = m.node("now")
    assert now is not None and now.state == DOING
    assert "pineapple" in now.label
    assert "759 flowers" in now.why
    assert m.headline.startswith("right now:")


def test_a_disagreement_with_the_guide_is_a_warning_not_a_goal(ladder, standing):
    node = build(ladder, standing, PLAN).node("skip_bubble_wand")
    assert node.state == SKIP
    assert "DO NOT BUY" in node.why
    assert "guide says" in node.detail


def test_the_same_goal_is_never_drawn_twice(ladder, standing):
    keys = [n.key for n in build(ladder, standing, PLAN, Chose(),
                                 quests=_needs()).nodes]
    assert len(keys) == len(set(keys))


def test_every_node_carries_a_reason(ladder, standing):
    for node in build(ladder, standing, PLAN, Chose(), quests=_needs()).nodes:
        assert node.why or node.detail or node.progress, \
            f"{node.key} explains nothing"


def test_describe_reads_as_text(ladder, standing):
    text = build(ladder, standing, PLAN, Chose(), quests=_needs()).describe()
    assert "right now" in text
    assert "48 Bees" in text
    assert "Stage 1" in text
