#!/usr/bin/env python3
"""Lay out the coin detector's candidates on saved frames, for review by eye.

    ./scripts/review_coins.py OUT_DIR WINDOW_DIR... [--frames 0,45,100] [--min-p 0.3]

THE TOKEN SCHOOL (the owner, 2026-10-02, asked for set time where the AI
trains on tokens to get better at them). The detector
was trained on 363 frames, nearly all Pineapple Patch pickups
(data/models/coin_labels.json); the bot now gathers Pine Tree and fights in
Strawberry, and by 2026-10-02 2,762 of its first 2,840 chases (from run 531)
had ended "the chase never reached it" (var/school-coins/lessons.jsonl). So
new frames are labelled from where it plays now. THAT FIGURE IS HISTORY:
MEASURED 2026-10-21 (tools/analysis/chase_lessons.py, runs 1050-1158) 577 of
4,147 chases were never reached (13.9%); what is short now is the verdict
after reaching -- 157 of 1,831 reached honey tokens confirmed, the trickle
hiding the lump (docs/pending/chase-analysis-2026-10-21.md).

Drawing boxes by hand is slow; answering yes or no is not. For each frame this
runs both stages (`coins.look`), keeps every candidate the network gives at
least --min-p, merges repeats, and writes:

  OUT_DIR/<window>__<frame>.png   the frame with each candidate numbered, and
                                  a zoomed crop of each beside it
  OUT_DIR/review.json             per frame, the candidates (id, box, p) and an
                                  empty `answers` -- "coin:<kind>", "no", or
                                  "skip" per id -- for the reviewer to fill

`scripts/merge_coin_review.py` turns the answers into coin_labels.json rows:
a "coin" answer a coin with its box and kind (from "review"), a "no" a
`not_coins` box -- the hard negatives `train_coins.py` already learns from.
It never touches the game.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cv2                                                      # noqa: E402
import numpy as np                                              # noqa: E402

from hivemind.vision import coins                               # noqa: E402

SHEET_W = 960                 # the frame's width on the sheet
CROP_PX = 96                  # each candidate's zoomed crop
CROPS_PER_ROW = 4
MAX_CANDIDATES = 16


def candidates(frame, min_p: float) -> list:
    """[(cx, cy, side, p)] strongest first, merged, at p >= min_p."""
    found = []
    for cx, cy, side, logit, _s1 in coins.look(frame):
        p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, logit))))
        if p >= min_p:
            found.append((cx, cy, side, p))
    merged = coins.merge([(cx, cy, side, p) for cx, cy, side, p in found])
    return merged[:MAX_CANDIDATES]


def sheet(frame, found) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = SHEET_W / w
    left = cv2.resize(frame, (SHEET_W, int(h * scale)))
    crops = []
    for i, (cx, cy, side, p) in enumerate(found):
        half = side * 0.75
        x0, y0 = int(max(0, cx - half)), int(max(0, cy - half))
        x1, y1 = int(min(w, cx + half)), int(min(h, cy + half))
        cv2.rectangle(left, (int(x0 * scale), int(y0 * scale)),
                      (int(x1 * scale), int(y1 * scale)), (0, 0, 255), 2)
        cv2.putText(left, str(i), (int(x0 * scale), max(12, int(y0 * scale) - 3)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        c = frame[y0:y1, x0:x1]
        c = cv2.resize(c, (CROP_PX, CROP_PX)) if c.size else np.zeros((CROP_PX, CROP_PX, 3), np.uint8)
        cv2.putText(c, f"{i} {p:.2f}", (3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
        crops.append(c)
    rows = max(1, math.ceil(len(crops) / CROPS_PER_ROW))
    grid = np.zeros((rows * CROP_PX, CROPS_PER_ROW * CROP_PX, 3), np.uint8)
    for i, c in enumerate(crops):
        r, k = divmod(i, CROPS_PER_ROW)
        grid[r * CROP_PX:(r + 1) * CROP_PX, k * CROP_PX:(k + 1) * CROP_PX] = c
    height = max(left.shape[0], grid.shape[0])
    out = np.zeros((height, left.shape[1] + grid.shape[1], 3), np.uint8)
    out[:left.shape[0], :left.shape[1]] = left
    out[:grid.shape[0], left.shape[1]:] = grid
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("windows", nargs="+")
    ap.add_argument("--frames", default="0,45,100")
    ap.add_argument("--min-p", type=float, default=0.3)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    picks = [int(x) for x in args.frames.split(",") if x.strip()]
    review = {"note": "answers per candidate id: coin:<kind>, no, or skip",
              "frames": []}
    for wdir in args.windows:
        wdir = Path(wdir)
        frames = sorted(wdir.glob("*.jpg")) + sorted(wdir.glob("*.png"))
        for k in picks:
            if k >= len(frames):
                continue
            path = frames[k]
            frame = cv2.imread(str(path))
            if frame is None:
                continue
            found = candidates(frame, args.min_p)
            name = f"{wdir.name}__{path.stem}"
            cv2.imwrite(str(out / f"{name}.png"), sheet(frame, found))
            try:
                rel = str(path.resolve().relative_to(Path.home() / "Hivemind"))
            except ValueError:
                rel = str(path)
            review["frames"].append({
                "path": rel, "window": wdir.name, "sheet": f"{name}.png",
                "candidates": [{"id": i, "box": [int(cx - side / 2), int(cy - side / 2),
                                                 int(cx + side / 2), int(cy + side / 2)],
                                "p": round(p, 3)} for i, (cx, cy, side, p) in enumerate(found)],
                "answers": {}})
            print(f"{name}: {len(found)} candidate(s)", flush=True)
    (out / "review.json").write_text(json.dumps(review, indent=1))
    print(f"{len(review['frames'])} frame(s) laid out in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
