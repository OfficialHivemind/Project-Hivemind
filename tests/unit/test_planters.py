"""Planter harvest timing.

The most important test here is the one asserting the CONSERVATIVE default: with
field degradation unverified, the model must never recommend harvesting early.
Harvesting early for a benefit that may not exist loses real yield chasing an
imagined one; waiting costs at most a few percent if degradation is real.
"""
import pytest

from hivemind.tasks.planters import (DEGRADATION_VERIFIED, PlanterState,
                                     decide, rank_by_urgency)

HOUR = 3600.0


def planter(**kw):
    base = dict(id="p1", seed="Paper Planter", field_name="Sunflower",
                planted_at=0.0, grow_seconds=4 * HOUR, base_yield=100_000.0)
    base.update(kw)
    return PlanterState(**base)


def test_the_unverified_default_is_off():
    """If this ever flips without a measurement recorded, the guard is gone."""
    assert DEGRADATION_VERIFIED is False


def test_growth_is_linear_and_caps_at_full():
    p = planter()
    assert p.growth(now=0.0) == 0.0
    assert p.growth(now=2 * HOUR) == pytest.approx(0.5)
    assert p.growth(now=4 * HOUR) == 1.0
    assert p.growth(now=99 * HOUR) == 1.0


def test_fully_grown_is_always_harvested():
    d = decide(planter(), now=4 * HOUR)
    assert d.harvest is True
    assert d.reason == "fully grown"


@pytest.mark.parametrize("health", [1.0, 0.8, 0.6, 0.4, 0.2])
def test_never_harvests_early_while_degradation_is_unverified(health):
    """The conservative branch, at every field health."""
    d = decide(planter(field_health=health), now=3.9 * HOUR,
               degradation_verified=False)
    assert d.harvest is False
    assert "unverified" in d.reason


def test_with_degradation_confirmed_a_spent_field_is_harvested_early():
    d = decide(planter(field_health=0.3), now=2 * HOUR,
               degradation_verified=True)
    assert d.harvest is True
    assert "floor" in d.reason


def test_with_degradation_confirmed_a_healthy_field_still_waits():
    d = decide(planter(field_health=1.0), now=2 * HOUR,
               degradation_verified=True)
    assert d.harvest is False
    assert d.reason == "growing, field healthy"


def test_nearly_grown_on_a_middling_field_harvests_once_confirmed():
    d = decide(planter(field_health=0.6), now=3.7 * HOUR,
               degradation_verified=True)
    assert d.harvest is True
    assert d.growth >= 0.9


def test_yield_scales_with_growth_and_field_health():
    p = planter(field_health=0.5)
    assert p.expected_yield(now=2 * HOUR) == pytest.approx(100_000 * 0.5 * 0.5)


def test_decision_reports_what_waiting_would_gain():
    d = decide(planter(), now=2 * HOUR, degradation_verified=False)
    assert d.yield_now == pytest.approx(50_000)
    assert d.yield_if_waited == pytest.approx(100_000)
    assert d.gain_from_waiting == pytest.approx(50_000)
    assert d.wait_seconds == pytest.approx(2 * HOUR)


def test_zero_grow_time_is_immediately_ready():
    assert planter(grow_seconds=0.0).growth(now=0.0) == 1.0


def test_rank_puts_ready_planters_first_then_soonest():
    ready = planter(id="ready", grow_seconds=1 * HOUR)
    soon = planter(id="soon", grow_seconds=3 * HOUR)
    later = planter(id="later", grow_seconds=9 * HOUR)
    order = [p.id for p in rank_by_urgency([later, soon, ready], now=2 * HOUR)]
    assert order == ["ready", "soon", "later"]
