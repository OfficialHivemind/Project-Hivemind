"""Reading and advancing an NPC dialogue box, and why a click is the only way.

WHAT THIS IS FOR. The owner asked for the quest line: complete quests, talk to
the bears and turn them in.
`act/bearvisit` got as far as opening one -- it walks to the Black Bear, reads
the prompt, presses E, and photographs what comes up. What it could not do was
get past the first page, because nothing knew what advances a dialogue.

NOW IT IS MEASURED, from `var/bears/black_bear-dialogue-032911.jpg` and
`var/bears/black_bear-after-leaving-032930.jpg` (2026-09-23, 03:29:11 and
03:29:30, nineteen seconds apart):

  1. THE BOX SAYS WHAT ADVANCES IT. Bottom right of the box, in small type:
     "Click to continue". A mouse click, not a key -- which matters, because
     this project's standing rule is that Return and Escape are never pressed
     at a Roblox screen (a menu carries Log Out and Leave as ordinary tiles).

  2. WALKING AWAY DOES NOT WORK. `bearvisit.talk` ran `natro_back_black_bear`
     between those two frames and the character DID NOT MOVE: the bear is in
     the same place, the camera is identical, and only the ground tokens and
     the buff bar changed. An open dialogue swallows the movement keys. So a
     dialogue is not something to walk out of; until it is closed the bot is
     frozen, and before this module the only way out was the rejoin.

  3. THE BOX IS SCREEN-FIXED. Its blue body occupied EXACTLY
     x=716 y=763 w=489 h=117 in both frames, to the pixel, while the world
     behind it moved on. So it is a UI overlay at a known place, and a click
     into it lands on the box rather than on the world.

WHAT IT REFUSES TO DO. It clicks the BOX and nothing else: not the left-hand
icon column, not a token, not the "?" in the corner. It advances only while
the text keeps changing, and it stops at `MAX_PAGES` rather than clicking at
whatever is on screen for ever. If no box is found it does nothing at all --
the click is never sent "just in case", because a click into the world is a
tool swing or a menu press.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

# THE BOX'S OWN BLUE, sampled at five points across the body and title of
# both dialogue frames: HSV (108, 202-212, 163-172). The band is widened a
# little around that, and deliberately NOT widened as far as the hive pad's
# blue, which those same frames show at a different hue/value and which sits
# higher up the screen.
BOX_HSV = ((104, 170, 120), (112, 240, 210))

# WHAT SHAPE COUNTS AS THE BOX. Measured: 489 x 117 at (716, 763), area
# 47,909 of a 57,213-pixel rectangle -- 84% filled, the shortfall being the
# white text. A three-line dialogue is taller and a one-line one shorter, so
# height is bounded loosely and width tightly; `MIN_FILL` is what separates a
# filled UI panel from a ragged patch of blue scenery.
MIN_AREA = 15_000
MIN_WIDTH = 300
MIN_HEIGHT = 60
MIN_FILL = 0.75

# WHERE ON THE SCREEN IT CAN BE, as fractions of the frame rather than pixels,
# so a resolution change cannot silently make the test find nothing.
#
# THE NIGHT SKY IS THE SAME BLUE. Scanning 453 saved frames with the colour
# and fill tests alone found the two real boxes and one impostor:
# `var/homing/attempt-254/look18-row-no-d-y174218-b-0442.jpg`, an 859x256
# rectangle at (1061, 0) that is 80% filled -- open night sky above the
# horizon. Without this it would have been clicked, and a click into the world
# is a tool swing.
#
# The box was measured at y=763 of 1080 (0.71 down) and 489 of 1920 wide
# (0.25 across). A taller dialogue starts higher up, so the top is bounded
# loosely at half way; the sky blob starts at y=0 and fails that outright. The
# width bound is the second, independent test: the sky spans 0.45 of the frame
# and the box a quarter of it.
TOP_BELOW = 0.5          # the box's top edge is in the lower half
WIDER_THAN = 0.5         # ...and it is narrower than half the frame

# Where the box was measured, used only to prefer the real one when more than
# one candidate survives -- never to require it, because a resolution change
# would move it and a hard-coded rectangle would then silently find nothing.
EXPECTED = (716, 763, 489, 117)

# How long to let the next page draw after a click. The panel settle
# elsewhere in this package is 1.5 s; a dialogue page is a UI redraw rather
# than a network round trip, so this is shorter and is followed by a re-read
# rather than by an assumption.
AFTER_CLICK_SECONDS = 0.8

# A dialogue that never stops advancing is a dialogue this does not
# understand, and clicking at an unknown screen is the thing the whole module
# is careful about. Ten pages was far more than any bear had shown (the Polar
# Bear's nine, var/bear_dialogues.json) -- until the Gifted Bucko Bee's next
# quest, 2026-10-01 08:47 (run-551): "I've loaded the next quest into your
# Quest Menu" on page 9, "Report back when it's complete" on page 10, and the
# box still open at the cap. Sixteen, still stopping the moment the text stops
# changing. THIRTY-TWO: MEASURED 2026-10-07 16:44, the Spirit Bear's first talk
# ran past sixteen pages ("...my sister, she was the one who wanted sunflowers."
# on page 16, the box open) before any quest was offered. SIXTY-FOUR: MEASURED
# 2026-10-09 22:36, her Glitter talk ran 31 pages and the box was still open at
# the cap ("They used to sell this stuff for 5m Honey a pouch ..."). It still
# stops the moment the text stops changing.
MAX_PAGES = 64

# AN OPTIONS MENU IS NOT A PAGE, AND IT WAS TAKEN FOR A CLOSED BOX. MEASURED
# 2026-09-27 06:04 (attempt 487, var/respawn/060428-unknown.jpg): after three
# pages the Gifted Bucko Bee showed "Give Translator to Gifted Bucko Bee."
# (greyed) and "Leave" -- two rows of the box's own blue, 487x34 at (715, 769)
# and (716, 813), too short for `find`, while the menu's light body fused with
# the Blue HQ's floor into one 1108x437 blob 22% filled. So `advance` found no
# box and said "the box closed", and the character stood in the menu -- which
# swallows movement and the reset -- through two respawns that did not happen
# and a rejoin. A centre click would have been worse: the rows are what a click
# selects, and every option but Leave may give something away. So a menu's
# rows are found (OPTION_ROW_*), and the ONE row the Leave template matches
# (LEAVE_THRESHOLD; 1.000 on that menu's four frames, at most 0.505 on 1,377
# other saved frames) is the only thing ever clicked in one. No Leave found,
# nothing pressed.
OPTION_ROW_WIDTH = (440, 540)      # 487-488 measured
OPTION_ROW_HEIGHT = (24, 48)       # 34 measured
OPTION_ROW_FILL = 0.8              # 0.89 and 0.95 measured
LEAVE_TEMPLATE = "dialogue_leave.png"
LEAVE_THRESHOLD = 0.85
# A menu has only a few options; more rows than this is not a menu.
MAX_OPTION_ROWS = 6


@dataclass
class Box:
    """Where the dialogue box is, in screen pixels."""
    x: int
    y: int
    w: int
    h: int
    fill: float = 0.0

    @property
    def centre(self) -> tuple:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def describe(self) -> str:
        return (f"a dialogue box {self.w}x{self.h} at ({self.x}, {self.y}), "
                f"{self.fill:.0%} filled")


def find(frame) -> Box | None:
    """The dialogue box on this frame, or None.

    None means "no box", and every caller treats that as "press nothing".
    """
    if frame is None:
        return None
    try:
        hsv = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2HSV)
    except cv2.error:
        return None
    lo, hi = BOX_HSV
    mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
    count, _labels, stats, _cent = cv2.connectedComponentsWithStats(mask, 8)
    rows, cols = mask.shape[:2]
    best = None
    for x, y, w, h, area in stats[1:]:
        if area < MIN_AREA or w < MIN_WIDTH or h < MIN_HEIGHT:
            continue
        if y < TOP_BELOW * rows or w > WIDER_THAN * cols:
            continue                        # sky, not a dialogue box
        fill = area / float(w * h) if w and h else 0.0
        if fill < MIN_FILL:
            continue
        box = Box(int(x), int(y), int(w), int(h), float(fill))
        if best is None or _closer_to_expected(box, best):
            best = box
    return best


def find_options(frame) -> list:
    """The rows of an NPC options menu on this frame, top to bottom, or [].

    Each is a band of the box's own blue (BOX_HSV) of an option row's size
    (OPTION_ROW_*), in the lower half of the screen and narrower than half of
    it, as the box itself is (TOP_BELOW, WIDER_THAN). Finding rows presses
    nothing; `leave_row` says which one, if any, may be clicked."""
    if frame is None:
        return []
    try:
        hsv = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2HSV)
    except cv2.error:
        return []
    lo, hi = BOX_HSV
    mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
    _count, _labels, stats, _cent = cv2.connectedComponentsWithStats(mask, 8)
    rows_px, cols_px = mask.shape[:2]
    rows = []
    for x, y, w, h, area in stats[1:]:
        if not (OPTION_ROW_WIDTH[0] <= w <= OPTION_ROW_WIDTH[1]
                and OPTION_ROW_HEIGHT[0] <= h <= OPTION_ROW_HEIGHT[1]):
            continue
        if y < TOP_BELOW * rows_px or w > WIDER_THAN * cols_px:
            continue
        fill = area / float(w * h) if w and h else 0.0
        if fill < OPTION_ROW_FILL:
            continue
        rows.append(Box(int(x), int(y), int(w), int(h), float(fill)))
    rows.sort(key=lambda b: b.y)
    return rows if len(rows) <= MAX_OPTION_ROWS else []


_LEAVE: dict = {}


def _leave_template():
    """The Leave row's crop (data/templates/ui), loaded once; None if missing."""
    if "tpl" not in _LEAVE:
        tpl = None
        try:
            from ..datapaths import data
            path = data("templates", "ui", LEAVE_TEMPLATE)
            if path.exists():
                tpl = cv2.imread(str(path))
        except Exception:
            tpl = None
        _LEAVE["tpl"] = tpl
    return _LEAVE["tpl"]


