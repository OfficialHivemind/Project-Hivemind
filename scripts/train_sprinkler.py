#!/usr/bin/env python3
"""Train the sprinkler (Golden Gusher) finder, vision/sprinkler, and measure it.

    OPENBLAS_NUM_THREADS=2 nice -n 19 capped --mem 3000M \
        python3 scripts/train_sprinkler.py [--epochs 12] [--out data/models/sprinkler.npz]

DATA: the self-labelled set of scripts/build_sprinkler_dataset.py
(--data, default $HIVEMIND_WORK/datasets/sprinkler): half-size route
frames from gathers, split BY RUN 70/15/15, labelled per frame
  sprinkler       Gusher era, after a placing, boxes from the builder's
                  HOG verifier at 0.9 (eye-checked precision 0.956)
  absent_certain  before run 896: no Gusher existed, so no proposal is one
  unlabelled      Gusher era, nothing verified: off screen OR missed
Every stage-1 proposal (vision/sprinkler.proposals) of those frames becomes a
32x32 crop, labelled
  1   overlaps a label box (IoU >= MATCH_IOU)
  0   on an absent_certain frame, or the builder's verifier scores it under
      LOW (the Gusher era's bees, tokens and glints)
  ignored otherwise -- an unverified tan post may be a Gusher the labeller
      missed, and teaching it "no" would teach the misses.
The network is vision/coinnet's (forward pass shared with the bot, backward
pass scripts/train_coins.backward), Adam on class-weighted cross-entropy.

THE LABELS ARE THE LABELLER'S. Measured against them, the network can only
show how well it copies the labeller. The numbers that count are the EYE-
GRADED ones: the builder's eyecheck/graded.json (boxes graded by eye; E1 was
used to pick the labeller's threshold, E2/E3 are test-split) and
--frame-grades (whole test frames graded by eye, see docs/pending/ai-sprinkler.md).
It never touches the game and reads ~/Hivemind/var only for latency.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cv2                                                      # noqa: E402
import numpy as np                                              # noqa: E402

from hivemind.datapaths import data                             # noqa: E402
from hivemind.vision import coinnet, sprinkler                  # noqa: E402

DATA = Path(os.environ.get("HIVEMIND_WORK") or Path.home() / ".cache/hivemind-dev") / "datasets/sprinkler"
MATCH_IOU = 0.4
LOW = 0.3
POS_AUG = 6                 # jittered/mirrored copies of each positive
CUTS = (0.3, 0.5, 0.7, 0.8, 0.9, 0.95)

_spec = importlib.util.spec_from_file_location("train_coins", ROOT / "scripts" / "train_coins.py")
train_coins = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(train_coins)


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ---- the builder's verifier, to pick certain negatives in the Gusher era -----
HOG = cv2.HOGDescriptor((32, 64), (16, 16), (8, 8), (8, 8), 9)


def verifier_features(work: np.ndarray, box, s: float = 2.0) -> np.ndarray:
    """scripts/build_sprinkler_dataset.features, on the half-size frame
    (box in work px, shape terms in full-frame px as it was trained)."""
    x, y, w, h = box
    H, W = work.shape[:2]
    px, py = int(w * 0.2), int(h * 0.2)
    c = work[max(0, y - py):min(H, y + h + py), max(0, x - px):min(W, x + w + px)]
    patch = cv2.resize(c, (32, 64), interpolation=cv2.INTER_AREA)
    hog = HOG.compute(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)).ravel()
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    hist = np.concatenate([cv2.calcHist([hsv], [0], None, [16], [0, 180]).ravel(),
                           cv2.calcHist([hsv], [1], None, [8], [0, 256]).ravel()]) / (32 * 64.0)
    fw, fh = w * s, h * s
    shape = np.array([fh / max(1.0, fw), np.log1p(fw * fh) / 12.0, y / float(H)], np.float32)
    return np.concatenate([hog, hist, shape]).astype(np.float32)


def verifier(path: Path):
    m = json.loads(path.read_text())["model"]
    mu, sd, w, b = np.array(m["mu"]), np.array(m["sd"]), np.array(m["w"]), float(m["b"])
    return lambda X: 1.0 / (1.0 + np.exp(-(((X - mu) / sd) @ w + b)))


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / float(aw * ah + bw * bh - inter) if inter else 0.0


def prepare(root: Path) -> dict:
    """Every proposal of every manifest frame: crop, label, split, frame."""
    cache = root / "train-cache.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=False)
        return {k: z[k] for k in z.files}
    score = verifier(root / "verifier.json")
    rows = [json.loads(ln) for ln in (root / "manifest.jsonl").open()]
    crops, ys, splits, frames, boxes, vs = [], [], [], [], [], []
    t0 = time.time()
    for i, r in enumerate(rows):
        work = cv2.imread(str(root / r["image"]))
        if work is None:
            continue
        s = 1.0 / r["image_scale"]
        truth = [[v / s for v in b["box"]] for b in r["boxes"]]
        props = sprinkler.proposals(work)
        if not props:
            continue
        V = score(np.stack([verifier_features(work, b, s) for b in props]))
        for b, v in zip(props, V):
            if r["label"] == "absent_certain":
                y = 0
            elif any(iou(b, t) >= MATCH_IOU for t in truth):
                y = 1
            elif v < LOW:
                y = 0
            else:
                y = -1
            crops.append(sprinkler.crop(work, b))
            ys.append(y)
            splits.append(r["split"])
            frames.append(i)
            boxes.append(b)
            vs.append(v)
        if i % 1000 == 0:
            log(f"  {i}/{len(rows)} frames, {len(ys)} proposals ({time.time() - t0:.0f}s)")
    out = {"crops": np.array(crops, np.uint8), "y": np.array(ys, np.int8),
           "split": np.array(splits), "frame": np.array(frames, np.int32),
           "box": np.array(boxes, np.int32), "verifier": np.array(vs, np.float32)}
    np.savez_compressed(cache, **out)
    return out


def augment(work_crop: np.ndarray, rng) -> np.ndarray:
    """A positive moved, resized, mirrored and recoloured a little."""
    c = work_crop
    side = c.shape[0]
    sc = rng.uniform(0.88, 1.15)
    dx, dy = rng.uniform(-0.08, 0.08, 2) * side
    M = np.array([[sc, 0, (1 - sc) * side / 2 + dx], [0, sc, (1 - sc) * side / 2 + dy]], np.float32)
    c = cv2.warpAffine(c, M, (side, side), borderMode=cv2.BORDER_REPLICATE)
    if rng.random() < 0.5:
        c = c[:, ::-1]
    return np.clip(c.astype(np.float32) * rng.uniform(0.85, 1.15)
                   + rng.uniform(-12, 12), 0, 255).astype(np.uint8)


def prf(scores, truth, cut) -> dict:
    tp = int(((scores >= cut) & truth).sum())
    fp = int(((scores >= cut) & ~truth).sum())
    fn = int(((scores < cut) & truth).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"P": round(p, 3), "R": round(r, 3),
            "F1": round(2 * p * r / (p + r), 3) if p + r else 0.0, "tp": tp, "fp": fp, "fn": fn}


def probs(params, crops) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(coinnet.logits(params, crops.astype(np.float32) / 255.0),
                                        -30, 30)))


def eye_graded(root: Path, params) -> dict:
    """The builder's boxes graded by eye, scored by this network."""
    path = root / "eyecheck" / "graded.json"
    sets: dict[str, list] = {}
    for g in json.loads(path.read_text()):
        img = cv2.imread(g["source"])
        if img is None:
            continue
        work, s = sprinkler.to_work(img)
        b = [int(round(v / s)) for v in g["box"]]
        sets.setdefault(g["set"], []).append((sprinkler.crop(work, b), bool(g["sprinkler"])))
    out = {}
    for name, items in sorted(sets.items()):
        p = probs(params, np.stack([c for c, _ in items]))
        t = np.array([t for _, t in items])
        out[name] = {"n": len(t), "true": int(t.sum()),
                     **{f"{c:.2f}": prf(p, t, c) for c in CUTS}}
    return out


