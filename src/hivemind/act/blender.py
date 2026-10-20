"""The Blender, driven: a material the goals are short of, made from what the
inventory holds (the owner, 2026-10-05: craft items to get gear).

WHY. Every gear goal waits on Blender materials (brain/goals, 2026-10-05 22:20):
the Bubble Mask on 2 Oil (23 of 25), the Honeycomb Belt on Enzymes and Glue,
the Cobalt and Crimson Guards on extracts. goals.yaml records each recipe from
the wiki's Blender page as a `kind: blender` source ("50 Sunflower Seeds + 10
Royal Jelly"), and the inventory holds thousands of the berries.

THE WINDOW, MEASURED 2026-10-04 22:38 (var/shoplook/20261004-223849-blender-
window.jpg, 1920x1080), every line read exactly by tesseract: the red X at
(713, 338), the page "1/ 20" at the top right, the recipe "-Red Extract -"
under it, its ingredients as icons with counts, the arrows at the bar's ends
and the green "Make Red Extract" between them (0.88 green).

NATRO'S WAY (submacros/natro_macro.ahk nm_Blender, read 2026-10-05), whose
places land on that window (Make at the bar's middle, the right arrow, the X):
the right arrow until the wanted recipe shows, Make, "+" for each one more,
Confirm; a green End Craft collects a finished craft, a red one means it is
still crafting and the window is shut; 300 s an item.

WHAT MAKE OPENS, MEASURED 2026-10-13 22:32:21 (var/shoplook/20261013-223221-
blend-make-1.jpg, tests/fixtures/blender/qty-row.jpg): a "Select Quantity:"
row in the bar -- a teal "-" (693-767, 650-700), the box reading "1" (767-
860), a green "+" (861-941) -- then a green Confirm (973-1086, 634-684) and a
red Cancel (1106-1226). After Confirm the window reads "Crafting Enzymes...",
"0 / 1" and a 4:59 timer (-make-2). So the bar's own words are read and only
a button reading "Confirm" is pressed; for more than one the "+" is found by
its colour and place, pressed, and the box must read the number first (see
set_quantity). After Confirm the window must read as crafting, and it is shut
by its X either way. A green button reading End Crafting (Natro's finished
one) is pressed to collect; red End Crafting and Speed Up (tickets) never are.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

TITLE_BOX = (845, 375, 1220, 420)
PAGE_BOX = (1140, 322, 1232, 356)
MAKE_BOX = (793, 633, 1124, 685)
BAR = (690, 608, 1232, 706)             # the arrows and the button between them
PANEL = (683, 309, 1235, 708)
NEXT_ARROW = (1207, 658)
PAGES = 20
SECONDS_PER_ITEM = 300                  # Natro's BlenderAmount * 300
MAX_PER_VISIT = 10                      # 50 min of crafting a visit
SETTLE_S = 0.8
MAKE_GREEN_MIN = 0.5
# THE BAR'S BUTTONS, MEASURED 2026-10-06: Make 333 x 54 (tests/fixtures/
# blender/window.jpg), a red End Crafting 242 x 81 while crafting (var/shoplook/
# 20261006-001340-blend-made.jpg), a green one 246 x 85 when done (-015304-
# blend-window.jpg) -- past the Feed box's limits (act/feed BUTTON_W/H), which
# threw them away: the Oil finished by 00:18 sat uncollected at 01:53, and a
# red one never read as crafting. Confirm and Cancel fit the old limits.
BAR_BUTTON_SIZES = ((60, 360), (24, 100))
# THE QUANTITY ROW, MEASURED 2026-10-13 22:32:21 (tests/fixtures/blender/
# qty-row.jpg): the "+" 80 x 50 (the button finder's (861, 650, 80, 50)) with
# the box 94 wide left of it and the "-" 74 wide left of that, HSV (89, 183,
# 133) -- teal, which the button finder's green and red leave out. Its "+" is
# never read: bar_buttons read it "e" live and "-" on this frame.
PLUS_W, PLUS_H = 80, 50
QTY_W, MINUS_W = 94, 74
TEAL = (86, 100)                        # the "-" (89-90); the panel's blue is 107-110
PLUS_SETTLE_S = 0.15                    # between presses (Natro: 30 ms)
# THE PANEL'S BLUE over PANEL: 0.77 open, 0.04 shut (MEASURED on the 22:38
# window and the frame after its X).
PANEL_BLUE_MIN = 0.4


def title_of(text) -> str:
    """"-Red Extract -" -> "red extract"."""
    return " ".join(re.sub(r"[^a-z ]", " ", str(text or "").lower()).split())


def recipe(gives, labels: dict, item_of) -> dict | None:
    """{slug: count} from a goals.yaml source's words ("50 Sunflower Seeds +
    10 Royal Jelly, 5 minutes -- ..."), each named by `item_of(words, labels)`
    (act/feed.item_of); None when any ingredient is not a known row."""
    head = re.split(r",|--|\(", str(gives or ""))[0]
    parts = re.findall(r"(\d+)\s+([A-Za-z][A-Za-z ]*?)\s*(?=\+|$)", head.strip())
    if not parts:
        return None
    out = {}
    for n, words in parts:
        slug = item_of(words, labels)
        if slug is None:
            return None
        out[slug] = out.get(slug, 0) + int(n)
    return out


def _short_of(rows, labels, item_of):
    """(row, [(need, recipe, short)], [needs no recipe makes]) for the FIRST
    open goal that is short of materials, else None. A need the last read did
    not count is short of all of it when the Blender makes it, and left out
    when it does not (NOT COUNTED BY THE LAST READ is unknown, not short:
    MEASURED 2026-10-05 23:48, a read that missed the Blueberry row -- 9,994
    held at 23:07 -- left the Bubble Mask "short" of them and the Blender idle)."""
    for row in rows or ():
        if getattr(row, "state", "") == "owned":
            continue
        missing = list(getattr(row, "missing", None) or ())
        if not missing:
            continue
        plan, cannot = [], []
        for need in missing:
            parts = next((recipe(src.get("gives"), labels, item_of)
                          for src in (getattr(need, "sources", None) or ())
                          if (src or {}).get("kind") == "blender"), None)
            if not parts:
                if getattr(need, "have", None) is not None:
                    cannot.append(need)
                continue
            short = max(1, int(getattr(need, "need", 0) or 0) - int(getattr(need, "have", 0) or 0))
            plan.append((need, parts, short))
        return row, plan, cannot
    return None


def choose(rows, held: dict, labels: dict, item_of, keep: dict | None = None):
    """choose_n's (slug, label, ingredients), without how many."""
    got = choose_n(rows, held, labels, item_of, keep)
    return None if got is None else got[:3]


