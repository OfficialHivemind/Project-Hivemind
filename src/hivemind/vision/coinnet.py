"""The small convolutional network that says whether a crop is a token coin.

Stage 2 of `vision/coins` (read that module for why tokens are found this way
at all). Forward pass only: training is `scripts/train_coins.py`, which runs
this same `forward` so the network it measures is the network the bot runs.

THE NETWORK. A 32x32 colour crop, three times [3x3 convolution, ReLU, 2x2
max-pool] with 16, 32 and 64 channels, a 64-unit dense layer with ReLU, and
one output: the logit that the crop is a coin. About 89,000 weights, stored
in data/models/coins.npz as float32 beside the stage-1 model. Plain numpy --
the bot's Python has numpy and OpenCV and nothing else (no torch, no
onnxruntime), and at this size a batch of 160 crops is a few milliseconds of
matrix products.
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

LAYERS = 3                  # conv blocks; each halves the side
KERNEL = 3


def im2col(x: np.ndarray, k: int = KERNEL) -> np.ndarray:
    """N,H,W,C (already padded) -> N,H-k+1,W-k+1,k*k*C, in (ky, kx, c) order."""
    n, h, w, c = x.shape
    win = sliding_window_view(x, (k, k), axis=(1, 2))           # N,H',W',C,k,k
    return win.transpose(0, 1, 2, 4, 5, 3).reshape(n, h - k + 1, w - k + 1, k * k * c)


def forward(params: dict, x: np.ndarray, keep: list | None = None,
            pad: int = 1) -> np.ndarray:
    """Logits for a batch `x` of N x size x size x 3 floats in 0..1 (BGR).

    `keep`, when a list, receives each layer's intermediate arrays -- the
    trainer's backward pass needs them; the bot passes nothing. `pad` 1 is
    stage 2's same-size convolutions on a 32 px crop; 0 is vision/coindet's
    valid ones on a 46 px window, the network that runs densely over a frame."""
    a = x
    for i in range(LAYERS):
        cols = im2col(np.pad(a, ((0, 0), (pad, pad), (pad, pad), (0, 0))) if pad else a)
        z = cols @ params[f"w{i}"] + params[f"b{i}"]
        r = np.maximum(z, 0)
        n, h, w, c = r.shape
        blocks = r.reshape(n, h // 2, 2, w // 2, 2, c)
        a = blocks.max(axis=(2, 4))
        if keep is not None:
            keep.append((cols, z, blocks, a))
    flat = a.reshape(len(a), -1)
    hidden = flat @ params["w3"] + params["b3"]
    act = np.maximum(hidden, 0)
    out = (act @ params["w4"] + params["b4"]).ravel()
    if keep is not None:
        keep.append((a.shape, flat, hidden, act))
    return out


def logits(params: dict, x: np.ndarray, batch: int = 256) -> np.ndarray:
    """`forward` in batches, so a big look never builds one huge im2col."""
    if len(x) == 0:
        return np.zeros(0, np.float32)
    return np.concatenate([forward(params, x[s:s + batch])
                           for s in range(0, len(x), batch)])


def fresh(size: int = 32, chans=(3, 16, 32, 64), hidden: int = 64,
          seed: int = 0) -> dict:
    """He-initialised weights for a new network (the trainer's start)."""
    rng = np.random.default_rng(seed)
    p = {}
    for i in range(LAYERS):
        cin, cout = chans[i], chans[i + 1]
        fan = KERNEL * KERNEL * cin
        p[f"w{i}"] = (rng.standard_normal((fan, cout)) * np.sqrt(2 / fan)).astype(np.float32)
        p[f"b{i}"] = np.zeros(cout, np.float32)
    flat = (size // 2 ** LAYERS) ** 2 * chans[-1]
    p["w3"] = (rng.standard_normal((flat, hidden)) * np.sqrt(2 / flat)).astype(np.float32)
    p["b3"] = np.zeros(hidden, np.float32)
    p["w4"] = (rng.standard_normal((hidden, 1)) * np.sqrt(1 / hidden)).astype(np.float32)
    p["b4"] = np.zeros(1, np.float32)
    return p


PARAM_NAMES = tuple([f"{k}{i}" for i in range(LAYERS) for k in ("w", "b")]
                    + ["w3", "b3", "w4", "b4"])
