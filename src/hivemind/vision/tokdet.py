"""Typed token detector v2: ONE network over the whole world view, every coin
and its kind in one pass. An A/B against today's detector (vision/coins).

OFF UNLESS SWITCHED ON. vision/tokens.detect asks vision/coindet, which is
vision/coins (HOG candidates + coinnet) unless something else is on. With the
setting `gather.token_detector_v2` on AND data/models/tokdet.onnx loading,
`look` answers instead; a missing or broken model, or OpenCV failing on a
frame, falls back to vision/coindet's answer and `error()` says why.

THE NETWORK (own design, after CenterNet "Objects as Points", Zhou et al.
2019, and FCOS's two-level assignment; no code or weights from either, see
NOTICE.md). The world box (vision/coins.world_box) is resized to IN_W x IN_H
and run through plain 3x3 convolutions with ReLU, stride 2 to go down
(BACKBONE). Two heads answer, one per level: P3 every 8 input px for small
coins, P4 every 16 for big ones. Each cell says
  0      objectness logit: a coin's centre is in this cell
  1, 2   the coin's centre from the cell's centre, in cells
  3      log(coin side / the level's stride)
  4..    one logit per kind in CLASSES (softmax)
A coin is a cell that is the largest of its 3x3 neighbours and over the
floor. Its kind is the best class when that class is at least `TAU` sure and
not "other", else "unknown".

What it returns is vision/coins.look's shape plus the kind -- (cx, cy, coin
side, logit, 0.0, kind) in frame pixels -- with the logit scaled so that
vision/coins.confidence_of gives the objectness probability back: the
chase confidence cut means "this sure it is a coin" for both detectors.

Training (numpy, no torch on this PC): scripts/train_tokdet.py, which runs
this module's `forward`, so what it measures is what the bot runs; the bot
runs the same weights exported by `to_onnx` through cv2.dnn. Numbers and
limits: docs/pending/tokdet-v2.md.
"""
from __future__ import annotations

import os
import threading

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from ..datapaths import data
from . import coinnet, coins

MODEL = data("models", "tokdet.onnx")
SETTING = "gather.token_detector_v2"

# ---- CONFIG: the network's shape (the trainer and the ONNX file share it) ----
IN_W, IN_H = 640, 320           # the world box (~1632 x 799 at 1080p) shrunk ~0.39x
# (name, input layer, out channels, stride); "image" is the input
BACKBONE = (("c1", "image", 16, 2), ("c2", "c1", 32, 2), ("c3", "c2", 32, 1),
            ("c4", "c3", 64, 2), ("c5", "c4", 64, 1),
            ("c6", "c5", 96, 2), ("c7", "c6", 96, 1))
# (level name, feature layer, stride, hidden channels of its 3x3 head conv)
LEVELS = (("p3", "c5", 8, 64), ("p4", "c7", 16, 64))
CLASSES = ("black_blue_burst", "black_red_burst", "blue_boost", "haste", "honey",
           "item_pineapple", "item_treat", "red_boost", "white_black_flower",
           "yellow_moon", "other")
EXTRA = 4                       # objectness, dx, dy, log side
SPLIT_SIDE = 48.0               # input px: smaller coins are P3's, bigger P4's
TAU = 0.5                       # a kind is named only this sure
FLOOR_P = 0.2                   # cells under this objectness are not reported

_local = threading.local()
_error = ""
_on = False


# ---- the network, numpy (the trainer's forward pass and the tests') ----------
def layers():
    """Every conv as (name, input, cin, cout, kernel, stride, relu)."""
    chans = {"image": 3}
    out = []
    for name, src, cout, stride in BACKBONE:
        out.append((name, src, chans[src], cout, 3, stride, True))
        chans[name] = cout
    for lvl, src, _stride, hidden in LEVELS:
        out.append((f"{lvl}h", src, chans[src], hidden, 3, 1, True))
        out.append((lvl, f"{lvl}h", hidden, EXTRA + len(CLASSES), 1, 1, False))
    return out


