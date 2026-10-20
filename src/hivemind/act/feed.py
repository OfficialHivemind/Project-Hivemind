"""Feeding the bees for a quest step: "Feed 100 Treats to your Bees. 0/100".

WHY. Search For Sunflower Seeds (var/quests.json, read 2026-10-05) waits on
two steps nothing here could do -- "Feed 100 Treats to your Bees. 0/100" and
"Feed 25 Sunflower Seeds to your Bees. 0/25" -- with 21,831 Treats and 371
Sunflower Seeds held (var/inventory/20261005-154813, rows titled "Treat" and
"Sunflower Seed").

HOW NATRO FEEDS (submacros/natro_macro.ahk nm_Feed, read 2026-10-05): at the
hive, the item dragged from the inventory onto the bee in the middle of the
screen; the game's Feed box comes up; one click on its number field, "100"
typed, one click on Feed. Natro finds the box by a 60 x 20 bitmap of the white
word "Feed", clicks the field 140 px right of it and 5 down, and Cancel 64 px
under it.

HERE: the drop is act/inventory.hatch_egg's -- the row found by its title, the
item held over the cell until it glows or, after FEED_DWELL_S, let go anyway
(Natro's way: it never looks). The buttons are found by their colour and their
own words, read alone (vision/amulet's way); the box's question must name the
item; the field is right of Feed (MEASURED, below), clicked, the amount typed
and read back off it before Feed is pressed. A field that does not read back
exactly the amount, or a box still up after Feed, is Cancelled. The first try
(2026-10-05 22:38) found the box and its buttons and Cancelled: the field had
been looked for as a white box (it is blue) and read left of its digits.

ONLY THE DIGITS 1 AND 0 ARE EVER TYPED (CHUNKS of 100 or 10). A digit the
field does not take lands on the game as a hotbar key. On this account 1 is
the Sprinkler (MEASURED on var/bears/panda_bear-look8-114113.jpg: Sprinkler,
Gumdrops x145, -, Field Dice x8, Micro-Converter x1, Jelly Beans x39, Coconut
x15), which cannot be placed at the hive, and 0 is no slot -- where a 2 or a 5
would use a Gumdrop or the Micro-Converter. The keys go one at a time through
the guarded input's tap, never platform/input.type_text, which refuses to type
while the game has focus (safety.never_chat). Neither Enter nor "/" -- the
chat's keys -- is ever pressed.
"""
from __future__ import annotations

import json
import math
import re
import time

FEED_DWELL_S = 1.0
CHUNKS = (100, 10)
REGION = (560, 300, 1360, 780)          # where the box is looked for, at 1920x1080
BUTTON_W = (60, 260)
BUTTON_H = (24, 72)
BUTTON_FILL = 0.55
# THE BOX, MEASURED 2026-10-05 22:38 (var/shoplook/20261005-223858-feed-box.jpg,
# Sunflower Seeds on the Demon): "How many Sunflower Seeds will you feed to Demon
# Bee?" over a green "Feed:" (832, 474, 122 x 48), the number field right of it
# -- BLUE with a white "1", (964, 474, 263 x 48), read by vision/amulet.read_button
# -- and under them a red "Cancel" and a green "All (404)", which feeds every one
# held and is never pressed.
FIELD_GAP = 10                          # the field's left edge from Feed's right
FIELD_W = 263
TITLE_ABOVE = (95, 8)                   # the question, from Feed's top: (up, to)
TITLE_W = 400
NATRO_CANCEL = (0, 64)
SETTLE_S = 0.8
KEY_GAP_S = 0.08
# THE FIELD'S DIGITS BY THEIR SHAPE, since only 1s and 0s are ever typed.
# MEASURED 2026-10-06 02:43 (var/shoplook/20261006-024328-feed-typed.jpg): the
# field showed "100" -- white on its blue, a "1" 7 x 23 px, each "0" 14 x 23
# (slashed), the text caret 1 px wide -- and the OCR read "160", so a right
# feed was Cancelled. The pointer is moved onto the question first: its I-beam
# over the field (23:08) is one more white shape, which can only add a glyph.
GLYPH_MIN_H = 18
GLYPH_MIN_W = 3
GLYPH_ONE_MAX_W = 10


def chunks(remaining: int, most: int = 3) -> list:
    """What is typed for `remaining`: 100s while 100 or more is owed, else
    10s, rounded up (25 -> [10, 10, 10], 100 -> [100]); at most `most`."""
    if remaining <= 0:
        return []
    size = CHUNKS[0] if remaining >= CHUNKS[0] else CHUNKS[1]
    return [size] * min(most, math.ceil(remaining / size))


def _singular(words) -> str:
    w = " ".join(re.sub(r"[^a-z ]", " ", str(words).lower()).split())
    if w.endswith("ies"):
        return w[:-3] + "y"
    return w[:-1] if w.endswith("s") else w


