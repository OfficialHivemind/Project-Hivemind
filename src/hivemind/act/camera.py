"""Where the camera points: one count of the zoom, pitch and yaw taps sent.

Every look helper that changes the view does its own taps and its own undo
(the gather view in brain/farm, the hive and jelly looks, the MTS survey, the
egg hatch, the planter seek, the Stump Snail tilt -- docs/pending/camera.md).
This is the one place that counts them, so a pose can be asked for and put
back: `with camera.looking(Pose(zoom=3)): ...` zooms out three taps and zooms
back in on every way out of the block.

THE TAPS, AND WHAT EACH IS MEASURED TO DO (1920x1080, Sober):

    yaw    period +1 (right), comma -1 (left). 45 degrees a tap, 8 taps a
           full turn: MEASURED by closure, scripts/diag_camera.py (DESIGN 8a:
           similarity to the spawn view 0.777 at 8 taps, 0.343 at 4, 0.339 at
           12, ~0 elsewhere). Counted in world/bearings `heading_taps`, which
           the walks already square up by; this module reads and feeds it
           rather than keep a second count.
    pitch  pageup +1, pagedown -1. PageUp raises the camera so it looks DOWN
           (the hive leaves the top of the screen), PageDown lowers it so it
           looks up: MEASURED on the hive look's frames, 2026-10-03 06:21
           (scripts/run_farm.py EGG_PREVIEW_TILT). From the spawn pitch two
           PageDown "put the camera in the floor" (same frames), so the low
           end is at most 2 taps down. Degrees a tap: NOT MEASURED.
    zoom   o +1 (out), i -1 (in). One tap out already shows the empty hive
           cell from the pad and six show the whole hive (MEASURED,
           vision/hivecell, var/shoplook/20261005-223751-hatch-before-z6.jpg).
           Degrees/studs a tap: NOT MEASURED. Past the far limit an `o` does
           nothing while its `i` still zooms in (brain/farm GATHER_ZOOM_MOST,
           from Natro's ceiling of 8, not measured here) -- so a count is only
           exact inside the limits, which is why callers stay well inside them.

AFTER A RESPAWN OR A REJOIN. Both are already detected and told to the compass
(`Bearings.spawned`: the join, a death on a walk, a death in a gather, the
respawn itself); this module watches its `spawns` count, so no caller has to
tell it twice.
  * yaw goes back to spawn heading. MEASURED: scripts/diag_reset_state.py,
    two views after a respawn 0.991 similar after the camera was turned 3 taps
    between them (DESIGN 8a "A respawn DOES restore the camera").
  * zoom and pitch are KEPT across a respawn. ASSUMED -- the codebase already
    plays by it (act/bugrun: a zoom-out would change the thresholds "for the
    rest of the session"; DESIGN 8ap: a trip that dies mid-gather "leaves the
    camera tilted"; brain/farm undoes its view before every respawn), and one
    frame pair is consistent with it: the gather died zoomed out 1 tap at
    2026-10-22 16:14:23 (run-1188), its `i` was still sent, and the next walk
    started at the usual zoom (var/routes/attempt-1188/161614-survey_walk-00-
    start.jpg against attempt-1204/212958). A respawn that reset the zoom
    would have left it one tap closer. The live check is in docs/pending/camera.md.
  * a rejoin is a new process (watchdog), and a new Camera starts at HOME: the
    zoom and pitch the session joined with (ASSUMED a fresh join resets them,
    as brain/farm's gather view says).

Nothing here decides to move the camera; it sends exactly the taps a caller
asks for, so moving a caller onto it changes no key it sends.
"""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import Callable

from ..world.bearings import TAPS_PER_FULL_TURN, Bearings
from .routes import CAMERA_GAP, CAMERA_KEYS

