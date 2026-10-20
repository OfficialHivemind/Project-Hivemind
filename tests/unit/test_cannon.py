"""The red cannon, Natro Macro's way.

The owner, 2026-09-22: use the cannon for far places. Natro's field
paths carry a cannon branch -- the community's flight timings: which keys to
hold, how long before the shot, how long after -- and `nm_gotoCannon` hops
toward the cannon until its prompt shows. These tests pin down the transpile
of those branches, the runner's new ops, the graph's preference, and the walk
to the cannon.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

from hivemind.act import routes as R
from hivemind.act.routes import RouteRunner
from hivemind.nav.router import Edge, Router

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _transpiler():
    spec = importlib.util.spec_from_file_location(
        "transpile_natro", ROOT / "scripts/transpile_natro.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = _transpiler()

# paths/gtf-pinetree.ahk, NatroTeam/NatroMacro (GPLv3), as read 2026-09-22.
PINETREE = '''﻿if (MoveMethod = "Cannon") {
    nm_gotoramp()
    nm_gotocannon()
    send "{e down}"
    HyperSleep(100)
    send "{e up}{" RightKey " down}{" BackKey " down}"
    HyperSleep(925)
    send "{space 2}"
    HyperSleep(4500)
    send "{" BackKey " up}"
    HyperSleep(500)
    send "{" RightKey " up}{space}{" RotLeft " 4}"
    Sleep 2000
} else {
    nm_gotoramp()
    nm_Walk(67.5, BackKey, LeftKey)
    send "{" RotRight " 4}"
    nm_Walk(31, FwdKey)
    ;path 230630 noobyguy
}
'''


# ---- the transpile -----------------------------------------------------------

def test_send_tokens_read_autohotkeys_concatenated_string():
    assert T.send_tokens('send "{e up}{" RightKey " down}{" BackKey " down}"') == [
        ("e", "up"), ("RightKey", "down"), ("BackKey", "down")]
    assert T.send_tokens('send "{space 2}"') == [("space", "2")]
    assert T.send_tokens('send "{" RotLeft " 4}"') == [("RotLeft", "4")]
    assert T.send_tokens('send "{space}{" RotRight " 4}" ; land') == [("space", ""), ("RotRight", "4")]


@pytest.mark.parametrize("token, want", [
    (("e", "down"), [{"op": "key_down", "keys": "e"}]),
    (("e", "up"), [{"op": "key_up", "keys": "e"}]),
    (("e", ""), [{"op": "interact"}]),
    (("space", "2"), [{"op": "jump"}, {"op": "jump"}]),
    (("space", ""), [{"op": "jump"}]),
    (("RightKey", "down"), [{"op": "key_down", "keys": "d"}]),
    (("BackKey", "up"), [{"op": "key_up", "keys": "s"}]),
    (("RotLeft", "4"), [{"op": "camera", "direction": "left"}] * 4),
    (("RotRight", "1"), [{"op": "camera", "direction": "right"}]),
    (("F14", ""), None),                      # not a key this transpiler knows
    (("FwdKey", ""), None),                   # a bare movement tap: never seen, never guessed
])
def test_each_send_token_becomes_the_op_it_names(token, want):
    assert T.ops_of_token(*token) == want


def test_the_cannon_branch_is_the_first_branch_when_the_condition_says_cannon():
    flight = T.cannon_branch(PINETREE)
    assert "nm_gotocannon()" in flight and "HyperSleep(4500)" in flight
    assert "nm_Walk(67.5" not in flight, "that is the walking branch"
    assert T.cannon_branch("nm_Walk(5, FwdKey)") == "", "no branch, no flight"


def test_pine_tree_flies_exactly_as_natro_wrote_it():
    steps, credits, unknown = T.cannon_steps_of(T.cannon_branch(PINETREE))
    assert unknown == []
    assert steps == [
        {"op": "walk", "keys": "w", "studs": 20.0},
        {"op": "hive_offset", "keys": "d", "tiles_per_slot": 9.2,
         "tiles_offset": -4.0, "studs_per_tile": 4.0},
        {"op": "cannon_approach"},
        {"op": "key_down", "keys": "e"},
        {"op": "pause", "seconds": 0.1},
        {"op": "key_up", "keys": "e"},
        {"op": "key_down", "keys": "ds"},          # right and back, one press
        {"op": "pause", "seconds": 0.925},
        {"op": "jump"}, {"op": "jump"},             # {space 2}: the shot
        {"op": "pause", "seconds": 4.5},            # the flight
        {"op": "key_up", "keys": "s"},
        {"op": "pause", "seconds": 0.5},
        {"op": "key_up", "keys": "d"},
        {"op": "jump"},
        {"op": "camera", "direction": "left"}, {"op": "camera", "direction": "left"},
        {"op": "camera", "direction": "left"}, {"op": "camera", "direction": "left"},
        {"op": "pause", "seconds": 2.0},
    ]


def test_an_unknown_keystroke_is_reported_not_dropped():
    steps, _, unknown = T.cannon_steps_of('nm_gotocannon()\nsend "{F14 down}"\nSleep 100')
    assert unknown == ["F14 down"]
    assert {"op": "pause", "seconds": 0.1} in steps


def test_the_cost_is_time_at_natros_base_speed_not_a_distance():
    steps, _, _ = T.cannon_steps_of(T.cannon_branch(PINETREE))
    waits = 0.1 + 0.925 + 4.5 + 0.5 + 2.0
    assert T.cannon_cost_studs(steps) == pytest.approx(20.0 + T.CANNON_APPROACH_STUDS + waits * 28.0, abs=0.1)


# ---- the graph ---------------------------------------------------------------

FAR = ["pine_tree", "pumpkin", "pineapple", "rose_field", "stump", "mountain_top",
       "cactus", "strawberry", "clover", "bamboo", "blue_flower", "spider"]
NEAR = ["dandelion", "sunflower", "mushroom", "coconut", "pepper"]
ALLOWED_OPS = {"walk", "hive_offset", "cannon_approach", "key_down", "key_up",
               "pause", "jump", "camera", "interact", "jump_hold", "jump_release"}


def test_the_shipped_graph_flies_to_every_far_field_and_walks_to_the_near_ones():
    router = Router()
    by_name = {e.name: e for e in router.edges}
    for field in FAR:
        name = f"natro_out_{field}_via_red_cannon"
        assert name in by_name, f"no cannon route to {field}"
        assert by_name[name].via == "red_cannon"
        legs = [leg.name for leg in router.route("hive", field).legs]
        assert name in legs, f"the router walks to {field}: {legs}"
    for field in NEAR:
        legs = [leg.name for leg in router.route("hive", field).legs]
        assert not any("cannon" in leg for leg in legs), f"{field} is near; it should walk: {legs}"


def test_every_cannon_route_presses_only_what_the_flight_needs_and_lifts_every_key():
    router = Router()
    flights = [e for e in router.edges if e.name.endswith("_via_red_cannon")]
    # every far field has its flight; errands fly too now (boosters, the
    # Blender: 27 flights on 2026-10-03), and each is held to the same rules
    assert set(FAR) <= {e.end for e in flights}, set(FAR) - {e.end for e in flights}
    for edge in flights:
        ops = [s["op"] for s in edge.steps]
        assert set(ops) <= ALLOWED_OPS, (edge.name, set(ops) - ALLOWED_OPS)
        assert ops[:3] == ["walk", "hive_offset", "cannon_approach"], edge.name
        down = "".join(s["keys"] for s in edge.steps if s["op"] == "key_down")
        up = "".join(s["keys"] for s in edge.steps if s["op"] == "key_up")
        assert sorted(down) == sorted(up), f"{edge.name} leaves a key down: {down!r} vs {up!r}"
        # a glide's held jump (Natro's) is let go again
        assert ops.count("jump_hold") == ops.count("jump_release"), edge.name
        assert set(down) <= set("wasde"), (edge.name, down)
        # boarding: E goes down first (Natro holds it 100 ms, sometimes with
        # the steering keys already down) and comes up again
        i = ops.index("key_down")
        assert "e" in edge.steps[i]["keys"], (edge.name, edge.steps[i])
        assert any(s["op"] == "key_up" and "e" in s["keys"] for s in edge.steps[i:]), edge.name


# ---- the runner's ops ----------------------------------------------------------

class FakeInput:
    def __init__(self):
        self.events: list[tuple[str, str]] = []
        self.down: set[str] = set()

    def press(self, *keys):
        for k in keys:
            self.down.add(k)
            self.events.append(("press", k))

    def release(self, *keys):
        for k in keys:
            self.down.discard(k)
            self.events.append(("release", k))

    def release_all(self):
        self.down.clear()
        self.events.append(("release_all", ""))

    def tap(self, key, ms=40):
        self.events.append(("tap", key))

    class _Held:
        def __init__(self, inp, keys):
            self.inp, self.keys = inp, keys

        def __enter__(self):
            self.inp.press(*self.keys)
            return self.inp

        def __exit__(self, *exc):
            self.inp.release(*self.keys)

    def held(self, *keys):
        return FakeInput._Held(self, keys)


def _runner(steps, panel_text=None, name="fly"):
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge(name, "hive", "field", 100.0, steps=steps))
    inp = FakeInput()
    return RouteRunner(inp, r, walkspeed=100000.0, panel_text=panel_text), inp


def test_key_down_holds_across_later_steps_and_key_up_lifts_it():
    runner, inp = _runner([
        {"op": "key_down", "keys": "ds"},
        {"op": "jump"}, {"op": "jump"},
        {"op": "pause", "seconds": 0.0},
        {"op": "key_up", "keys": "s"},
        {"op": "key_up", "keys": "d"},
    ])
    out = runner.run("fly")
    assert out.ok
    assert inp.events == [("press", "d"), ("press", "s"), ("tap", "space"), ("tap", "space"),
                          ("release", "s"), ("release", "d")]
    assert not inp.down and not out.notes


def test_a_key_still_down_when_the_route_ends_is_lifted_and_said():
    runner, inp = _runner([{"op": "key_down", "keys": "w"}, {"op": "jump"}])
    out = runner.run("fly")
    assert not inp.down
    assert any("still down at the end" in n for n in out.notes), out.notes


def test_a_key_still_down_when_a_step_raises_is_lifted_too():
    class Boom(FakeInput):
        def tap(self, key, ms=40):
            raise RuntimeError("input died")
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("fly", "hive", "field", 1.0, steps=[{"op": "key_down", "keys": "d"}, {"op": "jump"}]))
    inp = Boom()
    runner = RouteRunner(inp, r, walkspeed=100000.0)
    with pytest.raises(RuntimeError):
        runner.run("fly")
    assert not inp.down


def test_the_cannon_approach_refuses_without_a_panel_reader():
    runner, inp = _runner([{"op": "cannon_approach"}, {"op": "key_down", "keys": "e"}])
    out = runner.run("fly")
    assert not out.ok and "panel reader" in out.reason
    assert ("press", "e") not in inp.events, "it must not board a cannon it cannot see"


# ---- the approach: one hop, hold right until the banner (R.CANNON_APPROACH_VERSION)
def _flyer(scores, panel=lambda: "Fire the Red Cannon", steps=None):
    """A runner whose cannon template reads `scores` in turn (the last one
    repeats) -- vision/screenstate's banner match, wired as run_farm does."""
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("fly", "hive", "field", 100.0,
               steps=steps or [{"op": "cannon_approach"}]))
    inp = FakeInput()
    runner = RouteRunner(inp, r, walkspeed=100000.0, panel_text=panel)
    left = list(scores)
    runner.cannon_prompt = lambda: left.pop(0) if len(left) > 1 else left[0]
    return runner, inp


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    monkeypatch.setattr(R, "CANNON_HOLD_SECONDS", 0.2)
    monkeypatch.setattr(R, "CANNON_SEARCH_SECONDS", 0.05)


