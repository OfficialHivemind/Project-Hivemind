#!/usr/bin/env python3
"""Sheets for boxing tokens by eye on whole frames (the tokdet-v2 eye test).

    ./scripts/tokdet_eyesheet.py FRAMES.json OUTDIR --models tokdet.npz,coins.npz[,...]
    ./scripts/tokdet_eyesheet.py --new OUTDIR tokdet.npz [FLOOR]  # spots a later model adds

For each frame: OUTDIR/NN.jpg, the world box at 0.6x with a grid every 100
frame px (labels in frame px) and every candidate any of the models reports
at confidence >= 0.25, merged and numbered; OUTDIR/NN-crops.jpg, each
candidate at 112 px with its number. The grader writes OUTDIR/grades.json:
{"NN": {"cands": {"<candidate index>": kind}, "extra": [[cx, cy, side, kind]]}}
in frame px -- every coin on the frame, candidate or not, so the frame is
labelled WHOLE; kind "?" is a spot that could not be settled (left out both
ways). scripts/train_tokdet.py score reads it (`eye_frames`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import cv2                                                      # noqa: E402
import numpy as np                                              # noqa: E402

from hivemind.vision import coins, tokdet as T                  # noqa: E402

LIVE = Path.home() / "Hivemind"


def candidates(img, models, floor=0.25):
    found = []
    for m in models:
        if isinstance(m, coins.Model):
            found += [d[:4] for d in coins.look(img, m=m)]
        else:
            found += [d[:4] for d in T.run(m, img)]
    return coins.merge([d for d in found if d[3] >= floor * coins.LOGIT_FULL])


def new_candidates(folder: Path, model: str, floor: float = 0.25) -> int:
    """--new FOLDER MODEL.npz: a model trained after the sheets were made may
    report spots no sheet candidate covered. Each such spot at >= 0.25 is cut
    into FOLDER/new.jpg (labelled "frame:n") and listed in new.json, to be
    graded into that frame's "extra". FLOOR (default 0.25) grades only the
    spots at or over that confidence."""
    import train_tokdet
    net = train_tokdet.onnx_net(train_tokdet.load_params(model))
    index = json.loads((folder / "index.json").read_text())
    grades = json.loads((folder / "grades.json").read_text())
    tiles, listed = [], {}
    for key, row in index.items():
        img = cv2.imread(str(LIVE / row["path"]))
        known = [c[:3] for c in row["candidates"]] + [e[:3] for e in grades.get(key, {}).get("extra", ())]
        for cx, cy, side, *_ in candidates(img, [net], floor):
            if any(abs(cx - k[0]) < k[2] * 0.75 and abs(cy - k[1]) < k[2] * 0.75 for k in known):
                continue
            n = len(listed.setdefault(key, []))
            listed[key].append([round(cx), round(cy), round(side)])
            half = side * 0.75
            crop = img[max(0, int(cy - half)):int(cy + half), max(0, int(cx - half)):int(cx + half)]
            tile = cv2.resize(crop, (112, 112)) if crop.size else np.zeros((112, 112, 3), np.uint8)
            cv2.putText(tile, f"{key}:{n}", (3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            tiles.append(tile)
    if tiles:
        rows = [np.hstack(tiles[i:i + 8] + [np.zeros_like(tiles[0])] * (8 - len(tiles[i:i + 8])))
                for i in range(0, len(tiles), 8)]
        cv2.imwrite(str(folder / "new.jpg"), np.vstack(rows))
    (folder / "new.json").write_text(json.dumps(listed, indent=1))
    print(f"{len(tiles)} new spots in {folder}")
    return 0


def main() -> int:
    if sys.argv[1] == "--new":
        return new_candidates(Path(sys.argv[2]), sys.argv[3],
                              float(sys.argv[4]) if len(sys.argv) > 4 else 0.25)
    frames = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    models = []
    for p in sys.argv[sys.argv.index("--models") + 1].split(","):
        if p.endswith(".npz") and "tokdet" in Path(p).name:
            import train_tokdet
            models.append(train_tokdet.onnx_net(train_tokdet.load_params(p)))
        else:
            models.append(coins.Model.load(Path(p)))
    index = {}
    for k, rel in enumerate(frames):
        img = cv2.imread(str(LIVE / rel))
        h, w = img.shape[:2]
        x0, y0, x1, y1 = coins.world_box(w, h)
        cands = candidates(img, models)
        s = 0.6
        view = cv2.resize(img[y0:y1, x0:x1], None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        for gx in range((x0 // 100 + 1) * 100, x1, 100):
            X = int((gx - x0) * s)
            cv2.line(view, (X, 0), (X, view.shape[0]), (255, 255, 255), 1)
            cv2.putText(view, str(gx), (X + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
        for gy in range((y0 // 100 + 1) * 100, y1, 100):
            Y = int((gy - y0) * s)
            cv2.line(view, (0, Y), (view.shape[1], Y), (255, 255, 255), 1)
            cv2.putText(view, str(gy), (2, Y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
        tiles = []
        for n, (cx, cy, side, _z) in enumerate(cands):
            a = (int((cx - side / 2 - x0) * s), int((cy - side / 2 - y0) * s))
            b = (int((cx + side / 2 - x0) * s), int((cy + side / 2 - y0) * s))
            cv2.rectangle(view, a, b, (0, 0, 255), 2)
            cv2.putText(view, str(n), (a[0], a[1] - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            half = side * 0.75
            crop = img[max(0, int(cy - half)):int(cy + half), max(0, int(cx - half)):int(cx + half)]
            tile = cv2.resize(crop, (112, 112)) if crop.size else np.zeros((112, 112, 3), np.uint8)
            cv2.putText(tile, str(n), (3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            tiles.append(tile)
        cv2.imwrite(str(out / f"{k:02d}.jpg"), view, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if tiles:
            rows = [np.hstack(tiles[i:i + 8] + [np.zeros_like(tiles[0])] * (8 - len(tiles[i:i + 8])))
                    for i in range(0, len(tiles), 8)]
            cv2.imwrite(str(out / f"{k:02d}-crops.jpg"), np.vstack(rows))
        index[f"{k:02d}"] = {"path": rel, "candidates": [[round(v, 1) for v in c] for c in cands]}
    (out / "index.json").write_text(json.dumps(index, indent=1))
    print(f"wrote {len(frames)} sheets into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
