"""Ground-plane calibration from walking.

There is no ruler in Bee Swarm, so the homography has to come out of motion
alone. The geometry that makes that possible: for a pinhole camera over flat
ground, 1/(y - y_horizon) is AFFINE IN DEPTH, so walking forward changes it by
the same amount for every tracked point whatever its depth.

These tests check it against the synthetic camera, where the truth is known
exactly. The headline assertion is that the recovered world coordinates match
ground truth to floating-point precision -- if the derivation were wrong, the
error would be structural and obvious rather than small.
"""
import math

import numpy as np
import pytest

from hivemind.nav.calibrate import (Calibration, UnusableScene, calibrate,
                                    fit_horizon, scene_quality)
from hivemind.sim.kinematic import Camera

WIDTH, HEIGHT = 1920, 1080
BURST = 7.0


def make_camera(pitch=28.0, focal=900.0, height=12.0):
    return Camera(width=WIDTH, height=HEIGHT, focal=focal,
                  cam_height=height, pitch_deg=pitch)


def truth_horizon(cam):
    return cam.height / 2 - cam.focal * math.tan(math.radians(cam.pitch_deg))


def truth_zero_depth_row(cam):
    """The row at which world depth is zero, from the projection identity."""
    a = math.radians(cam.pitch_deg)
    s, c = math.sin(a), math.cos(a)
    return truth_horizon(cam) + cam.focal * cam.cam_height / (c * cam.cam_height * s)


def bursts(cam, seed=3, n=600):
    rng = np.random.default_rng(seed)
    world = np.column_stack([rng.uniform(-60, 60, n), rng.uniform(5, 120, n)])

    def one(dx, dz):
        p0, v0 = cam.project(world, 0.0, 0.0)
        p1, v1 = cam.project(world, dx, dz)
        ok = (v0 & v1
              & (p0[:, 1] > cam.height * 0.45) & (p0[:, 1] < cam.height * 0.98)
              & (p1[:, 1] > cam.height * 0.45) & (p1[:, 1] < cam.height * 0.98))
        return np.stack([p0[ok], p1[ok]], axis=1)

    return one(0.0, BURST), one(BURST, 0.0), world


# ---- the horizon ---------------------------------------------------------

@pytest.mark.parametrize("pitch", [18.0, 28.0, 40.0])
def test_horizon_is_recovered_exactly(pitch):
    cam = make_camera(pitch=pitch)
    forward, _, _ = bursts(cam)
    found, residual = fit_horizon(forward)
    assert found == pytest.approx(truth_horizon(cam), abs=0.05)
    assert residual < 1e-6, "delta_u should be constant at the true horizon"


def test_the_residual_reports_a_bad_fit():
    """Scrambled pairs do not obey the ground-plane model."""
    cam = make_camera()
    forward, _, _ = bursts(cam)
    rng = np.random.default_rng(1)
    noisy = forward.copy()
    noisy[:, 1, 1] += rng.uniform(-80, 80, len(noisy))
    _, residual = fit_horizon(noisy)
    assert residual > 1e-3


# ---- full calibration ----------------------------------------------------

def test_world_coordinates_are_recovered_to_machine_precision():
    cam = make_camera()
    forward, strafe, world = bursts(cam)
    cal = calibrate(forward, strafe, (WIDTH, HEIGHT), burst_distance=BURST,
                    feet_row=truth_zero_depth_row(cam))

    screen, vis = cam.project(world, 0.0, 0.0)
    sel = (vis & (screen[:, 1] > cam.height * 0.5)
           & (screen[:, 1] < cam.height * 0.95)
           & (screen[:, 0] > 100) & (screen[:, 0] < WIDTH - 100))
    assert sel.sum() >= 10

    for (sx, sy), (wx, wz) in zip(screen[sel], world[sel]):
        ex, ez = cal.to_world(sx, sy)
        assert ex == pytest.approx(wx, abs=1e-4)
        assert ez == pytest.approx(wz, abs=1e-4)


def test_a_wrong_anchor_shifts_depth_by_a_CONSTANT_only():
    """Motion cannot recover the offset, and that limit must behave predictably.

    A constant shift is tolerable (displacement is unaffected); a varying error
    would mean the model itself is wrong.
    """
    cam = make_camera()
    forward, strafe, world = bursts(cam)
    cal = calibrate(forward, strafe, (WIDTH, HEIGHT), burst_distance=BURST,
                    feet_row=truth_zero_depth_row(cam) + 300)

    screen, vis = cam.project(world, 0.0, 0.0)
    sel = vis & (screen[:, 1] > cam.height * 0.5) & (screen[:, 1] < cam.height * 0.95)
    errors = [cal.to_world(sx, sy)[1] - wz
              for (sx, sy), (wx, wz) in zip(screen[sel], world[sel])]
    assert np.std(errors) < 1e-4, "the offset error must be constant"


