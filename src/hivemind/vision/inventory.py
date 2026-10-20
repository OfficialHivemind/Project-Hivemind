"""The inventory menu, as a picture: where it is, and how its words are read.

THE OWNER'S REQUEST: "make sure it rechecks what i have and so it knows what
goals". The goal materials -- 9,999 treats for the Honey Mask, the Guards'
extracts and stingers -- were counts nobody had seen since his screenshot of
20 Sep. `act/inventory` opens the menu and asks; this file is what it knows
about the menu without having seen it.

NOTHING HERE HAS BEEN SEEN ON THIS MACHINE. No frame in var/ shows the item
menu open, so every figure below is Natro Macro's, cited where it is used,
and the first live reads keep their pictures (var/inventory/) so the figures
can be measured and the counts checked. Natro's inventory code
(lib/nm_InventorySearch.ahk, lib/nm_OpenMenu.ahk):

  * the menu opens from the first HUD button: `nm_OpenMenu` clicks x = 30
    (the buttons 55 apart, "itemmenu" first) at window-y + offsetY + 120 --
    our own measured row is x = 27 + 56i at y = 128 (vision/questmenu), and
    the owner's screenshots confirmed the first one is the inventory (egg);
  * the list is one column on the left: Natro pictures x 0..306 from
    offsetY + 150 down to the bottom of the window, and scrolls it with the
    mouse wheel with the pointer parked at (30, offsetY + 200);
  * each item is 80 px tall, marked on its left by a 3 x 20 px strip of one
    colour, RGB (212, 221, 218) (`bitmaps["item"]`, natro_macro.ahk:8231),
    which nm_InventorySearch looks for at the list's very left edge --
    `Gdip_ImageSearch(pBMScreen, bitmaps["item"], , , , 6, , 2)` is OuterX2
    = 6 and Variation = 2 in Gdip_ImageSearch's own argument order
    (lib/Gdip_ImageSearch.ahk:73) -- and reads as "the list is there": with
    no marker it returns 0 WITHOUT turning the wheel ("image 20px, item 80px
    => y+20-80 = y-60").

Our offsetY is 8: the same buttons sit at y = 128 here and at offsetY + 120
in Natro. So the panel is y 158..1080, x 0..306 -- and the quest menu's own
panel, measured from a real frame (run_farm QUEST_MENU_BOX, x 0..330 from
y 160), sits in the same place, which is the one cross-check to hand.
"""
from __future__ import annotations

import re

import numpy as np

from . import questmenu

# Where the list is, in a 1920x1080 frame (see the module note).
NATRO_OFFSET_Y = 128 - 120
INVENTORY_BOX = (0, 150 + NATRO_OFFSET_Y, 306, 1080 - (150 + NATRO_OFFSET_Y))
# Where the pointer waits while the wheel scrolls the list (Natro: 30, +200).
SCROLL_AT = (30, 200 + NATRO_OFFSET_Y)
# The inventory is the first HUD button (vision/questmenu.BUTTONS).
BUTTON_INDEX = questmenu.BUTTONS.index("inventory")

# Natro's item marker: 3 x 20 px of RGB (212, 221, 218), variation 2, with
# its left edge in x 0..3 of the list (OuterX2 = 6 less the 3 px width).
ITEM_MARK_RGB = (212, 221, 218)
ITEM_MARK_VARIATION = 2
ITEM_MARK_RUN = 20
ITEM_MARK_WIDTH = 3
ITEM_MARK_X = 6
ITEM_PITCH = 80

# UNDER THE RED DAMAGE VIGNETTE the marker is not its own colour. MEASURED
# 2026-10-12 22:22 (var/inventory/20261012-222209, a Ladybug fight in the
# Mushroom Field): the whole edge read BGR (161..175, 163..176, 205..207),
# darkest at the top and bottom -- a smooth screen-space overlay, no world
# texture through it (the panel is opaque: (218, 221, 212) exactly over
# grey floor and green field alike). Every one of its 784 edge rows fits
# out = k * marker + (1 - k) * (0, 0, red): blue and green scaled by the
# same k (0.58..0.80 here), the red the overlay's own (fitted 187). Natro
# waits for it to fade ("wait for red vignette effect to disappear",
# nm_InventorySearch); in a fight it does not, so a marker seen through it
# counts too -- that colour line and nothing else: plain dimming (red
# scaled with the rest) or any other tint is still not the marker.
VIGNETTE_K = (0.55, 0.97)          # how much of the marker shows through
VIGNETTE_RED = (120, 255)          # the overlay's own red
VIGNETTE_TOLERANCE = 2            # its fit: 0.7 at the 99th percentile
# THAT COLOUR ALONE IS NOT ENOUGH: pale greys and pinks of the world pass it
# (627 of the 139,306 route frames, 2026-10-12). So under the vignette the
# marker must also be the LIST's shape: item rows ITEM_ROW_PITCH apart,
# VIGNETTE_ROWS gaps in a row. MEASURED on every kept page (25 pages, 5
# reads, 2026-10-02/12): the rows (first markers, a gap of more than 30
# starting the next) are 90 px apart 7-8 times on each page, the vignetted
# one included. With it, no route frame of the world passes; the two it adds
# to the exact test's 630 both show the list under the vignette
# (attempt-613 030643, a Pine Tree pattern). A lossy (JPEG) frame jitters
# the rows; the live frames and kept pages are lossless.
ITEM_ROW_PITCH = 90
ITEM_ROW_PITCH_TOLERANCE = 2
VIGNETTE_ROWS = 3

