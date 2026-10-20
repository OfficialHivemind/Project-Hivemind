"""Wanting something, and knowing the distance. See brain/progress.py."""
from __future__ import annotations

import pathlib

import pytest

from hivemind.brain.decide import load_fields
from hivemind.brain.progress import Goal, Ladder, Standing, load

ROOT = pathlib.Path(__file__).resolve().parents[2]

DATA = {
    "tools": {
        "order": ["scooper", "rake", "golden_rake", "spark_staff", "petal_wand"],
        "known": {"rake": {"honey": 800, "shop": "noob_shop"},
                  "spark_staff": {"honey": 60_000_000,
                                  "shop": "mountain_top_shop"}},
        "unpriced": ["golden_rake", "petal_wand"],
        "shops": {"petal_shop": {"honey_from": 1_500_000_000}},
    },
    "hive": {"base_slots": 25, "max_slots": 50, "slot_cost": "unknown",
             "slots_bought_at": "mountain_top_shop"},
    "not_yet_known": {"eggs": "how bees are obtained"},
}
WORLD = {"sunflower": {"bees_required": 0}, "pine_tree": {"bees_required": 15},
         "coconut": {"bees_required": 35}, "pepper": {"bees_required": 35}}


@pytest.fixture
def ladder():
    return Ladder(DATA, WORLD)


# ---- the next thing to buy ------------------------------------------------
def test_it_aims_at_the_rung_above_the_tool_held(ladder):
    goal = ladder.next_tool(Standing(honey=6_198_839, tool="golden_rake"))
    assert goal.name == "spark_staff" and goal.cost == 60_000_000


def test_it_says_how_far_short_we_are(ladder):
    goal = ladder.next_tool(Standing(honey=6_198_839, tool="golden_rake"))
    assert goal.shortfall == 53_801_161
    assert "53,801,161" in goal.describe()


def test_something_affordable_says_so(ladder):
    goal = ladder.next_tool(Standing(honey=5_000, tool="scooper"))
    assert goal.reachable_now and "affordable now" in goal.describe()


def test_an_unpriced_rung_is_still_a_goal(ladder):
    """A planner that skipped unpriced things would look complete and would
    never once suggest buying a bee."""
    goal = ladder.next_tool(Standing(honey=1_000, tool="rake"))
    assert goal.name == "golden_rake"
    assert goal.cost is None
    assert "do not know what it costs" in goal.blocked_by


def test_an_unknown_tool_aims_at_the_bottom_rung(ladder):
    assert ladder.next_tool(Standing(tool=None)).name == "scooper"


def test_the_last_tool_has_nothing_above_it(ladder):
    assert ladder.next_tool(Standing(tool="petal_wand")) is None


def test_unknown_honey_is_not_treated_as_none_held(ladder):
    goal = ladder.next_tool(Standing(honey=None, tool="golden_rake"))
    assert goal.shortfall is None, "unknown honey must not read as zero honey"


# ---- bees and the map -----------------------------------------------------
def test_the_next_field_is_the_cheapest_one_still_locked(ladder):
    goal = ladder.next_field(Standing(bees=15))
    assert goal.name in {"coconut", "pepper"}
    assert "needs 35 bees" in goal.blocked_by


def test_a_field_already_proven_is_not_a_goal(ladder):
    goal = ladder.next_field(Standing(bees=0, fields_proven=("pine_tree",)))
    assert goal.name != "pine_tree"


def test_no_locked_fields_means_no_field_goal(ladder):
    assert ladder.next_field(Standing(bees=99)) is None


def test_an_unknown_bee_count_asks_for_no_field(ladder):
    assert ladder.next_field(Standing(bees=None)) is None


# ---- hive slots -----------------------------------------------------------
def test_hive_slots_are_wanted_and_honestly_unpriced(ladder):
    goal = ladder.next_hive_slot(Standing(honey=6_000_000, bees=25))
    assert goal.cost is None
    assert "read in game" in goal.blocked_by
    assert "mountain top shop" in goal.blocked_by


def test_a_full_hive_wants_no_more_slots(ladder):
    assert ladder.next_hive_slot(Standing(bees=50)) is None


