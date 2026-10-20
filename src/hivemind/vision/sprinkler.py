"""Where the account's own sprinkler (Golden Gushers) stands on screen.

For the sprinkler anchor (act/drift `sprinkler_anchor`): after a pattern pass,
walk back until the sprinkler is near the character again -- the job a
sprinkler finder does in other macros. Two stages, numpy + OpenCV only:

  1. PROPOSALS: tan, upright blobs at half resolution -- the Gusher's colour.
     MEASURED on attempt-1247 (the Gusher's sunlit side): HSV p10..p90 =
     (21..26, 86..116, 126..167), widened for shade and glare. High recall,
     low precision: bees, honey tokens and the character's yellow parts pass.
  2. A 32x32 crop of each proposal through the coin network's shape
     (`vision/coinnet`, ~89k weights, its own weights in
     data/models/sprinkler.npz): "is this a Gusher".

Trained and measured by scripts/train_sprinkler.py on the self-labelled set
(local research data, not shipped, built by
scripts/build_sprinkler_dataset.py); the numbers are in
docs/pending/ai-sprinkler.md. GOLDEN GUSHERS ONLY: another sprinkler has
another colour and needs its own gate and its own training.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from ..datapaths import data
from . import coinnet

MODEL = data("models/sprinkler.npz")

# ---- stage 1, on a 960-wide frame (half of 1920x1080) -----------------------
WORK_W = 960
TAN_LO, TAN_HI = (17, 65, 105), (28, 135, 215)
HUD_TOP, HUD_BOTTOM = 75, 470            # work rows: pills/icons above, hotbar below
MIN_AREA, MAX_AREA = 150, 6000           # work px
MIN_TALL, MIN_FILL = 1.0, 0.35           # height/width, area/box

# ---- stage 2 ----------------------------------------------------------------
CROP = 32
CONTEXT = 1.3                            # square side = CONTEXT x the box's longer side
# The cut the trainer chose on the validation runs (data/models/sprinkler.npz
# `cut`); this is only the fallback for a model saved without one.
CUT = 0.5


@dataclass(frozen=True)
class Sighting:
    """One sprinkler on screen, in the frame's own pixels."""
    x: int
    y: int
    w: int
    h: int
    score: float

    @property
    def centre(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2


def proposals(work: np.ndarray) -> list[tuple[int, int, int, int]]:
    """(x, y, w, h) in WORK px of every tan upright blob."""
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, TAN_LO, TAN_HI)
    m[:HUD_TOP] = 0
    m[HUD_BOTTOM:] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        if MIN_AREA <= a <= MAX_AREA and h >= MIN_TALL * w and a >= MIN_FILL * w * h:
            out.append((x, y, w, h))
    return out


def crop(work: np.ndarray, box) -> np.ndarray:
    """The CROP x CROP square round a work-px box, edge-padded at the border."""
    x, y, w, h = box
    side = max(8, int(round(max(w, h) * CONTEXT)))
    cx, cy = x + w // 2, y + h // 2
    x0, y0 = cx - side // 2, cy - side // 2
    pad = side
    big = cv2.copyMakeBorder(work, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    c = big[y0 + pad:y0 + pad + side, x0 + pad:x0 + pad + side]
    return cv2.resize(c, (CROP, CROP), interpolation=cv2.INTER_AREA)


def to_work(frame: np.ndarray) -> tuple[np.ndarray, float]:
    """The frame at WORK_W wide, BGR, and frame px per work px.

    THE LIVE CAPTURE IS BGRA. MEASURED runs 1254-1259 (2026-10-27 02:29-09:03):
    433 of the 867 `sprinkler anchor` lines were "raised (matmul ... size 27 is
    different from 36)" -- a 4-channel crop into a network trained on 3 -- on
    every look with a tan proposal, so the live finder never scored one; the
    saved jpgs it was trained and tested on are BGR."""
    if frame.ndim == 3 and frame.shape[2] > 3:
        frame = np.ascontiguousarray(frame[:, :, :3])
    s = frame.shape[1] / float(WORK_W)
    if abs(s - 1.0) < 1e-6:
        return frame, 1.0
    work = cv2.resize(frame, (WORK_W, round(frame.shape[0] / s)), interpolation=cv2.INTER_AREA)
    return work, s


@lru_cache(maxsize=1)
def load(path: Path = MODEL) -> tuple[dict, float]:
    with np.load(path, allow_pickle=False) as z:
        params = {k: z[k] for k in coinnet.PARAM_NAMES}
        cut = float(z["cut"]) if "cut" in z.files else CUT
    return params, cut


def find(frame: np.ndarray, params: dict | None = None,
         cut: float | None = None) -> list[Sighting]:
    """Every sprinkler on screen scoring `cut` or more, best first."""
    if frame is None:
        return []
    if params is None:
        params, model_cut = load()
        cut = model_cut if cut is None else cut
    cut = CUT if cut is None else cut
    work, s = to_work(frame)
    boxes = proposals(work)
    if not boxes:
        return []
    x = np.stack([crop(work, b) for b in boxes]).astype(np.float32) / 255.0
    p = 1.0 / (1.0 + np.exp(-np.clip(coinnet.logits(params, x), -30, 30)))
    out = [Sighting(int(b[0] * s), int(b[1] * s), int(b[2] * s), int(b[3] * s), float(q))
           for b, q in zip(boxes, p) if q >= cut]
    return sorted(out, key=lambda o: -o.score)