# Names that say the panel is the inventory and not some other menu: the
# goal materials (goals.yaml), what his 20 Sep screenshot of it held
# (account.yaml `inventory`), and the other items the materials research
# names as held and blended (salvage materials_research.json: the Blender's
# inputs, "materials none of these need", the eggs) -- so a page of fruit,
# waxes or potions, wherever the list was left, still reads as the list.
# Field and shop names are left out ("Strawberry Field", "Pineapple Patch",
# "Coconut Field"): a quest panel is full of them. Two different ones must
# be read, for the same reason `questmenu.QUEST_SHAPE_MINIMUM` asks for two
# markers: one common word appears on plenty of panels.
INVENTORY_NAMES = (
    "treat", "oil", "enzymes", "glue", "glitter", "soft wax", "moon charm",
    "blue extract", "red extract", "stinger", "gold egg", "ticket",
    "gumdrop", "field dice", "loaded dice", "honeysuckle", "sprinkler builder",
    "jelly bean", "royal jelly",
    "sunflower seed", "blueberr", "bitterberr", "neonberr", "magic bean",
    "star jelly", "hard wax", "caustic wax", "swirled wax", "turpentine",
    "super smoothie", "purple potion", "tropical drink", "ant pass",
    "smooth dice", "silver egg", "diamond egg", "mythic egg", "star treat",
    "micro-converter",
)
INVENTORY_MINIMUM = 2


def button(frame=None) -> tuple[int, int]:
    """Where the inventory button is (vision/questmenu's measured row)."""
    return questmenu.button_at(BUTTON_INDEX, frame)


def crop(frame):
    """The list's part of a frame."""
    x, y, w, h = INVENTORY_BOX
    return frame[y:y + h, x:x + w, :3]


def looks_like_inventory(text: str) -> bool:
    """Does the transcribed panel name at least two inventory items?"""
    low = " ".join((text or "").lower().split())
    return len({n for n in INVENTORY_NAMES if n in low}) >= INVENTORY_MINIMUM


def item_rows(image) -> list[int]:
    """The y (within `image`, the list's crop) of every item marker Natro's
    test would find: a whole ITEM_MARK_WIDTH x ITEM_MARK_RUN block of the
    marker colour within ITEM_MARK_VARIATION, its left edge in x 0..3.
    act/inventory turns the wheel only while this finds one (Natro's own
    gate); the row geometry is logged and kept with each page, as it has not
    been seen on this machine yet. Only when that finds none is the same
    block looked for in the marker's colour under the red damage vignette
    (`_vignetted`, see VIGNETTE_K)."""
    if image is None or getattr(image, "size", 0) == 0:
        return []
    edge = image[:, :ITEM_MARK_X, :3].astype(np.int16)
    if edge.shape[1] < ITEM_MARK_WIDTH or edge.shape[0] < ITEM_MARK_RUN:
        return []
    want = (ITEM_MARK_RGB[2], ITEM_MARK_RGB[1], ITEM_MARK_RGB[0])   # BGR
    match = (np.abs(edge - np.array(want, dtype=np.int16))
             <= ITEM_MARK_VARIATION).all(axis=2)
    found = _blocks(match)
    if found:
        return found
    found = _blocks(_vignetted(edge, want))
    return found if _pitched(found) >= VIGNETTE_ROWS else []


def _pitched(marks) -> int:
    """The most item rows in a row ITEM_ROW_PITCH apart (as gaps)."""
    rows: list[int] = []
    last = None
    for mark in marks:
        if last is None or mark - last > 30:
            rows.append(mark)
        last = mark
    best = run = 0
    for a, b in zip(rows, rows[1:]):
        run = run + 1 if abs(b - a - ITEM_ROW_PITCH) <= ITEM_ROW_PITCH_TOLERANCE else 0
        best = max(best, run)
    return best


def _vignetted(edge, want) -> np.ndarray:
    """Which pixels are the marker's colour seen through the red vignette:
    blue and green the marker's own times one k in VIGNETTE_K, and the red
    what is left of the marker's plus (1 - k) of a red in VIGNETTE_RED."""
    b, g, r = (edge[..., i].astype(np.float32) for i in range(3))
    k = (b / want[0] + g / want[1]) / 2
    red = r - want[2] * k
    tol = VIGNETTE_TOLERANCE
    return ((np.abs(b - want[0] * k) <= tol) & (np.abs(g - want[1] * k) <= tol)
            & (k >= VIGNETTE_K[0]) & (k <= VIGNETTE_K[1])
            & (red >= (1 - k) * VIGNETTE_RED[0] - tol)
            & (red <= (1 - k) * VIGNETTE_RED[1] + tol))


