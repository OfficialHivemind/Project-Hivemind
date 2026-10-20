#!/usr/bin/env python3
"""Build vision/fieldsense's gallery from the bot's own saved frames, labelled
by the game's reward feed, and measure it on nights it has never seen.

    nice -n 19 .venv/bin/python scripts/train_fieldsense.py            # var/ here
    nice -n 19 .venv/bin/python scripts/train_fieldsense.py --var /home/<user>/Hivemind/var

READ-ONLY on the var directory. Writes data/models/fieldsense.npz (the seed
gallery: 648 bytes a frame; the live shards stay in var/fieldsense, which the
bot loads itself) and data/models/fieldsense.json (what it was built from,
every held-out number, the trust table `Look.sure` reads, and the rules the
bot may use and on what: `arrival.early_rule.aims`, `arrival.sight.
destinations`, `edge.threshold` and `edge.back_at`).

WHERE THE LABELS COME FROM, and nothing else labels a frame (research vpr
timeline.py and label.py, DESIGN 8dz):

  * var/night/attempts.log gives each run-NNN.log its start time; the run log's
    "I am in the X field (N% sure, feed, Ks ago)" lines are the game's own
    reward-feed fixes at T-K, and "I am on our own hive pad (98% sure, panel,
    0s ago)" / "at the red cannon ..." are panel fixes at T;
  * var/incidents/*/NNN_t+X.Xs.jpg ring-buffer dumps (the last frame's mtime,
    corrected by the folder's HHMMSS when a dump was written late), var/routes/
    attempt-N/ per-step snaps and var/homing/ frames, timed by mtime;
  * FIELD F: between two consecutive feed fixes that both name F no more than
    40 s apart, or within 2 s of a fix of F, and no panel fix within 20 s;
    HIVE / LANDMARK: within [-0.5, +1.5] s of a panel fix naming it;
  * live runs add var/fieldsense/live-*.npz, labelled by the same rule live
    (vision/fieldsense.Labeller); they join the gallery and the hold-outs, and
    their visits count towards MIN_VISITS, so a place learned live is measured.

HOW IT IS MEASURED. A night is one overnight session (the start time minus
12 h, as a date). Every number is leave-one-NIGHT-out: the held-out night's
frames are scored by SVMs trained only on the other nights, because the
research found leave-one-attempt-out optimistic (93.8% falling to 71.9% as
neighbouring attempts are excluded, placerec q1_strict). The trust table is
built from those held-out predictions, so a look's `sure` is how often a look
like it was right on an unseen night.
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.dont_write_bytecode = True

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from hivemind.vision import fieldsense as fs  # noqa: E402
from hivemind.world.bearings import SURE_ELSEWHERE  # noqa: E402

cv2.setNumThreads(1)

START = re.compile(r"attempt (\d+) starting (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) -> (\S+)")
EXITED = re.compile(r"attempt (\d+) exited (-?\d+) after (\d+)s")
STAMP = re.compile(r"^\s+(\d\d):(\d\d):(\d\d)\s\s(.*)$")
FEED = re.compile(r"I am in the ([a-z ]+?) field \((\d+)% sure, feed, (\d+)s ago\)")
PANEL = re.compile(r"I am (on our own hive pad|on a free hive pad|at the ([a-z ]+?)) "
                   r"\((\d+)% sure, panel, (\d+)s ago\)")
ROUTE_FRAME = re.compile(r"^(\d{6})-(.+?)-(\d{2})(?:\.(\d{2}))?-(.+)\.jpg$")
INCIDENT_FRAME = re.compile(r"^(\d{3})_t\+(\d+\.\d)s\.jpg$")

# The research's sampler (vpr/sample.py): per class at most 700 frames, per
# class and attempt between 6 and 45, 2.5 s apart. Kept in fieldsense.
PER_CLASS, PER_ATTEMPT, MIN_PER_ATTEMPT = fs.PER_CLASS, fs.PER_ATTEMPT, 6
# A place is taught only with fieldsense.MIN_VISITS visits behind it.
MIN_VISITS = fs.MIN_VISITS
# The arrival truth: the majority of the first 5 feed fixes within 120 s of
# the walk's last step (research vpr/arrival.py). 9 of 112 walks were
# mislabelled by the first fix alone -- a 1-2 s Spider pill at the Strawberry
# border.
ARRIVAL_FIXES, ARRIVAL_WINDOW = 5, 120.0
# What one pattern pass takes, for "what the first pass's feed said": 24.97 s
# between "token brain:" blocks on strawberry and spider (DESIGN 8dg).
ONE_PASS_SECONDS = 25.0

FIELD_OF_ROUTE = {"rose_field": "rose"}


def slug(name: str) -> str:
    return name.strip().replace(" ", "_")


def night_of(t0: float) -> str:
    return fs.night_of(t0)


# ---- the run logs ------------------------------------------------------------
def run_windows(var: Path) -> dict[int, tuple[float, float]]:
    """{run: (start, end)} from attempts.log, the LAST start line per run."""
    runs: dict[int, list] = {}
    last = None
    log = var / "night" / "attempts.log"
    with open(log, errors="replace") as fh:
        for line in fh:
            m = START.search(line)
            if m:
                n, path = int(m.group(1)), m.group(3)
                if not path.startswith(str(var / "night" / "run-")):
                    last = None
                    continue
                t0 = time.mktime(time.strptime(m.group(2), "%Y-%m-%d %H:%M:%S"))
                runs[n] = [t0, None]
                last = n
                continue
            m = EXITED.search(line)
            if m and last is not None and int(m.group(1)) == last:
                runs[last][1] = runs[last][0] + int(m.group(3))
    out = {}
    for n, (t0, t1) in runs.items():
        path = var / "night" / f"run-{n:03d}.log"
        if not path.exists():
            continue
        mtime = path.stat().st_mtime
        t1 = mtime if t1 is None else t1
        if not (t0 - 60 <= mtime <= t1 + 3600):
            continue            # the file on disk is not the one this line wrote
        out[n] = (t0, t1)
    return out


def parse_run(var: Path, n: int, t0: float) -> dict:
    """The feed and panel fixes of run-NNN.log, as absolute times."""
    lt = time.localtime(t0)
    day0 = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    prev, offset = None, 0.0
    feed, panel = [], []
    with open(var / "night" / f"run-{n:03d}.log", errors="replace") as fh:
        for line in fh:
            m = STAMP.match(line)
            if not m:
                continue
            sod = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            text = m.group(4)
            if prev is None:
                if day0 + sod < t0 - 3600:
                    offset = 86400.0
            elif sod + 43200 < prev:
                offset += 86400.0
            prev = sod
            at = day0 + offset + sod
            for fm in FEED.finditer(text):
                feed.append((at - int(fm.group(3)), slug(fm.group(1))))
            pm = PANEL.search(text)
            if pm and int(pm.group(4)) == 0:
                what = pm.group(1)
                place = ("hive" if what.startswith("on ") else slug(pm.group(2)))
                panel.append((at, place))
    feed.sort()
    dedup = []
    for at, place in feed:            # one fix restated with a growing age
        if dedup and dedup[-1][1] == place and abs(at - dedup[-1][0]) <= 1.5:
            continue
        dedup.append((at, place))
    return {"feed": dedup, "panel": sorted(set(panel))}


# ---- the frames ------------------------------------------------------------------
def incident_frames(var: Path):
    """(path, t) of every ring-buffer frame. The dump's mtime is its LAST
    frame's; a dump written late is corrected by the folder's HHMMSS."""
    for d in sorted((var / "incidents").glob("*")):
        try:
            names = sorted(p for p in os.listdir(d) if INCIDENT_FRAME.match(p))
        except OSError:
            continue
        if not names:
            continue
        last = names[-1]
        t_last = os.path.getmtime(d / last)
        hms = [p for p in d.name.split("-") if len(p) == 6 and p.isdigit()]
        if hms:
            h = hms[0]
            lt = time.localtime(t_last)
            named = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(h[:2]),
                                 int(h[2:4]), int(h[4:]), 0, 0, -1))
            if named > t_last + 43200:
                named -= 86400
            if abs(named - t_last) > 1.5:
                t_last = named + 0.5
        off_last = float(INCIDENT_FRAME.match(last).group(2))
        for p in names:
            off = float(INCIDENT_FRAME.match(p).group(2))
            yield str(d / p), t_last - (off_last - off), "incident", None


def route_frames(var: Path, runs):
    """(path, t, 'route', (attempt, route, step, sub)) of every route snap."""
    for d in sorted((var / "routes").glob("attempt-*")):
        try:
            n = int(d.name.rsplit("-", 1)[1])
        except ValueError:
            continue
        if n not in runs:
            continue
        for p in sorted(os.listdir(d)):
            m = ROUTE_FRAME.match(p)
            if not m or "cannon-hop" in p:
                continue
            yield (str(d / p), os.path.getmtime(d / p), "route",
                   (n, m.group(2), int(m.group(3)), int(m.group(4) or 0)))


def homing_frames(var: Path, runs):
    for d in sorted((var / "homing").glob("attempt-*")):
        try:
            n = int(d.name.rsplit("-", 1)[1])
        except ValueError:
            continue
        for p in sorted(os.listdir(d)):
            if p.endswith(".jpg"):
                yield str(d / p), os.path.getmtime(d / p), "homing", (n,)


class Labels:
    """The research's labelling rule over one run's fixes."""

    def __init__(self, events: dict):
        self.ft = [t for t, _ in events["feed"]]
        self.ff = [f for _, f in events["feed"]]
        self.pt = [t for t, _ in events["panel"]]
        self.pp = [p for _, p in events["panel"]]

    def field(self, t: float) -> str | None:
        if not self.ft:
            return None
        j = bisect.bisect_left(self.pt, t - fs.PANEL_VETO_SECONDS)
        if j < len(self.pt) and self.pt[j] <= t + fs.PANEL_VETO_SECONDS:
            return None
        i = bisect.bisect_right(self.ft, t)
        before = (self.ft[i - 1], self.ff[i - 1]) if i > 0 else None
        after = (self.ft[i], self.ff[i]) if i < len(self.ft) else None
        if (before and after and before[1] == after[1]
                and after[0] - before[0] <= fs.BRACKET_SECONDS):
            return before[1]
        for fix in (before, after):
            if fix and abs(fix[0] - t) <= fs.NEAR_FIX_SECONDS:
                return fix[1]
        return None

    def panel(self, t: float) -> str | None:
        lo, hi = fs.PANEL_WINDOW
        j = bisect.bisect_left(self.pt, t - hi)
        hits = set()
        while j < len(self.pt) and self.pt[j] <= t - lo:
            hits.add(self.pp[j])
            j += 1
        return hits.pop() if len(hits) == 1 else None

    def label(self, t: float) -> str | None:
        f, p = self.field(t), self.panel(t)
        if f and p:
            return None
        return f or p


def route_target(route: str):
    m = re.match(r"natro_(out|home|back)_(.+?)(?:_via_red_cannon)?$", route)
    if m:
        return m.group(1), FIELD_OF_ROUTE.get(m.group(2), m.group(2))
    if route == "from_hive_to_pine_tree_with_red_cannon":
        return "out", "pine_tree"
    return None, None


def spread(items: list, k: int) -> list:
    if len(items) <= k:
        return list(items)
    step = len(items) / float(k)
    return [items[int(i * step)] for i in range(k)]


# ---- evaluation helpers ----------------------------------------------------------
def train(X, labels):
    return fs.Classifier.train(X, list(labels))


def auc(pos, neg) -> float:
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if not len(pos) or not len(neg):
        return float("nan")
    allv = np.concatenate([pos, neg])
    ranks = allv.argsort().argsort().astype(float) + 1
    # average ranks for ties
    order = np.argsort(allv)
    sorted_v = allv[order]
    i = 0
    while i < len(sorted_v):
        j = i
        while j + 1 < len(sorted_v) and sorted_v[j + 1] == sorted_v[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    rp = ranks[: len(pos)].sum()
    return float((rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def trust_table(pred, truth, margin, classes) -> dict:
    """Per predicted class: margin terciles (one band below 60 predictions,
    none below MIN_MEASURED) and the held-out precision in each."""
    table = {}
    for c in classes:
        m = pred == c
        n = int(m.sum())
        if n < fs.MIN_MEASURED:
            continue
        mg = margin[m]
        ok = (truth[m] == c)
        if n >= 3 * fs.MIN_MEASURED:
            cuts = list(np.quantile(mg, [1 / 3, 2 / 3]))
        else:
            cuts = []
        edges = [None] + [float(x) for x in cuts] + [None]
        bands = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            sel = np.ones(n, bool)
            if lo is not None:
                sel &= mg >= lo
            if hi is not None:
                sel &= mg < hi
            k = int(sel.sum())
            bands.append([lo, hi, round(float(ok[sel].mean()) if k else 0.0, 4), k])
        table[c] = bands
    return table


def coverage(pred, truth, margin) -> dict:
    order = np.argsort(-margin)
    c = (pred == truth)[order]
    prec = np.cumsum(c) / np.arange(1, len(c) + 1)
    out = {}
    for want in (0.5, 0.75, 0.9, 1.0):
        k = max(1, int(round(want * len(c))))
        out[f"precision_at_{int(want * 100)}pct"] = round(float(prec[k - 1]), 4)
    return out


# ---- main ------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--var", type=Path, default=ROOT / "var",
                    help="the bot's var directory (read only)")
    ap.add_argument("--out", type=Path, default=fs.MODEL,
                    help="the gallery .npz to write (the notes go beside it)")
    ap.add_argument("--cache", type=Path, default=None,
                    help="keep decoded descriptors here between runs (.npz)")
    ap.add_argument("--no-live", action="store_true",
                    help="leave out var/fieldsense/live-*.npz")
    # MEASURED 2026-10-22: section 4 trains once per attempt of every night;
    # at 12,235 rows (22 places, 584 live shards) that is hours per attempt's
    # worth of nights. The bot reads nothing from it (`learning` is a note).
    ap.add_argument("--no-learning", action="store_true",
                    help="skip section 4 (learning through the night)")
    ap.add_argument("--dry-run", action="store_true",
                    help="measure and print, write nothing")
    args = ap.parse_args(argv)
    var = args.var
    t_start = time.time()

    runs = run_windows(var)
    events = {n: parse_run(var, n, t0) for n, (t0, _) in runs.items()}
    labels = {n: Labels(e) for n, e in events.items()}
    spans = sorted((t0, t1, n) for n, (t0, t1) in runs.items())
    starts = [s[0] for s in spans]

    def attempt_at(t: float):
        i = bisect.bisect_right(starts, t + 5) - 1
        while i >= 0:
            t0, t1, n = spans[i]
            if t0 - 5 <= t <= t1 + 5:
                return n
            if t1 + 5 < t:
                break
            i -= 1
        return None

    print(f"runs {len(runs)}: feed fixes {sum(len(e['feed']) for e in events.values()):,}, "
          f"panel fixes {sum(len(e['panel']) for e in events.values()):,}", flush=True)

    # Label every frame, keeping only the labelled ones (and every route snap).
    labelled = defaultdict(list)          # (label, attempt) -> [(t, path, src)]
    walks = defaultdict(list)             # attempt -> [(t, route, step, sub, path)]
    seen = Counter()
    sources = [incident_frames(var), route_frames(var, runs), homing_frames(var, runs)]
    for gen in sources:
        for path, t, src, extra in gen:
            seen[src] += 1
            n = extra[0] if extra else attempt_at(t)
            if n is None or n not in labels:
                continue
            if src == "route":
                _, route, step, sub = extra
                walks[n].append((t, route, step, sub, path))
            lab = labels[n].label(t)
            if lab:
                labelled[(lab, n)].append((t, path, src))
    print(f"frames seen: {dict(seen)}; labelled {sum(len(v) for v in labelled.values()):,} "
          f"in {len(labelled)} (place, attempt) groups", flush=True)

    # The live shards, read first because their visits count too: a place the
    # bot has only learned live (Labeller) is a class once it has MIN_VISITS
    # visits, as the bot's own Gallery.rows makes it one, so it is measured
    # here and has trust bands -- or every other class's bands would be about
    # a classifier without it (DESIGN 8dz, review).
    g = fs.Gallery()
    live_dir = var / "fieldsense"
    if not args.no_live and live_dir.is_dir():
        for shard in sorted(live_dir.glob("live-*.npz")):
            try:
                g.load(shard, "live")
            except (OSError, ValueError, KeyError) as exc:
                print(f"  skipped {shard.name}: {exc}")

    # Which classes have enough visits to teach: the attempts behind each,
    # from the saved frames and the live shards together.
    seen_in = defaultdict(set)
    for place, n in labelled:
        seen_in[place].add(n)
    for place, n in zip(g.labels, g.attempts):
        seen_in[place].add(int(n))
    visits = Counter({c: len(v) for c, v in seen_in.items()})
    classes = sorted(c for c, v in visits.items() if v >= MIN_VISITS)
    print("visits per place:", dict(visits.most_common()), flush=True)

    # Sample (research sample.py), per class and attempt.
    chosen = []
    for c in classes:
        keys = [k for k in labelled if k[0] == c]
        if not keys:
            continue                   # learned live only: the shards carry it
        per = max(MIN_PER_ATTEMPT, min(PER_ATTEMPT, PER_CLASS // len(keys)))
        for k in keys:
            rows = sorted(labelled[k])
            thin, last = [], -1e9
            for r in rows:
                if r[0] - last >= fs.THIN_SECONDS:
                    thin.append(r)
                    last = r[0]
            for t, path, src in spread(thin, per):
                chosen.append((path, t, k[1], c, src))
    del labelled

    # Arrival walks: every walk out to a field, split at step 0.
    arrivals = []
    for n, rows in walks.items():
        rows.sort(key=lambda r: (r[0], r[2], r[3]))
        cur = None
        insts = []
        for r in rows:
            if (cur is None or r[1] != cur[0][1] or r[2] == 0
                    or r[0] - cur[-1][0] > 90):
                cur = [r]
                insts.append(cur)
            else:
                cur.append(r)
        for inst in insts:
            kind, target = route_target(inst[0][1])
            if kind != "out" or target not in classes:
                continue
            end = inst[-1][0]
            feed = events[n]["feed"]
            fixes = [f for t, f in feed if end - 1 <= t <= end + ARRIVAL_WINDOW][:ARRIVAL_FIXES]
            count = Counter(fixes).most_common()
            if not count or (len(count) > 1 and count[0][1] == count[1][1]):
                continue
            # WHAT THE FEED HAD SAID AT THE END OF ONE PASS, AND OF TWO, as
            # `landed_elsewhere` reads it: the latest field credited since the
            # trip began, and whether the aim was among them (its edge veto).
            said = {}
            for passes in (1, 2):
                window = [f for t, f in feed
                          if end - 1 <= t <= end + passes * ONE_PASS_SECONDS]
                said[passes] = (window[-1] if window and target not in window
                                else None)
            arrivals.append({"attempt": n, "route": inst[0][1], "target": target,
                             "truth": count[0][0], "path": inst[-1][4], "t": end,
                             "other_after_1": said[1], "other_after_2": said[2]})
    del walks
    print(f"sampled {len(chosen):,} frames of {len(classes)} places; "
          f"{len(arrivals)} walks out with a feed-majority truth", flush=True)

    # Decode and describe (cached by path).
    cache = {}
    if args.cache and args.cache.exists():
        with np.load(args.cache, allow_pickle=False) as z:
            for p, code, bed in zip(z["paths"], z["codes"], z["beds"]):
                cache[str(p)] = (code, bed)
    todo = sorted({c[0] for c in chosen} | {a["path"] for a in arrivals})
    todo = [p for p in todo if p not in cache]
    t0 = time.time()
    for k, path in enumerate(todo):
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            continue
        small = fs.shrink(img)
        bed = fs.flower_bed(small)
        cache[path] = (fs.quantise(fs.describe(small)),
                       np.array([bed.share, bed.cells, bed.dark, bed.raw_median,
                                 bed.towards[0], bed.towards[1]], np.float32))
        if k and k % 500 == 0:
            print(f"  decoded {k:,}/{len(todo):,} ({(time.time() - t0) / k * 1e3:.1f} ms each)",
                  flush=True)
    if args.cache and todo:
        paths = sorted(cache)
        np.savez(args.cache, paths=np.array(paths), codes=np.stack([cache[p][0] for p in paths]),
                 beds=np.stack([cache[p][1] for p in paths]))
    chosen = [c for c in chosen if c[0] in cache]
    arrivals = [a for a in arrivals if a["path"] in cache]

    codes = np.stack([cache[c[0]][0] for c in chosen])
    beds = np.stack([cache[c[0]][1] for c in chosen])
    lab = np.array([c[3] for c in chosen], dtype=object)
    att = np.array([c[2] for c in chosen], np.int32)
    times = np.array([c[1] for c in chosen], np.float64)
    srcs = np.array([c[4] for c in chosen], dtype=object)

    # Live shards join the gallery (and the hold-outs).
    live_rows = 0
    if len(g):
        keep = np.array([x in classes for x in g.labels])
        codes = np.concatenate([codes, g.codes[keep]])
        beds = np.concatenate([beds, np.full((int(keep.sum()), 6), np.nan, np.float32)])
        lab = np.concatenate([lab, np.array(g.labels, dtype=object)[keep]])
        att = np.concatenate([att, np.array(g.attempts, np.int32)[keep]])
        times = np.concatenate([times, np.array(g.times)[keep]])
        srcs = np.concatenate([srcs, np.array(["live"] * int(keep.sum()), dtype=object)])
        live_rows = int(keep.sum())
    del g
    # THE SAME CAPS THE BOT TRAINS UNDER (fieldsense.Gallery.rows: per class
    # the newest visits first, PER_ATTEMPT a visit, PER_CLASS in all), so what
    # is measured is what runs, and a gallery that has grown for months is
    # not trained on whole in every fold below.
    rows = _gallery(codes, lab, att, times).rows()
    if len(rows) < len(lab):
        print(f"  the bot's caps keep {len(rows):,} of {len(lab):,} frames", flush=True)
        codes, beds, lab, att, times, srcs = (a[rows] for a in (codes, beds, lab, att, times, srcs))
        live_rows = int((srcs == "live").sum())
    # WHAT THE BOT WILL TRAIN ON THIS GALLERY: the classes its rows keep. The
    # bot's field rules hold only while its classifier knows exactly these
    # (fieldsense.FieldSense.measured), since every trust band below is a
    # margin against these competitors.
    trained = sorted(set(lab))
    night = np.array([night_of(runs[a][0]) if a in runs else night_of(t)
                      for a, t in zip(att, times)])
    X = fs.unquantise(codes)
    nights = sorted(set(night))
    print(f"gallery {len(lab):,} frames ({live_rows:,} live), nights {nights}", flush=True)
    print("frames per place:", dict(Counter(lab).most_common()), flush=True)

    # ---- 1. which place, leave one night out --------------------------------
    pred = np.array([None] * len(lab), dtype=object)
    margin = np.zeros(len(lab), np.float32)
    models = {}
    for n in nights:
        tr = night != n
        if len(set(lab[tr])) < 2:
            continue
        model = train(X[tr], lab[tr])
        models[n] = model
        print(f"  night {n} held out ({time.time() - t_start:.0f}s)", flush=True)
        te = np.where(~tr)[0]
        te = te[np.isin(lab[te], model.classes)]
        if not len(te):
            continue
        sc = model.scores(X[te])
        for i, row in zip(te, sc):
            best, mg, _ = fs.top_two(row, model.classes)
            pred[i], margin[i] = best, mg
    scored = np.array([p is not None for p in pred])
    P, T, M = pred[scored], lab[scored], margin[scored]
    top1 = float((P == T).mean())
    per_class = {}
    for c in classes:
        m = T == c
        q = P == c
        per_class[c] = {"frames": int((lab == c).sum()), "held_out": int(m.sum()),
                        "nights": sorted(set(night[lab == c])),
                        "recall": round(float((P[m] == c).mean()), 4) if m.any() else None,
                        "precision": round(float((T[q] == c).mean()), 4) if q.any() else None}
    confusion = {c: dict(Counter(P[T == c]).most_common(4)) for c in classes}
    per_night = {n: {"n": int((night[scored] == n).sum()),
                     "top1": round(float((P[night[scored] == n] == T[night[scored] == n]).mean()), 4)}
                 for n in nights if (night[scored] == n).any()}
    trust = trust_table(P, T, M, classes)
    cov = coverage(P, T, M)
    print(f"\nWHICH PLACE, leave one night out: top-1 {top1:.3f} (n={len(T):,}); {cov}")
    print(f"  trust table: {json.dumps(trust)}")
    for n, v in per_night.items():
        print(f"  night {n}: {v['top1']:.3f} (n={v['n']})")
    for c in classes:
        v = per_class[c]
        print(f"  {c:16s} frames {v['frames']:5d} held-out {v['held_out']:5d} "
              f"recall {v['recall']} precision {v['precision']}  -> {confusion[c]}")

    # ---- 2. the walk out's last frame -----------------------------------------
    arr = []
    for a in arrivals:
        n = night_of(runs[a["attempt"]][0])
        model = models.get(n)
        if model is None or a["target"] not in model.classes:
            continue
        code = cache[a["path"]][0]
        bed = cache[a["path"]][1]
        row = model.scores(fs.unquantise(code[None, :]))[0]
        best, mg, _ = fs.top_two(row, model.classes)
        informative = (bed[1] > 0 and bed[2] < fs.DARK_NO_OPINION
                       and bed[3] < fs.WHITEOUT_NO_OPINION)
        sure = fs.Trust(trust).sure(best, mg)
        arr.append(dict(a, said=best, margin=float(mg), sure=sure,
                        informative=bool(informative)))
    arrival = {"walks": len(arr), "informative": sum(w["informative"] for w in arr)}
    good = [w for w in arr if w["informative"] and w["truth"] == w["target"]]
    bad = [w for w in arr if w["informative"] and w["truth"] != w["target"]]
    arrival["wrong_landings"], arrival["right_landings"] = len(bad), len(good)
    # TODAY'S RULE, the feed alone: another field at the end of two passes.
    arrival["feed_two_passes"] = {
        "wrong_caught": sum(w["other_after_2"] is not None for w in bad),
        "right_flagged": sum(w["other_after_2"] is not None for w in good)}
    arrival["feed_one_pass"] = {
        "wrong_caught": sum(w["other_after_1"] is not None for w in bad),
        "right_flagged": sum(w["other_after_1"] is not None for w in good)}
    for trust_at in (0.0, 0.8, 0.9, 0.95, 0.98):
        def doubts(w):
            return (w["said"] != w["target"] and w["sure"] is not None
                    and w["sure"] >= trust_at)
        # THE EARLY RULE: the look at the end of the walk doubts the aim AND
        # the feed names another field at the end of the first pass.
        arrival[f"look_{trust_at:.2f}"] = {
            "look_doubts_wrong": sum(doubts(w) for w in bad),
            "look_doubts_right": sum(doubts(w) for w in good),
            "and_one_pass_wrong_caught": sum(doubts(w) and w["other_after_1"] is not None
                                             for w in bad),
            "and_one_pass_right_flagged": sum(doubts(w) and w["other_after_1"] is not None
                                              for w in good)}
    # WHICH FIELD THE LAST FRAME SHOWS, against the feed's majority: what
    # whereami's "which field am I in" may say at the end of a walk.
    info = [w for w in arr if w["informative"]]
    arrival["top1"] = round(float(np.mean([w["said"] == w["truth"] for w in info])), 4) \
        if info else None
    for trust_at in (0.8, 0.9, 0.95):
        sure = [w for w in info if w["sure"] is not None and w["sure"] >= trust_at]
        arrival[f"top1_sure_{trust_at:.2f}"] = {
            "n": len(sure), "right": sum(w["said"] == w["truth"] for w in sure)}
    # THE TRUST AT WHICH A LOOK MAY SAY WHERE IT IS, for whereami's "which
    # field am I in" in place of the vision model's open question (MEASURED
    # at 44% on which field, DESIGN 8b). The compass is told a sight at the
    # precision measured here, so that must be at least what the compass
    # acts on (world/bearings SURE_ELSEWHERE); of the levels that clear it
    # with MIN_MEASURED answers behind them, the most precise, the lowest
    # level on a tie. None, and the vision model keeps the question.
    arrival["sight"] = None
    for trust_at in (0.8, 0.9, 0.95):
        v = arrival[f"top1_sure_{trust_at:.2f}"]
        if v["n"] < fs.MIN_MEASURED:
            continue
        precision = v["right"] / v["n"]
        best = arrival["sight"]
        if precision >= SURE_ELSEWHERE and (best is None or precision > best["precision"]):
            arrival["sight"] = {"trust": trust_at, "right": v["right"], "n": v["n"],
                                "precision": round(precision, 4),
                                # ...and only at the end of a walk to one of
                                # these: the only walks it was measured on.
                                "destinations": sorted({w["target"] for w in info})}
    # THE EARLY RULE'S TRUST LEVEL, chosen here so the farm loop never has to
    # guess one: the lowest level at which "the look doubts the aim and the
    # first pass's feed names another field" was at least as precise, on
    # held-out nights, as today's two-pass rule -- or none, and the rule is off.
    base_n = arrival["feed_two_passes"]["wrong_caught"] + arrival["feed_two_passes"]["right_flagged"]
    base = arrival["feed_two_passes"]["wrong_caught"] / base_n if base_n else None
    arrival["two_pass_precision"] = round(base, 4) if base is not None else None
    arrival["early_rule"] = None
    for trust_at in (0.8, 0.9, 0.95, 0.98):
        v = arrival[f"look_{trust_at:.2f}"]
        n = v["and_one_pass_wrong_caught"] + v["and_one_pass_right_flagged"]
        if not n or base is None:
            continue
        precision = v["and_one_pass_wrong_caught"] / n
        # today's rule would have flagged these right landings anyway
        extra = sum(w["said"] != w["target"] and w["sure"] is not None
                    and w["sure"] >= trust_at and w["other_after_1"] is not None
                    and w["other_after_2"] is None for w in good)
        if precision >= base and n >= fs.MIN_MEASURED // 2:
            arrival["early_rule"] = {"trust": trust_at, "precision": round(precision, 4),
                                     "wrong_caught_a_pass_sooner": v["and_one_pass_wrong_caught"],
                                     "of_wrong": len(bad),
                                     "right_flagged": v["and_one_pass_right_flagged"],
                                     "right_flagged_that_two_passes_would_not": extra,
                                     "of_right": len(good),
                                     # THE AIMS IT WAS MEASURED ON: a walk to a
                                     # place the classifier cannot name is
                                     # "doubted" by every sure look, and none
                                     # is in this sample.
                                     "aims": sorted({w["target"] for w in bad + good})}
            break
    by_route = defaultdict(lambda: [0, 0, 0, 0])
    for w in arr:
        if not w["informative"]:
            continue
        k = by_route[w["route"]]
        right = w["truth"] == w["target"]
        said_aim = w["said"] == w["target"]
        k[0 if right else 2] += 1
        k[1 if right else 3] += int(said_aim if right else not said_aim)
    arrival["by_route"] = {r: {"right_landings": v[0], "confirmed": v[1],
                               "wrong_landings": v[2], "doubted": v[3]}
                           for r, v in sorted(by_route.items())}
    print(f"\nTHE WALK OUT'S LAST FRAME ({arrival['walks']} walks, "
          f"{arrival['informative']} informative), nights held out:")
    for k, v in arrival.items():
        if (k.startswith(("look_", "feed_", "top1", "early", "two_"))
                or k.endswith("_landings")):
            print(f"  {k}: {v}")
    for r, v in arrival["by_route"].items():
        print(f"  {r:40s} {v}")

    # ---- 3. the flower bed: in a field or not -----------------------------------
    # "Off" is every frame labelled with somewhere that is not a field: the
    # hive and the landmarks (red cannon, ticket shop, honey dispenser), the
    # only places the game labels besides the fields. Not frames just past a
    # field's edge, and not a walk into the next field's flowers: nothing
    # labels those, so this measures flower bed against hive and landmark
    # ground.
    have_bed = ~np.isnan(beds[:, 0])
    fields = {f for e in events.values() for _, f in e["feed"]}
    is_field = np.array([c in fields for c in lab])
    info = have_bed & (beds[:, 1] > 0) & (beds[:, 2] < fs.DARK_NO_OPINION) & \
        (beds[:, 3] < fs.WHITEOUT_NO_OPINION)
    share = beds[:, 0]
    inside, outside = info & is_field, info & ~is_field
    edge = {"refused_share": round(float(1 - info[have_bed].mean()), 4),
            "auc_in_vs_off": round(auc(share[inside], share[outside]), 4),
            "in_field_median": round(float(np.median(share[inside])), 4),
            "in_field_p10": round(float(np.percentile(share[inside], 10)), 4),
            "off_field_p90": round(float(np.percentile(share[outside], 90)), 4),
            "n_in": int(inside.sum()), "n_off": int(outside.sum())}
    grid = np.round(np.arange(0.02, 0.41, 0.005), 3)

    def best_threshold(sel):
        a, b = share[inside & sel], share[outside & sel]
        if not len(a) or not len(b):
            return None
        bal = [((a >= g).mean() + (b < g).mean()) / 2 for g in grid]
        return float(grid[int(np.argmax(bal))])

    halves = [nights[: len(nights) // 2], nights[len(nights) // 2:]]
    tests = []
    for tune, test in (halves, halves[::-1]):
        g = best_threshold(np.isin(night, tune))
        if g is None:
            continue
        sel = np.isin(night, test)
        tests.append({"tuned_on": tune, "threshold": g, "tested_on": test,
                      "in_kept": round(float((share[inside & sel] >= g).mean()), 4),
                      "off_flagged": round(float((share[outside & sel] < g).mean()), 4)})
    edge["split_half"] = tests
    edge["threshold"] = best_threshold(np.ones(len(lab), bool))
    # WHERE THE WALK BACK STOPS: just past the edge, not deep in the flowers.
    # The highest edge either half of the nights chose on its own (at least
    # the pooled one), so a walk that starts under `threshold` stops where no
    # tuning would still call the frame off the field -- the in-field median
    # it stopped at before is a thickness Blue Flower, Dandelion, Mushroom and
    # Sunflower frames stay under most of the time (review, DESIGN 8dz).
    if edge["threshold"] is not None:
        edge["back_at"] = max([edge["threshold"]] + [t["threshold"] for t in tests])
    # Per place, for the owner and the next review: how thick the bed is in
    # each field's own frames, and how often a frame is under the edge.
    edge["by_place"] = {}
    for c in sorted(set(lab[inside])):
        sh = share[inside & (lab == c)]
        edge["by_place"][c] = {"n": int(len(sh)), "p25": round(float(np.percentile(sh, 25)), 4),
                               "median": round(float(np.median(sh)), 4),
                               "under_threshold": round(float((sh < edge["threshold"]).mean()), 4)
                               if edge["threshold"] is not None else None}
    print(f"\nTHE FLOWER BED: {edge}")

    # ---- 4. does learning from the night it is playing help? ---------------------
    order = [] if args.no_learning else sorted(nights)
    frozen_hits, learn_hits, n_test = 0, 0, 0
    for k, n in enumerate(order[1:], start=1):
        past = np.isin(night, order[:k])
        if len(set(lab[past])) < 2:
            continue
        frozen = train(X[past], lab[past])
        tonight = sorted(set(att[night == n]))
        for a in tonight:
            te = np.where((att == a) & (night == n))[0]
            te = te[np.isin(lab[te], frozen.classes)]
            if not len(te):
                continue
            earlier = (night == n) & (att < a)
            sel = past | earlier
            model = frozen if not earlier.any() else train(X[sel], lab[sel])
            fr = [fs.top_two(r, frozen.classes)[0] for r in frozen.scores(X[te])]
            le = [fs.top_two(r, model.classes)[0] for r in model.scores(X[te])]
            frozen_hits += sum(p == t for p, t in zip(fr, lab[te]))
            learn_hits += sum(p == t for p, t in zip(le, lab[te]))
            n_test += len(te)
    learning = {"frames": n_test,
                "frozen_at_start_of_night": round(frozen_hits / max(1, n_test), 4),
                "learning_through_the_night": round(learn_hits / max(1, n_test), 4)}
    print(f"\nLEARNING WHILE IT PLAYS (forward in time, each attempt scored before it is "
          f"taught): {learning}")

    # ---- 5. speed ------------------------------------------------------------------
    full = cv2.imread(chosen[len(chosen) // 2][0], cv2.IMREAD_COLOR)
    model = train(X, lab)
    sense = fs.FieldSense(model=None, notes=None, live_dir=None)
    sense.classifier, sense.trust = model, fs.Trust(trust)
    spent = []
    for _ in range(50):
        t1 = time.perf_counter()
        sense.look(full)
        spent.append(time.perf_counter() - t1)
    rows = _gallery(codes, lab, att, times).rows()
    t1 = time.perf_counter()
    train(X[rows], lab[rows])
    train_s = time.perf_counter() - t1
    speed = {"look_ms_median": round(float(np.median(spent)) * 1e3, 2),
             "look_ms_p95": round(float(np.percentile(spent, 95)) * 1e3, 2),
             "train_seconds": round(train_s, 2), "train_rows": int(len(rows))}
    print(f"\nSPEED (one thread): {speed}")

    notes = {"made": time.strftime("%Y-%m-%d %H:%M:%S"),
             "var": str(var).replace(str(Path.home()), "~", 1), "runs": len(runs), "nights": nights,
             "frames": int(len(lab)), "live_frames": live_rows,
             "classes": trained, "visits": {c: int(visits[c]) for c in trained},
             "descriptor": {"size": [fs.W, fs.H], "grid": list(fs.GRID),
                            "bins": [fs.HUE_BINS, fs.SAT_BINS], "dim": fs.DIM},
             "svm": {"C": fs.SVM_C, "gamma": fs.SVM_GAMMA, "kind": "one-vs-rest RBF"},
             "held_out": {"top1": round(top1, 4), "n": int(len(T)), "per_night": per_night,
                          "coverage": cov, "per_class": per_class, "confusion": confusion},
             "trust": trust, "arrival": arrival, "edge": edge, "learning": learning,
             "speed": speed, "seconds": round(time.time() - t_start, 1)}
    if args.dry_run:
        print("\n(dry run: nothing written)")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_name(f".{args.out.name}.tmp.npz")
    # THE SEED ONLY: the bot loads var/fieldsense/live-*.npz itself, so a live
    # row written here as well would be in its gallery twice. What it trains
    # is still what was measured: these rows and the same shards, under the
    # same caps (Gallery.rows).
    seed = srcs != "live"
    np.savez_compressed(tmp, codes=codes[seed], labels=np.array(lab[seed].astype(str)),
                        attempts=att[seed], times=times[seed])
    os.replace(tmp, args.out)
    note_path = args.out.with_suffix(".json")
    note_tmp = note_path.with_name(f".{note_path.name}.tmp")
    note_tmp.write_text(json.dumps(notes, indent=1) + "\n")
    os.replace(note_tmp, note_path)
    print(f"\nwrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB) and {note_path}")
    return 0


def _gallery(codes, lab, att, times) -> "fs.Gallery":
    g = fs.Gallery()
    g.extend(codes, list(lab), list(att), list(times), "seed")
    return g


if __name__ == "__main__":
    sys.exit(main())