# A FAILURE THAT TRYING AGAIN SOON CAN MEND: the drag that opened no box, a
# click the owner's Pause held back. Not a question that named another item or
# a field that read another number -- those fail the same way again.
SOON_REASONS = ("the drop opened no box", "was held back")


def rest_after(state: dict, soon_s: float, long_s: float, soon_tries: int) -> float:
    """How long the feeding rests after the failure var/fed.json records:
    `soon_s` for a SOON_REASONS failure while `soon_fails` (consecutive such
    failures, this one included) is at most `soon_tries`; `long_s` otherwise.
    MEASURED 2026-10-06 17:25: 20 of 25 Strawberries fed in two boxes, the
    third drop opened no box, and Mother Bear's Star Egg quest stood three
    hours behind it."""
    reason = str(state.get("reason") or "")
    if any(r in reason for r in SOON_REASONS) and int(state.get("soon_fails", 0) or 0) <= soon_tries:
        return float(soon_s)
    return float(long_s)


def asks_about(asked, item) -> bool:
    """Does the Feed box's question name `item`? Word by word, singular.
    MEASURED 2026-10-06 16:36: "how many blueberries will you feed to diamond
    bee" -- `_singular` of the whole question left "blueberries", in which
    "blueberry" is not a substring, and the feed was Cancelled; Pineapples and
    Treats passed only because their singulars are prefixes of their plurals."""
    said = " ".join(_singular(w) for w in str(asked or "").lower().split())
    want = _singular(item)
    return bool(want) and want in said


def item_of(words, labels: dict) -> str | None:
    """The slug the step's words name ("sunflower seeds" -> sunflower_seed),
    matched to the rows' own titles (consumables.yaml labels: Treat,
    Sunflower Seed, Strawberry), or None when none or two match."""
    want = _singular(words)
    found = [slug for slug, label in labels.items() if _singular(label) == want]
    return found[0] if len(found) == 1 else None


def load(path) -> dict:
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def owed(feeds, fed: dict, read_at: float) -> list:
    """[(item words, still owed)] from the quest read's FeedNeeds, less what
    was fed since that read (`fed`: {words: [[at, n], ...]}) -- the menu
    shows a feed only when it is read again."""
    out = []
    for need in feeds or ():
        since = sum(int(n) for at, n in (fed.get(need.item) or ())
                    if float(at) > float(read_at or 0))
        if need.remaining - since > 0:
            out.append((need.item, need.remaining - since))
    return out


def lit_or_dwelt(lit, dwell: float = FEED_DWELL_S, clock=time.monotonic):
    """`lit(frame)` (the cell's glow, vision/hivecell.hovered), or yes anyway
    once the item has been held over the cell `dwell` seconds."""
    began = []

    def check(frame) -> bool:
        if lit(frame):
            return True
        now = clock()
        if not began:
            began.append(now)
        return now - began[0] >= dwell
    return check


def _clean(text) -> str:
    return "".join(c for c in str(text).lower() if c.isalpha())


def _digits(text) -> str:
    return re.sub(r"\D", "", str(text or ""))


def _boxes(frame, region=REGION, sizes=None) -> list:
    """[(x, y, w, h)] of solid green and red blobs of a button's size
    (`sizes`: ((w lo, hi), (h lo, hi)), the Feed box's by default)."""
    import cv2
    import numpy as np
    from ..vision import amulet
    if frame is None:
        return []
    x0, y0, x1, y1 = region
    roi = np.ascontiguousarray(frame[y0:y1, x0:x1, :3])
    if roi.size == 0:
        return []
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = (((hue <= amulet.RED_HUE_LOW) | (hue >= amulet.RED_HUE_HIGH))
           & (sat >= amulet.RED_MIN_S) & (val >= amulet.RED_MIN_V))
    green = (hue >= 40) & (hue <= 85) & (sat >= 120) & (val >= 90)   # inventory's Yes
    out = []
    for mask in (green, red):
        n, _labels, stats, _c = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[i])
            (w_lo, w_hi), (h_lo, h_hi) = sizes or (BUTTON_W, BUTTON_H)
            if w_lo <= w <= w_hi and h_lo <= h <= h_hi and area >= BUTTON_FILL * w * h:
                out.append((x0 + x, y0 + y, w, h))
    return out


def buttons(frame, read=None, words_of=None) -> dict:
    """{"feed": box, "cancel": box} as found: each coloured button read alone
    (vision/amulet.read_button), then the words over REGION for what is still
    missing -- the last "Feed" in reading order, below any title saying it."""
    from ..vision import amulet
    read = read or amulet.read_button
    found = {}
    for box in _boxes(frame):
        word = _clean(read(frame, box))
        if word in ("feed", "cancel"):
            found.setdefault(word, box)
    if len(found) < 2 and frame is not None:
        words = {}
        for w in (words_of or amulet.read_words)(frame, REGION):
            word = _clean(w.text)
            if word in ("feed", "cancel") and w.conf >= amulet.MIN_CONFIDENCE:
                if word == "feed" or word not in words:     # the last Feed, the first Cancel
                    words[word] = (w.x, w.y, w.w, w.h)
        for word, box in words.items():
            found.setdefault(word, box)
    return found


