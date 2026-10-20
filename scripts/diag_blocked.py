#!/usr/bin/env python3
"""Which directions can the character actually move at spawn?

The flow-field diagnostic showed forward motion producing a dy IQR of 0.41 px
while strafing produced 12.78 px of dx -- a 30x difference. The frame explains
it: the bot spawns INSIDE the hive facing the honeycomb wall, so "w" walks into
a wall. There was never any forward translation for the calibration to fit.

That matters beyond calibration, so it is measured per direction rather than
inferred: hold each key, and report how much of the frame changed and how far
the tracked points actually moved.
"""
import pathlib
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                      # noqa: E402
from hivemind.vision.flow import FlowTracker            # noqa: E402

OUT = pathlib.Path("/tmp/hivemind-diag/blocked")
CHARACTER_BOX = (680, 420, 520, 580)


def probe(inp, cap, key, seconds=1.2):
    """Hold one key; return (frame-change fraction, median flow magnitude)."""
    before = cap.capture()
    tracker = FlowTracker()
    tracker.update(before)
    moved = []
    inp.press(key)
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            sample = tracker.update(cap.capture())
            if sample is not None and sample.pairs is not None:
                moved.append(sample)
            time.sleep(0.03)
    finally:
        inp.release(key)
    time.sleep(0.6)
    after = cap.capture()

    changed = float((cv2.absdiff(before[:, :, :3],
                                 after[:, :, :3]).max(axis=2) > 12).mean())
    if moved:
        cx, cy, cw, ch = CHARACTER_BOX
        magnitudes = []
        for sample in moved:
            starts = sample.pairs[:, 0, :]
            off = ~((starts[:, 0] >= cx) & (starts[:, 0] < cx + cw)
                    & (starts[:, 1] >= cy) & (starts[:, 1] < cy + ch))
            if off.sum():
                delta = sample.pairs[off, 1, :] - sample.pairs[off, 0, :]
                magnitudes.append(np.median(np.linalg.norm(delta, axis=1)))
        flow = float(np.median(magnitudes)) if magnitudes else 0.0
    else:
        flow = 0.0
    return changed, flow, after


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    try:
        cv2.imwrite(str(OUT / "00_spawn.png"), cap.capture()[:, :, :3])
        print("\n  key   direction    frame changed   median flow px/frame",
              flush=True)
        print("  " + "-" * 58, flush=True)
        for key, name in (("w", "forward"), ("s", "back"),
                          ("a", "left"), ("d", "right")):
            changed, flow, frame = probe(inp, cap, key)
            verdict = "BLOCKED" if flow < 1.0 else ""
            print(f"  {key}     {name:<11}  {changed:12.1%}   {flow:12.2f}  {verdict}",
                  flush=True)
            cv2.imwrite(str(OUT / f"after_{key}.png"), frame[:, :, :3])
            # return roughly to where we started
            opposite = {"w": "s", "s": "w", "a": "d", "d": "a"}[key]
            with inp.held(opposite):
                time.sleep(1.2)
            time.sleep(0.5)
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
