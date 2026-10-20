#!/usr/bin/env python3
"""Train and measure vision/tokdet, the typed token detector v2.

    ./scripts/train_tokdet.py build --teacher T.npz [--pseudo 2400]
    ./scripts/train_tokdet.py train --minutes 80 [--out tokdet.npz]
    ./scripts/train_tokdet.py score --model tokdet.npz --baseline T.npz
    ./scripts/train_tokdet.py export --model tokdet.npz --onnx data/models/tokdet.onnx

Everything lands in DATA (outside the repo) except the exported model. It
never touches the game; run it niced, capped at 3 GB, 2 BLAS threads.

THE DATA (build), every row tagged with its night (scripts/tokdet_split):
  hand   data/models/coin_labels.json frames, boxes and kinds by eye. Whole
         frames are supervised everywhere; "partial" ones (only the old
         detector's flags were reviewed) only on their coins and not-coins.
  pseudo gather frames from var/routes (pattern_<field>), nights never held
         out, boxed by a TEACHER: today's detector retrained on the train
         nights only (tokdet_split --baseline), so no held-out frame leaks in
         through it. Coins at confidence >= PSEUDO_POS are positives, those
         between PSEUDO_IGNORE and it are not supervised, the rest of the
         frame is background. ponytail: the teacher's misses (it never sees
         ~11% of coins) are taught as background; a second teacher or a
         track filter when that ceiling matters.
  self   datasets/tokens-typed self rows: 192 px chase crops whose kind came
         from the HUD (~86% right by eye). They train the kind head only, at
         the crop's centre: the coin's size is not known.
Held out: hand frames of tokdet_split.HELD_OUT nights, self rows of
SELF_HELD_OUT nights; pseudo frames from any held-out night are not used.

THE LOSS: CenterNet's penalty-reduced focal loss on objectness (Gaussian
targets, one level per coin by size), L1 on the offsets and log side at the
centre cell, softmax cross-entropy on the kind over the 3x3 cells round it.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import cv2                                                      # noqa: E402
import numpy as np                                              # noqa: E402

from hivemind.vision import coins, tokdet as T                  # noqa: E402
import tokdet_split                                             # noqa: E402

DATA = Path.home() / ".cache/hivemind-work/datasets/tokdet-v2"
TYPED = Path.home() / ".cache/hivemind-work/datasets/tokens-typed/blue"
LIVE = tokdet_split.LIVE
SELF_HELD_OUT = ("2026-10-25", "2026-10-26")
PSEUDO_POS, PSEUDO_IGNORE = 0.80, 0.25
WIDE_IN = 96                    # a 192 px chase crop at input scale (~75 px), padded
CROP = 256                      # training crop, input px
COIN_CROPS = 0.7                # share of crops cut round a coin when the frame has one
THRESHOLDS = (0.25, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.98)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def kind_index(kind: str) -> int:
    """CLASSES index; -1 for "unknown" (no kind loss)."""
    if kind in (None, "unknown"):
        return -1
    return T.CLASSES.index(kind) if kind in T.CLASSES else T.CLASSES.index("other")


# ---- build ----------------------------------------------------------------------
def _boxes_in(boxes, x0, y0, sx, sy):
    out = []
    for b in boxes:
        bx0, by0, bx1, by1 = b["box"]
        out.append([((bx0 + bx1) / 2 - x0) * sx, ((by0 + by1) / 2 - y0) * sy,
                    max(bx1 - bx0, by1 - by0) * (sx + sy) / 2,
                    kind_index(b.get("kind")), bool(b.get("sure", True))])
    return out


def gather_frames(exclude) -> list[Path]:
    out = []
    for p in sorted((LIVE / "var/routes").glob("attempt-*/*pattern_*.jpg")):
        if "-00-start" in p.name:
            continue
        if tokdet_split.night_of(p) not in exclude:
            out.append(p)
    return out


def build(args) -> int:
    import train_coins
    DATA.mkdir(parents=True, exist_ok=True)
    teacher = coins.Model.load(Path(args.teacher)) if args.pseudo else None
    frames = train_coins.load_frames(LIVE)
    train, held = tokdet_split.split(frames)
    pool = gather_frames(set(tokdet_split.HELD_OUT) | set(SELF_HELD_OUT))
    rng = random.Random(11)
    pseudo = sorted(rng.sample(pool, min(args.pseudo, len(pool))))
    log(f"{len(train)} train + {len(held)} held-out hand frames, {len(pseudo)} of "
        f"{len(pool)} gather frames to pseudo-label")
    n = len(frames) + len(pseudo)
    images = np.lib.format.open_memmap(DATA / "images.npy", "w+", np.uint8, (n, T.IN_H, T.IN_W, 3))
    rows = []
    for f in train + held:
        img = cv2.imread(str(LIVE / f["path"]))
        inp, x0, y0, sx, sy = T.to_input(img)
        images[len(rows)] = inp
        rows.append({"src": f["path"], "kind": "hand", "night": f["night"],
                     "held": f["night"] in tokdet_split.HELD_OUT, "partial": bool(f["partial"]),
                     "coins": _boxes_in(f["coins"], x0, y0, sx, sy),
                     "not_coins": _boxes_in(f.get("not_coins", ()), x0, y0, sx, sy)})
    t0 = time.time()
    for k, p in enumerate(pseudo):
        img = cv2.imread(str(p))
        if img is None:
            continue
        inp, x0, y0, sx, sy = T.to_input(img)
        found = coins.merge([c for c in coins.look(img, m=teacher)
                             if c[3] >= PSEUDO_IGNORE * coins.LOGIT_FULL])
        s = (sx + sy) / 2
        pos = [[(c[0] - x0) * sx, (c[1] - y0) * sy, c[2] * s, -1, True]
               for c in found if c[3] >= PSEUDO_POS * coins.LOGIT_FULL]
        ign = [[(c[0] - x0) * sx, (c[1] - y0) * sy, c[2] * s, -1, False]
               for c in found if c[3] < PSEUDO_POS * coins.LOGIT_FULL]
        images[len(rows)] = inp
        rows.append({"src": str(p.relative_to(LIVE)), "kind": "pseudo",
                     "night": tokdet_split.night_of(p), "held": False, "partial": False,
                     "coins": pos + ign, "not_coins": []})
        if k % 200 == 0:
            log(f"  pseudo {k}/{len(pseudo)}, {time.time() - t0:.0f} s")
    images.flush()
    # the self rows: kind only, at the centre
    wide, wrows = [], []
    for line in (TYPED / "manifest.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r["source"] != "self" or not r.get("wide"):
            continue
        img = cv2.imread(str(TYPED / r["wide"]))
        if img is None:
            continue
        src = Path(r["src"])
        night = tokdet_split.night_of(src if src.exists() else TYPED / r["wide"])
        side = round(img.shape[1] * T.IN_W / (1920 * (coins.WORLD[2] - coins.WORLD[0])))
        small = cv2.resize(img, (side, side), interpolation=cv2.INTER_AREA)
        pad = (WIDE_IN - side) // 2
        wide.append(cv2.copyMakeBorder(small, pad, WIDE_IN - side - pad, pad,
                                       WIDE_IN - side - pad, cv2.BORDER_REFLECT))
        wrows.append({"id": r["id"], "label": r["label"], "cls": kind_index(r["label"]),
                      "night": night, "held": night in SELF_HELD_OUT})
    np.save(DATA / "wide.npy", np.array(wide, np.uint8))
    (DATA / "labels.json").write_text(json.dumps({
        "made": time.strftime("%Y-%m-%d %H:%M:%S"), "classes": T.CLASSES,
        "in": [T.IN_W, T.IN_H], "teacher": str(args.teacher),
        "held_out_nights": tokdet_split.HELD_OUT, "self_held_out_nights": SELF_HELD_OUT,
        "pseudo_pos": PSEUDO_POS, "pseudo_ignore": PSEUDO_IGNORE,
        "frames": rows, "wide": wrows}))
    log(f"wrote {len(rows)} frames, {len(wrows)} self crops into {DATA}")
    return 0


# ---- targets ----------------------------------------------------------------------
def level_of(side: float) -> int:
    return 0 if side < T.SPLIT_SIDE else 1


def targets(row, h, w, flip, shift, scale):
    """Per level: (heat, mask, reg list, cls list) for one crop.

    The crop is the image scaled by `scale`, then cut at `shift` (x, y),
    `flip` mirrored; the row's boxes are moved the same way."""
    out = []
    coins_ = []
    for cx, cy, side, cls, sure in row["coins"]:
        cx, cy, side = cx * scale - shift[0], cy * scale - shift[1], side * scale
        if flip:
            cx = w - cx
        coins_.append((cx, cy, side, cls, sure))
    nots = []
    for cx, cy, side, *_ in row["not_coins"]:
        cx, cy, side = cx * scale - shift[0], cy * scale - shift[1], side * scale
        nots.append((w - cx if flip else cx, cy, side))
    for li, (_lvl, _src, stride, _h) in enumerate(T.LEVELS):
        gh, gw = h // stride, w // stride
        heat = np.zeros((gh, gw), np.float32)
        mask = np.ones((gh, gw), np.float32) if not row["partial"] else np.zeros((gh, gw), np.float32)
        ii, jj = np.mgrid[0:gh, 0:gw]
        ci_all, cj_all = (ii + 0.5) * stride, (jj + 0.5) * stride
        reg, cls_ = [], []
        for cx, cy, side, cls, sure in coins_:
            near = (np.abs(ci_all - cy) < side * 0.75) & (np.abs(cj_all - cx) < side * 0.75)
            if not sure:
                mask[near] = 0
                continue
            mine = level_of(side) == li
            borderline = 0.7 < side / T.SPLIT_SIDE < 1.4
            if not mine:
                if borderline:
                    mask[near] = 0
                elif row["partial"]:
                    mask[near] = 1
                continue
            mask[near] = 1
            i, j = int(cy // stride), int(cx // stride)
            if not (0 <= i < gh and 0 <= j < gw):
                continue
            sigma = max(0.5, side / stride / 6)
            g = np.exp(-((ii - i) ** 2 + (jj - j) ** 2) / (2 * sigma ** 2))
            heat = np.maximum(heat, g.astype(np.float32))
            # CENTRE REGION: a coin 3+ cells across is positive on the 3x3
            # cells round its centre, not only the one (FCOS's centre
            # sampling). MEASURED 2026-10-27: with one positive cell a coin,
            # 530 steps left objectness flat (p 0.06 everywhere, 0.09 at coins).
            r = 1 if side / stride >= 3 else 0
            for pi in range(i - r, i + r + 1):
                for pj in range(j - r, j + r + 1):
                    if 0 <= pi < gh and 0 <= pj < gw:
                        heat[pi, pj] = 1.0
                        reg.append((pi, pj, cx / stride - pj - 0.5, cy / stride - pi - 0.5,
                                    math.log(side / stride)))
            if cls >= 0:
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        if 0 <= i + di < gh and 0 <= j + dj < gw:
                            cls_.append((i + di, j + dj, cls))
        for cx, cy, side in nots:
            inb = (np.abs(ci_all - cy) < side / 2) & (np.abs(cj_all - cx) < side / 2)
            mask[inb & (heat < 0.05)] = 1
        out.append((heat, mask, reg, cls_))
    return out


# ---- training ---------------------------------------------------------------------
ALPHA, BETA = 2.0, 4.0


def focal(z, heat, mask):
    """CenterNet focal loss, summed (caller normalises), and d/dz."""
    p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
    p = np.clip(p, 1e-6, 1 - 1e-6)
    pos = heat >= 1.0
    lp = -((1 - p) ** ALPHA) * np.log(p)
    gp = ALPHA * p * (1 - p) ** ALPHA * np.log(p) - (1 - p) ** (ALPHA + 1)
    wn = (1 - heat) ** BETA
    ln = -wn * p ** ALPHA * np.log(1 - p)
    gn = -wn * (ALPHA * p ** ALPHA * (1 - p) * np.log(1 - p) - p ** (ALPHA + 1))
    loss = np.where(pos, lp, ln) * mask
    grad = np.where(pos, gp, gn) * mask
    return float(loss.sum()), grad.astype(np.float32), int((pos & (mask > 0)).sum())


LOSS = "focal"                  # or "bce": --loss
NEG_RATIO = 3.0                 # bce: background weighs this many times the coins


def bce(z, heat, mask, neg_norm):
    """Balanced cross-entropy on objectness: positives (heat 1) and the
    (1 - heat)^4-weighted negatives each average to one term; summed so the
    caller's 1/npos is undone for the negatives by `neg_norm`/npos."""
    p = np.clip(1 / (1 + np.exp(-np.clip(z, -30, 30))), 1e-6, 1 - 1e-6)
    pos = heat >= 1.0
    wn = (1 - heat) ** BETA * mask * ~pos
    loss = (-np.log(p) * pos * mask).sum() - (wn * np.log(1 - p)).sum() * neg_norm
    grad = (p - 1) * pos * mask + wn * p * neg_norm
    return float(loss), grad.astype(np.float32), 0


def batch_loss(outs, tgts, cls_weight=1.0, obj=True):
    """Loss and d/d(outputs) for a batch; `tgts[n][level]` from `targets`."""
    total, grads = 0.0, {}
    npos = sum(len(t[li][2]) for t in tgts for li in range(len(T.LEVELS))) if obj else 0
    ncls = sum(len(t[li][3]) for t in tgts for li in range(len(T.LEVELS)))
    nneg = sum(float(((1 - t[li][0]) ** BETA * t[li][1] * (t[li][0] < 1)).sum())
               for t in tgts for li in range(len(T.LEVELS))) if obj else 0.0
    neg_norm = NEG_RATIO * max(1, npos) / max(1.0, nneg)
    for li, (lvl, *_r) in enumerate(T.LEVELS):
        o = outs[lvl]
        g = np.zeros_like(o)
        for n, t in enumerate(tgts):
            heat, mask, reg, cls_ = t[li]
            if obj:
                l, gz, _ = (focal(o[n, :, :, 0], heat, mask) if LOSS == "focal"
                            else bce(o[n, :, :, 0], heat, mask, neg_norm))
                total += l / max(1, npos)
                g[n, :, :, 0] = gz / max(1, npos)
                for i, j, tx, ty, ts in reg:
                    v = o[n, i, j]
                    for c, tt in ((1, tx), (2, ty)):
                        total += abs(v[c] - tt) / max(1, npos)
                        g[n, i, j, c] += np.sign(v[c] - tt) / max(1, npos)
                    total += abs(v[3] - ts) / max(1, npos)
                    g[n, i, j, 3] += np.sign(v[3] - ts) / max(1, npos)
            for i, j, c in cls_:
                z = o[n, i, j, T.EXTRA:]
                q = np.exp(z - z.max())
                q /= q.sum()
                total += -cls_weight * math.log(q[c] + 1e-9) / max(1, ncls)
                q[c] -= 1
                g[n, i, j, T.EXTRA:] += cls_weight * q / max(1, ncls)
        grads[lvl] = g
    return total, grads


def col2im(dcols, shape, k, stride):
    n, h, w, c = shape
    if k == 1:
        dx = np.zeros(shape, dcols.dtype)
        dx[:, ::stride, ::stride] = dcols
        return dx
    p = k // 2
    ho, wo = dcols.shape[1:3]
    d = dcols.reshape(n, ho, wo, k, k, c)
    dxp = np.zeros((n, h + 2 * p, w + 2 * p, c), dcols.dtype)
    for ky in range(k):
        for kx in range(k):
            dxp[:, ky:ky + stride * ho:stride, kx:kx + stride * wo:stride] += d[:, :, :, ky, kx]
    return dxp[:, p:p + h, p:p + w]


def backward(params, keep, x_shape, douts):
    grads, dacts = {}, dict(douts)
    shapes = {"image": x_shape}
    for name, _src, *_ in T.layers():
        shapes[name] = keep[name][2].shape
    for name, src, cin, cout, k, stride, relu in reversed(T.layers()):
        da = dacts.pop(name)
        cols, z, _a = keep[name]
        dz = da * (z > 0) if relu else da
        dzf = dz.reshape(-1, cout)
        grads[f"{name}.w"] = cols.reshape(-1, cols.shape[-1]).T @ dzf
        grads[f"{name}.b"] = dzf.sum(0)
        if src == "image":
            continue
        dcols = (dzf @ params[f"{name}.w"].T).reshape(*dz.shape[:3], -1)
        dx = col2im(dcols, shapes[src], k, stride)
        dacts[src] = dacts[src] + dx if src in dacts else dx
    return grads


def jitter(img, rng):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + rng.uniform(-3, 3)) % 180
    hsv[..., 1] = np.clip(hsv[..., 1] * rng.uniform(0.85, 1.15), 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * rng.uniform(0.8, 1.2), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def sample(images, row_i, row, rng):
    """One augmented CROP x CROP training crop and its targets."""
    scale = float(np.exp(rng.uniform(math.log(0.75), math.log(1.33))))
    H, W = round(T.IN_H * scale), round(T.IN_W * scale)
    big = cv2.resize(images[row_i], (W, H), interpolation=cv2.INTER_AREA if scale < 1
                     else cv2.INTER_LINEAR)
    if H < CROP:
        big = cv2.copyMakeBorder(big, 0, CROP - H, 0, 0, cv2.BORDER_REFLECT)
        H = CROP
    sup = [b for b in row["coins"] + row["not_coins"]]
    sure = [b for b in row["coins"] if b[4]]
    # most crops hold a coin: a random 256 px crop of a frame mostly holds none
    if (row["partial"] and sup) or (sure and rng.random() < COIN_CROPS):
        pool = sup if row["partial"] else sure
        cx, cy = pool[int(rng.integers(len(pool)))][:2]
        sx = int(np.clip(cx * scale - CROP / 2 + rng.uniform(-80, 80), 0, W - CROP))
        sy = int(np.clip(cy * scale - CROP / 2 + rng.uniform(-80, 80), 0, H - CROP))
    else:
        sx, sy = int(rng.integers(0, W - CROP + 1)), int(rng.integers(0, H - CROP + 1))
    crop = big[sy:sy + CROP, sx:sx + CROP]
    flip = bool(rng.random() < 0.5)
    if flip:
        crop = crop[:, ::-1]
    crop = jitter(np.ascontiguousarray(crop), rng)
    return crop, targets(row, CROP, CROP, flip, (sx, sy), scale)


def wide_targets(cls):
    out = []
    for _lvl, _src, stride, _h in T.LEVELS:
        g = WIDE_IN // stride
        heat = np.zeros((g, g), np.float32)
        c = [(i, j, cls) for i in (g // 2 - 1, g // 2) for j in (g // 2 - 1, g // 2)]
        out.append((heat, heat, [], c))
    return out


def adam_step(params, grads, m, v, t, lr, wd=1e-4):
    for k in params:
        g = grads[k] + wd * params[k]
        m[k] = 0.9 * m[k] + 0.1 * g
        v[k] = 0.999 * v[k] + 0.001 * g * g
        params[k] = (params[k] - lr * (m[k] / (1 - 0.9 ** t))
                     / (np.sqrt(v[k] / (1 - 0.999 ** t)) + 1e-8)).astype(np.float32)


def save(params, path, **notes):
    np.savez_compressed(path, **params, classes=np.array(T.CLASSES),
                        notes=np.array(json.dumps(notes)))


def load_params(path):
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files if k not in ("classes", "notes")}


def train(args) -> int:
    labels = json.loads((DATA / "labels.json").read_text())
    images = np.load(DATA / "images.npy", mmap_mode="r")
    wide = np.load(DATA / "wide.npy")
    rows = [(i, r) for i, r in enumerate(labels["frames"]) if not r["held"]
            and (args.pseudo or r["kind"] != "pseudo")]
    hand = [x for x in rows if x[1]["kind"] == "hand"]
    widx = [i for i, r in enumerate(labels["wide"]) if not r["held"] and r["cls"] >= 0]
    log(f"training on {len(rows)} frames ({len(hand)} hand), {len(widx)} self crops; "
        f"{args.minutes} min budget, batch {args.batch}")
    global LOSS, NEG_RATIO
    LOSS, NEG_RATIO = args.loss, args.neg_ratio
    rng = np.random.default_rng(args.seed)
    params = load_params(args.init) if args.init else T.fresh(args.seed)
    m = {k: np.zeros_like(v) for k, v in params.items()}
    v = {k: np.zeros_like(v) for k, v in params.items()}
    t0, t, last_save, hist = time.time(), 0, time.time(), []
    budget = args.minutes * 60
    while time.time() - t0 < budget:
        frac = (time.time() - t0) / budget
        lr = args.lr * min(1.0, (t + 1) / 100) * 0.5 * (1 + math.cos(math.pi * frac))
        # hand frames are few: half of each batch is drawn from them
        picks = [hand[rng.integers(len(hand))] if k % 2 == 0 or not args.pseudo
                 else rows[rng.integers(len(rows))] for k in range(args.batch)]
        xs, tg = [], []
        for i, r in picks:
            c, tt = sample(images, i, r, rng)
            xs.append(c)
            tg.append(tt)
        x = np.array(xs, np.float32) / 255.0
        keep: dict = {}
        outs = T.forward(params, x, keep)
        loss, douts = batch_loss(outs, tg)
        grads = backward(params, keep, x.shape, douts)
        del keep
        if widx and args.wide_batch:
            wi = rng.choice(widx, args.wide_batch)
            xw = wide[wi].astype(np.float32) / 255.0
            if rng.random() < 0.5:
                xw = xw[:, :, ::-1].copy()
            keep = {}
            ow = T.forward(params, xw, keep)
            lw, dw = batch_loss(ow, [wide_targets(labels["wide"][k]["cls"]) for k in wi],
                                cls_weight=0.5, obj=False)
            gw = backward(params, keep, xw.shape, dw)
            for k in grads:
                grads[k] += gw[k]
            loss += lw
            del keep
        t += 1
        adam_step(params, grads, m, v, t, lr)
        hist.append(loss)
        if t % 50 == 0:
            log(f"step {t}, {time.time() - t0:.0f} s, lr {lr:.5f}, loss {np.mean(hist[-50:]):.4f}")
        if time.time() - last_save > 600:
            save(params, args.out, steps=t)
            last_save = time.time()
    save(params, args.out, steps=t, minutes=args.minutes, batch=args.batch,
         loss=args.loss, neg_ratio=args.neg_ratio, init=args.init,
         wide_batch=args.wide_batch, lr=args.lr, pseudo=bool(args.pseudo),
         loss_last=float(np.mean(hist[-100:])))
    log(f"done: {t} steps, wrote {args.out}")
    return 0


# ---- measuring ----------------------------------------------------------------------
def onnx_net(params):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "tokdet.onnx")
    Path(path).write_bytes(T.to_onnx(params))
    return T.load(path)


def f1(row):
    p, r = row["precision"], row["recall"]
    return round(2 * p * r / max(1e-9, p + r), 3)


def typed_score(frames, looks, cut):
    """Per kind, over the held-out frames: n coins of that kind, claims (a
    detection on a reviewed spot named that kind), right (claim on a coin of
    that kind)."""
    import train_coins
    out = {}
    for f, look in zip(frames, looks):
        dets = coins.merge([d for d in look if d[3] >= cut * coins.LOGIT_FULL])
        matched = set()
        for d in dets:
            kind = d[5]
            hit = [k for k, c in enumerate(f["coins"]) if c["sure"]
                   and train_coins.inside((d[0], d[1]), c["box"]) and k not in matched]
            reviewed = bool(hit) or any(train_coins.inside((d[0], d[1]), n["box"], 0.0)
                                        for n in f.get("not_coins", ()))
            if hit:
                matched.add(hit[0])
            if kind != "unknown" and reviewed:
                row = out.setdefault(kind, {"n": 0, "claims": 0, "right": 0})
                row["claims"] += 1
                if hit:
                    truth = f["coins"][hit[0]]["kind"]
                    row["right"] += kind_index(truth) == kind_index(kind)
        for c in f["coins"]:
            if c["sure"] and kind_index(c["kind"]) >= 0:
                kname = T.CLASSES[kind_index(c["kind"])]
                out.setdefault(kname, {"n": 0, "claims": 0, "right": 0})["n"] += 1
    for row in out.values():
        row["P"] = round(row["right"] / max(1, row["claims"]), 3)
        row["R"] = round(row["right"] / max(1, row["n"]), 3)
        row["F1"] = round(2 * row["P"] * row["R"] / max(1e-9, row["P"] + row["R"]), 3)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["n"]))