def _centre(box) -> tuple:
    x, y, w, h = box
    return x + w // 2, y + h // 2


def glyphs(frame, box) -> str:
    """The 1s and 0s shown in the field, read by their widths ("" when it shows
    no digit-sized white shape)."""
    import cv2
    import numpy as np
    if frame is None:
        return ""
    x, y, w, h = box
    roi = np.ascontiguousarray(frame[y:y + h, x:x + w, :3])
    if roi.size == 0:
        return ""
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    white = ((hsv[..., 1] < 70) & (hsv[..., 2] > 190)).astype(np.uint8)
    n, _labels, stats, _c = cv2.connectedComponentsWithStats(white)
    found = []
    for i in range(1, n):
        bx, _by, bw, bh, _area = (int(v) for v in stats[i])
        if bh >= GLYPH_MIN_H and bw >= GLYPH_MIN_W:
            found.append((bx, "1" if bw <= GLYPH_ONE_MAX_W else "0"))
    return "".join(ch for _x, ch in sorted(found))


def field_at(frame, feed) -> tuple:
    """(x, y, (x, y, w, h)) of the number field: right of Feed on its row, as
    measured."""
    fx, fy, fw, fh = feed
    box = (fx + fw + FIELD_GAP, fy, FIELD_W, fh)
    return box[0] + FIELD_W // 2, fy + fh // 2, box


def feed_box(vin, frames, amount: int, *, frame=None, ocr=None, read=None,
             words_of=None, item=None, title_ocr=None, keep=None, release=None,
             sleep=time.sleep) -> tuple:
    """(ok, reason): `amount` typed into the Feed box the drop opened, read
    back off the field, and Feed pressed -- else Cancel. 1s and 0s only.
    `item` (the step's words): the box's question must name it. `keep(frame,
    tag)` is handed the frame after the typing."""
    text = str(int(amount))
    if set(text) - {"0", "1"}:
        return False, f"{text} has a digit other than 1 and 0 -- nothing typed"
    if ocr is None:
        from ..vision import amulet
        ocr = amulet.read_button
    frame = frames() if frame is None else frame
    found = buttons(frame, read, words_of)
    if "feed" not in found:
        return False, "the drop opened no box with a Feed button"

    def cancel(why: str) -> tuple:
        if "cancel" in found:
            at = _centre(found["cancel"])
        else:
            fx, fy = _centre(found["feed"])
            at = (fx + NATRO_CANCEL[0], fy + NATRO_CANCEL[1])
        vin.click(*at)
        sleep(SETTLE_S)
        shut = "feed" not in buttons(frames(), read, words_of)
        return False, why + ("; Cancelled" if shut else "; Cancel did not shut the box")

    if item:
        if title_ocr is None:
            from .shoplook import _ocr_line
            title_ocr = lambda f, b: _ocr_line(f, b, psm=6)  # noqa: E731
        fx, fy = found["feed"][0], found["feed"][1]
        asked = _singular(title_ocr(frame, (fx, max(0, fy - TITLE_ABOVE[0]), fx + TITLE_W,
                                            fy - TITLE_ABOVE[1])))
        if not asks_about(asked, item):
            return cancel(f"the box asks {asked!r}, not about {item}")
    x, y, box = field_at(frame, found["feed"])
    before = _digits(ocr(frame, box))
    if vin.click(x, y) is False:
        return cancel("the click on the number field was held back")
    sleep(0.3)
    # A HELD ALT turns "1" into Roblox's Capture (act/hotbar: 72 of 658 slot-1
    # presses, and run-656 22:41:10): one tap of it first
    from .hotbar import release_alt
    release_alt(vin)
    if release is not None:          # and inside the compositor (platform/session)
        try:
            release()
        except Exception:
            pass
    for ch in text:
        vin.tap(ch)
        sleep(KEY_GAP_S)
    move = getattr(vin, "move_mouse", None)
    if callable(move):                  # the pointer off the field (GLYPH_*)
        fx, fy = found["feed"][0], found["feed"][1]
        move(fx + TITLE_W // 2, max(0, fy - TITLE_ABOVE[0] // 2))
    sleep(0.4)
    typed = frames()
    if keep is not None:
        keep(typed, "typed")
    shown = glyphs(typed, box) or _digits(ocr(typed, box))
    if shown != text:
        return cancel(f"the field read {shown!r} after {text} was typed (it read "
                      f"{before!r} before)")
    if vin.click(*_centre(found["feed"])) is False:
        return cancel("the click on Feed was held back")
    sleep(SETTLE_S)
    if "feed" in buttons(frames(), read, words_of):
        return cancel("the box was still up after Feed")
    return True, f"fed {text}: the field read {shown!r}, Feed pressed, the box shut"
