"""The quest list's pixels: its scrollbar, its rows, and a list longer than the panel.

THE OWNER'S STANDING ASK: "do his quests". The quest list is a scrolling panel
and the bot read only what the panel shows. MEASURED 2026-09-29 on the kept
open menus (var/quest_reads/close-*-open.jpg and -after.jpg, 2026-09-27 to 29):
the scrollbar's thumb ran from y 176 to 516 of a track to about 966 -- 43% of
it -- so more than half the list was never read. The Science Bear's "Limits of
Language" read as four steps where the wiki lists six (Science_Bear, fetched
2026-09-29: "Craft 50 Ingredients with the Blender." and "Defeat 50 Ants."),
and whatever quests are below it not at all. act/questscroll turns the wheel;
this module is what it sees.

MEASURED, ALL ON THOSE FRAMES (1920x1080):
  - THE THUMB, x 311-317 in its middle: rows 176-516 on six of the seven
    reads, 177-506 on the longest list, 176-767 on 2026-09-24's shorter one
    (024501.jpg) -- always from the top: every kept read opened at the top.
    It is see-through, and so is its track: BGR = 0.10 x the world + (194,
    184, 164) for the thumb and 0.175 x the world + (136, 115, 75) for the
    track, so over any world the thumb's red is 164 or more and the track's
    120 or less. Row by row, over 4,579 thumb rows and 5,522 track rows, the
    thumb's red was 165 or more at its 1st percentile and the track's never
    above 129: a row is thumb at THUMB_MIN_RED 147, halfway.
  - THE SCROLLBAR'S BORDER, x 307: BGR (126, 110, 76) within 25 on 99.9% of
    the track's rows on every open menu, and on 0.4% of the same rows of the
    world with the menu shut. Red alone is no test on the world -- the gold
    of the hive wall read as a thumb at rows 677-898 of close-065946-before
    -- so a thumb counts only beside this border.
  - THE LIST, left of the scrollbar (x 0-305), opaque: a quest is a white
    title bar 30 px tall, its steps coloured bars 40 px tall on a 50 px
    pitch set in from x ~15, and a dark band 10 px tall before the next
    quest. The margin (x 4) is the panel's own colour beside the step bars,
    so a row where x 16 is the margin's colour is not inside a step bar.

NOT MEASURED, because nothing kept shows a scrolled list: how far one notch
moves it, whether the rows above the first title scroll with it, and where
the thumb stops at the bottom. act/questscroll measures the first two live
before it believes anything and keeps what it saw; the bottom is never
needed -- the list's end is where the wheel stops moving it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

THUMB_X = (311, 318)           # the thumb's middle columns, [x0, x1)
TRACK_TOP = 176                # the thumb's top at the top of the list
TRACK_BOTTOM = 966             # the track's last row seen under the thumb
THUMB_MIN_RED = 147            # see the module note
THUMB_MIN_ROWS = 20
THUMB_GAP = 2                  # rows under THUMB_MIN_RED a run bridges
BORDER_X = 307                 # the scrollbar's dark left border
BORDER_BGR = (126, 110, 76)
BORDER_NEAR = 25.0
BORDER_SHARE = 0.9             # of the track's rows
AT_TOP_SLACK = 3
# A thumb this much of the track is a list the panel shows whole.
FITS_SHARE = 0.95

# The list, as it is pictured and compared: left of the scrollbar's border
# (x 306) and 8 px inside the thumb's first and last rows, clear of the
# panel's frame.
LIST_BOX = (0, 180, 306, 962)  # x0, y0, x1, y1

# ROWS THAT MAY BE CUT (`cut_rows`): the margin and the step bars' column.
MARGIN_X = (2, 7)
BAR_X = (14, 19)
TEXT_X = (14, 300)
INSIDE_BAR = 25                # max channel difference, bar column vs margin
TEXT_FREE = 40                 # max distance from the row's median colour
# A chunk handed to the reader is at most a panel's height, and at least
# this much of one, so a cut is never forced into the first rows.
CHUNK_LEAST = 200


@dataclass(frozen=True)
class Thumb:
    top: int
    bottom: int

    @property
    def rows(self) -> int:
        return self.bottom - self.top + 1

    @property
    def share(self) -> float:
        """How much of the track the thumb is: the share of the list shown."""
        return self.rows / float(TRACK_BOTTOM - TRACK_TOP + 1)

    @property
    def at_top(self) -> bool:
        return self.top <= TRACK_TOP + AT_TOP_SLACK

    @property
    def fits(self) -> bool:
        """The panel shows the whole list."""
        return self.share >= FITS_SHARE


def thumb(frame) -> Thumb | None:
    """The scrollbar's thumb, or None when there is none to see."""
    if frame is None or getattr(frame, "ndim", 0) != 3:
        return None
    h = frame.shape[0]
    y0, y1 = max(0, TRACK_TOP - 10), min(h, TRACK_BOTTOM + 10)
    if y1 - y0 < THUMB_MIN_ROWS or not has_scrollbar(frame):
        return None
    red = frame[y0:y1, THUMB_X[0]:THUMB_X[1], 2].astype(np.float32).mean(axis=1)
    lit = red >= THUMB_MIN_RED
    best, start, dark = None, None, 0
    for i, on in enumerate(list(lit) + [False] * (THUMB_GAP + 1)):
        if on:
            if start is None:
                start = i
            dark, end = 0, i
        elif start is not None:
            dark += 1
            if dark > THUMB_GAP:
                if best is None or end - start > best[1] - best[0]:
                    best = (start, end)
                start, dark = None, 0
    if best is None or best[1] - best[0] + 1 < THUMB_MIN_ROWS:
        return None
    return Thumb(top=y0 + best[0], bottom=y0 + best[1])


