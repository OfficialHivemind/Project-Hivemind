#!/usr/bin/env python3
"""Train the token coin detector (vision/coins) from hand-labelled frames.

    ./scripts/train_coins.py [--cv] [--epochs 12] [--threads 4]

Reads data/models/coin_labels.json -- frames from var/incidents/*-token (the
pickup windows the black box keeps) with every coin boxed by eye -- and
writes data/models/coins.npz (both stages' weights) and coins.json (what it
was trained on and, with --cv, what it measured).

--cv FIRST MEASURES, THEN TRAINS. Five folds grouped by pickup window: each
fold's frames are scored by a model trained without any frame of their
window, so a coin seen in training is never one it is scored on. Scoring is
strict: a coin found twice counts once and its second box counts against
precision; a box on no labelled coin is wrong. The table lands in coins.json
`held_out`, per threshold, and is what `gather.chase_confidence` should be
chosen from.

Stage 1 (HOG + a linear model, run by OpenCV) learns coins against random
background, then once more against its own false candidates on the training
frames (hard negatives). Stage 2 (vision/coinnet) learns from each labelled
coin 30 times over -- shifted, rescaled, turned, mirrored and recoloured --
and from every stage-1 candidate on the training frames, labelled by whether
it lies on a coin. Its backward pass is here; its forward pass is the bot's
own (`coinnet.forward`), so what is measured is what runs.

--school ADDS THE BOT'S OWN CHASES (brain/school, var/school-coins): every
crop a chase took before its walk whose verdict was "collected" -- the
token's counter moved -- is one more stage-2 coin crop, as it is and
mirrored. Only crops written after the labels were made (SCHOOL_AFTER), so
none is a moment some labelled frame shows; the held-out frames' folds are
unchanged and the table is measured both ways in the same run, the same
stage 1 under both. "nothing" verdicts are not used: all of them are the
honey "nothing" brain/school itself retired (`_legacy_verdict`), and by eye
they are coins. Chases from attempt SCHOOL_HELD_FROM on are never trained
on: they are a second test, the share of them the model calls a coin.

It never touches the game. Run it niced and with OPENBLAS_NUM_THREADS set
low while the owner plays: the five folds are about 80 minutes on 4 threads.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cv2                                                      # noqa: E402
import numpy as np                                              # noqa: E402

from hivemind.datapaths import data                             # noqa: E402
from hivemind.vision import coinnet, coins                      # noqa: E402

LABELS = data("models", "coin_labels.json")
NOTES = data("models", "coins.json")

# ---- the training data -------------------------------------------------------------
S1_POS_AUG = 6              # stage-1 copies of each coin (jittered, mirrored)
S1_RANDOM = 160             # random background windows per frame
S2_POS_AUG = 30             # stage-2 copies of each coin
S2_RANDOM = 100             # random background crops per frame
NOT_COIN_AUG = 4            # copies of each verified not-a-coin (a reviewed mistake)
CLEAR_OF_COIN = 0.6         # a background sample's centre stays this far out of every box
TRUTH_SIDE = (0.4, 2.5)     # a candidate this size relative to a coin is that coin
THRESHOLDS = (0.25, 0.4, 0.5, 0.6, 0.7, 0.8)      # confidence cuts to report
FOLDS = 5
# --school: the bot's own chases (see the docstring).
SCHOOL_AFTER = time.mktime((2026, 10, 7, 22, 0, 0, 0, 0, -1))   # coin_labels.json made 21:55
SCHOOL_HELD_FROM = 1090     # attempts from here on: the school's own held-out test
SCHOOL_CROP = 48            # brain/school.CROP, frame px round the chased point
# brain/school.WIDE_CROP (crops-wide/*.jpg, since 2026-10-20 15:30): preferred
# when present. It shows the whole coin; stage 2 sees a coin's side x CROP_PAD,
# so the crop taken from it is the MEDIAN labelled coin (112 px) x CROP_PAD.
# ponytail: one size for every coin; per-chase coin size if the lesson ever keeps it.
SCHOOL_WIDE = 192
SCHOOL_WIDE_SIDE = 112 * 1.25


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def inside(pt, box, grow: float = 0.25) -> bool:
    x0, y0, x1, y1 = box
    gx, gy = (x1 - x0) * grow, (y1 - y0) * grow
    return x0 - gx <= pt[0] <= x1 + gx and y0 - gy <= pt[1] <= y1 + gy


class Frame(dict):
    """A labelled frame whose work image is read from disk each time it is
    asked for, not held: 2026-10-07's 452 frames held were ~1 GB, beside a
    live game with 3-5 GB free and the bot stepping aside under 2. Each user
    binds `f["work"]` once."""

    def __missing__(self, key):
        if key == "work":
            return coins.work_image(cv2.imread(str(self["_file"])))
        raise KeyError(key)


def load_frames(root: Path) -> list[dict]:
    """The labelled frames, their paths relative to the live tree `root`."""
    body = json.loads(LABELS.read_text())
    frames = []
    for f in body["frames"]:
        path = root / f["path"]
        img = cv2.imread(str(path))
        if img is None:
            log(f"missing frame, skipped: {path}")
            continue
        frames.append(Frame({**f, "full": img.shape[:2], "_file": str(path)}))
    return frames


# ---- stage 1 ---------------------------------------------------------------------
def s1_crop(work, cx, cy, side, rng=None, flip=False):
    """A HOG window's pixels: a square of `side` WORK pixels round (cx, cy)."""
    c = coins.crop(work, cx, cy, side)                 # CROP_SIZE == HOG_WINDOW
    return cv2.flip(c, 1) if flip else c


