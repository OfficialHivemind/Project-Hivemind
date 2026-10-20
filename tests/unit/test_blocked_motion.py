"""Knowing when a held key is moving nothing. See act/routes._hold_watching,
world/bearings.saw_motion and nav/journey.Outcome.notes."""
from __future__ import annotations

import time
import contextlib
from types import SimpleNamespace

from hivemind.act import routes as R
from hivemind.vision import landmarks as lm
from hivemind.vision.flow import BLOCKED_FLOW_PX
from hivemind.world.bearings import Bearings


class Vin:
    def __init__(self):
        self.held_now: set[str] = set()
        self.taps: list[str] = []

    @contextlib.contextmanager
    def held(self, *keys):
        self.held_now.update(keys)
        try:
            yield
        finally:
            self.held_now.difference_update(keys)

    def tap(self, key, ms=40):
        self.taps.append(key)

    def press(self, *k): pass
    def release(self, *k): pass
    def release_all(self): self.held_now.clear()


def _runner(flow, studs, on_motion=None, watch=None):
    router = SimpleNamespace(
        edges=[SimpleNamespace(name="leg", steps=[{"op": "walk", "keys": "w", "studs": studs}])],
        routines={})
    return R.RouteRunner(Vin(), router, walkspeed=28.0, step_gap=0.0,
                         flow=flow, on_motion=on_motion, watch=watch, watch_hz=20)


# ------------------------------------------------------------ the runner ---
def test_a_hold_that_moves_nothing_is_written_down():
    """56 studs at 28/s is a two-second hold; the world never moves."""
    result = _runner(lambda: 0.0, studs=56).run("leg")
    assert result.ok
    assert result.blocked_seconds > R.BLOCKED_NOTE_SECONDS
    assert result.notes and "pushed against something" in result.notes[0]
    assert "w for 56 studs" in result.notes[0]


def test_a_hold_that_moves_is_not():
    result = _runner(lambda: 20.0, studs=56).run("leg")
    assert result.blocked_seconds == 0.0 and result.notes == []


def test_no_reading_is_not_a_zero_reading():
    """A featureless floor gives the tracker nothing; that is 'do not know',
    never 'blocked'."""
    result = _runner(lambda: None, studs=56).run("leg")
    assert result.blocked_seconds == 0.0 and result.notes == []


def test_a_short_stumble_is_below_the_note_threshold():
    # 28 studs = one second, all of it blocked, still under BLOCKED_NOTE_SECONDS
    result = _runner(lambda: 0.0, studs=28).run("leg")
    assert result.blocked_seconds == 0.0 and result.notes == []


def test_the_compass_is_told_at_the_watch_rate():
    heard = []
    _runner(lambda: 0.3, studs=28, on_motion=lambda k, px: heard.append((k, px))).run("leg")
    assert len(heard) >= 5
    assert all(k == "w" and px == 0.3 for k, px in heard)


def test_a_listener_that_throws_does_not_end_the_walk():
    def boom(k, px):
        raise RuntimeError("no")
    result = _runner(lambda: 0.3, studs=28, on_motion=boom).run("leg")
    assert result.ok and result.steps_run == 1


def test_the_watcher_still_stops_a_blocked_hold():
    result = _runner(lambda: 0.0, studs=56, watch=lambda: True).run("leg")
    assert result.ok                     # the route is not a failure...
    assert result.blocked_seconds < 0.5  # ...and it did not sit out the two seconds


def test_without_flow_it_is_the_plain_timed_hold():
    result = _runner(None, studs=28).run("leg")
    assert result.ok and result.blocked_seconds == 0.0


# ----------------------------------------------------------- the compass ---
class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


def _bearings():
    clock = Clock()
    return Bearings(lm.Table({}), clock=clock), clock


def test_blocked_time_accumulates_while_keys_move_nothing():
    """The route runner reports at its watch rate while a key is held (10 Hz),
    and a claim lapses MOTION_FRESH_S after the last report (world/bearings;
    run-531's stale 894 s), so the push is timed from reports that keep coming."""
    b, clock = _bearings()
    assert b.saw_motion("w", 0.1) is False
    for t in (0.5, 1.0, 1.5, 2.0, 2.5):
        clock.t = t
        assert b.saw_motion("w", 0.1) is False
    assert b.blocked_seconds == 2.5
    assert "pushing against something for 2s" in b.describe()


