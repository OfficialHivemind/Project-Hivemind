"""An empty hive cell, seen: where an egg may hatch without replacing a bee.

THE OWNER'S FESTIVE BEE EGG (bought 2026-10-02 23:30) goes into the 35th
cell, bought 2026-10-03 06:01. An egg let go over a bee replaces that bee
(wiki Egg), and with an egg held EVERY cell turns green (MEASURED 06:54), so
the light does not say which cell is empty: the cell itself does.

MEASURED 2026-10-03 07:15 (var/shoplook/20261003-071515-egg-before.jpg,
the camera one PageDown up from 14 studs behind the pad): the empty cell is
one flat dark gold -- H 24, S 205, V 145, its spread under 5 -- where a bee's
cell is a face (spread 23-83 per channel). The same gold lies in the hive's
shadows and the pad's rim, but there it is no hexagon: the empty cell is a
solid blob about 82 x 56 px filling 0.80 of its box, the shadows under 0.6.
With the egg held over the hive the same cell turns one flat green (H 68,
S 234, V 233), which is the drag's check before it lets go.
"""
from __future__ import annotations

EMPTY_H = (18, 30)
EMPTY_S = (170, 235)
EMPTY_V = (120, 170)
# AND ZOOMED OUT (`small`, inside our hive's band only), V up to 190: MEASURED
# 2026-10-06 01:52, slot 38's empty cell read V 170-181 (median 181) in a
# brighter light than slot 37's 155-167 at 22:37, and at 170 it was not found
# (var/shoplook/20261006-015159-hatch-before-z6.jpg). Not near: at 02:36, with
# 190 for both, the zoomed-in look found ONE "cell" in the gold beside the hive
# (where 170 finds two, and the hatch zooms on) and the egg went there.
EMPTY_V_SMALL = (120, 190)
ROI = (700, 40, 1400, 620)             # x0, y0, x1, y1: where the hive stands in that view
AREA = (2000, 7000)
FILL_MIN = 0.70
ASPECT = (1.15, 1.9)                   # width over height of a hexagon lying flat
FLAT_V_STD = 12.0
LIT_H = (55, 80)                       # the held egg's green
LIT_S_MIN, LIT_V_MIN = 170, 180
LIT_SHARE = 0.6
HALF = (16, 12)                        # the patch read round a cell's centre
# THE POINTER IS ON THE CELL while the egg is held there: MEASURED 07:46, its
# white arrow and black outline in the centre patch put V's spread at 33 and
# the check said no to a lit cell. The arrow hangs down and right from its
# tip, so the lit test reads a patch above and left of the point.
LIT_PATCH = (-22, -14, -2, 2)          # x0, y0, x1, y1 from the point


# ZOOMED OUT, THE CELLS ARE SMALL. MEASURED 2026-10-05 22:37 (var/shoplook/
# 20261005-223751-hatch-before-z6.jpg, six zoom taps out): the whole hive in
# view and slot 37's empty cell at its top a blob of 644 px, 29 x 33 after the
# opening, 0.67 of its box -- under every test above -- while the empty cell of
# the hive beside ours, at x 1345, passed all but the area. So a small cell is
# taken only inside OUR hive's own column: the span of its bee cells' colours
# (saturated, not the hives' gold), which on that frame is x 905-1140.
SMALL_AREA = (500, 7000)
SMALL_FILL_MIN = 0.6
SMALL_ASPECT = (0.75, 1.9)
BEE_S_MIN, BEE_V_MIN = 120, 150
BAND_PAD = 30
BAND_BOTTOM = 570                       # the grass below the pads is not a bee


def hive_band(frame):
    """(x0, x1) of our hive's column in the ROI: where its bee cells' colours
    are (saturated, not gold), or None when there are too few to say."""
    import cv2
    import numpy as np
    x0, y0, x1, _y1 = ROI
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[y0:BAND_BOTTOM, x0:x1, :3]), cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    bee = (s >= BEE_S_MIN) & (v >= BEE_V_MIN) & ((h < EMPTY_H[0] - 3) | (h > EMPTY_H[1] + 5))
    xs = np.nonzero(bee)[1]
    if xs.size < 500:
        return None
    lo, hi = np.percentile(xs, (2, 98))
    return int(lo) + x0 - BAND_PAD, int(hi) + x0 + BAND_PAD


