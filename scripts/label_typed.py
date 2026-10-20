#!/usr/bin/env python3
"""Turn the typed captures (var/school-typed, brain/typedcapture) into
labelled token crops -- only where the label cannot belong to another token.

    ./scripts/label_typed.py                       # label everything, print the tally
    ./scripts/label_typed.py --sheet 48            # plus an eye-check sheet of 48 crops

Reads --captures (default ~/Hivemind/var/school-typed) and never writes there.
Writes under --out (default $HIVEMIND_WORK/datasets/tokens-typed-capture):
<split>/<label>/<id>.png (64 px previews), icons/<id>.png (the buff icon that
appeared, for naming "buff_unnamed" ones once by eye), manifest.jsonl and
stats.json. A manifest row has scripts/train_token_types' hand-row shape:
"src" (the capture image) and "box" (x0, y0, x1, y1 in that image).

THE RULE (brain/typedcapture.label): the chase reached its token, no other
trusted sighting lay near the walk, and exactly one change happened between
the read before the chase and FEED_GRACE_S after it -- one new feed credit,
or one buff icon that appeared or stacked, or a Haste refill, or a honey lump
the feed did not credit. A feed credit must name a field (not Cub Buddy,
Leaves, a Sprout or a mob), be on no read of the 9 s before the chase, come
before the next chase began, and the chase before must not have reached its
token in the 6 s before. Everything else is counted in stats.json by why.

EVERY FRAME OF THE CAPTURE, IF IT LINES UP. decide.jpg is the frame the box
was read on. The black-box frames of the 0.5 s before it are labelled too
when the box's patch is found again within ALIGN_PX at ALIGN_NCC (the
character may still be moving at the end of a pass); the box moves with it.
A flat patch or a copy of the deciding frame adds no row.

SPLIT BY RUN, by scripts/build_token_dataset's sha1 rule on "attempt-<n>",
so a run's captures never teach and test.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hivemind.brain import typedcapture as tc  # noqa: E402

ALIGN_PX = 40
# ponytail: set by eye on 12 replayed captures, where 0.7 took a dark flat
# patch for a lit field; a patch flatter than ALIGN_STD finds anything.
ALIGN_NCC = 0.85
ALIGN_STD = 10.0
COIN_PX = 112               # a box for a target with none: the median coin (brain/school)
OUT_PX = 64


def split_of(run: str) -> str:
    """scripts/build_token_dataset.split_of: 70 / 15 / 15 by sha1 of the run."""
    h = int(hashlib.sha1(run.encode()).hexdigest(), 16) % 100
    return "train" if h < 70 else "val" if h < 85 else "test"


def box_in_crop(meta: dict) -> list[int]:
    """(x0, y0, x1, y1) of the chased token in the capture's crop pixels."""
    x0, y0, _side = meta["crop"]
    if meta.get("box"):
        bx, by, bw, bh = meta["box"]
        return [bx - x0, by - y0, bx + bw - x0, by + bh - y0]
    px, py = meta["point"]
    h = COIN_PX // 2
    return [px - x0 - h, py - y0 - h, px - x0 + h, py - y0 + h]


def aligned(decide, frame, box) -> list[int] | None:
    """The box moved onto `frame` by finding decide's patch there again."""
    x0, y0, x1, y1 = [int(v) for v in box]
    side = decide.shape[0]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(side, x1), min(side, y1)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return None
    patch = decide[y0:y1, x0:x1]
    if float(patch.std()) < ALIGN_STD or float(np.abs(frame.astype(np.int16) - decide).mean()) < 1.0:
        return None                     # flat, or the deciding frame again
    sx0, sy0 = max(0, x0 - ALIGN_PX), max(0, y0 - ALIGN_PX)
    area = frame[sy0:min(side, y1 + ALIGN_PX), sx0:min(side, x1 + ALIGN_PX)]
    if area.shape[0] < patch.shape[0] or area.shape[1] < patch.shape[1]:
        return None
    score = cv2.matchTemplate(area, patch, cv2.TM_CCOEFF_NORMED)
    _lo, best, _at, (mx, my) = cv2.minMaxLoc(score)
    if best < ALIGN_NCC:
        return None
    dx, dy = sx0 + mx - x0, sy0 + my - y0
    return [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]


def label_capture(folder: Path):
    """(label, why, changes, meta) of one capture folder."""
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    before = cv2.imread(str(folder / "bar_before.png"))
    after = cv2.imread(str(folder / "bar_after.png"))
    name, why, changes = tc.label(meta, before, after)
    return name, why, changes, meta


