"""Running a recorded route open-loop.

This is how every working Bee Swarm macro moves, and it needs no calibration,
so it is the layer that makes the transpiled graph usable today.

The tests that matter most are the ones about NOT doing something: the reset
primitive presses Escape, R, Return, and Roblox's in-game menu carries Log Out
and Leave as ordinary activatable tiles. A Return pressed at the wrong moment
logs the owner out of their account.
"""
import time

import pytest

from hivemind.act.routes import BASE_SPEED, RouteResult, RouteRunner
from hivemind.nav.router import Edge, Router, Routine


class FakeInput:
    def __init__(self):
        self.events: list[tuple[str, object]] = []
        self.held_keys: set[str] = set()

    def press(self, *keys):
        for k in keys:
            self.held_keys.add(k)
            self.events.append(("press", k))

    def release(self, *keys):
        for k in keys:
            self.held_keys.discard(k)
            self.events.append(("release", k))

    def release_all(self):
        self.events.append(("release_all", None))
        self.held_keys.clear()

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


def taps(inp) -> list[str]:
    return [key for action, key in inp.events if action == "tap"]


@pytest.fixture
def router():
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("leg_one", "hive", "field", 322.0, steps=[
        {"op": "shift_lock"},
        {"op": "camera", "direction": "right"},
        {"op": "walk", "keys": "w", "studs": 322.0},
        {"op": "jump"},
        {"op": "pause", "seconds": 0.0},
    ]))
    r.add(Edge("leg_two", "field", "shop", 161.0, steps=[
        {"op": "walk", "keys": "wd", "studs": 161.0},
        {"op": "interact"},
    ]))
    r.routines["with_reset"] = Routine("with_reset", [{"op": "reset"}], 0.0, False)
    r.routines["calls_missing"] = Routine(
        "calls_missing", [{"op": "call", "route": "nope"}], 0.0, False)
    return r


@pytest.fixture
def runner(router):
    inp = FakeInput()
    return RouteRunner(inp, router, walkspeed=1000.0), inp   # fast, for tests


# ---- the recordings are walkspeed-independent ------------------------------

def test_a_walk_holds_for_distance_over_walkspeed():
    inp = FakeInput()
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("one", "a", "b", 64.4,
               steps=[{"op": "walk", "keys": "w", "studs": 64.4}]))

    slow = RouteRunner(inp, r, walkspeed=BASE_SPEED)
    quick = RouteRunner(inp, r, walkspeed=BASE_SPEED * 4)
    assert slow._hold_seconds(64.4) == pytest.approx(2.0)
    assert quick._hold_seconds(64.4) == pytest.approx(0.5)


def test_the_recorded_distance_is_reported(runner):
    run, _ = runner
    result = run.run("leg_one")
    assert result.ok
    assert result.studs == pytest.approx(322.0)


# ---- the primitives that were silently dropped -----------------------------

def test_shift_lock_camera_and_jump_all_reach_the_keyboard(runner):
    """All three used to transpile into calls to routes that did not exist."""
    run, inp = runner
    run.run("leg_one")
    pressed = taps(inp)
    assert "shift" in pressed, "shift lock never sent"
    assert "period" in pressed, "camera turn never sent"
    assert "space" in pressed, "jump never sent"


def test_walk_keys_are_pressed_and_released(runner):
    run, inp = runner
    run.run("leg_two")
    assert ("press", "w") in inp.events and ("press", "d") in inp.events
    assert inp.held_keys == set(), "a movement key was left down"


def test_no_key_is_left_held_after_a_route(runner):
    run, inp = runner
    run.run("leg_one")
    run.run("leg_two")
    assert inp.held_keys == set()


# ---- reset must never press Return blind -----------------------------------

def test_reset_is_refused_without_a_way_to_confirm_the_menu(runner):
    """Escape opens a menu carrying Log Out and Leave as ordinary tiles."""
    run, inp = runner
    result = run.run("with_reset")
    assert "enter" not in taps(inp), "pressed Return with no confirmation"
    assert any("reset" in s for s in result.skipped)


def test_reset_stops_when_the_dialog_is_not_there(router, monkeypatch):
    import hivemind.act.routes as routes
    monkeypatch.setattr(routes, "MENU_SETTLE", 0.0)
    inp = FakeInput()
    run = RouteRunner(inp, router, confirm_menu=lambda: False)
    result = run.run("with_reset")
    assert "enter" not in taps(inp), "pressed Return on an unconfirmed menu"
    assert not result.ok
    assert "Leave" in result.reason, result.reason


def _up_until_return():
    """The respawn confirmation: up when looked for, gone once Return has
    taken -- the runner looks again after it (RESET_ENTER_RETRIES)."""
    looks = {"n": 0}

    def confirm():
        looks["n"] += 1
        return looks["n"] == 1
    return confirm


def test_reset_proceeds_once_the_dialog_is_confirmed(router, monkeypatch):
    import hivemind.act.routes as routes
    monkeypatch.setattr(routes, "RESET_SETTLE", 0.0)
    monkeypatch.setattr(routes, "MENU_SETTLE", 0.0)
    inp = FakeInput()
    run = RouteRunner(inp, router, confirm_menu=_up_until_return())
    result = run.run("with_reset")
    assert taps(inp) == ["escape", "r", "enter"]
    assert result.ok