def choose_n(rows, held: dict, labels: dict, item_of, keep: dict | None = None,
             making: dict | None = None):
    """(slug, label, ingredients, n) of the next material to make for the FIRST
    open goal that is short of materials, when the Blender can make one from
    what is held (less `keep`, what other errands still owe) -- else None, and
    later goals are not touched. `n`, how many this visit, is the least of what
    the goal is still short (less `making`, {slug: count} done in the Blender
    and not collected -- the inventory does not hold them yet), what the held
    items make, and MAX_PER_VISIT.

    ROYAL JELLY IS THE LIMIT: every recipe here takes 10 of it, and after the
    Bubble Mask's 2 Oil the next goal (the Honeycomb Belt) is short 50 Enzymes,
    50 Glue and 25 Oil -- 1,250 jelly the account does not have. Making some
    of that would spend the jelly the hive's rolls want on a goal it cannot
    finish. SINCE 2026-10-13 the jelly is bought for it (`crafting`, brain/
    buyer) and kept from the rolls (run_farm jelly_keep), so it does not wait
    on the rolls -- but it still waits on every other ingredient."""
    keep, making = keep or {}, making or {}
    got = _short_of(rows, labels, item_of)
    if got is None:
        return None
    _row, plan, _cannot = got
    if not plan:
        return None              # only unread
    # ONE MATERIAL AT A TIME, the first whose next craft is in hand (the owner,
    # 2026-10-13, left the choice to the bot): the Honeycomb Belt's Glue waits on
    # ~2,500 Gumdrops while its Enzymes and Oil are makeable now, and the jelly
    # is bought for the goal and kept from the rolls -- so the whole-goal rule
    # above only left the Blender idle. Enzymes serve the Cobalt Guard next too.
    # SEVERAL A VISIT (2026-10-13): the Belt's 45 Enzymes and 18 Oil were 63
    # walks at one a visit; Natro sets BlenderAmount with the "+".
    for need, parts, short in plan:
        n = min([short - int(making.get(need.material, 0) or 0), MAX_PER_VISIT]
                + [(held.get(s, 0) - keep.get(s, 0)) // k for s, k in parts.items()])
        if n >= 1:
            return need.material, need.label, parts, n
    return None


def _total(plan) -> dict:
    total: dict = {}
    for _need, parts, short in plan:
        for slug, n in parts.items():
            total[slug] = total.get(slug, 0) + n * short
    return total


JELLY = "royal_jelly"


@dataclass
class Crafting:
    """What the Blender still has to make for one goal, and the Royal Jelly
    it takes (`crafting`)."""
    goal: str = ""
    crafts: list = field(default_factory=list)   # [(material label, how many)]
    jelly: int = 0                                # Royal Jelly the crafts take, in all
    takes: dict = field(default_factory=dict)    # {slug: n} every ingredient the crafts take
    lacking: dict = field(default_factory=dict)  # {slug: short} of the OTHER ingredients
    cannot: list = field(default_factory=list)   # labels no recipe makes (Stingers)

    def what(self) -> str:
        """"45 Enzymes, 50 Glue and 18 Oil"."""
        parts = [f"{n:,} {label}" for label, n in self.crafts]
        return (", ".join(parts[:-1]) + " and " + parts[-1]) if len(parts) > 1 else "".join(parts)


def crafting(rows, held: dict, labels: dict, item_of) -> Crafting:
    """The Royal Jelly the Blender needs for the goal `choose` crafts for --
    every short material it makes, at its recipe's jelly (10 each in
    goals.yaml) -- and what else it waits on. MEASURED 2026-10-13
    (var/inventory.json 11:16): the Honeycomb Belt is short 45 Enzymes, 50
    Glue (not shown, so all of it) and 18 Oil = 1,130 jelly, 89 held; and
    2,500 Gumdrops for the Glue, 17 held. Empty when no goal is short.
    ponytail: one level of recipe -- the Cobalt Guard's Glitter is Moon
    Charms, which are jelly again; count those when the Cobalt is next."""
    got = _short_of(rows, labels, item_of)
    if got is None:
        return Crafting()
    row, plan, cannot = got
    out = Crafting(goal=str(getattr(row, "label", "") or ""),
                   crafts=[(need.label, short) for need, _parts, short in plan],
                   cannot=[need.label for need in cannot])
    out.takes = _total(plan)
    for slug, n in out.takes.items():
        if slug == JELLY:
            out.jelly = n
        elif int(held.get(slug, 0) or 0) < n:
            out.lacking[slug] = n - int(held.get(slug, 0) or 0)
    return out


def panel_open(frame) -> bool:
    """The Blender's blue panel is on screen."""
    import cv2
    import numpy as np
    if frame is None:
        return False
    x0, y0, x1, y1 = PANEL
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[y0:y1, x0:x1, :3]), cv2.COLOR_BGR2HSV)
    blue = ((hsv[..., 0] >= 100) & (hsv[..., 0] <= 125) & (hsv[..., 1] >= 120)
            & (hsv[..., 2] >= 90))
    return float(blue.mean()) >= PANEL_BLUE_MIN


