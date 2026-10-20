"""Calibrating the ground plane from walking, with no measuring tape.

The homography that turns screen pixels into world studs needs correspondences,
and the obvious way to get them -- stand next to something of known size -- does
not exist in Bee Swarm. There is no ruler in the world and no way to ask the
game where anything is.

So the calibration comes from walking, and it rests on one piece of geometry.

For a pinhole camera at height h, pitch a, focal f, looking at flat ground, a
point at depth Z projects to row y with

    y - y_horizon = f * h / (cos(a) * (h*sin(a) + Z*cos(a)))

Invert that and the mess collapses:

    u(y) = 1 / (y - y_horizon) = (h*sin(a)*cos(a) + Z*cos(a)^2) / (f*h)

which is AFFINE IN DEPTH. Walking forward by D takes every ground point from Z
to Z-D, so

    delta_u = -D * cos(a)^2 / (f*h)

is THE SAME for every tracked point, whatever its depth. That is the whole
trick. It gives two things for free:

  * `y_horizon` is the value that makes delta_u constant across all points, so
    it can be fitted by a 1-D search with no known distances at all
  * once it is fitted, delta_u gives the depth scale in units of D

D itself is still unknown -- nobody told us the walkspeed. It is fixed by
walking a SECOND burst sideways for the same duration. Roblox's WalkSpeed is
isotropic, so strafing for the same time covers the same distance, and the
lateral constraint pins the remaining scale. The unit of the whole system is
then "one calibration burst", which is self-consistent and honest; recorded path
lengths are re-measured into it as the bot walks them.

WHAT THIS DOES NOT GIVE, stated plainly: the depth offset (the world Z of the
player's own feet) is not recoverable from motion alone, because translating the
world does not change how it moves. It is anchored by the row where the player
model meets the ground, which is measured from a frame and passed in. An offset
error shifts absolute distance estimates by a constant; it does not affect
measured DISPLACEMENT, which is what the odometer and the walker actually use.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import GroundPlane

# MEASURED on a real 1920x1080 capture: the player model occupies roughly
# (680,420) 520x580, so its feet meet the ground near this row. Only the depth
# OFFSET depends on it; displacement does not.
DEFAULT_FEET_ROW = 960.0

# Preconditions on the scene, all MEASURED at the hive where calibration kept
# failing (see scene_quality). A blocked forward burst there gave 0.4 px of
# median flow; a working strafe in the same spot gave 12.8 px.
# 30 leaves room for the robust fitter's 3-MAD trimming to reach its own
# floor of 12 points. The live failure had 1001 pairs, so the count was
# never the discriminator there -- the flow was.
MIN_PAIRS = 30
MIN_FLOW_PX = 1.5          # below this the burst did not move the world
MIN_ROW_SPAN = 80.0        # tracked rows must cover some depth range


class UnusableScene(ValueError):
    """The bursts cannot support a calibration, and why.

    Distinct from a bad fit. A bad fit means the model does not describe this
    scene; this means the scene never provided the evidence in the first place,
    and the answer is to move somewhere else rather than to change the model.
    """


@dataclass
class SceneQuality:
    """What the bursts actually contained, before any fitting."""
    pairs: int
    flow_px: float            # median per-point displacement over the burst
    row_span: float           # rows covered by tracked points, in pixels
    usable: bool
    reason: str = ""

    def describe(self) -> str:
        return (f"{self.pairs} pairs, median flow {self.flow_px:.2f} px, "
                f"rows spanning {self.row_span:.0f} px"
                + (f" — {self.reason}" if self.reason else ""))


def scene_quality(pairs: np.ndarray, label: str = "burst") -> SceneQuality:
    """Did this burst contain enough motion and structure to fit anything?

    MEASURED, at the place the live calibration kept failing. The bot spawns on
    the hive platform FACING THE HONEYCOMB WALL, so "w" walks into it: a forward
    burst produced a median flow of 0.4 px while a strafe in the same spot
    produced 12.8 px. There was never any forward translation to fit, and the
    fitter dutifully produced a horizon of -2000 and a residual of 41 instead
    of saying so.

    Checking this first turns a confident wrong answer into an accurate
    complaint, which is the whole difference between "calibration failed" and
    "you are standing against a wall".
    """
    if len(pairs) < MIN_PAIRS:
        return SceneQuality(len(pairs), 0.0, 0.0, False,
                            f"only {len(pairs)} tracked pairs in the {label}")

    delta = pairs[:, 1, :] - pairs[:, 0, :]
    flow = float(np.median(np.linalg.norm(delta, axis=1)))
    rows = pairs[:, 0, 1]
    span = float(np.percentile(rows, 95) - np.percentile(rows, 5))

    if flow < MIN_FLOW_PX:
        return SceneQuality(
            len(pairs), flow, span, False,
            f"the {label} barely moved the scene ({flow:.2f} px, need "
            f"{MIN_FLOW_PX}) — the character is probably against a wall")
    if span < MIN_ROW_SPAN:
        return SceneQuality(
            len(pairs), flow, span, False,
            f"tracked points span only {span:.0f} rows (need {MIN_ROW_SPAN}) "
            "— too little depth range to fit a horizon")
    return SceneQuality(len(pairs), flow, span, True)


@dataclass
class Calibration:
    """The fitted camera model, in units of one calibration burst."""
    horizon_row: float
    depth_scale: float          # dz = depth_scale * u + depth_offset
    depth_offset: float
    lateral_scale: float        # dx = (x - cx) * u * lateral_scale
    centre_x: float
    residual: float             # spread of delta_u after fitting, lower is better
    points: int
    inlier_fraction: float = 1.0   # share of tracked points on the fitted plane

    @property
    def trustworthy(self) -> bool:
        """A tight fit on a small minority of points is a wall, not the ground."""
        return self.residual < 0.25 and self.inlier_fraction >= 0.55

    def to_world(self, x: float, y: float) -> tuple[float, float]:
        u = self._u(y)
        return ((x - self.centre_x) * u * self.lateral_scale,
                self.depth_scale * u + self.depth_offset)

    def _u(self, y: float) -> float:
        gap = y - self.horizon_row
        # A point at or above the horizon is infinitely far away; clamp so the
        # caller gets a very large depth rather than a division by zero or, far
        # worse, a sign flip that puts a distant object BEHIND the player.
        if gap < 1e-3:
            gap = 1e-3
        return 1.0 / gap

    def ground_plane(self, resolution: tuple[int, int],
                     samples: int = 40) -> GroundPlane:
        """Turn the model into the 3x3 homography the rest of nav expects."""
        width, height = resolution
        rng = np.random.default_rng(7)
        # sample across the lower half, where ground is actually visible
        xs = rng.uniform(width * 0.1, width * 0.9, samples)
        ys = rng.uniform(max(self.horizon_row + 20, height * 0.45),
                         height * 0.95, samples)
        screen = np.column_stack([xs, ys])
        world = np.array([self.to_world(x, y) for x, y in screen])
        return GroundPlane.fit(screen, world, resolution)


def fit_horizon_robust(pairs: np.ndarray, rounds: int = 5,
                       keep: float = 3.0) -> tuple[float, float, float]:
    """Fit the horizon while rejecting points that are not on the ground.

    MEASURED need: a live attempt near the hive returned a residual of 2.07 --
    the model failed outright -- because the character had walked into a corner
    facing a fence and a large building. Almost every tracked feature sat on a
    VERTICAL surface, and vertical surfaces do not obey the ground-plane relation
    at all.

    So this trims iteratively: fit, measure each point's delta_u against the
    median, discard those more than `keep` MADs away, refit. That converges on
    whichever plane dominates the scene.

    It returns the INLIER FRACTION alongside the residual, and the caller must
    check it. A tight residual over 8% of the points means the fit found some
    small consistent surface -- a wall, a rooftop -- and calling that the ground
    would be worse than admitting the scene is unusable.
    """
    working = pairs
    horizon, residual = fit_horizon(working)
    for _ in range(rounds):
        if len(working) < 12:
            break
        y0 = working[:, 0, 1].astype(np.float64) - horizon
        y1 = working[:, 1, 1].astype(np.float64) - horizon
        if np.any(y0 < 1e-6) or np.any(y1 < 1e-6):
            break
        delta = 1.0 / y1 - 1.0 / y0
        median = np.median(delta)
        mad = np.median(np.abs(delta - median))
        if mad < 1e-15:
            break                       # already a perfect fit; nothing to trim
        inliers = np.abs(delta - median) <= keep * mad
        if inliers.sum() < 12 or inliers.all():
            break
        working = working[inliers]
        horizon, residual = fit_horizon(working)
    return horizon, residual, len(working) / max(len(pairs), 1)


def fit_horizon(pairs: np.ndarray, low: float = -2000.0,
                high: float | None = None) -> tuple[float, float]:
    """Find the horizon row that makes delta_u constant across tracked points.

    `pairs` is (n, 2, 2): [[x0,y0],[x1,y1]] per point, from a forward walk.
    Returns (horizon_row, residual). Residual is the coefficient of variation of
    delta_u at the optimum -- near zero means the ground-plane model fits.

    Ternary search over a unimodal objective. The objective is the spread of
    delta_u, which is zero at the true horizon and grows either side of it.
    """
    y0 = pairs[:, 0, 1].astype(np.float64)
    y1 = pairs[:, 1, 1].astype(np.float64)
    if high is None:
        # the horizon is above every tracked ground point
        high = float(min(y0.min(), y1.min())) - 1.0

    def spread(horizon: float) -> float:
        g0, g1 = y0 - horizon, y1 - horizon
        if np.any(g0 < 1e-6) or np.any(g1 < 1e-6):
            return float("inf")
        delta = 1.0 / g1 - 1.0 / g0
        mean = float(np.mean(delta))
        if abs(mean) < 1e-12:
            return float("inf")
        return float(np.std(delta) / abs(mean))

    lo, hi = low, high
    for _ in range(200):
        a = lo + (hi - lo) / 3.0
        b = hi - (hi - lo) / 3.0
        if spread(a) < spread(b):
            hi = b
        else:
            lo = a
    horizon = (lo + hi) / 2.0
    return horizon, spread(horizon)


def calibrate(forward: np.ndarray, strafe: np.ndarray,
              resolution: tuple[int, int],
              burst_distance: float = 1.0,
              feet_row: float = DEFAULT_FEET_ROW,
              centre_x: float | None = None) -> Calibration:
    """Fit the ground model from one forward burst and one strafe burst.

    `burst_distance` sets the unit. Leave it at 1.0 and distances come out in
    "bursts"; pass a real stud count if one is ever established.
    """
    width, _height = resolution
    cx = width / 2.0 if centre_x is None else centre_x

    # Refuse before fitting, so an unusable scene is reported as an unusable
    # scene rather than as a nonsense horizon. See scene_quality().
    for burst, label in ((forward, "forward burst"), (strafe, "strafe burst")):
        quality = scene_quality(burst, label)
        if not quality.usable:
            raise UnusableScene(quality.reason)

    horizon, residual, inlier_fraction = fit_horizon_robust(forward)

    u0 = 1.0 / (forward[:, 0, 1].astype(np.float64) - horizon)
    u1 = 1.0 / (forward[:, 1, 1].astype(np.float64) - horizon)
    delta_u = float(np.median(u1 - u0))
    if abs(delta_u) < 1e-12:
        raise ValueError("forward burst produced no depth change — did it move?")
    # dz = depth_scale * u + offset, and walking forward reduces dz by D
    depth_scale = -burst_distance / delta_u

    # The strafe burst pins the lateral scale: dx = (x - cx) * u * K, and the
    # burst moved the world sideways by exactly one burst_distance.
    sx0 = strafe[:, 0, 0].astype(np.float64)
    sx1 = strafe[:, 1, 0].astype(np.float64)
    su0 = 1.0 / (strafe[:, 0, 1].astype(np.float64) - horizon)
    su1 = 1.0 / (strafe[:, 1, 1].astype(np.float64) - horizon)
    lateral_delta = ((sx1 - cx) * su1) - ((sx0 - cx) * su0)
    median_lateral = float(np.median(lateral_delta))
    if abs(median_lateral) < 1e-12:
        raise ValueError("strafe burst produced no lateral change — did it move?")
    lateral_scale = burst_distance / median_lateral

    # Anchor the depth offset so the player's own feet sit at dz = 0.
    depth_offset = -depth_scale * (1.0 / max(feet_row - horizon, 1e-3))

    return Calibration(horizon_row=horizon, depth_scale=depth_scale,
                       depth_offset=depth_offset,
                       lateral_scale=abs(lateral_scale), centre_x=cx,
                       residual=residual, points=len(forward),
                       inlier_fraction=inlier_fraction)