def s1_feature(hog, crop):
    return hog.compute(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)).ravel()


def coin_geometry(c):
    x0, y0, x1, y1 = [v * coins.WORK_SCALE for v in c["box"]]
    return (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0)


def background_points(f, rng, count):
    h, w = f["full"]
    wx0, wy0, wx1, wy1 = coins.world_box(w, h)
    boxes = [c["box"] for c in f["coins"]] + [n["box"] for n in f.get("not_coins", ())]
    out, tries = [], 0
    while len(out) < count and tries < 40 * count:
        tries += 1
        side = float(np.exp(rng.uniform(np.log(28), np.log(260)))) / coins.WORK_SCALE
        cx, cy = rng.uniform(wx0, wx1), rng.uniform(wy0, wy1)
        if any(inside((cx, cy), b, CLEAR_OF_COIN) for b in boxes):
            continue
        out.append((cx, cy, side))
    return out


def s1_samples(f, hog, rng):
    P, N = [], []
    work = f["work"]
    for c in f["coins"]:
        if not c["sure"]:
            continue
        cx, cy, side = coin_geometry(c)
        side *= coins.WINDOW_TO_COIN
        for k in range(S1_POS_AUG):
            s = side * (rng.uniform(0.9, 1.12) if k else 1.0)
            dx, dy = (rng.uniform(-.08, .08, 2) * side) if k else (0.0, 0.0)
            P.append(s1_feature(hog, s1_crop(work, cx + dx, cy + dy, s, flip=bool(k % 2))))
    for cx, cy, side in background_points(f, rng, S1_RANDOM):
        N.append(s1_feature(hog, s1_crop(work, cx * coins.WORK_SCALE, cy * coins.WORK_SCALE,
                                         side * coins.WORK_SCALE)))
    for n in f.get("not_coins", ()):
        cx, cy, side = coin_geometry(n)
        for k in range(NOT_COIN_AUG):
            s = side * coins.WINDOW_TO_COIN * (rng.uniform(0.9, 1.12) if k else 1.0)
            N.append(s1_feature(hog, s1_crop(work, cx, cy, s, flip=bool(k % 2))))
    return P, N


