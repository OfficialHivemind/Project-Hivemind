"""A Conversion Link whose honey shows up seconds after its pollen fell is
not a death (brain/farm DEATH_CONFIRM_S). MEASURED 2026-10-06 00:34: a fall
of 275,860 in Clover ended the trip as a death and honey stood 233,742
higher at the convert after; the counter rolls unreadably for seconds after
a conversion."""
from __future__ import annotations

from tests.unit.test_farm import FakeHud, build, clock, honey, pollen  # noqa: F401 (clock is a fixture)


def test_a_link_whose_honey_lags_is_not_a_death(clock):
    hud = FakeHud(clock, [pollen(0), pollen(100_000), pollen(300_000), pollen(20_000),
                          pollen(60_000), pollen(600_000), pollen(0)],
                  honey_script=[honey(1_000_000), honey(1_000_100), honey(1_000_200),
                                honey(1_000_300), honey(1_300_000)])
    loop, _, _, events = build(clock, hud)
    cycle = loop.run(cycles=1).cycles[0]
    said = " ".join(getattr(e, "message", "") for e in events)
    assert cycle.deaths == 0, said
    assert "not a death" in said
    assert "died" not in (cycle.gather_ended or "")


def test_a_fall_the_honey_never_explains_is_still_a_death(clock):
    hud = FakeHud(clock, [pollen(0), pollen(100_000), pollen(300_000), pollen(0)],
                  honey_script=[honey(1_000_000), honey(1_000_100), honey(1_000_200)])
    loop, _, _, _ = build(clock, hud)
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.deaths == 1
    assert "died" in cycle.gather_ended


def test_a_fall_that_leaves_the_bag_well_filled_is_not_a_death(clock):
    # MEASURED 2026-10-06 01:34: Links in Mushroom left 673,182 of 2,823,706,
    # the honey unreadable behind the floating numbers
    # (scaled to the test's 660,000 bag: 500,000 falling to 120,000)
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(500_000), pollen(120_000),
                          pollen(300_000), pollen(600_000)],
                  honey_script=[honey(1_000_000)])
    loop, _, _, events = build(clock, hud)
    cycle = loop.run(cycles=1).cycles[0]
    said = " ".join(getattr(e, "message", "") for e in events)
    assert cycle.deaths == 0, said
    assert "a death leaves the bag empty" in said


def test_a_death_read_before_the_counter_settles_is_still_a_death(clock):
    # MEASURED 2026-10-05 15:20 (run-654): a real death -- the compass at the
    # hive a second later -- read 13,421 of 2,089,866 at its first read
    # (scaled: 500,000 falling to 13,000), over the first 5,000 limit
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(500_000), pollen(13_000),
                          pollen(3_000)],
                  honey_script=[honey(1_000_000)])
    loop, _, _, events = build(clock, hud)
    cycle = loop.run(cycles=1).cycles[0]
    said = " ".join(getattr(e, "message", "") for e in events)
    assert cycle.deaths == 1, said
    assert "a death leaves the bag empty" not in said


class _Compass:
    """A stand-in world.bearings: where the game says we are, nothing else.
    `hive()`: whether the respawn's view is seen yet."""

    def __init__(self, field=None, hive=lambda: None):
        self.field, self.hive = field, hive

    def at(self, place):
        return self.hive() if place == "hive" else None

    def in_field(self):
        return self.field

    def __getattr__(self, name):          # every other compass call is a no-op
        return lambda *a, **k: None


def test_a_link_that_takes_nearly_all_the_bag_is_not_a_death_while_still_in_the_field(clock):
    # MEASURED 2026-10-06 02:42: 515,218 -> 34,774 in Cactus (6.7% left, under
    # the leftover line), honey +376K over the trip, the walk home starting
    # from the field (scaled: 500,000 -> 33,000)
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(500_000), pollen(33_000),
                          pollen(200_000), pollen(600_000)],
                  honey_script=[honey(1_000_000)])
    loop, _, _, events = build(clock, hud, bearings=_Compass(field="cactus"))
    cycle = loop.run(cycles=1).cycles[0]
    said = " ".join(getattr(e, "message", "") for e in events)
    assert cycle.deaths == 0, said
    assert "still names the cactus field" in said


def test_a_fall_with_the_compass_at_the_hive_is_never_a_link(clock):
    # as at 15:20 (run-654): the respawn's view ends the trip, the way it did
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(500_000), pollen(33_000),
                          pollen(3_000)],
                  honey_script=[honey(1_000_000)])
    # the respawn's view comes after the fall is read (the fourth read)
    loop, _, _, events = build(clock, hud, bearings=_Compass(
        field="cactus", hive=lambda: True if hud.pollen_reads >= 4 else None))
    cycle = loop.run(cycles=1).cycles[0]
    said = " ".join(getattr(e, "message", "") for e in events)
    assert "Conversion Link" not in said, said
    assert cycle.pattern_passes <= 3 and cycle.gather_ended, said
