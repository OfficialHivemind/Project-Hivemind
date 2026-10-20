"""Closed-loop walking, in the simulator.

The decisive test is test_haste_does_not_break_the_walk: a speed buff lands
mid-walk, which is the exact scenario that silently ruins every open-loop macro
(they hold the key for a precomputed time and sail past the target). A loop that
measures distance should not care at all.
"""
import numpy as np
import pytest

from hivemind.nav.geometry import GroundPlane
from hivemind.nav.odometry import WorldOdometer
from hivemind.nav.walker import Stuck, walk_studs
from hivemind.sim.kinematic import Camera, KinematicSim
from hivemind.vision.flow import FlowTracker

CAM = Camera()
CALIB_WORLD = [(-14, 22), (14, 22), (-9, 46), (9, 46), (0, 32), (-20, 60), (20, 60)]


@pytest.fixture(scope="module")
def plane():
    pts, _ = CAM.project(np.array(CALIB_WORLD, float), 0.0, 0.0)
    return GroundPlane.fit(pts, CALIB_WORLD, (CAM.width, CAM.height))


def make(plane, **kw):
    sim = KinematicSim(camera=CAM, **kw)
    odo = WorldOdometer(plane, FlowTracker(scale=1.0, min_tracked=6),
                        max_spread_studs=3.0, min_tracked=6)
    return sim, odo


@pytest.mark.parametrize("target", [20.0, 40.0, 75.0])
def test_walks_the_requested_distance(plane, target):
    sim, odo = make(plane)
    r = walk_studs(target, "w", vin=sim, frames=sim.frame, odo=odo,
                   clock=lambda: sim.time)
    # truth comes from the simulator, not from our own measurement
    assert sim.travelled == pytest.approx(target, rel=0.10), \
        f"asked {target}, actually moved {sim.travelled:.1f}"
    assert not r.stuck


def test_haste_does_not_break_the_walk(plane):
    """A speed buff lands mid-walk. Open-loop overshoots; we must not."""
    sim, odo = make(plane)
    real_frame = sim.frame

    def frame_with_haste():
        if sim.travelled > 15.0:
            sim.walkspeed = 56.0          # haste: double speed, mid-walk
        return real_frame()

    walk_studs(45.0, "w", vin=sim, frames=frame_with_haste, odo=odo,
               clock=lambda: sim.time)
    assert sim.travelled == pytest.approx(45.0, rel=0.12), \
        f"haste threw the walk off: moved {sim.travelled:.1f} of 45"


def test_slow_walkspeed_also_lands(plane):
    """The mirror case: a slower character must still arrive, not stop short."""
    sim, odo = make(plane, walkspeed=14.0)
    walk_studs(30.0, "w", vin=sim, frames=sim.frame, odo=odo, clock=lambda: sim.time)
    assert sim.travelled == pytest.approx(30.0, rel=0.10)


def test_wall_raises_stuck_quickly(plane):
    """Blocked at 10 studs while asked for 60: must give up fast, not grind."""
    sim, odo = make(plane, wall_at_z=10.0)
    with pytest.raises(Stuck):
        walk_studs(60.0, "w", vin=sim, frames=sim.frame, odo=odo,
                   clock=lambda: sim.time)
    assert sim.travelled < 12.0
    assert sim.time < 4.0, "took too long to notice it was stuck"


def test_keys_are_released_even_on_stuck(plane):
    """A leaked key would leave the character running at a wall forever."""
    sim, odo = make(plane, wall_at_z=8.0)
    with pytest.raises(Stuck):
        walk_studs(50.0, "w", vin=sim, frames=sim.frame, odo=odo,
                   clock=lambda: sim.time)
    assert sim._held == set(), f"keys leaked: {sim._held}"


def test_diagonal_walk(plane):
    sim, odo = make(plane)
    walk_studs(30.0, ("w", "d"), vin=sim, frames=sim.frame, odo=odo,
               clock=lambda: sim.time)
    assert sim.travelled == pytest.approx(30.0, rel=0.12)
    assert sim.x > 5 and sim.z > 5, "diagonal did not move on both axes"


def test_overshoot_is_bounded(plane):
    """Sampling at 10 Hz means we can only stop on a tick boundary; the early
    release must keep the error well under one tick of travel."""
    sim, odo = make(plane)
    walk_studs(50.0, "w", vin=sim, frames=sim.frame, odo=odo, clock=lambda: sim.time)
    tick_distance = sim.walkspeed * sim.dt          # 2.8 studs
    assert abs(sim.travelled - 50.0) < tick_distance
