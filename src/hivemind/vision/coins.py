"""Tokens as they really are: spinning coins, found by a trained two-stage detector.

THE GLYPH DETECTOR THIS REPLACES FOUND BEES. `vision/tokens` used to look for
"a cube with a white glyph and a dark outline" -- which is a description of a
Bee Swarm BEE: a cube with its level number in white on its faces. A token
is a COIN: an upright disc with a thick rim of its own colour, a bold icon on
each face, spinning about its vertical axis (a quarter turn in about 0.4 s,
var/incidents/*-token frame strips), so from one frame to the next it is a
full disc, an ellipse, or a thin edge. The owner saw it first: the boxes
were "for things that arnt even tokens like it thinks bees are", and
var/school/lessons.jsonl agreed -- 1,020 pickups in 9,433 chases.

MEASURED 2026-09-28 on 120 frames of 60 Pineapple Patch pickup windows
(var/incidents/*-token, frames 45 and 100 of each), 206 coins labelled by
eye (174 sure; data/models/coin_labels.json):

    the glyph detector    17.6 chaseable boxes a frame, 12% of them on a coin
    this one              see data/models/coins.json `held_out`: five folds,
                          every fold's frames scored by a model that never
                          saw their pickup window

HOW, in two stages, because each is cheap at what it is good at:

  1. CANDIDATES. HOG (a 32 px window over a 0.6-scale frame) and a linear
     model trained on the labelled coins against background and bee crops,
     run densely by OpenCV's `HOGDescriptor.detectMultiScale` in C++: 37 ms on
     one core, 14 on four; ~160 candidate squares a frame after
     non-maximum suppression, and 98% of the labelled coins among them.
  2. THE DECISION. Each candidate, cropped at 1.25x the coin and scaled to
     32x32, goes through a small convolutional network (`vision/coinnet`)
     that answers "is this a coin". It learned the coin's shape and rim in
     every colour, and against the bees, the damage numbers and the
     pineapple wall that the candidates stage also fires on.

Then one sighting per coin: a weaker candidate whose centre is within
MERGE_SHARE of a stronger one's side is the same coin seen at another scale.

CONFIDENCE IS THE NETWORK'S LOG-ODDS, SCALED. Its probabilities crowd
against 1 (a coin is 0.999+), so `Sighting.confidence` is logit / LOGIT_FULL
clipped to 0..1, which keeps the owner's 0..1 chase threshold meaningful:

    confidence 0.25  p 0.900        confidence 0.60  p 0.996
    confidence 0.50  p 0.990        confidence 0.70  p 0.9984

A Sighting's `box` is now the COIN's square, where it used to be the glyph's.
`kind` is "unknown" and `face_hsv` None: nothing here names a token yet.
"""
from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np

from ..datapaths import data
from . import coinnet

MODEL = data("models", "coins.npz")

# ---- stage 1: the candidates -------------------------------------------------
# The frame is looked at in 0.6 scale, where the smallest labelled coin (about
# 50 px across at 1920x1080) is 30 px -- one HOG window.
WORK_SCALE = 0.6
HOG_WINDOW = 32
HOG_BLOCK, HOG_STRIDE, HOG_CELL, HOG_BINS = 16, 8, 8, 9
WIN_STRIDE = 8
SCALE_STEP = 1.15
# The linear score a window needs to become a candidate. MEASURED (five
# folds): at 2.0, 98% of the sure coins are among the candidates, ~160 a
# frame; at 3.0, 94% and ~88.
STAGE1_HIT = 2.0
STAGE1_OVERLAP = 0.3
# The stage-1 window is trained as the coin's side x WINDOW_TO_COIN.
WINDOW_TO_COIN = 1.1

# ---- stage 2: the decision ---------------------------------------------------
CROP_SIZE = 32
CROP_PAD = 1.25             # the crop is the coin's side x this
# Below this probability a candidate is not reported at all; between it and
# the chase threshold it is reported, and the live view draws it as a dot.
REPORT_P = 0.9
LOGIT_FULL = float(np.log(0.9999 / 0.0001))      # confidence 1.0 at p 0.9999

# ---- one coin, one sighting ------------------------------------------------------
MERGE_SHARE = 0.75

# ---- which coin: the honey head --------------------------------------------------
# The Honey token is the commonest coin by far (about half the labelled ones)
# and the one quests ask for by name ("Honey Bee's Honey Hunt -- Collect 2,000
# Honey Tokens", var/quests.json 2026-09-23). Its threshold is the model's
# own (`Model.honey_p`), chosen by scripts/train_coins.py --kinds from its
# held-out measurement and saved with it.
HONEY_PREFIX = "honey_"