def logreg(X, y, l2=1e-3, iters=400, lr=0.5):
    """Class-balanced L2 logistic regression; weights for RAW features."""
    mu, sd = X.mean(0), X.std(0) + 1e-6
    Z = (X - mu) / sd
    w, b = np.zeros(Z.shape[1]), 0.0
    sw = np.where(y == 1, (y == 0).sum() / max(1, (y == 1).sum()), 1.0)
    sw /= sw.mean()
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = (p - y) * sw
        w -= lr * (Z.T @ g / len(y) + l2 * w)
        b -= lr * g.mean()
    return (w / sd).astype(np.float32), float(b - (w * mu / sd).sum())


def truth(f, cx, cy, side):
    """1 on a sure coin, 0 on nothing, None near an unsure one or ambiguous.

    A PARTIAL frame (one whose detections were reviewed, not the whole frame
    labelled by eye) knows only what was reviewed: 0 on a verified not-coin,
    None anywhere else -- an unreviewed spot may be a coin nobody looked at."""
    for c in f["coins"]:
        x0, y0, x1, y1 = c["box"]
        cs = max(x1 - x0, y1 - y0)
        if inside((cx, cy), c["box"]) and TRUTH_SIDE[0] <= side / cs <= TRUTH_SIDE[1]:
            return 1 if c["sure"] else None
        if inside((cx, cy), c["box"], CLEAR_OF_COIN):
            return None
    if f.get("partial"):
        return 0 if any(inside((cx, cy), n["box"], 0.0) for n in f.get("not_coins", ())) else None
    return 0


def train_stage1(train, rng):
    hog = coins.new_hog()
    P, N = [], []
    for f in train:
        p, n = s1_samples(f, hog, rng)
        P += p
        N += n
    X = np.array(P + N, np.float32)
    y = np.r_[np.ones(len(P)), np.zeros(len(N))]
    w, b = logreg(X, y)
    # ONE ROUND OF HARD NEGATIVES: its own false candidates on these frames.
    model = coins.Model(w, b, coinnet.fresh())
    hard = []
    for f in train:
        h, wd = f["full"]
        work = f["work"]
        for cx, cy, side, _ in coins.candidates(work, model, wd, h):
            if truth(f, cx, cy, side / coins.WINDOW_TO_COIN) == 0:
                hard.append(s1_feature(hog, s1_crop(work, cx * coins.WORK_SCALE,
                                                    cy * coins.WORK_SCALE,
                                                    side * coins.WORK_SCALE)))
    X = np.concatenate([X, np.array(hard, np.float32)]) if hard else X
    y = np.r_[y, np.zeros(len(hard))]
    w, b = logreg(X, y)
    log(f"  stage 1: {len(P)} coin windows, {len(N)} background, {len(hard)} hard negatives")
    return w, b


