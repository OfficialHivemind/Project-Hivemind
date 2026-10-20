"""Turning the camera until forward is walkable.

The bot spawns facing the hive wall with `w` blocked, and every movement key is
relative to the camera, so this is how it gets unstuck. The camera step was
measured by closure in game (8 taps per full turn, 45 degrees each); these
tests cover the search logic against a simulated world where the blocked
headings are known.
"""
import numpy as np
import pytest

from hivemind.act.orient import (CAMERA_STEP_DEG, OPEN_FLOW_PX,
                                 TAPS_PER_FULL_TURN, face_open_ground)


class FakeWorld:
    """A world where some camera headings face a wall.

    `blocked` is a set of tap counts, modulo a full turn, at which forward is
    obstructed -- exactly the pattern measured in game, where taps 0, 1 and 9
    were blocked and 9 = 1 + 8 is the same heading.
    """

    def __init__(self, blocked=(0, 1), open_flow=9.0, blocked_flow=1.1):
        self.blocked = set(blocked)
        self.open_flow, self.blocked_flow = open_flow, blocked_flow
        self.taps = 0
        self.held: set[str] = set()
        self.probes = 0

    # -- input side
    def press(self, *keys):
        self.held.update(keys)

    def release(self, *keys):
        self.held.difference_update(keys)

    def camera_right(self, taps=1, gap=0.0):
        self.taps += taps

    # -- vision side
    def frames(self):
        return np.zeros((8, 8, 4), np.uint8)

    def tracker(self):
        world = self

        class Tracker:
            def __init__(self):
                self._first = True

            def update(self, _frame):
                if self._first:
                    self._first = False
                    return None
                world.probes += 1
                blocked = (world.taps % TAPS_PER_FULL_TURN) in world.blocked
                magnitude = world.blocked_flow if blocked else world.open_flow
                pairs = np.zeros((6, 2, 2))
                pairs[:, 1, 0] = magnitude
                return type("S", (), {"pairs": pairs})()

        return Tracker


def run(world):
    # zero waits: the real ones are for the game to settle, not logic
    return face_open_ground(world, world.frames, world.tracker(),
                            seconds=0.0, settle=0.0)


# ---- the measured constants ------------------------------------------------

def test_a_full_turn_is_eight_taps_of_forty_five_degrees():
    assert TAPS_PER_FULL_TURN == 8
    assert CAMERA_STEP_DEG == pytest.approx(45.0)


def test_headings_wrap_at_a_full_turn():
    from hivemind.act.orient import Heading
    assert Heading(0, 0, False).degrees == pytest.approx(0.0)
    assert Heading(1, 0, False).degrees == pytest.approx(45.0)
    assert Heading(9, 0, False).degrees == pytest.approx(45.0)   # 9 == 1 + 8


# ---- the search ------------------------------------------------------------

def test_it_turns_until_forward_opens_up():
    """Spawn facing the wall (taps 0 and 1 blocked) -- it must reach tap 2."""
    world = FakeWorld(blocked=(0, 1))
    heading = run(world)
    assert heading.open
    assert heading.taps == 2, f"stopped at {heading.describe()}"
    assert heading.flow_px >= OPEN_FLOW_PX


def test_it_does_not_turn_when_forward_is_already_open():
    world = FakeWorld(blocked=())
    heading = run(world)
    assert heading.open and heading.taps == 0
    assert world.taps == 0, "turned the camera for no reason"


def test_it_stops_after_one_full_turn():
    """A second lap would only repeat the same headings."""
    world = FakeWorld(blocked=tuple(range(TAPS_PER_FULL_TURN)))
    heading = run(world)
    assert not heading.open
    assert world.taps <= TAPS_PER_FULL_TURN


def test_a_fully_blocked_sweep_returns_the_best_it_found():
    """No exception: a wrong guess costs a burst, not anything irreversible."""
    world = FakeWorld(blocked=tuple(range(TAPS_PER_FULL_TURN)),
                      blocked_flow=0.4)
    heading = run(world)
    assert not heading.open
    assert heading.flow_px == pytest.approx(0.4)


def test_no_key_is_left_held_by_a_probe():
    world = FakeWorld(blocked=(0, 1))
    run(world)
    assert world.held == set(), "a probe left a movement key down"


def test_a_probe_that_raises_still_releases_the_key():
    class Exploding(FakeWorld):
        def tracker(self):
            def factory():
                class Tracker:
                    def update(self, _frame):
                        raise RuntimeError("capture died")
                return Tracker()
            return factory

    world = Exploding()
    with pytest.raises(RuntimeError):
        run(world)
    assert world.held == set()