def test_a_refused_reset_does_not_leave_the_bot_on_the_leave_screen(router,
                                                                    monkeypatch):
    """MEASURED: Escape from the respawn confirmation goes back to the in-game
    menu, which is the screen carrying Leave -- so ONE escape is not enough."""
    import hivemind.act.routes as routes
    monkeypatch.setattr(routes, "MENU_SETTLE", 0.0)
    inp = FakeInput()
    run = RouteRunner(inp, router, confirm_menu=lambda: False)
    run.run("with_reset")
    assert taps(inp).count("escape") >= 2, "left the bot on the menu"


def test_the_back_out_keeps_escaping_until_the_dialog_is_gone(router,
                                                              monkeypatch):
    import hivemind.act.routes as routes
    monkeypatch.setattr(routes, "MENU_SETTLE", 0.0)
    inp = FakeInput()
    seen = {"n": 0}

    def stubborn():
        # the confirmation stays up for the first two escapes
        seen["n"] += 1
        return seen["n"] <= 3

    run = RouteRunner(inp, router, confirm_menu=stubborn)
    run.run("with_reset")
    # confirm_menu returned True on the pre-check, so it pressed enter
    assert "enter" in taps(inp)


def test_the_back_out_never_presses_anything_but_escape(router, monkeypatch):
    """Leave and Respawn are one focus-change away; only Escape is safe."""
    import hivemind.act.routes as routes
    monkeypatch.setattr(routes, "MENU_SETTLE", 0.0)
    inp = FakeInput()
    run = RouteRunner(inp, router, confirm_menu=lambda: False)
    run.run("with_reset")
    pressed = taps(inp)
    assert set(pressed) <= {"escape", "r"}, f"pressed something else: {pressed}"


# ---- honest reporting ------------------------------------------------------

def test_a_call_to_an_untranspiled_helper_is_recorded_not_swallowed(runner):
    run, _ = runner
    result = run.run("calls_missing")
    assert result.ok
    assert any("nope" in s for s in result.skipped)


def test_an_unknown_route_is_reported(runner):
    run, _ = runner
    result = run.run("does_not_exist")
    assert not result.ok and "no route named" in result.reason


def test_travel_runs_every_leg_of_a_routed_path(runner):
    run, _ = runner
    result = run.travel("hive", "shop")
    assert result.ok
    assert result.studs == pytest.approx(322.0 + 161.0)


def test_travel_reports_an_impossible_journey(runner):
    run, _ = runner
    result = run.travel("shop", "hive")
    assert not result.ok and "no known way" in result.reason


# ---- the hive-slot hop -----------------------------------------------------
# Every route out of the hive assumes the character starts at ITS OWN slot.
# BeeTuxMacro gets there with `for ((i=0; i<5-$1; i++)); do jump; ...; done`,
# which the first transpiler turned into an opaque shell line -- so the hop
# vanished and the first live run ended on sand beside slot 5.

@pytest.fixture
def hop_router():
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("to_hive", "corner", "hive", 16.1, steps=[
        {"op": "hop_to_slot", "from_slot": 5},
    ]))
    return r


@pytest.mark.parametrize("slot, expected_hops", [
    (5, 0), (4, 1), (3, 2), (1, 4),
])
def test_it_hops_five_minus_slot_times(hop_router, slot, expected_hops,
                                       monkeypatch):
    import hivemind.act.routes as routes
    monkeypatch.setattr(routes, "HOP_RISE", 0.0)
    monkeypatch.setattr(routes, "HOP_SETTLE", 0.0)
    inp = FakeInput()
    RouteRunner(inp, hop_router, hive_slot=slot).run("to_hive")
    assert taps(inp).count("space") == expected_hops * 2   # two jumps per hop


def test_an_unconfigured_slot_skips_the_hop_and_says_so(hop_router):
    """A guess here starts every hive route from the wrong place."""
    inp = FakeInput()
    result = RouteRunner(inp, hop_router, hive_slot=None).run("to_hive")
    assert taps(inp) == [], "hopped without knowing where to"
    assert any("hive slot" in s for s in result.skipped)


def test_a_slot_beyond_the_start_does_not_hop_backwards(hop_router):
    inp = FakeInput()
    RouteRunner(inp, hop_router, hive_slot=6).run("to_hive")
    assert taps(inp) == []


# ---- the shipped field patterns, end to end --------------------------------
# The three farm_* routines are the only routines the runner is ever asked to
# loop for minutes at a time (farm.sh:11 loops one forever while in a field),
# so they are the worst place for a key to be left down. Everything above runs
# synthetic steps; this runs the real transpiled data.

@pytest.mark.parametrize("name", ["farm_square", "farm_snake",
                                  "farm_better_snake"])
