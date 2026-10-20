#!/usr/bin/env python3
"""Build a TYPED token dataset from our own frames, labelled by what happened.

    ./scripts/build_token_dataset.py --cluster 40   # 1. group the chased crops by look
    (name each group once in <labeller>/names.json, from <labeller>/sheets/)
    ./scripts/build_token_dataset.py                # 2. build the dataset

Reads --home (default ~/Hivemind) and never writes there. Writes under --out
(default $HIVEMIND_WORK/datasets/tokens-typed)/<hive colour>/:
<split>/<label>/<id>.png (64 px), wide/ (a copy of each self-labelled
chase's 192 px crop), manifest.jsonl (one row per crop: label, source,
confidence, evidence, run, split, src, point) and stats.json.

WHERE THE TYPE COMES FROM. brain/school keeps, for every chase, the 192 px
crop round the chased point and what happened next: the HUD's verdict (honey
lump, Haste gained or refilled, a buff's stacks rising, a pollen lump) and
the sight verdict (the target was gone on arrival). MEASURED 2026-10-26 on
the 3,687 wide crops: the HUD verdict does NOT type the chased token. By eye
on 24 random crops per verdict, "honey" crops show blue bombs, boosts and
blueberries as often as honey coins (the walk crosses other tokens, and the
HUD cannot say which one paid); per look group the verdicts lift only 1.5-4x
over their base rate (stats.json "evidence_by_kind"). The LOOK is the strong
signal: the crops grouped by colour (`look_features`, k-means) fall into
groups that are one token kind by eye -- 18 of 40 groups at 7-10 of 10.
So a crop's label is its group's kind, named ONCE by eye (names.json, with
the share of the naming sheet that was that kind as "purity"), and it is
kept only where what happened next says a token was really there: the HUD
or the sight verdict "collected". Confidence is the purity, lowered where
the HUD verdict is one that kind does not produce (`COMPATIBLE`); labels
under MIN_CONFIDENCE are dropped.

NEGATIVES ("background"): the boxes data/models/coin_labels.json reviewed as
NOT coins (the shipped detector's false positives: bees, flowers, bubbles,
numbers), and random points of the frames labelled whole that touch no coin.
No source names a bee from a balloon, so they are one class.

HAND LABELS. coin_labels.json's sure typed coins are rows too (source
"hand"). The labeller never sees them -- groups are formed and named on the
school's crops -- so they also measure it (stats.json "labeller_vs_hand").
They are the coin detector's held-out frames (scripts/train_coins.py): a
detector trainer must leave out source "hand*" to keep its P/R comparable.

SPLIT BY RUN. A run is a school attempt or a coin_labels window, and every
crop of a run lands in one split (`split_of`), so no run teaches and tests.

HIVE COLOUR. Every frame so far is from one account, so the per-colour split
is the one folder named by --hive-colour; another account's school would be
built with its own --home and colour.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import shutil
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hivemind.brain.school import Lesson, NEVER, _legacy_verdict  # noqa: E402

WIDE = 192                  # brain/school.WIDE_CROP, centred on the chased point
WINDOW = 112                # frame px saved round a token's point: the median coin (brain/school)
OUT_PX = 64                 # saved crop side
LOOK_WINDOWS = (64, 112)    # central windows the look is described over
CLUSTER_SEED = 0
RADIUS_PCT = 75             # a crop farther from its group's centre than this percentile is not labelled
MIN_CONFIDENCE = 0.7
# What a kind's HUD verdict can be. Game logic, and MEASURED 2026-10-26 over
# the k=40 look groups of 3,687 wide crops (verdict per reached chase over
# its base rate): the haste look 3.4x haste; the blue-burst looks 1.9-3.9x
# stacks; the blue-boost looks 1.8-2.3x stacks; the honey looks 0.0x haste
# and 0.0-0.2x stacks over 517 reached chases. A verdict outside the set (a
# neighbour paid) lowers the confidence; none (sight only) a little.
COMPATIBLE = {
    "honey": {"honey"},
    "haste": {"haste"},
    "blue_boost": {"stacks"},
    "red_boost": {"stacks"},
    "black_blue_burst": {"stacks"},
}
OTHER_VERDICT = 0.75        # confidence factor: the HUD named another kind's effect
SIGHT_ONLY = 0.9            # confidence factor: only the sight verdict
SPLITS = (("train", 70), ("val", 85), ("test", 100))   # cumulative percent of runs
BACKGROUND_PER_FRAME = 4
WORLD = (0.08, 0.14, 0.93, 0.88)    # vision/coins.WORLD: the part of the frame that is the world


def split_of(run: str) -> str:
    """train / val / test, fixed per run (sha1 of its name)."""
    h = int(hashlib.sha1(run.encode()).hexdigest(), 16) % 100
    return next(name for name, upto in SPLITS if h < upto)


def evidence_class(evidence: str) -> str | None:
    """brain/school.judge's "collected" evidence as honey/haste/stacks/pollen."""
    e = evidence or ""
    if e.startswith("honey rose"):
        return "honey"
    if e.startswith(("haste ", "the Haste's square")):
        return "haste"
    if e.startswith(("the buff bar's stacks", "a buff's stacks rose", "a buff appeared")):
        return "stacks"
    if e.startswith("pollen rose"):
        return "pollen"
    return None