def fresh(seed: int = 0) -> dict:
    """He-initialised weights; the objectness bias starts at p 0.01 (focal
    loss practice) so the first steps are not swamped by background."""
    rng = np.random.default_rng(seed)
    p = {}
    for name, _src, cin, cout, k, _s, relu in layers():
        fan = k * k * cin
        scale = np.sqrt(2 / fan) if relu else 0.01
        p[f"{name}.w"] = (rng.standard_normal((fan, cout)) * scale).astype(np.float32)
        p[f"{name}.b"] = np.zeros(cout, np.float32)
    for lvl, *_ in LEVELS:
        p[f"{lvl}.b"][0] = np.log(0.01 / 0.99)
    return p


def im2col(x: np.ndarray, k: int, stride: int) -> np.ndarray:
    """N,H,W,C -> N,Ho,Wo,k*k*C ("same" padding), (ky, kx, c) order."""
    if k == 1:
        return x[:, ::stride, ::stride]
    pad = k // 2
    xp = np.pad(x, ((0, 0), (pad, pad), (pad, pad), (0, 0)))
    win = sliding_window_view(xp, (k, k), axis=(1, 2))[:, ::stride, ::stride]
    n, h, w, c = win.shape[:4]
    return win.transpose(0, 1, 2, 4, 5, 3).reshape(n, h, w, k * k * c)


def forward(params: dict, x: np.ndarray, keep: dict | None = None) -> dict:
    """{level: N x H x W x (EXTRA + classes) raw outputs} for `x`, N x IN_H x
    IN_W x 3 floats in 0..1 (BGR; any size divisible by 16). `keep`, when a
    dict, receives each layer's (cols, pre-activation, output)."""
    acts = {"image": x}
    for name, src, _cin, cout, k, stride, relu in layers():
        cols = im2col(acts[src], k, stride)
        z = cols @ params[f"{name}.w"] + params[f"{name}.b"]
        a = np.maximum(z, 0) if relu else z
        acts[name] = a
        if keep is not None:
            keep[name] = (cols, z, a)
    return {lvl: acts[lvl] for lvl, *_ in LEVELS}


