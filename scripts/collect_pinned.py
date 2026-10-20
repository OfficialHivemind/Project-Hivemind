#!/usr/bin/env python3
"""Collect the one measurement that would settle the token detector's worst bug.

WHY. `vision/tokens.nearest()` picks the player's own bee: over all 18 frames
of `var/tokens_live` the bee's own eyes and body sit 55-160 px from the point
the code treats as the character and the nearest real object is 385 px away, so
the bee won 14 of those 18. docs/GAPS.md §4 has the numbers.

The rule that would fix it is that the avatar is RIGID IN SCREEN SPACE and the
world is not -- so a glyph that does not move while the view does is part of
the character or the interface. It cannot be validated on the frames we have,
because every one of them was taken with the camera still: at the raw-glyph
level the real token is as static as the bee's eye.

THIS COLLECTS THE MISSING HALF, and it does it WITHOUT TOUCHING THE GAME. It
reads the JPEG the live view already writes (telemetry/liveview), so there is
no second screencopy client -- DESIGN 8a records a fourth one killing the game
twice -- and no input of any kind. It can run beside a farming bot all night.

For every sample it records each raw glyph's position, and how much the view
moved since the previous sample, so afterwards a glyph can be asked the only
question that matters: "when the view moved, did you?"

    ./scripts/collect_pinned.py --seconds 600 --out var/pinned
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import cv2
import numpy as np

from hivemind.vision import tokens

# How much of the frame has to change for the view to count as having MOVED.
# Not a detection threshold -- it is only used to label samples afterwards, and
# the analysis reports the distribution rather than trusting one number.
MOVED_FRACTION = 0.04
PIXEL_DELTA = 28


def changed(before, after) -> float:
    if before is None or after is None or before.shape != after.shape:
        return 0.0
    a = before.astype(np.int16)
    b = after.astype(np.int16)
    return float((np.abs(a - b).max(axis=2) > PIXEL_DELTA).mean())


def main() -> int:
    ap = argparse.ArgumentParser()
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    ap.add_argument("--frame", default=f"{runtime}/hivemind-live.jpg")
    ap.add_argument("--out", default="var/pinned")
    ap.add_argument("--seconds", type=float, default=600.0)
    ap.add_argument("--hz", type=float, default=3.0)
    ap.add_argument("--keep-every", type=int, default=30,
                    help="also save a copy of every Nth frame, for labelling")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    samples: list[dict] = []
    previous = None
    interval = 1.0 / max(0.2, args.hz)
    deadline = time.monotonic() + args.seconds
    index = 0
    unreadable = 0

    while time.monotonic() < deadline:
        time.sleep(interval)
        frame = cv2.imread(args.frame)
        if frame is None:
            unreadable += 1            # caught mid-write; routine
            continue
        bgr = frame[:, :, :3]
        # The detector's sightings, where this once recorded the glyph
        # detector's raw marks (vision/tokens: the glyph model found bees and
        # was replaced by vision/coins, 2026-09-28). The rows keep the old
        # "glyphs" key so earlier recordings and this one read the same way.
        seen = tokens.detect(bgr)
        row = {
            "i": index,
            "at": round(time.time(), 3),
            "moved": round(changed(previous, bgr), 4),
            "glyphs": [{"x": s.x, "y": s.y, "area": s.area, "box": list(s.box or ())}
                       for s in seen],
        }
        if args.keep_every and index % args.keep_every == 0:
            name = f"{index:05d}.jpg"
            cv2.imwrite(str(out / name), bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            row["frame"] = name
        samples.append(row)
        previous = bgr
        index += 1

    moving = [s for s in samples if s["moved"] >= MOVED_FRACTION]
    (out / "samples.json").write_text(json.dumps({
        "frame": args.frame,
        "hz": args.hz,
        "moved_fraction": MOVED_FRACTION,
        "samples": samples,
    }, indent=1))
    print(f"{len(samples)} samples, {len(moving)} of them with the view "
          f"moving, {unreadable} frames unreadable")
    print(f"written to {out / 'samples.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
