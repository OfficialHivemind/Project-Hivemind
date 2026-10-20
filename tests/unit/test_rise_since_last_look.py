"""A bag that fell in the field and is refilling is gathering, not stalled
(brain/farm RISE_SINCE_LAST_LOOK, W6 2026-10-12). MEASURED: of 20 gathers
flagged "has not risen" with the feed naming a field, the 150 frames saved at
the first rung read the pollen rising in 15 of the 17 legible; the bag had
fallen under its best, turned to honey where it stood. Off every field the
counter reads exactly flat, and that must still climb the ladder."""
from __future__ import annotations

import pytest

from hivemind.brain import farm
from tests.unit.test_farm import FakeClock, FakeHud, build, pollen

# up to a best, a quarter of it converted in the field (above DEATH_DROP, so
# nothing is booked), then a refill that stays under the old best for longer
# than the stall window, then past it
REFILL = ([pollen(100_000), pollen(200_000)]
          + [pollen(150_000 + 5_000 * i) for i in range(10)]
          + [pollen(210_000 + 10_000 * i) for i in range(40)])


@pytest.fixture
def clock():
    return FakeClock()


def _gather(clock, script, switch, monkeypatch):
    monkeypatch.setattr(farm, "RISE_SINCE_LAST_LOOK", switch)
    loop, _, _, events = build(clock, FakeHud(clock, script), stall_after=20.0,
                               farm_seconds=150.0)
    cycle = loop.run(cycles=1).cycles[0]
    said = [e.message for e in events if "rose since the last look" in getattr(e, "message", "")]
    return cycle, said


def test_a_refilling_bag_is_no_stall(clock, monkeypatch):
    cycle, said = _gather(clock, REFILL, "on", monkeypatch)
    assert cycle.recoveries == [], cycle.recoveries
    assert len(said) == 1 and "under this trip's best of 200,000" in said[0], said


def test_off_is_the_old_rule(clock, monkeypatch):
    cycle, said = _gather(clock, REFILL, "off", monkeypatch)
    assert cycle.recoveries[:1] == ["jump"], cycle.recoveries
    assert not said


def test_a_counter_that_fell_and_stays_flat_still_climbs_the_ladder(clock, monkeypatch):
    cycle, _ = _gather(clock, [pollen(300_000), pollen(240_000)], "on", monkeypatch)
    assert cycle.recoveries == ["jump", "turn", "go_home"], cycle.recoveries


def test_the_switch(monkeypatch):
    monkeypatch.setattr(farm, "RISE_SINCE_LAST_LOOK", "ab")
    assert farm.rise_since_last_look(3) and not farm.rise_since_last_look(4)
    monkeypatch.setattr(farm, "RISE_SINCE_LAST_LOOK", "off")
    assert not farm.rise_since_last_look(3)
    monkeypatch.setattr(farm, "RISE_SINCE_LAST_LOOK", "on")
    assert farm.rise_since_last_look(4)