def test_moving_again_clears_it():
    b, clock = _bearings()
    b.saw_motion("w", 0.1); clock.t = 3.0
    assert b.saw_motion("w", BLOCKED_FLOW_PX + 1) is True
    assert b.blocked_seconds == 0.0
    assert "pushing" not in b.describe()


def test_no_keys_held_means_no_opinion():
    b, _ = _bearings()
    assert b.saw_motion("", 0.0) is None
    assert b.blocked_seconds == 0.0


def test_a_spawn_clears_it():
    b, clock = _bearings()
    b.saw_motion("w", 0.0); clock.t = 5.0
    b.spawned()
    assert b.blocked_seconds == 0.0


def test_episodes_are_counted_once_each():
    b, clock = _bearings()
    for _ in range(5):
        b.saw_motion("w", 0.0)
    assert b.blocked_episodes == 1
    b.saw_motion("w", 10.0)
    b.saw_motion("w", 0.0)
    assert b.blocked_episodes == 2


# ------------------------------------------------------- arrival by sight ---
# The approach is three legs of 56 studs -- 168 in all -- so the 0.6 gate
# opens 100.8 studs in, which is 44.8 studs (1.6 s at walkspeed 28) into the
# SECOND leg. Arrival is therefore impossible during leg one, which is the
# whole point: leg one starts on the hive pad.
def _approach(arrive, flow=None, **kw):
    router = SimpleNamespace(edges=[SimpleNamespace(name="approach", steps=[
        {"op": "walk", "keys": "w", "studs": 56},
        {"op": "walk", "keys": "d", "studs": 56},
        {"op": "walk", "keys": "d", "studs": 56},
        {"op": "interact"},
        {"op": "walk", "keys": "a", "studs": 28},
    ])], routines={})
    return R.RouteRunner(Vin(), router, walkspeed=28.0, step_gap=0.0,
                         flow=flow, arrive=arrive, watch_hz=20, **kw)


def test_the_approach_total_is_measured_up_to_the_press():
    """168 studs of approach and a 28-stud departure. The departure is not
    part of the approach -- counting it would move the gate."""
    runner = _approach(lambda: False)
    assert runner.approach_studs("approach") == 168.0
    assert runner.approach_studs("no_such_route") is None


def test_a_call_step_is_followed_when_measuring_the_approach():
    """THE REAL SHAPE: from_hive_to_pumpkin_with_red_cannon is a `call` to
    from_hive_to_red_cannon and then a press, and every stud of the approach
    is inside the call."""
    router = SimpleNamespace(
        edges=[SimpleNamespace(name="outer", steps=[
            {"op": "call", "route": "inner"},
            {"op": "interact"},
            {"op": "walk", "keys": "a", "studs": 999},
        ])],
        routines={"inner": SimpleNamespace(steps=[
            {"op": "walk", "keys": "w", "studs": 64.4},
            {"op": "walk", "keys": "d", "studs": 212.5},
        ])})
    runner = R.RouteRunner(Vin(), router, walkspeed=28.0)
    assert runner.approach_studs("outer") == 276.9


def test_the_hold_ends_when_the_target_comes_into_view_and_the_rest_of_the_approach_is_skipped():
    runner = _approach(lambda: True)
    result = runner.run("approach")
    assert result.ok and runner.arrivals == 1
    assert any("stopped early" in n for n in result.notes)
    assert any("already arrived" in s for s in result.skipped), result.skipped
    # the walk AFTER the interact still runs to its timer: that is the
    # DEPARTURE, and the prompt it was approaching is often still on screen
    assert not any("walk a" in s for s in result.skipped)
    assert runner.arrivals == 1, "the departure was cut short too"


def test_arrival_CANNOT_fire_on_the_first_leg_of_the_approach():
    """THE OWNER'S BUG, as a test.

    "it tried going to the cannon to go to pumpkin but failed walked past and
    went to black bear". Arrival fired on the first watch tick of the first
    walk -- the hive pad's own prompt was on screen -- so all 259 remaining
    studs of the approach were skipped as "already arrived" and the route
    pressed E at the hive. The log line was
    "from_hive_to_pumpkin_with_red_cannon: w: stopped early".
    """
    legs = []
    runner = _approach(lambda: True)
    runner.on_step = lambda op, step: legs.append(
        (op, step.get("keys"), runner.approach_fraction()))
    runner.run("approach")
    first = [f for op, keys, f in legs if op == "walk"][0]
    assert first == 0.0
    # leg one ran in full: 56 studs at 28/s is 2 s, and it was not cut short
    assert not any("w:" in n for n in runner.run("approach").notes)