def leave_row(frame, rows, template=None) -> Box | None:
    """The one option row that reads "Leave", or None.

    None when the template is missing, when no row matches, and when more than
    one does: "I cannot tell" must mean "click nothing" (as screenstate's
    reset check does for Return)."""
    tpl = template if template is not None else _leave_template()
    if tpl is None or frame is None:
        return None
    th, tw = tpl.shape[:2]
    hits = []
    for row in rows:
        pad = 6
        x0, y0 = max(0, row.x - pad), max(0, row.y - pad)
        crop = frame[y0:row.y + row.h + pad, x0:row.x + row.w + pad, :3]
        if crop.shape[0] < th or crop.shape[1] < tw:
            continue
        score = float(cv2.minMaxLoc(
            cv2.matchTemplate(crop, tpl[:, :, :3], cv2.TM_CCOEFF_NORMED))[1])
        if score >= LEAVE_THRESHOLD:
            hits.append(row)
    return hits[0] if len(hits) == 1 else None


def _closer_to_expected(a: Box, b: Box) -> bool:
    """Prefer whichever candidate sits nearer where the box was measured."""
    ex, ey, ew, eh = EXPECTED
    def miss(box):
        return (abs(box.x - ex) + abs(box.y - ey)
                + abs(box.w - ew) + abs(box.h - eh))
    return miss(a) < miss(b)


