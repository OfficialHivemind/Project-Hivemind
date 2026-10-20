"""A full bag converted where it stands (brain/farm `convert_in_field`)."""
from __future__ import annotations

from tests.unit.test_farm import FakeHud, build, clock, honey, pollen  # noqa: F401 (clock is a fixture)


def test_a_bag_converted_in_the_field_gathers_on_and_keeps_its_pollen(clock):
    hud = FakeHud(clock, [pollen(0), pollen(100_000), pollen(600_000),
                          pollen(0), pollen(300_000), pollen(600_000), pollen(0)],
                  honey_script=[honey(10_000_000)])
    asked = []

    def convert(reading):
        asked.append(reading.value)
        return len(asked) == 1            # the first full bag only

    loop, _, routes, events = build(clock, hud, convert_in_field=convert)
    report = loop.run(cycles=1)
    cycle = report.cycles[0]

    assert asked == [600_000, 600_000]
    assert cycle.field_converts == 1
    # 500,000 before the convert (from the 100,000 it started at) and
    # 600,000 after it, from the empty bag
    assert cycle.pollen_gathered == 1_100_000
    assert routes.ran.count("collect_around") == 3, routes.ran
    assert "converted in the field" in cycle.describe()
    # the second full bag went home as before
    assert "600,000/660,000" in cycle.gather_ended


def test_without_the_hook_a_full_bag_goes_home_as_before(clock):
    hud = FakeHud(clock, [pollen(0), pollen(100_000), pollen(600_000), pollen(0)],
                  honey_script=[honey(1), honey(2)])
    loop, _, routes, _ = build(clock, hud)
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.field_converts == 0
    assert cycle.pollen_gathered == 500_000
    assert routes.ran.count("collect_around") == 1


def test_a_hook_that_raises_sends_the_bag_home(clock):
    hud = FakeHud(clock, [pollen(0), pollen(100_000), pollen(600_000), pollen(0)],
                  honey_script=[honey(1), honey(2)])

    def broken(reading):
        raise RuntimeError("no hotbar")

    loop, _, routes, events = build(clock, hud, convert_in_field=broken)
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.field_converts == 0 and cycle.pollen_gathered == 500_000
    assert any("could not convert in the field" in getattr(e, "message", "")
               for e in events)