def test_the_hold_stops_on_the_banner_and_the_panel_names_the_cannon(quick):
    runner, inp = _flyer([0.1, 0.2, 0.95])
    out = runner.run("fly")
    assert out.ok, out.reason
    assert sum(1 for e in inp.events if e == ("press", "space")) == 1, "one hop"
    assert ("press", R.CANNON_HOLD_KEY) in inp.events, "no hold right"
    assert any("at the red cannon after 1 hop" in n for n in out.notes), out.notes
    assert not inp.down


def test_a_hold_that_runs_out_is_a_miss_and_presses_nothing(quick):
    runner, inp = _flyer([0.1], steps=[{"op": "cannon_approach"},
                                       {"op": "key_down", "keys": "e"}])
    out = runner.run("fly")
    assert not out.ok and R.CANNON_MISS in out.reason, out.reason
    assert "no search: the hold ran out" in out.reason, out.reason
    assert ("press", "e") not in inp.events, "it must not board a cannon it never saw"
    assert not inp.down


def test_no_template_score_is_not_the_cannon(quick):
    """'I cannot tell' must never read as 'we are there'."""
    runner, inp = _flyer([None])
    out = runner.run("fly")
    assert not out.ok and "no template score to stop on" in out.reason, out.reason
    assert not inp.down