def test_the_gate_is_off_when_the_approach_length_is_unknown():
    """A route the graph cannot measure must not lose arrival entirely --
    a bare timer is worse than an early stop."""
    runner = _approach(lambda: True)
    runner.begin_approach(None)
    assert runner.approach_fraction() is None
    assert runner._may_arrive() is True


def test_without_a_target_in_view_the_approach_runs_to_its_timers():
    runner = _approach(lambda: False)
    result = runner.run("approach")
    assert runner.arrivals == 0 and result.skipped == []
    assert result.seconds >= 6.5


def test_arrival_works_with_the_flow_meter_running_too():
    runner = _approach(lambda: True, flow=lambda: 20.0)
    result = runner.run("approach")
    assert runner.arrivals == 1 and result.seconds < 5.0


def test_a_broken_arrival_check_does_not_end_the_route():
    def boom():
        raise RuntimeError("no frame")
    result = _approach(boom).run("approach")
    assert result.ok and result.skipped == []


# ------------------- the step gap must stay off BOTH sides of a jump --------
# THE OWNER FOUND THIS BY WATCHING: the bot missed the jumps to the
# cannon. `from_hive_to_red_cannon` ends
#
#     walk a 4.8 · jump · pause 0.1 · walk d 22.5 · jump · walk d 19.3
#
# and those walks carry the character ONTO the platform while it is airborne.
# `jump` is in TIMED_OPS so no gap goes before it -- but the walk after it got
# the full 0.12 s, and the second jump has no recorded pause at all, so its
# walk began a quarter of the rise late.
#
# Same fault, same file, found the same way as the glider: "the second jump
# button to activate the parachute was just a bit too late".

def _timed(steps, gap=0.12):
    router = SimpleNamespace(
        edges=[SimpleNamespace(name="hop", steps=steps)], routines={})
    return R.RouteRunner(Vin(), router, walkspeed=28.0, step_gap=gap)


def _gap_before_each(steps, gap=0.12):
    """When each op started, relative to the first, in seconds."""
    runner = _timed(steps, gap)
    stamps = []
    runner.on_step = lambda op, step: stamps.append((op, time.monotonic()))
    runner.run("hop")
    if not stamps:
        return []
    first = stamps[0][1]
    return [(op, round(at - first, 3)) for op, at in stamps]


def test_no_gap_between_a_jump_and_the_walk_that_follows_it():
    steps = [{"op": "jump"}, {"op": "walk", "keys": "d", "studs": 1}]
    marks = _gap_before_each(steps)
    assert marks[1][0] == "walk"
    assert marks[1][1] < 0.05, (
        f"the walk began {marks[1][1]:.3f}s after the jump; it must start "
        f"while the character is still in the air")


def test_the_recorded_pause_after_a_jump_is_not_stretched():
    steps = [{"op": "jump"}, {"op": "pause", "seconds": 0.1},
             {"op": "walk", "keys": "d", "studs": 1}]
    marks = _gap_before_each(steps)
    # jump at 0, pause at ~0, walk at ~0.1 -- the recorded pause and nothing
    # more. With the gap on it was 0.1 + 0.12.
    assert marks[2][0] == "walk"
    assert 0.09 <= marks[2][1] < 0.16, (
        f"the walk began {marks[2][1]:.3f}s after the jump; the route asked "
        f"for 0.1")


def test_the_gap_still_sits_between_two_plain_walks():
    """It is there for a reason: BeeTuxMacro spawns a process per keypress and
    its recordings carry that overhead. Between walks, tens of milliseconds
    change nothing."""
    steps = [{"op": "walk", "keys": "w", "studs": 1},
             {"op": "walk", "keys": "d", "studs": 1}]
    marks = _gap_before_each(steps)
    first_walk = 1 / 28.0
    assert marks[1][1] >= first_walk + 0.10, (
        f"the second walk began {marks[1][1]:.3f}s in; the gap is missing")


def test_the_gap_stays_off_the_glider_sequence():
    """`from_pine_tree_to_hive` deploys the glider with jump, pause 0.5275,
    jump. A gap on either side of those made it 46% late."""
    steps = [{"op": "jump"}, {"op": "pause", "seconds": 0.2},
             {"op": "jump"}]
    marks = _gap_before_each(steps)
    assert marks[2][0] == "jump"
    assert 0.19 <= marks[2][1] < 0.26, f"{marks[2][1]:.3f}s, asked for 0.2"
