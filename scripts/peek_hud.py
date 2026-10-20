#!/usr/bin/env python3
"""Read the HUD out of the live-view JPEG, without touching the running bot.

WHY. During an unattended run the only honest way to check a number the log
reported is to read the same pills the bot reads. The live view already writes
a full-resolution frame to disk for the GUI, so a second reader can use it
without opening a capture session or competing with the run for the
compositor -- which is what destabilised the nested Hyprland before.

IT IS NORMAL FOR THIS TO REPORT "unreadable" AND THE BOT NOT TO. The live view
is a JPEG written for a human to look at, and its compression is enough to cost
the digit matcher a glyph -- typically the slash, which comes back as
'35174?948750'. The bot reads the SAME pills from the raw screencopy frame and
does not have that problem: MEASURED over 120 real frames saved by the incident
recorder, `HudReader.pollen()` succeeded **120 out of 120**.

So a failure here is evidence about this script, not about the bot, and chasing
it would be chasing a compression artefact.

    ./.venv/bin/python scripts/peek_hud.py [--watch N]
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.brain.farm import HudReader          # noqa: E402
from hivemind.vision import screenstate as ss      # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIVE = pathlib.Path("/run/user/1000/hivemind-live.jpg")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=1, help="read this many times")
    ap.add_argument("--gap", type=float, default=2.0)
    ap.add_argument("--path", default=str(LIVE))
    args = ap.parse_args()

    templates = ss.load_templates(ROOT / "data/templates/digits")
    holder = {"frame": None}
    hud = HudReader(lambda: holder["frame"], templates)

    for i in range(max(1, args.watch)):
        holder["frame"] = cv2.imread(args.path)
        if holder["frame"] is None:
            print("  no live frame on disk")
            return 1
        print(f"  {time.strftime('%H:%M:%S')}  "
              f"honey {hud.honey().describe():>28}   "
              f"pollen {hud.pollen().describe()}", flush=True)
        if i + 1 < args.watch:
            time.sleep(args.gap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
