#!/usr/bin/env python3
"""Build, train and measure vision/coindet, the dense coin detector (backlog R8).

    ./scripts/train_coindet.py build [--limit N]      the training windows
    ./scripts/train_coindet.py train [--holdout K]    the network, as ONNX
    ./scripts/train_coindet.py eval  --holdout K      it against vision/coins
    ./scripts/train_coindet.py selfcheck              the exporter and the maths

NOTHING NEW IS LABELLED BY HAND. The labels are vision/coins' own,
data/models/coin_labels.json: 452 frames, 550 coins (496 sure) -- 120 frames
of Pineapple Patch pickup windows boxed whole by eye, 332 of other fields
where only the old detector's boxes were reviewed (coins and `not_coins`).
var/school-coins was looked at and left out: its 1,364 "collected" chases
are 48 px crops of a fixed size round the chase point, not the coin's box,
and a collected verdict does not say WHICH thing was picked up.

BUILD cuts every training window the way vision/coindet.look sees one --
the frame shrunk with INTER_AREA until the coin is COIN_IN_WINDOW px, then a
WINDOW px square round it: each sure coin POS_AUG times (shifted up to half
a stride, resized up to half a pyramid step, turned, mirrored, recoloured,
so every coin meets a cell and a pass that see it as trained), NEG_RANDOM
background windows a frame clear of every box, and each reviewed not-a-coin
NOT_COIN_AUG times. They go to a memmapped uint8 .npy under
~/.cache/hivemind-work/datasets/coindet/, never all in memory, with the
fold of every frame -- train_coins.folds, the rule coins.json was measured
with, so a held-out fold here is a held-out fold there.

TRAIN is train_coins' own stage-2 trainer (Adam, class-weighted cross-
entropy, coinnet's forward pass with pad=0 and the backward pass beside it):
a first round on the built windows, then ONE ROUND OF HARD NEGATIVES -- the
network run densely over its own training frames, every merged detection
`train_coins.truth` calls nothing (never an unreviewed spot of a partial
frame) cut as a window -- and a shorter second round from the first one's
weights. --holdout K leaves fold K's frames out of both rounds.

EVAL scores fold K's frames with the network trained without them, and with
vision/coins trained by train_coins.train on the same other folds, by
train_coins.score -- the strict scoring of coins.json's table -- and times a
look by each.

ONNX WITHOUT THE onnx PACKAGE. The venv has numpy and OpenCV and nothing
else (no torch, no onnx, no onnxruntime, 2026-10-12), so `to_onnx` writes
the protobuf itself: nine plain nodes. `selfcheck` proves cv2.dnn computes
from it what coinnet.forward computes, crop by crop across a whole image.

It never touches the game. Run it niced, OPENBLAS_NUM_THREADS low, under
~/.cache/hivemind-work/tools/capped while the owner plays.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import cv2                                                      # noqa: E402
import numpy as np                                              # noqa: E402

import train_coins as tc                                        # noqa: E402
from hivemind.vision import coindet, coinnet, coins             # noqa: E402

DATASET = Path.home() / ".cache/hivemind-work/datasets/coindet"

# ---- the training windows ----------------------------------------------------
POS_AUG = tc.S2_POS_AUG     # 30 windows per sure coin, the first one plain
NEG_RANDOM = 150            # background windows per frame (stage 2 took 100 behind HOG)
NOT_COIN_AUG = tc.NOT_COIN_AUG
HALF_STEP = float(np.sqrt(coindet.LEVEL_STEP))
SHIFT = coindet.STRIDE / 2 / coindet.COIN_IN_WINDOW     # half a stride, in coin sides

# ---- training ----------------------------------------------------------------
EPOCHS = 12
MINE_EPOCHS = 4
HARD_PER_FRAME = 40         # strongest false detections kept from each frame


def window_crop(img, cx, cy, side, angle=0.0, flip=False):
    """The WINDOW px square the network sees round a coin of `side` frame px
    at (cx, cy) of the full frame: shrunk with INTER_AREA as `look` shrinks
    the frame, then turned and placed at scale 1."""
    s = coindet.COIN_IN_WINDOW / side
    half = int(np.ceil(coindet.WINDOW / s))       # twice the window's half: room to turn
    x0, y0 = max(0, int(cx) - half), max(0, int(cy) - half)
    region = img[y0:int(cy) + half, x0:int(cx) + half]
    small = cv2.resize(region, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    scx = (cx - x0) * small.shape[1] / region.shape[1]
    scy = (cy - y0) * small.shape[0] / region.shape[0]
    M = cv2.getRotationMatrix2D((float(scx), float(scy)), float(angle), 1.0)
    M[0, 2] += coindet.WINDOW / 2 - scx
    M[1, 2] += coindet.WINDOW / 2 - scy
    out = cv2.warpAffine(small, M, (coindet.WINDOW, coindet.WINDOW),
                         flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return cv2.flip(out, 1) if flip else out


def centre_side(box):
    x0, y0, x1, y1 = box
    return (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0)


def jittered(img, box, k, rng, recolour=False):
    """A box's window `k`: 0 plain, then shifted/resized/turned/mirrored."""
    cx, cy, side = centre_side(box)
    if k == 0:
        return window_crop(img, cx, cy, side)
    dx, dy = rng.uniform(-SHIFT, SHIFT, 2) * side
    s = side * float(np.exp(rng.uniform(-np.log(HALF_STEP), np.log(HALF_STEP))))
    c = window_crop(img, cx + dx, cy + dy, s, rng.uniform(-12, 12), bool(k % 2))
    return tc.colour_jitter(c, rng) if recolour else c