# ---- stage 2 ---------------------------------------------------------------------
def colour_jitter(c, rng):
    hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + rng.uniform(-3, 3)) % 180
    hsv[..., 1] = np.clip(hsv[..., 1] * rng.uniform(0.85, 1.15), 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * rng.uniform(0.8, 1.2), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def turned_crop(work, cx, cy, side, angle, flip):
    size = coins.CROP_SIZE
    M = cv2.getRotationMatrix2D((float(cx), float(cy)), float(angle), size / max(2.0, side))
    M[0, 2] += size / 2 - cx
    M[1, 2] += size / 2 - cy
    c = cv2.warpAffine(work, M, (size, size),
                       flags=cv2.INTER_AREA if side > size else cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REFLECT)
    return cv2.flip(c, 1) if flip else c


def s2_samples(f, model, rng):
    P, N = [], []
    work = f["work"]
    for c in f["coins"]:
        if not c["sure"]:
            continue
        cx, cy, side = coin_geometry(c)
        for k in range(S2_POS_AUG):
            s = side * coins.CROP_PAD * (rng.uniform(0.85, 1.2) if k else 1.0)
            dx, dy = (rng.uniform(-.12, .12, 2) * side) if k else (0.0, 0.0)
            cr = turned_crop(work, cx + dx, cy + dy, s, rng.uniform(-12, 12) if k else 0.0,
                             bool(k % 2))
            P.append(colour_jitter(cr, rng) if k else cr)
    h, w = f["full"]
    for cx, cy, side, _ in coins.candidates(work, model, w, h):
        t = truth(f, cx, cy, side / coins.WINDOW_TO_COIN)
        if t is None:
            continue
        cr = coins.crop(work, cx * coins.WORK_SCALE, cy * coins.WORK_SCALE, coins.crop_side(side))
        (P if t else N).append(cr)
    for cx, cy, side in background_points(f, rng, S2_RANDOM):
        N.append(coins.crop(work, cx * coins.WORK_SCALE, cy * coins.WORK_SCALE,
                            side * coins.WORK_SCALE * coins.CROP_PAD))
    for n in f.get("not_coins", ()):
        cx, cy, side = coin_geometry(n)
        for k in range(NOT_COIN_AUG):
            s = side * coins.CROP_PAD * (rng.uniform(0.9, 1.12) if k else 1.0)
            dx, dy = (rng.uniform(-.08, .08, 2) * side) if k else (0.0, 0.0)
            N.append(turned_crop(work, cx + dx, cy + dy, s, 0.0, bool(k % 2)))
    return P, N


def backward(params, cache, dout, pad=1):
    """Gradients of the loss for every parameter, from `coinnet.forward`'s
    kept intermediates and d(loss)/d(logit); `pad` as the forward pass had it."""
    g = {}
    shape, flat, hidden, act = cache[coinnet.LAYERS]
    dout = dout.reshape(-1, 1).astype(np.float32)
    g["w4"] = act.T @ dout
    g["b4"] = dout.sum(0)
    dh = (dout @ params["w4"].T) * (hidden > 0)
    g["w3"] = flat.T @ dh
    g["b3"] = dh.sum(0)
    da = (dh @ params["w3"].T).reshape(shape)
    for i in reversed(range(coinnet.LAYERS)):
        cols, z, blocks, pooled = cache[i]
        mask = blocks == pooled[:, :, None, :, None, :]
        mask = mask / mask.sum(axis=(2, 4), keepdims=True)
        dz = (mask * da[:, :, None, :, None, :]).reshape(z.shape) * (z > 0)
        n, h, w, cout = dz.shape
        flat_dz = dz.reshape(-1, cout)
        g[f"w{i}"] = cols.reshape(-1, cols.shape[-1]).T @ flat_dz
        g[f"b{i}"] = flat_dz.sum(0)
        if i == 0:
            break
        dcols = (flat_dz @ params[f"w{i}"].T).reshape(n, h, w, coinnet.KERNEL, coinnet.KERNEL, -1)
        dpad = np.zeros((n, h + 2, w + 2, dcols.shape[-1]), np.float32)
        for ky in range(coinnet.KERNEL):
            for kx in range(coinnet.KERNEL):
                dpad[:, ky:ky + h, kx:kx + w, :] += dcols[:, :, :, ky, kx, :]
        da = dpad[:, pad:h + 2 - pad, pad:w + 2 - pad, :]
    return g


def train_stage2(X, y, epochs, seed, lr=1e-3, wd=1e-4, batch=128, pad=1, init=None):
    """Adam on class-weighted binary cross-entropy. `X` is the crops as
    uint8, scaled a batch at a time: the whole set in float32 was 1.6 GB (x2
    while dividing) at 2026-10-07's 452 frames, beside a live game with 5 GB
    free and the bot stepping aside under 2 (platform/memory). `pad` and
    `init` (weights to start from) are for scripts/train_coindet.py."""
    rng = np.random.default_rng(seed)
    params = ({k: v.copy() for k, v in init.items()} if init is not None
              else coinnet.fresh(size=coins.CROP_SIZE, seed=seed))
    y = y.astype(np.float32)
    pos_weight = (y == 0).sum() / max(1, (y == 1).sum())
    m = {k: np.zeros_like(v) for k, v in params.items()}
    v = {k: np.zeros_like(v) for k, v in params.items()}
    t = 0
    for ep in range(epochs):
        order = rng.permutation(len(X))
        total = 0.0
        for s in range(0, len(X), batch):
            idx = order[s:s + batch]
            xb, yb = X[idx].astype(np.float32) / 255.0, y[idx]
            cache: list = []
            logit = coinnet.forward(params, xb, keep=cache, pad=pad)
            p = 1 / (1 + np.exp(-np.clip(logit, -30, 30)))
            wgt = np.where(yb == 1, pos_weight, 1.0)
            wgt = wgt / wgt.sum()
            total += -(wgt * (yb * np.log(p + 1e-7) + (1 - yb) * np.log(1 - p + 1e-7))).sum() * len(idx)
            g = backward(params, cache, wgt * (p - yb), pad=pad)
            t += 1
            for k in params:
                gk = g[k] + wd * params[k]
                m[k] = 0.9 * m[k] + 0.1 * gk
                v[k] = 0.999 * v[k] + 0.001 * gk * gk
                step = lr * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(v[k] / (1 - 0.999 ** t)) + 1e-8)
                params[k] = (params[k] - step).astype(np.float32)
        log(f"  stage 2: epoch {ep + 1}/{epochs}, loss {total / len(X):.4f}")
    return params


