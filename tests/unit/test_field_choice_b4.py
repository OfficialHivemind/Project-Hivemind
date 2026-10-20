"""B4: one field choice from rates, quests and a running boost (decide.score_v2)."""
from __future__ import annotations

import pytest

from hivemind.brain.decide import FieldScore, boosted_gather, v2_rank

STATS = {"_": {"hpp": 1.5, "travel_s": 60.0, "convert_s": 190.0},
         "pine_tree_forest": {"gather_s": 600.0, "travel_s": 60.0, "hpp": 1.5,
                              "deaths": 0, "seconds": 50_000.0},
         "bamboo_field": {"gather_s": 600.0, "travel_s": 60.0, "hpp": 1.5,
                          "deaths": 0, "seconds": 50_000.0}}


def alts():
    return [FieldScore("pine_tree_forest", score=12_000, rate=12_000.0),
            FieldScore("bamboo_field", score=10_000, rate=10_000.0)]


def test_boosted_gather_shortens_the_trip():
    assert boosted_gather(6000.0, 10.0, 1.0, 900.0) == pytest.approx(600.0)
    assert boosted_gather(6000.0, 10.0, 2.0, 900.0) == pytest.approx(300.0)
    # boost runs out after 100 s: 2000 pollen fast, 4000 at the base rate
    assert boosted_gather(6000.0, 10.0, 2.0, 100.0) == pytest.approx(500.0)
    assert boosted_gather(6000.0, 10.0, 2.0, 0.0) == pytest.approx(600.0)


def test_no_boost_keeps_the_rate_order():
    assert v2_rank(alts(), STATS)[0][0].field == "pine_tree_forest"


def test_a_measured_boost_moves_the_choice():
    ranked = v2_rank(alts(), STATS, boosts={"bamboo_field": (1.45, 800.0)})
    assert ranked[0][0].field == "bamboo_field"
    assert "boost x1.45" in ranked[0][4]


def test_a_boost_gone_by_arrival_adds_nothing():
    plain = v2_rank(alts(), STATS)
    late = v2_rank(alts(), STATS, boosts={"bamboo_field": (1.45, 50.0)})
    assert [t[1] for t in late] == [t[1] for t in plain]


def test_quests_and_boosts_combine():
    # Pine owes a quest worth a little; a strong boost on Bamboo still wins it.
    bonus = {"pine_tree_forest": (0.5, 1_000_000)}
    assert v2_rank(alts(), STATS, bonus)[0][0].field == "pine_tree_forest"
    both = v2_rank(alts(), STATS, bonus, boosts={"bamboo_field": (3.0, 900.0)})
    assert both[0][0].field == "bamboo_field"