def frame_level(root: Path, d: dict, p: np.ndarray, cut: float) -> dict:
    """Per test frame, against the labeller: does a detection fire, and how far
    is the best one from the nearest label box (full-frame px)."""
    rows = [json.loads(ln) for ln in (root / "manifest.jsonl").open()]
    test = d["split"] == "test"
    by_frame: dict[int, list] = {}
    for k in np.nonzero(test)[0]:
        by_frame.setdefault(int(d["frame"][k]), []).append(k)
    out = {}
    for lab in ("absent_certain", "sprinkler", "unlabelled"):
        idx = [i for i, r in enumerate(rows) if r["split"] == "test" and r["label"] == lab]
        fired, errs = 0, []
        for i in idx:
            ks = [k for k in by_frame.get(i, []) if p[k] >= cut]
            if not ks:
                continue
            fired += 1
            if lab == "sprinkler":
                s = 1.0 / rows[i]["image_scale"]
                best = max(ks, key=lambda k: p[k])
                x, y, w, h = d["box"][best] * s
                cx, cy = x + w / 2, y + h / 2
                errs.append(min(np.hypot(cx - (b["box"][0] + b["box"][2] / 2),
                                         cy - (b["box"][1] + b["box"][3] / 2))
                                for b in rows[i]["boxes"]))
        out[lab] = {"frames": len(idx), "fired": fired,
                    "share": round(fired / max(1, len(idx)), 3)}
        if errs:
            e = np.array(errs)
            out[lab]["centre_err_px"] = {"median": round(float(np.median(e)), 1),
                                         "p90": round(float(np.percentile(e, 90)), 1),
                                         "over_45px": round(float((e > 45).mean()), 3)}
    return out


