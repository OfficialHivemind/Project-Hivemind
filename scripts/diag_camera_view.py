#!/usr/bin/env python3
"""What does the field look like at each camera zoom and tilt -- and what can
the bot still read there?

THE OWNER, 2026-09-22, watching the live view: "with the current veiw the bot
wont be able to see things behind it clearly or around it, its pretty zoomed
in", and that other macros have "better screen positions for optimal veiw". A
popular macro configures a camera per field -- a yaw, a pitch ("from a top-down view down to
a level, straight-ahead view"; Pine Tree starter pitch 3) and shift lock --
and gathers from that fixed view. This bot gathers from whatever camera the
walk out left it with.

CHANGING THE VIEW IS A CALIBRATION EVENT, which is why this measures before
anything is committed. Every pixel-based reading was calibrated at the current
zoom: token cube sizes (vision/tokens), the hive's yellow-pixel thresholds
(act/hive.hive_bearing), the own-bee pin (vision/pinned), the mob health bar.
The HUD is screen-fixed and should not move; that is checked too rather than
assumed.

WHAT IT DOES. From wherever the character stands, it steps the zoom out with
Roblox's `o` key one press at a time, and at each step tilts the camera with
PageDown/PageUp, photographing every combination and measuring on each frame:

    tokens      how many token candidates vision/tokens finds, and at what
                confidence -- more visible tokens at good confidence is the
                point of zooming out
    ground      the share of the frame that is field ground (green/flower
                colour) below the horizon -- a rough "how much of the
                surroundings can it see"
    hive        hive_bearing's yellow count, so the homing thresholds can be
                re-derived for the chosen view
    hud         whether the pollen and honey counters still read

It then restores the camera exactly (`i` for every `o`, the opposite tilt for
every tilt), so the run that follows is not left with a view nothing was
calibrated for. Presses only i, o, PageUp, PageDown. No movement, no interact.

    ./scripts/diag_camera_view.py [zoom_steps=4] [tilt_steps=3]

Frames and a CSV land in var/camera_view/.
"""
from __future__ import annotations

import csv
import pathlib
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                              # noqa: E402
from hivemind.act.hive import hive_bearing                      # noqa: E402
from hivemind.brain.farm import HudReader                       # noqa: E402
from hivemind.vision import screenstate as ss                   # noqa: E402
from hivemind.vision import tokens                              # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "var" / "camera_view"
# Field ground in Bee Swarm is saturated green with flower colour on top; this
# is a coarse HSV band for "ground", used only as a coverage proxy here.
GROUND_HSV = ((35, 60, 40), (90, 255, 255))
WORLD_ROWS = (170, 900)


def ground_share(frame) -> float:
    top, bottom = WORLD_ROWS
    world = frame[top:bottom, :, :3]
    hsv = cv2.cvtColor(world, cv2.COLOR_BGR2HSV)
    lo, hi = GROUND_HSV
    mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
    return float(mask.mean() / 255.0)


def main() -> int:
    zoom_steps = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    tilt_steps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    OUT.mkdir(parents=True, exist_ok=True)
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    hud = HudReader(cap.capture, ss.load_templates(ROOT / "data/templates/digits"))
    rows = []

    def measure(zoom: int, tilt: int) -> None:
        time.sleep(0.6)
        frame = cap.capture()
        if frame is None:
            print(f"  zoom {zoom} tilt {tilt:+d}: no frame")
            return
        bgr = frame[:, :, :3]
        name = f"zoom{zoom}_tilt{tilt:+d}.png"
        cv2.imwrite(str(OUT / name), bgr)
        seen = tokens.detect(bgr, limit=60)
        confident = [s for s in seen if s.confidence >= 0.7]
        bearing, yellow = hive_bearing(bgr)
        p, h = hud.pollen(), hud.honey()
        row = {
            "zoom_out": zoom, "tilt": tilt,
            "tokens": len(seen), "tokens_ge_0.7": len(confident),
            "best_conf": round(max((s.confidence for s in seen), default=0.0), 2),
            "ground_share": round(ground_share(frame), 3),
            "hive_yellow": yellow,
            "pollen_reads": p.ok, "pollen_conf": round(float(p.score or 0), 2),
            "honey_reads": h.ok, "honey_conf": round(float(h.score or 0), 2),
            "frame": name,
        }
        rows.append(row)
        print(f"  zoom {zoom} tilt {tilt:+d}: tokens {len(seen):2d} "
              f"({len(confident)} at >=0.7, best {row['best_conf']}), ground "
              f"{row['ground_share']:.0%}, hive yellow {yellow:,}, HUD pollen "
              f"{'ok' if p.ok else 'NO'} honey {'ok' if h.ok else 'NO'}",
              flush=True)

    try:
        print(f"\n  measuring {zoom_steps} zoom step(s) x tilt -{tilt_steps}..+{tilt_steps}",
              flush=True)
        measure(0, 0)
        for zoom in range(1, zoom_steps + 1):
            inp.tap("o")
            time.sleep(0.3)
            measure(zoom, 0)
            # tilt down (more top-down), then back, then up, then back
            for direction, key, back in ((+1, "pagedown", "pageup"),
                                         (-1, "pageup", "pagedown")):
                for t in range(1, tilt_steps + 1):
                    inp.tap(key)
                    time.sleep(0.25)
                    measure(zoom, direction * t)
                for _ in range(tilt_steps):
                    inp.tap(back)
                    time.sleep(0.2)
        # RESTORE. Every `o` gets an `i`, so the next run starts where this
        # one found the camera.
        for _ in range(zoom_steps):
            inp.tap("i")
            time.sleep(0.2)
        time.sleep(0.6)
        after = cap.capture()
        if after is not None:
            cv2.imwrite(str(OUT / "restored.png"), after[:, :, :3])
        with (OUT / "measurements.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\n  {len(rows)} views measured; frames and measurements.csv in {OUT}")
        print("  The view to adopt is the one with the most confident tokens and "
              "the widest ground share WHILE the HUD still reads. Pick it from the "
              "table, do not guess from the pictures.")
    finally:
        inp.release_all()
        ready.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