def test_displacement_is_correct_even_with_a_wrong_anchor():
    """Which is why the walker and odometer are unaffected by the offset."""
    cam = make_camera()
    forward, strafe, world = bursts(cam)
    cal = calibrate(forward, strafe, (WIDTH, HEIGHT), burst_distance=BURST,
                    feet_row=truth_zero_depth_row(cam) + 500)
    p0, v0 = cam.project(world, 0.0, 0.0)
    p1, v1 = cam.project(world, 0.0, BURST)
    ok = v0 & v1 & (p0[:, 1] > cam.height * 0.5) & (p1[:, 1] > cam.height * 0.5)
    moves = [cal.to_world(*a)[1] - cal.to_world(*b)[1]
             for a, b in zip(p0[ok], p1[ok])]
    assert np.median(moves) == pytest.approx(BURST, abs=1e-3)


@pytest.mark.parametrize("pitch,focal,height", [
    (18.0, 700.0, 9.0), (28.0, 900.0, 12.0), (40.0, 1100.0, 16.0)])
def test_it_works_across_camera_configurations(pitch, focal, height):
    cam = make_camera(pitch=pitch, focal=focal, height=height)
    forward, strafe, world = bursts(cam)
    cal = calibrate(forward, strafe, (WIDTH, HEIGHT), burst_distance=BURST,
                    feet_row=truth_zero_depth_row(cam))
    screen, vis = cam.project(world, 0.0, 0.0)
    sel = vis & (screen[:, 1] > cam.height * 0.55) & (screen[:, 1] < cam.height * 0.95)
    for (sx, sy), (wx, wz) in zip(screen[sel][:40], world[sel][:40]):
        assert cal.to_world(sx, sy)[1] == pytest.approx(wz, abs=1e-3)


def test_the_homography_it_produces_fits_its_own_model():
    cam = make_camera()
    forward, strafe, _ = bursts(cam)
    cal = calibrate(forward, strafe, (WIDTH, HEIGHT), burst_distance=BURST)
    plane = cal.ground_plane((WIDTH, HEIGHT))
    assert plane.rms_error < 0.01


# ---- degenerate input ----------------------------------------------------

def test_a_burst_that_did_not_move_is_rejected():
    cam = make_camera()
    forward, strafe, _ = bursts(cam)
    still = np.stack([forward[:, 0, :], forward[:, 0, :]], axis=1)
    with pytest.raises(ValueError, match="forward"):
        calibrate(still, strafe, (WIDTH, HEIGHT))


def test_a_strafe_that_did_not_move_is_rejected():
    cam = make_camera()
    forward, strafe, _ = bursts(cam)
    still = np.stack([strafe[:, 0, :], strafe[:, 0, :]], axis=1)
    with pytest.raises(ValueError, match="strafe"):
        calibrate(forward, still, (WIDTH, HEIGHT))


def test_a_point_on_the_horizon_does_not_divide_by_zero():
    cal = Calibration(horizon_row=100.0, depth_scale=1000.0, depth_offset=0.0,
                      lateral_scale=1.0, centre_x=960.0, residual=0.0, points=0)
    dx, dz = cal.to_world(960.0, 100.0)
    assert math.isfinite(dx) and math.isfinite(dz)


def test_a_point_ABOVE_the_horizon_is_not_reported_as_behind_you():
    """A sign flip there would send the bot walking backwards at a sky pixel."""
    cal = Calibration(horizon_row=400.0, depth_scale=1000.0, depth_offset=0.0,
                      lateral_scale=1.0, centre_x=960.0, residual=0.0, points=0)
    assert cal.to_world(960.0, 50.0)[1] > 0


# ---- robustness to a cluttered scene -------------------------------------

def polluted(cam, wall_fraction=0.45, seed=5):
    """Half the tracked points on a VERTICAL surface, which is the live failure.

    A calibration attempt near the hive returned residual 2.07 because the
    character was in a corner facing a fence and a building, so most features
    were on walls. Walls do not obey the ground-plane relation at all.
    """
    forward, strafe, world = bursts(cam)
    rng = np.random.default_rng(seed)
    wall = forward[: int(len(forward) * wall_fraction)].copy()
    wall[:, 1, 1] = wall[:, 0, 1] + rng.uniform(-1, 1, len(wall))
    return np.concatenate([forward, wall]), strafe, world


def test_robust_fitting_recovers_the_horizon_through_wall_clutter():
    from hivemind.nav.calibrate import fit_horizon_robust
    cam = make_camera()
    forward, _, _ = polluted(cam)
    horizon, residual, inliers = fit_horizon_robust(forward)
    assert horizon == pytest.approx(truth_horizon(cam), abs=0.5)
    assert residual < 1e-3
    assert 0.4 < inliers < 1.0, "it should reject the wall, not everything"