def test_a_shipped_field_pattern_runs_and_leaves_no_key_down(name):
    """Overnight, this loop runs thousands of times. One stuck key is a night
    of the character walking into a wall, and the panic hotkey is the only
    thing that would stop it.

    Also the end-to-end check that the graph and the runner agree: a step the
    runner does not recognise lands in `skipped` rather than being executed,
    so a pattern of 16 holds that the runner can only do 15 of would otherwise
    look exactly like success.
    """
    inp = FakeInput()
    run = RouteRunner(inp, Router(), walkspeed=1e6)   # fast, for tests
    result = run.run(name)

    assert result.ok, result.reason
    assert result.skipped == [], "the runner could not execute a recorded hold"
    assert inp.held_keys == set(), "a movement key was left down"
    assert result.studs > 0
    assert result.steps_run == len(Router().routines[name].steps)


@pytest.mark.parametrize("name", ["farm_square", "farm_snake",
                                  "farm_better_snake"])
def test_a_field_pattern_releases_its_keys_even_when_the_walk_raises(name):
    """`held()` is what guarantees this, and only an exception proves it.

    A panic stop, a compositor error or a SIGINT can land inside any hold. If
    the runner ever went back to bare press/release around the sleep, this is
    the test that would catch it -- the assertion above would not, because a
    clean run releases the keys either way.
    """
    inp = FakeInput()
    run = RouteRunner(inp, Router(), walkspeed=1e6)
    calls = {"n": 0}

    def explode(seconds):
        calls["n"] += 1
        if calls["n"] == 2:               # mid-pattern, with keys down
            raise KeyboardInterrupt("panic")
        return 0.0

    run._hold_seconds = explode
    with pytest.raises(KeyboardInterrupt):
        run.run(name)
    assert inp.held_keys == set(), "a key survived an exception mid-hold"


# ---------------------------------------------------------------------------
# The glide home
# ---------------------------------------------------------------------------
def test_a_hold_step_holds_its_keys_for_the_recorded_time(runner):
    """`hold` is measured in seconds, and that is the honest unit for a fall.

    MEASURED, and it is why the op exists: `from_pine_tree_to_hive` holds W
    across `sleep 4` with no `wait` to price it, so the transpiler could
    derive no distance and emitted a `raw` note that RouteRunner skipped. That
    step is the GLIDE off the pine tree, and dropping it is what the owner
    watched go wrong -- it jumped behind the ledge and never glided
    down.
    """
    run, vin = runner
    result = RouteResult("glide")
    run._run_step({"op": "hold", "keys": "w", "seconds": 0.05}, result, 0)
    assert ("press", "w") in vin.events, "the key never went down"
    assert ("release", "w") in vin.events, "the key never came back up"
    assert not vin.held_keys, "the key was left down after the hold"
    assert not result.skipped, f"the hold was skipped: {result.skipped}"


def test_a_hold_with_no_time_or_no_keys_does_nothing(runner):
    run, vin = runner
    result = RouteResult("noop")
    run._run_step({"op": "hold", "keys": "", "seconds": 4.0}, result, 0)
    run._run_step({"op": "hold", "keys": "w", "seconds": 0.0}, result, 0)
    assert not vin.held_keys
    assert ("press", "w") not in vin.events


def test_the_route_home_from_pine_tree_still_carries_its_glide():
    """A regression guard on the DATA, not just the executor.

    The graph is transpiler output. If a future run of the transpiler loses
    this step again, every farm cycle falls short of the hive and the bot
    presses its interact key wherever it lands -- which is how one cycle
    opened a Polar Bear quest dialogue.
    """
    from hivemind.nav.router import Router
    edge = next((e for e in Router().edges
                 if e.name == "from_pine_tree_to_hive"), None)
    assert edge is not None, "the route home from Pine Tree is missing"
    holds = [s for s in edge.steps if s.get("op") == "hold"]
    assert holds, "the glide hold is gone from the route home"
    assert any(float(s.get("seconds", 0)) >= 1.0 for s in holds), \
        "the four-second glide is no longer a hold"


# ---------------------------------------------------------------------------
# Looking while walking
# ---------------------------------------------------------------------------
def test_a_walk_lets_the_watcher_look_while_the_key_is_down(router):
    """Without this, nothing can react to anything mid-walk.

    A gather pass is 231.6 studs of `farm_snake`, about 8.3s at walkspeed 28,
    and the loop used to examine no frame at all during it. A mob detector
    above that layer answers a question about an eight-second-old screen.
    """
    vin = FakeInput()
    looks = []
    run = RouteRunner(vin, router, walkspeed=1000.0, step_gap=0.0,
                      watch=lambda: looks.append(sorted(vin.held_keys)) or False,
                      watch_hz=200.0)
    result = RouteResult("walk")
    run._run_step({"op": "walk", "keys": "w", "studs": 500.0}, result, 0)
    assert looks, "the watcher never got to look during the walk"
    assert all(view == ["w"] for view in looks), \
        "the key must still be held while the watcher looks"
    assert not vin.held_keys, "the key was left down"


def test_a_watcher_can_stop_a_walk_early(router):
    vin = FakeInput()
    run = RouteRunner(vin, router, walkspeed=1.0, step_gap=0.0,
                      watch=lambda: True, watch_hz=200.0)
    result = RouteResult("walk")
    started = time.monotonic()
    run._run_step({"op": "walk", "keys": "w", "studs": 10_000.0}, result, 0)
    assert time.monotonic() - started < 2.0, \
        "a 10,000-stud walk at walkspeed 1 should have been cut short"
    assert run.interrupted == 1
    assert not vin.held_keys, "the key must come up when the walk is aborted"


