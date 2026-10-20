"""Which item each hotbar slot holds, read off the screen.

WHY. act/hotbar knew only what it was told (`KNOWN_SLOTS`: the sprinkler and
the gumdrops), so nothing could use the rest -- and the owner keeps his time
savers there: on 2026-10-01 the bar held a Whirligig, Field Dice, a
Micro-Converter, Jelly Beans and a Coconut in slots 3-7. A player looks at the
bar; so does this.

HOW. Each slot's icon -- the tile's upper left, clear of the key hint drawn top
right and the count bottom right -- is matched against data/templates/hotbar/,
cut from the 21:3x frame of run-563. MEASURED on two other frames of the day
(16:31, attempt 557; 21:40, attempt 563): every slot named right at
0.91-0.99, with 0.56-0.74 between the best template and the next. A slot under
MIN_SCORE is unknown, never guessed; the counts are left to the inventory
read (tesseract misread four of seven).

GREYED TILES. The game greys a tile when its count reaches 0 and does NOT
redraw it when the count rises again; only a rejoin (or a use, through its
cooldown) brings the bright tile back. MEASURED 2026-10-13 over the 182 stack
frames of 10-12/10-13 (var/hotbar/*-stack1.jpg): all 7 greyed-to-bright
changes of slots 3 and 5 came on the first stack frame after a fresh join,
none without one, while greyed tiles showed x1 to x6; a
Whirligig shown "x2" greyed at 13:31:57 (var/routes/attempt-963/
133157-natro_home_bamboo-00-start.jpg) scored 0.65 here and the rescue said
"no Whirligig on the hotbar". Two greys: a dark one (it ran out in this
session) and a lighter, see-through one (it was out at the join). So greyed
templates (data/templates/hotbar/greyed/, `<item>-<grey>.png`, cut from that
frame and from 20261013-090636/084408-stack1.jpg) name the item and flag the
tile `greyed`. MEASURED on 667 frames of 10-12/10-13 (stack, route and press
frames, the three source frames left out): all 382 greyed Whirligig tiles
0.84-0.99 and all 452 greyed Micro-Converter tiles 0.74-0.99, each above its
bright score; the other 4,002 tiles 0.51 at most against either. Whether the game USES a greyed
tile is not measured (no press was ever made on one): act/hotbar judges such
a press by the tile turning to its cooldown, not by the brightness drop.

A COOLDOWN is a different tile: dark, with a timer ("2:15" 43 s after the
11:05:47 Whirligig, 3 min in all, its in-game text "(Cooldown: 3m)"). It
matches nothing here (0.33 at most) and stays unknown.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from ..datapaths import data
from ..telemetry import readhealth

TEMPLATES = data("templates", "hotbar")
GREYED = data("templates", "hotbar", "greyed")
FRAME_SIZE = (1920, 1080)
# Slot 1's whole tile at 1920x1080 (x0, y0, x1, y1); slot n is (n-1) pitches right
# (act/hotbar SLOT_PITCH).
TILE1 = (697, 975, 770, 1048)
PITCH = 76
SLOTS = 7
# The icon within a tile, (y0, y1, x0, x1): what the templates were cut from.
ICON = (8, 52, 6, 50)
MIN_SCORE = 0.8
# a greyed template's floor: between the 0.51 of any other tile and the 0.74
# of the worst greyed Micro-Converter (GREYED TILES above)
GREY_MIN_SCORE = 0.65


@dataclass(frozen=True)
class Slot:
    slot: int
    item: str | None        # a template's name, or None
    score: float
    greyed: bool = False    # drawn at a count of 0, maybe not redrawn since

    def describe(self) -> str:
        if not self.item:
            return f"slot {self.slot}: unknown ({self.score:.2f})"
        return (f"slot {self.slot}: {self.item.replace('_', ' ')}"
                f"{' (greyed)' if self.greyed else ''} ({self.score:.2f})")


@lru_cache(maxsize=2)          # the bright set and the greyed one
def templates(folder: str | None = None) -> dict:
    root = Path(folder) if folder else Path(TEMPLATES)
    out = {}
    for path in sorted(root.glob("*.png")):
        image = cv2.imread(str(path))
        if image is not None:
            out[path.stem] = image
    return out


def tile(frame, slot: int):
    """Slot `slot`'s tile, scaled to 1920x1080 pixels, or None."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    h, w = frame.shape[:2]
    sx, sy = w / FRAME_SIZE[0], h / FRAME_SIZE[1]
    x0, y0, x1, y1 = TILE1
    dx = PITCH * (int(slot) - 1)
    out = frame[int(y0 * sy):int(y1 * sy), int((x0 + dx) * sx):int((x1 + dx) * sx), :3]
    if out.size == 0:
        return None
    if (sx, sy) != (1.0, 1.0):
        out = cv2.resize(out, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    return out


def _best(icon, temps: dict) -> tuple[str | None, float]:
    best, score = None, -1.0
    for name, temp in temps.items():
        if temp.shape[0] > icon.shape[0] or temp.shape[1] > icon.shape[1]:
            temp = cv2.resize(temp, (icon.shape[1], icon.shape[0]))
        s = float(cv2.matchTemplate(icon, temp, cv2.TM_CCOEFF_NORMED).max())
        if s > score:
            best, score = name, s
    return best, score


def identify(frame, slot: int, known: dict | None = None,
             greyed: dict | None = None) -> Slot:
    """What slot `slot` holds. `known`/`greyed` stand in for the bright and
    the greyed templates (tests); with `known` alone no greyed ones are used."""
    t = tile(frame, slot)
    temps = templates() if known is None else known
    greys = (templates(str(GREYED)) if known is None else greyed) or {}
    if t is None or not temps:
        return Slot(slot=int(slot), item=None, score=0.0)
    y0, y1, x0, x1 = ICON
    icon = np.ascontiguousarray(t[y0:y1, x0:x1])
    best, score = _best(icon, temps)
    grey, grey_score = _best(icon, greys) if greys else (None, -1.0)
    # THE GREYED TEMPLATE WINS ONLY OVER THE BRIGHT ONE: a greyed Whirligig
    # read 0.80-0.81 on the bright template twice on 10-12 (09:18:13).
    if grey is not None and grey_score >= GREY_MIN_SCORE and grey_score > score:
        return Slot(slot=int(slot), item=grey.split("-")[0],
                    score=round(grey_score, 3), greyed=True)
    return Slot(slot=int(slot), item=best if score >= MIN_SCORE else None,
                score=round(max(0.0, score), 3))


def read(frame, known: dict | None = None, greyed: dict | None = None) -> list[Slot]:
    """Every slot, left to right."""
    slots = [identify(frame, n, known, greyed) for n in range(1, SLOTS + 1)]
    readhealth.note("hotbar tile", any(s.item for s in slots), max(s.score for s in slots))
    return slots


def find(frame, item: str, known: dict | None = None,
         greyed: dict | None = None) -> Slot | None:
    """The slot holding `item`, bright or greyed, or None when no slot shows it."""
    for s in read(frame, known, greyed):
        if s.item == item:
            return s
    return None


def slot_of(frame, item: str, known: dict | None = None) -> int | None:
    """The slot holding `item` (greyed included), or None when no slot shows it."""
    found = find(frame, item, known)
    return found.slot if found else None