# ---- decoding ------------------------------------------------------------------
def _sig(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def decode(outs: dict, floor: float = FLOOR_P, tau: float = TAU) -> list:
    """Coins in INPUT px from one image's outputs ({level: H x W x C}):
    (cx, cy, side, p, kind, class probabilities)."""
    import cv2
    found = []
    for lvl, _src, stride, _h in LEVELS:
        o = outs[lvl]
        p = _sig(o[..., 0]).astype(np.float32)
        peak = cv2.dilate(p, np.ones((3, 3), np.uint8))
        for i, j in zip(*np.nonzero((p >= floor) & (p >= peak))):
            v = o[i, j]
            cx = (j + 0.5 + float(np.clip(v[1], -2, 2))) * stride
            cy = (i + 0.5 + float(np.clip(v[2], -2, 2))) * stride
            side = float(np.exp(np.clip(v[3], -3, 4))) * stride
            z = v[EXTRA:] - v[EXTRA:].max()
            q = np.exp(z) / np.exp(z).sum()
            c = int(q.argmax())
            kind = CLASSES[c] if q[c] >= tau and CLASSES[c] != "other" else "unknown"
            found.append((float(cx), float(cy), side, float(p[i, j]), kind, q))
    return found


def to_input(frame: np.ndarray):
    """(the network's input image, x0, y0, sx, sy): frame px = x0 + input px / sx."""
    import cv2
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = coins.world_box(width, height)
    img = cv2.resize(np.ascontiguousarray(frame[y0:y1, x0:x1, :3]), (IN_W, IN_H),
                     interpolation=cv2.INTER_AREA)
    return img, x0, y0, IN_W / (x1 - x0), IN_H / (y1 - y0)


def to_frame(found: list, x0, y0, sx, sy) -> list:
    """`decode`'s coins as vision/coins.look's tuples plus the kind."""
    s = (sx + sy) / 2
    return [(x0 + cx / sx, y0 + cy / sy, side / s, p * coins.LOGIT_FULL, 0.0, kind)
            for cx, cy, side, p, kind, _q in found]


# ---- the bot's side: cv2.dnn ------------------------------------------------------
def switch(on: bool) -> None:
    """The setting's value; run_farm sets it each time it reads settings."""
    global _on
    _on = bool(on)


def enabled() -> bool:
    return _on


def error() -> str:
    """Why it fell back to today's detector, or "" while it has not."""
    return _error


def load(path=MODEL):
    import cv2
    # FROM A FILE: readNetFromONNX on bytes segfaulted (OpenCV 5.0.0, vision/coindet).
    return cv2.dnn.readNetFromONNX(str(path))


def _net():
    global _error
    net = getattr(_local, "net", None)
    if net is None and not _error:
        import cv2
        try:
            if not os.path.exists(MODEL):
                raise FileNotFoundError(str(MODEL))
            net = _local.net = load()
        except (cv2.error, OSError) as err:
            _error = f"no token detector v2 ({MODEL.name}): {err}"
    return net


def run(net, frame: np.ndarray, floor: float = FLOOR_P) -> list:
    """Coins in frame px, (cx, cy, side, logit, 0.0, kind)."""
    import cv2
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    img, x0, y0, sx, sy = to_input(frame)
    net.setInput(cv2.dnn.blobFromImage(img, 1 / 255.0))
    names = [lvl for lvl, *_ in LEVELS]
    outs = net.forward(names)
    found = decode({n: o[0].transpose(1, 2, 0) for n, o in zip(names, outs)}, floor)
    return to_frame(found, x0, y0, sx, sy)


def look(frame: np.ndarray) -> list | None:
    """The coins when switched on and working, else None (the caller then
    asks today's detector)."""
    global _error
    if not _on:
        return None
    net = _net()
    if net is None:
        return None
    import cv2
    try:
        return run(net, frame)
    except cv2.error as err:
        _error = f"token detector v2 failed, back on today's: {err}"
        _local.net = None
        return None


# ---- ONNX, by hand (vision/coinnet's protobuf writer) --------------------------------
def to_onnx(params: dict) -> bytes:
    """NCHW BGR 0..1 in ("image", 1 x 3 x IN_H x IN_W), one output per level."""
    f, node, ints, tensor, value = (coinnet._field, coinnet._node, coinnet._ints,
                                    coinnet._tensor, coinnet._value)
    nodes, inits = [], []
    for name, src, cin, cout, k, stride, relu in layers():
        w = params[f"{name}.w"].reshape(k, k, cin, cout).transpose(3, 2, 0, 1)
        inits += [tensor(f"{name}.w", w), tensor(f"{name}.b", params[f"{name}.b"])]
        conv_out = f"{name}.z" if relu else name
        attrs = [ints("kernel_shape", [k, k]), ints("strides", [stride, stride])]
        if k > 1:
            attrs.append(ints("pads", [k // 2] * 4))
        nodes.append(node("Conv", [src, f"{name}.w", f"{name}.b"], [conv_out], *attrs))
        if relu:
            nodes.append(node("Relu", [conv_out], [name]))
    outs = b"".join(f(12, value(lvl, [1, EXTRA + len(CLASSES), IN_H // s, IN_W // s]))
                    for lvl, _src, s, _h in LEVELS)
    graph = (b"".join(f(1, n) for n in nodes) + f(2, "tokdet")
             + b"".join(f(5, t) for t in inits)
             + f(11, value("image", [1, 3, IN_H, IN_W])) + outs)
    return (f(1, 8) + f(2, "hivemind") + f(7, graph)
            + f(8, f(1, "") + f(2, 13)))          # ir 8, opset 13