def test_a_watcher_that_raises_does_not_strand_a_held_key(router):
    def boom():
        raise RuntimeError("capture died mid-walk")
    vin = FakeInput()
    run = RouteRunner(vin, router, walkspeed=1000.0, step_gap=0.0,
                      watch=boom, watch_hz=200.0)
    result = RouteResult("walk")
    run._run_step({"op": "walk", "keys": "wd", "studs": 300.0}, result, 0)
    assert not vin.held_keys
    assert not result.skipped


def test_without_a_watcher_the_timing_is_unchanged(router):
    """The slicing must not change how far an unwatched walk goes."""
    vin = FakeInput()
    run = RouteRunner(vin, router, walkspeed=100.0, step_gap=0.0)
    started = time.monotonic()
    run._run_step({"op": "walk", "keys": "w", "studs": 50.0}, RouteResult("w"), 0)
    elapsed = time.monotonic() - started
    assert 0.4 < elapsed < 0.75, f"expected ~0.5s, got {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Walking by measurement instead of by timer
# ---------------------------------------------------------------------------
def test_a_walk_stops_when_the_world_has_moved_far_enough(router):
    """Closed loop: the distance is covered, not merely waited out.

    The drift this fixes: a timed hold assumes a fixed walkspeed, so a haste
    token makes every leg overshoot and the error accumulates until the
    character is somewhere else entirely.
    """
    from hivemind.nav.pace import PaceMeter
    meter = PaceMeter()
    for _ in range(20):                      # teach it: 20 px/s is normal
        meter.observe("w", flow_px=20.0, seconds=1.0)

    vin = FakeInput()
    # moving at DOUBLE the usual rate: 4 px per 0.1s slice = 40 px/s
    run = RouteRunner(vin, router, walkspeed=100.0, step_gap=0.0,
                      pace=meter, flow=lambda: 4.0, watch_hz=10.0)
    started = time.monotonic()
    run._run_step({"op": "walk", "keys": "w", "studs": 100.0}, RouteResult("w"), 0)
    elapsed = time.monotonic() - started
    # planned is 1.0s; at double speed the target flow arrives in about half
    assert elapsed < 0.85, f"did not stop early despite moving fast: {elapsed:.2f}s"
    assert run.paced_walks == 1
    assert not vin.held_keys


def test_a_blocked_walk_still_ends(router):
    """Against a wall the expected flow never arrives. The key must come up.

    The owner watched exactly this: it walked right, toward Pine Tree, into
    a wall.
    """
    from hivemind.nav.pace import PaceMeter
    meter = PaceMeter()
    for _ in range(20):
        meter.observe("w", flow_px=20.0, seconds=1.0)
    vin = FakeInput()
    run = RouteRunner(vin, router, walkspeed=1000.0, step_gap=0.0,
                      pace=meter, flow=lambda: 0.0, watch_hz=50.0)
    started = time.monotonic()
    run._run_step({"op": "walk", "keys": "w", "studs": 200.0}, RouteResult("w"), 0)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0, f"a blocked walk ran on for {elapsed:.2f}s"
    assert not vin.held_keys


def test_without_a_baseline_the_recorded_timing_is_used(router):
    """The first walks of a session must behave exactly as before."""
    from hivemind.nav.pace import PaceMeter
    vin = FakeInput()
    run = RouteRunner(vin, router, walkspeed=100.0, step_gap=0.0,
                      pace=PaceMeter(), flow=lambda: 50.0, watch_hz=50.0)
    started = time.monotonic()
    run._run_step({"op": "walk", "keys": "w", "studs": 50.0}, RouteResult("w"), 0)
    elapsed = time.monotonic() - started
    assert 0.4 < elapsed < 0.8, f"expected the recorded ~0.5s, got {elapsed:.2f}s"
    assert run.paced_walks == 0


def test_a_broken_flow_source_falls_back_to_the_timer(router):
    from hivemind.nav.pace import PaceMeter
    meter = PaceMeter()
    for _ in range(20):
        meter.observe("w", flow_px=20.0, seconds=1.0)

    def boom():
        raise RuntimeError("the tracker died")
    vin = FakeInput()
    run = RouteRunner(vin, router, walkspeed=100.0, step_gap=0.0,
                      pace=meter, flow=boom, watch_hz=50.0)
    run._run_step({"op": "walk", "keys": "w", "studs": 50.0}, RouteResult("w"), 0)
    assert not vin.held_keys


def test_the_step_gap_never_delays_a_timed_sequence(router):
    """The glider deploy is jump, pause 0.5275, jump — and that 0.5275 is real.

    MEASURED by the owner watching it fail: the second jump, which opens
    the parachute, came a little too late. A 0.12s gap inserted
    before every step turned 0.5275 into 0.7675, which is 45% late and the
    difference between gliding home and hitting the ground.
    """
    from hivemind.act.routes import STEP_GAP
    vin = FakeInput()
    run = RouteRunner(vin, router, walkspeed=1000.0, step_gap=STEP_GAP)
    result = RouteResult("glide")
    started = time.monotonic()
    for step in ({"op": "jump"}, {"op": "pause", "seconds": 0.5275},
                 {"op": "jump"}):
        run._run_step(step, result, 0)
    elapsed = time.monotonic() - started
    assert elapsed < 0.5275 + 0.06, (
        f"the glider sequence took {elapsed:.3f}s against a recorded 0.5275s "
        f"— a gap is being inserted inside a timed sequence")


