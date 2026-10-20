#!/usr/bin/env python3
"""Teach the digit reader new glyphs from a frame whose values are known.

Templates cannot be invented; every glyph must be cut from a real frame and
labelled from a value we can read ourselves. This script does that safely.

The one way to corrupt a template set is misalignment: if the segmenter finds
nine glyphs and the ground-truth string has ten characters, zipping them pairs
every glyph with the wrong label and the reader is then confidently wrong
forever. So a region is used ONLY when the counts match exactly, and is skipped
loudly otherwise.

Usage:
    python3 scripts/learn_digits.py FRAME.png --honey 10,216,209 \
                                              --pollen 445,583/660,000
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import cv2
import yaml

from hivemind.vision.digits import TemplateSet, read, segment

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "data/templates/digits"
REGIONS = ROOT / "data/calib/regions.yaml"


def learn(templates: TemplateSet, roi, truth: str, label: str) -> int:
    glyphs = segment(roi)
    if len(glyphs) != len(truth):
        print(f"  {label:8s} SKIPPED - segmented {len(glyphs)} glyphs but "
              f"{truth!r} has {len(truth)} characters. Labels would be "
              f"misaligned, so nothing was learned from this region.")
        return 0
    added = 0
    for glyph, char in zip(glyphs, truth):
        if char not in templates.templates:
            added += 1
        templates.add(char, glyph.image)
    print(f"  {label:8s} {truth!r} -> {len(glyphs)} glyphs, {added} newly seen")
    return added


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("frame", type=pathlib.Path)
    ap.add_argument("--honey", help="exact Honey value as displayed")
    ap.add_argument("--pollen", help="exact Pollen value, including the slash")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    regions = yaml.safe_load(REGIONS.read_text())["regions"]
    frame = cv2.imread(str(args.frame))
    if frame is None:
        sys.exit(f"cannot read {args.frame}")

    templates = (TemplateSet.load(TEMPLATES)
                 if (TEMPLATES / "index.json").exists() else TemplateSet())
    before = set(templates.chars)
    print(f"  known before: {sorted(before)}")

    used: list[tuple[str, str]] = []
    for name, truth in (("honey", args.honey), ("pollen", args.pollen)):
        if not truth:
            continue
        x, y, w, h = regions[name]
        if learn(templates, frame[y:y + h, x:x + w], truth, name) >= 0 and \
                len(segment(frame[y:y + h, x:x + w])) == len(truth):
            used.append((name, truth))

    gained = sorted(set(templates.chars) - before)
    print(f"  newly learned: {gained or 'nothing'}")

    # Verify by reading back -- but only the regions we actually learned from.
    # A region that was skipped for misalignment taught us nothing, so it must
    # not veto the glyphs a good region did contribute.
    ok = True
    for name, truth in used:
        x, y, w, h = regions[name]
        got, score = read(frame[y:y + h, x:x + w], templates)
        mark = "ok " if got == truth else "BAD"
        ok &= got == truth
        print(f"  {mark} {name:8s} reads {got!r} (min-confidence {score:.3f})")

    if not used:
        sys.exit("  nothing usable in this frame")
    if not ok:
        sys.exit("  refusing to save: a region did not read back as its truth")
    if args.dry_run:
        print("  dry run, not saved")
        return
    templates.save(TEMPLATES)
    print(f"  saved to {TEMPLATES}")
    missing = [d for d in "0123456789" if d not in templates.chars]
    print(f"  still unseen: {missing or 'none - all ten digits known'}")


if __name__ == "__main__":
    main()
