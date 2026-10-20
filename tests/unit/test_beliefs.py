"""The belief store.

The property that matters is not that it stores things -- a dict does that. It
is that a stale fact is INDISTINGUISHABLE FROM AN UNKNOWN ONE to a caller that
demanded freshness, so an irreversible action can never run on an old reading.
"""
import pytest

from hivemind.world.beliefs import (Belief, BeliefStore, Observation,
                                    choose_observation, half_life_for)


def test_a_fresh_observation_is_fully_trusted():
    store = BeliefStore()
    store.observe("bees", 25, source="hive")
    assert store.get("bees") == 25
    assert store.confidence("bees") == pytest.approx(1.0, abs=1e-3)


def test_confidence_halves_after_one_half_life():
    store = BeliefStore()
    now = 1000.0
    store.observe("bees", 25, at=now)
    half_life = half_life_for("bees")
    assert store.confidence("bees", now=now + half_life) == pytest.approx(0.5, abs=1e-6)
    assert store.confidence("bees", now=now + 2 * half_life) == pytest.approx(0.25, abs=1e-6)


def test_fast_moving_facts_decay_faster_than_slow_ones():
    """Pollen changes every second; owned tools essentially never do."""
    assert half_life_for("pollen") < half_life_for("bees") < half_life_for("tool")


def test_prefix_match_picks_the_longest_prefix():
    assert half_life_for("tool:golden_rake") == half_life_for("tool")
    assert half_life_for("something_unlisted") == half_life_for("anything_else")


def test_a_stale_fact_reads_as_unknown_when_freshness_is_demanded():
    """The core safety property."""
    store = BeliefStore()
    now = 1000.0
    store.observe("royal_jelly", 3410, at=now)
    much_later = now + half_life_for("royal_jelly") * 6      # confidence ~1.5%

    assert store.get("royal_jelly", now=much_later) == 3410          # curious read
    assert store.get("royal_jelly", min_confidence=0.9,
                     now=much_later) is None                          # spend read
    assert not store.knows("royal_jelly", 0.9, now=much_later)


def test_re_observing_restores_confidence():
    store = BeliefStore()
    now = 1000.0
    store.observe("bees", 25, at=now)
    later = now + half_life_for("bees") * 3
    assert store.confidence("bees", now=later) < 0.2
    store.observe("bees", 26, at=later)
    assert store.confidence("bees", now=later) == pytest.approx(1.0, abs=1e-3)
    assert store.get("bees", now=later) == 26


def test_invalidate_makes_a_fact_unknown_immediately():
    """Used after spending: we know the old number is now wrong."""
    store = BeliefStore()
    store.observe("royal_jelly", 3410)
    store.invalidate("royal_jelly")
    assert store.get("royal_jelly") is None
    assert store.confidence("royal_jelly") == 0.0


def test_partial_confidence_is_reported_not_rounded():
    store = BeliefStore()
    store.observe("bees", 25, confidence=0.6)
    assert store.confidence("bees") == pytest.approx(0.6, abs=1e-3)


def test_stale_lists_worst_first():
    store = BeliefStore()
    now = 1000.0
    store.observe("bees", 25, at=now - 100)
    store.observe("pollen", 400, at=now - 100)      # much shorter half-life
    worst = store.stale(min_confidence=0.99, now=now)
    assert worst[0].name == "pollen"


def test_on_change_fires_for_each_observation():
    seen = []
    store = BeliefStore(on_change=seen.append)
    store.observe("bees", 25)
    store.observe("bees", 26)
    assert [b.value for b in seen] == [25, 26]


# ---- observation as a schedulable action ---------------------------------

def test_observation_value_counts_only_missing_confidence():
    store = BeliefStore()
    now = 1000.0
    store.observe("bees", 25, at=now)                 # fully known
    obs = Observation("open hive", ("bees", "bee_types_discovered"), cost_s=20)
    # bees contributes ~0, the unobserved type count contributes ~1
    assert obs.value(store, now=now) == pytest.approx(1.0, abs=1e-3)


def test_an_expensive_observation_of_known_facts_is_not_worth_it():
    store = BeliefStore()
    now = 1000.0
    store.observe("bees", 25, at=now)
    obs = Observation("open hive", ("bees",), cost_s=60)
    assert obs.worth_it(store, now=now) is False


def test_an_observation_of_unknown_facts_is_worth_it():
    store = BeliefStore()
    obs = Observation("open hive", ("bees",), cost_s=20)
    assert obs.worth_it(store, seconds_per_point=30.0) is True


def test_weights_let_a_decision_say_which_facts_it_cares_about():
    store = BeliefStore()
    cheap = Observation("read hud", ("pollen",), cost_s=1)
    assert cheap.value(store, weights={"pollen": 0.1}) == pytest.approx(0.1)
    assert cheap.value(store, weights={"pollen": 5.0}) == pytest.approx(5.0)


def test_choose_observation_prefers_the_best_value_per_second():
    store = BeliefStore()
    cheap = Observation("read hud", ("pollen",), cost_s=1)
    dear = Observation("walk to hive", ("bees",), cost_s=45)
    assert choose_observation([dear, cheap], store) is cheap


def test_choose_observation_returns_none_when_nothing_is_worth_looking_at():
    store = BeliefStore()
    now = 1000.0
    store.observe("bees", 25, at=now)
    dear = Observation("walk to hive", ("bees",), cost_s=90)
    assert choose_observation([dear], store, now=now) is None


def test_belief_age_never_goes_negative():
    """Clock skew must not produce a confidence above 1."""
    belief = Belief("x", 1, observed_at=2000.0)
    assert belief.age(now=1000.0) == 0.0
    assert belief.confidence(now=1000.0) <= 1.0
