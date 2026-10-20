"""Gather patterns must cover a field from whichever side we walked in."""
from __future__ import annotations

import pathlib

import pytest

from hivemind.act.patterns import (KEYS, DEFAULT_SIZE, Facing, Pattern, Step,
                                   describe, load, steps_for)

FILE = pathlib.Path(__file__).resolve().parents[2] / "data/behaviour/patterns.yaml"


@pytest.fixture(scope="module")
def shipped():
    return load(FILE)


def test_the_shipped_file_loads(shipped):
    assert {"snake", "lines", "stationary", "squares"} <= set(shipped)


def test_every_shipped_pattern_explains_itself(shipped):
    """A pattern nobody can choose between is a pattern nobody will use."""
    for pattern in shipped.values():
        assert pattern.description, f"{pattern.name} has no description"
        assert pattern.best_for, f"{pattern.name} does not say when to use it"


def test_a_missing_file_is_not_fatal(tmp_path):
    assert load(tmp_path / "nope.yaml") == {}


def test_a_broken_file_is_not_fatal(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("this: [is not: valid: yaml")
    assert load(bad) == {}


@pytest.mark.parametrize("entry,toward", list(enumerate(KEYS)))
def test_toward_the_centre_follows_the_entry_side(entry, toward):
    assert Facing(entry=entry).key("toward") == toward


def test_the_four_directions_are_always_four_different_keys():
    for entry in range(4):
        facing = Facing(entry=entry)
        keys = {facing.key(d) for d in ("toward", "away", "left", "right")}
        assert len(keys) == 4, f"entry {entry} maps two directions to one key"


def test_away_is_the_opposite_of_toward():
    for entry in range(4):
        facing = Facing(entry=entry)
        pair = {facing.key("toward"), facing.key("away")}
        assert pair in ({"w", "s"}, {"a", "d"})


def test_an_unknown_direction_is_refused():
    with pytest.raises(ValueError):
        Facing().key("widdershins")


def test_the_same_pattern_rotates_with_the_entry_side(shipped):
    a = [s["keys"] for s in steps_for(shipped["snake"], Facing(0))]
    b = [s["keys"] for s in steps_for(shipped["snake"], Facing(1))]
    assert a == ["w", "d", "s", "d"]
    assert b == ["d", "s", "a", "s"]


def test_standing_still_presses_nothing(shipped):
    assert steps_for(shipped["stationary"], Facing(), reps=5) == []


def test_reps_repeat_the_whole_pattern(shipped):
    one = steps_for(shipped["snake"], Facing(), reps=1)
    three = steps_for(shipped["snake"], Facing(), reps=3)
    assert three == one * 3


def test_size_scales_the_lanes_but_not_the_spacing(shipped):
    """MEANT TO BE ASYMMETRIC. `size` says how much field to cover; lane
    spacing says how thoroughly. Scaling both would change nothing real."""
    small = steps_for(shipped["snake"], Facing(), size=0.5)
    full = steps_for(shipped["snake"], Facing(), size=1.0)
    assert small[0]["studs"] == pytest.approx(full[0]["studs"] / 2)
    assert small[1]["studs"] == pytest.approx(full[1]["studs"])


def test_size_is_never_zero_or_negative(shipped):
    for size in (0.0, -3.0):
        steps = steps_for(shipped["snake"], Facing(), size=size)
        assert steps and all(s["studs"] > 0 for s in steps)


def test_every_step_is_something_the_route_runner_can_run(shipped):
    """These are fed straight to act/routes, so they must be valid ops."""
    for pattern in shipped.values():
        for step in steps_for(pattern, Facing(), reps=2):
            assert step["op"] == "walk"
            assert step["keys"] in KEYS
            assert isinstance(step["studs"], float) and step["studs"] > 0


def test_zero_reps_walks_nowhere(shipped):
    assert steps_for(shipped["snake"], Facing(), reps=0) == []


def test_a_span_of_zero_emits_no_step():
    pattern = Pattern(name="x", steps=(Step("toward", 0.0), Step("right", 0.5)))
    assert len(steps_for(pattern, Facing())) == 1


def test_describe_says_which_way_it_starts(shipped):
    text = describe(shipped["snake"], Facing(1), size=DEFAULT_SIZE)
    assert "starting d" in text
    assert "stand still" in describe(shipped["stationary"], Facing())