def school_crops(root: Path):
    """(training crops, held-out crops) of the "collected" chases, as stage 2
    sees a crop: the 48 frame px round the chased point, at WORK_SCALE."""
    sys.path.insert(0, str(ROOT))
    from hivemind.brain.school import Lesson, _legacy_verdict
    train_c, held_c, n_wide = [], [], 0
    for line in (root / "lessons.jsonl").read_text().splitlines():
        body = json.loads(line)
        lesson = Lesson(**{k: body.get(k) for k in Lesson.__dataclass_fields__})
        wide = root / "crops-wide" / f"{lesson.id}.jpg"
        path, size, side = ((wide, SCHOOL_WIDE, SCHOOL_WIDE_SIDE) if wide.exists()
                            else (root / "crops" / f"{lesson.id}.png", SCHOOL_CROP, SCHOOL_CROP))
        if (lesson.outcome != "collected" or _legacy_verdict(lesson) or not path.exists()
                or path.stat().st_mtime < SCHOOL_AFTER):
            continue
        img = cv2.imread(str(path))
        if img is None or img.shape[:2] != (size, size):
            continue
        half = size * coins.WORK_SCALE / 2
        c = coins.crop(coins.work_image(img), half, half, side * coins.WORK_SCALE)
        n_wide += size == SCHOOL_WIDE
        (held_c if (lesson.attempt or 0) >= SCHOOL_HELD_FROM else train_c).append(c)
    return train_c, held_c, n_wide


def called_coin(model, crops, cut=0.5) -> float:
    """The share of `crops` the model calls a coin at confidence >= `cut`."""
    if not crops:
        return 0.0
    z = coinnet.logits(model.params, np.array(crops, np.float32) / 255.0)
    return round(float((z >= cut * coins.LOGIT_FULL).mean()), 3)


def train(frames, epochs, seed=0, school=None):
    """The model; with `school` (extra coin crops) the pair (without, with),
    the same stage 1 under both."""
    rng = np.random.default_rng(seed)
    w, b = train_stage1(frames, rng)
    stage1_only = coins.Model(w, b, coinnet.fresh())
    P, N = [], []
    for f in frames:
        p, n = s2_samples(f, stage1_only, rng)
        P += p
        N += n
    X = np.array(P + N, np.uint8)
    y = np.r_[np.ones(len(P)), np.zeros(len(N))]
    log(f"  stage 2: {len(P)} coin crops, {len(N)} other crops")
    del P, N
    params = train_stage2(X, y, epochs, seed)
    if school is None:
        return coins.Model(w, b, params)
    extra = np.array(school + [cv2.flip(c, 1) for c in school], np.uint8)
    log(f"  stage 2 again with {len(extra)} school crops")
    X = np.concatenate([X, extra])
    y = np.r_[y, np.ones(len(extra))]
    return coins.Model(w, b, params), coins.Model(w, b, train_stage2(X, y, epochs, seed))