# The spacing between zoom taps, as `forage.unblind` measured it working (it
# was brain/farm GATHER_ZOOM_GAP_S).
ZOOM_GAP_S = 0.15
# Each axis: the key for +1, the key for -1, and the pause after each tap.
# The tilt and turn keys keep the route runner's CAMERA_GAP.
AXES = {
    "yaw": (CAMERA_KEYS["right"], CAMERA_KEYS["left"], CAMERA_GAP),
    "pitch": (CAMERA_KEYS["up"], CAMERA_KEYS["down"], CAMERA_GAP),
    "zoom": ("o", "i", ZOOM_GAP_S),
}
# The order a pose is set in: the view's tilt and distance first, the turn
# last (brain/farm's gather view: PageUp, then the `o` taps).
ORDER = ("pitch", "zoom", "yaw")


@dataclass(frozen=True)
class Pose:
    """Taps from the spawn view. None on an axis = leave that axis alone."""
    zoom: int | None = None     # + out (o), - in (i)
    pitch: int | None = None    # + PageUp (looks down), - PageDown (looks up)
    yaw: int | None = None      # 0-7, + right; 45 degrees a tap

    def describe(self) -> str:
        parts = []
        if self.zoom is not None:
            parts.append(f"zoom {self.zoom:+d}")
        if self.pitch is not None:
            parts.append(f"pitch {self.pitch:+d}")
        if self.yaw is not None:
            parts.append(f"yaw {self.yaw % TAPS_PER_FULL_TURN * 360 // TAPS_PER_FULL_TURN} deg")
        return ", ".join(parts) or "any"


HOME = Pose(zoom=0, pitch=0, yaw=0)


def yaw_taps(now: int, to: int) -> int:
    """Signed taps from heading `now` to `to`, the short way (+ right).
    A half turn goes right."""
    d = (int(to) - int(now)) % TAPS_PER_FULL_TURN
    return d - TAPS_PER_FULL_TURN if d > TAPS_PER_FULL_TURN // 2 else d


class Camera:
    """Sends camera taps and counts them. Yaw lives in `bearings`."""

    def __init__(self, vin, bearings: Bearings | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.vin = vin
        self.bearings = bearings if bearings is not None else Bearings()
        self.sleep = sleep
        self._zoom = 0
        self._pitch = 0

    def _spawns_now(self) -> int:
        return int(getattr(self.bearings, "spawns", 0))

    @property
    def pose(self) -> Pose:
        """Where the camera is now, in taps from the spawn view. After a
        spawn yaw is the compass's (back at 0); zoom and pitch are kept."""
        return Pose(zoom=self._zoom, pitch=self._pitch,
                    yaw=self.bearings.heading_taps % TAPS_PER_FULL_TURN)

    def tap(self, axis: str, taps: int) -> None:
        """Send `taps` on `axis` (+ out / PageUp / right) and count each one
        as it is sent. A tap the input refuses (`False`: held back by the
        owner's Pause or Take Over, brain/controls) moved nothing and is not
        counted, and a raise part way leaves the count at what went out."""
        plus, minus, gap = AXES[axis]
        step = 1 if taps > 0 else -1
        for _ in range(abs(int(taps))):
            if self.vin.tap(plus if step > 0 else minus) is False:
                continue
            if axis == "zoom":
                self._zoom += step
            elif axis == "pitch":
                self._pitch += step
            else:
                self.bearings.turned(step)
            self.sleep(gap)

    def set(self, target: Pose) -> Pose:
        """Tap to `target` (its None axes untouched); returns the pose before."""
        before = self.pose
        for axis in ORDER:
            want = getattr(target, axis)
            if want is None:
                continue
            have = getattr(before, axis)
            self.tap(axis, yaw_taps(have, want) if axis == "yaw" else want - have)
        return before

    @contextlib.contextmanager
    def looking(self, target: Pose):
        """`with camera.looking(Pose(zoom=3)):` -- the view for the block, and
        the axes it changed put back on every way out. If the character
        respawned inside the block, yaw is not turned back: the respawn already
        put it at spawn heading, which is what every walk after expects."""
        spawns = self._spawns_now()
        before = self.set(target)
        try:
            yield self
        finally:
            back = Pose(**{axis: getattr(before, axis)
                           for axis in ORDER if getattr(target, axis) is not None})
            if self._spawns_now() != spawns:
                back = Pose(zoom=back.zoom, pitch=back.pitch)
            self.set(back)
