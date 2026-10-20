"""The game's red refusal notice, in the notice column at the bottom right.

WHY IT IS READ AT ALL. The sprinkler is pressed at the end of Natro's field
start (run_farm `natro_field_start`), and the game says so, in red, when it
will not build one: "You must be standing in a field to build a Sprinkler."
MEASURED 2026-09-27 over the 960 gather snapshots in var/routes (the first
legs of every gather since attempt 476): a red box in this column on 579 of
them, and on 309 of the 315 first three legs of Pine Tree's -- Natro's start
walks a fixed distance from where ITS route lands to the sprinkler corner,
ours lands short of that, and the walk ends past the field's edge. Every one
of ten sampled boxes read that sentence; none of the feed's blue lines is red.

HOW MUCH RED IS ONE NOTICE. The column is its lowest five slots or so, where
new notices appear and older ones are pushed up: tall enough that three
refusals in a row are all still in it (a two-slot column held two, and a
third only pushed the oldest out -- the share stopped rising). Over those
960 frames its red share was about 0 on 317 (no notice), 0.05-0.07 on 508
(one, fully drawn: median 0.064), 0.01-0.05 on 90 (one fading or sliding up)
and 0.1 and over on 21 (two or more). So a press is refused when the share
RISES by NEW_NOTICE (about half a notice) or more across it: a notice left by
an earlier press is already in `before`, a new one adds its own share on top,
and a press the game accepted adds nothing.

AND WHICH NOTICE: READ, NOT ASSUMED. Since the Pine Tree flight lands on the
flowers (act/routes GLIDE_SIDES, 2026-10-01), the start spot is where the
last trip's sprinkler still stands, and the game refuses a second one there
in the same red: "Cannot place sprinklers this close to eachother." Read off
every saved press of 2026-10-01 (var/hotbar, `read_newest`): the morning's
refusals all said the field sentence, until the 12:04 trip -- three presses
"Cannot place sprinklers this close", then the step-backs walked off the
flowers and two said "You must be standing in a field". A sprinkler already
standing within reach is the start spot doing its job, so the bot is told
which (`kind_of`).
"""
from __future__ import annotations

import cv2
import numpy as np

# The column, as (y0, y1, x0, x1) of a 1920x1080 frame: its lowest slots,
# where a new notice appears.
NOTICE_BOX = (900, 1075, 1480, 1915)
FRAME_SIZE = (1920, 1080)
# Red, as the notice's fill: hue within 6 of 0/180, saturated and bright.
RED_HUE = 6
RED_MIN_SATURATION = 150
RED_MIN_VALUE = 120
# One fully drawn notice fills about 0.064 of the column; a rise of this much
# is a new one (see the module note for the distribution).
NEW_NOTICE = 0.03