def _blocks(match) -> list[int]:
    """One block: columns c..c+2 all matching, ITEM_MARK_RUN rows in a row."""
    tops: set = set()
    for c in range(ITEM_MARK_X - ITEM_MARK_WIDTH + 1):
        wide = match[:, c:c + ITEM_MARK_WIDTH].all(axis=1).astype(np.int32)
        runs = np.convolve(wide, np.ones(ITEM_MARK_RUN, np.int32), mode="valid")
        tops.update(np.flatnonzero(runs == ITEM_MARK_RUN).tolist())
    out: list[int] = []
    for top in sorted(tops):
        if not out or top - out[-1] > ITEM_MARK_RUN:
            out.append(int(top))
    return out


# ---- the words ------------------------------------------------------------
# THE EXAMPLE NAMES NO ITEM. This model writes text a picture does not hold
# (DESIGN 8a: "claim hive" for 11 of 24 crops that showed nothing, "geometry
# first, language model second"), and an example of "Treat: 1,234" is one of
# INVENTORY_NAMES -- half of what `looks_like_inventory` needs, handed to it
# by the question. The geometry first is act/inventory's marker test.
TRANSCRIBE = ("This is the item list of the game's inventory menu. List every "
              "item you can read, one per line, as the item's name, a colon "
              "and the number shown for it, e.g. 'Name: 12'. Reply with "
              "only the list.")


def count_question(label: str) -> str:
    """A closed question about one material on one page."""
    return (f"Is there an item called {label} in this list? If there is, reply "
            f"with only the number shown for it, digits only. If there is "
            f"not, reply with only the word none.")


_NUMBER = re.compile(r"(\d[\d,.]*)")


def answer_count(text: str | None) -> int | None:
    """A closed answer as a count, or None ("none", no number, two numbers)."""
    if not text:
        return None
    low = text.strip().lower()
    if low.startswith("none") or low.startswith("no"):
        return None
    found = _NUMBER.findall(low)
    if len(found) != 1:
        return None
    return questmenu.number(found[0].rstrip(".,"))


def spellings(label: str) -> set[str]:
    """"Moon Charms" -> {"moon charms", "moon charm"}: the menu's own
    spelling is not known, so either is looked for."""
    low = " ".join(label.lower().split())
    out = {low}
    if low.endswith("s"):
        out.add(low[:-1])
    else:
        out.add(low + "s")
    return out


# "Treat: 1,234", "Treat x1,234", "- Treat 1,234": a name, then the one number
# the line ends with. AND "Whirligig: 8/100": a count over the item's cap, as
# the menu draws the capped items (Coconut 7/500, Micro-Converter 15/15,
# Cloud Vial 1/10 on the 2026-10-01 19:25 read) -- the count is the first.
_LINE = re.compile(r"^[-*\u2022\s]*(.+?)\s*(?::|\bx|\u00d7)?\s*(\d[\d,.]*)"
                   r"(?:\s*/\s*(\d[\d,.]*))?\s*$", re.IGNORECASE)


def _entries(text: str):
    """(name, count) for every line that is one name and one number."""
    for name, value, _cap in entries_with_caps(text):
        yield name, value


def entries_with_caps(text: str):
    """(name, count, cap or None) for every line that is one name and one
    number, or one count over one cap."""
    for raw in (text or "").splitlines():
        found = _LINE.match(" ".join(raw.split()))
        if not found:
            continue
        name = " ".join(found.group(1).lower().rstrip(": ").split())
        value = questmenu.number(found.group(2).rstrip(".,"))
        cap = (questmenu.number(found.group(3).rstrip(".,"))
               if found.group(3) else None)
        if name and value is not None:
            yield name, value, cap


def caps_in(text: str, labels: dict) -> dict:
    """{item: cap} for each item a line shows as count/cap."""
    out: dict = {}
    for name, _value, cap in entries_with_caps(text):
        if cap is None:
            continue
        for key, label in labels.items():
            if name in spellings(label):
                out[key] = cap
    return out


def counts_in(text: str, labels: dict) -> dict:
    """{material: count} for each material that one line of a transcription
    names EXACTLY -- "Treat: 1,234", not "Star Treat: 3" -- with one number,
    and no other line gives it a different one. `labels` is {material: label}."""
    out: dict = {}
    entries = list(_entries(text))
    for key, label in labels.items():
        names = spellings(label)
        seen = {value for name, value in entries if name in names}
        if len(seen) == 1:
            out[key] = seen.pop()
    return out


def names_in(text: str, labels: dict) -> set:
    """The materials a transcription gives a line of their own."""
    entries = {name for name, _v in _entries(text)}
    return {key for key, label in labels.items() if entries & spellings(label)}
