"""The autonomy gate and the irreversibility firewall.

The rule worth testing hardest: the firewall applies in EVERY mode, including
autopilot. No autonomy setting should be able to permit spending 3,333 royal
jelly on a forty-minute-old inventory reading, and in autopilot the answer is
not "ask the owner" (that would break the promise never to interrupt) but "go
and look first".
"""
import pytest

from hivemind.brain.autonomy import Arbiter, Outcome, Proposal
from hivemind.telemetry.events import Autonomy, Option
from hivemind.world.beliefs import BeliefStore, half_life_for
from hivemind.world.settings import Settings


def proposal(**kw):
    base = dict(question="Do the thing?", chosen="yes",
                options=[Option("yes", 2.0), Option("no", 1.0)])
    base.update(kw)
    return Proposal(**base)


def fresh_store(**facts):
    store = BeliefStore()
    for name, value in facts.items():
        store.observe(name, value, at=1000.0)
    return store


# ---- the modes -----------------------------------------------------------

def test_autopilot_acts_on_a_routine_choice():
    a = Arbiter(fresh_store(), mode=Autonomy.AUTOPILOT)
    assert a.judge(proposal(), now=1000.0).outcome is Outcome.ACT


def test_autopilot_acts_even_on_a_strategy_choice():
    a = Arbiter(fresh_store(), mode=Autonomy.AUTOPILOT)
    r = a.judge(proposal(strategic=True), now=1000.0)
    assert r.outcome is Outcome.ACT


def test_ask_strategy_asks_about_strategy_but_not_chores():
    a = Arbiter(fresh_store(), mode=Autonomy.ASK_STRATEGY)
    assert a.judge(proposal(strategic=True), now=1000.0).outcome is Outcome.ASK
    assert a.judge(proposal(), now=1000.0).outcome is Outcome.ACT


def test_ask_strategy_ignores_reversible_irreversibility():
    """An irreversible chore is still a chore in this mode."""
    a = Arbiter(fresh_store(), mode=Autonomy.ASK_STRATEGY)
    assert a.judge(proposal(reversible=False), now=1000.0).outcome is Outcome.ACT


def test_ask_notable_asks_about_anything_irreversible():
    a = Arbiter(fresh_store(), mode=Autonomy.ASK_NOTABLE)
    assert a.judge(proposal(reversible=False), now=1000.0).outcome is Outcome.ASK


def test_a_big_spend_is_asked_about_in_both_ask_modes():
    for mode in (Autonomy.ASK_STRATEGY, Autonomy.ASK_NOTABLE):
        a = Arbiter(fresh_store(), mode=mode, max_spend=1_000_000)
        r = a.judge(proposal(cost_honey=5_000_000), now=1000.0)
        assert r.outcome is Outcome.ASK, mode
        assert "limit" in r.reason


# ---- the firewall --------------------------------------------------------

def test_the_firewall_blocks_an_irreversible_act_on_a_stale_belief():
    store = BeliefStore()
    store.observe("royal_jelly", 3410, at=0.0)
    stale = half_life_for("royal_jelly") * 6          # confidence ~1.5%
    a = Arbiter(store, mode=Autonomy.ASK_NOTABLE)
    r = a.judge(proposal(reversible=False, depends_on=("royal_jelly",)),
                now=stale)
    assert r.outcome is Outcome.OBSERVE
    assert "royal_jelly" in r.observe


def test_the_firewall_applies_in_autopilot_too():
    """No autonomy setting may permit acting blind."""
    store = BeliefStore()
    store.observe("royal_jelly", 3410, at=0.0)
    stale = half_life_for("royal_jelly") * 6
    a = Arbiter(store, mode=Autonomy.AUTOPILOT)
    r = a.judge(proposal(reversible=False, depends_on=("royal_jelly",)),
                now=stale)
    assert r.outcome is Outcome.OBSERVE, "autopilot must not act on a stale belief"


def test_autopilot_observes_rather_than_asking():
    """Observing keeps the promise never to interrupt."""
    store = BeliefStore()
    store.observe("bees", 25, at=0.0)
    a = Arbiter(store, mode=Autonomy.AUTOPILOT)
    r = a.judge(proposal(reversible=False, depends_on=("bees",)),
                now=half_life_for("bees") * 8)
    assert r.outcome is Outcome.OBSERVE
    assert r.outcome is not Outcome.ASK


def test_a_fresh_belief_passes_the_firewall():
    store = fresh_store(royal_jelly=3410)
    a = Arbiter(store, mode=Autonomy.AUTOPILOT)
    r = a.judge(proposal(reversible=False, depends_on=("royal_jelly",)),
                now=1000.0)
    assert r.outcome is Outcome.ACT


def test_a_reversible_act_is_not_firewalled():
    store = BeliefStore()
    store.observe("pollen", 400, at=0.0)
    a = Arbiter(store, mode=Autonomy.AUTOPILOT)
    r = a.judge(proposal(reversible=True, depends_on=("pollen",)), now=1e6)
    assert r.outcome is Outcome.ACT


def test_an_unknown_belief_counts_as_stale():
    a = Arbiter(BeliefStore(), mode=Autonomy.AUTOPILOT)
    r = a.judge(proposal(reversible=False, depends_on=("never_observed",)),
                now=0.0)
    assert r.outcome is Outcome.OBSERVE


# ---- locks ---------------------------------------------------------------

def test_a_forbidden_action_is_refused_in_every_mode():
    for mode in Autonomy:
        a = Arbiter(fresh_store(), mode=mode, forbidden={"offer at the Wind Shrine"})
        r = a.judge(proposal(chosen="offer at the Wind Shrine"), now=1000.0)
        assert r.outcome is Outcome.REFUSE, mode


def test_settings_drive_the_arbiter(tmp_path):
    import yaml
    path = tmp_path / "s.yaml"
    path.write_text(yaml.safe_dump({
        "autonomy.mode": "ask_notable",
        "autonomy.max_spend": 1234,
        "autonomy.min_confidence": 0.75,
        "economy.wind_shrine": False,
    }))
    a = Arbiter(fresh_store()).apply_settings(Settings(path))
    assert a.mode is Autonomy.ASK_NOTABLE
    assert a.max_spend == 1234
    assert a.min_confidence == pytest.approx(0.75)
    assert "offer at the Wind Shrine" in a.forbidden


def test_a_nonsense_mode_falls_back_rather_than_crashing(tmp_path):
    import yaml
    path = tmp_path / "s.yaml"
    path.write_text(yaml.safe_dump({"autonomy.mode": "banana"}))
    a = Arbiter(fresh_store()).apply_settings(Settings(path))
    assert a.mode is Autonomy.ASK_STRATEGY


def test_early_harvest_is_locked_by_default():
    """It must stay off until field degradation is measured."""
    a = Arbiter(fresh_store()).apply_settings(Settings("/nonexistent"))
    assert "harvest early" in a.forbidden