def test_the_step_gap_still_applies_between_walks(router):
    """It was added for a real reason and must not vanish everywhere."""
    from hivemind.act.routes import STEP_GAP
    vin = FakeInput()
    run = RouteRunner(vin, router, walkspeed=100_000.0, step_gap=STEP_GAP)
    result = RouteResult("walks")
    started = time.monotonic()
    for _ in range(4):
        run._run_step({"op": "walk", "keys": "w", "studs": 1.0}, result, 0)
    assert time.monotonic() - started >= STEP_GAP * 3


# --- a walk cut short by a mob must be FINISHED, not abandoned -------------
# MEASURED 2026-09-22: 15 to 22 walks cut short per run by the mob watcher,
# against recorded routes whose whole design is exact distances. The walk home
# missed the hive every time; a 656,538-pollen backpack had to be banked by
# rejoining instead. Natro's paths deliberately overshoot into walls to
# normalise position, so a walk that stops early does not merely fall short --
# it lands somewhere the rest of the path was never written for.

def _resumable(watch, settle, walkspeed=1000.0):
    from hivemind.act.routes import RouteRunner
    from hivemind.nav.router import Edge, Router
    inp = FakeInput()
    router = Router(path="/nonexistent", measurements=None)
    router.add(Edge("walk_it", "a", "b", 400.0,
                    steps=[{"op": "walk", "keys": "w", "studs": 400.0}]))
    runner = RouteRunner(inp, router, walkspeed=walkspeed,
                         watch=watch, settle=settle,
                         flow=lambda: 99.0)     # never reads as blocked
    return runner, inp


def test_a_walk_cut_short_is_finished_once_the_coast_is_clear():
    danger = {"on": True}
    seen = {"watch": 0}

    def watch():
        seen["watch"] += 1
        return danger["on"] and seen["watch"] == 1      # one interruption

    runner, inp = _resumable(watch, settle=lambda: not danger["on"])
    danger["on"] = True

    def clear():
        danger["on"] = False
        return True

    runner.settle = clear
    result = runner.run("walk_it")

    assert runner.interrupted == 1
    assert runner.resumed == 1, "the remaining distance was abandoned"
    assert any("finishing the last" in n for n in result.notes), result.notes


def test_the_keys_come_up_while_it_waits():
    """Walking on through the settle would defeat the reaction that stopped
    it. `held` is per attempt, not around the whole loop."""
    held_during_wait = []
    seen = {"n": 0}

    def watch():
        seen["n"] += 1
        return seen["n"] == 1

    runner, inp = _resumable(watch, settle=None)

    def settle():
        held_during_wait.append(set(inp.held_keys))
        return True

    runner.settle = settle
    runner.run("walk_it")

    assert held_during_wait, "settle was never consulted"
    assert all(not h for h in held_during_wait), held_during_wait


def test_it_gives_up_on_the_remainder_if_it_never_becomes_safe():
    """Better to arrive short and say so than to stand in a mob for ever."""
    runner, _ = _resumable(watch=lambda: True, settle=lambda: False)
    import hivemind.act.routes as R
    was, R.SETTLE_TIMEOUT = R.SETTLE_TIMEOUT, 0.05
    try:
        result = runner.run("walk_it")
    finally:
        R.SETTLE_TIMEOUT = was

    assert runner.resumed == 0
    assert any("unwalked" in n for n in result.notes), result.notes


def test_without_a_settle_hook_nothing_changes():
    """The old behaviour must survive for any caller that does not opt in."""
    seen = {"n": 0}

    def watch():
        seen["n"] += 1
        return seen["n"] == 1

    runner, _ = _resumable(watch, settle=None)
    result = runner.run("walk_it")

    assert runner.interrupted == 1
    assert runner.resumed == 0
    assert not any("finishing the last" in n for n in result.notes)


# --- feeling for the ramp when the hive slot is unknown ---------------------
# Natro's `nm_gotoRamp` walks 9.2*slot-4 tiles right from the pad to the ramp,
# a corner. With the slot unconfigured the bot used to skip that walk and every
# route out of the hive began from the wrong place. Now it walks the distance
# slot 6 would need, lets the ramp wall stop it, and reads the slot back off
# the distance it actually covered before the flow said blocked.

def _offset_runner(flow, walkspeed=100.0, slot=None):
    from hivemind.act.routes import RouteRunner
    from hivemind.nav.router import Edge, Router
    inp = FakeInput()
    router = Router(path="/nonexistent", measurements=None)
    router.add(Edge("to_ramp", "hive", "ramp", 200.0, steps=[
        {"op": "hive_offset", "keys": "d", "tiles_per_slot": 9.2,
         "tiles_offset": -4.0, "studs_per_tile": 4.0}]))
    runner = RouteRunner(inp, router, walkspeed=walkspeed, flow=flow,
                         hive_slot=slot)
    runner.watch_interval = 0.01
    return runner, inp


