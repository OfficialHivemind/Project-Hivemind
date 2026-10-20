"""Odometry tests against known ground truth.

Optical flow is the component the whole navigation stack trusts, so it is tested
on displacement accuracy, robustness to independently-moving objects, and -- most
importantly -- whether it *knows when it is wrong*. A confidently wrong odometer
is far more dangerous than one that reports failure.
"""
import cv2
import numpy as np
import pytest

from hivemind.vision.flow import FlowTracker, Odometer

RNG = np.random.default_rng(1234)


def textured(w=640, h=360):
    """A frame with plenty of trackable corners, like real ground detail."""
    img = RNG.integers(0, 255, (h, w), dtype=np.uint8)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def shift(img, dx, dy):
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, M, (img.shape[1], img.shape[0]),
                          borderMode=cv2.BORDER_REFLECT)


@pytest.mark.parametrize("dx,dy", [(5, 0), (0, 7), (12, -9), (-20, 4), (2.5, 1.5)])
def test_measures_known_displacement(dx, dy):
    t = FlowTracker(scale=1.0)
    base = textured()
    assert t.update(base) is None            # first frame has no reference
    s = t.update(shift(base, dx, dy))
    assert s.ok
    assert s.dx == pytest.approx(dx, abs=0.6)
    assert s.dy == pytest.approx(dy, abs=0.6)


def test_downscaling_preserves_scale():
    """scale=0.5 halves the work; the reported displacement must still be in
    full-resolution pixels."""
    base = textured()
    t = FlowTracker(scale=0.5)
    t.update(base)
    s = t.update(shift(base, 16, -8))
    assert s.ok
    assert s.dx == pytest.approx(16, abs=1.5)
    assert s.dy == pytest.approx(-8, abs=1.5)


def test_median_rejects_moving_distractors():
    """Bees, particles and other players move independently. A mean would be
    dragged by them; the median must not be."""
    base = textured()
    moved = shift(base, 10, 0)
    # paste several big blobs travelling the opposite way
    for cx in (80, 240, 400, 560):
        cv2.circle(moved, (cx, 180), 26, (255, 255, 255), -1)
        cv2.circle(moved, (cx - 40, 240), 22, (0, 0, 0), -1)
    t = FlowTracker(scale=1.0)
    t.update(base)
    s = t.update(moved)
    assert s.ok
    assert s.dx == pytest.approx(10, abs=1.5), "distractors dragged the estimate"


def test_stationary_reads_zero():
    """Walking into a wall must read ~0, which is how we detect being stuck."""
    base = textured()
    t = FlowTracker(scale=1.0)
    t.update(base)
    s = t.update(base.copy())
    assert s.ok
    assert s.magnitude < 0.4


def test_untrackable_frames_fail_safe():
    """Two unrelated frames must never produce a large phantom displacement.

    Measured behaviour: the forward-backward check kills most points and the few
    survivors agree on "barely moved", so the reading collapses toward zero. That
    is the safe direction -- it surfaces as "stuck" (we stop and recover) rather
    than as bogus distance (we walk somewhere wrong and never notice).
    """
    t = FlowTracker(scale=1.0)
    t.update(textured())
    s = t.update(textured())          # different random content
    assert s.magnitude < 2.0, f"phantom displacement of {s.magnitude:.1f}px"


# NOTE: there is deliberately no test for the opt-in `max_spread` pixel gate.
# It is off by default (world-space agreement is the real check) and the median
# plus forward-backward filtering are specifically built to be hard to fool, so
# every attempt to construct a scene that trips it ended up measuring our own
# robustness instead. A test that cannot fail for the stated reason is worse
# than no test. Revisit if the gate ever gets switched on for a real code path.


def test_featureless_frame_fails_cleanly():
    flat = np.full((360, 640, 3), 128, np.uint8)
    t = FlowTracker(scale=1.0)
    t.update(flat)
    s = t.update(flat.copy())
    assert not s.ok and s.tracked == 0


def test_odometer_accumulates_a_leg():
    """Ten steps of 8px must integrate to 80px, which is what walk_studs()
    will threshold on."""
    base = textured()
    odo = Odometer(FlowTracker(scale=1.0))
    odo.update(base)
    cur = base
    for _ in range(10):
        cur = shift(cur, 8, 0)
        odo.update(cur)
    assert odo.dx == pytest.approx(80, abs=4)
    assert odo.distance == pytest.approx(80, abs=4)
    assert odo.rejected == 0


def test_displacement_is_the_characters_movement_and_none_until_measured():
    """The ground slid +80 px right, so the character went 80 px LEFT; and
    before any accepted frame the answer is None, never zero."""
    base = textured()
    odo = Odometer(FlowTracker(scale=1.0))
    assert odo.displacement() is None
    odo.update(base)
    assert odo.displacement() is None, "one frame is not a measurement"
    cur = base
    for _ in range(10):
        cur = shift(cur, 8, 0)
        odo.update(cur)
    dx, dy = odo.displacement()
    assert dx == pytest.approx(-80, abs=4)
    assert dy == pytest.approx(0, abs=4)
    assert odo.samples == 10
    odo.reset()
    assert odo.displacement() is None and odo.samples == 0