def score_set(frames, detectors, shipped) -> dict:
    """Boxes (strict, train_coins.score), kinds and ms per frame for each
    detector on the same frames; `detectors` {name: frame -> look}."""
    import train_coins
    looks = {k: [] for k in detectors}
    ms = {k: [] for k in detectors}
    for f in frames:
        img = cv2.imread(str(LIVE / f["path"]))
        for name, fn in detectors.items():
            t = time.perf_counter()
            look = fn(img)
            ms[name].append((time.perf_counter() - t) * 1000)
            if look and len(look[0]) < 6:       # today's names: the shipped honey head
                merged = coins.merge([d for d in look if d[3] >= 0.25 * coins.LOGIT_FULL])
                kinds = coins.kinds_of(img, merged, m=shipped)
                named = {(d[0], d[1]): k for d, k in zip(merged, kinds)}
                look = [(*d[:5], named.get((d[0], d[1]), "unknown")) for d in look]
            looks[name].append(look)
    out = {"frames": len(frames), "coins": sum(c["sure"] for f in frames for c in f["coins"]),
           "boxes": {}, "kinds": {}, "ms_per_frame": {}, "matched": {}}
    for name, lk in looks.items():
        table = {}
        for cut in THRESHOLDS:
            row = train_coins.score(frames, lk, cut)
            row["F1"] = f1(row)
            table[f"{cut:.2f}"] = row
        out["boxes"][name] = table
        out["kinds"][name] = {f"{c:.2f}": typed_score(frames, lk, c) for c in (0.4, 0.6, 0.9)}
        out["ms_per_frame"][name] = {"median": round(float(np.median(ms[name])), 1),
                                     "p90": round(float(np.percentile(ms[name], 90)), 1)}
    # MATCHED: for each cut of today's (retrained) detector, v2's best recall at
    # a cut where its precision is at least as high
    if "tokdet" in out["boxes"] and "today_retrained" in out["boxes"]:
        mine = out["boxes"]["tokdet"]
        for cut, row in out["boxes"]["today_retrained"].items():
            ok = [(r["recall"], c) for c, r in mine.items() if r["precision"] >= row["precision"]]
            best = max(ok) if ok else None
            out["matched"][cut] = {"today": [row["precision"], row["recall"], row["F1"]],
                                   "tokdet_cut": best[1] if best else None,
                                   "tokdet": ([mine[best[1]]["precision"], mine[best[1]]["recall"],
                                               mine[best[1]]["F1"]] if best else None)}
    return out