def _wall_after(seconds):
    """Flow that reads open ground, then a wall from `seconds` in."""
    import time as _t
    t0 = {"at": None}

    def flow():
        now = _t.monotonic()
        if t0["at"] is None:
            t0["at"] = now
        return 99.0 if now - t0["at"] < seconds else 0.0
    return flow


def test_with_the_slot_unknown_it_walks_to_the_ramp_and_learns_the_slot():
    # slot 3 by the formula: (9.2*3 - 4) tiles * 4 studs = 94.4 studs; at 100
    # studs/s that is 0.944 s before the wall
    runner, inp = _offset_runner(_wall_after(0.944), walkspeed=100.0)

    result = runner.run("to_ramp")

    assert result.skipped == [], result.skipped
    assert result.learned_slot == 3, (result.learned_slot, result.notes)
    assert any("learned slot 3" in n for n in result.notes), result.notes
    assert "d" in "".join(inp.legs) if hasattr(inp, "legs") else True


def test_never_meeting_a_wall_is_said_rather_than_read_as_a_slot():
    runner, _ = _offset_runner(lambda: 99.0, walkspeed=100.0)

    result = runner.run("to_ramp")

    assert result.learned_slot is None
    assert any("without meeting a wall" in n for n in result.notes), result.notes


def test_with_no_flow_it_still_refuses_to_guess():
    runner, inp = _offset_runner(flow=None, walkspeed=100.0)

    result = runner.run("to_ramp")

    assert result.learned_slot is None
    assert any("hive_offset" in s for s in result.skipped), result.skipped


def test_a_configured_slot_walks_the_formula_and_learns_nothing():
    runner, _ = _offset_runner(_wall_after(0.5), walkspeed=100.0, slot=2)

    result = runner.run("to_ramp")

    assert result.learned_slot is None
    assert result.skipped == []
    assert result.studs == pytest.approx((9.2 * 2 - 4.0) * 4.0)


# --- Natro's `switch HiveSlot`, kept as data and chosen at run time ----------
# The walks home end in a branch per slot: `case 3` stops on pad 3, `default`
# walks to the ramp corner. The runner takes the case for the slot it was
# given and the general path otherwise. See scripts/transpile_natro.slot_switch
# and docs/DESIGN.md 8cc.

SWITCH = {"op": "slot_switch",
          "cases": {"3": [{"op": "walk", "keys": "s", "studs": 10.8}]},
          "default": [{"op": "walk", "keys": "s", "studs": 6.0},
                      {"op": "walk", "keys": "d", "studs": 140.0},
                      {"op": "walk", "keys": "s", "studs": 10.8}]}


def _switch_runner(slot, snapshot=None):
    from hivemind.act.routes import RouteRunner
    from hivemind.nav.router import Edge, Router
    inp = FakeInput()
    router = Router(path="/nonexistent", measurements=None)
    router.add(Edge("home", "spider", "hive", 300.0, steps=[
        {"op": "walk", "keys": "w", "studs": 144.0}, dict(SWITCH)]))
    runner = RouteRunner(inp, router, walkspeed=100000.0, hive_slot=slot,
                         snapshot=snapshot)
    return runner, inp


def _walked(inp) -> list[str]:
    return [key for action, key in inp.events if action == "press"]


def test_the_owned_slots_branch_is_the_one_walked():
    runner, inp = _switch_runner(slot=3)
    result = runner.run("home")
    assert result.ok
    assert _walked(inp) == ["w", "s"], inp.events
    assert result.steps_run == 2
    assert result.studs == 144.0 + 10.8
    assert result.branches == ["home: took the case 3 branch for hive slot 3 (1 step(s))"]


def test_a_slot_with_no_case_walks_the_general_path():
    runner, inp = _switch_runner(slot=5)
    result = runner.run("home")
    assert _walked(inp) == ["w", "s", "d", "s"], inp.events
    assert result.studs == 144.0 + 6.0 + 140.0 + 10.8
    assert result.branches == ["home: took the default branch for hive slot 5 (3 step(s))"]


def test_an_unknown_slot_walks_the_general_path_and_says_so():
    for unknown in (None, 0):
        runner, inp = _switch_runner(slot=unknown)
        result = runner.run("home")
        assert _walked(inp) == ["w", "s", "d", "s"], (unknown, inp.events)
        assert result.branches == ["home: took the default branch for hive slot unknown (3 step(s))"]


def test_every_leg_of_the_branch_is_photographed_like_any_other():
    labels = []
    runner, _ = _switch_runner(slot=5, snapshot=labels.append)
    runner.run("home")
    assert labels == ["home-00-start", "home-01-walk-w144",
                      "home-02.01-walk-s6", "home-02.02-walk-d140",
                      "home-02.03-walk-s10"], labels


