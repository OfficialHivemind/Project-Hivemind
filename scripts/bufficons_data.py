#!/usr/bin/env python3
"""Build the buff-icon dataset (vision/bufficons) from the bot's OWN frames.

    extract   every frame of every Nth route attempt -> the buff bar's band
              (rows 58..96, the first 12 icon slots, 456 px) in a memmap,
              plus a meta row per frame (attempt, file, mtime, night)
    cluster   k-means over the slot crops, and a contact sheet per cluster so
              each cluster can be named once by eye (NAMES.json, by hand)
    label     per slot: the class (template reader at high score first, else
              the named cluster when the crop sits near its centre), and the
              drain line, fitted along each icon's track over consecutive
              frames (the line only ever falls)

Nothing here reads another macro's data; the templates are ours
(data/templates/buffs, scripts/build_buff_templates.py). ~/Hivemind is only
read. Run niced under the memory cap:

    PYTHONPATH=src nice -n 19 capped --mem 3000M python scripts/bufficons_data.py extract --every 3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hivemind.vision import bufficons, buffs                        # noqa: E402

ROUTES = Path.home() / "Hivemind/var/routes"
OUT = Path(os.environ.get("HIVEMIND_WORK") or Path.home() / ".cache/hivemind-dev") / "datasets/bufficons"
ICON, SLOTS = buffs.ICON, buffs.MAX_SLOTS
WIDTH = ICON * SLOTS
# A "night" is the bot's day: it starts NIGHT_SHIFT_S after midnight and runs
# 24 h, so one overnight run is one group (the held-out split is by night).
NIGHT_SHIFT_S = 8 * 3600


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def night_of(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t - NIGHT_SHIFT_S))


def _band(path: str):
    cv2.setNumThreads(1)
    f = cv2.imread(path)
    if f is None or f.shape[:2] != (1080, 1920):
        return None
    return np.ascontiguousarray(f[buffs.BAR_TOP:buffs.BAR_BOTTOM, :WIDTH])


def extract(every: int, workers: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    atts = sorted((p for p in ROUTES.glob("attempt-*") if p.name[8:].isdigit()),
                  key=lambda p: int(p.name[8:]))
    files = []
    for a in atts[::every]:
        files += sorted(str(p) for p in a.glob("*.jpg"))
    log(f"{len(files)} frames from {len(atts[::every])} attempts")
    bands = np.lib.format.open_memmap(OUT / "bands.npy", "w+", np.uint8,
                                      (len(files), ICON, WIDTH, 3))
    meta, n = [], 0
    with Pool(workers) as pool:
        for path, band in zip(files, pool.imap(_band, files, chunksize=16)):
            if band is None:
                continue
            p = Path(path)
            t = p.stat().st_mtime
            bands[n] = band
            meta.append({"i": n, "attempt": int(p.parent.name[8:]), "file": p.name,
                         "t": round(t, 2), "night": night_of(t)})
            n += 1
            if n % 5000 == 0:
                log(f"  {n}")
    bands.flush()
    del bands
    with open(OUT / "meta.jsonl", "w") as fh:
        for m in meta:
            fh.write(json.dumps(m) + "\n")
    (OUT / "count.txt").write_text(str(n))
    log(f"kept {n} frames")


def load():
    n = int((OUT / "count.txt").read_text())
    bands = np.load(OUT / "bands.npy", mmap_mode="r")[:n]
    meta = [json.loads(line) for line in open(OUT / "meta.jsonl")]
    return bands, meta


def slot_crop(bands, i, s):
    return bands[i, :, s * ICON:(s + 1) * ICON]


def feature(crop: np.ndarray) -> np.ndarray:
    """What k-means groups on: the icon at 12x12 in HSV-ish colour, plus a
    flatness term so empty scenery slots fall together."""
    small = cv2.resize(crop, (12, 12), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    return small.ravel()


def sqdist(X, C):
    """Squared distances N x K without the N x K x D temporary."""
    return np.maximum((X * X).sum(1)[:, None] - 2 * X @ C.T + (C * C).sum(1)[None], 0)


def cluster(k: int, sample: int, seed: int = 0, tag: str = "") -> None:
    """k-means over `sample` frames' slots -- or, with `tag` "2", over a sample
    of the slots the first pass left unnamed (slots.jsonl rows without `y`)
    -- and the sheets to name the clusters by eye (NAMES<tag>.json)."""
    bands, meta = load()
    rng = np.random.default_rng(seed)
    if tag:
        left = [(r["i"], r["slot"]) for r in map(json.loads, open(OUT / "slots.jsonl"))
                if not r.get("y")]
        pairs = [left[j] for j in rng.choice(len(left), min(sample * SLOTS, len(left)), replace=False)]
    else:
        pairs = [(int(i), int(s)) for i in rng.choice(len(meta), min(sample, len(meta)),
                                                      replace=False) for s in range(SLOTS)]
    X = np.stack([feature(slot_crop(bands, i, s)) for i, s in pairs])
    log(f"k-means k={k} on {len(X)} slot crops")
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 60, 1e-3)
    cv2.setRNGSeed(seed)
    _, lab, centres = cv2.kmeans(X, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    lab = lab.ravel()
    dist = np.sqrt(sqdist(X, centres)[np.arange(len(X)), lab])
    radius = np.array([np.percentile(dist[lab == c], 90) if (lab == c).any() else 0.0
                       for c in range(k)], np.float32)
    np.save(OUT / f"centres{tag}.npy", centres)
    np.save(OUT / f"radius{tag}.npy", radius)
    sheets = OUT / f"clusters{tag}"
    sheets.mkdir(exist_ok=True)
    sizes = np.bincount(lab, minlength=k)
    for c in range(k):
        idx = np.flatnonzero(lab == c)
        pick = rng.choice(idx, min(24, len(idx)), replace=False)
        tiles = [cv2.resize(np.ascontiguousarray(slot_crop(bands, *pairs[j])), (76, 76),
                            interpolation=cv2.INTER_NEAREST) for j in pick]
        tiles += [np.zeros((76, 76, 3), np.uint8)] * (24 - len(tiles))
        sheet = np.vstack([np.hstack(tiles[r * 12:(r + 1) * 12]) for r in range(2)])
        cv2.imwrite(str(sheets / f"c{c:03d}_n{sizes[c]}.png"), sheet)
    # one overview: 4 crops a cluster, 10 clusters a row, labelled
    rows = []
    for start in range(0, k, 10):
        row = []
        for c in range(start, min(k, start + 10)):
            idx = np.flatnonzero(lab == c)[:4]
            t = [cv2.resize(np.ascontiguousarray(slot_crop(bands, *pairs[j])), (48, 48),
                            interpolation=cv2.INTER_NEAREST) for j in idx]
            t += [np.zeros((48, 48, 3), np.uint8)] * (4 - len(t))
            cell = np.vstack([np.hstack(t[:2]), np.hstack(t[2:])])
            cell = cv2.copyMakeBorder(cell, 14, 2, 2, 2, cv2.BORDER_CONSTANT, value=(255, 255, 255))
            cv2.putText(cell, f"{c}", (2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
            row.append(cell)
        row += [np.full_like(row[0], 255)] * (10 - len(row))
        rows.append(np.hstack(row))
    for s in range(0, len(rows), 5):
        cv2.imwrite(str(OUT / f"overview{tag}_{s // 5}.png"), np.vstack(rows[s:s + 5]))
    log(f"sizes: {sorted(sizes.tolist(), reverse=True)[:20]} ...")


# ---- labelling ---------------------------------------------------------------------
# Template reader thresholds: the reader's own acceptance lines, and a margin
# above them for a LABEL (buffs.py measured 96/96 Haste at 0.9+, bears 0.88+).
HASTE_LABEL = 0.90
BEAR_LABEL = 0.88
# NOT THE MELODY TEMPLATE. MEASURED 2026-10-27 by eye on test nights: of 34
# slots buffs.find(..., "melody") accepts (0.75+), 2 are Melody -- the rest
# are flat sky or wall, which the top-rows correlation cannot tell from a
# white square; at 0.85 its labels still broke Melody's drain clock (33
# tracks scattered over 0.19-0.79 rows/s against 134 at 1.23-1.29 without).
# Melody is named by its clusters alone.
# A crop takes its cluster's name only this close to the centre, as a share of
# that cluster's own 90th-percentile distance (looser crops are left out).
CLUSTER_RADIUS = 1.0


def frame_of(band):
    f = np.zeros((buffs.BAR_BOTTOM, WIDTH, 3), np.uint8)
    f[buffs.BAR_TOP:] = band
    return f


def template_labels(band) -> dict[int, tuple[str, float]]:
    """slot -> (class, score) where our template reader is sure."""
    f = frame_of(band)
    out = {}
    for h in buffs.find_all(f, "haste"):
        if h.score >= HASTE_LABEL:
            out[h.slot] = ("haste", h.score)
    b = buffs.bear(f)
    if b.present and b.score >= BEAR_LABEL:
        # only when aligned to a slot (not mid-slide)
        strip = band[buffs.BEAR_ROWS[0]:buffs.BEAR_ROWS[1]]
        tpl = buffs._template(f"bear_{b.kind}", colour=True)
        r0, r1 = buffs.BEAR_ROWS
        c0, c1 = buffs.BEAR_COLS
        res = cv2.matchTemplate(np.ascontiguousarray(strip),
                                np.ascontiguousarray(tpl[r0:r1, c0:c1]), cv2.TM_CCOEFF_NORMED)[0]
        x = int(np.argmax(res)) - c0
        if x % ICON in (0, 1, ICON - 1):
            out[int(round(x / ICON))] = (f"bear_{b.kind}", b.score)
    return out


def passes():
    """The named cluster sets, first pass first: (centres, radius, names)."""
    out = []
    for tag in ("", "2"):
        if (OUT / f"centres{tag}.npy").exists() and (OUT / f"NAMES{tag}.json").exists():
            names = {int(k): v for k, v in json.loads((OUT / f"NAMES{tag}.json").read_text()).items()}
            out.append((np.load(OUT / f"centres{tag}.npy"), np.load(OUT / f"radius{tag}.npy"), names))
    return out


def label() -> None:
    bands, meta = load()
    sets = passes()
    rows = []
    t0 = time.time()
    for m in meta:
        band = np.asarray(bands[m["i"]])
        tl = template_labels(band)
        X = np.stack([feature(slot_crop(bands, m["i"], s)) for s in range(SLOTS)])
        dds = [sqdist(X, centres) for centres, _, _ in sets]
        for s in range(SLOTS):
            row = {"i": m["i"], "slot": s}
            if s in tl:
                row["tname"], row["tscore"] = tl[s][0], round(tl[s][1], 3)
            # the class: template when sure; else the first pass whose named cluster
            # has the crop within its radius
            for n, ((_, radius, names), dd) in enumerate(zip(sets, dds)):
                c = int(dd[s].argmin())
                dist = float(np.sqrt(dd[s, c]))
                cname = names.get(c, "?")
                ok = dist <= CLUSTER_RADIUS * radius[c]
                if n == 0:
                    row.update(cluster=c, cname=cname, cdist=round(dist, 3), cok=bool(ok))
                if ok and cname not in ("?", "mixed"):
                    row["cname"], row["pass"] = cname, n + 1
                    break
            if "tname" in row:
                row["y"] = row["tname"]
            elif row.get("pass"):
                row["y"] = row["cname"]
            rows.append(row)
        if m["i"] % 5000 == 0:
            log(f"  labelled {m['i']} frames ({time.time() - t0:.0f}s)")
    with open(OUT / "slots.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    from collections import Counter
    log("classes: " + json.dumps(Counter(r.get("y", "-") for r in rows).most_common()))


# ---- the drain clock ---------------------------------------------------------------
# EVERY ICON DRAINS LIKE HASTE'S (vision/buffs DRAIN_*): its coloured square
# empties from the top and the world shows through. So each class's FILL is its
# square's colour (the median of the icon's bottom-left corner, clear of the
# count), its MASK the pixels of a full icon that show that colour, and a
# crop's drain line the highest row from which every masked row below still
# shows the fill on FILL_ROW_SHARE of its pixels. Bears draw their face over all
# of the square and darken instead: their line is buffs.bear_drain_line.
# Where the square's own colour is looked for: the patch whose colour varies
# least across the class's crops wins (Baby Love's heart covers the bottom-left
# corner, Melody's notes the middle, a long count the bottom right).
FILL_PATCHES = ((slice(31, 36), slice(2, 8)), (slice(26, 36), slice(1, 3)),
                (slice(16, 22), slice(1, 4)), (slice(30, 36), slice(30, 36)))
TOP_PATCHES = ((slice(2, 6), slice(2, 8)), (slice(2, 6), slice(30, 36)))
FILL_TOL = bufficons.FILL_TOL
MASK_MIN_ROWS = 12       # a class whose mask covers fewer rows has no readable clock
# Tracks: frames of one attempt with the class up, at most TRACK_GAP_S apart;
# a line that rises by REFILL_ROWS or more is the buff refilled (a new track).
TRACK_GAP_S = 8.0
REFILL_ROWS = 3
TRACK_MIN = 3            # frames
TRACK_MIN_SPAN_S = 3.0
TRACK_MAX_RESID = 1.5    # rows, median absolute residual of the straight fit


def fill_masks(bands, rows, classes):
    """class -> (fill BGR, mask 38x38 bool) for classes with a square to read."""
    out = {}
    by = {}
    for r in rows:
        if r.get("y") in classes:
            by.setdefault(r["y"], []).append(r)
    rng = np.random.default_rng(2)
    for c, rs in by.items():
        pick = [rs[j] for j in rng.choice(len(rs), min(400, len(rs)), replace=False)]
        crops = np.stack([np.asarray(slot_crop(bands, r["i"], r["slot"])) for r in pick]).astype(np.float32)
        # each patch's median colour is a candidate; the fill is the one that covers
        # most of the icons' lower half (Melody's note heads are grey in a white
        # square: both patches are steady, the white covers far more)
        lower = crops[:, ICON // 2:]
        best = None
        for pr, pc in FILL_PATCHES:
            f = np.median(crops[:, pr, pc].reshape(len(crops), -1, 3).mean(1), axis=0)
            cover = float((np.linalg.norm(lower - f, axis=-1) < FILL_TOL).mean())
            if best is None or cover > best[0]:
                best = (cover, f)
        fill = best[1]
        tops = [np.linalg.norm(crops[:, pr, pc].reshape(len(crops), -1, 3).mean(1) - fill, axis=1)
                for pr, pc in TOP_PATCHES]
        full = crops[np.minimum(*tops) < FILL_TOL]
        if len(full) < 10:
            # never seen full here (Baby Love's heart reaches both top corners):
            # the tenth of the crops showing the most fill stand in for full
            fillish = (np.linalg.norm(crops - fill, axis=-1) < FILL_TOL).sum((1, 2))
            full = crops[np.argsort(-fillish)[:max(10, len(crops) // 10)]]
        near = np.linalg.norm(full - fill, axis=-1) < FILL_TOL     # N,38,38
        mask = near.mean(0) > 0.8
        rr, cc = np.mgrid[:ICON, :ICON]
        mask &= ~((rr >= buffs.DRAIN_TEXT_BOX[0]) & (cc >= buffs.TEXT_LEFT))
        mask[ICON - 1, :] = False
        mask[:, 0] = False
        if mask.any(1).sum() >= MASK_MIN_ROWS:
            out[c] = (fill, mask)
    return out


def drain_line(crop, fill, mask) -> int:
    return bufficons.fill_line(crop, fill, mask)


def isotonic(y):
    """Non-decreasing least-squares fit (pool adjacent violators)."""
    blocks = [[float(v), 1] for v in y]
    out = []
    for b in blocks:
        out.append(b)
        while len(out) > 1 and out[-2][0] / out[-2][1] > out[-1][0] / out[-1][1]:
            s, n = out.pop()
            out[-1][0] += s
            out[-1][1] += n
    res = []
    for s, n in out:
        res += [s / n] * n
    return res


# A class's rate is TRUSTED (its seconds are reported) on RATE_MIN_TRACKS
# tracks whose rates agree: interquartile range within RATE_MAX_IQR of the
# median. MEASURED on this set: Haste's 1,420 tracks give 1.89 rows/s
# (IQR 1.855-1.915), the hand clock's 1.895 (vision/buffs DRAIN_ROWS_PER_S);
# a class whose line is noisy spreads 3x and more.
RATE_MIN_TRACKS = 10
RATE_MAX_IQR = 0.3


def trusted(v) -> bool:
    med = float(np.median(v))
    q1, q3 = np.percentile(v, [25, 75])
    return bool(len(v) >= RATE_MIN_TRACKS and med > 0 and (q3 - q1) / med <= RATE_MAX_IQR)


def drain(rows_path: Path = OUT / "slots.jsonl") -> None:
    """Add `line` (raw drain line) to every labelled slot with a readable clock,
    and `dline` (the track's monotone fit) where the slot sits on a clean track;
    write per-class rates (rows a second) to rates.json."""
    bands, meta = load()
    rows = [json.loads(x) for x in open(rows_path)]
    for r in rows:                      # a rerun starts clean: no stale lines or tracks
        for k in ("line", "dline", "track"):
            r.pop(k, None)
    classes = sorted({r["y"] for r in rows if r.get("y") and r["y"] != "background"
                      and not r["y"].startswith("bear_")})
    masks = fill_masks(bands, rows, classes)
    log("classes with a fill clock: " + ", ".join(sorted(masks)))
    np.savez_compressed(OUT / "fills.npz", names=np.array(sorted(masks)),
                        fills=np.array([masks[c][0] for c in sorted(masks)], np.float32),
                        masks=np.array([masks[c][1] for c in sorted(masks)], bool))
    for r in rows:
        y = r.get("y")
        if y in masks:
            r["line"] = drain_line(np.asarray(slot_crop(bands, r["i"], r["slot"])), *masks[y])
        elif y and y.startswith("bear_"):
            ln = buffs.bear_drain_line(np.ascontiguousarray(slot_crop(bands, r["i"], r["slot"])),
                                       y[5:])
            if ln is not None:
                r["line"] = ln
    # tracks per (attempt, class): one instance a class (the deepest line when two)
    by = {}
    for r in rows:
        if "line" in r:
            m = meta[r["i"]]
            k = (m["attempt"], r["y"])
            by.setdefault(k, {}).setdefault(r["i"], []).append(r)
    rates, kept = {}, 0
    for (att, y), frames in by.items():
        order = sorted(frames, key=lambda i: meta[i]["t"])
        track = []

        def close(track):
            nonlocal kept
            if len(track) < TRACK_MIN:
                return
            ts = np.array([meta[i]["t"] for i, _ in track])
            ls = np.array([r["line"] for _, r in track], float)
            if ts[-1] - ts[0] < TRACK_MIN_SPAN_S or ls[-1] - ls[0] < 2:
                return
            if (ls >= ICON).all():
                return
            a, b = np.polyfit(ts - ts[0], ls, 1)
            resid = np.median(np.abs(ls - (a * (ts - ts[0]) + b)))
            if resid > TRACK_MAX_RESID or a <= 0:
                return
            rates.setdefault(y, []).append(float(a))
            fit = isotonic(ls)
            for (i, r), v in zip(track, fit):
                r["dline"] = round(v, 2)
                r["track"] = f"{att}:{y}:{track[0][0]}"
                kept += 1

        for i in order:
            r = max(frames[i], key=lambda q: q["line"])
            if track:
                pi, pr = track[-1]
                if meta[i]["t"] - meta[pi]["t"] > TRACK_GAP_S or r["line"] <= pr["line"] - REFILL_ROWS:
                    close(track)
                    track = []
            track.append((i, r))
        close(track)
    summary = {y: {"tracks": len(v), "rows_per_s": round(float(np.median(v)), 3),
                   "iqr": [round(float(np.percentile(v, 25)), 3), round(float(np.percentile(v, 75)), 3)],
                   "full_s": round(ICON / float(np.median(v)), 1),
                   "trusted": trusted(v)}
               for y, v in rates.items()}
    (OUT / "rates.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    log(f"{kept} slots on clean tracks; rates: {json.dumps(summary)}")
    with open(rows_path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--every", type=int, default=3)
    e.add_argument("--workers", type=int, default=2)
    c = sub.add_parser("cluster")
    c.add_argument("--k", type=int, default=120)
    c.add_argument("--sample", type=int, default=6000)
    c.add_argument("--second", action="store_true", help="cluster the slots still unnamed")
    sub.add_parser("label")
    sub.add_parser("drain")
    a = ap.parse_args()
    if a.cmd == "extract":
        extract(a.every, a.workers)
    elif a.cmd == "cluster":
        cluster(a.k, a.sample, tag="2" if a.second else "")
    elif a.cmd == "drain":
        drain()
    else:
        label()
        drain()
    return 0


if __name__ == "__main__":
    sys.exit(main())
