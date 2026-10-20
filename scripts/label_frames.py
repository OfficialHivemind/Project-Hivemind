#!/usr/bin/env python3
"""Label recorded frames with the field the GAME named, not the one we guessed.

    ./.venv/bin/python scripts/label_frames.py var/frames2 var/frame_labels.txt

WHY THIS IS WORTH A BATCH RUN. Every descriptor this project has tried to
localise with was scored against labels somebody typed in by eye, mine included,
and 8b records where that led. The reward feed removes the guesswork: when it
says `+590 Honey (from Pumpkin Patch)` the field is not an opinion.

TWO RULES, BOTH LEARNED THE HARD WAY.

  * The pills are found by GEOMETRY before anything reads them. Asked to
    transcribe an empty crop, the model returned "claim hive" in 11 of 24
    frames -- text that is nowhere near that corner of the screen. `feed.rows`
    is the gate and a frame with no pills is never sent anywhere.

  * Only names in `data/knowledge/world.yaml` are accepted. The feed also
    credits "Puffshroom", "Festive Gift" and "Rhino Beetle", which are sources
    of honey and not places to stand.

Frames with no feed are left unlabelled rather than guessed at, so the output is
a subset and every line in it is something the game said.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.brain.vlm import VisionModel          # noqa: E402
from hivemind.vision import feed                    # noqa: E402
from hivemind.vision.whereami import FROM, field_in, field_names  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
TRANSCRIBE = ("Transcribe every line of text in this image exactly, one per "
              "line. If there is no text, reply with nothing at all.")
# NAME MATCHING LIVES IN ONE PLACE, and this is why. The first version of this
# script had its own copy that stripped only a trailing " field", so it quietly
# dropped every Pumpkin Patch, Pine Tree Forest and Pepper Patch frame while
# looking like it was working. `vision.whereami.field_in` is the version with
# the suffixes right, and is what the bot uses at run time.


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("out")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    fields = field_names(ROOT / 'data/knowledge/world.yaml')
    frames = sorted(pathlib.Path(args.folder).glob("*.jpg"))
    if args.limit:
        frames = frames[:args.limit]
    model = VisionModel()
    if not model.available():
        print("  the vision model is not reachable")
        return 1

    print(f"  {len(frames)} frames, {len(fields)} known fields", flush=True)
    labels: list[tuple[str, str]] = []
    other: dict[str, int] = {}
    with_feed = asked = 0
    started = time.monotonic()

    for i, path in enumerate(frames, 1):
        image = cv2.imread(str(path))
        if image is None:
            continue
        strip = feed.strip(image)
        if strip is None:
            continue                       # no pills: nothing to read, ever
        with_feed += 1
        big = cv2.resize(strip, None, fx=2.0, fy=2.0,
                         interpolation=cv2.INTER_CUBIC)
        ok, buf = cv2.imencode(".png", big)
        if not ok:
            continue
        asked += 1
        answer = model.ask(buf.tobytes(), TRANSCRIBE)
        said = (getattr(answer, "text", answer) or "").lower()
        slug = field_in(said, fields)
        if slug:
            labels.append((path.name, slug))
        else:
            for raw in FROM.findall(said):
                name = " ".join(str(raw).split()).strip()
                other[name] = other.get(name, 0) + 1
        if i % 50 == 0:
            rate = (time.monotonic() - started) / max(1, asked)
            print(f"    {i}/{len(frames)}  feed={with_feed}  "
                  f"labelled={len(labels)}  {rate:.1f}s/read", flush=True)

    out = pathlib.Path(args.out)
    out.write_text("".join(f"{n} {s}\n" for n, s in labels))
    counts: dict[str, int] = {}
    for _, slug in labels:
        counts[slug] = counts.get(slug, 0) + 1

    print(f"\n  {with_feed} frames had a feed, {len(labels)} named a field")
    for slug, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {slug:<16} {n}")
    if other:
        print("\n  named, but not a field (correctly ignored):")
        for name, n in sorted(other.items(), key=lambda kv: -kv[1])[:8]:
            print(f"    {name:<24} {n}")
    print(f"\n  written to {out}")
    model.unload()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
