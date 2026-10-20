"""Natro's per-field gather patterns, transpiled.

`farm_snake` walked 232 studs inside a box about 16 by 38 studs, in a field
200 studs across, on every trip to every field. These pin down the transpile
of Natro's own patterns and the per-field widths its community settled on.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _transpiler():
    spec = importlib.util.spec_from_file_location(
        "transpile_natro_patterns", ROOT / "scripts/transpile_natro_patterns.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = _transpiler()

CORNER_X_SNAKE_HEAD = '''﻿send "{" TCLRKey " down}"
Walk(4 * size)
send "{" TCLRKey " up}{" TCFBKey " down}"
Walk(2 * size)
send "{" TCFBKey " up}{" AFCLRKey " down}"
Walk(8 * size)
send "{" AFCLRKey " up}{" TCFBKey " down}{" AFCLRKey " down}"
Walk( Sqrt( ( ( 8 * size ) ** 2 ) + ( ( 8 * size ) ** 2 ) ) )
send "{" TCFBKey " up}{" AFCLRKey " up}"
'''

LOOPED = '''loop reps {
	send "{" TCLRKey " down}"
	Walk(11 * size)
	send "{" TCLRKey " up}"
}
'''


# ---- the pieces ------------------------------------------------------------------

def test_the_toward_centre_keys_follow_natros_invert_flags():
    assert T.keymap(0, 0) == {"TCFBKey": "w", "AFCFBKey": "s", "TCLRKey": "a", "AFCLRKey": "d",
                              "FwdKey": "w", "BackKey": "s", "LeftKey": "a", "RightKey": "d"}
    flipped = T.keymap(1, 1)
    assert (flipped["TCFBKey"], flipped["AFCFBKey"]) == ("s", "w")
    assert (flipped["TCLRKey"], flipped["AFCLRKey"]) == ("d", "a")


@pytest.mark.parametrize("expression, size, reps, want", [
    ("4 * size", 1.0, 3, 4.0),
    ("8 * size", 0.5, 3, 4.0),
    ("6 + reps", 1.0, 6, 12.0),
    ("Sqrt( ( ( 8 * size ) ** 2 ) + ( ( 8 * size ) ** 2 ) )", 1.0, 1, pytest.approx(11.3137)),
    ("6.7 * size + 10", 1.0, 1, pytest.approx(16.7)),
])
def test_a_walk_distance_is_evaluated_not_guessed(expression, size, reps, want):
    assert T.tiles(expression, size, reps) == want


def test_an_unknown_name_in_a_walk_is_refused():
    with pytest.raises(ValueError):
        T.tiles("8 * mystery", 1.0, 1)


def test_each_walk_becomes_one_step_with_the_keys_held_at_the_time():
    steps = T.steps_of(CORNER_X_SNAKE_HEAD, size=1.0, reps=3, keys=T.keymap(0, 1))
    assert steps == [
        {"op": "walk", "keys": "d", "studs": 16.0},          # TCLR, inverted -> d
        {"op": "walk", "keys": "w", "studs": 8.0},
        {"op": "walk", "keys": "a", "studs": 32.0},          # AFCLR, inverted -> a
        {"op": "walk", "keys": "wa", "studs": 45.25},        # both down: a diagonal
    ]


def test_a_loop_over_reps_repeats_its_body():
    steps = T.steps_of(LOOPED, size=1.0, reps=3, keys=T.keymap(0, 0))
    assert steps == [{"op": "walk", "keys": "a", "studs": 44.0}] * 3


def test_a_sleep_is_a_pause_and_stationary_is_only_that():
    steps = T.steps_of("Sleep 10000", size=0.5, reps=1, keys=T.keymap(0, 0))
    assert steps == [{"op": "pause", "seconds": 10.0}]


def test_a_key_left_down_at_the_end_is_released():
    steps = T.steps_of('send "{" TCLRKey " down}"\nWalk(1)\n', 1.0, 1, T.keymap(0, 0))
    assert steps[-1] == {"op": "release_all"}


# ---- the shipped file ------------------------------------------------------------

def test_every_field_natro_configures_has_a_pattern_in_the_graph():
    from hivemind.nav.router import Router
    rt = Router()
    for field in ("dandelion", "sunflower", "pumpkin", "rose_field", "pepper",
                  "mushroom", "bamboo", "coconut", "pineapple", "spider",
                  "strawberry", "blue_flower", "pine_tree", "mountain_top"):
        name = f"natro_pattern_{field}"
        assert name in rt.routines, name
        routine = rt.routines[name]
        assert routine.studs > 400, f"{name} covers only {routine.studs} studs"
        assert not routine.verified


def test_the_patterns_press_nothing_but_movement():
    from hivemind.nav.router import Router
    rt = Router()
    allowed = {"walk", "pause", "release_all"}
    for name, routine in rt.routines.items():
        if not name.startswith("natro_pattern_"):
            continue
        ops = {s.get("op") for s in routine.steps}
        assert ops <= allowed, (name, ops - allowed)
        for step in routine.steps:
            if step["op"] == "walk":
                assert set(step["keys"]) <= set("wasd"), (name, step)


def test_stationary_is_kept_only_where_it_was_measured_to_pay():
    """MEASURED 2026-09-23: standing still paid 469 pollen/s at Stump, where
    the cannon happened to land in flowers, and 0 pollen in 227 s at Cactus,
    where it did not. Natro's Stationary assumes you start beside the
    sprinkler; this bot arrives by cannon and lands where the flight ends."""
    from hivemind.nav.router import Router
    rt = Router()
    stump = rt.routines["natro_pattern_stump"]
    assert stump.studs == 0.0
    assert all(s["op"] == "pause" for s in stump.steps), stump.steps
    for field in ("cactus", "clover"):
        routine = rt.routines[f"natro_pattern_{field}"]
        assert routine.studs > 400, f"{field} must walk until standing still pays there"


def test_dandelions_pattern_is_wider_than_ours_by_the_width_natro_chose():
    from hivemind.nav.router import Router
    rt = Router()
    ours = rt.routines["farm_snake"].studs
    theirs = rt.routines["natro_pattern_dandelion"].studs
    assert theirs > 2.5 * ours, (ours, theirs)
    # width 6 for Dandelion against 1 for Rose: the difference shows up in studs
    assert (rt.routines["natro_pattern_dandelion"].studs
            > rt.routines["natro_pattern_rose_field"].studs)
