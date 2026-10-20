"""Gather patterns must cover a field from whichever side we walked in."""
from __future__ import annotations

import pathlib

import pytest

from hivemind.act.patterns import (KEYS, DEFAULT_SIZE, Facing, Pattern, Step,
                                   describe, load, steps_for)

import hivemind

ROOT = pathlib.Path(hivemind.__file__).resolve().parents[2]
FILE = ROOT / "data/behaviour/patterns.yaml"


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


# ---- Hivemind's own closed patterns ---------------------------------------
import yaml  # noqa: E402

from hivemind.act import patterns as P  # noqa: E402
from hivemind.act.routes import GATHER_PREFIXES, pass_drift  # noqa: E402
from hivemind.world import userpatterns as up  # noqa: E402

OWN = P.own_routines()
CASES = [(shape, field) for field in P.FIELD_FLOWERS for shape in P.OWN_SHAPES]


def _scaled(steps, k):
    return [dict(s, studs=s["studs"] * k) for s in steps]


def test_field_sizes_match_the_wiki_flower_counts():
    """Each wiki size's product is that field's flower count in world.yaml."""
    world = yaml.safe_load((ROOT / "data/knowledge/world.yaml").read_text())["fields"]
    for field, (a, b) in P.FIELD_FLOWERS.items():
        assert a * b == world[{"rose_field": "rose"}.get(field, field)]["flowers"], field


def test_every_own_pattern_passes_the_studio_check_with_enter_and_exit():
    # x2: each at full size and its SMALL_SIZE twin (AI-N5)
    assert len(OWN) == 2 * (len(CASES) + 2 * sum(1 for s, _ in CASES if s != "petals"))
    for shape, field in CASES:
        assert P.own_name(shape, field) in OWN
        assert up.validate(P.own_pattern(shape, field)).ok
        assert P.own_field(P.own_name(shape, field)) == field
        assert all(s["op"] == "walk" for s in OWN[P.own_name(shape, field)]["steps"])
    assert P.own_field("natro_pattern_pepper_as_natro") is None
    assert P.own_name("sweep", "pepper").startswith(GATHER_PREFIXES)
    assert P.own_pattern("sweep", "stump") is None          # not a rectangle: no size


@pytest.mark.parametrize("shape, field", CASES)
@pytest.mark.parametrize("speed", [0.85, 1.0, 1.15])
def test_a_pass_closes_at_any_steady_speed(shape, field, speed):
    """No drift: the pass ends where it began, and enter + exit cancel, even
    with every leg off by the same haste error."""
    name = P.own_name(shape, field)
    dx, dy = pass_drift(_scaled(OWN[name]["steps"], speed))
    assert abs(dx) < 0.05 and abs(dy) < 0.05, (dx, dy)
    ends = sum((OWN.get(f"{name}_{p}", {"steps": []})["steps"] for p in ("enter", "exit")), [])
    ex, ey = pass_drift(_scaled(ends, speed))
    assert abs(ex) < 0.05 and abs(ey) < 0.05


@pytest.mark.parametrize("shape, field", CASES)
def test_the_whole_gather_stays_on_the_field(shape, field):
    """The PROOF the module promises: enter, 30 passes and exit, walked 15%
    long (the measured worst haste error) from an arrival ARRIVAL_SLACK off
    the field's middle in any direction, keep the character BODY_STUDS
    inside the field's short side -- so either way round the field lies."""
    name = P.own_name(shape, field)
    walk = (OWN.get(f"{name}_enter", {"steps": []})["steps"] + OWN[name]["steps"] * 30
            + OWN.get(f"{name}_exit", {"steps": []})["steps"])
    left, right, near, far = P.footprint(_scaled(walk, P.SPEED_ERROR))
    half = min(P.FIELD_FLOWERS[field]) * P.FLOWER_STUDS / 2
    reach = max(-left, right, -near, far) + P.ARRIVAL_SLACK + P.BODY_STUDS
    assert reach <= half + 0.05, (reach, half)
    # and it covers the sprinkler's ground round the arrival, not a spot
    assert min(-left, right, -near, far) >= 0.4 * min(P.side(field), 2 * P.SPRINKLER_REACH)


def test_the_baseline_pattern_does_not_close():
    """Why: CornerXSnake (the field's own today) ends every pass 36.7 studs
    from its start (offfield.md), so the same proof cannot hold for it."""
    rows = yaml.safe_load((ROOT / "data/world/natro_patterns.yaml").read_text())["routines"]
    pepper = next(r for r in rows if r["name"] == "natro_pattern_pepper_as_natro")
    dx, dy = pass_drift(pepper["steps"])
    assert (dx * dx + dy * dy) ** 0.5 > 36


def test_own_patterns_ship_look_only():
    assert P.OWN_PATTERNS_LIVE is False and P.ENTER_EXIT_LIVE is False
    farm = (ROOT / "scripts/run_farm.py").read_text()
    assert 'settings.bool("gather.own_patterns")' in farm
    assert "own pattern would:" in farm and "would: walk" in farm
    # both flags or neither (no loop without its enter), and no exit from a cut pass
    assert "OWN_PATTERNS_LIVE and patterns_mod.ENTER_EXIT_LIVE" in farm
    assert 'part == "exit" and getattr(cycle_or_pattern, "pass_cut", False)' in farm


# ---- AI-N5: the twins the per-field pick tries after the shape -------------
@pytest.mark.parametrize("shape, field", CASES)
def test_a_size_twin_is_loaded_closes_and_stays_inside_its_full_size(shape, field):
    name, small = P.own_name(shape, field), P.own_name(shape, field, P.SMALL_SIZE)
    assert P.twin(name) == small and P.twin(small) is None
    assert small in OWN and P.own_field(small) == field
    dx, dy = pass_drift(OWN[small]["steps"])
    assert abs(dx) < 0.05 and abs(dy) < 0.05
    big, little = P.footprint(OWN[name]["steps"]), P.footprint(OWN[small]["steps"])
    assert all(abs(s) <= abs(b) + 0.05 for s, b in zip(little, big))
    for part in ("enter", "exit"):
        if f"{name}_{part}" in OWN:
            assert OWN[f"{small}_{part}"]["studs"] == pytest.approx(
                OWN[f"{name}_{part}"]["studs"] * P.SMALL_SIZE, abs=0.11)


def test_the_field_patterns_twin_is_the_sprinkler_where_the_route_lands():
    assert P.twin("natro_pattern_pepper_as_natro") == "natro_pattern_pepper"
    assert P.twin("natro_pattern_pine_tree_as_natro") is None     # SPOT_SETTLED, measured
    assert P.twin("natro_pattern_pepper") is None and P.twin("farm_snake") is None
    # never walked on Pepper / Bamboo / Blue Flower: new movement, look-only
    assert P.SPOT_TWIN_LIVE is False
    assert "sprinkler spot would:" in (ROOT / "scripts/run_farm.py").read_text()
