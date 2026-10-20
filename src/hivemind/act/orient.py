"""Facing a direction the character can actually walk in.

The bot spawns on the hive platform facing the honeycomb wall, so `w` is
blocked. MEASURED at spawn, three separate runs, median flow per frame:

    w 1.12 / 1.24 / 1.23      s 2.20 / 2.04      a 10.99 / 10.42      d 11.35 / 11.33

That single fact wasted a lot of effort: every calibration attempt was fitting
a "forward burst" that contained no forward motion, and the fitter answered
anyway with a horizon of -2000. A frame-difference check did not catch it
either, because a blocked `w` still changed 70% of the frame -- the hive's
beams and sparkles animate on their own. Only tracked displacement tells the
two apart, which is why everything here measures flow.

THE CAMERA IS THE STEERING WHEEL

Every movement key is relative to where the camera points, so turning the
camera is how "forward" gets redefined. Roblox turns it with comma and period
(BeeTuxMacro drives exactly those keys), and the step size was measured by
CLOSURE rather than assumed: tapping one at a time and comparing each frame
with the starting view, the view came back around at 8 taps (similarity 0.777
against ~0 for the unrelated headings, and 0.343 at 4 taps and 0.339 at 12 --
the two half-turns agreeing with each other).

    8 taps per full turn, 45 degrees per tap

Forward was blocked at 0, 1 and 9 taps in that sweep, and 9 = 1 + 8 is the same
heading -- the wall repeating exactly one full turn later, which is the same
closure result seen from the other side.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

# MEASURED by closure, see the module docstring. Not a documented constant, so
# if Roblox changes it, scripts/diag_camera.py re-measures it in one run.
TAPS_PER_FULL_TURN = 8
CAMERA_STEP_DEG = 360.0 / TAPS_PER_FULL_TURN

# A direction counts as open above this many pixels of flow per frame. The gap
# between blocked and open is wide -- roughly 1 px against 7-17 px -- so the
# threshold is not delicately placed.
OPEN_FLOW_PX = 2.5
PROBE_SECONDS = 0.7
SETTLE_SECONDS = 0.4


@dataclass
class Heading:
    """Where the camera ended up, and how well it walks."""
    taps: int
    flow_px: float
    open: bool

    @property
    def degrees(self) -> float:
        return (self.taps * CAMERA_STEP_DEG) % 360.0

    def describe(self) -> str:
        return (f"{self.taps} taps ({self.degrees:.0f} deg), "
                f"{self.flow_px:.1f} px/frame — "
                f"{'open' if self.open else 'blocked'}")


def probe_flow(vin, frames, tracker_factory, key: str = "w",
               seconds: float = PROBE_SECONDS,
               settle: float = SETTLE_SECONDS) -> float:
    """Median flow per frame while holding `key`. 0 when nothing moves."""
    tracker = tracker_factory()
    tracker.update(frames())
    magnitudes: list[float] = []
    try:
        vin.press(key)
        deadline = time.monotonic() + seconds
        while True:                       # always take at least one sample
            sample = tracker.update(frames())
            if sample is not None and sample.pairs is not None:
                delta = sample.pairs[:, 1, :] - sample.pairs[:, 0, :]
                magnitudes.append(float(np.median(np.linalg.norm(delta, axis=1))))
            if time.monotonic() >= deadline:
                break
            time.sleep(0.03)
    finally:
        vin.release(key)
    time.sleep(settle)
    return float(np.median(magnitudes)) if magnitudes else 0.0


def face_open_ground(vin, frames, tracker_factory,
                     max_taps: int = TAPS_PER_FULL_TURN,
                     seconds: float = PROBE_SECONDS,
                     settle: float = SETTLE_SECONDS) -> Heading:
    """Turn the camera until forward is walkable, and report where it stopped.

    Sweeps at most one full turn, because after that it is back where it
    started and a second lap would only repeat the same headings. If nothing
    opens up, the best heading found is returned with `open` False rather than
    an exception: the caller may still want to try, and a wrong guess here
    costs a wasted burst rather than anything irreversible.
    """
    def probe() -> float:
        return probe_flow(vin, frames, tracker_factory,
                          seconds=seconds, settle=settle)

    best = Heading(0, probe(), False)
    best.open = best.flow_px >= OPEN_FLOW_PX
    if best.open:
        return best

    for tap in range(1, max_taps + 1):
        vin.camera_right(1)
        time.sleep(settle)
        flow = probe()
        if flow > best.flow_px:
            best = Heading(tap, flow, flow >= OPEN_FLOW_PX)
        if flow >= OPEN_FLOW_PX:
            return Heading(tap, flow, True)
    return best
