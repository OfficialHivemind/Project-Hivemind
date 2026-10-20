#!/usr/bin/env python3
"""How well is the Vicious Bee's spike seen? Score detectors on our own frames.

    ./.venv/bin/python scripts/score_vicspike.py [--var ~/Hivemind/var] [--sift 300]

THE FRAMES (all ours; the hunt's run past dawn, so most are day frames):
  * NEGATIVES: every kept hunt frame (var/vicious/<stamp>/*.jpg -- 20 of 20
    hunts 'absent', so no spike was stepped on) and the last frame of every
    route whose `00-start` view vision/night calls night (var/routes: fields
    and paths all over the map). A hit on one is a false alarm. (Not proven
    spike-free -- a spike nobody stepped on may stand in one; every hit's crop
    is written to --crops for a person to look at, which is how that is
    checked.)
  * POSITIVES: the owner's spike (var/reference/vicious_spike_owner_2026-10-21
    .png), SPIKES below (the real ones in our own frames), and the owner's spike cut out and pasted into
    each negative frame on a patch of field, 0.25-1.1x its size, leaning up to
    +-25 degrees, 0.7-1.15x as bright, through JPEG q70 (seeded, so the numbers
    repeat). A hit within 3/4 of its length of where it was pasted is found.
  ponytail: pasted spikes carry the one real spike's colours; a spike in
  another light or at a lookout's top-down angle is untested until frames of
  one exist (the look-only lookout keeps them).

THE DETECTORS, side by side:
  * colour (Q3b, 2026-10-21): H 85-110, S<120, V>150, a blob 2.5x taller than
    wide -- the rule ROADMAP Q3b found flags too much.
  * sift: SIFT keypoints of the owner's crop, Lowe ratio 0.75, >= 4 matches
    within 40 px -- the keypoint idea, measured on the same frames.
  * vicspike: vision/vicspike.find (colour + spike shape + grass at its base).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.vision import night, vicspike     # noqa: E402

REF = "reference/vicious_spike_owner_2026-10-21.png"
# THE REAL SPIKES IN OUR OWN HUNT FRAMES, found by this detector's first
# version and checked by eye 2026-10-26 (frame, its base x, y at 1920x1080):
# two of the 'absent' hunts had a spike in view and walked past it.
# 20261023-204232 also shows "Vicious Bee is attacking ... in the Clover
# Field!" at 0032.1 -- the bee WAS summoned; the feed's text read missed it.
SPIKES = (
    ("vicious/20261015-070531/0027.7-clover-arrived.jpg", 927, 337),
    ("vicious/20261015-070531/0029.2-check.jpg", 282, 337),
    ("vicious/20261015-070531/0042.2-check.jpg", 1105, 250),   # against the sky
    ("vicious/20261023-204232/0029.1-clover-arrived.jpg", 1515, 350),
    ("vicious/20261023-204232/0030.5-check.jpg", 842, 352),
    # the same night's arrival, seen by the route's own camera
    ("routes/attempt-1017/070558-natro_out_clover_via_red_cannon-15-pause-.jpg", 927, 337),
    # another night (attempt-669, 02:47): one beside a Moon token, in the
    # field the cactus start/pattern frames show
    ("routes/attempt-669/024733-natro_start_cactus-walk-01-pause-.jpg", 707, 370),
    ("routes/attempt-669/024815-natro_pattern_cactus_as_natro-01-pause-.jpg", 707, 370),
)
REAL_NEAR = 45                    # px: a hit this close to the labelled base


def negatives(var: pathlib.Path) -> list[pathlib.Path]:
    labelled = {var / f for f, _x, _y in SPIKES}
    out = sorted(var.glob("vicious/*/*.jpg"))
    for d in sorted(var.glob("routes/attempt-*")):
        groups: dict[str, list[str]] = {}
        for f in sorted(os.listdir(d)):
            parts = f.split("-")
            if len(parts) >= 3:
                groups.setdefault(parts[1], []).append(f)
        for g in groups.values():
            start = [f for f in g if "-00-start" in f]
            if start and night.is_night(cv2.imread(str(d / start[0]))):
                out.append(d / g[-1])
    return [p for p in out if p not in labelled]


def sprite(ref: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The owner's spike cut out: (BGR crop, alpha 0-1)."""
    hsv = cv2.cvtColor(ref, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (85, 0, 150), (110, 120, 255))
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask)
    i = 1 + int(np.argmax(st[1:, 4]))
    x, y, w, h, _a = st[i]
    m = (lab == i).astype(np.uint8)
    m = cv2.dilate(m, np.ones((3, 3), np.uint8))
    alpha = cv2.GaussianBlur(m.astype(np.float32), (3, 3), 0)
    p = 3
    return (ref[y - p:y + h + p, x - p:x + w + p].copy(),
            alpha[y - p:y + h + p, x - p:x + w + p].copy())


