#!/usr/bin/env python3
"""Turn the loot captures (var/school-loot, brain/lootcapture) into labelled
loot crops -- only where the label cannot belong to another coin.

    ./scripts/label_loot.py                    # label the live captures, print the tally
    ./scripts/label_loot.py --backfill         # first rebuild captures from old frames
    ./scripts/label_loot.py --sheet 48         # plus an eye-check sheet

--backfill makes captures from what var/ already holds: every black-box
window (var/incidents/*, frames with their times) that covers a drop read of
var/mob_drops.jsonl, cut by brain/lootcapture's own writer, with the feed
read off the window's own frames by tesseract (vision/feed). Written under
--out/backfill, never into var/.

THE RULE (brain/lootcapture.label): the read brought exactly one new credit,
a drop the mob table names, the buff bar shows no pickup of its own, and
exactly one sure coin (vision/tokens.detect) was beside the character on two
looks in a row, the later its last, with none there after.

Writes under --out (default $HIVEMIND_WORK/datasets/loot): manifest.jsonl
in scripts/train_token_types' hand-row shape ("src" + "box", "label", "split"),
<split>/<label>/<id>.png previews and stats.json. SPLIT BY NIGHT (the
capture's date, sha1 as build_token_dataset), so a night never teaches and
tests. It never touches the game; run it niced.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import hashlib
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hivemind.brain import lootcapture as lc  # noqa: E402

VAR = Path.home() / "Hivemind" / "var"
OUT_PX = 64
FRAME_T = re.compile(r"_t\+([\d.]+)s\.jpg$")
# The read before: whereami reads every ~3 s (lootcapture LOOKBACK_S).
READ_EVERY_S = 3.0


def split_of(run: str) -> str:
    h = int(hashlib.sha1(run.encode()).hexdigest(), 16) % 100
    return "train" if h < 70 else "val" if h < 85 else "test"


# ---- backfill -------------------------------------------------------------------
def drop_reads(path: Path) -> list[tuple[float, list]]:
    """(read time, [(mob, item, amount)]) of var/mob_drops.jsonl, the rows of
    one read (written together, within 0.05 s) joined."""
    reads: list = []
    for line in path.open(encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if reads and r["at"] - reads[-1][0] < 0.05:
            reads[-1][1].append((r["mob"], r["item"], r["amount"]))
        else:
            reads.append((r["at"], [(r["mob"], r["item"], r["amount"])]))
    return reads


def window_frames(folder: Path) -> list[tuple[float, Path]]:
    """(wall time, file) of an incident window: its last frame is reason.txt's
    write (IncidentRecorder.save), the rest by their t+ offsets."""
    files = [(float(m.group(1)), folder / f) for f in os.listdir(folder)
             if (m := FRAME_T.search(f))]
    if not files:
        return []
    end = (folder / "reason.txt").stat().st_mtime
    last = max(t for t, _ in files)
    return sorted((end - (last - t), p) for t, p in files)


def feed_text(path: Path) -> str:
    from hivemind.vision import feed
    img = cv2.imread(str(path))
    strip = feed.strip(img) if img is not None else None
    return feed.read_text(strip) if strip is not None else ""


def backfill(var: Path, out: Path) -> int:
    reads = drop_reads(var / "mob_drops.jsonl")
    times = [t for t, _ in reads]
    made = 0
    for folder in sorted((var / "incidents").iterdir()):
        try:
            frames = window_frames(folder)
        except OSError:
            continue
        if not frames:
            continue
        t0, t1 = frames[0][0], frames[-1][0]
        a, b = bisect.bisect_left(times, t0 + lc.LOOKBACK_S), bisect.bisect_right(times, t1 + 0.3)
        for read_at, drops in reads[a:b]:
            if all(item in lc.SKIP for _m, item, _n in drops):
                continue
            ft = [t for t, _ in frames]

            def at_or_before(t):
                i = bisect.bisect_right(ft, t) - 1
                return frames[i][1] if i >= 0 else None
            now = {"t": read_at - READ_EVERY_S}
            ring = _Ring([(t, p.read_bytes()) for t, p in frames
                          if read_at - lc.LOOKBACK_S - 0.1 <= t <= read_at])
            cap = lc.LootCapture(out, ring=ring, clock=lambda: now["t"],
                                 max_captures=10 ** 6, max_bytes=10 ** 12, allowed=lambda _p: True)
            before = at_or_before(read_at - READ_EVERY_S)
            if before is not None:
                cap.heard(feed_text(before))
            now["t"] = read_at
            cap.heard(feed_text(at_or_before(read_at)))
            got = None
            for mob, item, amount in drops:
                got = cap.dropped(mob, item, amount) or got
            if got is not None:
                meta = json.loads((got / "meta.json").read_text(encoding="utf-8"))
                meta.update(at=read_at, window=folder.name)
                (got / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
                made += 1
    return made


class _Ring:
    def __init__(self, items):
        self.items = items

    def between(self, t0, t1):
        return [(t, d) for t, d in self.items if t0 <= t <= t1]


# ---- labelling -----------------------------------------------------------------------
def looks_of(folder: Path, meta: dict) -> list:
    """[(frame name, dt, [(x, y, side, confidence)])] in crop pixels: each crop
    put back on a black frame where it was cut, so the detector sees it as live."""
    from hivemind.vision import tokens
    w, h = meta["frame_wh"]
    x0, y0, side = meta["crop"]
    out = []
    for name, dt in meta.get("frames") or ():
        img = cv2.imread(str(folder / name))
        if img is None:
            continue
        canvas = np.zeros((h, w, 3), np.uint8)
        cx0, cy0 = max(0, x0), max(0, y0)
        cx1, cy1 = min(w, x0 + side), min(h, y0 + side)
        canvas[cy0:cy1, cx0:cx1] = img[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
        seen = [(s.x - x0, s.y - y0, s.box[2], s.confidence) for s in tokens.detect(canvas)
                if cx0 <= s.x < cx1 and cy0 <= s.y < cy1]
        out.append((name, dt, seen))
    return out


def preview(src: Path, box) -> np.ndarray | None:
    img = cv2.imread(str(src))
    if img is None:
        return None
    x0, y0, x1, y1 = [int(v) for v in box]
    cx, cy, h = (x0 + x1) // 2, (y0 + y1) // 2, max(8, max(x1 - x0, y1 - y0) // 2)
    pad = cv2.copyMakeBorder(img, h, h, h, h, cv2.BORDER_CONSTANT)
    crop = pad[cy:cy + 2 * h, cx:cx + 2 * h]
    return cv2.resize(crop, (OUT_PX, OUT_PX), interpolation=cv2.INTER_AREA) if crop.size else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--var", type=Path, default=VAR)
    ap.add_argument("--out", type=Path, default=Path(os.environ.get("HIVEMIND_WORK") or Path.home() / ".cache/hivemind-dev") / "datasets/loot")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--sheet", type=int, default=0, help="crops on an eye-check sheet")
    ap.add_argument("--seed", type=int, default=2027)
    args = ap.parse_args(argv)
    if args.out.resolve().is_relative_to(args.var.resolve()):
        print("--out must not be inside --var", file=sys.stderr)
        return 2
    if args.backfill:
        print(f"backfill: {backfill(args.var, args.out / 'backfill')} capture(s) made", flush=True)
    known = lc.known_items()
    folders = sorted(p for root in (args.var / lc.DIR, args.out / "backfill") if root.is_dir()
                     for p in root.iterdir() if (p / "meta.json").is_file())
    why_not: collections.Counter = collections.Counter()
    labels: collections.Counter = collections.Counter()
    rows: list[dict] = []
    for folder in folders:
        try:
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            name, why, pick = lc.label(meta, looks_of(folder, meta), known,
                                       cv2.imread(str(folder / "bar_first.png")),
                                       cv2.imread(str(folder / "bar_last.png")))
        except (OSError, ValueError, KeyError) as exc:
            why_not[f"unreadable: {type(exc).__name__}"] += 1
            continue
        if name is None:
            why_not[why] += 1
            continue
        labels[name] += 1
        frame, box = pick
        run = "night-" + time.strftime("%Y%m%d", time.localtime(meta["at"]))
        rows.append({"id": f"loot-{folder.parent.name}-{folder.name}", "run": run,
                     "split": split_of(run), "label": name, "source": "loot",
                     "confidence": 1.0, "evidence": why, "capture": str(folder),
                     "src": str(folder / frame), "box": box,
                     "dt": dict((n, d) for n, d in meta["frames"]).get(frame),
                     "drops": meta.get("drops")})
    for r in rows:
        crop = preview(Path(r["src"]), r["box"])
        if crop is None:
            continue
        rel = Path(r["split"]) / r["label"] / f"{r['id']}.png"
        (args.out / rel).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.out / rel), crop)
        r["file"] = str(rel)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "manifest.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    stats = {"captures": len(folders), "labelled": sum(labels.values()),
             "labels": dict(labels.most_common()), "rejected": dict(why_not.most_common()),
             "splits": {s: dict(collections.Counter(r["label"] for r in rows if r["split"] == s))
                        for s in ("train", "val", "test")}}
    (args.out / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(json.dumps(stats, indent=1))
    if args.sheet and rows:
        pick = random.Random(args.seed).sample(rows, min(args.sheet, len(rows)))
        tiles = []
        for r in pick:
            img = cv2.imread(r["src"])
            x0, y0, x1, y1 = r["box"]
            cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 255), 2)
            cv2.putText(img, r["label"][:18], (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            tiles.append(cv2.resize(img, (256, 256)))
        while len(tiles) % 4:
            tiles.append(np.zeros((256, 256, 3), np.uint8))
        sheet = np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)])
        cv2.imwrite(str(args.out / "sheet.jpg"), sheet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
