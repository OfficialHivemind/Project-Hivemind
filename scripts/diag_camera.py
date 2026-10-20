#!/usr/bin/env python3
"""How many degrees does one Roblox camera tap turn, and which heading is open?

Established: `period` / `comma` DO turn the follow camera under Sober -- four
taps swung the view from the hive wall to the open field -- and the bot can
spawn wedged, with `w` blocked. Measured flow per frame at spawn, twice:
w 1.12/1.24, s 2.20/2.04, a 10.99/10.42, d 11.35/11.33.

Two things measured here, both by CLOSURE rather than assumption:

  1. TAPS PER FULL TURN. Tap one at a time and compare each frame with the one
     at spawn. The view comes back around after a full turn, so the tap count
     with the highest similarity IS the full turn and 360/that is the step.
     No field-of-view assumption is involved. An earlier version tried to infer
     the angle from a phase correlation and got a response of 0.001, because a
     large 3D rotation is not an image translation -- the low response was
     itself the evidence that something big had happened.

  2. WHICH HEADING OPENS UP `w`, which is what navigation actually needs.
"""
import pathlib
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                  # noqa: E402
from hivemind.vision.flow import FlowTracker        # noqa: E402

OUT = pathlib.Path("/tmp/hivemind-diag/camera3")
# The world only. The HUD strips at top and bottom never move and would make
# every frame look similar to every other.
BAND = (200, 260, 1520, 560)
TAPS = 12


def world(frame):
    x, y, w, h = BAND
    return cv2.cvtColor(frame[y:y + h, x:x + w, :3], cv2.COLOR_BGR2GRAY)


def similarity(a, b):
    """Normalised correlation between two views. 1.0 means identical."""
    fa, fb = np.float32(world(a)).ravel(), np.float32(world(b)).ravel()
    fa, fb = fa - fa.mean(), fb - fb.mean()
    denominator = float(np.linalg.norm(fa) * np.linalg.norm(fb))
    return float(fa @ fb / denominator) if denominator else 0.0


def flow_for(inp, cap, key, seconds=0.7):
    tracker = FlowTracker()
    tracker.update(cap.capture())
    magnitudes = []
    inp.press(key)
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            sample = tracker.update(cap.capture())
            if sample is not None and sample.pairs is not None:
                d = sample.pairs[:, 1, :] - sample.pairs[:, 0, :]
                magnitudes.append(np.median(np.linalg.norm(d, axis=1)))
            time.sleep(0.03)
    finally:
        inp.release(key)
    time.sleep(0.4)
    return float(np.median(magnitudes)) if magnitudes else 0.0


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    try:
        spawn = cap.capture()
        cv2.imwrite(str(OUT / "tap_00.png"), spawn[:, :, :3])
        base = flow_for(inp, cap, "w")
        with inp.held("s"):
            time.sleep(0.4)
        time.sleep(0.4)

        print(f"\n  forward flow at spawn: {base:.2f} px/frame"
              f"  {'(blocked)' if base < 1.5 else ''}\n", flush=True)
        print("  taps   similarity to spawn   forward flow   verdict", flush=True)
        print("  " + "-" * 60, flush=True)
        print(f"  {0:>4}   {1.000:18.3f}   {base:12.2f}", flush=True)

        scores = {}
        for tap in range(1, TAPS + 1):
            inp.camera_right(1)
            time.sleep(0.5)
            frame = cap.capture()
            cv2.imwrite(str(OUT / f"tap_{tap:02d}.png"), frame[:, :, :3])
            scores[tap] = similarity(spawn, frame)
            forward = flow_for(inp, cap, "w")
            with inp.held("s"):          # undo the step, so headings compare
                time.sleep(0.4)
            time.sleep(0.4)
            print(f"  {tap:>4}   {scores[tap]:18.3f}   {forward:12.2f}   "
                  f"{'OPEN' if forward > 1.5 else 'blocked'}", flush=True)

        turned = max((t for t in scores if t >= 3), key=lambda t: scores[t])
        print(f"\n  the view returns closest to spawn after {turned} taps"
              f" (similarity {scores[turned]:.3f})", flush=True)
        print(f"  => roughly {360 / turned:.0f} degrees per tap", flush=True)
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
