"""Donating one sticker to the Sticker Stack, by its own Yes/No question.

WHY. The owner, 2026-10-07: "teach it sticker stack and what stickers not to
use due to rarity"; 2026-10-10: "improve sticker stacking". Each sticker type
stacked raises the Stack Boost for good (wiki Sticker Stack); the account's
stack read "Stack Boost (x13)" on 2026-10-09 (var/places/sticker_stack-menu-
124420.jpg).

HOW (Natro nm_StickerStack): E opens the menu, a click on a sticker in "Choose
a Sticker to Donate" asks Yes/No, and Yes donates it. The menu shows icons,
not names, so the NAME comes from the question: a Yes is given only when the
question names a sticker of data/knowledge/stickers.yaml that brain/stickers
lets the stack take (not kept for rarity, not stacked before). Anything else --
no name read, an unknown or rare sticker -- is answered No and the next icon is
tried. One donation a visit.

THE SHOP TRAP, AGAIN. The third row of icons (y 612) lies inside where the
inventory's Yes button sits (act/inventory DIALOG_YES, y 564..613), so a click
made while an unseen question is open could be a Yes. So: no click on an icon
unless the frame shows the menu and no question; and a click that opens no
question the detector knows ends the visit -- frames kept, nothing else
clicked. The first live visits are the measurement.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from ..brain import stickers as stickers_mod
from . import inventory

# THE ICONS, MEASURED on var/places/sticker_stack-menu-124420.jpg (1920x1080):
# a 4-wide grid in "Choose a Sticker to Donate", 65 px apart. Only the three
# rows fully in view; the list scrolls, and scrolling is not done here.
# ponytail: fixed grid at the measured scale; find the icons by their white
# "sticker" badge (Natro's stickernormal bitmap) if the window moves
ICON_COLUMNS = (722, 787, 855, 920)
ICON_ROWS = (482, 547, 612)
# "Choose a Sticker to Donate:" over the grid: the menu is open
MENU_HEADER = (697, 420, 957, 446)
QUESTION_WAIT_S = 2.0
# NO STICKER LEFT TO GIVE (MEASURED 2026-10-18 01:33, var/places/sticker_stack-
# menu-013336.jpg): the grid reads "(You have no types of Stickers that can be
# added to the Stack)" -- every type he owns is stacked -- and the only way to
# keep the boost is the yellow "Boost without a Sticker (25 Tickets)" button.
# The bot never pressed it, so the stack ran out (the owner, 2026-10-17:
# "sticker stack no work"). The box's first line, "Stack Boost (x47) (22:50)",
# says how long the boost has left.
GRID_BOX = (692, 450, 955, 655)
BOOST_LINE = (972, 452, 1220, 468)
TICKET_BUTTON = (1062, 352, 1216, 386)
TICKET_BOOST_WHEN_LEFT_S = 10 * 60
# THE QUESTION'S FIRST LINE, READ ALONE. MEASURED 2026-10-19 on every saved
# var/places/sticker_stack-*-asked-no-*.jpg: the box holds THREE lines
# ('Add "Precise Eye Sticker" to the Stack?' / 'Rewards: 1 Hard Wax' / 'Stack
# Boost: +1% ...'), read whole it came back 'add pinkpgcirfjir ktgtche...' and
# every sticker was answered No -- the owner: "it wasnt able to press yes on
# sticker stack". This box reads 'Add "Pink Chair Sticker" to the Stack?'.
QUESTION_LINE = (765, 462, 1155, 493)
# ...BUT THE LINES MOVE: the text is centred, so a name that wraps ('Add
# "Purple Pointed Critter Sticker" to the / Stack?') lifts the first line to
# y 455-480 (var/places/sticker_stack-r0c0-asked-no-005327.jpg). The lines are
# found by their white letters, row by row, and read until one ends the
# question with "?".
QUESTION_BOX = (760, 448, 1160, 552)      # ticket-boost only when under 10 min are left
SETTLE_S = 0.4
NAME_SIMILAR = 0.85


@dataclass
class Donated:
    name: str | None = None          # the sticker given, or None
    asked: list = field(default_factory=list)   # (icon, question, answered Yes)
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.name is not None

    def describe(self) -> str:
        said = "; ".join(f"{q!r} -> {'Yes' if y else 'No'}" for _i, q, y in self.asked)
        return (f"donated the {self.name}" if self.ok else f"nothing donated ({self.reason})") \
            + (f" — asked: {said}" if said else "")


def menu_open(frame, ocr) -> bool:
    words = " ".join(str(ocr(frame, MENU_HEADER) or "").lower().split())
    return "choose" in words and "sticker" in words


def sticker_named(question: str, table: dict) -> str | None:
    """The table's sticker the question names (its longest name found in it,
    letters only), or None."""
    letters = lambda t: re.sub(r"[^a-z]", "", str(t or "").lower())  # noqa: E731
    q = letters(question)
    hits = [n for n in table["stickers"] if letters(n) and letters(n) in q]
    if hits:
        return max(hits, key=lambda n: len(letters(n)))
    # ONE LETTER MISREAD ('Standina Beekeeper', 'Cvan Decorative Border',
    # 'Nectar lcon' -- the 2026-10-19 re-read of the saved questions): the
    # quoted name against the table, closest at NAME_SIMILAR or better, and a
    # clear winner, so two near names never swap.
    import difflib
    m = re.search(r'"([^"]+)"', str(question or ""))
    quoted = letters(m.group(1) if m else question).removesuffix("sticker")
    if len(quoted) < 5:
        return None
    scored = sorted(((difflib.SequenceMatcher(None, quoted, letters(n)).ratio(), n)
                     for n in table["stickers"] if letters(n)), reverse=True)
    if scored and scored[0][0] >= NAME_SIMILAR and (
            len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08):
        return scored[0][1]
    return None


def donate_one(vin, frames, ocr, table: dict, stacked, *, keep=None,
               sleep=time.sleep, clock=time.monotonic) -> Donated:
    """Try the icons in order until one question names a sticker the stack may
    take, and answer Yes to it; No to every other question. `stacked` are the
    names stacked before; `keep(frame, tag)` saves a frame."""
    keep = keep or (lambda f, tag: None)
    out = Donated()
    for r, y in enumerate(ICON_ROWS):
        for c, x in enumerate(ICON_COLUMNS):
            icon = f"r{r}c{c}"
            frame = frames()
            if frame is None or inventory.dialog_open(frame) or not menu_open(frame, ocr):
                keep(frame, f"{icon}-not-the-menu")
                out.reason = f"before {icon} the frame was not the open menu with no question"
                return out
            if vin.click(x, y) is False:
                out.reason = f"the click on {icon} was refused"
                return out
            ends, asked_frame = clock() + QUESTION_WAIT_S, None
            while clock() < ends:
                sleep(SETTLE_S)
                f = frames()
                if f is not None and inventory.dialog_open(f):
                    asked_frame = f
                    break
            if asked_frame is None:
                keep(frames(), f"{icon}-no-question")
                out.reason = (f"the click on {icon} opened no question the detector "
                              f"knows — the visit ends there")
                return out
            question = question_text(asked_frame, ocr)
            name = sticker_named(question, table)
            if name is None:
                question = inventory.dialog_question(asked_frame, ocr)
                name = sticker_named(question, table)
            yes = bool(name) and name in stickers_mod.stackable([name], stacked, table)
            keep(asked_frame, f"{icon}-asked-{'yes' if yes else 'no'}")
            inventory.answer(vin, asked_frame, yes=yes)
            out.asked.append((icon, question, yes))
            sleep(SETTLE_S)
            if yes:
                out.name = name
                _confirm_removal(vin, frames, ocr, table, name, out, keep, sleep, clock)
                return out
    out.reason = "no icon in view was a sticker the stack may take"
    return out


# A SECOND QUESTION AFTER THE YES (2026-10-20 07:39, run-1103): "The Blowing
# Leaf Sticker will be permanently removed from your inventory. Continue?"
# came up after 'Add "Blowing Leaf Sticker" to the Stack?' -> Yes, nothing
# answered it, the HUD stayed dimmed 60 s and the run ended (a rejoin). Yes
# only when it is that removal question AND names the same sticker; any other
# box gets No, so nothing is ever left open.
REMOVAL_WORDS = "permanently removed"


# MEASURED on that frame (var/incidents/20261020-073922-hud-missing): the
# pointer still rests on Yes from the first click, the hovered Yes is darker
# (HSV V 84, under dialog_open's 90), so the box reads as "no dialog" until
# the pointer moves off it; and the line reader read "Blowina" where
# inventory.dialog_question read "blowing leaf", so that one names it.
POINTER_REST = (960, 760)


def _confirm_removal(vin, frames, ocr, table, name, out, keep, sleep, clock) -> None:
    move = getattr(vin, "move_mouse", None)
    if move is not None:
        move(*POINTER_REST)
    ends = clock() + QUESTION_WAIT_S
    while clock() < ends:
        sleep(SETTLE_S)
        f = frames()
        if f is None or not inventory.dialog_open(f):
            continue
        question = inventory.dialog_question(f, ocr) or question_text(f, ocr)
        same = sticker_named(question, table) == name
        yes = REMOVAL_WORDS in question.lower() and same
        keep(f, f"removal-asked-{'yes' if yes else 'no'}")
        inventory.answer(vin, f, yes=yes)
        out.asked.append(("removal", question, yes))
        if not yes:
            out.name = None
            out.reason = f"the second question was not the removal of {name}: {question!r}"
        sleep(SETTLE_S)
        return


def no_stickers(frame, ocr) -> bool:
    """The grid says there is no sticker type left to donate."""
    words = re.sub(r"[^a-z]", "", str(ocr(frame, GRID_BOX) or "").lower())
    return "notypes" in words or ("nottypes" in words) or ("canbeadded" in words and "no" in words)


def boost_left_s(frame, ocr) -> int | None:
    """Seconds the stack boost has left, from "Stack Boost (x47) (22:50)";
    None when it is not read (no boost running reads no time)."""
    m = re.search(r"\((\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?\)", str(ocr(frame, BOOST_LINE) or ""))
    if not m:
        return None
    a, b, c = (int(x) if x else None for x in m.groups())
    return a * 3600 + b * 60 + c if c is not None else a * 60 + b


def _yellow(frame, box) -> float:
    import cv2
    import numpy as np
    x0, y0, x1, y1 = box
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[y0:y1, x0:x1, :3]), cv2.COLOR_BGR2HSV)
    return float(((hsv[..., 0] >= 20) & (hsv[..., 0] <= 35) & (hsv[..., 1] >= 150)
                  & (hsv[..., 2] >= 180)).mean())


def ticket_boost(vin, frames, ocr, *, keep=None, sleep=time.sleep,
                 clock=time.monotonic, when_left_s: int = TICKET_BOOST_WHEN_LEFT_S,
                 nothing_to_give: bool = False) -> Donated:
    """The 25-ticket boost, only when no sticker can be given and the boost is
    missing or under `when_left_s`; Yes only to a question that names tickets."""
    keep = keep or (lambda f, tag: None)
    out = Donated()
    frame = frames()
    if frame is None or inventory.dialog_open(frame) or not menu_open(frame, ocr):
        out.reason = "not the open menu"
        return out
    # `nothing_to_give`: the icons were all asked and every one is kept for
    # rarity or stacked -- the boost would lapse just the same
    if not nothing_to_give and not no_stickers(frame, ocr):
        out.reason = "a sticker can still be donated"
        return out
    left = boost_left_s(frame, ocr)
    if left is not None and left > when_left_s:
        out.reason = f"the stack boost still has {left // 60}:{left % 60:02d} — no tickets spent"
        return out
    if _yellow(frame, TICKET_BUTTON) < 0.4:
        keep(frame, "ticket-no-button")
        out.reason = "the yellow ticket button is not where it was measured"
        return out
    x0, y0, x1, y1 = TICKET_BUTTON
    if vin.click((x0 + x1) // 2, (y0 + y1) // 2) is False:
        out.reason = "the click on the ticket button was refused"
        return out
    ends, asked = clock() + QUESTION_WAIT_S, None
    while clock() < ends:
        sleep(SETTLE_S)
        f = frames()
        if f is not None and inventory.dialog_open(f):
            asked = f
            break
    if asked is None:
        keep(frames(), "ticket-no-question")
        out.reason = "the ticket button opened no question the detector knows"
        return out
    question = inventory.dialog_question(asked, ocr)
    yes = "ticket" in re.sub(r"[^a-z]", "", question.lower())
    keep(asked, f"ticket-asked-{'yes' if yes else 'no'}")
    inventory.answer(vin, asked, yes=yes)
    out.asked.append(("ticket", question, yes))
    if yes:
        out.name = "25 Tickets"
    else:
        out.reason = f"the ticket question did not name tickets ({question!r}) — answered No"
    return out


def text_lines(frame, box=QUESTION_BOX, min_px: int = 6, pad: int = 3) -> list:
    """(x0, y0, x1, y1) of each line of white text in `box`, top first."""
    import cv2
    import numpy as np
    x0, y0, x1, y1 = box
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[y0:y1, x0:x1, :3]), cv2.COLOR_BGR2HSV)
    rows = ((hsv[..., 1] < 70) & (hsv[..., 2] > 170)).sum(axis=1)
    lines, start = [], None
    for i, n in enumerate(list(rows) + [0]):
        if n >= min_px and start is None:
            start = i
        elif n < min_px and start is not None:
            if i - start >= 8:                      # a letter row, not a speck
                lines.append((x0, max(y0, y0 + start - pad), x1, min(y1, y0 + i + pad)))
            start = None
    return lines


def question_text(frame, ocr) -> str:
    """The question's own words: its lines read one by one until the "?"."""
    if ocr is None:          # no reader: the caller falls back to inventory.dialog_question
        return ""
    words = []
    for box in text_lines(frame)[:3]:
        words.append(str(ocr(frame, box) or ""))
        if "?" in words[-1]:
            break
    return " ".join(words) or str(ocr(frame, QUESTION_LINE) or "")
