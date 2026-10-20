#!/usr/bin/env python3
"""Train and measure the buff-icon reader (vision/bufficons).

Data: scripts/bufficons_data.py (extract, cluster, label) in
$HIVEMIND_WORK/datasets/bufficons -- slots.jsonl holds, per bar slot of
every kept frame, the class `y` and the drain line (`line` raw, `dline` on a
clean track). Split BY NIGHT (bufficons_data.night_of): sorted nights, every
TEST_EVERY-th one held out for test, the one before it for validation; the
test nights are never trained on or used to pick an epoch.

    PYTHONPATH=src nice -n 19 capped --mem 3000M python scripts/train_bufficons.py \
        [--epochs 8] [--out data/models/bufficons.npz]

Writes the model and <out>.json (every number: per-class P/R/F1 for the model
and for vision/buffs' template reader on the same test slots, drain error,
milliseconds a bar).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from hivemind.vision import bufficons, buffs, coinnet                # noqa: E402
import bufficons_data as bd                                           # noqa: E402
from train_coins import backward                                     # noqa: E402

TEST_EVERY = 4
CAP_PER_CLASS = 5000       # training rows a class at most (tabby, the forks...)
# BACKGROUND IS MOST OF THE BAR and the hard part. MEASURED on the first model
# (5,000 background rows, union eye-check of test nights): flat white or pale
# scenery read as a polar bear morph (22 of 48 claims wrong) or Melody (24 of
# 34), flat dark green as Focus (7 of 48). So more background, and with
# --hard every background row of the TRAINING nights a previous model calls
# an icon (hard negatives) on top.
CAP_BACKGROUND = 15000
CAP_HARD = 20000
MIN_TRAIN = 30             # a class with fewer training rows is left out
DRAIN_WEIGHT = 2.0         # the share-left loss next to cross-entropy
RAW_LINE_WEIGHT = 0.3      # a slot off any clean track: its raw line, trusted less
TAU = 0.6


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def splits(meta):
    nights = sorted({m["night"] for m in meta})
    test = {n for k, n in enumerate(nights) if k % TEST_EVERY == TEST_EVERY - 1}
    val = {n for k, n in enumerate(nights) if k % TEST_EVERY == TEST_EVERY - 2}
    return nights, test, val


def crops_of(bands, rows, rng=None):
    out = np.empty((len(rows), bd.ICON, bd.ICON, 3), np.uint8)
    for n, r in enumerate(rows):
        s = r["slot"]
        if rng is not None and rng.random() < 0.3:
            # mid-slide: the bar moves when an icon ahead expires
            dx = int(rng.integers(-3, 4))
            x0 = min(max(0, s * bd.ICON + dx), bd.WIDTH - bd.ICON)
            out[n] = bands[r["i"], :, x0:x0 + bd.ICON]
        else:
            out[n] = bd.slot_crop(bands, r["i"], s)
    return out


def targets(rows, classes):
    k = {c: j for j, c in enumerate(classes)}
    y = np.array([k[r["y"]] for r in rows])
    left = np.zeros(len(rows), np.float32)
    w = np.zeros(len(rows), np.float32)
    for n, r in enumerate(rows):
        if "dline" in r:
            left[n], w[n] = (bd.ICON - r["dline"]) / bd.ICON, 1.0
        elif "line" in r:
            left[n], w[n] = (bd.ICON - r["line"]) / bd.ICON, RAW_LINE_WEIGHT
    return y, left, w


def train(bands, rows, classes, epochs, seed, val_rows, lr=1e-3, wd=1e-4, batch=128):
    rng = np.random.default_rng(seed)
    k = len(classes)
    params = coinnet.fresh(size=bufficons.SIZE, seed=seed, outputs=k + 1)
    y, left, w = targets(rows, classes)
    n_by = np.bincount(y, minlength=k).astype(np.float32)
    cw = 1.0 / np.sqrt(np.maximum(n_by, 1))
    cw = cw / (cw * n_by).sum() * n_by.sum()
    m = {kk: np.zeros_like(v) for kk, v in params.items()}
    v = {kk: np.zeros_like(v2) for kk, v2 in params.items()}
    t, best = 0, (-1.0, None, 0)
    vX = bufficons.prepare(crops_of(bands, val_rows))
    vy, _, _ = targets(val_rows, classes)
    for ep in range(epochs):
        order = rng.permutation(len(rows))
        total = 0.0
        for s in range(0, len(rows), batch):
            ib = order[s:s + batch]
            xb = crops_of(bands, [rows[j] for j in ib], rng).astype(np.float32)
            xb *= rng.uniform(0.85, 1.15, (len(ib), 1, 1, 1)).astype(np.float32)
            xb = bufficons.prepare(np.clip(xb, 0, 255).astype(np.uint8))
            cache: list = []
            z = coinnet.forward(params, xb, keep=cache)
            zc = z[:, :k] - z[:, :k].max(1, keepdims=True)
            p = np.exp(zc)
            p /= p.sum(1, keepdims=True)
            yb = y[ib]
            wgt = cw[yb] / cw[yb].sum()
            total += -(wgt * np.log(p[np.arange(len(ib)), yb] + 1e-7)).sum() * len(ib)
            d = np.zeros_like(z)
            d[:, :k] = p
            d[np.arange(len(ib)), yb] -= 1
            d[:, :k] *= wgt[:, None]
            sg = 1 / (1 + np.exp(-np.clip(z[:, k], -30, 30)))
            dw = w[ib] / len(ib)
            d[:, k] = DRAIN_WEIGHT * dw * 2 * (sg - left[ib]) * sg * (1 - sg)
            g = backward(params, cache, d)
            t += 1
            for kk in params:
                gk = g[kk] + wd * params[kk]
                m[kk] = 0.9 * m[kk] + 0.1 * gk
                v[kk] = 0.999 * v[kk] + 0.001 * gk * gk
                step = lr * (m[kk] / (1 - 0.9 ** t)) / (np.sqrt(v[kk] / (1 - 0.999 ** t)) + 1e-8)
                params[kk] = (params[kk] - step).astype(np.float32)
        z = coinnet.logits(params, vX)
        # classes with a handful of val rows swing this by whole points: only 20+
        table = prf(vy, z[:, :k].argmax(1), range(k))
        f1 = macro_f1({c: v for c, v in table.items() if v["n"] >= 20})
        log(f"  epoch {ep + 1}/{epochs}: loss {total / len(rows):.4f}, val macro-F1 {f1:.3f}")
        if f1 > best[0]:
            best = (f1, {kk: vv.copy() for kk, vv in params.items()}, ep + 1)
    log(f"  kept epoch {best[2]} (val macro-F1 {best[0]:.3f})")
    return best[1]


def prf(truth, pred, labels):
    truth, pred = np.asarray(truth), np.asarray(pred)
    out = {}
    for c in labels:
        tp = int(((truth == c) & (pred == c)).sum())
        fp = int(((truth != c) & (pred == c)).sum())
        fn = int(((truth == c) & (pred != c)).sum())
        P = tp / (tp + fp) if tp + fp else 0.0
        R = tp / (tp + fn) if tp + fn else 0.0
        out[c] = {"n": tp + fn, "claimed": tp + fp, "p": round(P, 3), "r": round(R, 3),
                  "f1": round(2 * P * R / (P + R), 3) if P + R else 0.0}
    return out


def macro_f1(table, skip=()):
    vals = [v["f1"] for c, v in table.items() if v["n"] > 0 and c not in skip]
    return float(np.mean(vals)) if vals else 0.0


def template_reader(band) -> dict[int, str]:
    """slot -> name as vision/buffs reads the bar today (its own acceptance
    lines: ICON_MIN_SCORE for Haste/Melody, BEAR_MIN_SCORE for a morph)."""
    f = bd.frame_of(band)
    out = {}
    for name in ("haste", "melody"):
        for h in buffs.find_all(f, name):
            out.setdefault(h.slot, name)
    b = buffs.bear(f)
    if b.present:
        r0, r1 = buffs.BEAR_ROWS
        c0, c1 = buffs.BEAR_COLS
        tpl = buffs._template(f"bear_{b.kind}", colour=True)
        res = cv2.matchTemplate(np.ascontiguousarray(band[r0:r1]),
                                np.ascontiguousarray(tpl[r0:r1, c0:c1]), cv2.TM_CCOEFF_NORMED)[0]
        x = max(0, int(np.argmax(res)) - c0)
        out[int(round(x / bd.ICON))] = f"bear_{b.kind}"
    return out


def template_bar(frame):
    """Today's whole template read of a bar (what run_farm calls per step)."""
    return buffs.haste(frame), buffs.bear(frame), buffs.find(frame, "melody")