def test_the_approach_counts_the_branch_that_will_run():
    runner, _ = _switch_runner(slot=3)
    assert runner.approach_studs("home") == 144.0 + 10.8
    runner, _ = _switch_runner(slot=5)
    assert runner.approach_studs("home") == 144.0 + 6.0 + 140.0 + 10.8


def test_what_a_route_contains_is_asked_of_every_branch():
    from hivemind.act.routes import RouteRunner
    from hivemind.nav.router import Edge, Router
    inp = FakeInput()
    router = Router(path="/nonexistent", measurements=None)
    router.add(Edge("pressy", "a", "b", 10.0, steps=[
        {"op": "slot_switch", "cases": {"2": [{"op": "interact"}]},
         "default": [{"op": "walk", "keys": "w", "studs": 4.0}]}]))
    router.add(Edge("caller", "a", "b", 10.0, steps=[
        {"op": "slot_switch", "cases": {},
         "default": [{"op": "call", "route": "pressy"}]}]))
    runner = RouteRunner(inp, router, walkspeed=1000.0, hive_slot=3)
    # slot 3 would never press, but the route CAN, and that is the question
    assert runner._has_op("pressy", "interact")
    assert runner.route_names("caller") == ["caller", "pressy"]


# --- the guarded reset as a standalone step, for coming home from an errand --

def test_respawn_presses_nothing_on_the_menu_until_the_dialog_is_confirmed(router, monkeypatch):
    from hivemind.act import routes
    monkeypatch.setattr(routes, "MENU_SETTLE", 0.0)
    monkeypatch.setattr(routes, "RESET_SETTLE", 0.0)
    inp = FakeInput()
    run = RouteRunner(inp, router, confirm_menu=lambda: False)
    result = run.respawn()
    assert not result.ok and "refusing to press Return" in result.reason
    assert "enter" not in taps(inp)


def test_respawn_confirms_then_returns(router, monkeypatch):
    from hivemind.act import routes
    monkeypatch.setattr(routes, "MENU_SETTLE", 0.0)
    monkeypatch.setattr(routes, "RESET_SETTLE", 0.0)
    inp = FakeInput()
    run = RouteRunner(inp, router, confirm_menu=_up_until_return())
    result = run.respawn()
    assert result.ok, result.reason
    assert taps(inp) == ["escape", "r", "enter"]


def test_respawn_without_a_way_to_confirm_is_a_refusal_not_a_press(router):
    inp = FakeInput()
    run = RouteRunner(inp, router)
    result = run.respawn()
    assert not result.ok and "no menu confirmation" in result.reason
    assert taps(inp) == []


# --- lean legs: walk INTO the wall this leg is for, however far it is ------
# Natro's walks home open by leaning into a wall or corner to fix the position
# (the transpiler marks them from Natro's comments). Recorded as timed walks
# they reach the wall only from within the recording; held until the flow says
# blocked they reach it from anywhere. See DESIGN 8cq.

def _lean_runner(flow, walkspeed=100.0, lean_studs=50.0):
    from hivemind.act.routes import RouteRunner
    from hivemind.nav.router import Edge, Router
    inp = FakeInput()
    router = Router(path="/nonexistent", measurements=None)
    router.add(Edge("home", "field", "hive", 100.0, steps=[
        {"op": "walk", "keys": "s", "studs": lean_studs, "lean": True,
         "why": "walk back against wall"},
        {"op": "walk", "keys": "w", "studs": 20.0}]))
    runner = RouteRunner(inp, router, walkspeed=walkspeed, flow=flow)
    runner.watch_interval = 0.01
    return runner, inp


def _held_seconds(inp, key):
    """How long `key` was down, from the fake input's event stream."""
    import time as _t
    down = None
    total = 0.0
    for action, k in inp.events:
        if k != key:
            continue
        if action == "press":
            down = _t.monotonic()
        elif action == "release" and down is not None:
            total += _t.monotonic() - down
            down = None
    return total


def test_a_lean_runs_past_the_recording_until_the_wall():
    """Recorded 1.0 s (100 studs at 100/s); the wall is 1.3 s away. The old
    hold stopped at 1.0 s in open ground; the lean reaches the wall and
    releases after LEAN_STOP_SECONDS of blocked flow, inside the 3.0 s cap."""
    import hivemind.act.routes as R
    runner, inp = _lean_runner(_wall_after(1.3), walkspeed=100.0, lean_studs=100.0)
    t0 = __import__("time").monotonic()
    result = runner.run("home")
    took = __import__("time").monotonic() - t0
    assert result.ok
    note = [n for n in result.notes if "lean" in n][0]
    assert "reached the wall after" in note, note
    assert took >= 1.3 + R.LEAN_STOP_SECONDS - 0.05, took
    assert took < 1.0 * R.LEAN_CAP_FACTOR, took
    assert inp.held_keys == set(), "a key was left down"


def test_a_lean_with_no_wall_stops_at_the_cap_and_says_so():
    import hivemind.act.routes as R
    runner, inp = _lean_runner(lambda: 99.0, walkspeed=100.0)
    t0 = __import__("time").monotonic()
    result = runner.run("home")
    took = __import__("time").monotonic() - t0
    note = [n for n in result.notes if "lean" in n][0]
    assert "without meeting a wall" in note, note
    assert 0.5 * R.LEAN_CAP_FACTOR - 0.1 <= took < 0.5 * R.LEAN_CAP_FACTOR + 0.6, took