@dataclass
class Read:
    """Every page of one dialogue, and how it ended."""
    pages: list = field(default_factory=list)
    clicks: int = 0
    # CLOSED MEANS A BOX WAS SEEN AND THEN WENT, whether or not its words
    # were read: a transcriber that is down (run_farm swallows its errors)
    # used to make a dialogue clicked shut report closed=False.
    closed: bool = False
    reason: str = ""
    saw_box: bool = False
    # Clicks made on a page whose words came back empty.
    blank_pages: int = 0
    # Options menus left by their Leave row (see OPTION_ROW_*).
    menus_left: int = 0

    @property
    def text(self) -> str:
        return " | ".join(self.pages)

    def describe(self) -> str:
        if not self.pages and self.saw_box:
            end = ("then the box closed" if self.closed
                   else f"the box is still open — {self.reason or 'stopped'}")
            return (f"a dialogue box was on screen but no page could be read "
                    f"({self.blank_pages} blank over {self.clicks} click(s)); {end}")
        if not self.pages:
            return f"no dialogue was read — {self.reason or 'no box on screen'}"
        end = ("the box closed" if self.closed
               else f"the box is still open — {self.reason or 'stopped'}")
        menus = (f", {self.menus_left} options menu(s) left by Leave"
                 if self.menus_left else "")
        return (f"{len(self.pages)} page(s) over {self.clicks} click(s){menus}; "
                f"{end}")


