#!/usr/bin/env python3
"""How long each token kind lies on the field, measured on OUR frames, and
the stacked same-kind pairs a duplicated (duped) token would make.

    ./tools/analysis/token_lifespans.py [--home ~/Hivemind] [--out DIR]

THE FRAMES are the saved token bursts (var/incidents/*-token: 150 frames,
~7.7 s, ~19 fps). Bursts saved a few seconds apart share frames, so they are
stitched into longer sequences (frame time = the burst's last file's mtime
less the frame's t+ offset; a frame already in the sequence is known by its
file size). Every frame is run through the live detector (vision/tokens.
detect) with the typed head on (vision/tokentypes), and the sightings are
tracked STRICTLY frame to frame by the farm's own Tracker carried by the
ground flow (vision/flow, the farm's GROUND_ROI), forgetting after
GAP_S -- a coin seen edge-on drops out for a few frames, never longer.

A track's VISIBLE LIFE is last sighting - first sighting. It is kept only
when uncensored at both ends: born after the sequence's first EDGE_S and away
from the world box's edge (not walked into view), died before the last EDGE_S,
away from the edge (not walked out of view), not within PICKUP_PX of the
character (picked up, not expired) and with no camera turn while alive. What
is left is a lower bound per token (the detector finds it a little after it
lands); its upper tail is the kind's life. Read-only; never touches the game.

DUPED CANDIDATES (ROADMAP AI-N2): a track seen in place longer than DUPED_LIFE
x its kind's `life_s`, and two sightings in one frame named the same kind, one above the
other (|dx| <= STACK_DX x the coin side, dy within STACK_DY sides), listed in
--out's pairs.json for eye-checking; see docs/pending/lifespans.md.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import cv2                                                      # noqa: E402
import numpy as np                                              # noqa: E402

from hivemind.vision import coins, tokens, tokentypes           # noqa: E402
from hivemind.vision.flow import GROUND_ROI, FlowTracker        # noqa: E402
from hivemind.vision.tracks import Tracker                      # noqa: E402

GAP_S = 0.8                 # unseen this long = gone (strict, not the farm's 4 s)
MATCH_PX = 60.0             # frame to frame at ~19 fps, after the flow carry
EDGE_S = 0.5                # born/died this close to a sequence end: censored
EDGE_PX = 60                # born/died this close to the world box: censored
PICKUP_PX = 200             # died this close to the character: picked up
ANCHOR = (960, 669)         # the character's feet at 1920x1080 (tokenbrain)
TURN_PX = 80                # a flow step this big, or a failed one, is a turn
MIN_MATCHES = 4             # fewer is a glint
STACK_DX, STACK_DY = 0.5, (0.6, 3.0)
# A duped token lasts twice its kind's life (wiki, Digital Bee / Ability
# Tokens, via bee-swarm-simulator.wiki read 2026-10-27; fandom answered 402):
# an uncensored track past this x tokens.yaml `life_s` is a duped candidate.
DUPED_LIFE = 1.5


def sequences(inc: Path):
    """[[(time, size, path), ...], ...]: stitched bursts, oldest first."""
    bursts = []
    for d in sorted(inc.glob("*-token")):
        fs = sorted(f for f in os.listdir(d) if f.endswith(".jpg"))
        if not fs:
            continue
        ts = [float(re.search(r"t\+([\d.]+)s", f).group(1)) for f in fs]
        last = os.stat(d / fs[-1]).st_mtime
        bursts.append([(last - (ts[-1] - t), os.stat(d / f).st_size, str(d / f))
                       for f, t in zip(fs, ts)])
    bursts.sort(key=lambda b: b[0][0])
    seqs: list[list] = []
    for b in bursts:
        if seqs and b[0][0] <= seqs[-1][-1][0] + 0.3:
            seen = {s for _, s, _ in seqs[-1]}
            tail = seqs[-1][-1][0]
            seqs[-1].extend(f for f in b if f[1] not in seen and f[0] > tail - 0.05)
        else:
            seqs.append(list(b))
    return seqs


def near_edge(x, y, box) -> bool:
    x0, y0, x1, y1 = box
    return min(x - x0, x1 - x, y - y0, y1 - y) < EDGE_PX


def look_at(seq, cache: dict) -> None:
    """Per frame of `seq`, into `cache[path]`: (frame size, ground homography
    from the last frame or None at a turn, [(x, y, kind, confidence, side)])."""
    flow = FlowTracker(roi=GROUND_ROI)
    for _, _, path in seq:
        if path in cache:
            flow.reset()            # ponytail: a cached frame breaks the flow chain once
            continue
        frame = cv2.imread(path)
        if frame is None:
            continue
        f = flow.update(frame)
        hom = None
        if f is not None and f.ok and f.pairs is not None and len(f.pairs) >= 8 \
                and f.motion_px <= TURN_PX:
            hom, _ = cv2.findHomography(f.pairs[:, 0], f.pairs[:, 1], cv2.RANSAC, 3.0)
        cache[path] = (frame.shape[1], frame.shape[0], f is None,
                       None if hom is None else hom.tolist(),
                       [(s.x, s.y, s.kind, s.confidence, s.box[2]) for s in tokens.detect(frame)])


def run_sequence(seq, cache: dict, pairs_out: list, gap: float = GAP_S):
    """Tracks of one sequence as dicts (kind, life, censored why, ...)."""
    tr = Tracker(match_px=MATCH_PX, forget_after=gap, forget_unconfirmed_after=gap)
    t0, t1 = seq[0][0], seq[-1][0]
    born: dict = {}                  # id -> (x, y) at birth
    turned_ids: set = set()
    every: dict = {}
    box = None
    for when, _, path in seq:
        if path not in cache:
            continue
        w, h, first, hom, seen = cache[path]
        box = box or coins.world_box(w, h)
        if hom is None and not first:
            turned_ids |= set(tr.tracks)
            tr.turned()
        found = [tokens.Sighting(x=x, y=y, kind=k, confidence=c, box=(0, 0, side, side))
                 for x, y, k, c, side in seen]
        for t in tr.observe(found, when, scene_transform=hom):
            every[t.id] = t
            born.setdefault(t.id, (t.x, t.y))
        by_kind = collections.defaultdict(list)
        for s in found:
            if s.kind != "unknown":
                by_kind[s.kind].append(s)
        for kind, ss in by_kind.items():
            for a in ss:
                for b in ss:
                    side = max(a.box[2], b.box[2])
                    if a is not b and abs(a.x - b.x) <= STACK_DX * side \
                            and STACK_DY[0] * side <= b.y - a.y <= STACK_DY[1] * side:
                        pairs_out.append({"frame": path, "kind": kind, "upper": [a.x, a.y],
                                          "lower": [b.x, b.y], "side": side})
    out = []
    for t in every.values():
        if t.matches < MIN_MATCHES:
            continue
        bx, by = born[t.id]
        why = ("born at the start" if t.first_seen < t0 + EDGE_S else
               "walked into view" if near_edge(bx, by, box) else
               "alive at the end" if t.last_seen > t1 - EDGE_S else
               "walked out of view" if near_edge(t.x, t.y, box) else
               "at the character" if np.hypot(t.x - ANCHOR[0], t.y - ANCHOR[1]) < PICKUP_PX else
               "camera turn" if t.id in turned_ids else "")
        out.append({"kind": t.kind, "life": round(t.last_seen - t.first_seen, 2),
                    "matches": t.matches, "conf": round(t.detector_confidence, 3),
                    "censored": why, "seq": seq[0][2], "first": round(t.first_seen - t0, 2),
                    "xy": [t.x, t.y], "own_motion": t.own_motion()})
    return out


def km_quantile(rows, q: float) -> float | None:
    """Kaplan-Meier: the life by which a share `q` of tokens seen landing
    has vanished, counting the right-censored ones (still alive at the end,
    walked out of view, picked up, a turn) as at risk until then."""
    pts = sorted((r["life"], not r["censored"]) for r in rows
                 if r["censored"] not in LEFT)
    s, n = 1.0, len(pts)
    for life, vanished in pts:
        if vanished:
            s *= 1 - 1 / n
            if 1 - s >= q:
                return life
        n -= 1
    return None


LEFT = ("born at the start", "walked into view")


def table(rows) -> dict:
    """Per kind: n, median, p90, p95, max of the uncensored visible lives,
    and the Kaplan-Meier p90 / p95 over every track seen landing."""
    by, every = collections.defaultdict(list), collections.defaultdict(list)
    for r in rows:
        every[r["kind"]].append(r)
        if not r["censored"]:
            by[r["kind"]].append(r["life"])
    return {k: {"n": len(v), "median": round(float(np.median(v)), 2),
                "p90": round(float(np.percentile(v, 90)), 2),
                "p95": round(float(np.percentile(v, 95)), 2), "max": round(max(v), 2),
                "n_landed": sum(r["censored"] not in LEFT for r in every[k]),
                "km_p90": km_quantile(every[k], 0.9), "km_p95": km_quantile(every[k], 0.95)}
            for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", type=Path, default=Path.home() / "Hivemind")
    ap.add_argument("--out", type=Path, required=True, help="tracks.jsonl, pairs.json, report.json")
    ap.add_argument("--limit", type=int, default=0, help="only the first N sequences")
    ap.add_argument("--gap", type=float, default=GAP_S, help="unseen this long = gone (s)")
    args = ap.parse_args()
    tokentypes.switch(True)
    if tokentypes.model() is None:
        print(tokentypes.error())
        return 1
    seqs = sequences(args.home / "var/incidents")
    if args.limit:
        seqs = seqs[:args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    cache_file = args.out / "looks.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    rows, pairs = [], []
    for i, seq in enumerate(seqs):
        look_at(seq, cache)
        got = run_sequence(seq, cache, pairs, args.gap)
        rows += got
        print(f"sequence {i + 1}/{len(seqs)}: {len(seq)} frames, "
              f"{seq[-1][0] - seq[0][0]:.1f} s, {len(got)} tracks", flush=True)
    cache_file.write_text(json.dumps(cache), encoding="utf-8")
    with (args.out / "tracks.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    (args.out / "pairs.json").write_text(json.dumps(pairs, indent=1), encoding="utf-8")
    kinds = tokens.load_kinds(ROOT / "data/knowledge/tokens.yaml")
    long_ = [r for r in rows if not r["censored"] and kinds.life_s(r["kind"])
             and r["life"] > DUPED_LIFE * kinds.life_s(r["kind"])]
    report = {"sequences": len(seqs), "seconds": round(sum(s[-1][0] - s[0][0] for s in seqs), 1),
              "tracks": len(rows), "censored": dict(collections.Counter(r["censored"] or "kept" for r in rows)),
              "lives": table(rows), "stacked_pairs": dict(collections.Counter(p["kind"] for p in pairs)),
              "longer_than_its_life": long_}
    (args.out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
