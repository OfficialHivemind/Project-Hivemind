#!/usr/bin/env python3
"""Cut the bear-morph templates (vision/buffs `bear`, DESIGN 8dx) out of the
saved route and homing frames.

WHY. Natro's movespeed formula adds four to the base for a bear morph
(lib/Walk.ahk, `(bear ? 4 : 0)`), and from attempt 362 on this account's bar
shows one often: Mushroom's walks home that stopped at the fence short of
the hives walked their sideways leg under one. Reading it needs the icons.

HOW, in two passes:
  1. SEEDS: the icons named below, read by eye on their bars, one median per
     morph: the brown bear on every leg of attempt 410's walk home from
     Mushroom (01:19:11-01:19:30), the black bear on 410's first six homing
     looks after it, the polar bear on 407's walk home (00:02:18, 00:02:27),
     the panda on 364's walk to Riley Bee (22:48:35-22:48:39); and, added
     2026-10-14, the two rare morphs a gifted Bear Bee gives (BSS wiki: Mother
     or Science, a 20% chance), first seen on attempt 850: the Science Bear
     (golden fur, grey goggles) on 866's eight homing looks at 03:16, the
     Mother Bear (cream, pink cheeks) on 894's last three at 06:48.
  2. EVERY INSTANCE: each saved frame of attempts FIRST..LAST-1 is matched
     along its bar (TM_CCOEFF_NORMED, colour, buffs.BEAR_ROWS/BEAR_COLS);
     where a seed scores INSTANCE_MIN, the 38 px there is an instance of that
     morph. A morph's template is the per-pixel 90th percentile of its
     instances: the undrained look, because a drained row is the same face
     darkened to 0.84-0.94 (see vision/buffs), so the bear's drain line can
     be measured against it. Attempts from LAST on are left out, so they can
     test the templates (DESIGN 8dx has the held-out figures). The rare two
     are cut from attempts RARE_FIRST..RARE_LAST-1 and tested on the rest.

    ./scripts/build_bear_templates.py --var /path/to/Hivemind/var
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.vision import buffs                                # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data/templates/buffs"

# (frame under var/, bar slot) -- read by eye, 2026-09-26
_MUSH410 = ("011911-natro_home_mushroom-00-start", "011913-natro_home_mushroom-01-walk-w54",
            "011916-natro_home_mushroom-02-walk-a108", "011916-natro_home_mushroom-03-camera-left",
            "011916-natro_home_mushroom-04-camera-left", "011917-natro_home_mushroom-05-camera-left",
            "011917-natro_home_mushroom-06-camera-left", "011919-natro_home_mushroom-07-walk-a46",
            "011929-natro_home_mushroom-08-walk-w288", "011930-natro_home_mushroom-09.01-walk-s10")
SEEDS = {
    "brown": [(f"routes/attempt-410/{n}.jpg", 5 if n.endswith("00-start") else 4)
              for n in _MUSH410],
    "black": [(f"homing/attempt-410/{n}.jpg", 4) for n in (
        "look00-turn-left-y031404-b-0641", "look01-tap-back-and-walk-y011181-b-0168",
        "look02-step-y084287-b+0054", "look03-step-y190406-b+0333",
        "look04-at-row-y328930-b+0216", "look05-row-no-d-y303829-b+0226")],
    "polar": [("routes/attempt-407/000218-natro_home_mushroom-00-start.jpg", 4),
              ("routes/attempt-407/000227-natro_home_mushroom-07-walk-a46.jpg", 3)],
    "panda": [(f"routes/attempt-364/{n}.jpg", 4) for n in (
        "224835-natro_out_riley_bee-00-start", "224836-natro_out_riley_bee-01-walk-w20",
        "224838-natro_out_riley_bee-02-hive_offset-d", "224839-natro_out_riley_bee-04-pause-")],
    "science": [(f"homing/attempt-866/{n}.jpg", 6) for n in (
        "look00-scan-y000000-b+0000", "look01-scan-y000000-b+0000",
        "look02-turn-right-y095755-b+0687", "look03-step-y163775-b+0347",
        "look04-turn-right-y334617-b+0455", "look05-step-y425638-b+0073",
        "look06-step-y823801-b-0013", "look07-flat-wall-y819692-b-0029")],
    "mother": [(f"homing/attempt-894/{n}.jpg", 6) for n in (
        "look05-scan-y001763-b-0412", "look06-scan-y000000-b+0000",
        "look07-scan-y000000-b+0000")],
}
# MEASURED with the seeds over every saved frame: bear faces score 0.85 or
# more, nothing else over 0.69 (vision/buffs BEAR_MIN_SCORE).
INSTANCE_MIN = 0.85
FIRST, LAST = 362, 420
RARE = ("science", "mother")
RARE_FIRST, RARE_LAST = 840, 960


def bar(path: pathlib.Path):
    img = cv2.imread(str(path))
    if img is None or img.shape[0] < buffs.BAR_BOTTOM or img.shape[1] < buffs.ICON * buffs.MAX_SLOTS:
        return None
    return np.ascontiguousarray(img[buffs.BAR_TOP:buffs.BAR_BOTTOM,
                                    :buffs.ICON * buffs.MAX_SLOTS])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--var", default=str(ROOT / "var"))
    args = ap.parse_args()
    var = pathlib.Path(args.var)
    r0, r1 = buffs.BEAR_ROWS
    c0, c1 = buffs.BEAR_COLS
    seeds = {}
    for kind, picks in SEEDS.items():
        icons = []
        for rel, slot in picks:
            strip = bar(var / rel)
            if strip is None:
                print(f"missing seed frame {rel}; nothing written")
                return 1
            icons.append(strip[:, slot * buffs.ICON:(slot + 1) * buffs.ICON])
        seeds[kind] = np.ascontiguousarray(
            np.median(np.stack(icons), axis=0).astype(np.uint8)[r0:r1, c0:c1])
    found: dict[str, list] = {k: [] for k in SEEDS}
    attempt = re.compile(r"attempt-(\d+)$")
    for folder in sorted(list((var / "routes").glob("attempt-*"))
                         + list((var / "homing").glob("attempt-*"))):
        m = attempt.search(folder.name)
        n = int(m.group(1)) if m else -1
        if not (FIRST <= n < LAST or RARE_FIRST <= n < RARE_LAST):
            continue
        for path in sorted(folder.glob("*.jpg")):
            strip = bar(path)
            if strip is None:
                continue
            best = None
            for kind, seed in seeds.items():
                res = cv2.matchTemplate(np.ascontiguousarray(strip[r0:r1]), seed,
                                        cv2.TM_CCOEFF_NORMED)[0]
                x = int(np.argmax(res))
                if best is None or res[x] > best[0]:
                    best = (float(res[x]), kind, x - c0)
            score, kind, left = best
            first, last = (RARE_FIRST, RARE_LAST) if kind in RARE else (FIRST, LAST)
            if (score >= INSTANCE_MIN and 0 <= left <= strip.shape[1] - buffs.ICON
                    and first <= n < last):
                found[kind].append(strip[:, left:left + buffs.ICON].copy())
    OUT.mkdir(parents=True, exist_ok=True)
    for kind, icons in found.items():
        if not icons:
            print(f"{kind}: no instances; not written")
            continue
        template = np.percentile(np.stack(icons), 90, axis=0).round().astype(np.uint8)
        cv2.imwrite(str(OUT / f"bear_{kind}.png"), template)
        first, last = (RARE_FIRST, RARE_LAST) if kind in RARE else (FIRST, LAST)
        print(f"{kind}: {len(icons)} instances on attempts {first}-{last - 1} -> bear_{kind}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
