"""The small convolutional network that says whether a crop is a token coin.

Stage 2 of `vision/coins` (read that module for why tokens are found this way
at all). Forward pass only: training is `scripts/train_coins.py`, which runs
this same `forward` so the network it measures is the network the bot runs.

THE NETWORK. A 32x32 colour crop, three times [3x3 convolution, ReLU, 2x2
max-pool] with 16, 32 and 64 channels, a 64-unit dense layer with ReLU, and
one output: the logit that the crop is a coin (vision/tokentypes uses the
same shape with one output per token kind). About 89,000 weights, stored
in data/models/coins.npz as float32 beside the stage-1 model. `forward` is
plain numpy -- the trainer's, which needs every layer's arrays -- and the
bot's Python has numpy and OpenCV and nothing else (no torch, no onnx, no
onnxruntime).

THE BOT RUNS IT THROUGH cv2.dnn (`logits`). MEASURED 2026-10-27 on 240
frames of the 8 newest var/incidents/*-token windows (median 26.5
candidates a frame): stage 2 in numpy was 21.0 ms a frame, more than the
HOG candidates (12.6 ms on 4 OpenCV threads); the same weights written as
ONNX (`to_onnx`) and run by cv2.dnn take 0.95 ms on 4 threads and 3.2 on 1,
logits within 4e-6 of numpy's (docs/pending/inferworker.md). A model that
will not load or run there falls back to numpy, and `dnn_error()` says why.
"""
from __future__ import annotations

import os
import tempfile
import threading

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
    out = act @ params["w4"] + params["b4"]
    out = out.ravel() if out.shape[1] == 1 else out     # N logits, or N x classes
    if keep is not None:
        keep.append((a.shape, flat, hidden, act))
    return out


def logits(params: dict, x: np.ndarray, batch: int = 256) -> np.ndarray:
    """`forward`'s answer for a batch of crops, by cv2.dnn when it can (the
    module docstring), else `forward` in batches, so a big look never builds
    one huge im2col."""
    if len(x) == 0:
        return np.zeros(0, np.float32)
    if USE_DNN:
        out = _dnn_logits(params, x)
        if out is not None:
            return out
    return np.concatenate([forward(params, x[s:s + batch])
                           for s in range(0, len(x), batch)])


# ---- cv2.dnn ----------------------------------------------------------------
# False runs every look through `forward` (numpy), the way it ran before
# 2026-10-27.
USE_DNN = True
# ONE NET PER THREAD AND MODEL: a cv2.dnn.Net holds its input and its layers'
# buffers, and the overlay thread and the chaser both look (as vision/coins
# keeps one HOG per thread). A model is its weight arrays, held here so
# their ids are not reused while the net lives: a trainer that assigns new
# arrays (params[k] = ...) gets a new net.
_local = threading.local()
_NETS_KEPT = 8              # coins + honey + typed + sprinkler, with room
_dnn_error = ""


def dnn_error() -> str:
    """Why `logits` fell back to numpy, or "" while it has not."""
    return _dnn_error


def _net_for(params: dict):
    global _dnn_error
    nets = getattr(_local, "nets", None)
    if nets is None:
        nets = _local.nets = {}
    arrays = tuple(params[k] for k in PARAM_NAMES)
    key = tuple(map(id, arrays))
    if key in nets:
        return nets[key][1]
    if _dnn_error:
        return None
    import cv2
    if len(nets) >= _NETS_KEPT:
        nets.clear()
    try:
        # FROM A FILE: readNetFromONNX on bytes segfaulted (OpenCV 5.0.0,
        # 2026-10-12, vision/coindet).
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "coinnet.onnx")
            with open(path, "wb") as f:
                f.write(to_onnx(params, pad=1))
            net = cv2.dnn.readNetFromONNX(path)
    except (cv2.error, OSError, KeyError, ValueError) as err:
        _dnn_error = f"coin network on numpy, cv2.dnn would not load it: {err}"
        return None
    nets[key] = (arrays, net)
    return net


def _dnn_logits(params: dict, x: np.ndarray) -> np.ndarray | None:
    """`forward(params, x)` by cv2.dnn, or None (numpy then answers)."""
    global _dnn_error
    side = 2 ** LAYERS * round((params["w3"].shape[0] / params["w2"].shape[1]) ** 0.5)
    # float32 weights only: a float64 model (the gradient tests) keeps numpy's
    # precision
    if x.ndim != 4 or x.shape[1:] != (side, side, 3) or params["w0"].dtype != np.float32:
        return None
    net = _net_for(params)
    if net is None:
        return None
    import cv2
    try:
        net.setInput(np.ascontiguousarray(x.transpose(0, 3, 1, 2), np.float32))
        out = net.forward().reshape(len(x), -1)
    except cv2.error as err:
        _dnn_error = f"coin network back on numpy, cv2.dnn failed: {err}"
        _local.nets = {}
        return None
    return out.ravel() if out.shape[1] == 1 else out


