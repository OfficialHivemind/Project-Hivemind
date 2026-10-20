#!/usr/bin/env python3
"""Replay recorded frames through the token pipeline and print every decision.

A TEST BENCH, on our own recordings: replay a gather session tick by tick
and inspect the field state, buffs, timing, candidates and scores at each
decision point. We record -- `var/incidents/<stamp>-
token/NNN_t+SS.Ss.jpg`, 150 frames at about 10 fps around each token event
-- and until tonight nothing replayed them. This does, with the same
pipeline the farm runs: detect -> name the kind -> drop what is pinned to
the screen -> remember (Tracker, carried by the ground's flow) -> decide
(TokenBrain). No game needed, no keys pressed.

WHAT IT IS FOR. Tuning the brain against evidence instead of a live run:
how often it holds, chases, switches; what it would chase; what the body
gate removes; whether a real token in the frame is ever picked. Run it after
changing a weight or a curve and read the summary before touching the farm.

    ./scripts/replay_brain.py [incident-dir ...] [--every N] [--overlay] [--in-view]

With no directories it replays every `var/incidents/*token*`. `--overlay`
writes annotated frames to var/replay/<incident>/ for the eye to check.
`--in-view` decides as the farm does, on what the latest look matched; each
replay also counts how many chase targets the next frame still shows where
the chase could start (tokenbrain.IN_VIEW_S has the numbers).
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import chase                                  # noqa: E402
from hivemind.brain import tokenbrain                           # noqa: E402
from hivemind.brain.tokenbrain import IN_VIEW_S, TokenBrain     # noqa: E402
from hivemind.vision import tokens                              # noqa: E402
from hivemind.vision.flow import GROUND_ROI, FlowTracker        # noqa: E402
from hivemind.vision import pinned as pinned_mod                # noqa: E402
from hivemind.vision.pinned import Pinned                       # noqa: E402
from hivemind.vision.tracks import Tracker                      # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
STAMP = re.compile(r"^(\d+)_t\+(\d+\.\d)s\.jpg$")


def frames_of(folder: pathlib.Path):
    for p in sorted(folder.glob("*.jpg")):
        m = STAMP.match(p.name)
        if m:
            yield float(m.group(2)), p


def replay(folder: pathlib.Path, kinds, every: int, overlay: bool,
           confidence: float, homography: bool = False, in_view: bool = False,
           in_view_s: float | None = None, value: float | None = None) -> dict:
    tracker = Tracker()
    brain = TokenBrain(priority_of=kinds.priority, life_of=kinds.life_s,
                       weight_of=kinds.weight, preempt_of=kinds.preempt_px,
                       in_view_s=in_view_s if in_view_s is not None
                       else IN_VIEW_S if in_view else None)
    verdicts = collections.Counter()
    # STARTABLE: does the very next frame hold a sighting act/chase's `pick`
    # would start on -- within SAME_TOKEN_PX of the target, at `confidence`?
    # (run_farm's chase looks again before its first step.)
    startable = collections.Counter()
    waiting = None                         # the last chase target, for the next frame
    pinned = Pinned()
    flow = FlowTracker(roi=GROUND_ROI)
    anchor = None
    tally = collections.Counter()
    targets = collections.Counter()
    kinds_now, kinds_would, would_n = (collections.Counter() for _ in range(3))
    gated_body = 0
    seen_tracks: dict = {}                 # every track ever alive, by id
    scene = (0.0, 0.0)
    previous = None
    carried = None                         # ground homography composed since the last observe
    out_dir = ROOT / "var" / "replay" / folder.name
    if overlay:
        out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n=== {folder.name} ===")
    for i, (t, path) in enumerate(frames_of(folder)):
        frame = cv2.imread(str(path))
        if frame is None:
            continue
        if anchor is None:
            anchor = chase.anchor_of(frame.shape[1], frame.shape[0])
        sample = flow.update(frame)
        # the same view-change measure the farm feeds the pin with
        moved = pinned_mod.view_change(previous, frame) if previous is not None else 0.0
        previous = frame
        if sample is not None and sample.ok:
            # accumulated across the frames this replay skips, as the farm's
            # flow does between two looks
            scene = (scene[0] + float(sample.dx), scene[1] + float(sample.dy))
        H = None
        if homography and sample is not None and sample.pairs is not None and len(sample.pairs) >= 8:
            src = sample.pairs[:, 0, :].astype(np.float64)
            dst = sample.pairs[:, 1, :].astype(np.float64)
            H, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
            if inliers is None or int(inliers.sum()) < 8:
                H = None
        # compose the per-frame transforms across the frames this replay skips
        if H is not None:
            carried = H if carried is None else H @ carried
        if waiting is not None:
            tx, ty = waiting
            waiting = None
            near = [s_ for s_ in tokens.detect(frame) if s_.confidence >= confidence
                    and ((s_.x - tx) ** 2 + (s_.y - ty) ** 2) ** 0.5 <= chase.SAME_TOKEN_PX]
            startable["startable" if near else "not startable"] += 1
        if i % every:
            continue
        seen = tokens.detect(frame)
        seen = [s_ for s_ in seen if s_.confidence >= confidence]
        for s_ in seen:
            s_.kind = kinds.classify(s_)
        pinned.teach(moved, seen)
        kept = pinned.keep(moved, seen)
        if homography and carried is not None:
            tracker.observe(kept, t, scene_transform=carried)
        else:
            tracker.observe(kept, t, scene_shift=scene)
        scene = (0.0, 0.0)
        carried = None
        for tr in tracker.alive(t):
            seen_tracks[tr.id] = tr
        decision = brain.decide(tracker.alive(t), anchor, anchor, t)
        tally[decision.action] += 1
        # tokenbrain.WEIGHTS_LIVE off: the chase's kind as decided, and as
        # the per-hive weights / urgency / preempts would have it
        if decision.action == "chase":
            kinds_now[decision.target.kind] += 1
        if decision.would:
            would_n[decision.would.split()[0]] += 1
            print(f"           weights would: {decision.would[:140]}")
        w = decision.would
        if w.startswith("chase "):
            kinds_would[w.split()[1].split("#")[0]] += 1
        elif not w and decision.action == "chase":
            kinds_would[decision.target.kind] += 1
        gated_body += sum(1 for c in decision.ranked
                          if c.gated and "own body" in c.gated)
        if decision.target is not None and not decision.target.is_return:
            targets[f"{decision.target.kind}#{decision.target.track_id}"] += 1
            if decision.action == "chase":
                waiting = (decision.target.x, decision.target.y)
        top = [c for c in decision.ranked if not c.gated and not c.is_return][:3]
        print(f"  t+{t:5.1f}s  seen {len(seen):2d} kept {len(kept):2d} tracks "
              f"{len(tracker.alive(t)):2d}  {decision.describe()[:90]}")
        for c in top:
            print(f"           {c.describe()[:110]}")
        if value is not None:
            would = tokenbrain.shadow(decision, value)
            if would:
                verdicts[would.split()[0]] += 1
                print(f"           would: {would[:150]}")
        if overlay:
            canvas = frame.copy()
            for s_ in kept:
                cv2.rectangle(canvas, (s_.x - 12, s_.y - 12), (s_.x + 12, s_.y + 12), (0, 255, 0), 1)
            if decision.target is not None and not decision.target.is_return:
                cv2.circle(canvas, (decision.target.x, decision.target.y), 26, (0, 0, 255), 3)
            cv2.circle(canvas, anchor, 6, (255, 0, 255), -1)
            cv2.putText(canvas, decision.describe()[:80], (20, 1040),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.imwrite(str(out_dir / path.name), canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    print(f"  -- decisions {dict(tally)}; own-body gates {gated_body}; "
          f"switches {brain.interrupts}; targets {dict(targets.most_common(6))}")
    print(f"  -- chase targets in the next frame: {dict(startable)}")
    if value is not None:
        print(f"  -- value chooser at {value:,.0f} honey/s gathering: {dict(verdicts)}")
    # MOTION AGAINST THE GROUND, per confirmed track ever seen: the statistic
    # that should separate a token (lies still, bobs) from a bee or a damage
    # number (moves on its own). Printed so a threshold can be measured, not
    # guessed.
    rows = sorted(((t.own_motion() or 0.0), t) for t in seen_tracks.values() if t.matches >= 3)
    if rows:
        vals = [m for m, _ in rows]
        q = lambda f: vals[min(len(vals) - 1, int(f * len(vals)))]
        print(f"  -- own motion (px/s) over {len(vals)} tracks with 3+ matches: "
              f"p10 {q(0.1):.0f}  p50 {q(0.5):.0f}  p90 {q(0.9):.0f}  max {vals[-1]:.0f}")
        print("     stillest:", "; ".join(f"#{t.id} {t.kind} ({t.x},{t.y}) x{t.matches} {m:.0f}px/s" for m, t in rows[:4]))
        print("     fastest: ", "; ".join(f"#{t.id} {t.kind} ({t.x},{t.y}) x{t.matches} {m:.0f}px/s" for m, t in rows[-4:]))
    # HOW LONG A TOKEN STAYED IN VIEW, per kind: first to last sighting of a
    # track matched 3+ times -- a floor on its life on the field (it may have
    # spawned before the first look and lasted past the last), to set beside
    # tokens.yaml's wiki `life_s`.
    lived = collections.defaultdict(list)
    for t in seen_tracks.values():
        if t.matches >= 3:
            lived[t.kind].append(t.last_seen - t.first_seen)
    return {"folder": folder.name, "decisions": dict(tally), "gated_body": gated_body,
            "kinds_now": kinds_now, "kinds_would": kinds_would, "would": would_n,
            "lived": lived,
            "targets": dict(targets), "startable": dict(startable)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="*")
    ap.add_argument("--every", type=int, default=2, help="replay every Nth frame (default 2)")
    ap.add_argument("--overlay", action="store_true")
    ap.add_argument("--homography", action="store_true",
                    help="carry tracks by a ground homography fitted to the flow's point pairs "
                         "instead of the median shift")
    ap.add_argument("--confidence", type=float, default=chase.DEFAULT_CHASE_CONFIDENCE,
                    help="detector confidence the brain may see (the farm's gather.chase_confidence)")
    ap.add_argument("--in-view", action="store_true",
                    help="decide only on the tracks the latest look matched, as the farm "
                         "does (tokenbrain.IN_VIEW_S)")
    ap.add_argument("--in-view-s", type=float, default=None, metavar="F",
                    help="gate tracks unseen longer than F s (sweeps tokenbrain.IN_VIEW_S)")
    ap.add_argument("--value", type=float, default=None, metavar="HONEY_S",
                    help="print the shadow value chooser's verdict on each decision at this "
                         "gathering rate, honey/s (tokenbrain.shadow)")
    ap.add_argument("--hive", default="",
                    help="the hive colour (progression.hive): picks tokens.yaml's "
                         "weight_by_hive row for the weights-would tally")
    args = ap.parse_args()
    dirs = [pathlib.Path(d) for d in args.dirs] or sorted(
        p for p in (ROOT / "var" / "incidents").glob("*token*") if p.is_dir())
    kinds = tokens.load_kinds(ROOT / "data/knowledge/tokens.yaml", hive=args.hive)
    results = [replay(d, kinds, max(1, args.every), args.overlay, args.confidence,
                      args.homography, args.in_view, args.in_view_s, args.value)
               for d in dirs]
    total, starts = collections.Counter(), collections.Counter()
    for r in results:
        total.update(r["decisions"])
        starts.update(r["startable"])
    print(f"\n{len(results)} recording(s): decisions {dict(total)}; "
          f"chase targets in the next frame {dict(starts)}")
    now, would, said = collections.Counter(), collections.Counter(), collections.Counter()
    lived = collections.defaultdict(list)
    for r in results:
        now.update(r["kinds_now"])
        would.update(r["kinds_would"])
        said.update(r["would"])
        for k, v in r["lived"].items():
            lived[k].extend(v)
    print(f"chases by kind {dict(now)}; with the weights (tokenbrain.WEIGHTS_LIVE) "
          f"{dict(would)}; differing decisions {dict(said)}")
    for k, v in sorted(lived.items()):
        v.sort()
        q = lambda f: v[min(len(v) - 1, int(f * len(v)))]
        print(f"in view, first to last sighting, {k}: n {len(v)}  p50 {q(0.5):.1f}s  "
              f"p90 {q(0.9):.1f}s  max {v[-1]:.1f}s  (tokens.yaml life_s {kinds.life_s(k)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