def advance(*, frames, click, transcribe, sleep=time.sleep,
            after_click: float = AFTER_CLICK_SECONDS,
            max_pages: int = MAX_PAGES, on_note=None, on_frame=None) -> Read:
    """Read a dialogue to its end, clicking the box to turn the page.

    `frames()` gives a frame, `click(x, y)` sends one left click at those
    screen pixels, `transcribe(frame)` returns the words on it. Every click
    goes to the centre of a box this found on the frame it just looked at --
    never to a remembered position, because the box could have closed between
    the look and the click and the click would then land in the world.
    """
    note = on_note or (lambda text: None)
    out = Read()
    rechecked = False
    for page in range(1, max(1, int(max_pages)) + 1):
        frame = _look(frames)
        if frame is None:
            # NO FRAME IS NOT "NO BOX": one more look, then say so.
            sleep(after_click)
            frame = _look(frames)
            if frame is None:
                out.reason = "no frame to look for the box on"
                return out
        box = find(frame)
        if box is None:
            # AN OPTIONS MENU: its Leave row, or nothing (see OPTION_ROW_*).
            rows = find_options(frame)
            if rows:
                out.saw_box = True
                leave = leave_row(frame, rows)
                if leave is None:
                    out.reason = (f"an options menu of {len(rows)} row(s) and no "
                                  f"Leave row this recognises — pressing nothing, "
                                  f"because any other option may give something away")
                    note(f"dialogue: {out.reason}")
                    return out
                try:
                    sent = click(*leave.centre)
                except Exception as exc:
                    out.reason = f"could not click Leave ({exc})"
                    return out
                if sent is False:
                    out.reason = ("the click on Leave was held back by the owner's "
                                  "Pause or Take Over")
                    return out
                out.clicks += 1
                out.menus_left += 1
                note(f"dialogue: an options menu of {len(rows)} row(s) — clicked "
                     f"its Leave row at {leave.centre}")
                sleep(after_click)
                rechecked = False
                continue
            # CLOSED ONLY AFTER A SECOND LOOK: the menu that follows a last
            # page can take a moment to draw.
            if out.saw_box and not rechecked:
                rechecked = True
                sleep(after_click)
                continue
            out.closed = out.saw_box
            if not out.saw_box:
                out.reason = "no box on screen"
            return out
        rechecked = False
        out.saw_box = True
        words = " ".join(str(transcribe(frame) or "").split())
        # "NONE" ON A FRAME WITH A BOX IS A BLANK READ, not a page: the
        # question asks for NONE where it sees no dialogue, and a box between
        # pages draws so. MEASURED 2026-10-03 02:41:57-02:42:01 at the Bucko
        # Bee: page 2 read 'NONE', the next look 'NONE' again was taken for
        # "the page did not change", and the clicking stopped with the box
        # open -- the respawn after was swallowed by it.
        if words.upper().strip(" .'\"") == "NONE":
            words = ""
        if on_frame is not None:
            try:
                on_frame(frame, page)
            except Exception:
                pass
        # NEW AGAINST THE PAGE BEFORE, not every page so far: MEASURED
        # 2026-10-07 18:29, the Spirit Bear's long story says "Hmm..." at page
        # 12 and again at page 24, and the second was taken for a page that
        # did not turn -- the box left open, no quest reached (MAX_PAGES still
        # bounds a dialogue that goes round)
        if words and words != (out.pages[-1] if out.pages else None):
            out.pages.append(words)
            note(f"dialogue page {len(out.pages)}: {words[:140]!r}")
        elif words:
            # The same page twice means the click did not turn it. Say so
            # rather than clicking again at a screen that is not responding.
            out.reason = ("the page did not change after a click — not "
                          "clicking again")
            return out
        else:
            out.blank_pages += 1
        try:
            sent = click(*box.centre)
        except Exception as exc:
            out.reason = f"could not click ({exc})"
            return out
        if sent is False:
            # HELD BACK BY THE OWNER'S PAUSE OR TAKE OVER (brain/controls
            # STALE_AFTER_A_WAIT): the box was found on a frame from before it.
            out.reason = ("the click was held back by the owner's Pause or "
                          "Take Over — not clicking at a box found before it")
            return out
        out.clicks += 1
        sleep(after_click)
    out.reason = f"stopped after {max_pages} pages"
    return out


def _look(frames):
    try:
        return frames()
    except Exception:
        return None
