"""Nectar levels off the buff bar: how full each of the five nectars is, 0-100.

WHY. The owner, 2026-10-10: nectar matters a great deal, and planters give a
lot of it; the research (docs/pending/brain-research.md) found it is the one
thing Natro's planters are built on and this bot never read.

HOW (Natro ba_GetNectarPercent): each nectar's icon fills from the bottom in its
own flat colour -- Comforting 0x7E9EB3, Motivating 0x937DB3, Satisfying 0xB398A7,
Refreshing 0x78B375, Invigorating 0xB35951 -- inside a 38 px icon at 1080p; the
filled height over the icon's height is the percent (100% = 24 h of nectar).
MEASURED 2026-10-11 00:14 (tests/fixtures/nectar/comforting-21.jpg): the
Comforting icon at x ~152-190, its colour in the bottom 8 of 38 rows -- 21% --
after one Blue Clay harvest.

WHAT IT REFUSES. No frame is no reading (every nectar None). On a frame, an
icon not found is 0 -- Natro's reading, and the bar shows every nectar held.
"""
from __future__ import annotations

import numpy as np

NECTARS = {
    "comforting": (126, 158, 179),
    "motivating": (147, 125, 179),
    "satisfying": (179, 152, 167),
    "refreshing": (120, 179, 117),
    "invigorating": (179, 89, 81),
}
# THE ICON ROW at 1080p, MEASURED on the fixture: icons from y 57, the fill's
# lowest row 94, the bar's own bottom edge below it. A fill RISES FROM THE
# BOTTOM, so only a run of the colour unbroken up from there counts -- the
# world through an icon's empty part, or anywhere else, does not start there.
ICON_BOTTOM = 94
BOTTOM_SLACK = 2              # the run may start this far above ICON_BOTTOM
X_SPAN = (0, 860)             # Natro's search width
ICON_PX = 38                  # an icon's height at 1080p
TOLERANCE = 30                # summed |R|+|G|+|B| from the nectar's colour (JPEG)
# THE ICONS' GRID: 38 px cells from the left edge (MEASURED on the fixtures:
# 0-37, 38-75, 76-113, 114-151, 152-189). A fill spans most of its cell's width
# at the bottom and starts at the cell's edge; the world behind the bar does
# not (2026-10-10 16:52, a wall at x 584-604 read as "satisfying 53%").
ICON_W = 38
MIN_COLUMNS = 10              # columns of a cell lit from the bottom: a fill, not a speck
EDGE_PX = 5                   # a fill reaches both sides of its cell at the bottom
ABOVE_PX = 12                 # rows read above an icon's top: the world goes on there
RUN_PERCENTILE = 80           # the icon's glyph breaks some columns' runs


def _runs(near: np.ndarray) -> np.ndarray:
    """Per column, the length of the matching run up from the bottom rows."""
    h, w = near.shape
    out = np.zeros(w, dtype=np.int32)
    for x in range(w):
        col = near[:, x]
        start = next((y for y in range(h - 1, max(-1, h - 2 - BOTTOM_SLACK), -1) if col[y]), None)
        if start is None:
            continue
        y = start
        while y >= 0 and col[y]:
            y -= 1
        out[x] = start - y
    return out


def read(frame) -> dict:
    """{nectar: percent 0-100}: 0 when its icon is not on the bar (Natro's
    reading too: no icon is no nectar); every one None when there is no frame."""
    out = {name: None for name in NECTARS}
    if frame is None or getattr(frame, "size", 0) == 0:
        return out
    out = {name: 0.0 for name in NECTARS}
    scale = frame.shape[0] / 1080.0
    icon = ICON_PX * scale
    bottom = int(round(ICON_BOTTOM * scale))
    # TALLER THAN AN ICON: a fill stops at its icon's top edge, the world's
    # colour (the sky behind the bar, MEASURED cells 13-15 reading "100%") goes on
    top = max(0, int(bottom - icon - ABOVE_PX * scale))
    x0, x1 = (int(v * scale) for v in X_SPAN)
    rgb = frame[top:bottom + 1, x0:x1, :3][:, :, ::-1].astype(np.int32)
    cell = ICON_W * scale
    for name, colour in NECTARS.items():
        near = np.abs(rgb - np.array(colour)).sum(axis=2) <= TOLERANCE
        runs = _runs(near)
        # CELL BY CELL: the icon whose cell has its colour rising from the
        # bottom across enough of its columns (the glyph breaks the middle ones)
        best = None
        for i in range(int(runs.size // cell) + 1):
            cols = runs[int(i * cell):int((i + 1) * cell)]
            lit = cols[cols >= 2]
            edge = max(1, int(EDGE_PX * scale))
            if (lit.size >= MIN_COLUMNS * scale
                    and (cols[:edge] >= 2).any() and (cols[-edge:] >= 2).any()
                    and float(np.median(lit)) <= icon + 2):
                height = float(np.percentile(lit, RUN_PERCENTILE))
                best = max(best or 0.0, height)
        if best is not None:
            out[name] = round(min(100.0, 100.0 * best / icon), 1)
    return out


def describe(levels: dict) -> str:
    seen = [f"{k} {v:.0f}%" for k, v in levels.items() if v]
    return ", ".join(seen) if seen else "no nectar on the buff bar"
