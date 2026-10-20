#!/usr/bin/env python3
"""Does a descriptor actually tell two places apart? Score it and find out.

    ./.venv/bin/python scripts/measure_ground.py var/frames2 var/labels.txt

`labels.txt` is one `filename  field-name` per line. Frames with no label are
ignored, so labelling a subset is fine and is the normal case.

WHAT IT PRINTS, and why these two numbers are the whole answer:

    worst likeness between two frames of the SAME field
    best  likeness between two frames of DIFFERENT fields

If the first is above the second there is a threshold that works and the
descriptor separates. If they cross, no threshold works, and any "place" built
on it is noise wearing a name. THAT IS WHAT KILLED THE FIRST MAP: whole-screen
colour scored -0.042 worst-same against +0.803 best-different, and the code was
asking whether the correlation cleared 0.45.

It scores every descriptor it is given, side by side on the same frames, so the
comparison is like for like and the winner is chosen by measurement.
"""
from __future__ import annotations

import pathlib
import sys
from collections import defaultdict

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.brain import observe                 # noqa: E402
from hivemind.vision import ground                 # noqa: E402

DESCRIPTORS = {
    "whole-screen (in use today)": (observe.signature, observe.likeness),
    "ground band": (ground.signature, ground.likeness),
}


def read_labels(path: pathlib.Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            out[parts[0]] = " ".join(parts[1:]).lower()
    return out


def score(frames: dict[str, object], labels: dict[str, str],
          sig_of, like) -> tuple[float, float, int, int]:
    sigs = {name: sig_of(img) for name, img in frames.items()}
    names = sorted(sigs)
    worst_same, best_diff = 1.0, -1.0
    same_n = diff_n = 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            value = like(sigs[a], sigs[b])
            if labels[a] == labels[b]:
                worst_same = min(worst_same, value)
                same_n += 1
            else:
                best_diff = max(best_diff, value)
                diff_n += 1
    return worst_same, best_diff, same_n, diff_n


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    folder = pathlib.Path(sys.argv[1])
    labels = read_labels(pathlib.Path(sys.argv[2]))

    frames, missing = {}, []
    for name in sorted(labels):
        img = cv2.imread(str(folder / name))
        if img is None:
            missing.append(name)
        else:
            frames[name] = img
    if missing:
        print(f"  {len(missing)} labelled frames not found, e.g. {missing[0]}")
    if len(frames) < 4:
        print("  need at least four labelled frames")
        return 1

    by_field = defaultdict(list)
    for name in frames:
        by_field[labels[name]].append(name)
    print(f"\n  {len(frames)} frames over {len(by_field)} fields")
    for field, names in sorted(by_field.items()):
        print(f"    {field:<20} {len(names)} frames")
    if len(by_field) < 2:
        print("  need at least two different fields to measure separation")
        return 1

    print()
    for title, (sig_of, like) in DESCRIPTORS.items():
        worst_same, best_diff, same_n, diff_n = score(frames, labels,
                                                      sig_of, like)
        gap = worst_same - best_diff
        verdict = ("SEPARATES" if gap > 0 else
                   "DOES NOT SEPARATE — no threshold works")
        print(f"  {title}")
        print(f"    worst same-field  {worst_same:+.3f}  ({same_n} pairs)")
        print(f"    best  diff-field  {best_diff:+.3f}  ({diff_n} pairs)")
        print(f"    margin            {gap:+.3f}   {verdict}")
        if gap > 0:
            print(f"    -> usable threshold: {(worst_same + best_diff) / 2:+.3f}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
