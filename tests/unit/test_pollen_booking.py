"""A gather books every look's rise, so a bag that fell in the field and
refilled under its best books the refill (brain/farm POLLEN_BOOKING, W7
2026-10-12), and a full bag is seen between a pass's steps (FULL_MID_PASS).
MEASURED on the in-gather incident clips of runs 783-915: 61 falls of
10,000+ pollen, each with the honey up as much in the same second (Honey
Mark links, Coin Scatter) -- 30% of what Mushroom's bag took in, 20% of
Rose's -- and none of it booked by the high-water mark; run-877 sat at 99.75%
inside one 121 s pass while the end-of-pass check waited."""
from __future__ import annotations

import pytest

from hivemind.brain import farm
from hivemind.brain.ledger import Ledger
from tests.unit.test_farm import FakeClock, FakeHud, FakeInput, FakeRoutes, build, pollen

# the HUD's wait, the gather's start, up to a best, a fall in the field the
# second look agrees with, a refill under the old best and past it, then a
# flat bag to the cap
FELL = [pollen(0), pollen(0), pollen(100_000), pollen(200_000), pollen(150_000),
        pollen(150_000), pollen(190_000), pollen(230_000)]


@pytest.fixture
def clock():
    return FakeClock()


def _trip(clock, script, monkeypatch, booking="on", full="on", **kw):
    monkeypatch.setattr(farm, "POLLEN_BOOKING", booking)
    monkeypatch.setattr(farm, "FULL_MID_PASS", full)
    kw.setdefault("stall_after", 1e9)
    kw.setdefault("farm_seconds", 60.0)
    loop, inp, routes, events = build(clock, FakeHud(clock, script), **kw)
    return loop.run(cycles=1).cycles[0], inp, routes, events


def test_a_fall_in_the_field_books_its_refill(clock, monkeypatch, tmp_path):
    cycle, _, _, _ = _trip(clock, FELL, monkeypatch)
    # 0 -> 200,000, fell to 150,000, back up to 230,000: 280,000 went in
    assert cycle.pollen_gathered == 280_000
    assert cycle.pollen_refilled == 50_000
    assert "refilled the bag after it fell in the field" in cycle.describe()
    row = Ledger(tmp_path / "trips.jsonl").record(cycle)
    assert (row["pollen"], row["refilled"]) == (280_000, 50_000)


def test_off_is_the_high_water_mark(clock, monkeypatch):
    cycle, _, _, _ = _trip(clock, FELL, monkeypatch, booking="off", full="off")
    assert (cycle.pollen_gathered, cycle.pollen_refilled) == (230_000, 0)


def test_a_lone_low_misread_books_nothing(clock, monkeypatch):
    # the second look reads the bag back up: the low look was a misread
    script = [pollen(0), pollen(0), pollen(100_000), pollen(200_000), pollen(150_000),
              pollen(210_000), pollen(230_000)]
    cycle, _, _, _ = _trip(clock, script, monkeypatch)
    assert (cycle.pollen_gathered, cycle.pollen_refilled) == (230_000, 0)


def test_a_death_keeps_only_what_the_links_banked(clock, monkeypatch):
    cycle, _, _, _ = _trip(clock, FELL[:7] + [pollen(0)], monkeypatch)
    assert cycle.deaths == 1
    assert (cycle.pollen_gathered, cycle.pollen_refilled) == (0, 0)


def test_the_looks_between_steps_book_a_fall_inside_one_pass(clock, monkeypatch):
    # the pass's own ends read 0 and 200,000; between its steps the bag rose
    # to 180,000, fell to 120,000 (said twice) and refilled
    script = [pollen(0), pollen(0), pollen(180_000), pollen(120_000), pollen(120_000),
              pollen(160_000), pollen(200_000)]
    inp = FakeInput()
    cycle, _, _, _ = _trip(clock, script, monkeypatch, inp=inp, farm_seconds=20.0,
                           routes=FakeRoutes(inp, clock, steps=4, seconds=12.0))
    assert (cycle.pollen_gathered, cycle.pollen_refilled) == (260_000, 60_000)


def _full(clock, monkeypatch, script, switch):
    inp = FakeInput()
    routes = FakeRoutes(inp, clock, steps=3, seconds=9.0)
    cycle, inp, routes, events = _trip(clock, script, monkeypatch, booking=switch,
                                       full=switch, inp=inp, routes=routes)
    said = [e.message for e in events if "FULL_MID_PASS" in getattr(e, "message", "")]
    return cycle, inp, routes.steps_run, said


def test_a_full_bag_between_steps_ends_the_pass(monkeypatch):
    # full_at is 90% of 660,000: the third step's look sees 600,000, and the
    # pass ends there instead of walking its last step ("off" walks it)
    cycle, inp, steps, said = _full(FakeClock(), monkeypatch, [pollen(0), pollen(0),
                                    pollen(300_000), pollen(600_000)], "on")
    old, _, old_steps, old_said = _full(FakeClock(), monkeypatch, [pollen(0), pollen(0),
                                        pollen(600_000)], "off")
    for c in (cycle, old):
        assert c.pattern_passes == 1
        assert c.gather_ended.startswith("backpack 600,000/660,000"), c.gather_ended
    assert steps == old_steps - 1
    assert len(said) == 1 and "between two steps of" in said[0] and not old_said
    assert not inp.held_keys