def eye_frames(folder: Path):
    """The whole frames graded by eye (scripts/tokdet_eyesheet sheets, then
    grades.json beside index.json), in train_coins' frame shape. A grade
    names candidates by index ("?" = could not settle: an unsure coin, left
    out both ways) and adds "extra" coins [cx, cy, side, kind] no candidate
    covered."""
    if not (folder / "grades.json").exists():
        return []
    grades = json.loads((folder / "grades.json").read_text())
    index = json.loads((folder / "index.json").read_text())
    out = []
    for key, g in sorted(grades.items()):
        if key.startswith("_"):
            continue
        cands = index[key]["candidates"]
        coins_ = [(*cands[int(i)][:3], kind) for i, kind in g.get("cands", {}).items()]
        coins_ += [tuple(e) for e in g.get("extra", ())]
        out.append({"path": index[key]["path"], "partial": False, "not_coins": [],
                    "coins": [{"box": [cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2],
                               "kind": "unknown" if k == "?" else k, "sure": k != "?"}
                              for cx, cy, s, k in coins_]})
    return out


def evaluate(args) -> int:
    import train_coins
    cv2.setNumThreads(2)
    params = load_params(args.model)
    net = onnx_net(params)
    base = coins.Model.load(Path(args.baseline))
    shipped = coins.Model.load(coins.MODEL)
    detectors = {"tokdet": lambda im: T.run(net, im),
                 "today_retrained": lambda im: coins.look(im, m=base),
                 "today_shipped": lambda im: coins.look(im, m=shipped)}
    _train, held = tokdet_split.split(train_coins.load_frames(LIVE))
    report = {"made": time.strftime("%Y-%m-%d %H:%M:%S"), "model": str(args.model),
              "held_out_nights": tokdet_split.HELD_OUT,
              "note": "held_out frames are all 'partial': precision counts only detections "
                      "on a reviewed coin or not-coin. today_shipped trained on them.",
              "held_out": score_set(held, detectors, shipped)}
    for name in ("eyetest", "eyetest_b"):
        eye = eye_frames(DATA / name)
        if eye:
            report[name] = score_set(eye, detectors, shipped)
    # the self crops of held-out nights: kind at the centre, tokdet vs the honey head
    labels = json.loads((DATA / "labels.json").read_text())
    wide = np.load(DATA / "wide.npy")
    idx = [i for i, r in enumerate(labels["wide"]) if r["held"]]
    out = T.forward({k: v for k, v in params.items()}, wide[idx].astype(np.float32) / 255.0)
    g = WIDE_IN // T.LEVELS[0][2]
    cen = out["p3"][:, g // 2 - 1:g // 2 + 1, g // 2 - 1:g // 2 + 1, T.EXTRA:].mean((1, 2))
    q = np.exp(cen - cen.max(1, keepdims=True))
    q /= q.sum(1, keepdims=True)
    pred = [T.CLASSES[int(r.argmax())] if r.max() >= T.TAU and T.CLASSES[int(r.argmax())] != "other"
            else "unknown" for r in q]
    # the honey head on the same crops, cut as live (coin side 112 px x CROP_PAD)
    hc = []
    for i in idx:
        w = coins.work_image(cv2.imread(str(TYPED / "wide" / (labels["wide"][i]["id"][5:] + ".jpg"))))
        half = w.shape[0] / 2
        hc.append(coins.crop(w, half, half, 112 * coins.WORK_SCALE * coins.CROP_PAD))
    from hivemind.vision import coinnet
    z = coinnet.logits(shipped.honey, np.array(hc, np.float32) / 255.0)
    hp = ["honey" if 1 / (1 + math.exp(-v)) >= shipped.honey_p else "unknown" for v in z]
    truth = [labels["wide"][i]["label"] for i in idx]
    truth = [T.CLASSES[kind_index(t)] for t in truth]
    report["self_crops"] = {"rows": len(idx), "nights": SELF_HELD_OUT,
                            "tokdet": _per_kind(truth, pred), "today_honey_head": _per_kind(truth, hp)}
    Path(args.report).write_text(json.dumps(report, indent=1) + "\n")
    for part in ("held_out", "eyetest", "eyetest_b"):
        for name, table in report.get(part, {}).get("boxes", {}).items():
            log(f"{part} {name}: " + "  ".join(
                f"{c} P{r['precision']} R{r['recall']} F1 {r['F1']}" for c, r in table.items())
                + f"  | {report[part]['ms_per_frame'][name]}")
    log(f"self crops: {json.dumps(report['self_crops'])}")
    log(f"wrote {args.report}")
    return 0


def _per_kind(truth, pred):
    out = {}
    for k in sorted(set(truth) | {p for p in pred if p != "unknown"}):
        n = sum(t == k for t in truth)
        claims = sum(p == k for p in pred)
        right = sum(t == k and p == k for t, p in zip(truth, pred))
        P, R = right / max(1, claims), right / max(1, n)
        out[k] = {"n": n, "claims": claims, "right": right, "P": round(P, 3), "R": round(R, 3),
                  "F1": round(2 * P * R / max(1e-9, P + R), 3)}
    out["_accuracy"] = round(sum(t == p for t, p in zip(truth, pred)) / max(1, len(truth)), 3)
    return out


def export(args) -> int:
    params = load_params(args.model)
    Path(args.onnx).write_bytes(T.to_onnx(params))
    log(f"wrote {args.onnx}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--teacher", default="")
    b.add_argument("--pseudo", type=int, default=2400)
    t = sub.add_parser("train")
    t.add_argument("--minutes", type=float, default=80)
    t.add_argument("--batch", type=int, default=12)
    t.add_argument("--wide-batch", type=int, default=24)
    t.add_argument("--lr", type=float, default=2e-3)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--pseudo", type=int, default=1, help="0: hand frames only")
    t.add_argument("--init", default="")
    t.add_argument("--loss", default="focal", choices=("focal", "bce"))
    t.add_argument("--neg-ratio", type=float, default=NEG_RATIO)
    t.add_argument("--out", default=str(DATA / "tokdet.npz"))
    e = sub.add_parser("score")
    e.add_argument("--model", default=str(DATA / "tokdet.npz"))
    e.add_argument("--baseline", default=str(DATA / "coins_trainnights.npz"))
    e.add_argument("--report", default=str(DATA / "report.json"))
    x = sub.add_parser("export")
    x.add_argument("--model", default=str(DATA / "tokdet.npz"))
    x.add_argument("--onnx", default=str(T.MODEL))
    args = ap.parse_args()
    return {"build": build, "train": train, "score": evaluate, "export": export}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