# The world part of the frame (vision/tokens.world_box's fractions): the HUD,
# the menu column, the hotbar and the reward feed are not looked at.
WORLD = (0.08, 0.14, 0.93, 0.88)


class Model:
    """The two stages' weights, as data/models/coins.npz holds them -- and,
    when trained, the honey head (`honey`): the same network, asked "is this
    coin a Honey token"."""

    def __init__(self, stage1_w: np.ndarray, stage1_b: float, params: dict,
                 honey: dict | None = None, honey_p: float = 0.0):
        self.stage1 = np.append(np.asarray(stage1_w, np.float32),
                                np.float32(stage1_b)).astype(np.float32)
        self.params = {k: np.asarray(v, np.float32) for k, v in params.items()}
        self.honey = ({k: np.asarray(v, np.float32) for k, v in honey.items()}
                      if honey else None)
        self.honey_p = float(honey_p)

    @classmethod
    def load(cls, path: Path = MODEL) -> "Model":
        with np.load(path, allow_pickle=False) as z:
            geometry = (int(z["work_scale_milli"]), int(z["hog_window"]), int(z["crop_size"]))
            if geometry != (round(WORK_SCALE * 1000), HOG_WINDOW, CROP_SIZE):
                raise ValueError(f"{path} was trained for scale/window/crop {geometry}")
            params = {k: z[k] for k in coinnet.PARAM_NAMES}
            honey = ({k: z[HONEY_PREFIX + k] for k in coinnet.PARAM_NAMES}
                     if HONEY_PREFIX + "w0" in z.files else None)
            honey_p = float(z["honey_p"]) if "honey_p" in z.files else 0.0
            return cls(z["stage1_w"], float(z["stage1_b"]), params, honey, honey_p)

    def save(self, path: Path, **notes) -> None:
        extra = {}
        if self.honey:
            extra = {HONEY_PREFIX + k: v for k, v in self.honey.items()}
            extra["honey_p"] = np.float32(self.honey_p)
        np.savez_compressed(
            path, stage1_w=self.stage1[:-1], stage1_b=np.float32(self.stage1[-1]),
            work_scale_milli=round(WORK_SCALE * 1000), hog_window=HOG_WINDOW,
            crop_size=CROP_SIZE, **self.params, **extra, **notes)


def new_hog() -> cv2.HOGDescriptor:
    return cv2.HOGDescriptor((HOG_WINDOW, HOG_WINDOW), (HOG_BLOCK, HOG_BLOCK),
                             (HOG_STRIDE, HOG_STRIDE), (HOG_CELL, HOG_CELL), HOG_BINS)


_lock = threading.Lock()
_model: Model | None = None
_model_error: str = ""
# ONE HOGDescriptor PER THREAD. The live view's overlay thread and the
# chaser's both look for tokens; a descriptor carries its detector as state,
# and nothing in OpenCV's documentation promises that two threads may share
# one mid-detect.
_local = threading.local()


def model() -> Model | None:
    """The trained model, loaded once; None (and `model_error()` says why)
    when data/models/coins.npz is missing or unreadable."""
    global _model, _model_error
    if _model is None and not _model_error:
        with _lock:
            if _model is None and not _model_error:
                try:
                    _model = Model.load(MODEL)
                except (OSError, KeyError, ValueError) as err:
                    _model_error = f"no coin model ({MODEL.name}): {err}"
    return _model


def model_error() -> str:
    return _model_error


def use(m: Model | None) -> None:
    """Swap in a model (the trainer's measurement, and the tests)."""
    global _model, _model_error
    with _lock:
        _model, _model_error = m, ""
    _local.__dict__.clear()


def _hog_for(m: Model) -> cv2.HOGDescriptor:
    if getattr(_local, "owner", None) is not m:
        hog = new_hog()
        hog.setSVMDetector(m.stage1)
        _local.hog, _local.owner = hog, m
    return _local.hog