def window(img, x: float, y: float, side: int):
    """A side x side crop of `img` centred on (x, y), black past the edges."""
    out = np.zeros((side, side, 3), np.uint8)
    x0, y0 = int(round(x)) - side // 2, int(round(y)) - side // 2
    H, W = img.shape[:2]
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x0 + side), min(H, y0 + side)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = img[sy0:sy1, sx0:sx1, :3]
    return out


def saved(img, x, y):
    return cv2.resize(window(img, x, y, WINDOW), (OUT_PX, OUT_PX), interpolation=cv2.INTER_AREA)


def look_features(wide) -> np.ndarray:
    """Colour of the middle of a WIDE crop: per LOOK_WINDOWS square, an
    18x3x3 HSV histogram (square-rooted) and a 3x3 Lab layout."""
    out = []
    c0 = wide.shape[0] // 2
    for s in LOOK_WINDOWS:
        c = cv2.resize(wide[c0 - s // 2:c0 + s // 2, c0 - s // 2:c0 + s // 2], (32, 32),
                       interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
        h = cv2.calcHist([hsv], [0, 1, 2], None, [18, 3, 3], [0, 180, 0, 256, 0, 256]).ravel()
        out.append(np.sqrt(h / max(1.0, float(h.sum()))))
        lab = cv2.cvtColor(cv2.resize(c, (3, 3), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2LAB)
        out.append(lab.ravel() / 255.0 * 0.7)
    return np.concatenate(out).astype(np.float32)


class Labeller:
    """The look groups (centres, radii) and their names."""

    def __init__(self, centres, radii, names: dict):
        self.centres = np.asarray(centres, np.float32)
        self.radii = np.asarray(radii, np.float32)
        self.names = {int(k): v for k, v in names.items() if v and v.get("kind")}

    @classmethod
    def load(cls, folder: Path) -> "Labeller":
        z = np.load(folder / "groups.npz")
        names = json.loads((folder / "names.json").read_text(encoding="utf-8"))
        return cls(z["centres"], z["radii"], names)

    def kind(self, feat) -> tuple[int, str | None, float]:
        """(group, its kind or None, purity) of one look; kind None when the
        group is unnamed or the look sits outside its radius."""
        d = ((self.centres - feat) ** 2).sum(1)
        g = int(np.argmin(d))
        name = self.names.get(g)
        if name is None or d[g] > self.radii[g]:
            return g, None, 0.0
        return g, name["kind"], float(name.get("purity") or 1.0)


def lessons(school: Path):
    for line in (school / "lessons.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            body = json.loads(line)
        except ValueError:
            continue
        yield Lesson(**{k: body.get(k) for k in Lesson.__dataclass_fields__})


def cluster(school: Path, folder: Path, k: int) -> np.ndarray:
    """Group every wide crop by look; write groups.npz, a names.json to fill
    in (kept if there is one) and a contact sheet row per group."""
    ids, imgs = [], []
    for p in sorted((school / "crops-wide").glob("*.jpg")):
        im = cv2.imread(str(p))
        if im is not None and im.shape[:2] == (WIDE, WIDE):
            ids.append(p.stem)
            imgs.append(im)
    F = np.stack([look_features(im) for im in imgs])
    cv2.setRNGSeed(CLUSTER_SEED)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-4)
    _, lab, centres = cv2.kmeans(F, k, None, crit, 5, cv2.KMEANS_PP_CENTERS)
    lab = lab.ravel()
    d = ((F - centres[lab]) ** 2).sum(1)
    radii = np.array([np.percentile(d[lab == g], RADIUS_PCT) if (lab == g).any() else 0.0
                      for g in range(k)], np.float32)
    folder.mkdir(parents=True, exist_ok=True)
    np.savez(folder / "groups.npz", centres=centres, radii=radii, ids=np.array(ids), labels=lab)
    names = folder / "names.json"
    if not names.exists():
        names.write_text(json.dumps({str(g): {"kind": None, "purity": None, "seen": ""}
                                     for g in range(k)}, indent=1), encoding="utf-8")
    rng = random.Random(CLUSTER_SEED)
    rows = []
    for g in range(k):
        members = [j for j in range(len(ids)) if lab[j] == g]
        tiles = [cv2.resize(imgs[j][32:160, 32:160], (96, 96))
                 for j in rng.sample(members, min(10, len(members)))]
        tiles += [np.zeros((96, 96, 3), np.uint8)] * (10 - len(tiles))
        tag = np.zeros((96, 70, 3), np.uint8)
        cv2.putText(tag, str(g), (5, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        cv2.putText(tag, f"n{len(members)}", (5, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        rows.append(np.hstack([tag] + tiles))
    (folder / "sheets").mkdir(exist_ok=True)
    for s in range(0, k, 8):
        cv2.imwrite(str(folder / "sheets" / f"sheet{s // 8}.jpg"), np.vstack(rows[s:s + 8]))
    return lab


def overlaps(a, b, grow=0.2) -> bool:
    g = grow * max(b[2] - b[0], b[3] - b[1])
    return not (a[2] <= b[0] - g or a[0] >= b[2] + g or a[3] <= b[1] - g or a[1] >= b[3] + g)


def centre(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def hand_rows(home: Path, labels_path: Path, rng: random.Random, labeller: Labeller | None = None,
              check: collections.Counter | None = None):
    """(crop, row) for every sure typed coin, reviewed not-coin and random
    background point of coin_labels.json. With `labeller` and `check`, each
    sure typed coin's (hand kind, labeller kind or "-") is counted."""
    data = json.loads(labels_path.read_text(encoding="utf-8"))
    for f in data["frames"]:
        img = cv2.imread(str(home / f["path"]))
        if img is None:
            continue
        run, base = f["window"], Path(f["path"]).stem
        common = {"run": run, "src": f["path"], "field": f.get("field")}
        for i, c in enumerate(f["coins"]):
            if not c.get("sure") or c["kind"] == "unknown":
                continue
            x, y = centre(c["box"])
            if labeller is not None and check is not None:
                check[(c["kind"], labeller.kind(look_features(window(img, x, y, WIDE)))[1] or "-")] += 1
            yield saved(img, x, y), {**common, "id": f"hand-{run}-{base}-c{i}", "label": c["kind"],
                                     "source": "hand", "confidence": 1.0, "point": [x, y],
                                     "box": c["box"]}
        for i, c in enumerate(f.get("not_coins", [])):
            x, y = centre(c["box"])
            yield saved(img, x, y), {**common, "id": f"hand-{run}-{base}-n{i}", "label": "background",
                                     "source": "hand_not_coin", "confidence": 0.95, "point": [x, y],
                                     "box": c["box"]}
        if f.get("partial", True):
            continue                # only frames labelled whole have known-empty ground
        H, W = img.shape[:2]
        x0, y0, x1, y1 = int(W * WORLD[0]), int(H * WORLD[1]), int(W * WORLD[2]), int(H * WORLD[3])
        taken = [c["box"] for c in f["coins"]] + [c["box"] for c in f.get("not_coins", [])]
        for i in range(BACKGROUND_PER_FRAME):
            for _ in range(50):
                bx, by = rng.randint(x0, x1 - WINDOW), rng.randint(y0, y1 - WINDOW)
                box = [bx, by, bx + WINDOW, by + WINDOW]
                if not any(overlaps(box, t) for t in taken):
                    taken.append(box)
                    x, y = centre(box)
                    yield saved(img, x, y), {**common, "id": f"hand-{run}-{base}-b{i}",
                                             "label": "background", "source": "hand_background",
                                             "confidence": 0.85, "point": [x, y], "box": box}
                    break


def self_rows(school: Path, labeller: Labeller, drops: collections.Counter, by_kind: dict):
    """(crop, row) for each chase whose target's look is a named kind and
    whose aftermath says a token was there."""
    for lesson in lessons(school):
        path = school / "crops-wide" / f"{lesson.id}.jpg"
        wide = cv2.imread(str(path)) if path.exists() else None
        if wide is None or wide.shape[:2] != (WIDE, WIDE):
            drops["no wide crop (48 px only, before 2026-10-20)"] += 1
            continue
        group, kind, purity = labeller.kind(look_features(wide))
        hud = lesson.outcome == "collected" and not _legacy_verdict(lesson)
        ev = evidence_class(lesson.evidence) if hud else None
        if kind is not None and lesson.evidence != NEVER:
            by_kind.setdefault(kind, collections.Counter()).update(
                ["reached"] + ([ev] if ev else []) + (["sight"] if lesson.sight == "collected" else []))
        if kind is None:
            drops["look in no named group, or outside its radius"] += 1
            continue
        if not hud and lesson.sight != "collected":
            drops["nothing after the chase said a token was there"] += 1
            continue
        factor = (1.0 if ev in COMPATIBLE.get(kind, ()) else
                  OTHER_VERDICT if ev is not None and kind in COMPATIBLE else SIGHT_ONLY)
        conf = round(purity * factor, 2)
        if conf < MIN_CONFIDENCE:
            drops["confidence under MIN_CONFIDENCE"] += 1
            continue
        yield saved(wide, WIDE / 2, WIDE / 2), {
            "id": f"self-{lesson.id}", "run": f"attempt-{lesson.attempt}", "src": str(path),
            "point": [WIDE / 2, WIDE / 2], "label": kind, "source": "self", "confidence": conf,
            "group": group, "evidence": lesson.evidence if hud else None, "evidence_class": ev,
            "sight": lesson.sight or None, "attempt": lesson.attempt}


def build(home: Path, school: Path, labels: Path, out: Path, colour: str,
          labeller_dir: Path, seed: int = 0) -> dict:
    labeller = Labeller.load(labeller_dir)
    dest = out / colour
    dest.mkdir(parents=True, exist_ok=True)
    drops, by_kind, check, counts = collections.Counter(), {}, collections.Counter(), collections.Counter()
    sources = [hand_rows(home, labels, random.Random(seed), labeller, check),
               self_rows(school, labeller, drops, by_kind)]
    with open(dest / "manifest.jsonl", "w", encoding="utf-8") as man:
        for source in sources:
            for crop, row in source:
                row["split"] = split_of(row["run"])
                row["hive_colour"] = colour
                rel = Path(row["split"]) / row["label"] / f"{row['id']}.png"
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(dest / rel), crop)
                row["file"] = str(rel)
                if row["source"] == "self":      # var/ is not ours to keep: copy the 192 px original
                    (dest / "wide").mkdir(exist_ok=True)
                    shutil.copy2(row["src"], dest / "wide" / Path(row["src"]).name)
                    row["wide"] = f"wide/{Path(row['src']).name}"
                man.write(json.dumps(row) + "\n")
                counts[(row["split"], row["label"], row["source"])] += 1
    named = {n["kind"] for n in labeller.names.values()}
    judged = [(h, k) for (h, k), n in check.items() for _ in range(n) if h in named]
    stats = {
        "hive_colour": colour,
        "rows": sum(counts.values()),
        "by_split_label_source": {"/".join(k): v for k, v in sorted(counts.items())},
        "dropped_self": dict(drops),
        # share of the reached chases of each look with each verdict
        "evidence_by_kind": {k: {e: round(c[e] / max(1, c["reached"]), 3)
                                 for e in ("honey", "haste", "stacks", "pollen", "sight")}
                             | {"reached": c["reached"]} for k, c in sorted(by_kind.items())},
        # the labeller on the hand-labelled coins of the kinds it names
        "labeller_vs_hand": {
            "pairs": {f"{h}->{k}": n for (h, k), n in sorted(check.items())},
            "coins_of_named_kinds": len(judged),
            "given_a_kind": sum(k != "-" for _, k in judged),
            "right": sum(h == k for h, k in judged),
        },
    }
    (dest / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--home", type=Path, default=Path.home() / "Hivemind",
                    help="the install whose var/ and data/models/ are read (read-only)")
    ap.add_argument("--out", type=Path,
                    default=Path(os.environ.get("HIVEMIND_WORK") or Path.home() / ".cache/hivemind-dev") / "datasets/tokens-typed")
    ap.add_argument("--hive-colour", default="blue")
    ap.add_argument("--labeller", type=Path, help="default: <out>/labeller")
    ap.add_argument("--cluster", type=int, metavar="K",
                    help="group the wide crops into K looks for naming, then stop")
    args = ap.parse_args()
    school = args.home / "var" / "school-coins"
    labeller = args.labeller or args.out / "labeller"
    if args.cluster:
        lab = cluster(school, labeller, args.cluster)
        print(f"{len(lab)} crops in {args.cluster} groups: name them in {labeller / 'names.json'}")
        return
    stats = build(args.home, school, args.home / "data" / "models" / "coin_labels.json",
                  args.out, args.hive_colour, labeller)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
