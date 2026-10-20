#!/usr/bin/env python3
"""Self-labelled SPRINKLER dataset: where the Golden Gushers stand on screen.

WHY. The sprinkler anchor (drift fix: walk back until the sprinkler sits in a
central box after each pattern loop) needs a detector, and a detector needs
boxes. Nobody draws them by hand here: the bot's own logs say WHEN it placed
its sprinklers and WHICH sprinklers it owned, and that is the label signal.

WHAT THE DATA ALLOWS (measured 2026-10-26, see docs/pending/sprinkler-dataset.md):
  * the camera turns while a pattern walks (follow camera), and the route
    frames are 0.5-1.5 s apart, so a pixel track from the placing frame
    forward does NOT hold (vision.flow kept 0-7 points and read 0,0 between
    the pattern frames of attempt-1247). Tracking is by appearance, inside one
    gather, not by geometry.
  * the account's sprinkler changed: 1 sprinkler until run 859, 2 (Silver)
    runs 860-895, 3 stacked (Golden Gushers) from run 896 (10-12 08:53) on --
    read from the log's "sprinkler stack: k of N". The Gusher is a tan post
    with toothed rings; nothing of that look exists before run 896.

HOW (positive-unlabelled, by era):
  1. every route frame of a gathering pattern is indexed with its run, field,
     time (file mtime) and the gather's sprinkler state from the run log
     (placed / already standing, before the next "gathering with").
  2. PROPOSALS: tan, taller-than-wide components (the Gusher's colour gate).
     Bees, honey tokens and the character's own yellow parts pass it too.
  3. VERIFIER: a logistic regression on HOG + colour of each proposal, trained
     with proposals from Gusher-era frames after a placing as positives and
     proposals from pre-Gusher frames (no Gusher can be on screen) as
     negatives, on TRAIN runs only. Distractors occur in both eras, the Gusher
     only in one, so the score learns the Gusher.
  4. LABELS: verified boxes in Gusher-era after-placing frames; a gather whose
     frames agree (>= 2 frames with a box) is marked `seq_confirmed`.
     NEGATIVES: pre-Gusher frames ("absent_certain": the object did not
     exist). Gusher-era frames with no verified box are kept as
     "unlabelled" -- the sprinkler may be off screen OR missed.
  5. splits by RUN (hash), so no gather is in two splits; eye-check sheets of
     the test split are written for a person (or Claude) to grade.

Run (heavy: ~17k frames; under the memory cap):
    OPENBLAS_NUM_THREADS=2 nice -n 19 capped --mem 3000M \
        python3 scripts/build_sprinkler_dataset.py --out $HIVEMIND_WORK/datasets/sprinkler

Read-only on ~/Hivemind/var; writes only under --out.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

VAR = Path.home() / "Hivemind" / "var"

# ---- era: which sprinkler the account had ----------------------------------
# "sprinkler stack: k of N" -> N extra sprinklers stacked on the first.
STACK_RE = re.compile(r"sprinkler stack: \d+ of (\d+)")
GUSHER_TOTAL = 3          # Golden Gushers place 3 (economy.yaml tiers)

# ---- run-log events ---------------------------------------------------------
LINE_RE = re.compile(r"^\s+(\d\d):(\d\d):(\d\d)\s\s(.*)$")
GATHER_RE = re.compile(r"gathering with (\S+)")
PLACED = "sprinkler: placed"
STANDING = "sprinkler: already standing"

# ---- route frames -----------------------------------------------------------
# 182621-natro_pattern_pepper_as_natro-01-walk-a16.jpg
FRAME_RE = re.compile(r"^(\d{6})-natro_pattern_(.+?)_as_natro-(\d+)-")

# ---- proposals: the Gusher's colour, at half resolution ---------------------
# MEASURED on attempt-1247/182621-...-02 (the Gusher's sunlit side):
# HSV p10..p90 = (21..26, 86..116, 126..167). Widened for shade and glare.
TAN_LO, TAN_HI = (17, 65, 105), (28, 135, 215)
HUD_TOP, HUD_BOTTOM = 75, 470            # half-res rows: pills/icons, hotbar
MIN_AREA, MAX_AREA = 150, 6000           # half-res px
MIN_TALL, MIN_FILL = 1.0, 0.35           # height/width, area/box
SCALE = 0.5

PATCH_W, PATCH_H = 32, 64
HOG = cv2.HOGDescriptor((PATCH_W, PATCH_H), (16, 16), (8, 8), (8, 8), 9)

SPLITS = (("train", 70), ("val", 15), ("test", 15))


def split_of(run: int) -> str:
    """Stable split by run number: one run (one night's process) is never in
    two splits, so a gather's near-duplicate frames cannot leak."""
    h = int(hashlib.sha1(f"run-{run}".encode()).hexdigest(), 16) % 100
    acc = 0
    for name, share in SPLITS:
        acc += share
        if h < acc:
            return name
    return SPLITS[-1][0]


def sprinklers_in_run(lines) -> int | None:
    """How many sprinklers this run placed per gather: 1 + the stack's N, or
    None when the run never stacked (one sprinkler, or never placed)."""
    most = None
    for ln in lines:
        m = STACK_RE.search(ln)
        if m:
            most = max(most or 0, int(m.group(1)))
    return None if most is None else most + 1


def log_events(lines, end_epoch: float) -> list[tuple[float, str, str]]:
    """(epoch, kind, detail) for gather starts and sprinkler placings. Log lines
    carry only HH:MM:SS; the date comes from the log's mtime (its last line),
    walking backwards and stepping a day back whenever the clock jumps up."""
    stamped = []
    for ln in lines:
        m = LINE_RE.match(ln)
        if m:
            secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            stamped.append((secs, m.group(4)))
    if not stamped:
        return []
    end = dt.datetime.fromtimestamp(end_epoch)
    day = dt.datetime(end.year, end.month, end.day).timestamp()
    if stamped[-1][0] > end.hour * 3600 + end.minute * 60 + end.second + 60:
        day -= 86400                       # last line before midnight, file touched after
    out = []
    prev = None
    for secs, text in reversed(stamped):
        if prev is not None and secs > prev + 3600:
            day -= 86400
        prev = secs
        t = day + secs
        if text.startswith(PLACED):
            out.append((t, "placed", ""))
        elif text.startswith(STANDING):
            out.append((t, "standing", ""))
        else:
            g = GATHER_RE.search(text)
            if g:
                out.append((t, "gather", g.group(1)))
    return sorted(out)


def sprinkler_state(t: float, events) -> str:
    """'down' when, inside the gather that holds time t, a sprinkler was placed
    (or found standing) at or before t; 'not_yet' when not (yet); 'no_gather'
    when no gather started before t in this run."""
    gather_at = None
    for et, kind, _ in events:
        if et > t + 1.0:           # route frames are written ~1 s after the log line
            break
        if kind == "gather":
            gather_at = et
    if gather_at is None:
        return "no_gather"
    for et, kind, _ in events:
        if gather_at <= et <= t + 1.0 and kind in ("placed", "standing"):
            return "down"
    return "not_yet"


def proposals(img: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Full-res (x, y, w, h) boxes of tan, upright blobs: the Gusher's colour
    gate. High recall, low precision -- the verifier sorts them."""
    sm = cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(sm, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, TAN_LO, TAN_HI)
    m[:HUD_TOP] = 0
    m[HUD_BOTTOM:] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        if not MIN_AREA <= a <= MAX_AREA:
            continue
        if h < MIN_TALL * w or a / float(w * h) < MIN_FILL:
            continue
        s = 1.0 / SCALE
        out.append((int(x * s), int(y * s), int(w * s), int(h * s)))
    return out


def features(img: np.ndarray, box) -> np.ndarray:
    """HOG of the box (20% context, squashed to 32x64) + a hue/sat histogram +
    the box's own shape. 756 + 24 + 3 dims."""
    x, y, w, h = box
    H, W = img.shape[:2]
    px, py = int(w * 0.2), int(h * 0.2)
    x0, y0, x1, y1 = max(0, x - px), max(0, y - py), min(W, x + w + px), min(H, y + h + py)
    crop = img[y0:y1, x0:x1]
    patch = cv2.resize(crop, (PATCH_W, PATCH_H), interpolation=cv2.INTER_AREA)
    hog = HOG.compute(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)).ravel()
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    hh = cv2.calcHist([hsv], [0], None, [16], [0, 180]).ravel()
    sh = cv2.calcHist([hsv], [1], None, [8], [0, 256]).ravel()
    hist = np.concatenate([hh, sh]) / float(PATCH_W * PATCH_H)
    shape = np.array([h / max(1.0, w), np.log1p(w * h) / 12.0, y / float(H)], np.float32)
    return np.concatenate([hog, hist, shape]).astype(np.float32)


class LogReg:
    """L2 logistic regression by full-batch gradient descent on standardised
    features -- enough for ~800 dims and a few 10k rows, no new dependency."""

    def __init__(self, l2: float = 1e-2, steps: int = 400, lr: float = 0.5):
        self.l2, self.steps, self.lr = l2, steps, lr

    def fit(self, X: np.ndarray, y: np.ndarray) -> "LogReg":
        self.mu = X.mean(0)
        self.sd = X.std(0) + 1e-6
        Z = (X - self.mu) / self.sd
        n, d = Z.shape
        # balanced weights: each class carries half the loss
        wpos = 0.5 / max(1, y.sum())
        wneg = 0.5 / max(1, (1 - y).sum())
        sw = np.where(y > 0, wpos, wneg)
        self.w = np.zeros(d, np.float64)
        self.b = 0.0
        for _ in range(self.steps):
            p = 1.0 / (1.0 + np.exp(-(Z @ self.w + self.b)))
            g = sw * (p - y)
            self.w -= self.lr * (Z.T @ g + self.l2 * self.w)
            self.b -= self.lr * g.sum()
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        Z = (X - self.mu) / self.sd
        return 1.0 / (1.0 + np.exp(-(Z @ self.w + self.b)))

    def to_json(self) -> dict:
        return {"mu": self.mu.tolist(), "sd": self.sd.tolist(),
                "w": self.w.tolist(), "b": float(self.b)}


def index_frames(var: Path, limit_runs: int | None = None,
                 gusher_from: int | None = None, walk_every: int = 8) -> list[dict]:
    """Every gathering-pattern route frame with its run, era, field and the
    gather's sprinkler state. Before `gusher_from`, every `walk_every`-th
    other route frame (walks, cannon, step-backs) comes too, kind "walk":
    more certain negatives for the verifier (sand paths, tokens, hives)."""
    rows = []
    runs = sorted(int(p.name[8:]) for p in (var / "routes").glob("attempt-*")
                  if p.name[8:].isdigit())
    if limit_runs:
        runs = runs[-limit_runs:]
    for run in runs:
        logp = var / "night" / f"run-{run}.log"
        if not logp.exists():
            continue
        lines = logp.read_text(errors="replace").splitlines()
        pre = gusher_from is not None and run < gusher_from
        if not pre and not any(PLACED in ln for ln in lines):
            continue
        count = sprinklers_in_run(lines)
        events = log_events(lines, logp.stat().st_mtime)
        for k, f in enumerate(sorted((var / "routes" / f"attempt-{run}").iterdir())):
            m = FRAME_RE.match(f.name)
            if not m and not (pre and k % walk_every == 0 and f.suffix == ".jpg"):
                continue
            t = f.stat().st_mtime
            rows.append({"path": str(f), "run": run, "epoch": round(t, 2),
                         "kind": "pattern" if m else "walk",
                         "field": m.group(2) if m else "-", "step": int(m.group(3)) if m else -1,
                         "sprinklers": count,
                         "state": sprinkler_state(t, events),
                         "split": split_of(run)})
    return rows


def era_of(row: dict, gusher_from_run: int) -> str:
    return "gusher" if row["run"] >= gusher_from_run else "pre_gusher"


def first_gusher_run(var: Path) -> int:
    """The first run whose log stacked GUSHER_TOTAL sprinklers."""
    for logp in sorted((var / "night").glob("run-*.log"),
                       key=lambda p: int(p.stem[4:]) if p.stem[4:].isdigit() else 0):
        if not logp.stem[4:].isdigit():
            continue
        if sprinklers_in_run(logp.read_text(errors="replace").splitlines()) == GUSHER_TOTAL:
            return int(logp.stem[4:])
    raise SystemExit("no Golden Gusher run found in the logs")


def sequences(rows: list[dict]) -> None:
    """Group frames into one gather pass: same run and field, step counter
    restarting at 0, under 60 s between frames."""
    seq_id, last = 0, None
    for r in sorted(rows, key=lambda r: (r["run"], r["epoch"])):
        if (last is None or r["run"] != last["run"] or r["field"] != last["field"]
                or r["step"] <= last["step"] or r["epoch"] - last["epoch"] > 60):
            seq_id += 1
        r["seq"] = seq_id
        last = r



def eye_sheet(items, path: Path, cols: int = 8, tile: int = 160) -> None:
    """Contact sheet: each item (frame path, box) cut with context, numbered."""
    tiles = []
    for i, (fp, box) in enumerate(items):
        img = cv2.imread(fp)
        if box is None:
            c = cv2.resize(img, (tile * 2, tile))
            c = c[:, :tile * 2]
        else:
            x, y, w, h = box
            cx, cy, s = x + w // 2, y + h // 2, max(w, h) * 2 + 40
            x0, y0 = max(0, cx - s // 2), max(0, cy - s // 2)
            c = img[y0:y0 + s, x0:x0 + s].copy()
            cv2.rectangle(c, (x - x0, y - y0), (x - x0 + w, y - y0 + h), (0, 0, 255), 2)
            c = cv2.resize(c, (tile, tile))
        cv2.putText(c, str(i), (3, 20), 0, 0.7, (0, 0, 255), 2)
        tiles.append(c)
    if not tiles:
        return
    blank = np.zeros((tile, tile, 3), np.uint8)
    while len(tiles) % cols:
        tiles.append(blank)
    cv2.imwrite(str(path), np.vstack([np.hstack(tiles[i:i + cols])
                                      for i in range(0, len(tiles), cols)]))


def grade(clf: LogReg, path: Path, threshold: float) -> dict | None:
    """Precision/recall of the verifier on proposals graded BY EYE:
    graded.json = [{"source": frame, "box": [x,y,w,h], "sprinkler": true|false,
    "set": name}, ...]. The sets are kept apart: a set used to pick the
    threshold is not the one the result is quoted from."""
    if not path.exists():
        return None
    by_set: dict[str, list] = {}
    for g in json.loads(path.read_text(encoding="utf-8")):
        img = cv2.imread(g["source"])
        if img is None:
            continue
        s = float(clf.score(features(img, tuple(g["box"]))[None])[0])
        by_set.setdefault(g.get("set", "eye"), []).append((s, bool(g["sprinkler"])))
    out = {}
    for name, pairs in by_set.items():
        res = {"n": len(pairs), "true_sprinklers": sum(t for _, t in pairs)}
        for thr in sorted({0.5, 0.7, 0.8, 0.9, 0.95, threshold}):
            tp = sum(1 for s, t in pairs if s >= thr and t)
            fp = sum(1 for s, t in pairs if s >= thr and not t)
            fn = sum(1 for s, t in pairs if s < thr and t)
            p = tp / (tp + fp) if tp + fp else 0.0
            r = tp / (tp + fn) if tp + fn else 0.0
            res[f"{thr:.2f}"] = {"P": round(p, 3), "R": round(r, 3),
                                 "F1": round(2 * p * r / (p + r), 3) if p + r else 0.0}
        out[name] = res
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--var", type=Path, default=VAR)
    ap.add_argument("--out", type=Path,
                    default=Path(os.environ.get("HIVEMIND_WORK") or Path.home() / ".cache/hivemind-dev") / "datasets/sprinkler")
    ap.add_argument("--limit-runs", type=int, default=None, help="newest N runs only (smoke)")
    ap.add_argument("--threshold", type=float, default=0.9,
                    help="verifier score for a box to become a label")
    ap.add_argument("--rounds", type=int, default=2, help="self-training rounds")
    ap.add_argument("--low", type=float, default=0.3,
                    help="a bag proposal under this score becomes a negative in self-training")
    ap.add_argument("--copy-scale", type=float, default=0.5,
                    help="frames are copied at this scale (boxes are in full-res px)")
    ap.add_argument("--neg-per-run", type=int, default=6,
                    help="pre-Gusher frames copied per run as certain negatives")
    a = ap.parse_args(argv)
    out = a.out
    (out / "frames").mkdir(parents=True, exist_ok=True)
    (out / "eyecheck").mkdir(exist_ok=True)
    t0 = time.time()

    gusher_from = first_gusher_run(a.var)
    rows = index_frames(a.var, a.limit_runs, gusher_from)
    sequences(rows)
    for r in rows:
        r["era"] = era_of(r, gusher_from)
    print(f"indexed {len(rows)} pattern frames; Golden Gushers from run {gusher_from} "
          f"({time.time() - t0:.0f}s)", flush=True)

    # ---- proposals + features (cached) --------------------------------------
    cache = out / "proposals.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=False)
        P_row, P_box, X = z["row"], z["box"], z["X"]
    else:
        prow, pbox, feats = [], [], []
        for i, r in enumerate(rows):
            img = cv2.imread(r["path"])
            if img is None:
                continue
            for b in proposals(img):
                prow.append(i)
                pbox.append(b)
                feats.append(features(img, b))
            if i % 1000 == 0:
                print(f"  proposals {i}/{len(rows)}: {len(prow)} ({time.time() - t0:.0f}s)", flush=True)
        P_row = np.array(prow, np.int32)
        P_box = np.array(pbox, np.int32).reshape(-1, 4)
        X = np.array(feats, np.float32).reshape(len(prow), -1)
        np.savez_compressed(cache, row=P_row, box=P_box, X=X)
    print(f"{len(P_row)} proposals ({time.time() - t0:.0f}s)", flush=True)

    # ---- weak targets ------------------------------------------------------
    era = np.array([rows[i]["era"] == "gusher" for i in P_row])
    down = np.array([rows[i]["state"] == "down" for i in P_row])
    split = np.array([rows[i]["split"] for i in P_row])
    pos = era & down                         # bag: some of these are Gushers
    neg = ~era                               # certain: no Gusher existed
    use = pos | neg
    tr = use & (split == "train")
    clf = LogReg().fit(X[tr], pos[tr].astype(np.float64))
    S = clf.score(X)
    # SELF-TRAINING: the bag's low scorers are mostly its distractors (glints,
    # tokens, the new bees), so they join the negatives; only the bag's high
    # scorers stay positive. Train runs only, as before.
    for _ in range(a.rounds):
        p2 = tr & pos & (S >= a.threshold)
        n2 = tr & (neg | (pos & (S < a.low)))
        clf = LogReg().fit(X[p2 | n2], p2[p2 | n2].astype(np.float64))
        S = clf.score(X)
    va = use & (split == "val")
    # proxy only: how well the score separates the eras on val runs (an upper
    # bound is NOT precision -- most positive-bag proposals are not Gushers)
    neg_va = S[va & neg]
    print(f"val: pre-Gusher proposals over threshold {a.threshold}: "
          f"{(neg_va >= a.threshold).mean():.4f} of {len(neg_va)}; "
          f"Gusher-era bag proposals over it: {(S[va & pos] >= a.threshold).mean():.3f} "
          f"of {(va & pos).sum()}", flush=True)
    (out / "verifier.json").write_text(json.dumps(
        {"threshold": a.threshold, "gusher_from_run": gusher_from,
         "tan_lo": TAN_LO, "tan_hi": TAN_HI, "patch": [PATCH_W, PATCH_H],
         "model": clf.to_json()}))

    # ---- labels -------------------------------------------------------------
    boxes_of: dict[int, list] = {}
    for k in np.nonzero(pos & (S >= a.threshold))[0]:
        boxes_of.setdefault(int(P_row[k]), []).append(
            {"box": [int(v) for v in P_box[k]], "score": round(float(S[k]), 4)})
    seq_hits: dict[int, int] = {}
    for i in boxes_of:
        seq_hits[rows[i]["seq"]] = seq_hits.get(rows[i]["seq"], 0) + 1

    manifest = []
    rng = np.random.default_rng(0)
    neg_by_run: dict[int, list[int]] = {}
    for i, r in enumerate(rows):
        if r["era"] == "pre_gusher" and r["kind"] == "pattern":
            neg_by_run.setdefault(r["run"], []).append(i)
    keep_neg = set()
    for run, idx in neg_by_run.items():
        keep_neg.update(rng.choice(idx, size=min(a.neg_per_run, len(idx)), replace=False).tolist())

    for i, r in enumerate(rows):
        if r["era"] == "gusher" and r["state"] == "down":
            label = "sprinkler" if i in boxes_of else "unlabelled"
        elif i in keep_neg:
            label = "absent_certain"
        else:
            continue
        name = f"run{r['run']}-{Path(r['path']).name}"
        dst = out / "frames" / r["split"] / name
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            img = cv2.imread(r["path"])
            small = cv2.resize(img, None, fx=a.copy_scale, fy=a.copy_scale,
                               interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(dst), small, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        manifest.append({
            "image": str(dst.relative_to(out)), "source": r["path"],
            "split": r["split"], "run": r["run"], "seq": r["seq"],
            "field": r["field"], "step": r["step"], "epoch": r["epoch"],
            "sprinkler_type": "golden_gushers" if r["era"] == "gusher" else "older",
            "state": r["state"], "label": label,
            "boxes": boxes_of.get(i, []),     # full-res px; image is copy_scale of that
            "seq_confirmed": seq_hits.get(r["seq"], 0) >= 2,
            "image_scale": a.copy_scale})
    with (out / "manifest.jsonl").open("w") as f:
        for m in manifest:
            f.write(json.dumps(m) + "\n")

    # ---- eye-check sheets (test split only) ---------------------------------
    test_lab = [m for m in manifest if m["split"] == "test" and m["label"] == "sprinkler"]
    pick = rng.choice(len(test_lab), size=min(48, len(test_lab)), replace=False) if test_lab else []
    items = []
    for j in pick:
        m = test_lab[int(j)]
        b = max(m["boxes"], key=lambda b: b["score"])
        items.append((m["source"], tuple(b["box"])))
    eye_sheet(items, out / "eyecheck" / "test_labels.jpg")
    # recall side: every test-split Gusher-era proposal, scored, a random 48
    tp = np.nonzero(pos & (split == "test"))[0]
    pick2 = rng.choice(tp, size=min(48, len(tp)), replace=False) if len(tp) else []
    eye_sheet([(rows[int(P_row[k])]["path"], tuple(int(v) for v in P_box[k])) for k in pick2],
              out / "eyecheck" / "test_proposals.jpg")
    (out / "eyecheck" / "index.json").write_text(json.dumps({
        "test_labels": [[fp, list(b)] for fp, b in items],
        "test_proposals": [[rows[int(P_row[k])]["path"], [int(v) for v in P_box[k]],
                            round(float(S[k]), 4)] for k in pick2]}, indent=1))

    graded = grade(clf, out / "eyecheck" / "graded.json", a.threshold)
    summary = {
        "built": time.strftime("%Y-%m-%d %H:%M"), "gusher_from_run": gusher_from,
        "pattern_frames": sum(1 for r in rows if r["kind"] == "pattern"),
        "walk_negative_frames": sum(1 for r in rows if r["kind"] == "walk"),
        "proposals": int(len(P_row)),
        "threshold": a.threshold,
        "by_split": {s: {lab: sum(1 for m in manifest if m["split"] == s and m["label"] == lab)
                         for lab in ("sprinkler", "unlabelled", "absent_certain")}
                     for s, _ in SPLITS},
        "boxes": sum(len(m["boxes"]) for m in manifest),
        "seq_confirmed_frames": sum(1 for m in manifest if m["label"] == "sprinkler" and m["seq_confirmed"]),
        "eye_graded": graded,
        "seconds": round(time.time() - t0)}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
