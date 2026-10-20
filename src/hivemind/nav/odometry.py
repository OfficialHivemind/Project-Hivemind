"""World-space odometry: how many STUDS did we move?

Naively you would take the median pixel displacement from optical flow and
multiply by a pixels-per-stud constant. That is wrong under perspective: a patch
of ground 10 studs away slides across many more pixels than one 50 studs away,
for exactly the same player movement. A single scale factor is only valid for a
single depth.

So we reproject *every* tracked point through the ground-plane homography and
take the median of the resulting WORLD displacements. Perspective is handled
exactly, features at any depth contribute correctly, and the median still throws
out bees, other players and anything else moving under its own power.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..vision.flow import FlowSample, FlowTracker
from .geometry import GroundPlane


@dataclass(frozen=True)
class WorldStep:
    dx: float          # studs, +right
    dz: float          # studs, +forward
    tracked: int
    spread: float      # median abs deviation in studs; high = untrustworthy
    ok: bool

    @property
    def distance(self) -> float:
        return float(np.hypot(self.dx, self.dz))


class WorldOdometer:
    """Accumulates measured world displacement. Reset before each leg."""

    def __init__(self, plane: GroundPlane, tracker: FlowTracker | None = None,
                 max_spread_studs: float = 1.5, min_tracked: int = 8):
        self.plane = plane
        self.tracker = tracker or FlowTracker()
        self.max_spread = max_spread_studs
        self.min_tracked = min_tracked
        self.reset()

    def reset(self) -> None:
        self.tracker.reset()
        self.dx = 0.0
        self.dz = 0.0
        self.path_length = 0.0      # integrated, not straight-line
        self.rejected = 0
        self.last: WorldStep | None = None

    def _to_world_step(self, s: FlowSample) -> WorldStep:
        if not s.ok or s.pairs is None or len(s.pairs) < self.min_tracked:
            return WorldStep(0.0, 0.0, s.tracked, 0.0, False)

        w0 = self.plane.to_world_many(s.pairs[:, 0, :])
        w1 = self.plane.to_world_many(s.pairs[:, 1, :])
        d = w1 - w0

        # Scene moves opposite to the player: ground sliding backwards past the
        # camera means we advanced.
        d = -d

        med = np.median(d, axis=0)
        # Median of the per-point EUCLIDEAN deviation -- NOT a median over the
        # flattened (N,2) array, which pools the dx and dz deviations into one
        # 2N sample. Pooled, whenever one axis agrees (the normal case for a
        # straight walk, where every ground point agrees dx~0) those N
        # near-zero values fill the lower half and drag the median to ~0
        # however badly the other axis disagrees. This is the only trust gate
        # the navigation stack enables by default -- the pixel gate in
        # FlowTracker defaults to None -- so blind here means fabricated
        # distance reaching walk_studs() unchallenged.
        spread = float(np.median(np.linalg.norm(d - med, axis=1)))
        return WorldStep(float(med[0]), float(med[1]), len(d), spread,
                         spread <= self.max_spread)

    def update(self, frame: np.ndarray) -> WorldStep | None:
        s = self.tracker.update(frame)
        if s is None:
            return None
        step = self._to_world_step(s)
        self.last = step
        if step.ok:
            self.dx += step.dx
            self.dz += step.dz
            self.path_length += step.distance
        else:
            self.rejected += 1
        return step

    @property
    def displacement(self) -> float:
        """Straight-line studs from the starting point."""
        return float(np.hypot(self.dx, self.dz))
