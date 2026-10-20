"""A field whose walk home misses pays for the rejoins its misses cost
(brain/decide Planner.home_odds, FAILED_HOME_WALK_SECONDS).

var/skill_stats.json, 2026-09-29: Dandelion's walk home landed 2 of 14 and Pine
Tree's 178 of 188, and the planner priced both as landing every time.
"""
from __future__ import annotations

import pytest

from hivemind.brain.decide import (FAILED_HOME_WALK_SECONDS, REJOIN_SECONDS, Planner,
                                   Situation)
from hivemind.brain.fieldnotes import FieldNotes, Note


def _two_equal_fields():
    notes = FieldNotes()
    for name in ("strawberry", "blue_flower"):
        notes.notes[name] = Note(field=name, proven=True, visits=3, seconds=900.0,
                                 pollen=300_000, paid_seconds=900.0, paid_pollen=300_000)
    fields = {"strawberry": {"flowers": 400, "mobs": []},
              "blue_flower": {"flowers": 400, "mobs": []}}
    return fields, notes


def _ranked(home_odds, walk_home=("strawberry", "blue_flower")):
    fields, notes = _two_equal_fields()
    p = Planner(fields, notes, reachable={"strawberry", "blue_flower"},
                walk_home=set(walk_home), trip_seconds=1000.0)
    p.home_odds = home_odds
    return {s.field: s for s in p.rank(Situation(pollen=0, capacity=1_000_000))}


def test_the_field_whose_walk_home_misses_ranks_below_the_one_whose_lands():
    odds = {"strawberry": (0.9, "; home 9 of 10"), "blue_flower": (0.2, "; home 2 of 10")}
    ranked = _ranked(lambda name: odds[name])
    assert ranked["strawberry"].score > ranked["blue_flower"].score
    cost = FAILED_HOME_WALK_SECONDS + REJOIN_SECONDS
    expected = (1000.0 / (1000.0 + 0.8 * cost)) / (1000.0 / (1000.0 + 0.1 * cost))
    assert ranked["blue_flower"].score / ranked["strawberry"].score == pytest.approx(expected)
    assert "home 2 of 10" in ranked["blue_flower"].why


def test_a_walk_home_that_always_lands_costs_nothing():
    ranked = _ranked(lambda name: (1.0, ""))
    assert ranked["strawberry"].score == ranked["blue_flower"].score


def test_no_odds_means_no_price_and_a_failing_lookup_is_no_price_either():
    plain = _ranked(None)
    assert plain["strawberry"].score == plain["blue_flower"].score

    def broken(name):
        raise RuntimeError("no skills file")
    ranked = _ranked(broken)
    assert ranked["strawberry"].score == plain["strawberry"].score


def test_a_field_without_a_walk_home_is_not_charged_twice():
    """It already pays the whole rejoin (REJOIN_SECONDS); home_odds is only for
    walks home that exist."""
    seen = []

    def odds(name):
        seen.append(name)
        return (0.0, "; never lands")
    _ranked(odds, walk_home=("strawberry",))
    assert "blue_flower" not in seen


def test_a_held_rescue_item_prices_a_miss_as_a_respawn_once_live():
    from hivemind.brain import decide
    held = lambda name: (0.8, "; home", name == "strawberry")  # noqa: E731
    old = decide.MISS_RESCUE_PRICED_LIVE
    try:
        decide.MISS_RESCUE_PRICED_LIVE = False
        ranked = _ranked(held)
        assert ranked["strawberry"].score == ranked["blue_flower"].score
        assert "look-only" in ranked["strawberry"].why
        decide.MISS_RESCUE_PRICED_LIVE = True
        ranked = _ranked(held)
        assert ranked["strawberry"].score > ranked["blue_flower"].score
        rescued = 0.2 * (FAILED_HOME_WALK_SECONDS + decide.RESCUED_MISS_SECONDS)
        stranded = 0.2 * (FAILED_HOME_WALK_SECONDS + REJOIN_SECONDS)
        assert ranked["strawberry"].score / ranked["blue_flower"].score == pytest.approx(
            (1000.0 + stranded) / (1000.0 + rescued))
    finally:
        decide.MISS_RESCUE_PRICED_LIVE = old