def rows_of(folder: Path, name: str, meta: dict, why: str) -> list[dict]:
    """One manifest row per frame of the capture the box holds on."""
    decide = cv2.imread(str(folder / "decide.jpg"))
    if decide is None:
        return []
    box = box_in_crop(meta)
    run = f"attempt-{meta.get('attempt')}"
    common = {"run": run, "label": name, "source": "capture", "confidence": 1.0,
              "evidence": why, "capture": folder.name, "kind_brain": meta.get("kind"),
              "split": split_of(run)}
    rows = [{**common, "id": f"cap-{folder.name}-decide", "src": str(folder / "decide.jpg"),
             "box": box, "dt": 0.0}]
    for file, dt in meta.get("frames") or ():
        img = cv2.imread(str(folder / file))
        moved = aligned(decide, img, box) if img is not None else None
        if moved is not None:
            rows.append({**common, "id": f"cap-{folder.name}-{Path(file).stem}",
                         "src": str(folder / file), "box": moved, "dt": dt})
    return rows


def preview(src: str, box) -> np.ndarray | None:
    img = cv2.imread(src)
    if img is None:
        return None
    x0, y0, x1, y1 = [int(v) for v in box]
    cx, cy, h = (x0 + x1) // 2, (y0 + y1) // 2, max(x1 - x0, y1 - y0) // 2
    pad = cv2.copyMakeBorder(img, h, h, h, h, cv2.BORDER_CONSTANT)
    crop = pad[cy:cy + 2 * h, cx:cx + 2 * h]
    return cv2.resize(crop, (OUT_PX, OUT_PX), interpolation=cv2.INTER_AREA) if crop.size else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--captures", type=Path, default=Path.home() / "Hivemind/var" / tc.DIR)
    ap.add_argument("--out", type=Path,
                    default=Path(os.environ.get("HIVEMIND_WORK") or Path.home() / ".cache/hivemind-dev") / "datasets/tokens-typed-capture")
    ap.add_argument("--sheet", type=int, default=0, help="crops on an eye-check sheet")
    ap.add_argument("--seed", type=int, default=2027)
    args = ap.parse_args(argv)
    if args.out.resolve().is_relative_to(args.captures.resolve()):
        print("--out must not be inside --captures", file=sys.stderr)
        return 2
    folders = sorted(p for p in args.captures.glob("*") if (p / "meta.json").is_file())
    why_not: collections.Counter = collections.Counter()
    labels: collections.Counter = collections.Counter()
    rows: list[dict] = []
    for folder in folders:
        try:
            name, why, changes, meta = label_capture(folder)
        except (OSError, ValueError, KeyError) as exc:
            why_not[f"unreadable: {type(exc).__name__}"] += 1
            continue
        if name is None:
            why_not[why] += 1
            continue
        got = rows_of(folder, name, meta, why)
        labels[name] += 1
        for r in got:
            r["changes"] = changes
        rows += got
        if name == "buff_unnamed":
            after = cv2.imread(str(folder / "bar_after.png"))
            bar, _clear = tc.bar_changes(cv2.imread(str(folder / "bar_before.png")), after)
            slot = next((s for _kind, s, n in bar if n == name), None)
            if after is not None and slot is not None:
                (args.out / "icons").mkdir(parents=True, exist_ok=True)
                icon = tc.occupied(after)[slot]
                cv2.imwrite(str(args.out / "icons" / f"{folder.name}.png"), icon)
    for r in rows:
        crop = preview(r["src"], r["box"])
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
    stats = {"captures": len(folders), "labelled": sum(labels.values()), "rows": len(rows),
             "labels": dict(labels.most_common()), "rejected": dict(why_not.most_common()),
             "splits": dict(collections.Counter(r["split"] for r in rows))}
    (args.out / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(json.dumps(stats, indent=1))
    if args.sheet and rows:
        decide = [r for r in rows if r["id"].endswith("-decide") and "file" in r]
        pick = random.Random(args.seed).sample(decide, min(args.sheet, len(decide)))
        tiles = [cv2.putText(cv2.resize(cv2.imread(str(args.out / r["file"])), (128, 128)),
                             r["label"][:14], (2, 124), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                             (255, 255, 255), 1) for r in pick]
        while len(tiles) % 8:
            tiles.append(np.zeros((128, 128, 3), np.uint8))
        sheet = np.vstack([np.hstack(tiles[i:i + 8]) for i in range(0, len(tiles), 8)])
        cv2.imwrite(str(args.out / "sheet.png"), sheet)
        (args.out / "sheet.json").write_text(json.dumps([r["id"] for r in pick]), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
