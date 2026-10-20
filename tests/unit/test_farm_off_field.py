"""A gather the game has said is no field ends soon, not on the ladder
(brain/farm OFF_FIELD_STALL_S). MEASURED 2026-10-06 01:55 (run-664): the
Cactus flight landed off the field, the sprinkler was refused "You must be
standing in a field" at once, and the ladder walked 20 passes over 207 s."""
from __future__ import annotations

from hivemind.brain.farm import FLAT_COUNTER, OFF_FIELD_STALL_S, STALL_SECONDS, Rung
from tests.unit.test_farm import FakeHud, build, clock, pollen  # noqa: F401 (clock is a fixture)


def _refused(cycle):
    cycle.off_field = "the game refused the sprinkler"


def test_no_field_and_no_rise_goes_home_soon(clock):
    hud = FakeHud(clock, [pollen(0)])
    loop, _, _, _ = build(clock, hud, before_gather=_refused)
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.gather_ended.startswith(FLAT_COUNTER), cycle.gather_ended
    assert "refused the sprinkler" in cycle.gather_ended
    assert cycle.recoveries[-1] == Rung.GO_HOME.value
    assert OFF_FIELD_STALL_S <= cycle.gather_seconds < STALL_SECONDS


def test_a_rise_after_the_refusal_gathers_on(clock):
    # a landing at the field's edge that the pattern walks onto the flowers
    hud = FakeHud(clock, [pollen(0), pollen(0), pollen(20_000), pollen(60_000),
                          pollen(120_000), pollen(600_000)])
    loop, _, _, _ = build(clock, hud, before_gather=_refused)
    cycle = loop.run(cycles=1).cycles[0]
    assert "refused the sprinkler" not in (cycle.gather_ended or "")
    assert Rung.GO_HOME.value not in cycle.recoveries


def test_a_first_reading_after_an_unreadable_start_is_no_rise(clock):
    # the trip's start could not be read: the first reading is where it
    # begins, not evidence of gathering, and the game's "no field" stands
    from tests.unit.test_farm import UNREADABLE
    hud = FakeHud(clock, [UNREADABLE] * 3 + [pollen(0)])
    loop, _, _, _ = build(clock, hud, before_gather=_refused)
    cycle = loop.run(cycles=1).cycles[0]
    assert "refused the sprinkler" in (cycle.gather_ended or ""), cycle.gather_ended
    assert OFF_FIELD_STALL_S <= cycle.gather_seconds < STALL_SECONDS
