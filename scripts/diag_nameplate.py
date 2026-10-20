#!/usr/bin/env python3
"""What a real mob nameplate actually measures on THIS client.

WHY. `vision/nameplate.py` says its recall is unmeasured, and it is right to:
its only positive samples were four PC-client screenshots from the wiki. On
2026-09-20 the bot stood in the Pineapple Patch beside a Rhino Beetle whose
nameplate filled a tenth of the screen and logged ZERO sightings. That is the
first real mob this project has ever had frames of, so it is the first chance
to replace an assumption with a number.

This does not change any behaviour. It reads frames the live view already
wrote, reports what the shipped detector finds, and separately measures every
bar-shaped blob it can see so the real geometry can be read off instead of
guessed at.

    ./.venv/bin/python scripts/diag_nameplate.py var/mobframes [--save N]
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.vision import nameplate  # noqa: E402

# Deliberately wider than the shipped bands: the point is to find out what the
# real bar is, not to confirm what we already believed.
WIDE_GREEN = ((35, 120, 120), (85, 255, 255))


def blobs(frame, top: int = 170):
    bgr = frame[top:, :, :3]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(WIDE_GREEN[0], np.uint8),
                       np.array(WIDE_GREEN[1], np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for row in stats[1:count]:
        x, y, w, h, area = (int(v) for v in row[:5])
        if w < 40 or h < 6:
            continue
        aspect = w / max(1, h)
        if not (3.0 <= aspect <= 20.0):
            continue
        fill = area / float(w * h)
        if fill < 0.55:
            continue
        patch = hsv[y:y + h, x:x + w]
        out.append({
            "x": x, "y": y + top, "w": w, "h": h, "aspect": round(aspect, 2),
            "fill": round(fill, 2),
            "hue": int(np.median(patch[:, :, 0])),
            "sat": int(np.median(patch[:, :, 1])),
            "val": int(np.median(patch[:, :, 2])),
        })
    return sorted(out, key=lambda b: -b["w"] * b["h"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--save", type=int, default=6,
                    help="write this many candidate crops for eyeballing")
    args = ap.parse_args()

    folder = pathlib.Path(args.folder)
    files = sorted(folder.glob("*.jpg"))
    if not files:
        print("no frames")
        return 1

    shipped_hits = 0
    frames_with_candidate = 0
    every = []
    saved = 0
    out_dir = folder / "candidates"

    for path in files:
        frame = cv2.imread(str(path))
        if frame is None:
            continue
        if nameplate.find(frame, top=170):
            shipped_hits += 1
        found = blobs(frame)
        if found:
            frames_with_candidate += 1
            every.extend(found)
            if saved < args.save:
                out_dir.mkdir(exist_ok=True)
                b = found[0]
                pad = 60
                y0, y1 = max(0, b["y"] - pad), min(frame.shape[0], b["y"] + b["h"] + pad)
                x0, x1 = max(0, b["x"] - pad), min(frame.shape[1], b["x"] + b["w"] + pad)
                cv2.imwrite(str(out_dir / f"{path.stem}.png"), frame[y0:y1, x0:x1])
                saved += 1

    print(f"\n  frames:                 {len(files)}")
    print(f"  shipped detector fired: {shipped_hits}")
    print(f"  frames with a bar-shaped green blob: {frames_with_candidate}")
    if every:
        w = np.array([b["w"] for b in every])
        h = np.array([b["h"] for b in every])
        a = np.array([b["aspect"] for b in every])
        print(f"\n  candidate geometry over {len(every)} blobs")
        print(f"    width   min {w.min():4d}  median {int(np.median(w)):4d}  max {w.max():4d}")
        print(f"    height  min {h.min():4d}  median {int(np.median(h)):4d}  max {h.max():4d}")
        print(f"    aspect  min {a.min():5.1f}  median {np.median(a):5.1f}  max {a.max():5.1f}")
        print(f"    hue     median {int(np.median([b['hue'] for b in every]))}")
        print(f"    sat     median {int(np.median([b['sat'] for b in every]))}")
        print(f"    val     median {int(np.median([b['val'] for b in every]))}")
        print("\n  largest few:")
        for b in sorted(every, key=lambda b: -b["w"] * b["h"])[:8]:
            print(f"    {b['w']:4d}x{b['h']:<3d} aspect {b['aspect']:5.2f} "
                  f"fill {b['fill']:.2f} hsv({b['hue']},{b['sat']},{b['val']}) "
                  f"at ({b['x']},{b['y']})")
    if saved:
        print(f"\n  wrote {saved} crops to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