def hive_box(frame):
    """(x0, y0, x1, y1) of our hive's bee cells in the ROI -- where their
    colours are (saturated, not gold) -- or None when there are too few.
    For a scan over every cell in view (run_farm find_bee_by_card): a tilted
    view shows only some rows (MEASURED 2026-10-06 23:43, var/shoplook/
    20261006-234327-jelly-view.jpg: the hive's lowest rows, y 0-300)."""
    import cv2
    import numpy as np
    x0, y0, x1, _y1 = ROI
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[y0:BAND_BOTTOM, x0:x1, :3]), cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    bee = (s >= BEE_S_MIN) & (v >= BEE_V_MIN) & ((h < EMPTY_H[0] - 3) | (h > EMPTY_H[1] + 5))
    ys, xs = np.nonzero(bee)
    if xs.size < 500:
        return None
    (xlo, xhi), (ylo, yhi) = np.percentile(xs, (2, 98)), np.percentile(ys, (2, 98))
    return int(xlo) + x0, int(ylo) + y0, int(xhi) + x0, int(yhi) + y0


def scan_points(box, step: int = 90) -> list:
    """Points a step apart over `box`, the box's middle first, then outward."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    pts = [(x, y) for y in range(y0 + step // 3, y1, step) for x in range(x0 + step // 3, x1, step)]
    return sorted(pts, key=lambda q: abs(q[0] - cx) + abs(q[1] - cy))


def empty_cells(frame, small: bool = False) -> list:
    """[(x, y)] centres of the empty cells in view, most solid first. `small`:
    zoomed out -- the small-cell tests, inside our hive's band only."""
    import cv2
    import numpy as np
    if frame is None:
        return []
    band = hive_band(frame) if small else None
    if small and band is None:
        return []
    area_r, fill_min, aspect_r = ((SMALL_AREA, SMALL_FILL_MIN, SMALL_ASPECT) if small
                                  else (AREA, FILL_MIN, ASPECT))
    x0, y0, x1, y1 = ROI
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[y0:y1, x0:x1, :3]), cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    v_lo, v_hi = EMPTY_V_SMALL if small else EMPTY_V
    mask = ((h >= EMPTY_H[0]) & (h <= EMPTY_H[1]) & (s >= EMPTY_S[0]) & (s <= EMPTY_S[1])
            & (v >= v_lo) & (v <= v_hi)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, labels, stats, centres = cv2.connectedComponentsWithStats(mask)
    found = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        w, hh = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
        if not (area_r[0] <= area <= area_r[1]) or hh == 0:
            continue
        fill, aspect = area / float(w * hh), w / float(hh)
        if fill < fill_min or not (aspect_r[0] <= aspect <= aspect_r[1]):
            continue
        if float(v[labels == i].std()) > FLAT_V_STD:
            continue
        at = (int(centres[i][0]) + x0, int(centres[i][1]) + y0)
        if band is not None and not band[0] <= at[0] <= band[1]:
            continue
        found.append((fill, at))
    return [c for _f, c in sorted(found, reverse=True)]


def _patch(frame, x: int, y: int):
    import cv2
    import numpy as np
    hx, hy = HALF
    p = frame[max(0, y - hy):y + hy, max(0, x - hx):x + hx, :3]
    return cv2.cvtColor(np.ascontiguousarray(p), cv2.COLOR_BGR2HSV) if p.size else None


def lit(frame, x: int, y: int) -> bool:
    """The cell at (x, y) shows the held egg's flat green: it would take it.
    Read above and left of the point, clear of the pointer (LIT_PATCH)."""
    import cv2
    import numpy as np
    if frame is None:
        return False
    x, y = int(x), int(y)
    x0, y0, x1, y1 = LIT_PATCH
    p = frame[max(0, y + y0):y + y1, max(0, x + x0):x + x1, :3]
    if p.size == 0:
        return False
    hsv = cv2.cvtColor(np.ascontiguousarray(p), cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = (h >= LIT_H[0]) & (h <= LIT_H[1]) & (s >= LIT_S_MIN) & (v >= LIT_V_MIN)
    return float(green.mean()) >= LIT_SHARE and float(v.std()) <= FLAT_V_STD * 2


# THE CELL THE GAME TAKES glows white under the held egg: MEASURED 2026-10-03
# 06:54 (a bee's cell, from the pad) and 08:46 (the empty cell, from the pad,
# one zoom tap out) H 0, S 0, V 255, flat. It comes a moment after the pointer
# arrives (08:27 read green 0.15 s in), and from 14 studs back it never came
# (07:58, and the drop there did nothing). The drop is let go on it.
HOVER_S_MAX, HOVER_V_MIN = 40, 235


# AND ON A SMALL CELL (zoomed out, SMALL_*), a patch that stays inside it: the
# 29 x 33 cell of 22:37 is narrower than LIT_PATCH reaches.
LIT_PATCH_SMALL = (-9, -9, -1, 0)


def hovered(frame, x: int, y: int, small: bool = False) -> bool:
    """The cell at (x, y) glows the white of the cell the game takes for the
    held egg. Read above and left of the point, clear of the pointer."""
    import cv2
    import numpy as np
    if frame is None:
        return False
    x, y = int(x), int(y)
    x0, y0, x1, y1 = LIT_PATCH_SMALL if small else LIT_PATCH
    p = frame[max(0, y + y0):y + y1, max(0, x + x0):x + x1, :3]
    if p.size == 0:
        return False
    hsv = cv2.cvtColor(np.ascontiguousarray(p), cv2.COLOR_BGR2HSV)
    white = (hsv[..., 1] <= HOVER_S_MAX) & (hsv[..., 2] >= HOVER_V_MIN)
    return float(white.mean()) >= LIT_SHARE


# THE CARD A NEW BEE TYPE BRINGS. MEASURED 2026-10-03 09:55: after the
# Festive Bee hatched (09:27) the game's card -- "New Type Discovered! / You
# hatched a... / Festive Bee!!!" -- stayed up in the middle of the screen,
# over the character, for half an hour. Its close is a red box (43 x 33,
# 0.88-0.91 of it red) with a dark X, the card's yellow title bar right of it
# (0.72 yellow) and the card's dark body under it (0.58 dark). A red bee in a
# yellow hive cell (var/respawn/232609-pad.jpg, 2026-09-24) has the yellow
# beside it too, but is 0.75-0.81 red and has 0.05-0.09 dark under it.
CARD_RED_SIDE = (25, 70)
CARD_FILL_MIN = 0.85
CARD_YELLOW_MIN = 0.5
CARD_BODY_DARK_MIN = 0.35


def new_type_card_close(frame):
    """(x, y) of the new-type card's red close box, or None."""
    import cv2
    import numpy as np
    if frame is None:
        return None
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[:, :, :3]), cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = (((h <= 8) | (h >= 170)) & (s >= 140) & (v >= 110)).astype(np.uint8)
    yellow = (h >= 18) & (h <= 35) & (s >= 120) & (v >= 180)
    n, _labels, stats, _c = cv2.connectedComponentsWithStats(red, connectivity=8)
    for i in range(1, n):
        x, y, w, hh, area = (int(v_) for v_ in stats[i])
        if not (CARD_RED_SIDE[0] <= w <= CARD_RED_SIDE[1]
                and CARD_RED_SIDE[0] <= hh <= CARD_RED_SIDE[1]):
            continue
        if area < CARD_FILL_MIN * w * hh:
            continue
        right = yellow[y:y + hh, x + w:min(frame.shape[1], x + 3 * w)]
        body = v[y + hh + 4:y + hh + 120, x:x + 6 * w] < 90
        if (right.size and float(right.mean()) >= CARD_YELLOW_MIN
                and body.size and float(body.mean()) >= CARD_BODY_DARK_MIN):
            return (x + w // 2, y + hh // 2)
    return None


# A CELL'S COLOURS NAME ITS BEE'S RARITY AND COLOUR (wiki Hive: "The background
# color of the hive slot is based on the bee's rarity; bronze for Common, white
# for Rare, bright yellow for Epic, aqua blue for Legendary, light purple for
# Mythic, and green for Event", and the face is drawn "in the bee's color").
# So a Legendary red bee -- in this hive the Demon, the Royal Jelly's target
# (brain/hivejudge) -- is the one aqua cell with a red face. MEASURED on the
# hive look of 2026-10-03 06:21 (three PageUp taps from level, the bottom row
# seen from above): its aqua strip 54 x 24 at (1117, 249), H 85 S 169 V 184,
# 26% red (eyes and mouth) over it and as far again below; the Diamonds'
# and Ninjas' aqua cells hold no red at all.
AQUA = ((80, 100), 120, 140)            # H range, S min, V min
FACE_RED_MIN = 0.10
FACE_RED_PX = 150


def red_legendary_cells(frame) -> list:
    """(x, y) of each aqua (Legendary) cell holding a red face: the middle of
    its aqua strip, the face the game lets a click open (wiki Hive: "as long
    as you click the face of the bee"). A guess for a click that is then
    read, never a reason to use anything on it."""
    import cv2
    import numpy as np
    if frame is None:
        return []
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[:, :, :3]), cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    (lo, hi), smin, vmin = AQUA
    aqua = ((h >= lo) & (h <= hi) & (s >= smin) & (v >= vmin)).astype(np.uint8)
    red = ((h <= 8) | (h >= 170)) & (s >= 150) & (v >= 150)
    n, _labels, stats, _c = cv2.connectedComponentsWithStats(aqua, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, hh, area = (int(q) for q in stats[i])
        if area < 300:
            continue
        box = red[y:min(frame.shape[0], y + 2 * hh), x:x + w]
        if box.size and int(box.sum()) >= FACE_RED_PX and float(box.mean()) >= FACE_RED_MIN:
            out.append((x + w // 2, y + hh // 2))
    return out


# THE WHOLE HIVE IN VIEW, its cells by column. MEASURED 2026-10-06 05:38
# (var/shoplook/20261006-053827-hatch-before-z3.jpg -- from the pad, one
# PageDown and three zoom taps out, the egg hatch's view): five columns of
# cells 55.5 px apart, the first 46 px in from hive_box's left (box x
# 799-1120), each column's cells 53.5 px apart and every other column half a
# cell lower. A point every half cell down each column lands on a face or on
# the border between two (a click there opens one of them, or nothing). The
# colours cannot place the cells: the Basic Bee's brown face is under
# BEE_S_MIN, and it is the bee looked for.
COLUMNS = 5
COL_FROM, COL_STEP = 0.143, 0.173       # of hive_box's width


def column_points(box) -> list:
    """Points down the hive's columns every half cell, the top rows first --
    the newest cells, where the eggs bought for new slots hatched."""
    x0, y0, x1, y1 = box
    w = x1 - x0
    half = COL_STEP * w / 2
    pts = []
    for c in range(COLUMNS):
        x = int(round(x0 + COL_FROM * w + c * COL_STEP * w))
        y = y0 + half / 2
        while y < y1:
            pts.append((x, int(round(y))))
            y += half
    return sorted(pts, key=lambda q: (q[1], q[0]))


# EACH SLOT'S FACE IN THAT SAME VIEW (brain/hiveplanner's numbering: slot 1
# bottom left, rows of 5 upward, odd columns half a cell lower). MEASURED
# 2026-10-13 14:55 (var/shoplook/20261013-145524-jelly-view.jpg, 42 bees):
# column 0's faces at y 150, 205, 258, 310, 363, 415, 463, 515 (rows 9 to 2),
# column 1's at 178 to 545 -- so row 1 sits behind the pad's crowd at ~574.
# The columns' x come from hive_box as column_points' do. CALIBRATION KNOBS:
# a first live look (look-only, frames kept) should confirm ROW1_Y.
ROW1_Y, ROW_STEP, ODD_DROP = 574, 53, 27


def slot_point(box, slot: int) -> tuple:
    """(x, y) of a slot's face in the whole-hive view, `box` hive_box's."""
    x0, _y0, x1, _y1 = box
    w = x1 - x0
    col, row = (slot - 1) % COLUMNS, (slot - 1) // COLUMNS + 1
    return (int(round(x0 + COL_FROM * w + col * COL_STEP * w)),
            int(ROW1_Y - (row - 1) * ROW_STEP + (ODD_DROP if col % 2 else 0)))
