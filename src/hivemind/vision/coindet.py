"""Token coins found by ONE small network run over the whole frame (backlog R8).

OFF UNLESS SWITCHED ON. `look` is vision/coins.look -- today's detector --
unless the bot's environment has HIVEMIND_COINDET=1 AND data/models/
coindet.onnx loads; a missing or broken model, or OpenCV failing on a frame,
falls back to vision/coins and `error()` says why. Switching it on with no
model changes nothing.

WHY A SECOND COIN DETECTOR. vision/coins finds candidates with HOG and lets
the small network of vision/coinnet decide. MEASURED (data/models/coins.json,
2026-10-07, five folds by pickup window, 246 sure coins on 120 fully
labelled frames): only 218 of the 246 are ever among the HOG candidates, so
11% of the coins are gone before the network looks; recall at confidence
0.40 is 0.707, precision 0.721. Here the network itself looks at every
position. It is coinnet's own shape -- three blocks of [3x3 convolution,
ReLU, 2x2 max-pool] with 16, 32 and 64 channels, a 64-unit layer, one logit
-- with VALID (unpadded) convolutions, so on a 46 px window it ends in a 4x4
map and the dense layer is a 4x4 convolution. On a whole frame the same
network then answers for a 46 px window every 8 px, and each answer is
exactly what it says about that window as a crop -- which is how
scripts/train_coindet.py trains it, on crops, with coinnet's own forward
pass and train_coins' backward pass.

SIZES BY A PYRAMID. The network knows one coin size: COIN_IN_WINDOW px
across, the share of its window a coin fills in stage 2's crop. The world
part of the frame is shrunk so that a coin of SIDES[0] frame px is that
size, then by LEVEL_STEP again and again until a coin of SIDES[1] is; 13
passes. The smallest labelled coin is 42 px, 90% are under 260
(coin_labels.json, 550 coins).

What it returns is vision/coins.look's shape -- (cx, cy, coin side, logit,
0.0) in frame pixels, unmerged -- so vision/tokens.detect thresholds, merges
and names (the honey head) exactly as before. There is no stage-1 score; the
last field is 0.

cv2.dnn runs it: OpenCV 5.0 is in the venv, torch and onnxruntime are not,
and cv2.dnn.readNetFromONNX loads it from a FILE (from bytes it segfaulted,
OpenCV 5.0.0, 2026-10-12). ONE NET PER THREAD, as coins keeps one HOG per
thread: the overlay thread and the chaser both look.
"""
from __future__ import annotations

import os
import threading

import cv2
import numpy as np

from ..datapaths import data
from . import coins

MODEL = data("models", "coindet.onnx")
SWITCH = "HIVEMIND_COINDET"     # "1" in the environment turns it on

# ---- the window, as the trainer cuts it and the network sees it -------------
WINDOW = 46                     # 3 x (valid 3x3 conv, pool 2) then a 4x4 conv -> 1
STRIDE = 8                      # three 2x2 pools
COIN_IN_WINDOW = coins.CROP_SIZE / coins.CROP_PAD    # 25.6 px, as stage 2 sees one

# ---- the pyramid -------------------------------------------------------------
SIDES = (42.0, 420.0)           # coin sides looked for, frame px
LEVEL_STEP = 1.2                # coin size between two passes

# Cells under this logit are not reported (vision/tokens drops them anyway).
REPORT_LOGIT = float(np.log(coins.REPORT_P / (1.0 - coins.REPORT_P)))

_local = threading.local()
_error = ""


def enabled() -> bool:
    return os.environ.get(SWITCH) == "1"


def error() -> str:
    """Why it fell back to vision/coins, or "" while it has not."""
    return _error


def load(path=MODEL) -> cv2.dnn.Net:
    return cv2.dnn.readNetFromONNX(str(path))


def _net():
    global _error
    net = getattr(_local, "net", None)
    if net is None and not _error:
        try:
            net = _local.net = load()
        except cv2.error as err:
            _error = f"no coin detector net ({MODEL.name}): {err}"
    return net


def look(frame: np.ndarray) -> list[tuple[float, float, float, float, float]]:
    """vision/coins.look's answer -- from this network when switched on."""
    global _error
    if enabled():
        net = _net()
        if net is not None:
            try:
                return look_with(net, frame)
            except cv2.error as err:
                _error = f"coin detector failed, back on vision/coins: {err}"
                _local.net = None
    return coins.look(frame)


def levels() -> list[float]:
    """The coin sides, frame px, the pyramid's passes are for."""
    out, side = [], SIDES[0]
    while side <= SIDES[1] + 1e-6:
        out.append(side)
        side *= LEVEL_STEP
    return out


def look_with(net, frame: np.ndarray, floor: float = REPORT_LOGIT) -> list:
    """Every window at or over `floor`, every pass: (cx, cy, coin side,
    logit, 0.0) in frame pixels."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = coins.world_box(width, height)
    world = np.ascontiguousarray(frame[y0:y1, x0:x1, :3])
    out = []
    for side in levels():
        s = COIN_IN_WINDOW / side
        lw, lh = round(world.shape[1] * s), round(world.shape[0] * s)
        if min(lw, lh) < WINDOW:
            break
        img = cv2.resize(world, (lw, lh), interpolation=cv2.INTER_AREA)
        net.setInput(cv2.dnn.blobFromImage(img, 1 / 255.0))
        z = net.forward()[0, 0]
        sx, sy = world.shape[1] / lw, world.shape[0] / lh
        for i, j in zip(*np.nonzero(z >= floor)):
            out.append((x0 + (j * STRIDE + WINDOW / 2) * sx,
                        y0 + (i * STRIDE + WINDOW / 2) * sy,
                        COIN_IN_WINDOW * sx, float(z[i, j]), 0.0))
    return out