# ---- the whole picture ----------------------------------------------------
def test_affordable_goals_come_before_distant_ones(ladder):
    """With no rates recorded it falls back to list order, still skipping traps."""
    goals = ladder.goals(Standing(honey=60_000_000, bees=25, tool="golden_rake"))
    assert goals[0].name == "spark_staff" and goals[0].reachable_now
    assert goals[0].cost == 60_000_000


def test_unpriceable_goals_sort_last(ladder):
    """They are research tasks, not plans."""
    goals = ladder.goals(Standing(honey=1_000, bees=25, tool="golden_rake"))
    assert goals[-1].cost is None


def test_it_lists_the_holes_in_its_own_knowledge(ladder):
    holes = ladder.unknowns()
    assert any("eggs" in h for h in holes)
    assert any("2 of 5 tools have no price" in h for h in holes)


def test_describe_reads_like_a_person_wrote_it(ladder):
    text = ladder.describe(Standing(honey=6_198_839, bees=25,
                                    tool="golden_rake"))
    assert "6,198,839" in text
    assert "spark staff" in text     # this fixture does not mark it a trap
    assert "does not know" in text


def test_a_missing_file_is_not_fatal(tmp_path):
    assert load(tmp_path / "gone.yaml") == {}
    assert Ladder({}, {}).goals(Standing()) == []


# ---- against the real shipped knowledge -----------------------------------
def test_the_real_progression_file_answers_the_owners_question():
    """6.2M honey, Golden Rake, 25 bees proved: what next?"""
    lad = Ladder(load(ROOT / "data/knowledge/progression.yaml"),
                 load_fields(ROOT / "data/knowledge/world.yaml"))
    goals = lad.goals(Standing(honey=6_198_839, bees=25, tool="golden_rake",
                               colour="blue"))
    names = [g.name for g in goals]
    # THE OWNER'S CORRECTION, locked in: players rate the Spark Staff badly;
    # research what they say. It must never be the answer.
    assert "spark_staff" not in names
    assert "spark_staff" in lad.skip
    # THE OWNER'S SECOND CORRECTION, and it was worth 3,500,000 honey:
    # (is the Bubble Wand worse than the Golden Rake?) It is. The old assertion here
    # was that a blue hive should buy the colour-matched tool, which rested on
    # comparing the Bubble Wand's BLUE-ONLY 240 pollen/s against the Golden
    # Rake's 167 all-flower average -- as though every flower in a blue field
    # were blue. MEASURED over 420 frames of the Pineapple Patch the bot
    # actually farms: 42.5% blue, 46.8% white, 10.8% red. Blended honestly the
    # Bubble Wand is 171/s against 167/s, a 1.02x gain for 3.5 million honey.
    #
    # The price said so too, and nobody read it: this costs 3,500,000 and the
    # Golden Rake cost 20,000,000.
    assert "bubble_wand" not in names, (
        "a 1.02x sidegrade must never be recommended as the next purchase")
    assert lad.unknowns(), "it must admit what it has not looked up"


def test_a_cheap_tool_is_not_recommended_over_a_dearer_one_we_hold():
    """REGRESSION for the Bubble Wand. See the owner's correction above."""
    lad = Ladder(load(ROOT / "data/knowledge/progression.yaml"),
                 load_fields(ROOT / "data/knowledge/world.yaml"))
    standing = Standing(honey=6_198_839, bees=25, tool="golden_rake",
                        colour="blue")
    for goal in lad.upgrades(standing):
        held = (lad.known.get("golden_rake") or {}).get("honey") or 0
        if goal.cost and held and goal.cost < held:
            assert goal.blocked_by, (
                f"{goal.name} costs {goal.cost:,} against the {held:,} tool we "
                f"already hold and was offered without a warning")


def test_the_colour_bonus_is_blended_by_the_measured_flower_share():
    """240/s on blue flowers is not 240/s in a field that is 42.5% blue."""
    lad = Ladder(load(ROOT / "data/knowledge/progression.yaml"),
                 load_fields(ROOT / "data/knowledge/world.yaml"))
    blended = lad.rate_for("bubble_wand", "blue")
    assert blended is not None
    # Strictly between the two figures the wiki gives, and nowhere near 240.
    assert 120 < blended < 200
    assert blended < lad.rate_for("golden_rake", "blue") * 1.15
