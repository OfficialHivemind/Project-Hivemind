"""Ground-plane geometry: screen pixels <-> world studs.

Bee Swarm uses a fixed-pitch follow camera, which means the ground plane maps to
the screen through a single 3x3 homography that can be calibrated once and reused
everywhere. That one matrix is what converts

    "a token at pixel (840, 610)"    into    "12.4 studs forward, 4.1 studs left"

and turns token-chasing from a guess into arithmetic. Without it you are reduced
to fixed movement patterns, which is what every existing macro does.

World frame: +X right, +Z forward, origin at the player's feet, units = studs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml


class NotCalibrated(RuntimeError):
    pass


@dataclass
class GroundPlane:
    H: np.ndarray                 # 3x3 screen -> world
    resolution: tuple[int, int]   # the resolution it was calibrated at
    rms_error: float = 0.0        # studs, over the calibration points

    # ---- construction ----------------------------------------------------
    @classmethod
    def fit(cls, screen_pts, world_pts, resolution) -> "GroundPlane":
        """Fit from >=4 correspondences of (screen px) -> (world studs)."""
        s = np.asarray(screen_pts, np.float32).reshape(-1, 1, 2)
        w = np.asarray(world_pts, np.float32).reshape(-1, 1, 2)
        if len(s) < 4:
            raise ValueError("need at least 4 correspondences")
        H, _ = cv2.findHomography(s, w, cv2.RANSAC, 2.0)
        if H is None:
            raise ValueError("homography fit failed - are the points collinear?")
        gp = cls(H.astype(np.float64), tuple(resolution))
        gp.rms_error = gp._rms(screen_pts, world_pts)
        return gp

    def _rms(self, screen_pts, world_pts) -> float:
        pred = self.to_world_many(screen_pts)
        err = pred - np.asarray(world_pts, np.float64)
        return float(np.sqrt((err ** 2).sum(axis=1).mean()))

    # ---- transforms -------------------------------------------------------
    def to_world_many(self, screen_pts) -> np.ndarray:
        p = np.asarray(screen_pts, np.float32).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(p, self.H).reshape(-1, 2).astype(np.float64)

    def to_world(self, x: float, y: float) -> tuple[float, float]:
        """Screen pixel -> (dx, dz) in studs relative to the player."""
        out = self.to_world_many([(x, y)])[0]
        return float(out[0]), float(out[1])

    def to_screen(self, dx: float, dz: float) -> tuple[float, float]:
        p = np.asarray([(dx, dz)], np.float32).reshape(-1, 1, 2)
        out = cv2.perspectiveTransform(p, np.linalg.inv(self.H)).reshape(2)
        return float(out[0]), float(out[1])

    def bearing(self, x: float, y: float) -> tuple[float, float]:
        """Distance in studs and heading in degrees (0 = forward, +ve = right)."""
        dx, dz = self.to_world(x, y)
        return float(np.hypot(dx, dz)), float(np.degrees(np.arctan2(dx, dz)))

    # ---- persistence ------------------------------------------------------
    def save(self, path: str | Path) -> None:
        Path(path).write_text(yaml.safe_dump({
            "resolution": list(self.resolution),
            "rms_error_studs": round(self.rms_error, 4),
            "H": [[float(v) for v in row] for row in self.H],
        }, sort_keys=False))

    @classmethod
    def load(cls, path: str | Path) -> "GroundPlane":
        p = Path(path)
        if not p.exists():
            raise NotCalibrated(f"no ground-plane calibration at {p}")
        d = yaml.safe_load(p.read_text())
        return cls(np.array(d["H"], np.float64), tuple(d["resolution"]),
                   float(d.get("rms_error_studs", 0.0)))