def _green(frame, box, hues=(40, 85)) -> float:
    """The share of `box` (x0, y0, x1, y1) a button's colour: green, or the
    `hues` given (TEAL)."""
    import cv2
    import numpy as np
    x0, y0, x1, y1 = box
    patch = np.ascontiguousarray(frame[y0:y1, x0:x1, :3])
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    return float(((hsv[..., 0] >= hues[0]) & (hsv[..., 0] <= hues[1]) & (hsv[..., 1] >= 120)
                  & (hsv[..., 2] >= 90)).mean())


def bar_buttons(frame, read=None) -> list:
    """[(words, (x, y, w, h), colour)] of the coloured buttons in the bar --
    act/feed's button finder, each read alone (vision/amulet.read_button)."""
    import cv2
    import numpy as np
    from ..vision import amulet
    from .feed import _boxes
    read = read or amulet.read_button
    out = []
    if frame is None:
        return out
    for box in _boxes(frame, BAR, BAR_BUTTON_SIZES):
        x, y, w, h = box
        hsv = cv2.cvtColor(np.uint8([[frame[y + h // 2, x + 3, :3]]]), cv2.COLOR_BGR2HSV)[0, 0]
        colour = "green" if 40 <= hsv[0] <= 85 else "red"
        out.append((title_of(read(frame, box)), box, colour))
    return out


def browse_to(vin, frames, ocr, want: str, *, sleep=time.sleep, stopped=None) -> tuple:
    """(frame, reads) with `want`'s recipe showing, else (None, reads): the
    right arrow a page at a time, at most PAGES, reading the title each time."""
    want_t = title_of(want)
    reads, first = [], None
    for _ in range(PAGES + 1):
        frame = frames()
        title = title_of(ocr(frame, TITLE_BOX)) if frame is not None else ""
        reads.append(title)
        if title == want_t:
            return frame, reads
        if title and title == first:
            break                        # round once: it is not there
        first = first or title
        if stopped is not None and stopped():
            break
        if vin.click(*NEXT_ARROW) is False:
            break
        sleep(SETTLE_S)
    return None, reads


def _words(frame, region, words_of=None) -> list:
    """vision/amulet.read_words over `region`, the sure ones."""
    from ..vision import amulet
    if frame is None:
        return []
    return [w for w in (words_of or amulet.read_words)(frame, region)
            if w.conf >= amulet.MIN_CONFIDENCE]


def reads_make(said: str, want: str) -> bool:
    """The Make button's read names `want`: "make oil", or the same with a
    stray letter or two off the button's edge in front -- MEASURED 2026-10-06
    13:33, "y make oil" turned a ready craft away. Never another recipe's."""
    words, target = said.split(), ("make " + title_of(want)).split()
    head = words[:len(words) - len(target)]
    return words[-len(target):] == target and all(len(w) <= 2 for w in head)

def plus_button(found, confirm):
    """The quantity row's green "+" among bar_buttons' `found`: the green one
    nearest left of `confirm`, about PLUS_W x PLUS_H, on its row -- by colour
    and place, never by its letter. None when there is none."""
    cx, cy, _cw, ch = confirm
    near = [b for _w, b, c in found
            if c == "green" and b != confirm and b[0] + b[2] <= cx
            and abs(b[2] - PLUS_W) <= 20 and abs(b[3] - PLUS_H) <= 12
            and abs(b[1] + b[3] // 2 - (cy + ch // 2)) <= ch]
    return max(near, default=None)


def quantity_box(plus) -> tuple:
    """(x0, y0, x1, y1) of the box with the number, left of the "+"."""
    x, y, _w, h = plus
    return (x - QTY_W, y, x - 1, y + h)


def count_of(text):
    """The quantity box's number from its read ("1" -> 1; tesseract's l, I
    and | for 1 and O for 0), None when it is not just a number."""
    t = str(text or "").strip(" .,'`\"").translate(str.maketrans("lI|Oo", "11100"))
    return int(t) if t.isdigit() else None


def _digits(frame, box, run=None):
    """The box's number by a digits-only tesseract on the white figures alone
    (a single digit read as a character, then as a word), None when unread.
    WHY: MEASURED 2026-10-14 09:04:28 (var/shoplook/20261014-090428-blend-
    make-2.jpg) the box showed a plain "6" and the line read gave nothing --
    "10" and "8" had read, a lone "6" did not; the visit was cancelled."""
    import subprocess
    import cv2
    from ..vision.beemenu import LANGUAGE, TESSERACT
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    x0, y0, x1, y1 = box
    crop = frame[y0:y1, x0:x1, :3]
    if crop.size == 0:
        return None
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, white = cv2.threshold(grey, 150, 255, cv2.THRESH_BINARY_INV)   # dark figures on white (150: 7 of 7 frames, 200 misread a 5)
    big = cv2.copyMakeBorder(cv2.resize(white, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC),
                             20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    ok, png = cv2.imencode(".png", big)
    if not ok:
        return None
    binary, lang = TESSERACT, LANGUAGE
    for psm in (8, 10, 7):
        try:
            out = (run or subprocess.run)(
                [binary, "stdin", "stdout", "-l", lang, "--psm", str(psm),
                 "-c", "tessedit_char_whitelist=0123456789"],
                input=png.tobytes(), capture_output=True, timeout=10.0)
        except (OSError, subprocess.SubprocessError):
            return None
        got = count_of(out.stdout.decode("utf-8", "replace").strip())
        if got is not None:
            return got
    return None


def read_count(ocr, frame, box):
    """The quantity box's number: the line read first, the digits-only read
    when that gives nothing (`_digits`)."""
    got = count_of(ocr(frame, box))
    return got if got is not None else _digits(frame, box)


def set_quantity(vin, frames, ocr, frame, found, confirm, n: int, reads: list,
                 sleep=time.sleep) -> tuple:
    """(count, reason) with the quantity row open on `frame`: `n` set by the
    "+" and read back in the box; when it reads anything else, the "-" back to
    a box reading 1; else Cancel and (0, reason). Nothing is pressed for more
    than one unless the box first reads 1 (else (1, "") -- one, as before).
    A count over one is only ever returned once the box has read it."""
    plus = plus_button(found, confirm)
    if plus is None:
        reads.append("no '+' left of Confirm: one")
        return 1, ""
    box = quantity_box(plus)
    first = read_count(ocr, frame, box)
    if first != 1:
        reads.append(f"the quantity box read {first}, not 1: one")
        return 1, ""
    x, y, w, h = plus
    for _ in range(n - 1):
        if vin.click(x + w // 2, y + h // 2) is False:
            break
        sleep(PLUS_SETTLE_S)
    sleep(SETTLE_S)
    now = frames()
    got = read_count(ocr, now, box) if now is not None else None
    reads.append(f"quantity: {got} of {n}")
    if got == n:
        return n, ""
    minus = (box[0] - MINUS_W, y, box[0], y + h)
    if now is not None and _green(now, minus, TEAL) >= MAKE_GREEN_MIN:
        for _ in range(n - 1):
            if vin.click((minus[0] + minus[2]) // 2, y + h // 2) is False:
                break
            sleep(PLUS_SETTLE_S)
        sleep(SETTLE_S)
        now = frames()
        back = read_count(ocr, now, box) if now is not None else None
        reads.append(f"after '-': {back}")
        if back == 1:
            return 1, ""
    cancel = next((b for wd, b, c in found if wd == "cancel" and c == "red"), None)
    if cancel is not None and vin.click(cancel[0] + cancel[2] // 2,
                                        cancel[1] + cancel[3] // 2) is not False:
        sleep(SETTLE_S)
        return 0, f"the quantity box read {got}, not {n} -- Cancel pressed"
    return 0, f"the quantity box read {got}, not {n}, and no Cancel was pressed"


def make_one(vin, frames, ocr, want: str, frame, *, n: int = 1, read=None, words_of=None,
             sleep=time.sleep) -> tuple:
    """(made, reason, reads) with `want`'s page showing on `frame`: Make, then
    `n` set (set_quantity; one presses no "+"), then Confirm only when a button
    reads it, then the window must read crafting. `made` is how many were
    confirmed, 0 when none."""
    reads = []
    said = title_of(ocr(frame, MAKE_BOX))
    reads.append(f"button: {said!r}")
    if not reads_make(said, want) or _green(frame, MAKE_BOX) < MAKE_GREEN_MIN:
        return 0, f"the button read {said!r}, not a green 'Make {want}'", reads
    x0, y0, x1, y1 = MAKE_BOX
    if vin.click((x0 + x1) // 2, (y0 + y1) // 2) is False:
        return 0, "the click on Make was held back", reads
    sleep(SETTLE_S)
    after = frames()
    found = bar_buttons(after, read)
    reads.append("after Make: " + ", ".join(f"{w!r} {c}" for w, _b, c in found))
    confirm = next((b for w, b, c in found if w == "confirm"), None)
    if confirm is None:
        confirm = next(((w.x, w.y, w.w, w.h) for w in _words(after, BAR, words_of)
                        if title_of(w.text) == "confirm"), None)
    if confirm is None:
        return 0, "Make opened no button reading Confirm", reads
    if n > 1:
        n, why = set_quantity(vin, frames, ocr, after, found, confirm, n, reads, sleep)
        if not n:
            return 0, why, reads
    x, y, w, h = confirm
    if vin.click(x + w // 2, y + h // 2) is False:
        return 0, "the click on Confirm was held back", reads
    sleep(SETTLE_S)
    done = frames()
    words = " ".join([w for w, _b, _c in bar_buttons(done, read)]
                     + [title_of(w.text) for w in _words(done, PANEL, words_of)])
    reads.append(f"after Confirm: {words!r}")
    if "craft" not in words and "speed" not in words:
        return 0, "the window did not read as crafting after Confirm", reads
    return n, f"{n} {want} crafting", reads


def finished_button(frame, read=None):
    """The green End Crafting button of a finished craft (Natro's EndCraftG),
    or None. A red one is still crafting and is never pressed."""
    for words, box, colour in bar_buttons(frame, read):
        if colour == "green" and "end" in words and "craft" in words:
            return box
    return None


def still_crafting(frame, read=None) -> bool:
    return any(colour == "red" and "craft" in words
               for words, _box, colour in bar_buttons(frame, read))
