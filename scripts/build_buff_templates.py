#!/usr/bin/env python3
"""Cut the buff-bar templates -- the Haste icon, the Melody icon and the stack
digits -- out of recorded frames whose bars were read by eye.

WHY THESE EXIST. Natro Macro's `Walk()` never holds a key for a fixed time:
it reads the Haste stacks off the buff bar every iteration and integrates
movespeed until the distance is covered (lib/Walk.ahk, GPLv3, read
2026-09-22). Every recorded route in this project is a blind timed hold, so
a few Haste tokens make every leg overshoot -- the owner saw a walk drift
far to the right after a Haste token was picked up, and
data/knowledge/machines.yaml has said so for a day. Reading the bar needs
templates, and templates come from real frames, labelled by eye:

    LABELS below: frame -> {slot: text as it reads on screen}

MEASURED 2026-09-22 on those frames: the bar's icons are 38 px squares
abutting from x=0, rows 58..96; the stack text is white with a dark outline,
digits 12 px tall in rows 23..35 of the icon, the 'x' 9 px tall in rows
26..35; a multiplier like "x1.22" uses a smaller 6-8 px font this does not
read. Digits 0, 7 and 8 were first labelled on 2026-09-27 (LABELS); a new
icon or a new font is labelled here the same way and this rerun.

    ./scripts/build_buff_templates.py
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.vision import buffs                                # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data/templates/buffs"
FIXTURES = ROOT / "tests/fixtures/buffs"

# Read by eye off the recorded frames, 2026-09-22 21:35. Slots are counted
# from the left edge of the screen; an empty string is an icon with no count.
LABELS = {
    "var/incidents/234344-token/145_t+07.4s.jpg": {
        0: "x5", 1: "x14", 2: "x3", 3: "x3", 4: "", 5: "", 6: "x2", 7: "x1.22"},
    "var/incidents/235445-token/091_t+04.7s.jpg": {
        0: "x5", 1: "x14", 2: "x4", 3: "x3", 4: "x1.20", 5: "", 6: ""},
    "var/homing/attempt-240/look14-step-y268855-b+0274.jpg": {
        0: "x15", 1: "x6", 2: "x49"},
    # 0, 7 AND 8, read by eye 2026-09-27 off the Haste icon (slot 3), from
    # the 4,156 count glyphs no template read in a third of the saved frames:
    # they fell into three shapes, 1,453 eights, 987 zeros and 714 sevens.
    "var/routes/attempt-452/163804-natro_out_pine_tree_via_red_cannon-02-hive_offset-d.jpg": {
        3: "x8"},
    "var/routes/attempt-457/172822-natro_out_brown_bear-01-walk-w20.jpg": {
        3: "x10"},
    "var/routes/attempt-364/224858-natro_out_riley_bee-45-camera-right.jpg": {
        3: "x7"},
}
# Which slot holds which named icon, in the frames where it is known.
ICONS = {
    "haste": ("var/incidents/235445-token/091_t+04.7s.jpg", 5),    # no count over it
    "melody": ("var/incidents/234344-token/145_t+07.4s.jpg", 5),
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "digits").mkdir(exist_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    frames = {p: cv2.imread(str(ROOT / p)) for p in LABELS}
    for p, f in frames.items():
        if f is None:
            print(f"missing frame {p}; nothing written")
            return 1

    # the named icons, as grayscale 38x38 patches
    for name, (path, slot) in ICONS.items():
        icon = buffs.slots(frames[path])[slot]
        cv2.imwrite(str(OUT / f"{name}.png"), cv2.cvtColor(icon, cv2.COLOR_BGR2GRAY))
        print(f"{name}: slot {slot} of {path}")

    # the digits: every glyph box the reader finds in a labelled slot, in order,
    # paired with the label's characters after the leading 'x'
    written: dict[str, str] = {}
    for path, per_slot in LABELS.items():
        icons = buffs.slots(frames[path])
        for slot, text in per_slot.items():
            if not text or "." in text:            # multipliers use the small font
                continue
            found = buffs.glyphs(icons[slot])
            digits = text[1:]
            if len(found) != len(digits):
                print(f"  {path} slot {slot} {text!r}: found {len(found)} glyph(s) for "
                      f"{len(digits)} digit(s) -- skipped")
                continue
            for (_box, own), ch in zip(found, digits):
                if ch in written:
                    continue
                cv2.imwrite(str(OUT / "digits" / f"{ch}.png"), own)
                written[ch] = f"{path} slot {slot} ({text})"
    for ch in sorted(written):
        print(f"digit {ch}: {written[ch]}")
    missing = sorted(set("0123456789") - set(written))
    print(f"digits not yet seen in a stack count: {missing}")

    # fixtures for the tests: the bar strip of each labelled frame + its labels
    fixture_labels = {}
    for i, (path, per_slot) in enumerate(LABELS.items()):
        strip = frames[path][buffs.BAR_TOP:buffs.BAR_BOTTOM, 0:buffs.ICON * buffs.MAX_SLOTS]
        name = f"bar{i}.png"
        cv2.imwrite(str(FIXTURES / name), strip)
        fixture_labels[name] = {str(k): v for k, v in per_slot.items()}
    (FIXTURES / "labels.json").write_text(json.dumps(fixture_labels, indent=1))
    print(f"fixtures: {len(fixture_labels)} bar strips -> {FIXTURES}")

    # self-check: read every labelled count back
    wrong = 0
    for path, per_slot in LABELS.items():
        icons = buffs.slots(frames[path])
        for slot, text in per_slot.items():
            if not text or "." in text:
                continue
            got = buffs.stacks(icons[slot])
            want = int(text[1:])
            if got != want:
                wrong += 1
            print(f"  read slot {slot} of {pathlib.Path(path).name}: {text} -> {got}"
                  f"{'' if got == want else '   WRONG'}")
    print("all counts read back" if not wrong else f"{wrong} count(s) misread")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