def has_scrollbar(frame) -> bool:
    """Is the list's scrollbar on screen: its dark border down the track?"""
    if frame is None or getattr(frame, "ndim", 0) != 3 or frame.shape[1] <= BORDER_X:
        return False
    column = frame[TRACK_TOP:TRACK_BOTTOM + 1, BORDER_X, :3].astype(np.float32)
    if column.shape[0] == 0:
        return False
    near = np.linalg.norm(column - np.array(BORDER_BGR, np.float32), axis=1) <= BORDER_NEAR
    return float(near.mean()) >= BORDER_SHARE


def list_crop(frame) -> np.ndarray:
    """The list's part of a frame (LIST_BOX), as a copy."""
    x0, y0, x1, y1 = LIST_BOX
    return np.ascontiguousarray(frame[y0:y1, x0:x1, :3]).copy()


def cut_rows(image) -> np.ndarray:
    """Rows of a list image a cut may go through: not inside a step bar,
    where the bar column is the margin's colour, and free of text, where
    nothing differs much from the row's own colour -- so no line of text is
    split, and no step is parted from its own "Complete!"."""
    img = image[:, :, :3].astype(np.int16)
    margin = img[:, MARGIN_X[0]:MARGIN_X[1]].mean(axis=1)
    bar = img[:, BAR_X[0]:BAR_X[1]].mean(axis=1)
    outside = np.abs(bar - margin).max(axis=1) < INSIDE_BAR
    text = img[:, TEXT_X[0]:TEXT_X[1]]
    median = np.median(text, axis=1)
    spread = np.abs(text - median[:, None, :]).max(axis=2).max(axis=1)
    return outside & (spread < TEXT_FREE)


# HOW FAR THE LIST MOVED between two pictures of it. act/inventory's
# `shift_between` finds the middle band of the new picture in the old one,
# which measures at most about half a page; a page is advanced three
# quarters of one here, so the new picture's TOP band is found instead, and
# only where the move was expected to put it -- the list is a stack of
# look-alike bars 50 px apart, and a match one bar out must never win.
SHIFT_BAND = 130               # rows of the new picture looked for
SHIFT_MATCH = 0.9              # act/inventory's: the same picture, moved