# ---- scoring ----------------------------------------------------------------------
def score(frames, looks, cut):
    """Strict: per frame, merged detections at >= `cut` confidence, each coin
    matched at most once, a second box on it counted against precision.

    On a PARTIAL frame a detection on nothing reviewed is `unreviewed` and
    left out of precision -- nobody looked at it -- and its recall is over
    the reviewed coins only, so it is reported apart from the complete ones."""
    tp = dup = fp = unreviewed = found = sure = candidates_on = 0
    for f, look in zip(frames, looks):
        z_cut = cut * coins.LOGIT_FULL
        dets = coins.merge([d for d in look if d[3] >= z_cut])
        matched = set()
        for d in dets:
            hit = [k for k, c in enumerate(f["coins"]) if inside((d[0], d[1]), c["box"])]
            free = [k for k in hit if k not in matched]
            if free:
                matched.add(free[0])
                tp += 1
            elif hit:
                dup += 1
            elif not f.get("partial") or any(inside((d[0], d[1]), n["box"], 0.0)
                                             for n in f.get("not_coins", ())):
                fp += 1
            else:
                unreviewed += 1
        for k, c in enumerate(f["coins"]):
            if c["sure"]:
                sure += 1
                found += k in matched
                candidates_on += any(inside((d[0], d[1]), c["box"]) for d in look)
    n = tp + dup + fp
    return {"per_frame": round((n + unreviewed) / max(1, len(frames)), 2),
            "precision": round(tp / max(1, n), 3),
            "recall": round(found / max(1, sure), 3),
            "right": tp, "twice": dup, "wrong": fp, "unreviewed": unreviewed,
            "coins_found": found, "coins": sure, "coins_among_candidates": candidates_on}


def folds(frames) -> dict:
    """Pickup window -> fold. One rule for every table measured on these
    labels (coins.json, scripts/train_coindet.py), so their folds match."""
    windows = sorted({f["window"] for f in frames})
    random.Random(7).shuffle(windows)
    return {w: k % FOLDS for k, w in enumerate(windows)}


def cross_validate(frames, epochs, school=None):
    """The held-out table and looks; with `school`, ({"without": .., "with": ..},
    looks of the school model), both measured on the same folds."""
    fold_of = folds(frames)
    looks = [None] * len(frames)
    base_looks = [None] * len(frames)
    for k in range(FOLDS):
        train_idx = [i for i, f in enumerate(frames) if fold_of[f["window"]] != k]
        test_idx = [i for i, f in enumerate(frames) if fold_of[f["window"]] == k]
        log(f"fold {k + 1}/{FOLDS}: training on {len(train_idx)} frames, scoring {len(test_idx)}")
        model = train([frames[i] for i in train_idx], epochs, seed=k, school=school)
        base, model = model if school is not None else (None, model)
        for i in test_idx:
            f = frames[i]
            h, w = f["full"]
            work = f["work"]
            looks[i] = _look_work(work, model, w, h)
            if base is not None:
                base_looks[i] = _look_work(work, base, w, h)
    if school is not None:
        return {"without school": _table(frames, base_looks),
                "with school": _table(frames, looks)}, looks
    return _table(frames, looks), looks


def _table(frames, looks):
    table = {}
    for group, members in (("labelled whole", [i for i, f in enumerate(frames) if not f.get("partial")]),
                           ("reviewed detections", [i for i, f in enumerate(frames) if f.get("partial")])):
        if not members:
            continue
        table[group] = {f"{cut:.2f}": score([frames[i] for i in members], [looks[i] for i in members], cut)
                        for cut in THRESHOLDS}
        for cut, row in table[group].items():
            log(f"  held out ({group}), confidence >= {cut}: {row}")
    return table


