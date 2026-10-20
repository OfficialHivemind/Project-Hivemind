#!/usr/bin/env python3
"""Which hand-labelled frames (data/models/coin_labels.json) are trained on
and which are held out, BY NIGHT, for vision/tokdet (docs/pending/tokdet-v2.md).

A frame's night is the local date of its file time minus 12 h, so one
evening-to-morning session is one night. HELD_OUT nights are never trained
on by either model in the comparison, nor by the teacher that pseudo-labels
the training frames.

    ./scripts/tokdet_split.py                     # print the split
    ./scripts/tokdet_split.py --baseline OUT.npz  # today's detector, retrained
                                                  # on the train nights only
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

LIVE = Path.home() / "Hivemind"
HELD_OUT = ("2026-09-28", "2026-10-07")


def night_of(path: Path) -> str:
    t = os.path.getmtime(path) - 12 * 3600
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d")


def split(frames, root: Path = LIVE):
    """(train, held out) lists of train_coins frames, each with "night" set."""
    train, held = [], []
    for f in frames:
        f["night"] = night_of(root / f["path"])
        (held if f["night"] in HELD_OUT else train).append(f)
    return train, held


def main() -> int:
    import train_coins
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="")
    ap.add_argument("--epochs", type=int, default=12)
    args = ap.parse_args()
    import cv2
    cv2.setNumThreads(2)
    frames = train_coins.load_frames(LIVE)
    train, held = split(frames)
    for name, part in (("train", train), ("held out", held)):
        nights = sorted({f["night"] for f in part})
        print(f"{name}: {len(part)} frames, {sum(len(f['coins']) for f in part)} boxes, "
              f"{sum(not f['partial'] for f in part)} labelled whole, nights {nights}")
    if args.baseline:
        model = train_coins.train(train, args.epochs, seed=99)
        model.save(Path(args.baseline))
        print(f"wrote {args.baseline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