def vertical_shift(before, after, most: int | None = None) -> tuple[int, float]:
    """(rows the list moved UP from `before` to `after`, match score), the
    move looked for from 0 to `most` rows (the whole picture when None). A
    list scrolled down shows at its top what was lower in `before`."""
    import cv2
    a = cv2.cvtColor(np.ascontiguousarray(before[:, :, :3]), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(np.ascontiguousarray(after[:, :, :3]), cv2.COLOR_BGR2GRAY)
    band = min(SHIFT_BAND, b.shape[0] // 2)
    reach = a.shape[0] - band if most is None else min(a.shape[0] - band, int(most))
    if reach < 0:
        return 0, 0.0
    scores = cv2.matchTemplate(a[:reach + band], b[:band], cv2.TM_CCOEFF_NORMED)[:, 0]
    at = int(np.argmax(scores))
    return at, float(scores[at])


def stitch(pages) -> np.ndarray:
    """One picture of the whole list from [(list image, its top row)], each
    top the list's measured scroll from the first."""
    height = max(top + img.shape[0] for img, top in pages)
    width = pages[0][0].shape[1]
    canvas = np.zeros((height, width, 3), np.uint8)
    for img, top in sorted(pages, key=lambda p: p[1]):
        canvas[top:top + img.shape[0]] = img[:, :, :3]
    return canvas


def chunks(canvas, most: int) -> list | None:
    """The canvas cut into pieces of at most `most` rows, each cut on a row
    `cut_rows` allows; None when some stretch has no such row -- a cut there
    would split something, and nothing is read from a guess."""
    allowed = cut_rows(canvas)
    out, start, h = [], 0, canvas.shape[0]
    while h - start > most:
        window = np.flatnonzero(allowed[start + CHUNK_LEAST:start + most + 1])
        if window.size == 0:
            return None
        cut = start + CHUNK_LEAST + int(window[-1])
        out.append(canvas[start:cut])
        start = cut
    out.append(canvas[start:])
    return out


# A SIDE PANEL LEFT OPEN (the quest list, the badge list -- both x 0-320 with
# this border at x 306-307). MEASURED 2026-10-14 over every route start frame of
# 10-05..10-14 (var/routes/attempt-*/*-00-start.jpg, 2,753 judged runs): the
# border column's colour varies by under PANEL_EDGE_STD down rows 180-960 on an
# open panel (std 8-19) and by 34+ on the world, while the list beside it
# (x 300) varies by PANEL_LIST_STD or more (a dark corridor is flat in both).
# With a panel open 6 of 15 runs landed elsewhere, 4 of the 6 flights; with
# none 449 of 2,738. The badge list's border is orange (BGR ~31,107,154,
# var/badges/20261014-170733/page.jpg), the quest list's blue-grey
# (BORDER_BGR, close-223527-open.jpg).
PANEL_EDGE_X = 307
PANEL_LIST_X = 300
PANEL_ROWS = (180, 960)
PANEL_EDGE_STD = 20.0
PANEL_LIST_STD = 40.0
PANEL_COLOURS = {"quests": BORDER_BGR, "badges": (31, 107, 154)}
PANEL_COLOUR_NEAR = 40.0


def side_panel(frame) -> str | None:
    """Which HUD side panel is open: "quests", "badges", "panel" (one whose
    border colour is not known), or None."""
    if frame is None or getattr(frame, "ndim", 0) != 3:
        return None
    h, w = frame.shape[:2]
    if h < PANEL_ROWS[1] or w <= PANEL_EDGE_X:
        return None
    edge = frame[PANEL_ROWS[0]:PANEL_ROWS[1], PANEL_EDGE_X, :3].astype(np.float32)
    beside = frame[PANEL_ROWS[0]:PANEL_ROWS[1], PANEL_LIST_X, :3].astype(np.float32)
    if edge.std(axis=0).max() > PANEL_EDGE_STD or beside.std(axis=0).max() < PANEL_LIST_STD:
        return None
    colour = edge.mean(axis=0)
    for name, bgr in PANEL_COLOURS.items():
        if np.linalg.norm(colour - np.array(bgr, np.float32)) <= PANEL_COLOUR_NEAR:
            return name
    return "panel"