def _look_work(work, model, width, height):
    """`coins.look` on an already scaled image (the frames are kept scaled)."""
    cands = coins.candidates(work, model, width, height)
    if not cands:
        return []
    batch = np.stack([coins.crop(work, cx * coins.WORK_SCALE, cy * coins.WORK_SCALE,
                                 coins.crop_side(side))
                      for cx, cy, side, _ in cands]).astype(np.float32) / 255.0
    out = coinnet.logits(model.params, batch)
    return [(cx, cy, side / coins.WINDOW_TO_COIN, float(z), s1)
            for (cx, cy, side, s1), z in zip(cands, out)]


# ---- which coin: the honey head (--kinds) ------------------------------------------
HONEY_AUG = 30
HONEY_CUTS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.98)
HONEY_MIN_PRECISION = 0.95  # the head names a coin honey only this sure


def honey_crops(frames, rng, aug=HONEY_AUG):
    """Crops of the sure, named coins: 1 for honey, 0 for every other kind.
    `aug` copies of each (the first as it is), as stage 2 is trained."""
    X, y = [], []
    for f in frames:
        work = None
        for c in f["coins"]:
            if not c["sure"] or c.get("kind", "unknown") in ("", "unknown"):
                continue
            if work is None:
                work = f["work"]
            cx, cy, side = coin_geometry(c)
            label = 1 if c["kind"] == "honey" else 0
            for k in range(aug):
                s = side * coins.CROP_PAD * (rng.uniform(0.85, 1.2) if k else 1.0)
                dx, dy = (rng.uniform(-.12, .12, 2) * side) if k else (0.0, 0.0)
                cr = turned_crop(work, cx + dx, cy + dy, s,
                                 rng.uniform(-12, 12) if k else 0.0, bool(k % 2))
                X.append(colour_jitter(cr, rng) if k else cr)
                y.append(label)
    return X, y


def train_honey(frames, epochs, seed):
    rng = np.random.default_rng(seed)
    X, y = honey_crops(frames, rng)
    log(f"  honey head: {int(sum(y))} honey crops, {len(y) - int(sum(y))} of other coins")
    return train_stage2(np.array(X, np.uint8), np.array(y), epochs, seed)


