"""The Memory Match board: whether it is up, where its tiles are, what each shows.

THE OWNER, 2026-09-28, asked for Memory Match.

WHERE EACH FACT COMES FROM. None is measured on this machine yet: the machines
are in the place survey read-only (run_farm PLACE_ROUTES), and the player
(act/memorymatch) presses nothing until a frame of the board here has checked
every constant below. They are Natro Macro's, read from its source
(submacros/natro_macro.ahk nm_SolveMemoryMatch 12836-13090, and its reference
patches nm_image_assets/memorymatch/bitmaps.ahk, looked at 2026-09-28 and not
copied -- Natro is GPL-3):
  - the board opens when E is pressed at the machine, and its title bar is
    gold with "Memory Match" in dark brown, in the 500x50 px band whose top
    left is (middle x - 250, middle y - 210); the bar is 300 px wide for the
    16-tile board and 400 px for the 20-tile one (MMTitle, MMTitleWide);
  - the tiles are 4 rows of 4, or of 5, 80 px apart: column c (1..4) at
    middle x - 200 + 80c, less 40 px for the 5-column board, row r (1..4) at
    middle y - 200 + 80r;
  - a tile showing nothing is flat brown, BGR about (56, 115, 159)
    (MMEmptyTile); Natro waits after a click until the tile is not that;
  - the chances left are a dark digit on gold -- Natro's 100x100 px square at
    (middle x - 275 - offset, middle y - 146) also holds "Chances:" and
    "Badge Chances:" and read nothing on any frame here; see CHANCES_AT;
  - two tiles hold the same prize when one's 50x50 px picture is found in the
    other's (Natro: Gdip_ImageSearch at variation 10).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

import cv2
import numpy as np

FRAME_SIZE = (1920, 1080)
MIDDLE = (FRAME_SIZE[0] // 2, FRAME_SIZE[1] // 2)
TITLE_BAND = (MIDDLE[0] - 250, MIDDLE[1] - 210, MIDDLE[0] + 250, MIDDLE[1] - 160)
TITLE_WORDS = "memorymatch"
# a gold bar wider than this is the 20-tile board. MEASURED 2026-10-12 18:03
# (var/memorymatch/20261012-180227): the 16-tile card's bar is 384 px
# (x 768-1151), which Natro's 350 called 20 tiles -- every click then
# landed 40 px left, between tiles.
# ponytail: the 20-tile bar is not measured yet; one more 80 px column
# makes it ~464, so the cut sits halfway.
BAR_WIDE_FROM = 424
PITCH = 80
FIRST = 200                    # middle - 200 + 80 * index
WIDE_SHIFT = 40
ROWS = 4
FACE = 50                      # the square read as a tile's prize
HIDDEN_BGR = (56, 115, 159)
HIDDEN_TOLERANCE = 28.0        # mean distance from HIDDEN_BGR
HIDDEN_MAX_SPREAD = 22.0       # a flat tile: little variation inside
SAME_MIN = 0.90                # normalised correlation for "the same prize"
# THE CHANCES DIGIT, MEASURED 2026-10-14 on every board frame kept in
# var/memorymatch (33 games, 2026-10-12..14): the digit alone sits in x
# middle - 224 +- 25 (less 40 on the 20-tile board), y middle - 108 .. - 77,
# between "Chances:" (ends y middle - 125) and "Badge Chances:" (from middle -
# 63). Read there, tesseract (afr, the only language installed) gives 6 6 D A
# 3 2 I O through a 16-tile game -- 6 chances, 3 from badges -- and D D A 3 2
# I O through a 20-tile one: D is its 5, A its 4, I its 1, O its 0, every time.
CHANCES_AT = (MIDDLE[0] - 224, MIDDLE[1] - 118, MIDDLE[1] - 66)   # x centre, y0, y1
CHANCES_HALF = 35
CHANCES_GLYPHS = {"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "i": "1",
                  "A": "4", "D": "5", "S": "5", "s": "5"}
CHANCES_MOST_DARK = 0.4        # a box darker than this is not the gold card
GOLD_HUE = (15, 35)            # OpenCV hue of the title bar's gold
GOLD_MIN_S, GOLD_MIN_V = 90, 150
TESSERACT, LANGUAGE, TIMEOUT_S = "tesseract", "afr", 8.0


@dataclass
class Board:
    tiles: int                 # 16 or 20
    centres: list              # [(x, y)] by tile number - 1, column by column

    @property
    def columns(self) -> int:
        return self.tiles // ROWS


def centres(tiles: int) -> list[tuple[int, int]]:
    """Natro's grid, numbered column by column (its GridOAC order)."""
    columns = tiles // ROWS
    shift = WIDE_SHIFT if columns == 5 else 0
    out = []
    for c in range(1, columns + 1):
        for r in range(1, ROWS + 1):
            out.append((MIDDLE[0] - FIRST + PITCH * c - shift, MIDDLE[1] - FIRST + PITCH * r))
    return out


def _ocr_line(image, run) -> str:
    ok, png = cv2.imencode(".png", image)
    if not ok:
        return ""
    try:
        out = run([TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "7"],
                  input=png.tobytes(), capture_output=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    text = out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes) else str(out.stdout)
    return text.strip()


def _clean(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalpha())