def ms(fn, frames, reps=3):
    for f in frames[:5]:
        fn(f)
    ts = []
    for _ in range(reps):
        for f in frames:
            t0 = time.perf_counter()
            fn(f)
            ts.append((time.perf_counter() - t0) * 1000)
    return {"median": round(float(np.median(ts)), 3), "p95": round(float(np.percentile(ts, 95)), 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "data/models/bufficons.npz")
    ap.add_argument("--eval-only", action="store_true", help="measure the model already at --out")
    ap.add_argument("--hard", type=Path, help="a previous model: add the background it calls an icon")
    a = ap.parse_args()
    bands, meta = bd.load()
    rows = [json.loads(x) for x in open(bd.OUT / "slots.jsonl")]
    rows = [r for r in rows if r.get("y")]
    nights, test_n, val_n = splits(meta)
    part = {r_i: ("test" if meta[r_i]["night"] in test_n else "val" if meta[r_i]["night"] in val_n
                  else "train") for r_i in range(len(meta))}
    rng = np.random.default_rng(a.seed)
    tr_all = [r for r in rows if part[r["i"]] == "train"]
    counts = {}
    for r in tr_all:
        counts[r["y"]] = counts.get(r["y"], 0) + 1
    classes = sorted(c for c, n in counts.items() if n >= MIN_TRAIN)
    classes.remove("background")
    classes = ["background"] + classes
    keep = set(classes)
    train_rows = []
    for c in classes:
        rs = [r for r in tr_all if r["y"] == c]
        if c == "background":
            rng.shuffle(rs)
            hard = []
            if a.hard:
                old = bufficons.Model.load(a.hard)
                for s in range(0, len(rs), 4096):
                    pp, _ = old.predict(crops_of(bands, rs[s:s + 4096]))
                    hard += [rs[s + j] for j in np.flatnonzero(pp.argmax(1) != 0)]
                log(f"hard negatives: {len(hard)} background rows {a.hard.name} calls an icon")
                rng.shuffle(hard)
            ids = {id(r) for r in hard[:CAP_HARD]}
            rs = hard[:CAP_HARD] + [r for r in rs if id(r) not in ids][:CAP_BACKGROUND]
            train_rows += rs
            continue
        if len(rs) > CAP_PER_CLASS:
            # keep every tracked (drain-labelled) row first
            tracked = [r for r in rs if "dline" in r]
            rest = [r for r in rs if "dline" not in r]
            rng.shuffle(rest)
            rs = (tracked + rest)[:max(CAP_PER_CLASS, min(len(tracked), 2 * CAP_PER_CLASS))]
        train_rows += rs
    val_rows = [r for r in rows if part[r["i"]] == "val" and r["y"] in keep]
    if len(val_rows) > 6000:
        val_rows = [val_rows[j] for j in rng.choice(len(val_rows), 6000, replace=False)]
    test_rows = [r for r in rows if part[r["i"]] == "test" and r["y"] in keep]
    log(f"nights {len(nights)}: test {sorted(test_n)}, val {sorted(val_n)}")
    log(f"classes {len(classes)}; train {len(train_rows)}, val {len(val_rows)}, test {len(test_rows)}")

    if a.eval_only:
        model = bufficons.Model.load(a.out)
        assert model.classes == classes, "the data's classes changed since that model"
        params, rates = model.params, model.rates
    else:
        params = train(bands, train_rows, classes, a.epochs, a.seed, val_rows)
        with open(bd.OUT / "rates.json") as fh:
            rates = {c: v["rows_per_s"] for c, v in json.load(fh).items()
                     if c in keep and v["trusted"]}
        with np.load(bd.OUT / "fills.npz") as z:
            named = [str(c) for c in z["names"]]
            fills = {c: z["fills"][j] for j, c in enumerate(named) if c in keep}
            masks = {c: z["masks"][j] for j, c in enumerate(named) if c in keep}
        model = bufficons.Model(params, classes, TAU, rates, fills, masks)
        model.save(a.out)
        log(f"saved {a.out}")

    # ---- test: classes (in chunks: 190k crops at once is gigabytes) ----
    p, left = [], []
    for s in range(0, len(test_rows), 4096):
        pp, ll = model.predict(crops_of(bands, test_rows[s:s + 4096]))
        p.append(pp)
        left.append(ll)
    p, left = np.concatenate(p), np.concatenate(left)
    truth = [r["y"] for r in test_rows]
    pred = []
    for row in p:
        j = int(row.argmax())
        pred.append(classes[j] if row[j] >= TAU or classes[j] == "background" else "background")
    tmpl, cache = [], {}
    for r in test_rows:
        if r["i"] not in cache:
            cache[r["i"]] = template_reader(np.asarray(bands[r["i"]]))
        tmpl.append(cache[r["i"]].get(r["slot"], "background"))
    report = {"nights": nights, "test_nights": sorted(test_n), "val_nights": sorted(val_n),
              "classes": classes, "tau": TAU, "rates_rows_per_s": rates,
              "n": {"train": len(train_rows), "val": len(val_rows), "test": len(test_rows)},
              "params": int(sum(v.size for v in params.values()))}
    report["cnn"] = prf(truth, pred, classes)
    report["template"] = prf(truth, tmpl, classes)
    # an independent check of the labels: label source per class in test
    src = {}
    for r in test_rows:
        s = src.setdefault(r["y"], {"template": 0, "cluster": 0, "both_agree": 0})
        if "tname" in r:
            s["template"] += 1
            if r["cname"] == r["tname"]:
                s["both_agree"] += 1
        else:
            s["cluster"] += 1
    report["label_source_test"] = src

    # ---- test: drain ----
    err = {}
    for n, r in enumerate(test_rows):
        if "dline" not in r:
            continue
        true_left = (bd.ICON - r["dline"]) / bd.ICON
        e = err.setdefault(r["y"], {"cnn_rows": [], "read_rows": [], "tmpl_rows": [], "raw_rows": []})
        e["cnn_rows"].append(abs(float(left[n]) - true_left) * bd.ICON)
        crop = np.asarray(bd.slot_crop(bands, r["i"], r["slot"]))
        e["read_rows"].append(abs(model.left_of(crop, r["y"], float(left[n])) - true_left) * bd.ICON)
        e["raw_rows"].append(abs(r["line"] - r["dline"]))
        if r["y"] == "haste" or r["y"].startswith("bear_"):
            f = bd.frame_of(np.asarray(bands[r["i"]]))
            got = buffs.haste(f) if r["y"] == "haste" else buffs.bear(f)
            if got.present and got.remaining_s is not None:
                rate = buffs.DRAIN_ROWS_PER_S if r["y"] == "haste" else buffs.BEAR_DRAIN_ROWS_PER_S
                e["tmpl_rows"].append(abs(got.remaining_s * rate - true_left * bd.ICON))
    report["drain_test"] = {
        c: {kk: ({"n": len(vv), "mae_rows": round(float(np.mean(vv)), 2),
                  "p90_rows": round(float(np.percentile(vv, 90)), 2),
                  "mae_s": (round(float(np.mean(vv)) / rates[c], 2) if c in rates else None)}
                 if vv else None) for kk, vv in e.items()}
        for c, e in err.items()}

    # ---- speed: one whole bar, both readers, on test frames ----
    frames = [bd.frame_of(np.asarray(bands[i])) for i in sorted(cache)[:300]]
    report["ms_per_bar"] = {"cnn": ms(model.read, frames), "template": ms(template_bar, frames)}

    a.out.with_suffix(".json").write_text(json.dumps(report, indent=1))
    log(json.dumps({"cnn_macro_f1": macro_f1(report["cnn"], ("background",)),
                    "template_macro_f1": macro_f1(report["template"], ("background",)),
                    "ms": report["ms_per_bar"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
