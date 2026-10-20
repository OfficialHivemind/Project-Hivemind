"""A fake Bee Swarm world you can walk around in.

Its job is to let the control loop be tested without the game: key presses move
a player, a camera renders the ground, and the same vision code runs against the
result. That makes the closed loop testable in milliseconds instead of requiring
someone to be logged in, and it is the only sane way to debug behaviour that
plays out over hours.

It also lets us reproduce the exact conditions that break open-loop macros --
haste procs, lag spikes, walls -- on demand and deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

KEY_VECTORS = {"w": (0.0, 1.0), "s": (0.0, -1.0), "a": (-1.0, 0.0), "d": (1.0, 0.0)}


@dataclass
class Camera:
    width: int = 1280
    height: int = 720
    focal: float = 800.0
    cam_height: float = 12.0
    pitch_deg: float = 28.0

    def project(self, world: np.ndarray, px: float, pz: float,
                yaw_deg: float = 0.0):
        """World (x, z) -> screen (x, y), plus a visibility mask.

        `yaw_deg` turns the camera about the vertical axis. It defaults to 0
        because the calibration derivation assumes pure translation -- and it
        exists because the Roblox camera does NOT hold still: it swings to
        follow the character, which is the leading explanation for the
        calibration failing in game while being exact here.
        """
        rel = np.column_stack([world[:, 0] - px,
                               np.full(len(world), self.cam_height),
                               world[:, 1] - pz])
        a = np.radians(self.pitch_deg)
        c, s = np.cos(a), np.sin(a)
        rotation = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
        if yaw_deg:
            y = np.radians(-yaw_deg)          # rotate the world against the camera
            cy, sy = np.cos(y), np.sin(y)
            rotation = rotation @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        pc = rel @ rotation.T
        vis = pc[:, 2] > 1.0
        x = self.focal * pc[:, 0] / np.where(vis, pc[:, 2], 1) + self.width / 2
        y = self.focal * pc[:, 1] / np.where(vis, pc[:, 2], 1) + self.height / 2
        return np.column_stack([x, y]), vis


@dataclass
class KinematicSim:
    camera: Camera = field(default_factory=Camera)
    walkspeed: float = 28.0          # studs/second
    dt: float = 0.1                  # seconds per tick (10 Hz capture)
    x: float = 0.0
    z: float = 0.0
    seed: int = 11
    wall_at_z: float | None = None   # blocks forward travel past this z
    tokens: list[tuple[float, float]] = field(default_factory=list)
    _held: set = field(default_factory=set)
    time: float = 0.0

    def __post_init__(self):
        rng = np.random.default_rng(self.seed)
        # fixed ground detail, in world coordinates
        self._texture = np.column_stack([rng.uniform(-90, 90, 1800),
                                         rng.uniform(-40, 200, 1800)])
        self._shades = rng.integers(70, 255, len(self._texture))
        self._rng = rng

    # ---- the input surface the walker drives ------------------------------
    def press(self, *keys: str) -> None:
        self._held.update(k.lower() for k in keys)

    def release(self, *keys: str) -> None:
        for k in keys:
            self._held.discard(k.lower())

    # ---- physics -----------------------------------------------------------
    def step(self) -> None:
        vx = vz = 0.0
        for k in self._held:
            if k in KEY_VECTORS:
                dx, dz = KEY_VECTORS[k]
                vx += dx; vz += dz
        n = np.hypot(vx, vz)
        if n > 0:
            vx, vz = vx / n, vz / n          # diagonals are not faster
            nz = self.z + vz * self.walkspeed * self.dt
            if self.wall_at_z is not None and nz > self.wall_at_z:
                nz = self.wall_at_z          # blocked
            self.z = nz
            self.x += vx * self.walkspeed * self.dt
        self.time += self.dt

    # ---- rendering ---------------------------------------------------------
    def render(self) -> np.ndarray:
        img = np.full((self.camera.height, self.camera.width, 3), (58, 104, 68), np.uint8)
        img += self._rng.integers(0, 10, img.shape, dtype=np.uint8)
        pts, vis = self.camera.project(self._texture, self.x, self.z)
        for (sx, sy), shade, ok in zip(pts, self._shades, vis):
            if ok and 0 <= sx < self.camera.width and 0 <= sy < self.camera.height:
                r = max(1, int(1 + (sy - self.camera.height / 2) / 120))
                cv2.circle(img, (int(sx), int(sy)), r, (int(shade),) * 3, -1)
        if self.tokens:
            tp, tv = self.camera.project(np.array(self.tokens, float), self.x, self.z)
            for (sx, sy), ok in zip(tp, tv):
                if ok and 0 <= sx < self.camera.width and 0 <= sy < self.camera.height:
                    cv2.circle(img, (int(sx), int(sy)), 13, (40, 215, 245), -1)
        return img

    def frame(self) -> np.ndarray:
        """Advance one tick and render -- the callable the walker polls."""
        self.step()
        return self.render()

    @property
    def travelled(self) -> float:
        return float(np.hypot(self.x, self.z))
