#!/usr/bin/env python3
"""Draw what the bot can point at onto a frame, and save the picture.

THE OWNER'S QUESTION, and it deserves an answer you can look at: the AI's
view showed no token highlights -- maybe because the character was not in a
field, maybe not; find out.

The GUI already draws these boxes over the live view (gui/panels/liveview), so
this is not a second implementation of the overlay -- it asks `vision.notice`
the same question the GUI asks and paints the answer, so a still can be checked
without watching the window. Use it on the live frame while the bot is running:

    ./scripts/shoot_overlay.py                       # the live frame
    ./scripts/shoot_overlay.py some/frame.jpg out.png

Boxes are coloured the way the GUI colours them: tokens accent, sightings too
weak to chase dim, mobs red, everything else blue.

IT SHOWS THE DETECTOR RAW. The running bot also passes every sighting through
`vision.pinned`, which drops the marks that never move while the view does --
the player's own bee, the interface, and (seen here on 2026-09-22) THE MOUSE
CURSOR, which is a white high-contrast arrow with a dark outline and scored
0.64. Nothing is filtered out here on purpose: the question this script
answers is what the detector believes, and the filter is the separate question
of what the chaser acts on.
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import cv2

from hivemind.vision import notice
from hivemind.vision import screenstate as ss

# BGR, roughly the GUI's palette (gui/theme).
COLOURS = {
    "token": (60, 200, 245),      # accent
    "maybe": (120, 120, 120),     # a near miss, drawn dim and labelled
    "mob": (60, 60, 235),
    "landmark": (220, 170, 90),
    "target": (90, 210, 120),
}


def main() -> int:
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    source = sys.argv[1] if len(sys.argv) > 1 else f"{runtime}/hivemind-live.jpg"
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "overlay.png")

    frame = cv2.imread(str(source))
    if frame is None:
        print(f"could not read {source}")
        return 1
    screen = ss.classify(frame)
    boxes = notice.notice(frame, world=screen is ss.Screen.IN_GAME)
    print(f"{source}: {screen.value}, {len(boxes)} box(es)")

    canvas = frame.copy()
    for box in boxes:
        colour = COLOURS.get(box.get("kind", ""), (200, 200, 200))
        x, y = int(box["x"]), int(box["y"])
        w, h = int(box.get("w", 0)), int(box.get("h", 0))
        cv2.rectangle(canvas, (x, y), (x + max(w, 2), y + max(h, 2)), colour, 2)
        label = str(box.get("label", ""))[:52]
        cv2.putText(canvas, label, (x, max(14, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1, cv2.LINE_AA)
        print(f"  {box['kind']:9s} {w:4d}x{h:<4d} at ({x:4d},{y:4d})  {label}")

    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), canvas)
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