# ---- build -------------------------------------------------------------------
def build(args) -> int:
    root, out = Path(args.root), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    frames = [f for f in json.loads(tc.LABELS.read_text())["frames"]
              if (root / f["path"]).exists()]
    fold_of = tc.folds(frames)                   # before --limit: the folds coins.json used
    if args.limit:
        frames = frames[::max(1, len(frames) // args.limit)][:args.limit]
    bound = sum(POS_AUG * sum(c["sure"] for c in f["coins"])
                + NOT_COIN_AUG * len(f.get("not_coins", ())) + NEG_RANDOM for f in frames)
    X = np.lib.format.open_memmap(out / "windows.npy", "w+", np.uint8,
                                  (bound, coindet.WINDOW, coindet.WINDOW, 3))
    y = np.zeros(bound, np.uint8)
    src = np.zeros(bound, np.int16)
    rng = np.random.default_rng(0)
    n, meta = 0, []
    for i, f in enumerate(frames):
        img = cv2.imread(str(root / f["path"]))
        h, w = img.shape[:2]
        pos = [jittered(img, c["box"], k, rng, recolour=True)
               for c in f["coins"] if c["sure"] for k in range(POS_AUG)]
        neg = [jittered(img, b["box"], k, rng)
               for b in f.get("not_coins", ()) for k in range(NOT_COIN_AUG)]
        neg += [window_crop(img, cx, cy, side)
                for cx, cy, side in tc.background_points({**f, "full": (h, w)}, rng, NEG_RANDOM)]
        for rows, label in ((pos, 1), (neg, 0)):
            if rows:
                X[n:n + len(rows)] = np.stack(rows)
                y[n:n + len(rows)], src[n:n + len(rows)] = label, i
                n += len(rows)
        meta.append({"path": f["path"], "window": f["window"], "fold": fold_of[f["window"]],
                     "partial": bool(f.get("partial")), "full": [h, w]})
        if i % 50 == 0:
            tc.log(f"  frame {i + 1}/{len(frames)}: {n} windows")
    X.flush()
    np.save(out / "labels.npy", y[:n])
    np.save(out / "frames.npy", src[:n])
    (out / "meta.json").write_text(json.dumps({
        "made": time.strftime("%Y-%m-%d %H:%M:%S"), "labels": tc.LABELS.name,
        "rows": n, "coin_windows": int(y[:n].sum()), "other_windows": int(n - y[:n].sum()),
        "window": coindet.WINDOW, "coin_in_window": coindet.COIN_IN_WINDOW,
        "pos_aug": POS_AUG, "neg_random": NEG_RANDOM, "frames": meta}, indent=1) + "\n")
    tc.log(f"wrote {n} windows ({int(y[:n].sum())} coin) of {len(frames)} frames to {out}")
    return 0


class Rows:
    """The chosen rows of the memmapped windows, then the mined ones, as
    train_coins.train_stage2 indexes its X -- read a batch at a time."""

    def __init__(self, X, rows, extra):
        self.X, self.rows, self.extra = X, np.asarray(rows), extra

    def __len__(self):
        return len(self.rows) + len(self.extra)

    def __getitem__(self, idx):
        idx = np.asarray(idx)
        n = len(self.rows)
        out = np.empty((len(idx),) + self.X.shape[1:], np.uint8)
        a = idx < n
        out[a] = self.X[self.rows[idx[a]]]
        if (~a).any():
            out[~a] = self.extra[idx[~a] - n]
        return out


def labelled(meta, root, keep):
    """The labelled frames of `meta` whose fold `keep` accepts, as train_coins'
    Frames (the work image read from disk when asked for)."""
    labels = {f["path"]: f for f in json.loads(tc.LABELS.read_text())["frames"]}
    return [tc.Frame({**labels[m["path"]], "full": tuple(m["full"]),
                      "_file": str(root / m["path"])})
            for m in meta["frames"] if keep(m["fold"])]


def net_of(params):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "coindet.onnx"
        path.write_bytes(to_onnx(params))
        return coindet.load(path)


# ---- train -------------------------------------------------------------------
def train(args) -> int:
    started = time.time()
    data_dir, root = Path(args.out), Path(args.root)
    meta = json.loads((data_dir / "meta.json").read_text())
    X = np.load(data_dir / "windows.npy", mmap_mode="r")
    y = np.load(data_dir / "labels.npy")
    fold = np.array([m["fold"] for m in meta["frames"]])[np.load(data_dir / "frames.npy")]
    rows = np.nonzero(fold != args.holdout)[0]
    held = f"fold {args.holdout} held out" if args.holdout >= 0 else "every fold"
    tc.log(f"round 1: {len(rows)} windows ({int(y[rows].sum())} coin), {held}")
    empty = np.zeros((0,) + X.shape[1:], np.uint8)
    params = tc.train_stage2(Rows(X, rows, empty), y[rows], args.epochs, seed=0, pad=0)

    net = net_of(params)
    hard = []
    frames = labelled(meta, root, lambda k: k != args.holdout)
    for f in frames:
        img = cv2.imread(f["_file"])
        dets = coins.merge(coindet.look_with(net, img))
        wrong = [d for d in dets if tc.truth(f, d[0], d[1], d[2]) == 0][:HARD_PER_FRAME]
        hard += [window_crop(img, d[0], d[1], d[2]) for d in wrong]
    hard = np.array(hard, np.uint8).reshape((-1,) + X.shape[1:])
    tc.log(f"round 2: {len(hard)} hard negatives from {len(frames)} training frames")
    params = tc.train_stage2(Rows(X, rows, hard), np.r_[y[rows], np.zeros(len(hard))],
                             args.mine_epochs, seed=1, pad=0, init=params)

    out = Path(args.onnx or data_dir / (f"coindet-holdout{args.holdout}.onnx"
                                         if args.holdout >= 0 else "coindet.onnx"))
    out.write_bytes(to_onnx(params))
    out.with_suffix(".json").write_text(json.dumps({
        "made": time.strftime("%Y-%m-%d %H:%M:%S"), "dataset": str(data_dir),
        "dataset_made": meta["made"], "holdout": args.holdout, "windows": int(len(rows)),
        "hard_negatives": int(len(hard)), "epochs": args.epochs,
        "mine_epochs": args.mine_epochs, "seconds": round(time.time() - started)},
        indent=1) + "\n")
    tc.log(f"wrote {out}")
    return 0


# ---- eval --------------------------------------------------------------------
def timed_looks(frames, look):
    looks, ms = [], []
    for f in frames:
        img = cv2.imread(f["_file"])
        t = time.perf_counter()
        looks.append(look(img))
        ms.append((time.perf_counter() - t) * 1000)
    return looks, round(statistics.median(ms), 1) if ms else None


def evaluate(args) -> int:
    data_dir, root, k = Path(args.out), Path(args.root), args.holdout
    meta = json.loads((data_dir / "meta.json").read_text())
    held = labelled(meta, root, lambda fold: fold == k)
    rest = labelled(meta, root, lambda fold: fold != k)
    onnx = Path(args.onnx or data_dir / f"coindet-holdout{k}.onnx")
    net = coindet.load(onnx)
    new, new_ms = timed_looks(held, lambda img: coindet.look_with(net, img))
    tc.log(f"vision/coins retrained on the same {len(rest)} frames, for the comparison")
    old_model = tc.train(rest, args.epochs)
    old, old_ms = timed_looks(held, lambda img: coins.look(img, old_model))
    # THE UNION: the dense net's hits as extra stage-1 candidates for
    # vision/coins' own network, which still decides -- does it win back the
    # coins HOG never offers (11% MEASURED 2026-10-21) without the dense
    # net's false ones? MEASURED 2026-10-21 22:31, fold 0, 59 whole-labelled
    # coins: at 0.50 union P 0.716 R 0.746 against coins P 0.878 R 0.678; at
    # 0.70 P 0.824 R 0.661 against 0.923 / 0.576; 151 ms a look against 55.
    # It buys recall with precision the network cannot win back: not shipped.
    uni, uni_ms = timed_looks(held, lambda img: coins.look(img, old_model, extra=[
        (d[0], d[1], d[2] * coins.WINDOW_TO_COIN, 0.0)
        for d in coins.merge(coindet.look_with(net, img))]))
    table = {"fold": k, "frames": len(held), "onnx": str(onnx),
             "ms_per_look": {"coindet": new_ms, "coins": old_ms, "union": uni_ms}, "groups": {}}
    for group, keep in (("labelled whole", lambda f: not f.get("partial")),
                        ("reviewed detections", lambda f: f.get("partial"))):
        idx = [i for i, f in enumerate(held) if keep(f)]
        if not idx:
            continue
        rows = table["groups"][group] = {}
        for cut in tc.THRESHOLDS:
            a = tc.score([held[i] for i in idx], [new[i] for i in idx], cut)
            b = tc.score([held[i] for i in idx], [old[i] for i in idx], cut)
            u = tc.score([held[i] for i in idx], [uni[i] for i in idx], cut)
            rows[f"{cut:.2f}"] = {"coindet": a, "coins": b, "union": u}
            tc.log(f"  {group} >= {cut:.2f}: coindet P {a['precision']:.3f} R {a['recall']:.3f}"
                   f" | coins P {b['precision']:.3f} R {b['recall']:.3f}"
                   f" | union P {u['precision']:.3f} R {u['recall']:.3f}  ({a['coins']} coins)")
    tc.log(f"  a look: coindet {new_ms} ms, coins {old_ms} ms, union {uni_ms} ms (median)")
    path = data_dir / f"eval-holdout{k}.json"
    path.write_text(json.dumps(table, indent=1) + "\n")
    tc.log(f"wrote {path}")
    return 0


# ---- ONNX, by hand -----------------------------------------------------------
# Protobuf field numbers from onnx.proto (ModelProto, GraphProto, NodeProto,
# AttributeProto, TensorProto, ValueInfoProto); only what nine nodes need.
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


def to_onnx(params: dict) -> bytes:
    """coinnet's weights as the dense network: NCHW BGR 0..1 in, logits out."""
    nodes, inits, x = [], [], "image"
    for i in range(coinnet.LAYERS):
        w = params[f"w{i}"]
        cin = w.shape[0] // (coinnet.KERNEL * coinnet.KERNEL)
        k3 = coinnet.KERNEL
        inits += [_tensor(f"w{i}", w.reshape(k3, k3, cin, -1).transpose(3, 2, 0, 1)),
                  _tensor(f"b{i}", params[f"b{i}"])]
        nodes += [_node("Conv", [x, f"w{i}", f"b{i}"], [f"c{i}"], _ints("kernel_shape", [k3, k3])),
                  _node("Relu", [f"c{i}"], [f"r{i}"]),
                  _node("MaxPool", [f"r{i}"], [f"p{i}"], _ints("kernel_shape", [2, 2]),
                        _ints("strides", [2, 2]))]
        x = f"p{i}"
    c, hidden = params["w2"].shape[1], params["w3"].shape[1]
    side = round((params["w3"].shape[0] / c) ** 0.5)
    inits += [_tensor("w3", params["w3"].reshape(side, side, c, hidden).transpose(3, 2, 0, 1)),
              _tensor("b3", params["b3"]),
              _tensor("w4", params["w4"].T.reshape(1, hidden, 1, 1)), _tensor("b4", params["b4"])]
    nodes += [_node("Conv", [x, "w3", "b3"], ["c3"], _ints("kernel_shape", [side, side])),
              _node("Relu", ["c3"], ["r3"]),
              _node("Conv", ["r3", "w4", "b4"], ["logit"], _ints("kernel_shape", [1, 1]))]
    graph = (b"".join(_field(1, n) for n in nodes) + _field(2, "coindet")
             + b"".join(_field(5, t) for t in inits)
             + _field(11, _value("image", [1, 3, "h", "w"]))
             + _field(12, _value("logit", [1, 1, "gh", "gw"])))
    return (_field(1, 8) + _field(2, "hivemind") + _field(7, graph)
            + _field(8, _field(1, "") + _field(2, 13)))          # ir 8, opset 13


# ---- selfcheck ---------------------------------------------------------------
def selfcheck(args) -> int:
    """The exported network is coinnet.forward(pad=0) at every 8 px window of
    an image, and train_coins.backward(pad=0) is its gradient."""
    rng = np.random.default_rng(3)
    params = coinnet.fresh(seed=1)
    params = {k: (v + rng.normal(0, 0.05, v.shape)).astype(np.float32) for k, v in params.items()}
    img = rng.integers(0, 256, (110, 150, 3), np.uint8)
    net = net_of(params)
    net.setInput(cv2.dnn.blobFromImage(img, 1 / 255.0))
    dense = net.forward()[0, 0]
    W, S = coindet.WINDOW, coindet.STRIDE
    assert dense.shape == ((110 - W) // S + 1, (150 - W) // S + 1), dense.shape
    crops = np.stack([img[i * S:i * S + W, j * S:j * S + W]
                      for i in range(dense.shape[0]) for j in range(dense.shape[1])])
    want = coinnet.forward(params, crops.astype(np.float32) / 255.0, pad=0)
    assert np.allclose(dense.ravel(), want, atol=1e-3), np.abs(dense.ravel() - want).max()

    x = crops[:3].astype(np.float64) / 255.0
    p64 = {k: v.astype(np.float64) for k, v in params.items()}
    cache: list = []
    coinnet.forward(p64, x, keep=cache, pad=0)
    grad = tc.backward(p64, cache, np.ones(len(x)), pad=0)
    for name in coinnet.PARAM_NAMES:                  # each one's largest gradient
        at = np.unravel_index(np.abs(grad[name]).argmax(), grad[name].shape)
        bumped = {k: v.copy() for k, v in p64.items()}
        bumped[name][at] += 1e-5
        numeric = (coinnet.forward(bumped, x, pad=0).sum()
                   - coinnet.forward(p64, x, pad=0).sum()) / 1e-5
        assert abs(numeric - grad[name][at]) <= 1e-3 + 1e-2 * abs(numeric), (name, numeric, grad[name][at])

    frame = np.zeros((1080, 1920, 3), np.uint8)
    assert coindet.look_with(net, frame, floor=-1e9), "a look over a frame found no windows"
    print("selfcheck ok: ONNX == coinnet.forward(pad=0) on every window; backward(pad=0) == finite differences")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("build", "train", "eval", "selfcheck"))
    ap.add_argument("--root", default=str(Path.home() / "Hivemind"),
                    help="the live tree whose var/ holds the labelled frames (read only)")
    ap.add_argument("--out", default=str(DATASET), help="the dataset directory")
    ap.add_argument("--limit", type=int, default=0, help="build: only this many frames")
    ap.add_argument("--holdout", type=int, default=-1,
                    help="train/eval: the fold (0-4) left out; train -1 = every frame")
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    ap.add_argument("--mine-epochs", type=int, default=MINE_EPOCHS)
    ap.add_argument("--onnx", default="", help="the model file to write (train) or score (eval)")
    ap.add_argument("--threads", type=int, default=2,
                    help="OpenCV's threads (numpy's are OPENBLAS_NUM_THREADS)")
    args = ap.parse_args()
    cv2.setNumThreads(args.threads)
    if args.command == "eval" and args.holdout < 0:
        ap.error("eval needs --holdout K, the fold the model was trained without")
    return {"build": build, "train": train, "eval": evaluate, "selfcheck": selfcheck}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