def paste(frame, spr, alpha, rng: random.Random):
    """(frame with the spike pasted on field, (x, y, length)) or None."""
    s = rng.uniform(0.25, 1.1)
    # the owner's spike leans 13 degrees already; ours lean up to ~25 (an
    # eye-level camera has no roll, so a spike stands near upright)
    ang = rng.uniform(-25, 25)
    gain = rng.uniform(0.7, 1.15)
    h0, w0 = spr.shape[:2]
    size = int(max(h0, w0) * s * 1.5) + 4
    big = np.zeros((size, size, 3), np.float32)
    bal = np.zeros((size, size), np.float32)
    sm = cv2.resize(spr, (max(1, int(w0 * s)), max(1, int(h0 * s))), interpolation=cv2.INTER_AREA)
    am = cv2.resize(alpha, (sm.shape[1], sm.shape[0]), interpolation=cv2.INTER_AREA)
    oy, ox = (size - sm.shape[0]) // 2, (size - sm.shape[1]) // 2
    big[oy:oy + sm.shape[0], ox:ox + sm.shape[1]] = sm
    bal[oy:oy + sm.shape[0], ox:ox + sm.shape[1]] = am
    rot = cv2.getRotationMatrix2D((size / 2, size / 2), ang, 1.0)
    big = cv2.warpAffine(big, rot, (size, size))
    bal = cv2.warpAffine(bal, rot, (size, size))
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    grass = cv2.inRange(hsv, vicspike.GRASS_LO, vicspike.GRASS_HI)
    H, W = frame.shape[:2]
    for _ in range(60):
        x = rng.randrange(size, W - size)
        y = rng.randrange(max(size, vicspike.HUD_TOP + size), min(H - size, vicspike.HUD_BOTTOM - size))
        if (grass[y - size:y + size, x - size:x + size] > 0).mean() >= 0.4:
            break
    else:
        return None
    out = frame.astype(np.float32)
    y0, x0 = y - size // 2, x - size // 2
    a = bal[..., None]
    out[y0:y0 + size, x0:x0 + size] = (out[y0:y0 + size, x0:x0 + size] * (1 - a)
                                       + big * gain * a)
    # through JPEG q70 again, as the hunt keeps its frames (run_farm `keep`)
    ok, jpg = cv2.imencode(".jpg", np.clip(out, 0, 255).astype(np.uint8),
                           [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    return cv2.imdecode(jpg, cv2.IMREAD_COLOR), (x, y, int(max(h0, w0) * s))


def colour_rule(frame) -> list[tuple[int, int]]:
    """ROADMAP Q3b's first rule (2026-10-21): colour + tall and thin."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (85, 0, 150), (110, 120, 255))
    n, _lab, st, c = cv2.connectedComponentsWithStats(mask)
    return [(int(c[i][0]), int(c[i][1])) for i in range(1, n)
            if st[i, 4] >= 60 and st[i, 3] >= 2.5 * st[i, 2]]


class Sift:
    def __init__(self, spr):
        self.sift = cv2.SIFT_create()
        g = cv2.cvtColor(cv2.copyMakeBorder(spr, 20, 20, 20, 20, cv2.BORDER_REFLECT),
                         cv2.COLOR_BGR2GRAY)
        self.kp, self.des = self.sift.detectAndCompute(g, None)
        self.bf = cv2.BFMatcher()

    def __call__(self, frame) -> list[tuple[int, int]]:
        if self.des is None or len(self.des) < 2:
            return []
        kp, des = self.sift.detectAndCompute(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), None)
        if des is None or len(des) < 2:
            return []
        pts = []
        for m in self.bf.knnMatch(self.des, des, k=2):
            if len(m) == 2 and m[0].distance < 0.75 * m[1].distance:
                pts.append(kp[m[0].trainIdx].pt)
        out = []
        for p in pts:
            near = [q for q in pts if abs(q[0] - p[0]) < 40 and abs(q[1] - p[1]) < 40]
            if len(near) >= 4:
                out.append((int(p[0]), int(p[1])))
        return out[:1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--var", default=str(pathlib.Path.home() / "Hivemind" / "var"))
    ap.add_argument("--sift", type=int, default=0, help="also score SIFT on this many frames")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--crops", default="", help="write every false alarm's crop here")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    var = pathlib.Path(a.var).expanduser()
    ref = cv2.imread(str(var / REF))
    if ref is None:
        print(f"no {var / REF}")
        return 1
    spr, alpha = sprite(ref)
    negs = negatives(var)
    if a.limit:
        negs = negs[:a.limit]
    rng = random.Random(a.seed)
    dets = {"colour (Q3b)": lambda f: colour_rule(f),
            "vicspike": lambda f: [(s.x, s.y) for s in vicspike.find(f)]}
    if a.sift:
        dets["sift"] = Sift(spr)
    stats = {k: {"fp_frames": 0, "fp_hits": 0, "tp": 0, "pos": 0, "neg": 0,
                 "by_size": {}} for k in dets}
    for k, det in dets.items():
        stats[k]["owner_frame"] = bool(det(ref))
        found = 0
        for f, x, y in SPIKES:
            img = cv2.imread(str(var / f))
            found += img is not None and any(np.hypot(hx - x, hy - y) <= REAL_NEAR
                                             for hx, hy in det(img))
        stats[k]["real"] = f"{found}/{len(SPIKES)}"
    for j, path in enumerate(negs):
        frame = cv2.imread(str(path))
        if frame is None:
            continue
        pasted = paste(frame, spr, alpha, rng)
        for k, det in dets.items():
            if k == "sift" and j >= a.sift:
                continue
            st = stats[k]
            hits = det(frame)
            st["neg"] += 1
            st["fp_hits"] += len(hits)
            if hits:
                st["fp_frames"] += 1
                if a.crops and k == "vicspike":
                    for s in vicspike.find(frame):
                        vicspike.keep_crop(frame, s, a.crops, f"{path.parent.name}-{path.stem}")
            if pasted is None:
                continue
            img, (x, y, length) = pasted
            # within 3/4 of its length of its middle: a base or a centre
            got = any(np.hypot(hx - x, hy - y) <= max(15, 0.75 * length) for hx, hy in det(img))
            bucket = "<40px" if length < 40 else "40-80px" if length < 80 else ">=80px"
            b = st["by_size"].setdefault(bucket, [0, 0])
            b[0] += got
            b[1] += 1
            st["tp"] += got
            st["pos"] += 1
    print(f"{len(negs)} hunt and night-route frames (negatives), the same with the owner's spike pasted in "
          f"(positives), seed {a.seed}")
    for k, st in stats.items():
        neg, pos = max(1, st["neg"]), max(1, st["pos"])
        rec = st["tp"] / pos
        fpr = st["fp_frames"] / neg
        prec = st["tp"] / max(1, st["tp"] + st["fp_frames"])
        sizes = ", ".join(f"{b} {v[0]}/{v[1]}" for b, v in sorted(st["by_size"].items()))
        print(f"  {k:13s} recall {rec:.3f} ({st['tp']}/{st['pos']})  false-alarm frames "
              f"{fpr:.3f} ({st['fp_frames']}/{st['neg']}, {st['fp_hits']} hits)  precision "
              f"{prec:.3f} (1:1)  owner's frame {'HIT' if st['owner_frame'] else 'missed'}  "
              f"our real spikes {st['real']}  "
              f"[{sizes}]")
    print(json.dumps({k: {kk: vv for kk, vv in st.items()} for k, st in stats.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
