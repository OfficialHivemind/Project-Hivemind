#!/usr/bin/env python3
"""Does camera YAW explain the in-game calibration failure?

The ground-plane derivation assumes walking translates the camera without
rotating it. In game the camera follows the character, so if it swings while
the character moves, the flow field carries a rotational component and
`delta_u` is no longer constant across tracked points.

The live symptom to reproduce:

    attempt 0: horizon y=  -626  residual=4.8800  inliers=21%
    attempt 3: horizon y=  -345  residual=4.7805  inliers=41%

A horizon fitted far above the frame, a residual two orders of magnitude over
the 0.25 threshold, and a minority of inliers -- while the SAME code recovers
the horizon to 0.000 px with no yaw at all.

This sweeps yaw per burst and reports what the fit does. No game required.
"""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.nav.calibrate import calibrate, fit_horizon_robust  # noqa: E402
from hivemind.sim.kinematic import Camera                          # noqa: E402

WIDTH, HEIGHT = 1920, 1080
BURST = 7.0


def make_bursts(cam, yaw_deg, seed=3, n=600):
    """One forward burst and one strafe burst, each with `yaw_deg` of swing."""
    rng = np.random.default_rng(seed)
    world = np.column_stack([rng.uniform(-60, 60, n), rng.uniform(5, 120, n)])

    def one(dx, dz):
        p0, v0 = cam.project(world, 0.0, 0.0, yaw_deg=0.0)
        p1, v1 = cam.project(world, dx, dz, yaw_deg=yaw_deg)
        ok = (v0 & v1
              & (p0[:, 1] > HEIGHT * 0.45) & (p0[:, 1] < HEIGHT * 0.98)
              & (p1[:, 1] > HEIGHT * 0.45) & (p1[:, 1] < HEIGHT * 0.98)
              & (p0[:, 0] > 0) & (p0[:, 0] < WIDTH)
              & (p1[:, 0] > 0) & (p1[:, 0] < WIDTH))
        return np.stack([p0[ok], p1[ok]], axis=1)

    return one(0.0, BURST), one(BURST, 0.0)


def main() -> int:
    cam = Camera(width=WIDTH, height=HEIGHT, focal=900.0,
                 cam_height=12.0, pitch_deg=28.0)
    true_horizon = HEIGHT / 2 - 900.0 * np.tan(np.radians(28.0))

    print(f"\n  true horizon row: {true_horizon:.1f}")
    print("\n  yaw/burst   horizon    residual  inliers  trustworthy   "
          "median dx   dy depends on x?")
    print("  " + "-" * 92)

    for yaw in (0.0, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0):
        forward, strafe = make_bursts(cam, yaw)
        horizon, residual, inliers = fit_horizon_robust(forward)
        try:
            cal = calibrate(forward, strafe, (WIDTH, HEIGHT), burst_distance=1.0)
            trusted = "yes" if cal.trustworthy else "NO"
        except ValueError:
            trusted = "error"

        # the two cheap live diagnostics, measured here where truth is known
        dx = forward[:, 1, 0] - forward[:, 0, 0]
        dy = forward[:, 1, 1] - forward[:, 0, 1]
        median_dx = float(np.median(dx))
        # does dy at a given row depend on x? correlate dy against x within a
        # narrow band of rows, where pure translation predicts no dependence
        rows = forward[:, 0, 1]
        band = (rows > np.percentile(rows, 40)) & (rows < np.percentile(rows, 60))
        if band.sum() > 10:
            xs = forward[band, 0, 0]
            corr = float(np.corrcoef(xs, dy[band])[0, 1])
        else:
            corr = float("nan")

        print(f"  {yaw:6.2f}   {horizon:9.0f}  {residual:9.4f}  {inliers:6.0%}"
              f"  {trusted:>11}  {median_dx:9.2f}  {corr:15.3f}")

    print("\n  Reference, measured in game: residual 4.78-10.61, inliers 16-41%,")
    print("  horizon -16 to -1246 for a frame whose true horizon is ~62.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
