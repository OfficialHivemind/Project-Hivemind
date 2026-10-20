"""ROADMAP A9, the death audit's rules (docs/pending/deaths-2026-10-19.md):
D1 a death on the walk home is that walk's miss, D2 a death the feed
overruled is taken back, D3 (look-only) a small bag's fall that left a Link's
share."""
from pathlib import Path

import hivemind
from hivemind.brain import alive
from hivemind.brain.fieldnotes import FieldNotes

RUN_FARM = Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py"


def test_d1_a_void_fall_on_the_walk_home_counts():
    # run-894 07:57:23: Rose's walk home began, the void took 1,401,423.
    assert alive.walk_home_death_counts(105.0, 100.0, 1_401_423, None)


def test_d1_not_a_death_before_the_walk_began():
    assert not alive.walk_home_death_counts(99.0, 100.0, 1_401_423, None)


def test_d1_not_a_small_one_nor_one_the_feed_overruled_nor_no_stamp():
    assert not alive.walk_home_death_counts(105.0, 100.0, 7_043, None)
    assert not alive.walk_home_death_counts(105.0, 100.0, 3_000_000, "pine_tree")
    assert not alive.walk_home_death_counts(None, 100.0, 3_000_000, None)


def test_d2_an_overruled_death_is_taken_back_once():
    notes = FieldNotes(clock=lambda: 0.0)
    notes.died("pine_tree")
    assert notes.known("pine_tree").deaths == 1
    assert notes.took_back_death("pine_tree")
    assert notes.known("pine_tree").deaths == 0
    assert not notes.took_back_death("pine_tree")
    assert not notes.took_back_death(None)


def test_d3_the_link_shaped_falls_and_not_the_big_deaths():
    # Trip-ending falls whose pad was then not there (run-1067 23:22,
    # run-1049 08:00) against real deaths of full bags (run-655 16:20,
    # run-652 05:04).
    assert alive.small_bag_fall_unproven(19_206, 3_678)
    assert alive.small_bag_fall_unproven(33_364, 13_320)
    assert not alive.small_bag_fall_unproven(783_957, 15_570)
    assert not alive.small_bag_fall_unproven(1_076_473, 8_936)
    assert not alive.small_bag_fall_unproven(1_418, 0)
    assert not alive.small_bag_fall_unproven(None, 5)


def test_the_farm_loop_uses_all_three():
    text = RUN_FARM.read_text()
    assert "walk_home_death_counts(" in text
    assert "notes.took_back_death(" in text
    assert "small_bag_fall_unproven(" in text
    assert '"elsewhere" if fell else' in text