def world_box(width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = WORLD
    return int(width * x0), int(height * y0), int(width * x1), int(height * y1)


def work_image(frame: np.ndarray) -> np.ndarray:
    return cv2.resize(np.ascontiguousarray(frame[:, :, :3]), None, fx=WORK_SCALE,
                      fy=WORK_SCALE, interpolation=cv2.INTER_AREA)


def candidates(work: np.ndarray, m: Model, width: int, height: int,
               hit: float = STAGE1_HIT) -> list[tuple[float, float, float, float]]:
    """Stage 1 on a WORK_SCALE image: (cx, cy, window side, score), in FRAME
    pixels, inside the world box, after non-maximum suppression."""
    rects, weights = _hog_for(m).detectMultiScale(
        work, hitThreshold=hit, winStride=(WIN_STRIDE, WIN_STRIDE),
        scale=SCALE_STEP, groupThreshold=0)
    rects = np.asarray(rects).reshape(-1, 4)
    weights = np.asarray(weights, np.float32).ravel()
    if len(rects) == 0:
        return []
    # NMSBoxes keeps only scores STRICTLY above its threshold, and the window
    # scores can be negative; only their order matters here, so they are
    # shifted to start at 1 (starting at 0 dropped the weakest candidate, and
    # every candidate when all scored alike -- tests/vision/test_coins).
    keep = cv2.dnn.NMSBoxes([[int(v) for v in r] for r in rects],
                            [float(w) - float(weights.min()) + 1.0 for w in weights],
                            0.0, STAGE1_OVERLAP)
    x0, y0, x1, y1 = world_box(width, height)
    out = []
    for j in np.asarray(keep).ravel():
        x, y, w, h = rects[int(j)]
        cx, cy = (x + w / 2) / WORK_SCALE, (y + h / 2) / WORK_SCALE
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            out.append((float(cx), float(cy), float(w) / WORK_SCALE, float(weights[int(j)])))
    return out


def crop(work: np.ndarray, cx: float, cy: float, side: float) -> np.ndarray:
    """A CROP_SIZE square of the WORK image round (cx, cy), `side` WORK pixels."""
    scale = CROP_SIZE / max(2.0, side)
    M = np.array([[scale, 0.0, CROP_SIZE / 2 - scale * cx],
                  [0.0, scale, CROP_SIZE / 2 - scale * cy]], np.float32)
    return cv2.warpAffine(work, M, (CROP_SIZE, CROP_SIZE),
                          flags=cv2.INTER_AREA if side > CROP_SIZE else cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REFLECT)


def crop_side(window_side: float) -> float:
    """The stage-2 crop's side, in WORK pixels, for a stage-1 window's side in
    FRAME pixels."""
    return window_side * WORK_SCALE * CROP_PAD / WINDOW_TO_COIN


def confidence_of(logit: float) -> float:
    return float(min(1.0, max(0.0, logit / LOGIT_FULL)))


def merge(found: list, share: float = MERGE_SHARE) -> list:
    """Strongest first; a weaker one centred within `share` of a kept one's
    side, on both axes, is that coin again."""
    kept = []
    for s in sorted(found, key=lambda s: -s[3]):
        if any(abs(s[0] - k[0]) < share * k[2] and abs(s[1] - k[1]) < share * k[2]
               for k in kept):
            continue
        kept.append(s)
    return kept


def look(frame: np.ndarray, m: Model | None = None,
         hit: float = STAGE1_HIT, extra=()) -> list[tuple[float, float, float, float, float]]:
    """Every candidate with its network logit: (cx, cy, coin side, logit,
    stage-1 score), in frame pixels, unmerged and unthresholded -- what the
    trainer measures and `detect` filters. `extra` are more stage-1
    candidates, (cx, cy, window side, score) in frame pixels, from another
    finder (scripts/train_coindet.py eval, the "union" column). Offline
    only: `extra` skips world_box and the non-maximum suppression the live
    stage-1 candidates get, so wire it in live only after adding both."""
    m = m or model()
    if m is None or frame is None or getattr(frame, "size", 0) == 0:
        return []
    height, width = frame.shape[:2]
    work = work_image(frame)
    cands = candidates(work, m, width, height, hit) + list(extra)
    if not cands:
        return []
    batch = np.stack([crop(work, cx * WORK_SCALE, cy * WORK_SCALE, crop_side(side))
                      for cx, cy, side, _ in cands]).astype(np.float32) / 255.0
    out = coinnet.logits(m.params, batch)
    return [(cx, cy, side / WINDOW_TO_COIN, float(z), s1)
            for (cx, cy, side, s1), z in zip(cands, out)]


def kinds_of(frame: np.ndarray, found: list, m: Model | None = None) -> list[str]:
    """For each of `found` ((cx, cy, coin side, ...) in frame pixels), "honey"
    where the honey head is sure, else "unknown"; all "unknown" without one."""
    m = m or model()
    if m is None or m.honey is None or not found or frame is None:
        return ["unknown"] * len(found)
    work = work_image(frame)
    batch = np.stack([crop(work, c[0] * WORK_SCALE, c[1] * WORK_SCALE,
                           c[2] * WORK_SCALE * CROP_PAD)
                      for c in found]).astype(np.float32) / 255.0
    z = coinnet.logits(m.honey, batch)
    p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
    return ["honey" if q >= m.honey_p else "unknown" for q in p]
