"""Ground-plane homography tests against a synthetic pinhole camera.

We build a camera with known height and pitch, project ground points through it,
then check the fitted homography inverts that projection. Crucially the accuracy
check uses points that were NOT part of the fit -- a homography can always fit its
own calibration points, so only held-out points prove it generalises.
"""
import numpy as np
import pytest

from hivemind.nav.geometry import GroundPlane, NotCalibrated

W, H_PX = 1920, 1080
FOCAL = 1200.0
CAM_HEIGHT = 12.0          # studs above the ground
PITCH = np.radians(28.0)   # looking down


def project(X, Z):
    """Ground point (X, 0, Z) in studs -> screen pixel, via a pinhole camera."""
    # OpenCV camera frame: +X right, +Y DOWN, +Z forward. The ground is below
    # the camera, so it sits at +Y.
    rel = np.array([X, CAM_HEIGHT, Z], float)
    c, s = np.cos(PITCH), np.sin(PITCH)
    R = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    pc = R @ rel
    if pc[2] <= 0.1:
        raise ValueError("behind the camera")
    return (FOCAL * pc[0] / pc[2] + W / 2, FOCAL * pc[1] / pc[2] + H_PX / 2)


CALIB = [(-14, 22), (14, 22), (-9, 46), (9, 46), (0, 32), (-20, 60), (20, 60)]
HELDOUT = [(0, 27), (-6, 38), (11, 52), (4, 41), (-16, 30)]


@pytest.fixture(scope="module")
def plane():
    world = CALIB
    screen = [project(x, z) for x, z in world]
    return GroundPlane.fit(screen, world, (W, H_PX))


def test_fit_is_tight(plane):
    assert plane.rms_error < 0.05, f"rms {plane.rms_error} studs on calibration points"


@pytest.mark.parametrize("X,Z", HELDOUT)
def test_held_out_points_recover(plane, X, Z):
    """The real test: points the fit never saw."""
    sx, sy = project(X, Z)
    dx, dz = plane.to_world(sx, sy)
    assert dx == pytest.approx(X, abs=0.25)
    assert dz == pytest.approx(Z, abs=0.25)


def test_round_trip_world_screen_world(plane):
    for X, Z in HELDOUT:
        sx, sy = plane.to_screen(X, Z)
        dx, dz = plane.to_world(sx, sy)
        assert (dx, dz) == pytest.approx((X, Z), abs=0.05)


def test_bearing_directions(plane):
    """Sanity on the sign convention: +heading is to the right."""
    dist, head = plane.bearing(*project(0, 30))
    assert dist == pytest.approx(30, abs=0.3) and abs(head) < 1.0

    _, right = plane.bearing(*project(15, 30))
    _, left = plane.bearing(*project(-15, 30))
    assert right > 5 and left < -5
    assert right == pytest.approx(-left, abs=1.0)


def test_further_objects_are_higher_on_screen(plane):
    """Guards against a flipped axis, which would send the bot backwards."""
    near_y = project(0, 20)[1]
    far_y = project(0, 60)[1]
    assert far_y < near_y


def test_save_load_round_trip(plane, tmp_path):
    p = tmp_path / "homography.yaml"
    plane.save(p)
    back = GroundPlane.load(p)
    assert back.resolution == plane.resolution
    for X, Z in HELDOUT:
        assert back.to_world(*project(X, Z)) == pytest.approx(plane.to_world(*project(X, Z)), abs=1e-6)


def test_missing_calibration_is_explicit(tmp_path):
    with pytest.raises(NotCalibrated):
        GroundPlane.load(tmp_path / "nope.yaml")


def test_too_few_points_rejected():
    with pytest.raises(ValueError):
        GroundPlane.fit([(0, 0), (1, 1), (2, 2)], [(0, 0), (1, 1), (2, 2)], (W, H_PX))