def read_board(frame, run=subprocess.run) -> Board | None:
    """The board when its title bar is up and reads "Memory Match", else None."""
    if frame is None or frame.shape[:2] != (FRAME_SIZE[1], FRAME_SIZE[0]):
        return None
    x0, y0, x1, y1 = TITLE_BAND
    band = np.ascontiguousarray(frame[y0:y1, x0:x1, :3])
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    gold = ((hsv[..., 0] >= GOLD_HUE[0]) & (hsv[..., 0] <= GOLD_HUE[1])
            & (hsv[..., 1] >= GOLD_MIN_S) & (hsv[..., 2] >= GOLD_MIN_V))
    columns = np.flatnonzero(gold.mean(axis=0) > 0.3)
    if columns.size == 0:
        return None
    # dark letters on the gold, made black on white for one line of reading
    letters = (hsv[..., 2] < 110) & (gold.mean(axis=0) > 0)[None, :]
    page = np.where(letters, 0, 255).astype(np.uint8)
    page = cv2.resize(cv2.copyMakeBorder(page, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255),
                      None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    if TITLE_WORDS not in _clean(_ocr_line(page, run)):
        return None
    tiles = _tiles(frame, columns[-1] - columns[0] + 1)
    return Board(tiles=tiles, centres=centres(tiles))


def _tiles(frame, bar_width: int) -> int:
    """16 or 20, by THE TILES THEMSELVES first: a 20-tile board's outer
    columns (x 800 and 1120 on its top row) are face-down tiles, where a
    16-tile board has its card's gold edge (MEASURED 2026-10-12 18:03,
    var/memorymatch/20261012-180227: card x 768-1151, tiles 840-1080). Only
    when neither layout's outer tiles read face-down (a flipped corner,
    mid-game) does the title bar's width decide."""
    wide, narrow = centres(20), centres(16)
    try:
        if is_hidden(face(frame, wide[0])) and is_hidden(face(frame, wide[-1])):
            return 20
        if is_hidden(face(frame, narrow[0])) and is_hidden(face(frame, narrow[-1])):
            return 16
    except Exception:
        pass
    return 20 if bar_width > BAR_WIDE_FROM else 16


def face(frame, centre) -> np.ndarray:
    """The FACE x FACE square a tile's prize is read from."""
    x, y = centre
    h = FACE // 2
    return np.ascontiguousarray(frame[y - h:y + h, x - h:x + h, :3]).copy()


def is_hidden(square) -> bool:
    """A tile showing no prize: flat, and the tiles' own brown."""
    if square is None or square.size == 0:
        return False
    inner = square[FACE // 5:-FACE // 5, FACE // 5:-FACE // 5].reshape(-1, 3).astype(np.float32)
    mean = inner.mean(axis=0)
    return (float(np.linalg.norm(mean - np.array(HIDDEN_BGR, np.float32))) <= HIDDEN_TOLERANCE
            and float(inner.std(axis=0).mean()) <= HIDDEN_MAX_SPREAD)


def content(square) -> float:
    """How much prize the square shows: the share of edge pixels (Canny).
    A face still popping up is smaller, so fewer; the game's reveal FLASH
    (a flat yellow square) has almost none. MEASURED 2026-10-15
    (var/memorymatch/20261015-052145, -070719): prizes 0.13-0.25, the
    flash 0.04, a Royal Jelly full 0.23 vs popping 0.20. A first version
    counted pixels far from the tile's brown, and the flash won it."""
    if square is None or square.size == 0:
        return 0.0
    grey = cv2.cvtColor(np.ascontiguousarray(square[..., :3]), cv2.COLOR_BGR2GRAY)
    return float((cv2.Canny(grey, 60, 140) > 0).mean())


def likeness(a, b) -> float:
    """How alike two tiles' prizes are: the best normalised correlation of
    a's middle within b, allowing a few pixels' shift."""
    if a is None or b is None or a.size == 0 or b.size == 0:
        return 0.0
    m = FACE // 8
    probe = np.ascontiguousarray(a[m:-m, m:-m])
    score = cv2.matchTemplate(np.ascontiguousarray(b), probe, cv2.TM_CCOEFF_NORMED)
    return float(score.max())


def same_prize(a, b) -> bool:
    return likeness(a, b) >= SAME_MIN


def read_chances(frame, board: Board, run=subprocess.run) -> int | None:
    """The chances left, read as a number, or None (no gold card there, or
    a read that is not one or two digits)."""
    if frame is None or frame.shape[:2] != (FRAME_SIZE[1], FRAME_SIZE[0]):
        return None
    shift = WIDE_SHIFT if board.columns == 5 else 0
    x, y0, y1 = CHANCES_AT
    x -= shift
    square = np.ascontiguousarray(frame[y0:y1, x - CHANCES_HALF:x + CHANCES_HALF, :3])
    dark = cv2.cvtColor(square, cv2.COLOR_BGR2HSV)[..., 2] < 110
    if not dark.any() or dark.mean() > CHANCES_MOST_DARK:
        return None
    page = np.where(dark, 0, 255).astype(np.uint8)
    page = cv2.resize(cv2.copyMakeBorder(page, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255),
                      None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    text = "".join(CHANCES_GLYPHS.get(ch, ch) for ch in _ocr_line(page, run) if not ch.isspace())
    return int(text) if text.isdigit() and len(text) <= 2 else None