def test_a_panel_reader_that_cannot_look_leaves_it_to_the_template(quick):
    def broken():
        raise RuntimeError("model down")
    runner, inp = _flyer([0.95], panel=broken)
    out = runner.run("fly")
    assert out.ok, out.reason
    assert any("panel reader could not look" in n for n in out.notes), out.notes
    weak = R.CANNON_TEMPLATE_CONFIRMS - 0.05      # past the stop, short of the words
    runner, inp = _flyer([weak], panel=broken)
    out = runner.run("fly")
    assert not out.ok and "nothing was pressed" in out.reason, out.reason
    assert not inp.down


def test_a_banner_whose_panel_names_something_else_is_not_the_cannon(quick):
    runner, inp = _flyer([0.95], panel=lambda: "Talk to Black Bear")
    out = runner.run("fly")
    assert not out.ok and R.CANNON_MISS in out.reason, out.reason
    assert any("not the cannon" in n for n in out.notes), out.notes
    assert not inp.down


def test_a_route_with_its_own_approach_is_not_stopped_by_a_passing_prompt(quick):
    """The arrival watcher ends a walk when a prompt appears. Along the hive
    row an empty pad's "Claim Hive" appears; a cannon route must walk on."""
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("fly", "hive", "field", 100.0, steps=[
        {"op": "walk", "keys": "w", "studs": 50.0},
        {"op": "walk", "keys": "d", "studs": 50.0},
        {"op": "cannon_approach"},
    ]))
    inp = FakeInput()
    runner = RouteRunner(inp, r, walkspeed=100000.0, arrive=lambda: True,
                         panel_text=lambda: "Fire the Red Cannon")
    runner.cannon_prompt = lambda: 0.95
    out = runner.run("fly")
    assert out.ok, out.reason
    assert not out.skipped, out.skipped
    assert not any("stopped early" in n for n in out.notes), out.notes
    assert ("press", "d") in inp.events, "the second walk was skipped"
    assert runner.approach_studs("fly") == 100.0, "the approach ends at the cannon approach"