# ---- ONNX, by hand -----------------------------------------------------------
# Protobuf field numbers from onnx.proto (ModelProto, GraphProto, NodeProto,
# AttributeProto, TensorProto, ValueInfoProto); only what nine nodes need.
# (Moved here from scripts/train_coindet.py, which exports coindet with it.)
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num: int, val) -> bytes:
    """One field: an int as a varint, a str or bytes length-delimited."""
    if isinstance(val, int):
        return _varint(num << 3) + _varint(val)
    if isinstance(val, str):
        val = val.encode()
    return _varint(num << 3 | 2) + _varint(len(val)) + val


def _ints(name, vals):              # AttributeProto: name 1, ints 8, type 20 (INTS 7)
    return _field(1, name) + b"".join(_field(8, v) for v in vals) + _field(20, 7)


def _node(op, ins, outs, *attrs):   # NodeProto: input 1, output 2, op_type 4, attribute 5
    return (b"".join(_field(1, s) for s in ins) + b"".join(_field(2, s) for s in outs)
            + _field(4, op) + b"".join(_field(5, a) for a in attrs))


def _tensor(name, a):               # TensorProto: dims 1, data_type 2 (FLOAT 1), name 8, raw 9
    a = np.ascontiguousarray(a, "<f4")
    return (b"".join(_field(1, d) for d in a.shape) + _field(2, 1) + _field(8, name)
            + _field(9, a.tobytes()))


def _value(name, dims):             # ValueInfoProto -> TypeProto.Tensor (float) -> shape
    shape = b"".join(_field(1, _field(1, d) if isinstance(d, int) else _field(2, d))
                     for d in dims)
    return _field(1, name) + _field(2, _field(1, _field(1, 1) + _field(2, shape)))


def to_onnx(params: dict, pad: int = 0) -> bytes:
    """The network as ONNX: NCHW BGR 0..1 in, logits out. `pad` as `forward`'s:
    0 is vision/coindet's dense network over a whole image (the dense layer
    a 4x4 convolution), 1 the stage-2 network on a batch of crops (each
    answer N x outputs x 1 x 1)."""
    nodes, inits, x = [], [], "image"
    padding = (_ints("pads", [pad] * 4),) if pad else ()
    for i in range(LAYERS):
        w = params[f"w{i}"]
        cin = w.shape[0] // (KERNEL * KERNEL)
        inits += [_tensor(f"w{i}", w.reshape(KERNEL, KERNEL, cin, -1).transpose(3, 2, 0, 1)),
                  _tensor(f"b{i}", params[f"b{i}"])]
        nodes += [_node("Conv", [x, f"w{i}", f"b{i}"], [f"c{i}"],
                        _ints("kernel_shape", [KERNEL, KERNEL]), *padding),
                  _node("Relu", [f"c{i}"], [f"r{i}"]),
                  _node("MaxPool", [f"r{i}"], [f"p{i}"], _ints("kernel_shape", [2, 2]),
                        _ints("strides", [2, 2]))]
        x = f"p{i}"
    c, hidden = params["w2"].shape[1], params["w3"].shape[1]
    outputs = params["w4"].shape[1]
    side = round((params["w3"].shape[0] / c) ** 0.5)
    inits += [_tensor("w3", params["w3"].reshape(side, side, c, hidden).transpose(3, 2, 0, 1)),
              _tensor("b3", params["b3"]),
              _tensor("w4", params["w4"].T.reshape(outputs, hidden, 1, 1)),
              _tensor("b4", params["b4"])]
    nodes += [_node("Conv", [x, "w3", "b3"], ["c3"], _ints("kernel_shape", [side, side])),
              _node("Relu", ["c3"], ["r3"]),
              _node("Conv", ["r3", "w4", "b4"], ["logit"], _ints("kernel_shape", [1, 1]))]
    graph = (b"".join(_field(1, n) for n in nodes) + _field(2, "coindet")
             + b"".join(_field(5, t) for t in inits)
             + _field(11, _value("image", [1 if not pad else "n", 3, "h", "w"]))
             + _field(12, _value("logit", [1 if not pad else "n", outputs, "gh", "gw"])))
    return (_field(1, 8) + _field(2, "hivemind") + _field(7, graph)
            + _field(8, _field(1, "") + _field(2, 13)))          # ir 8, opset 13


def fresh(size: int = 32, chans=(3, 16, 32, 64), hidden: int = 64,
          seed: int = 0, outputs: int = 1) -> dict:
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
    p["w4"] = (rng.standard_normal((hidden, outputs)) * np.sqrt(1 / hidden)).astype(np.float32)
    p["b4"] = np.zeros(outputs, np.float32)
    return p


PARAM_NAMES = tuple([f"{k}{i}" for i in range(LAYERS) for k in ("w", "b")]
                    + ["w3", "b3", "w4", "b4"])
