"""The bee menu's words: which list it is, how many bees it says, and each row.

THE OWNER, 2026-10-01: "the ai should be able to tell whats good bees in my
hive and follow that original blue bee guid". The bot had only his screenshot
of 20 Sep (data/knowledge/account.yaml: 26 bees, 28 types), so this reads the
menu that screenshot was of.

WHAT THE MENU IS, from the wiki's pictures of it (File:Beecounts-1.png,
File:Bee_Menu_Sample.png, read 2026-10-01): the third HUD button (the smiley,
vision/questmenu.BUTTONS, confirmed from the owner's screenshots) opens a list
down the left of the screen in the inventory's column, headed "You Have N
Bees" and "You've Discovered N Types of Bees", then one row a type: the
bee's face with "xN" under it, its name ("Basic Bee") and a line about it.
act/inventory reads that column; act/beemenu reads this one the same way.

THE HEADER IS THE CHECK. The rows' counts must add up to "You Have N Bees"
before the hive is called read (act/beemenu): a page the wheel skipped, or a
count misread, shows as a sum that does not.
"""
from __future__ import annotations

import re
from functools import lru_cache

import numpy as np

from ..datapaths import data
from . import questmenu

BUTTON_INDEX = questmenu.BUTTONS.index("bees")
TYPES_FILE = data("knowledge", "bee_types.yaml")

# THE EXAMPLE NAMES NO BEE ("Name Bee"), for the reason vision/inventory gives:
# the model copies examples, and a real name handed to it by the question is
# half of what `looks_like_bee_list` asks for.
TRANSCRIBE = ("This is the bee list of the game's bee menu. Copy the header "
              "lines at its top if the page shows them, then list every bee "
              "you can read, one per line, as the bee's name, a colon and the "
              "number written under its picture (shown as xN), e.g. "
              "'Name Bee: 3'. Reply with only the lines.")
TOTAL_QUESTION = ("At the top of this bee list, a line reads 'You Have N Bees'. "
                  "What is N? Reply with only the number, or 'none' if that "
                  "line is not on the page.")


def count_question(label: str) -> str:
    return (f"In this bee list, what number is written under the picture of the "
            f"{label} (shown as xN)? Reply with only the number, or 'none' if "
            f"the {label} is not on the page.")


@lru_cache(maxsize=1)
def types() -> dict:
    """{key: {label, rarity, colour}} from data/knowledge/bee_types.yaml."""
    import yaml
    try:
        body = yaml.safe_load(TYPES_FILE.read_text()) or {}
    except (OSError, ValueError):
        return {}
    return {str(k): dict(v or {}) for k, v in (body.get("types") or {}).items()}


def button(frame=None) -> tuple[int, int]:
    """Where the bee menu's button is (vision/questmenu's measured row)."""
    return questmenu.button_at(BUTTON_INDEX, frame)


_TOTAL = re.compile(r"you\s*(?:'?ve)?\s*have\s+(\d{1,3})\s*bees?\b", re.I)
_TYPES = re.compile(r"discovered\s+(\d{1,3})\s+types?\b", re.I)
# "Bubble Bee: 13", "Bubble Bee x13", "Bubble Bee (x13)", "- Bubble Bee: x13"
_ROW = re.compile(r"\b([A-Za-z]+)\s+bee\b\s*[:\-–(]*\s*[x×]?\s*(\d{1,3})\b", re.I)


def header(text: str) -> tuple[int | None, int | None]:
    """(N of "You Have N Bees", N of "You've Discovered N Types"), None for a
    line the text does not hold."""
    low = " ".join(str(text or "").split())
    total = _TOTAL.search(low)
    kinds = _TYPES.search(low)
    return (int(total.group(1)) if total else None,
            int(kinds.group(1)) if kinds else None)


def counts_in(text: str) -> dict:
    """{bee key: count} of every row the text gives a number for. The header's
    "You Have N Bees" is not a row: its word before "Bees" is not a type."""
    known = types()
    out: dict = {}
    for line in str(text or "").splitlines():
        for name, number in _ROW.findall(line):
            key = name.lower()
            if key in known:
                out[key] = int(number)
    return out


def names_in(text: str) -> set:
    """The bee types the text names at all, with a count or not."""
    low = " ".join(str(text or "").lower().split())
    return {k for k, v in types().items()
            if str(v.get("label") or "").lower() in low}


# THE LIST'S ROWS, the pixel sign that it is on screen (act/inventory rule 2).
# MEASURED 2026-10-01 22:29 on the first page the bot opened
# (var/beemenu/20261001-222944/page-00.png, the inventory's 306 x 922 crop):
# the inventory's item marker is on none of it, and down its left edge each
# bee's row is one colour for 120 px -- (196, 200, 203) for a colourless bee,
# (77, 135, 202) for a blue one -- with the next row's top 130 px below,
# within a rarity's section; the headers ("You Have 34 Bees") are 30 px bars.
# A uniform run alone is not enough: it fired on 15,105 of 35,480 saved route
# frames of the world. Two whole rows a pitch apart fired on none of 35,509,
# nor on any of the inventory's kept pages.
ROW_H, ROW_PITCH, ROW_TOL = 120, 130, 3
ROW_EDGE_X = 6                  # the columns looked at, from the crop's left
ROW_DEV = 6                     # how far a row's edge may stray from its colour