def latency(root: Path, params, cut: float, n: int = 200) -> dict:
    """find() on full 1920x1080 originals, as the bot would call it."""
    rows = [json.loads(ln) for ln in (root / "manifest.jsonl").open()]
    rng = np.random.default_rng(1)
    pick = rng.choice([r["source"] for r in rows if r["split"] == "test"], size=n, replace=False)
    ts = []
    for src in pick:
        img = cv2.imread(src)
        if img is None:
            continue
        t = time.perf_counter()
        sprinkler.find(img, params, cut)
        ts.append((time.perf_counter() - t) * 1000)
    ts = np.array(ts)
    return {"frames": len(ts), "median_ms": round(float(np.median(ts)), 2),
            "p95_ms": round(float(np.percentile(ts, 95)), 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--out", type=Path, default=data("models", "sprinkler.npz"))
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    cv2.setNumThreads(2)
    rng = np.random.default_rng(a.seed)
    d = prepare(a.data)
    y, split = d["y"], d["split"]
    counts = {s: {"pos": int(((split == s) & (y == 1)).sum()),
                  "neg": int(((split == s) & (y == 0)).sum()),
                  "ignored": int(((split == s) & (y < 0)).sum())} for s in ("train", "val", "test")}
    log(f"proposals: {counts}")

    tr = np.nonzero((split == "train") & (y >= 0))[0]
    X, Y = [], []
    for k in tr:
        X.append(d["crops"][k])
        Y.append(y[k])
        if y[k] == 1:
            for _ in range(POS_AUG):
                X.append(augment(d["crops"][k], rng))
                Y.append(1)
        else:
            X.append(d["crops"][k][:, ::-1])
            Y.append(0)
    X, Y = np.ascontiguousarray(np.array(X, np.uint8)), np.array(Y)
    log(f"training on {len(X)} crops ({int(Y.sum())} positive copies)")
    t0 = time.time()
    params = train_coins.train_stage2(X, Y, a.epochs, a.seed)
    log(f"trained in {time.time() - t0:.0f}s")

    p = probs(params, d["crops"])
    res = {"proposals": counts, "epochs": a.epochs, "train_seconds": round(time.time() - t0)}
    for s in ("val", "test"):
        m = (split == s) & (y >= 0)
        res[f"{s}_vs_labeller"] = {f"{c:.2f}": prf(p[m], y[m] == 1, c) for c in CUTS}
    # the cut: best F1 on VAL against the labeller, never test
    cut = max(CUTS, key=lambda c: res["val_vs_labeller"][f"{c:.2f}"]["F1"])
    res["cut"] = cut
    # ignored proposals: how many the network calls a Gusher (unknown truth)
    ign = (split == "test") & (y < 0)
    res["test_ignored_called"] = round(float((p[ign] >= cut).mean()), 3) if ign.any() else None
    res["eye_graded_boxes"] = eye_graded(a.data, params)
    res["frames_test"] = frame_level(a.data, d, p, cut)
    res["latency_full_frame"] = latency(a.data, params, cut)
    np.savez_compressed(a.out, **params, cut=np.float32(cut))
    (a.out.with_suffix(".json")).write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
