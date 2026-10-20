#!/usr/bin/env python3
"""Train the token-TYPE classifier (vision/tokentypes) and score it against
today's model on the same held-out crops.

    ./scripts/train_token_types.py [--dataset DIR] [--variants eco,small,full]
                                   [--epochs 30] [--out DIR] [--negatives DIR]
    ./scripts/train_token_types.py --verdicts MODEL.npz     # the HUD outside check

THE SHIPPED data/models/token_types.npz (2026-10-27, ~29 min on 2 threads) is
`--variants small --epochs 20 --negatives <datasets/sprinkler>`'s
token_types_small.npz, copied; its numbers are data/models/token_types.json
and docs/pending/ai-tokens-typed.md.

The data is scripts/build_token_dataset.py's (datasets/tokens-typed/<colour>/
manifest.jsonl): hand-boxed coins of coin_labels.json, self-labelled chase
crops and background, split by run into train / val / test. Every crop is
cut the way vision/coins cuts a live sighting -- the frame at WORK_SCALE, the
coin's side x CROP_PAD, 32 px -- from the ORIGINAL picture (the hand frame
under --home, the 192 px chase crop under the dataset's wide/), so the
network sees at train time exactly what it will see live. A chase crop has
no coin size, so it is the median labelled coin's (112 px), as
train_coins.py --school does.

THE CLASSES are every kind with at least MIN_TRAIN train rows, "other" (a coin
of a kind too rare to learn: merged, it still counts as a coin), and
"background".

THREE SIZES, chosen on val, measured once on test:
  eco    today's coin network, frozen, with a new softmax layer on its 64
         hidden units -- the "type head" on coinnet; costs one 64 x K product
         on top of a coin forward
  small  coinnet's shape (16/32/64 channels, 64 hidden), K outputs, started
         from today's coin weights and trained whole
  full   twice the width (32/64/128, 128 hidden), from scratch

TODAY'S MODEL on the same crops: a coin if the coin network's p >= REPORT_P
(what vision/tokens.detect reports), then "honey" if the honey head says so,
else no type. NOTE it was trained on every coin_labels.json frame, so on the
hand test rows it is scored on crops it learned from; the new models never
saw a test row.

It never touches the game. Run it niced, under the memory cap, 2 threads.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import cv2                                                      # noqa: E402
import numpy as np                                              # noqa: E402

from hivemind.vision import coinnet, coins, tokentypes          # noqa: E402
from train_coins import backward, colour_jitter, turned_crop    # noqa: E402

MIN_TRAIN = 10
AUG = 12                    # augmented copies of each train row (plus the row itself)
WIDE = 192                  # brain/school.WIDE_CROP
WIDE_SIDE = 112             # the median labelled coin, frame px (train_coins.SCHOOL_WIDE_SIDE / CROP_PAD)
VARIANTS = {
    "eco": None,
    "small": dict(chans=(3, 16, 32, 64), hidden=64),
    "full": dict(chans=(3, 32, 64, 128), hidden=128),
}
NEG_AUG = 2                 # augmented copies of each --negatives row
TAUS = (0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ---- the crops ---------------------------------------------------------------------
def geometry(row: dict, dataset: Path, home: Path, cache: dict):
    """(work image, cx, cy, crop side) in WORK pixels, as vision/coins crops."""
    scale = coins.WORK_SCALE
    if row["source"] == "self":
        key = dataset / row["wide"]
        side = WIDE_SIDE
        cx = cy = WIDE / 2
    elif "image_scale" in row:              # --negatives: a half-size route frame
        key = Path(row["image"])
        (cx, cy), side = row["point"], WIDE_SIDE
        scale = coins.WORK_SCALE / row["image_scale"]
    else:
        key = home / row["src"]
        x0, y0, x1, y1 = row["box"]
        cx, cy, side = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0)
    if key not in cache:
        img = cv2.imread(str(key))
        cache[key] = None if img is None else (
            coins.work_image(img) if scale == coins.WORK_SCALE else
            cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR))
    s = coins.WORK_SCALE
    return cache[key], cx * s, cy * s, side * s * coins.CROP_PAD


def crops_for(rows, dataset, home, rng=None, aug=0):
    """32 px crops (uint8) and the row index each came from; with `aug`, that
    many shifted / rescaled / turned / mirrored / recoloured copies too."""
    cache: dict = {}
    X, idx = [], []
    for i, r in enumerate(rows):
        work, cx, cy, side = geometry(r, dataset, home, cache)
        if work is None:
            continue
        X.append(coins.crop(work, cx, cy, side))
        idx.append(i)
        for k in range(min(aug, r.get("aug", aug))):
            s = side * rng.uniform(0.85, 1.2)
            dx, dy = rng.uniform(-.12, .12, 2) * side / coins.CROP_PAD
            c = turned_crop(work, cx + dx, cy + dy, s, rng.uniform(-12, 12), bool(k % 2))
            X.append(colour_jitter(c, rng))
            idx.append(i)
        if len(cache) > 64:                 # hand frames come grouped; keep memory flat
            cache.clear()
    return np.array(X, np.uint8), np.array(idx)


def split_of(run: str) -> str:
    """scripts/build_token_dataset.split_of: train / val / test by sha1 of the run."""
    h = int(hashlib.sha1(run.encode()).hexdigest(), 16) % 100
    return "train" if h < 70 else "val" if h < 85 else "test"


def negative_rows(sdir: Path, rng) -> list[dict]:
    """Background the chases showed the coin network passing: the Golden
    Gushers (datasets/sprinkler boxes, centre and cap) and two random world
    points on each frame certain to have no Gusher -- field floor, flowers.
    Split by the token dataset's rule on the same run name, so no run is in
    two splits. ponytail: a random point can land on a token (a few %)."""
    out = []
    for line in (sdir / "manifest.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        common = {"label": "background", "image": str(sdir / r["image"]), "aug": NEG_AUG,
                  "image_scale": r["image_scale"], "split": split_of(f"attempt-{r['run']}")}
        if r["label"] == "sprinkler":
            for b in r["boxes"]:
                x, y, w, h = b["box"]                       # full-frame x, y, width, height
                for cy in (y + h / 2, y + w / 2):
                    out.append({**common, "source": "sprinkler", "point": [x + w / 2, cy]})
        elif r["label"] == "absent_certain":
            wx0, wy0, wx1, wy1 = coins.world_box(1920, 1080)
            for _ in range(2):
                out.append({**common, "source": "field",
                            "point": [rng.uniform(wx0, wx1), rng.uniform(wy0, wy1)]})
    return out


# ---- training -----------------------------------------------------------------------
def softmax(z):
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def class_weights(y, k):
    n = np.bincount(y, minlength=k).astype(np.float32)
    w = 1.0 / np.sqrt(np.maximum(n, 1))         # ponytail: sqrt-balanced; focal loss if rare kinds stay at 0
    return w / (w * n).sum() * n.sum()


def adam_train(params, X, y, k, epochs, seed, train_keys, lr=1e-3, wd=1e-4, batch=128,
               feats=None, val=None):
    """Softmax cross-entropy, Adam. `feats` (precomputed frozen hidden units)
    trains only w4/b4 (eco). Keeps the epoch that scores best on `val`."""
    rng = np.random.default_rng(seed)
    cw = class_weights(y, k)
    m = {kk: np.zeros_like(params[kk]) for kk in train_keys}
    v = {kk: np.zeros_like(params[kk]) for kk in train_keys}
    t, best = 0, (-1.0, None, 0)
    for ep in range(epochs):
        order = rng.permutation(len(y))
        total = 0.0
        for s in range(0, len(y), batch):
            ib = order[s:s + batch]
            yb = y[ib]
            if feats is not None:
                act = feats[ib]
                z = act @ params["w4"] + params["b4"]
            else:
                cache: list = []
                z = coinnet.forward(params, X[ib].astype(np.float32) / 255.0, keep=cache)
            p = softmax(z)
            wgt = cw[yb] / cw[yb].sum()
            total += -(wgt * np.log(p[np.arange(len(yb)), yb] + 1e-7)).sum() * len(yb)
            d = p.copy()
            d[np.arange(len(yb)), yb] -= 1
            d *= wgt[:, None]
            if feats is not None:
                g = {"w4": act.T @ d, "b4": d.sum(0)}
            else:
                g = backward(params, cache, d)
            t += 1
            for kk in train_keys:
                gk = g[kk] + wd * params[kk]
                m[kk] = 0.9 * m[kk] + 0.1 * gk
                v[kk] = 0.999 * v[kk] + 0.001 * gk * gk
                step = lr * (m[kk] / (1 - 0.9 ** t)) / (np.sqrt(v[kk] / (1 - 0.999 ** t)) + 1e-8)
                params[kk] = (params[kk] - step).astype(np.float32)
        msg = f"    epoch {ep + 1}/{epochs}, loss {total / len(y):.4f}"
        if val is not None:
            f1 = val(params)
            msg += f", val macro-F1 {f1:.3f}"
            if f1 > best[0]:
                best = (f1, {kk: vv.copy() for kk, vv in params.items()}, ep + 1)
        log(msg)
    if best[1] is not None:
        log(f"    kept epoch {best[2]} (val macro-F1 {best[0]:.3f})")
        return best[1], best[2]
    return params, epochs


def hidden_units(params, X):
    """The 64 hidden units of the coin network (eco's frozen features)."""
    out = []
    for s in range(0, len(X), 256):
        cache: list = []
        coinnet.forward(params, X[s:s + 256].astype(np.float32) / 255.0, keep=cache)
        out.append(cache[coinnet.LAYERS][3])
    return np.concatenate(out)


# ---- scoring ------------------------------------------------------------------------
def prf(truth, pred, classes):
    """Per class (n, precision, recall, F1); "unknown" predictions are no claim."""
    out = {}
    for c in classes:
        tp = sum(1 for t, p in zip(truth, pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(truth, pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(truth, pred) if t == c and p != c)
        P = tp / (tp + fp) if tp + fp else 0.0
        R = tp / (tp + fn) if tp + fn else 0.0
        out[c] = {"n": tp + fn, "claimed": tp + fp, "precision": round(P, 3), "recall": round(R, 3),
                  "f1": round(2 * P * R / (P + R), 3) if P + R else 0.0}
    return out


def macro_f1(table, typed):
    vals = [table[c]["f1"] for c in typed if table[c]["n"] > 0]
    return float(np.mean(vals)) if vals else 0.0


def predict(probs, classes, tau):
    """argmax, or "unknown" (a coin, no type claimed) when a non-background
    winner is under `tau`; "other" is also no type claimed."""
    out = []
    for p in probs:
        j = int(p.argmax())
        c = classes[j]
        if c != "background" and (p[j] < tau or c == "other"):
            c = "unknown"
        out.append(c)
    return out


def coin_table(truth, pred):
    """Coin (any kind) vs background."""
    t = ["coin" if x != "background" else "background" for x in truth]
    p = ["coin" if x != "background" else "background" for x in pred]
    return prf(t, p, ["coin"])["coin"]


def latency(fn, crops, n, reps=200):
    batch = crops[:n].astype(np.float32) / 255.0
    for _ in range(10):
        fn(batch)
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn(batch)
        ts.append((time.perf_counter() - t0) * 1000)
    return round(float(np.median(ts)), 3), round(float(np.percentile(ts, 95)), 3)


def evidence_class(evidence: str) -> str | None:
    """brain/school.judge's "collected" evidence as honey/haste/stacks/pollen
    (scripts/build_token_dataset.evidence_class)."""
    e = evidence or ""
    if e.startswith("honey rose"):
        return "honey"
    if e.startswith(("haste ", "the Haste's square")):
        return "haste"
    if e.startswith(("the buff bar's stacks", "a buff's stacks rose", "a buff appeared")):
        return "stacks"
    if e.startswith("pollen rose"):
        return "pollen"
    return None


def verdicts(model_path: Path, school: Path, dataset: Path) -> dict:
    """An outside check on chases NO model trained on: every wide chase crop
    not in the dataset, named by the model, against what the HUD said after
    the chase reached it. A kind's verdict rate over the base rate is the
    signal (a neighbour can pay instead, so no rate is 100%)."""
    from hivemind.brain.school import NEVER, Lesson, _legacy_verdict
    used = {Path(json.loads(line)["src"]).name for line in (dataset / "manifest.jsonl").open()
            if json.loads(line)["source"] == "self"}
    m = tokentypes.Model.load(model_path)
    today = coins.Model.load(coins.MODEL)
    rows = []
    for line in (school / "lessons.jsonl").open():
        body = json.loads(line)
        lesson = Lesson(**{k: body.get(k) for k in Lesson.__dataclass_fields__})
        path = school / "crops-wide" / f"{lesson.id}.jpg"
        if path.name in used or lesson.evidence == NEVER or not path.exists():
            continue
        img = cv2.imread(str(path))
        if img is None or img.shape[:2] != (WIDE, WIDE):
            continue
        half = WIDE * coins.WORK_SCALE / 2
        c = coins.crop(coins.work_image(img), half, half, WIDE_SIDE * coins.WORK_SCALE * coins.CROP_PAD)
        hud = lesson.outcome == "collected" and not _legacy_verdict(lesson)
        rows.append((c, evidence_class(lesson.evidence) if hud else None))
    X = np.array([r[0] for r in rows], np.float32) / 255.0
    named = m.name(X)
    hp = 1 / (1 + np.exp(-np.clip(coinnet.logits(today.honey, X), -30, 30)))
    honey_today = ["honey" if p >= today.honey_p else "unknown" for p in hp]
    out = {"reached_chases": len(rows)}
    for who, names in (("typed", named), ("today", honey_today)):
        tab = {}
        for kind in sorted(set(names)) + ["ALL"]:
            ev = [e for n, (_, e) in zip(names, rows) if kind == "ALL" or n == kind]
            cnt = collections.Counter(ev)
            tab[kind] = {"n": len(ev), **{c: round(cnt[c] / max(1, len(ev)), 3)
                                         for c in ("honey", "haste", "stacks", "pollen")}}
        out[who] = tab
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path,
                    default=Path(os.environ.get("HIVEMIND_WORK") or Path.home() / ".cache/hivemind-dev") / "datasets/tokens-typed/blue")
    ap.add_argument("--home", type=Path, default=Path.home() / "Hivemind",
                    help="the live tree the hand frames' paths are relative to (only read)")
    ap.add_argument("--variants", default="eco,small,full")
    ap.add_argument("--negatives", type=Path, default=None, metavar="SPRINKLER_DATASET",
                    help="add datasets/sprinkler's Gushers and field floor as background")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "models")
    ap.add_argument("--report", type=Path, default=None, help="where the numbers go (json)")
    ap.add_argument("--verdicts", type=Path, default=None, metavar="MODEL.npz",
                    help="only the outside check: this model on the chases the dataset left out")
    args = ap.parse_args()
    if args.verdicts:
        print(json.dumps(verdicts(args.verdicts, args.home / "var/school-coins", args.dataset), indent=1))
        return 0

    rows = [json.loads(line) for line in (args.dataset / "manifest.jsonl").open(encoding="utf-8")]
    dataset_name = "/".join(args.dataset.parts[-2:])    # no home path in the repo
    train_counts = collections.Counter(r["label"] for r in rows if r["split"] == "train")
    kinds = sorted(k for k, n in train_counts.items() if n >= MIN_TRAIN and k != "background")
    classes = ["background", *kinds, "other"]
    k = len(classes)
    name = {c: i for i, c in enumerate(classes)}

    def cls(r):
        return r["label"] if r["label"] in name else "other"

    log(f"classes ({k}): {classes}")
    rng = np.random.default_rng(0)
    if args.negatives:
        neg = negative_rows(args.negatives, rng)
        rows += neg
        log(f"negatives: {dict(collections.Counter((r['split'], r['source']) for r in neg))}")
    split = {s: [r for r in rows if r["split"] == s] for s in ("train", "val", "test")}
    Xtr, itr = crops_for(split["train"], args.dataset, args.home, rng, AUG)
    ytr = np.array([name[cls(split["train"][i])] for i in itr])
    Xva, iva = crops_for(split["val"], args.dataset, args.home)
    Xte, ite = crops_for(split["test"], args.dataset, args.home)
    tva = [cls(split["val"][i]) for i in iva]
    tte = [cls(split["test"][i]) for i in ite]
    rte = [split["test"][i] for i in ite]
    log(f"crops: train {len(Xtr)} ({len(set(itr))} rows x{AUG + 1}), val {len(Xva)}, test {len(Xte)}")
    typed = [c for c in classes if c not in ("background", "other")]

    today = coins.Model.load(coins.MODEL)

    def today_pred(X):
        z = coinnet.logits(today.params, X.astype(np.float32) / 255.0)
        hz = coinnet.logits(today.honey, X.astype(np.float32) / 255.0)
        hp = 1 / (1 + np.exp(-np.clip(hz, -30, 30)))
        coin = 1 / (1 + np.exp(-np.clip(z, -30, 30))) >= coins.REPORT_P
        return ["background" if not c else ("honey" if h >= today.honey_p else "unknown")
                for c, h in zip(coin, hp)]

    report = {"made": time.strftime("%Y-%m-%d %H:%M"), "dataset": dataset_name,
              "classes": classes, "train_rows": dict(train_counts),
              "crops": {"train": int(len(Xtr)), "val": int(len(Xva)), "test": int(len(Xte))},
              "test_rows": dict(collections.Counter(tte)), "variants": {}}

    def slices(pred):
        out = {}
        orig = ("self", "hand", "hand_not_coin", "hand_background")
        for nm, keep in (("all", lambda r: r["source"] in orig),
                         ("hand", lambda r: r["source"] in orig[1:]),
                         ("self", lambda r: r["source"] in orig and (
                             r["source"] == "self" or r["label"] == "background")),
                         ("negatives", lambda r: r["source"] not in orig)):
            ix = [j for j, r in enumerate(rte) if keep(r)]
            t, p = [tte[j] for j in ix], [pred[j] for j in ix]
            tab = prf(t, p, ["background", *typed])
            if nm == "negatives":
                out[nm] = {"rows": len(ix), "named_a_kind": sum(x not in ("background", "unknown")
                                                                 for x in p)}
                continue
            out[nm] = {"rows": len(ix), "per_class": tab, "macro_f1_typed": round(macro_f1(tab, typed), 3),
                       "coin_vs_background": coin_table(t, p)}
        return out

    pt = today_pred(Xte)
    report["today"] = {"test": slices(pt), "val_macro_f1": round(macro_f1(
        prf(tva, today_pred(Xva), typed), typed), 3),
        "latency_ms_10_crops": latency(lambda b: coinnet.forward(today.honey, b), Xte, 10)}
    log(f"today: test macro-F1 (typed) {report['today']['test']['all']['macro_f1_typed']}")

    # The pipeline as it would ship: today's coin network decides "coin";
    # the new model only names the kind of what it called a coin.
    gate = np.array([p != "background" for p in pt])

    for vname in args.variants.split(","):
        log(f"variant {vname}")
        t0 = time.time()
        if vname == "eco":
            params = {kk: v.copy() for kk, v in today.params.items()}
            params["w4"] = (rng.standard_normal((64, k)) * 0.1).astype(np.float32)
            params["b4"] = np.zeros(k, np.float32)
            ftr, fva = hidden_units(today.params, Xtr), hidden_units(today.params, Xva)

            def val_f1(p, fva=fva):
                pr = softmax(fva @ p["w4"] + p["b4"])
                return macro_f1(prf(tva, predict(pr, classes, 0.0), typed), typed)
            params, ep = adam_train(params, None, ytr, k, args.epochs * 4, 0, ("w4", "b4"),
                                    lr=3e-3, feats=ftr, val=val_f1)
        else:
            cfg = VARIANTS[vname]
            params = coinnet.fresh(size=coins.CROP_SIZE, seed=1, outputs=k, **cfg)
            if vname == "small":            # start from today's coin features
                for kk in ("w0", "b0", "w1", "b1", "w2", "b2", "w3", "b3"):
                    params[kk] = today.params[kk].copy()

            def val_f1(p):
                pr = softmax(coinnet.logits(p, Xva.astype(np.float32) / 255.0))
                return macro_f1(prf(tva, predict(pr, classes, 0.0), typed), typed)
            params, ep = adam_train(params, Xtr, ytr, k, args.epochs, 0, tuple(params), val=val_f1)
        secs = round(time.time() - t0)

        def probs(X, params=params):
            return softmax(coinnet.logits(params, X.astype(np.float32) / 255.0))
        pva, pte = probs(Xva), probs(Xte)
        tau = max(TAUS, key=lambda t: macro_f1(prf(tva, predict(pva, classes, t), typed), typed))
        pred = predict(pte, classes, tau)
        shipped = [("background" if not g else (p if p not in ("background",) else "unknown"))
                   for g, p in zip(gate, pred)]
        nparams = int(sum(v.size for v in params.values()))
        row = {"epochs_kept": ep, "train_seconds": secs, "tau": tau, "params": nparams,
               "standalone": slices(pred), "behind_todays_coin_gate": slices(shipped),
               "latency_ms_10_crops": latency(lambda b: coinnet.forward(params, b), Xte, 10),
               "latency_ms_1_crop": latency(lambda b: coinnet.forward(params, b), Xte, 1),
               "latency_ms_40_crops": latency(lambda b: coinnet.forward(params, b), Xte, 40, 50),
               "confusion": dict(collections.Counter(f"{t}->{p}" for t, p in zip(tte, pred) if t != p))}
        report["variants"][vname] = row
        log(f"  {vname}: tau {tau}, test macro-F1 standalone "
            f"{row['standalone']['all']['macro_f1_typed']}, behind gate "
            f"{row['behind_todays_coin_gate']['all']['macro_f1_typed']}, "
            f"{nparams} params, {row['latency_ms_10_crops']} ms / 10 crops")
        args.out.mkdir(parents=True, exist_ok=True)
        tokentypes.Model(params, classes, tau).save(
            args.out / f"token_types_{vname}.npz", dataset=dataset_name, epochs=ep)
    out = args.report or args.out / "token_types_report.json"
    out.write_text(json.dumps(report, indent=1))
    log(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