def test_the_naive_fit_is_measurably_worse_on_the_same_scene():
    """Documents why the robust version exists."""
    from hivemind.nav.calibrate import fit_horizon, fit_horizon_robust
    cam = make_camera()
    forward, _, _ = polluted(cam)
    _, naive_residual = fit_horizon(forward)
    _, robust_residual, _ = fit_horizon_robust(forward)
    assert robust_residual < naive_residual / 10


def test_a_tight_fit_on_a_tiny_minority_is_not_trusted():
    """A wall fitted perfectly is still not the ground."""
    from hivemind.nav.calibrate import Calibration
    cal = Calibration(horizon_row=0, depth_scale=1, depth_offset=0,
                      lateral_scale=1, centre_x=960, residual=0.001,
                      points=500, inlier_fraction=0.08)
    assert cal.trustworthy is False


def test_a_good_fit_on_most_points_is_trusted():
    from hivemind.nav.calibrate import Calibration
    cal = Calibration(horizon_row=0, depth_scale=1, depth_offset=0,
                      lateral_scale=1, centre_x=960, residual=0.01,
                      points=500, inlier_fraction=0.8)
    assert cal.trustworthy is True


def test_a_loose_fit_is_not_trusted_however_many_points_agree():
    from hivemind.nav.calibrate import Calibration
    cal = Calibration(horizon_row=0, depth_scale=1, depth_offset=0,
                      lateral_scale=1, centre_x=960, residual=2.07,
                      points=1398, inlier_fraction=1.0)
    assert cal.trustworthy is False


def test_calibration_still_exact_on_a_clean_scene_after_trimming():
    cam = make_camera()
    forward, strafe, world = bursts(cam)
    cal = calibrate(forward, strafe, (WIDTH, HEIGHT), burst_distance=BURST,
                    feet_row=truth_zero_depth_row(cam))
    assert cal.inlier_fraction == 1.0
    screen, vis = cam.project(world, 0.0, 0.0)
    sel = vis & (screen[:, 1] > cam.height * 0.55) & (screen[:, 1] < cam.height * 0.95)
    for (sx, sy), (wx, wz) in zip(screen[sel][:30], world[sel][:30]):
        assert cal.to_world(sx, sy)[1] == pytest.approx(wz, abs=1e-3)


# --- the scene has to contain the evidence before anything is fitted --------
# MEASURED in game: the bot spawns on the hive platform facing the honeycomb
# wall, so "w" is blocked. Median flow per frame was w 0.22 px, s 4.51, a 10.88,
# d 9.78 -- forward blocked by 20-50x. The fitter was handed a burst with no
# translation in it and produced a horizon of -2000 rather than an objection.

def test_a_blocked_burst_is_reported_as_a_blocked_burst(camera=None):
    cam = make_camera()
    forward, strafe, _ = bursts(cam)
    # a burst that did not move: start and end identical
    stuck = np.stack([forward[:, 0, :], forward[:, 0, :]], axis=1)
    quality = scene_quality(stuck, "forward burst")
    assert not quality.usable
    assert "against a wall" in quality.reason
    with pytest.raises(UnusableScene, match="against a wall"):
        calibrate(stuck, strafe, (WIDTH, HEIGHT))


def test_a_good_scene_is_reported_usable():
    cam = make_camera()
    forward, strafe, _ = bursts(cam)
    for burst in (forward, strafe):
        quality = scene_quality(burst)
        assert quality.usable, quality.describe()
        assert quality.flow_px > 1.5


def test_too_few_tracked_points_is_reported():
    quality = scene_quality(np.zeros((5, 2, 2)), "forward burst")
    assert not quality.usable
    assert "5 tracked pairs" in quality.reason


# --- walking BACKWARD is a usable depth burst too ---------------------------
# Which matters because forward is exactly the direction that is blocked at
# spawn. Backward is still pure translation along the view axis; only the sign
# of delta_u flips, so a burst_distance of -1 recovers the same model.

def test_a_backward_burst_calibrates_with_a_negative_burst_distance():
    cam = make_camera()
    rng = np.random.default_rng(5)
    world = np.column_stack([rng.uniform(-60, 60, 600), rng.uniform(5, 120, 600)])

    def one(dx, dz):
        p0, v0 = cam.project(world, 0.0, 0.0)
        p1, v1 = cam.project(world, dx, dz)
        ok = (v0 & v1
              & (p0[:, 1] > HEIGHT * 0.45) & (p0[:, 1] < HEIGHT * 0.98)
              & (p1[:, 1] > HEIGHT * 0.45) & (p1[:, 1] < HEIGHT * 0.98))
        return np.stack([p0[ok], p1[ok]], axis=1)

    backward = one(0.0, -BURST)            # walked AWAY from the scene
    strafe = one(BURST, 0.0)

    cal = calibrate(backward, strafe, (WIDTH, HEIGHT), burst_distance=-1.0)
    assert cal.trustworthy, cal
    assert cal.horizon_row == pytest.approx(truth_horizon(cam), abs=0.5)
    assert cal.depth_scale > 0, "depth must still increase away from the camera"