def red_share(frame) -> float | None:
    """The share of the notice column that is the notice's red, or None when
    there is no frame to look at."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    h, w = frame.shape[:2]
    sy, sx = h / FRAME_SIZE[1], w / FRAME_SIZE[0]
    y0, y1, x0, x1 = NOTICE_BOX
    roi = frame[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx), :3]
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(np.ascontiguousarray(roi), cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    red = (((hue <= RED_HUE) | (hue >= 180 - RED_HUE))
           & (sat >= RED_MIN_SATURATION) & (val >= RED_MIN_VALUE))
    return float(red.mean())


def new_notice(before: float | None, after: float | None) -> bool:
    """Did a red notice appear between the two readings? An unreadable
    `after` says nothing; an unreadable `before` is taken as no notice."""
    if after is None:
        return False
    return after - (before or 0.0) >= NEW_NOTICE


# THE NEWEST NOTICE'S WORDS. A row of the column is part of a notice when this
# many of its pixels are the red; the lowest run of such rows is the newest.
ROW_MIN_RED = 40
# ...BUT ONLY A BAR'S RUN. Red flowers are the same red: Mountain Top's read
# as one notice 1480-1762 x 929-1074 (tests/fixtures/golden, 2026-10-26).
# A notice is a bar across the column, x 1565-1903, 21 rows (1033-1053), and
# its bottom 5 rows are red wall to wall: MEASURED 2026-10-26 on the two
# golden refusal frames (sprinkler_refused, feed_honey_gift), 0.97-0.99 of
# the bar's width red on 1049-1053 and 1.0 on 1034-1037, the text rows
# between 0.35-0.9; Mountain Top's flowers 0.42 at most across the same
# columns. So the newest notice is the lowest run of BAR_SOLID rows (no
# taller than BAR_SOLID_ROWS: a red field all across is not a bar's edge),
# taken up through its ROW_MIN_RED rows to at most BAR_ROWS.
# ponytail: a field red across the whole bar for a few rows only would pass;
# none seen in the frames below (Mountain Top: 0.42).
BAR_X = (1561, 1908)
BAR_SOLID = 0.9
BAR_SOLID_ROWS = 8
BAR_ROWS = 24
# The words that tell the two refusals apart, read loosely (tesseract has read
# "eachofher", "tnis close" and "standlnq", 2026-10-01).
TOO_CLOSE_WORD = "close"
NOT_IN_FIELD_WORD = "field"


def newest_box(frame) -> tuple | None:
    """(x0, y0, x1, y1) of the lowest red notice in the column, in the
    frame's own pixels; None when there is none."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    h, w = frame.shape[:2]
    sy, sx = h / FRAME_SIZE[1], w / FRAME_SIZE[0]
    y0, y1, x0, x1 = (int(NOTICE_BOX[0] * sy), int(NOTICE_BOX[1] * sy),
                      int(NOTICE_BOX[2] * sx), int(NOTICE_BOX[3] * sx))
    roi = frame[y0:y1, x0:x1, :3]
    if roi.size == 0:
        return None
    hsv = cv2.cvtColor(np.ascontiguousarray(roi), cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    red = (((hue <= RED_HUE) | (hue >= 180 - RED_HUE))
           & (sat >= RED_MIN_SATURATION) & (val >= RED_MIN_VALUE))
    bx0, bx1 = int((BAR_X[0] - NOTICE_BOX[2]) * sx), int((BAR_X[1] - NOTICE_BOX[2]) * sx)
    bar = red[:, bx0:bx1]
    solid = np.flatnonzero(bar.mean(axis=1) >= BAR_SOLID)
    if solid.size == 0:
        return None
    bottom = top = int(solid[-1])
    present = set(solid.tolist())
    while top - 1 in present:
        top -= 1
    if bottom - top + 1 > BAR_SOLID_ROWS:
        return None
    rows = set(np.flatnonzero(bar.sum(axis=1) >= ROW_MIN_RED).tolist())
    while top - 1 in rows and bottom - top + 1 < BAR_ROWS:
        top -= 1
    while bottom + 1 in rows and bottom - top + 1 < BAR_ROWS:
        bottom += 1
    cols = np.flatnonzero(bar[top:bottom + 1].any(axis=0))
    return (x0 + bx0 + int(cols[0]), y0 + top, x0 + bx0 + int(cols[-1]), y0 + bottom)


def read_newest(frame, run=None) -> str:
    """The newest notice's words, as tesseract reads them ("" when there is
    no notice or nothing could be read). Upscaled as the amulet's reader
    does (vision/amulet.read_words, ~0.15 s a notice)."""
    box = newest_box(frame)
    if box is None:
        return ""
    from . import amulet
    h, w = frame.shape[:2]
    sx, sy = FRAME_SIZE[0] / w, FRAME_SIZE[1] / h
    region = (int((box[0] - 4) * sx), int((box[1] - 4) * sy),
              int((box[2] + 4) * sx), int((box[3] + 4) * sy))
    kw = {} if run is None else {"run": run}
    words = amulet.read_words(frame, region=region, **kw)
    return " ".join(word.text for word in words)


def kind_of(text: str) -> str:
    """"too_close" (a sprinkler of ours already stands within reach),
    "not_in_field", or "unknown" when the words say neither."""
    said = (text or "").lower()
    if TOO_CLOSE_WORD in said:
        return "too_close"
    if NOT_IN_FIELD_WORD in said:
        return "not_in_field"
    return "unknown"