def honey_cross_validate(frames, epochs):
    """Each fold's coins, one plain crop each, scored by a head trained
    without their window. Returns the table and the chosen threshold."""
    fold_of = folds(frames)
    scored = []                                   # (p, is honey)
    for k in range(FOLDS):
        train = [f for f in frames if fold_of[f["window"]] != k]
        test = [f for f in frames if fold_of[f["window"]] == k]
        head = train_honey(train, epochs, seed=k)
        X, y = honey_crops(test, np.random.default_rng(0), aug=1)
        if not X:
            continue
        z = coinnet.logits(head, np.array(X, np.float32) / 255.0)
        scored += list(zip((1 / (1 + np.exp(-np.clip(z, -30, 30)))).tolist(), y))
        log(f"honey fold {k + 1}/{FOLDS}: {len(X)} coins scored")
    table, chosen = {}, None
    for cut in HONEY_CUTS:
        named = [(p, t) for p, t in scored if p >= cut]
        right = sum(t for _, t in named)
        honey = sum(t for _, t in scored)
        row = {"named_honey": len(named), "right": int(right),
               "precision": round(right / max(1, len(named)), 3),
               "recall": round(right / max(1, honey), 3),
               "coins": len(scored), "honey_coins": int(honey)}
        table[f"{cut:.2f}"] = row
        log(f"  honey held out, p >= {cut}: {row}")
        if chosen is None and len(named) and row["precision"] >= HONEY_MIN_PRECISION:
            chosen = cut
    return table, chosen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cv", action="store_true", help="measure on held-out windows first")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--threads", type=int, default=4,
                    help="OpenCV's threads (numpy's are OPENBLAS_NUM_THREADS)")
    ap.add_argument("--root", default=str(Path.home() / "Hivemind"),
                    help="the live tree whose var/incidents holds the frames")
    ap.add_argument("--out", default=str(coins.MODEL), help="the model file to write")
    ap.add_argument("--looks", default="", help="save the held-out looks here (JSON)")
    ap.add_argument("--school", default="",
                    help="add the bot's collected chases from this var/school-coins")
    ap.add_argument("--kinds", action="store_true",
                    help="measure and train only the honey head, into the existing model")
    args = ap.parse_args()
    cv2.setNumThreads(args.threads)
    frames = load_frames(Path(args.root))
    if args.kinds:
        return train_kinds(frames, args)
    n_coins = sum(len(f["coins"]) for f in frames)
    n_sure = sum(c["sure"] for f in frames for c in f["coins"])
    log(f"{len(frames)} frames from {len({f['window'] for f in frames})} pickup windows, "
        f"{n_coins} coins labelled ({n_sure} sure)")
    notes = {"made": time.strftime("%Y-%m-%d %H:%M:%S"), "labels": str(LABELS.name),
             "frames": len(frames), "windows": len({f["window"] for f in frames}),
             "coins": n_coins, "sure": n_sure, "epochs": args.epochs,
             "stage1_hit": coins.STAGE1_HIT, "report_p": coins.REPORT_P,
             "merge_share": coins.MERGE_SHARE}
    school = held = None
    if args.school:
        school, held, n_wide = school_crops(Path(args.school))
        log(f"school: {len(school)} collected crops to train on, {len(held)} held out "
            f"(attempt >= {SCHOOL_HELD_FROM}), {n_wide} of them wide")
        notes["school"] = {"crops": len(school), "held_out_crops": len(held), "wide_crops": n_wide,
                           "after": time.strftime("%Y-%m-%d %H:%M", time.localtime(SCHOOL_AFTER)),
                           "held_from_attempt": SCHOOL_HELD_FROM}
    if args.cv:
        table, looks = cross_validate(frames, args.epochs, school)
        notes["held_out"] = {"folds": FOLDS, "grouped_by": "pickup window",
                             "scoring": "strict: one match per coin, repeats count against",
                             "by_confidence": table}
        if school is not None:      # the school model's table where it always was
            notes["held_out"]["by_confidence"] = table["with school"]
            notes["held_out"]["without_school_same_folds"] = table["without school"]
        if args.looks:
            Path(args.looks).write_text(json.dumps(
                [{"path": f["path"], "look": look} for f, look in zip(frames, looks)]))
    log("training the shipped model on every frame")
    model = train(frames, args.epochs, seed=99, school=school)
    if school is not None:
        base, model = model
        notes["school"]["held_out_called_coin_at_0.50"] = {
            "shipped before": called_coin(coins.Model.load(coins.MODEL), held),
            "retrained without school": called_coin(base, held),
            "with school": called_coin(model, held)}
        log(f"school held out, called a coin at 0.50: {notes['school']['held_out_called_coin_at_0.50']}")
    out = Path(args.out)
    model.save(out)
    notes_path = out.with_suffix(".json")
    notes_path.write_text(json.dumps(notes, indent=1) + "\n")
    log(f"wrote {out} and {notes_path}")
    return 0


def train_kinds(frames, args) -> int:
    """--kinds: the honey head, measured then trained, saved into the model
    beside the two stages; its threshold is the measured one."""
    out = Path(args.out)
    model = coins.Model.load(out)
    table, chosen = honey_cross_validate(frames, args.epochs)
    notes_path = out.with_suffix(".json")
    notes = json.loads(notes_path.read_text()) if notes_path.exists() else {}
    notes["honey"] = {"held_out": table, "folds": FOLDS, "grouped_by": "pickup window",
                      "min_precision": HONEY_MIN_PRECISION, "threshold": chosen}
    if chosen is None:
        notes_path.write_text(json.dumps(notes, indent=1) + "\n")
        log(f"no threshold reached {HONEY_MIN_PRECISION:.0%} precision; no honey head saved")
        return 1
    log(f"training the shipped honey head (threshold {chosen})")
    model.honey = train_honey(frames, args.epochs, seed=99)
    model.honey_p = chosen
    model.save(out)
    notes_path.write_text(json.dumps(notes, indent=1) + "\n")
    log(f"wrote the honey head into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
