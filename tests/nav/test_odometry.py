"""End-to-end navigation sensing: rendered ground -> flow -> homography -> studs.

This is the test that matters. It renders a textured ground plane through a
synthetic camera, moves the player a KNOWN number of studs, and checks the full
pipeline recovers that distance. If this works, closed-loop movement works.
"""
import cv2
import numpy as np
import pytest

from hivemind.nav.geometry import GroundPlane
from hivemind.nav.odometry import WorldOdometer
from hivemind.vision.flow import FlowTracker

W, H = 1280, 720
FOCAL, CAM_H, PITCH = 800.0, 12.0, np.radians(28.0)
RNG = np.random.default_rng(7)

# Ground texture: fixed specks at known world positions, like grass detail.
TEXTURE = np.column_stack([RNG.uniform(-70, 70, 1400), RNG.uniform(3, 130, 1400)])
SHADES = RNG.integers(70, 255, len(TEXTURE))


def project(pts, player_z=0.0, player_x=0.0):
    """World points -> screen pixels, for a player standing at (player_x, player_z)."""
    rel = np.column_stack([pts[:, 0] - player_x,
                           np.full(len(pts), CAM_H),
                           pts[:, 1] - player_z])
    c, s = np.cos(PITCH), np.sin(PITCH)
    R = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    pc = rel @ R.T
    vis = pc[:, 2] > 1.0
    x = FOCAL * pc[:, 0] / pc[:, 2] + W / 2
    y = FOCAL * pc[:, 1] / pc[:, 2] + H / 2
    return np.column_stack([x, y]), vis


def render(player_z=0.0, player_x=0.0):
    img = np.full((H, W, 3), (58, 104, 68), np.uint8)
    img += RNG.integers(0, 10, img.shape, dtype=np.uint8)
    pts, vis = project(TEXTURE, player_z, player_x)
    for (x, y), shade, ok in zip(pts, SHADES, vis):
        if ok and 0 <= x < W and 0 <= y < H:
            # nearer specks draw bigger, which is what gives LK real corners
            r = max(1, int(6 - (y / H) * 0 + (y - H / 2) / 120))
            cv2.circle(img, (int(x), int(y)), max(1, r), (int(shade),) * 3, -1)
    return img


@pytest.fixture(scope="module")
def plane():
    world = [(-14, 22), (14, 22), (-9, 46), (9, 46), (0, 32), (-20, 60), (20, 60)]
    screen, _ = project(np.array(world, float))
    return GroundPlane.fit(screen, world, (W, H))


def walk(plane, steps, step_studs, strafe=0.0):
    """Walk forward in increments; return measured (dx, dz)."""
    odo = WorldOdometer(plane, FlowTracker(scale=1.0, min_tracked=6),
                        max_spread_studs=3.0, min_tracked=6)
    odo.update(render(0.0, 0.0))
    for i in range(1, steps + 1):
        odo.update(render(i * step_studs, i * strafe))
    return odo


@pytest.mark.parametrize("steps,step", [(6, 1.0), (10, 1.5), (4, 2.5)])
def test_forward_distance_recovered(plane, steps, step):
    odo = walk(plane, steps, step)
    expected = steps * step
    assert odo.rejected == 0, "frames were rejected during a clean walk"
    assert odo.dz == pytest.approx(expected, rel=0.12), \
        f"walked {expected} studs, measured {odo.dz:.2f}"
    assert abs(odo.dx) < 0.6 * step, "phantom sideways drift"


def test_strafe_component_recovered(plane):
    odo = walk(plane, 8, 1.0, strafe=0.5)
    assert odo.dz == pytest.approx(8.0, rel=0.15)
    assert odo.dx == pytest.approx(4.0, rel=0.25)


def test_standing_still_measures_nothing(plane):
    """The stuck-detection path: no movement must read ~0 studs."""
    odo = WorldOdometer(plane, FlowTracker(scale=1.0, min_tracked=6), min_tracked=6)
    f = render(0.0)
    odo.update(f)
    for _ in range(5):
        odo.update(f.copy())
    assert odo.displacement < 0.3, f"drifted {odo.displacement:.3f} studs while stationary"


def test_walking_into_a_wall_is_detectable(plane):
    """Player presses W but the world does not move -- the signature of being
    stuck on terrain. Distance must stay flat so the controller can give up."""
    odo = WorldOdometer(plane, FlowTracker(scale=1.0, min_tracked=6), min_tracked=6)
    odo.update(render(0.0))
    for _ in range(4):
        odo.update(render(0.0))
    assert odo.displacement < 0.3


def test_direction_sign_is_forward_positive(plane):
    """A sign error here would drive the bot backwards forever."""
    odo = walk(plane, 5, 2.0)
    assert odo.dz > 0, f"forward walk reported dz={odo.dz:.2f}"


# --- regression: the spread gate must see single-axis disagreement ----------
# The gate used to median over the FLATTENED (N,2) deviation array, pooling the
# dx and dz deviations into one 2N sample. For a straight walk every ground
# point agrees dx~0, so those N zeros filled the lower half and the median
# collapsed to ~0 however badly the points disagreed about FORWARD motion.
# This is the only trust gate enabled by default, so it was passing fabricated
# distance straight into walk_studs().

def _step_from_world(plane, w0, w1):
    """Build a FlowSample whose pairs project the given world motion."""
    from hivemind.vision.flow import FlowSample
    s0, _ = project(np.asarray(w0, float))
    s1, _ = project(np.asarray(w1, float))
    pairs = np.stack([s0, s1], axis=1).astype(np.float64)
    return FlowSample(0.0, 0.0, len(pairs), 0.0, True, pairs)


def test_spread_gate_catches_disagreement_about_forward_motion(plane):
    """20 points that disagree by up to 19 studs must not pass a 1.5 gate."""
    odo = WorldOdometer(plane, max_spread_studs=1.5, min_tracked=8)
    before = [(0.0, 25.0 + i) for i in range(20)]
    # each point slides back by a DIFFERENT amount: total disagreement 19 studs
    after = [(0.0, 25.0 + i - i) for i in range(20)]
    step = odo._to_world_step(_step_from_world(plane, before, after))
    assert step.spread > 1.5, f"disagreement invisible: spread={step.spread:.3f}"
    assert not step.ok, f"fabricated {step.dz:.1f} studs accepted"


def test_spread_gate_still_accepts_a_consistent_step(plane):
    """The tightened gate must not reject honest motion."""
    odo = WorldOdometer(plane, max_spread_studs=1.5, min_tracked=8)
    before = [(x, z) for x in (-8.0, 0.0, 8.0) for z in range(25, 45, 2)]
    after = [(x, z - 4.0) for x, z in before]     # every point agrees exactly
    step = odo._to_world_step(_step_from_world(plane, before, after))
    assert step.ok, f"consistent step rejected: spread={step.spread:.3f}"
    assert step.dz == pytest.approx(4.0, abs=0.05)