# ---- the speed factor -----------------------------------------------------------

def test_every_timed_hold_is_divided_by_the_movespeed_factor():
    """Natro's Walk() integrates real movespeed; ours divides the hold. Three
    Haste stacks are 1.3x, so the same studs take 1/1.3 of the time."""
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("walk", "a", "b", 64.4, steps=[{"op": "walk", "keys": "w", "studs": 64.4}]))
    inp = FakeInput()
    plain = RouteRunner(inp, r, walkspeed=32.2)
    hasty = RouteRunner(inp, r, walkspeed=32.2, movespeed_factor=lambda: 1.3)
    assert plain._hold_seconds(64.4) == pytest.approx(2.0)
    assert hasty._hold_seconds(64.4) == pytest.approx(2.0 / 1.3)
    assert hasty.last_factor == pytest.approx(1.3)


def test_a_reader_that_fails_or_reads_nonsense_means_base_speed():
    r = Router(path="/nonexistent", measurements=None)
    inp = FakeInput()

    def broken():
        raise RuntimeError("no frame")
    assert RouteRunner(inp, r, movespeed_factor=broken)._hold_seconds(32.2) == pytest.approx(32.2 / 32.2)
    assert RouteRunner(inp, r, movespeed_factor=lambda: 40.0)._hold_seconds(32.2) == pytest.approx(1.0)
    assert RouteRunner(inp, r, movespeed_factor=lambda: 0.0)._hold_seconds(32.2) == pytest.approx(1.0)


def test_patterns_are_not_photographed_only_routes():
    """24 legs every 13 s is not evidence, it is a full disk."""
    from hivemind.nav.router import Routine
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("out", "hive", "field", 10.0, steps=[{"op": "walk", "keys": "w", "studs": 10.0}]))
    r.routines["farm_snake"] = Routine("farm_snake", [{"op": "walk", "keys": "w", "studs": 8.0}], 8.0, False)
    shots = []
    runner = RouteRunner(FakeInput(), r, walkspeed=100000.0, snapshot=shots.append)
    runner.run("out")
    runner.run("farm_snake")
    assert shots and all(label.startswith("out-") for label in shots), shots