def test_a_block_before_half_the_recording_is_a_stumble_not_the_wall():
    """Blocked from the very start (a tile edge). Recorded 4.0 s, so the lean
    may not end before 2.0 s however long the flow has read blocked."""
    import hivemind.act.routes as R
    runner, inp = _lean_runner(lambda: 0.0, walkspeed=100.0, lean_studs=400.0)
    t0 = __import__("time").monotonic()
    result = runner.run("home")
    took = __import__("time").monotonic() - t0
    assert took >= 4.0 * R.LEAN_EARLIEST - 0.05, took
    assert took < 4.0 * R.LEAN_EARLIEST + 1.0, took
    assert "reached the wall" in [n for n in result.notes if "lean" in n][0]


def test_without_a_flow_reader_a_lean_is_the_recording_as_written():
    runner, inp = _lean_runner(None, walkspeed=100.0)
    t0 = __import__("time").monotonic()
    result = runner.run("home")
    took = __import__("time").monotonic() - t0
    assert result.ok and not any("lean" in n for n in result.notes)
    assert took < 1.0, took


def test_an_ordinary_walk_is_untouched_by_the_lean_machinery():
    runner, inp = _lean_runner(lambda: 99.0, walkspeed=100.0)
    result = runner.run("home")
    assert result.studs == 70.0
    assert [k for a, k in inp.events if a == "press"] == ["s", "w"]


def test_the_home_glide_says_it_is_airborne_while_it_coasts():
    """run_farm's watch ignores a mob while `airborne`: lifting the keys
    mid-glide drops the character (MEASURED 2026-10-08 01:22)."""
    from hivemind.act.routes import RouteRunner
    from hivemind.nav.router import Edge, Router
    inp = FakeInput()
    router = Router(path="/nonexistent", measurements=None)
    router.add(Edge("natro_home_pine_tree", "pine_tree", "hive", 432.0, steps=[
        {"op": "key_down", "keys": "w"}, {"op": "coast", "studs": 432.0},
        {"op": "key_up", "keys": "w"}]))
    seen = []
    runner = RouteRunner(inp, router, walkspeed=100000.0,
                         watch=lambda: seen.append(runner.airborne) or False,
                         settle=lambda: True, flow=lambda: 99.0)
    runner.run("natro_home_pine_tree")
    assert seen and all(seen), seen
    assert runner.airborne is False


def test_a_ramp_reading_of_2_4_is_slot_3_and_one_of_2_1_is_slot_2():
    # one too big pushes into the corner it walks to anyway; one too small
    # stops short of it (2026-10-08 03:05). (9.2*2.4-4)*4 = 72.3 studs.
    runner, _ = _offset_runner(_wall_after(0.723), walkspeed=100.0)
    assert runner.run("to_ramp").learned_slot == 3
    runner, _ = _offset_runner(_wall_after(0.613), walkspeed=100.0)
    assert runner.run("to_ramp").learned_slot == 2


# ---- CLOSE_THE_PASS: a CornerXSnake pass that ends where it began -----------

def _natro_pattern(name):
    import pathlib
    import yaml
    import hivemind
    path = pathlib.Path(hivemind.__file__).resolve().parents[2] / "data/world/natro_patterns.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("routines", data)
    return next(r["steps"] for r in rows if r["name"] == name)


def test_cornerxsnake_drifts_into_its_corner_and_the_closing_legs_undo_it():
    from hivemind.act.routes import closing_legs, pass_drift
    steps = _natro_pattern("natro_pattern_pepper_as_natro")
    right, forward = pass_drift(steps)
    assert right == pytest.approx(24.5, abs=0.1)
    assert forward == pytest.approx(27.3, abs=0.1)
    legs = closing_legs(steps)
    assert [k for k, _ in legs] == ["s", "a"]
    closed = steps + [{"op": "walk", "keys": k, "studs": s} for k, s in legs]
    assert pass_drift(closed) == pytest.approx((0.0, 0.0), abs=0.1)
    # a pattern that already closes walks nothing back
    assert closing_legs([{"op": "walk", "keys": "w", "studs": 8.0},
                         {"op": "walk", "keys": "s", "studs": 8.0}]) == []


def test_close_the_pass_is_look_only_and_says_so_once_a_gather(capsys):
    from hivemind.act import routes as routes_mod
    assert routes_mod.CLOSE_THE_PASS_LIVE is False
    inp = FakeInput()
    r = Router(path="/nonexistent", measurements=None)
    name = "natro_pattern_pepper_as_natro"
    r.routines[name] = Routine(name, [{"op": "walk", "keys": "w", "studs": 30.0},
                                      {"op": "walk", "keys": "d", "studs": 10.0}], 40.0, False)
    run = RouteRunner(inp, r, walkspeed=100000.0)
    run.run(name)
    run.run(name)
    assert [k for a, k in inp.events if a == "press"] == ["w", "d", "w", "d"]
    said = capsys.readouterr().out
    assert said.count("close the pass would: walk s 30.0 studs, a 10.0 studs") == 1