def _row_runs(image) -> list[tuple[int, int]]:
    """(top, bottom) of every left-edge run of one colour that is a row's
    height and a row's kind of colour (grey, or saturated)."""
    if image is None or getattr(image, "size", 0) == 0 or image.shape[1] < ROW_EDGE_X:
        return []
    edge = image[:, :ROW_EDGE_X, :3].astype(np.int16)
    col = np.median(edge, axis=1)
    out, y, n = [], 0, col.shape[0]
    while y < n:
        base = col[y]
        z = y
        while z + 1 < n and np.abs(col[z + 1] - base).max() <= ROW_DEV:
            z += 1
        if abs((z - y + 1) - ROW_H) <= 4:
            block = edge[y:z + 1]
            spread = float(base.max() - base.min())
            grey = spread <= 14 and 170 <= float(base.mean()) <= 240
            if np.abs(block - base).max() <= ROW_DEV + 6 and (grey or spread >= 80):
                out.append((int(y), int(z)))
        y = z + 1
    return out


def bee_rows(image) -> list[int]:
    """The tops of the bee list's whole rows that have another a row pitch
    above or below them; [] when the list is not on screen."""
    tops = [a for a, _b in _row_runs(image)]
    return [t for t in tops
            if any(abs(abs(t - u) - ROW_PITCH) <= ROW_TOL for u in tops if u != t)]


# THE HEADER, BY TESSERACT. MEASURED on the same page: the model asked to
# transcribe it skipped both header lines and wrote a count for each of the
# five rows -- "Basic Bee: 3", "Bomber Bee: 2", ... -- where the page draws
# none (those types are not in the hive); tesseract read the 30 px bars
# exactly, "You Have 34 Bees" and "You've Discovered 33 Types of Bees", from
# the crop's y 15-100 at x3 (only the `afr` tessdata is installed).
HEADER_BAND = (15, 100)
TESSERACT, LANGUAGE, OCR_TIMEOUT_S = "tesseract", "afr", 8.0


def ocr_header(image, run=None) -> tuple[int | None, int | None]:
    """(bees, types) from the header bars at the top of a list crop, by
    tesseract; (None, None) when the page does not show them."""
    import subprocess
    import cv2
    if image is None or getattr(image, "size", 0) == 0:
        return None, None
    y0, y1 = HEADER_BAND
    crop = image[y0:y1, :, :3]
    if crop.size == 0:
        return None, None
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    big = cv2.resize(grey, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    ok, png = cv2.imencode(".png", big)
    if not ok:
        return None, None
    try:
        out = (run or subprocess.run)(
            [TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "6"],
            input=png.tobytes(), capture_output=True, timeout=OCR_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None, None
    text = out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes) \
        else str(out.stdout)
    return header(text)


# ONE ROW AT A TIME. MEASURED on the first page's four whole rows (Basic,
# Bomber, Brave, Bumble -- none of them in the hive, so no count drawn): asked
# of the row's own crop, the model named all four right and answered "none" for
# the count of all four, where the whole page's transcription had invented a
# count for each. Two phrasings, so one row read once still has two readings.
ROW_NAME_QUESTION = "What is the bee's name written on this row? Reply with only the name."
ROW_COUNT_QUESTION = (
    "This is one row of a list of bee types. Under or on the square picture of "
    "the bee, at its bottom right, the game writes how many of this bee the "
    "player has, like x3 -- but only when the player has some. Is such a "
    "number written on this row? Reply with only the number, or none if no "
    "number is written.")
ROW_COUNT_AGAIN = (
    "How many of this bee does this row of the list say the player has? The "
    "game writes it like x3 at the bottom right of the bee's square picture, "
    "and writes nothing when the player has none. Reply with only the number, "
    "or none.")


# THE GIFTED STAR, in a row's top-right corner: dark (a gifted one of that type
# is in the hive now), faded (gifted once, none now) or none (never). MEASURED
# 2026-10-09 on var/beemenu/20261009-085621: the dark rows 0.166-0.179 of the
# corner under grey 70, the faded and starless ones 0.000-0.005.
STAR_CORNER = (0.40, 0.86)          # the row's top 40%, from 86% of its width
STAR_DARK_SHARE = 0.08


def gifted_star(row) -> bool:
    """Whether a row's star is the dark one: a gifted bee of its type held."""
    import cv2
    h, w = row.shape[:2]
    corner = row[:int(h * STAR_CORNER[0]), int(w * STAR_CORNER[1]):]
    if corner.size == 0:
        return False
    grey = cv2.cvtColor(corner, cv2.COLOR_BGR2GRAY) if corner.ndim == 3 else corner
    return float((grey < 70).mean()) > STAR_DARK_SHARE


def row_crops(image) -> list:
    """(top, the row's crop) of every whole row of a page of the list."""
    out = []
    for top, bottom in _row_runs(image):
        out.append((top, image[max(0, top - 4):bottom + 6]))
    return out


def match_name(text: str | None) -> str | None:
    """The bee type a row's name reads as, or None."""
    import difflib
    low = " ".join(str(text or "").lower().replace("'", " ").split())
    if not low:
        return None
    labels = {str(v.get("label") or "").lower(): k for k, v in types().items()}
    if low in labels:
        return labels[low]
    if not low.endswith(" bee"):
        low += " bee"
    near = difflib.get_close_matches(low, list(labels), n=1, cutoff=0.85)
    return labels[near[0]] if near else None


def looks_like_bee_list(text: str) -> bool:
    """The header, two different types each given a count, or three types
    named. A quest panel names bees ("Bucko Bee: Pollen") -- but the words are
    asked only after `bee_rows` found the list's rows, which it did on none of
    25 saved quest-menu frames and none of 25 inventory pages."""
    total, kinds = header(text)
    return (total is not None or kinds is not None or len(counts_in(text)) >= 2
            or len(names_in(text)) >= 3)
