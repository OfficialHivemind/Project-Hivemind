"""Opening the inventory, reading the goal materials' counts, and closing it.

THE OWNER: "make sure it rechecks what i have and so it knows what goals".
The gear goals need materials -- 9,999 treats, 50 oil, 25 enzymes and 5 gold
eggs for the Honey Mask alone -- and the only counts the bot had were his
screenshot of 20 Sep. This is the errand that looks (DESIGN 8ea).

IT IS act/quests' ERRAND WITH A LIST INSTEAD OF A PANEL, under the same rules
(see that module for why each one exists):

  1. NO KEYS. One click on the measured HUD button (vision/inventory.button)
     opens it, the same click closes it, and the wheel scrolls it -- with the
     pointer parked over the list first, because a wheel over the world
     zooms the camera.
  2. VERIFY BEFORE READING, PIXELS FIRST. The list's left edge must show
     Natro's item marker (vision/inventory.item_rows, the test Natro makes
     before it turns the wheel at all), and then the transcription of the
     page it opened on, or of the top of the list, must name two inventory
     items (looks_like_inventory); anything else is backed out of, never
     read as counts.
  3. BACK OUT RATHER THAN IMPROVISE. The only way out it tries is the button
     it came in by (act/quests._close).
  4. SAY SO WHEN IT IS STUCK OPEN. `InventoryRead.menu_open` stays True
     unless the list's part of the screen was seen to go back to the world.
  5. ONE NOTCH BEFORE A BURST. The marker says a list is drawn, not that the
     wheel reaches it. The first turn is a single notch, and the wheel goes
     on only if the list moved under it; a notch that moved the world beside
     the list instead is taken back (one notch the other way) and the menu
     shut. Before every later turn the marker must still be there.
  6. THE WHEEL TURNS NOW OR NOT AT ALL. GuardedInput waits a scroll out
     through a Pause and then sends it (only a click is dropped after a wait,
     brain/controls.STALE_AFTER_A_WAIT), so a burst decided on before a
     Pause would land on whatever he left on screen. Every turn goes only
     while `may_send` says it would go without waiting (`_turn`).
  7. NOT OPENED ON TOP OF ITSELF. A list already open when the errand starts
     (left open in a Take Over, or by a run that stopped) is shut with its
     own button first, and the errand starts again from the world; and a
     close counts only once Natro's marker is gone from the list's edge too.

WHAT IS READ, AND HOW IT IS BELIEVED. Every page is pictured and transcribed
while the menu is open; the menu is then SHUT, and every goal material a page
names is asked about again with a closed question on the same picture
(vision/inventory.count_question) -- the pages are all in memory, so the menu
is open only while the wheel turns. A count is written down only when two
readings agree -- the transcription and the closed answer, or the closed
answers of two overlapping pages. A material no page names is UNKNOWN, never
zero: whether the menu lists an item you hold none of has not been seen.
The one exception is the Whirligig (`write(zero_unseen=("whirligig",))` in
run_farm): MEASURED runs 1067-1167, all 13 complete reads without its row came
after the count fell to 1-2, and every press after them was refused.
Templates for the menu's digits would be faster and are the next step, but
none has been cut: nothing in var/ shows this menu, so the first live reads
keep every page (var/inventory/<stamp>/) for exactly that.

WHAT IS NOT MEASURED YET, and is logged on every read so it can be: how far
one wheel notch scrolls the list (measured live, from the first notch, by
where the middle of the page went), what the probe notch did to the world
beside the list, whether the list's panel is opaque, and the marker itself:
MEASURED 2026-09-26, Natro's test found no marker in any of the 8,999 saved
route frames of the world (scratch account-fix/marker_world.py; at the
variation of 6 this module used before, 35 of them), but it has never been
tried on this machine's menu -- a read it refuses keeps its page for that,
and GIVE_UP_AFTER refusals in a row stop the tries until this code changes.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
import contextvars
from typing import Callable

from ..vision import inventory as inv
from ..vision import questmenu
from . import quests

# A notch moves the list by some pixels; a page of the list is 922 px and an
# item 80 (vision/inventory). Scrolling three quarters of a page at a time
# leaves a quarter read twice, more than one item, so an item cut by the
# page's edge is whole on one of the two.
PAGE_ADVANCE = 0.75
# THE MOST THE WHEEL IS TURNED, each way: Natro's own caps -- nm_InventorySearch
# scrolls at most `max:=70` notches looking for an item, and 100 to reach the
# end of the list first (its "scrolltoend" loop).
MAX_DOWN_NOTCHES = 70
MAX_TOP_NOTCHES = 100
TOP_BURST = 10
# Natro waits 500 ms after each scroll "for scroll to finish".
AFTER_SCROLL = 0.5
# How long the menu is given to draw before it is looked at: act/quests'.
SETTLE_SECONDS = quests.SETTLE_SECONDS
# THE WORLD'S OWN MOTION IS MEASURED OVER THE OPEN TEST'S OWN INTERVAL. The
# open test compares frames SETTLE_SECONDS (and a click) apart, and what the
# world changes by itself grows with the time between two looks -- bees
# crossing the strip -- so a baseline over a shorter gap lets the world pass
# for a menu. Three looks SETTLE_SECONDS apart, and the larger of the two
# pairs' changes is the baseline. The probe notch is judged over the same gap.
BASELINE_LOOKS = 3
# NATRO WAITS FOR THE ITEM MARKER before each scroll: 40 looks 50 ms apart,
# 2 s ("wait for red vignette effect to disappear", nm_InventorySearch), and
# gives up without scrolling. Five looks over the same 2 s here: a capture
# takes far longer than Natro's 50 ms bitmap grab.
MARK_LOOKS = 5
MARK_WAIT = 2.0
# A match of the middle of one page in the other this good is the same
# picture moved; a shift of 0 at that score is a list that did not move.
SHIFT_MATCH = 0.9
# Reads whose pictures are kept (a read is a dozen pages of ~300 KB).
KEEP_READS = 5

KEEP_DIR = Path(__file__).resolve().parents[3] / "var" / "inventory"
# EVERY TRY IS WRITTEN DOWN, read or not (`note_try`, var/inventory_tried.json),
# so a read that fails is not tried again by the next process: processes
# restart every 19 min (the median gap between the starts of attempts
# 400-451, attempts.log), and each failed try is an open and a close.
# MEASURED on the close this errand shares (act/quests._close), over the
# saved run logs: 5 of 365 quest-menu opens ended "would not close — stopping
# so the rejoin can clear it", each a rejoin and the Wealth Clock streak.
# `not_due` keeps tries the caller's hour apart whatever they found, and
# after GIVE_UP_AFTER tries in a row that backed out for want of Natro's
# marker -- a colour or a place that will not change by itself -- stops
# trying until this code (the two inventory modules) changes.
GIVE_UP_AFTER = 3
# Why a turn of the wheel was not sent (rule 6).
HELD = "the owner paused or has the controls"
# HOW MUCH MORE THAN ITS OWN MOTION THE WORLD MUST CHANGE for the probe notch
# to count as gone to the camera. MEASURED over the seven reads of runs
# 555-563: the list opens at its top every time, so the notch up moves it 0 px
# and the world beside it changes by the bees alone -- 25%, 28%, 29%, 31%, 33%
# against its baselines of 34%, 26%, 36%, 29%, 41%, and 29% against 24% at
# 21:27 on 2026-10-01, which act/quests' CLOSED_MARGIN (2%) called a zoom and
# backed out of. The other six went on to scroll the list under the same
# wheel. A zoom moves the whole view; the bees have exceeded their own
# baseline by at most 5 points.
WORLD_MARGIN = 0.12


@dataclass(frozen=True)
class Menu:
    """A list menu of the HUD, read this module's way: the inventory, and the
    bee menu (act/beemenu) that the game draws in the same column. Which HUD
    button opens it (vision/questmenu.BUTTONS), what proves a page is it,
    and what the model is asked to write down from each page."""
    name: str
    button_index: int
    looks_like: Callable[[str], bool]
    transcribe: str
    # The pixel sign that the list is on screen (rule 2): Natro's item marker
    # for the inventory; the bee menu's own rows (vision/beemenu.bee_rows).
    rows: Callable = inv.item_rows


INVENTORY = Menu("inventory", inv.BUTTON_INDEX, inv.looks_like_inventory,
                 inv.TRANSCRIBE)

# THE MENU BEING READ, for the helpers' pixel test (`_rows_of`): set by `_read`
# for its own length, so the inventory's helpers stay as they were.
_ROWS: contextvars.ContextVar = contextvars.ContextVar("list_rows", default=None)


def _rows_of(image) -> list[int]:
    return (_ROWS.get() or inv.item_rows)(image)


@dataclass
class InventoryRead:
    ok: bool = False
    counts: dict = field(default_factory=dict)     # {material: count}, agreed
    unsure: dict = field(default_factory=dict)     # {material: [answers]}
    seen: list = field(default_factory=list)       # materials named anywhere
    pages: int = 0
    complete: bool = False                         # reached the list's end
    px_per_notch: float | None = None
    reason: str = ""
    menu_open: bool = False
    changed: float = 0.0
    kept: str = ""
    seconds: float = 0.0              # the whole errand, menu open to shut
    probe: dict = field(default_factory=dict)   # what the first notch did
    no_marker: bool = False           # backed out: Natro's marker not seen
    caps: dict = field(default_factory=dict)    # {item: cap} drawn as count/cap

    def describe(self) -> str:
        if not self.ok:
            return f"did not read the inventory: {self.reason}"
        got = ", ".join(f"{k} {v:,}" for k, v in sorted(self.counts.items()))
        return (f"read {self.pages} page(s) of the inventory in "
                f"{self.seconds:.0f}s"
                + ("" if self.complete else " (not to the end)")
                + (f": {got}" if got else ": no goal material count agreed")
                + (f"; unsure of {', '.join(sorted(self.unsure))}"
                   if self.unsure else "")
                + (" — MENU STILL OPEN" if self.menu_open else ""))


def wanted(settings) -> bool:
    """`goals.read_inventory`, default on (the owner asked for it)."""
    if settings is None:
        return True
    try:
        return bool(settings.bool("goals.read_inventory"))
    except Exception:
        return True


def shift_between(a, b) -> tuple[float, float]:
    """(pixels the list moved UP from `a` to `b`, match score). The middle
    band of `b` is found in `a`: a list scrolled down shows in `b` what was
    lower in `a`."""
    import cv2
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    h = gb.shape[0]
    top, band = h // 3, h // 6
    probe = gb[top:top + band]
    result = cv2.matchTemplate(ga, probe, cv2.TM_CCOEFF_NORMED)
    _lo, score, _lo_at, at = cv2.minMaxLoc(result)
    return float(at[1] - top), float(score)


def read_inventory(vin, frames, ask, *, materials: dict, sleep=time.sleep,
                   on_note=None, settings=None, keep_dir: Path | None = None,
                   clock=time.time, extras: dict | None = None) -> InventoryRead:
    """Open the inventory, picture every page, read the counts, close it.

    `frames()` is the current frame; `ask(image, question)` is the vision
    model's answer or None; `materials` is {material: label} of what to
    count (the goal materials). `extras` is {item: label} of everything else
    worth knowing (brain/stash: the consumables a player decides about),
    counted from the page transcriptions when two pages agree, and asked
    about only when a single page names it. The pointer is parked in the
    middle of the world on every way out (act/quests.PARKED)."""
    note = on_note or (lambda text: None)
    result = InventoryRead()
    if not wanted(settings):
        result.reason = "goals.read_inventory is off in the settings"
        return result
    began = time.monotonic()
    try:
        return _read(vin, frames, ask, materials, sleep, note, result,
                     keep_dir or KEEP_DIR, clock, extras or {})
    finally:
        result.seconds = time.monotonic() - began
        quests._park(vin, note)


def read_list(vin, frames, ask, *, menu: Menu, count, result=None,
              sleep=time.sleep, on_note=None, keep_dir: Path,
              clock=time.time) -> InventoryRead:
    """`read_inventory` for another list menu in the same column: open it by
    `menu`'s button, picture every page under the same rules, close it, and
    hand the pages [(image, transcription)] to `count(pages, ask, note,
    result)`. `result` may be an InventoryRead subclass. The helpers' notes
    are said in the menu's own name."""
    base = on_note or (lambda text: None)

    def note(text: str) -> None:
        text = str(text)
        base(menu.name + text[len("inventory"):] if text.startswith("inventory")
             else text)
    result = result if result is not None else InventoryRead()
    began = time.monotonic()
    try:
        return _read(vin, frames, ask, {}, sleep, note, result, keep_dir,
                     clock, {}, menu=menu, count=count)
    finally:
        result.seconds = time.monotonic() - began
        quests._park(vin, note)


def _crop_of(frames, note):
    frame = quests._grab(frames, note)
    return None if frame is None else inv.crop(frame).copy()


def _beside(frame):
    """The world beside the list: everything right of its strip."""
    x, _y, w, _h = inv.INVENTORY_BOX
    return frame[:, x + w:, :3]


def _baseline(frames, sleep, note):
    """(the strip as the world shows it, how much the strip and the world
    beside it move by themselves), or None with no frame.

    THREE FRAMES OF THE WORLD FIRST, for how much it moves on its own. On
    the pad the bees fly through this strip: MEASURED on the quest menu's
    closes (run-4*.log), the world alone moved 6% to 39% of the whole frame
    between two looks, so a fixed "a tenth changed" cannot tell a menu from
    a swarm. The menu has to move the strip clearly more, over the same
    interval (BASELINE_LOOKS); the world beside the strip is measured too,
    for the probe notch."""
    looks = []
    for look in range(BASELINE_LOOKS):
        if look:
            sleep(SETTLE_SECONDS)
        frame = quests._grab(frames, note)
        if frame is None:
            return None
        looks.append((inv.crop(frame).copy(), _beside(frame).copy()))
        del frame
    pairs = list(zip(looks, looks[1:]))
    return (looks[-1][0],
            max(quests.changed_fraction(a[0], b[0]) for a, b in pairs),
            max(quests.changed_fraction(a[1], b[1]) for a, b in pairs))


def _shut_left_open(vin, frames, sleep, note, x, y) -> bool:
    """A LIST ALREADY OPEN (rule 7), shut with its own button: one click,
    never a second -- a second on a list that did shut opens it -- and shut
    only when the marker has gone for MARK_WAIT and the HUD is back."""
    note(f"inventory: the list is already open (Natro's item marker is on "
         f"its edge before any click) — shutting it with its own button, "
         f"({x}, {y}), first")
    try:
        if vin.click(x, y) is False:
            note("inventory: that click was held back by a Pause or a Take Over")
            return False
    except Exception as exc:
        note(f"inventory: could not click to shut it: {exc}")
        return False
    sleep(SETTLE_SECONDS)
    if _still_listed(frames, sleep, note) or not _world_back(frames, sleep, note):
        return False
    note("inventory: the list that was left open is shut")
    return True


def _read(vin, frames, ask, materials, sleep, note, result, keep_dir, clock,
          extras=None, menu: Menu | None = None, count=None):
    menu = menu or INVENTORY
    token = _ROWS.set(menu.rows)
    try:
        return _read_menu(vin, frames, ask, materials, sleep, note, result,
                          keep_dir, clock, extras, menu, count)
    finally:
        _ROWS.reset(token)


def _read_menu(vin, frames, ask, materials, sleep, note, result, keep_dir,
               clock, extras, menu: Menu, count, on_page=None):
    x, y = questmenu.button_at(menu.button_index)
    # ROBLOX'S OWN OVERLAY FIRST (act/quests.close_roblox_overlay): a "Shop
    # now" toast over x 77-287 of the HUD row (run-1005) covers the bees
    # button, and the close below judges crops it cannot see the shop in.
    clear, said = quests.close_roblox_overlay(vin, frames, sleep=sleep, note=note)
    if said:
        note(said)
    if not clear:
        result.reason = said + " — nothing clicked"
        return result
    got = _baseline(frames, sleep, note)
    # ALREADY OPEN (rule 7)? Natro's marker is on none of the 8,999 saved
    # frames of the world (the module note), so a marker before any click is
    # the list itself. Clicked as if to open, it would SHUT, the change would
    # pass the open test, the world would be backed out of, and the close
    # would open it again and call it shut. So it is shut first and the
    # world looked at again; if it will not shut, the errand says the menu
    # is open and clicks nothing more.
    if got is not None and _rows_of(got[0]):
        result.menu_open = True
        if not _shut_left_open(vin, frames, sleep, note, x, y):
            result.reason = (f"the {menu.name} was already open and did not "
                             f"shut with its own button — not clicking again")
            return result
        result.menu_open = False
        got = _baseline(frames, sleep, note)
        if got is not None and _rows_of(got[0]):
            result.menu_open = True
            result.reason = ("Natro's item marker is still on the list's edge "
                             "after the list left open was shut — not clicking "
                             "again")
            return result
    if got is None:
        result.reason = "no frame to compare against"
        return result
    before, motion, beside_motion = got
    del got
    note(f"opening the {menu.name}: clicking ({x}, {y})")
    try:
        sent = vin.click(x, y)
    except Exception as exc:
        result.reason = f"the click failed: {exc}"
        return result
    if sent is False:
        result.reason = ("the click was held back by the owner's Pause or "
                         "Take Over — nothing was clicked")
        return result
    sleep(SETTLE_SECONDS)
    opened = _crop_of(frames, note)
    result.changed = quests.changed_fraction(before, opened)
    if result.changed < max(quests.CHANGED_TO_OPEN,
                            motion + quests.CLOSED_MARGIN):
        # A MOVING WORLD HIDES THE CHANGE, NOT THE MARKER. MEASURED
        # 2026-10-03 07:22 and 10:43: Glue in a field while the pattern ran,
        # the world moving 98.9% and 77.2% by itself, which no list can beat
        # by the margin -- and Natro's marker is on none of the world's saved
        # frames (rule 7), so the marker on the list's edge is the list, as
        # Natro itself waits for it (MARK_LOOKS over MARK_WAIT).
        marked = None
        for _ in range(MARK_LOOKS):
            look = _crop_of(frames, note)
            if look is not None and _rows_of(look):
                marked = look
                break
            sleep(MARK_WAIT / MARK_LOOKS)
        if marked is None:
            result.reason = (f"nothing opened — {result.changed:.1%} of the list's "
                             f"part of the screen changed, against {motion:.1%} "
                             f"the world moved by itself, and Natro's marker did "
                             f"not show; no further clicking is done on a guess")
            return result
        note(f"opening the {menu.name}: {result.changed:.1%} changed against the "
             f"world's own {motion:.1%}, but Natro's marker is on the list's edge — open")
        opened = marked
    result.menu_open = True
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
    folder = keep_dir / stamp
    pages: list = []                       # (crop, transcription)

    def closing(reason: str = ""):
        if reason:
            result.reason = reason
        # ALREADY SHUT BY THE GAME. MEASURED 2026-10-03 00:43: after Yes on
        # "Use Glitter?" the game shut its own list, and the close's click on
        # the button opened it again -- open through the trip, found "left
        # open" by the next use at 00:49. So a list whose marker is gone, with
        # the world back, is shut without a click.
        now = _crop_of(frames, note)
        if (now is not None and not _rows_of(now)
                and _world_back(frames, sleep, note)
                and not _still_listed(frames, sleep, note)):
            result.menu_open = False
            note("inventory: the list is already shut (the game shut it) — no click")
            return result
        quests._close(vin, lambda: _crop_of(frames, note), before, result,
                      sleep, note, x, y, opened=opened, what=menu.name,
                      motion=motion)
        # SHUT MEANS THE WORLD IS BACK AND THE LIST IS GONE: the HUD's pills
        # show with the list open beside them, and the close's `motion` test
        # is loose on a busy pad, so Natro's marker must be gone too (rule 7).
        if not result.menu_open and (not _world_back(frames, sleep, note)
                                     or _still_listed(frames, sleep, note)):
            result.menu_open = True
        return result

    def backing_out(reason: str):
        closing(reason)
        _keep(folder, pages, result, note)
        return result

    # PIXELS BEFORE WORDS (rule 2): no marker, no model call and no wheel.
    marks = _rows_of(opened)
    if not marks:
        pages.append((opened, ""))                    # kept, to measure it
        result.no_marker = True
        return backing_out(
            f"something opened ({result.changed:.0%} of the list's part "
            f"changed, the world {motion:.0%} by itself) but Natro's item "
            f"marker is not on the list's edge — backing out; the page is "
            f"kept in {folder} so the marker can be measured")
    first = _transcribe(ask, opened, note, menu.transcribe) or ""
    # THE WORDS MAY COME FROM THE TOP OF THE LIST INSTEAD. The list opens
    # where it was last left, and a page of planters or potions names none
    # of INVENTORY_NAMES; backing out there would leave it there, and every
    # later process would back out of the same page. So a first page with
    # the marker but not the words is taken to the top -- the wheel guarded
    # by the marker and the probe notch, two pixel tests -- and the top
    # page must name them instead, before anything is read as a count.
    named = menu.looks_like(first)
    note(f"{menu.name} open ({result.changed:.0%} of the list's part changed, "
         f"the world {motion:.0%} by itself); item markers at {marks[:12]}"
         + ("" if named else f"; the page does not read like the {menu.name} "
                             f"(read {first[:80]!r}), so the top must"))

    # TO THE TOP FIRST: the list opens where it was last left. A read that
    # stops before a page is read keeps the first one, for a look.
    try:
        vin.move_mouse(*inv.SCROLL_AT)
    except Exception as exc:
        pages.append((opened, first))
        return backing_out(f"could not park the pointer over the list: {exc}")
    why = _may_turn(vin, before, opened, motion)
    if why:
        pages.append((opened, first))
        return backing_out(f"{why} — not turning the wheel")
    how, page = _probe(vin, frames, sleep, note, beside_motion, result,
                       before, motion)
    if how not in ("moved", "top"):
        pages.append((opened, first))
        return backing_out({
            "held": f"{result.probe.get('held')} — not turning the wheel",
            "world": "the probe notch moved the world beside the list and not "
                     "the list — " + ("it was taken back" if result.probe.get(
                         "undone") else f"it was NOT taken back ({HELD})")
                     + ", and the menu is shut",
            "reversed": "the probe notch UP scrolled the list down — the "
                        "wheel's direction is not the one Input.scroll says, "
                        "so no burst is sent on a guess",
        }.get(how, "the probe notch neither moved the list nor left it as "
                   "it was — not turning the wheel again"))
    top_text = first if how == "top" else None
    # ONE STILL BURST IS NOT THE TOP. MEASURED 2026-10-11 04:06: the list opened
    # at its bottom, the probe notch moved it 100 px, then a burst of 10 moved
    # nothing -- read as "at the top, 1 notch", only the bottom page was read
    # and the Glitter on it was "no row titled 'Glitter'". The top is usually
    # 21-31 notches up; it is called only after two bursts in a row move nothing.
    still = 0
    for turned in range(MAX_TOP_NOTCHES // TOP_BURST if how == "moved" else 0):
        page = _marked(frames, note, sleep, page)
        why = _may_turn(vin, before, page, motion)
        if why or not _turn(vin, -TOP_BURST):
            pages.append((opened, first))
            return backing_out(f"{why or HELD} — not turning the wheel over it")
        sleep(AFTER_SCROLL)
        now = _crop_of(frames, note)
        if now is None:
            pages.append((opened, first))
            return backing_out("no frame while scrolling to the top")
        moved, score = shift_between(page, now)
        if score >= SHIFT_MATCH and abs(moved) < 1.0:
            still += 1
            if still >= 2:
                note(f"inventory: at the top, {1 + turned * TOP_BURST} notch(es) "
                     f"up from where it opened")
                break
            continue
        still = 0
        page = now
    text = (top_text if top_text is not None
            else _transcribe(ask, page, note, menu.transcribe) or "")
    if not named and not menu.looks_like(text):
        pages.extend([(opened, first)] + ([(page, text)] if how == "moved" else []))
        return backing_out(f"neither the page it opened on nor the top of the "
                           f"list reads like the {menu.name} (read "
                           f"{text[:80]!r}) — backing out")
    pages.append((page, text))
    # A PAGE'S OWN JOB (`use_item`): done on it, the scroll stops there
    done = bool(on_page(page)) if on_page is not None else False

    # DOWN, A MEASURED PAGE AT A TIME. The first notch measures how far one
    # goes; until that is known every notch is a page, so nothing is skipped.
    # A PAGE OF OTHER ITEMS DOES NOT STOP IT: the first page was verified,
    # and from there the list is the list while the marker and the strip say
    # so -- a page of potions and planters names none of the goal words.
    last, notches, step = page, 0, 1
    while not done and notches < MAX_DOWN_NOTCHES:
        if getattr(vin, "stale", False):
            return backing_out("the owner took the controls — not turning the "
                               "wheel any more")
        last = _marked(frames, note, sleep, last)
        why = _may_turn(vin, before, last, motion)
        if why or not _turn(vin, step):
            note(f"inventory: {why or HELD} — stopping the scroll there, and "
                 f"keeping the {len(pages)} page(s) read")
            break
        notches += step
        sleep(AFTER_SCROLL)
        now = _crop_of(frames, note)
        if now is None:
            break
        moved, score = shift_between(last, now)
        last = now
        if score >= SHIFT_MATCH and abs(moved) < 1.0:
            result.complete = True                  # the wheel moved nothing
            break
        if result.px_per_notch is None and score >= SHIFT_MATCH and moved > 0:
            result.px_per_notch = moved / step
            per_page = int(PAGE_ADVANCE * now.shape[0] / result.px_per_notch)
            note(f"inventory: one notch scrolls {result.px_per_notch:.0f} px, "
                 f"so {max(1, per_page - 1)} notch(es) a page")
            if per_page >= 2:
                # This notch was only the measurement: the next page is read
                # from PAGE_ADVANCE of a page past the last one read.
                step = per_page - 1
                continue
        pages.append((now, _transcribe(ask, now, note, menu.transcribe) or ""))
        if on_page is not None and on_page(now):
            break
    result.pages = len(pages)

    # SHUT IT FIRST. Every page is in memory, so the closed questions below
    # -- one model call per material a page names, 2-8 s an image (DESIGN 5,
    # the stack table) -- need no menu on screen: a dozen pages would
    # otherwise hold it open on the pad for minutes, ageing `before` (the
    # frame the close is judged against) and leaving it open if the process
    # dies in a model hang.
    closing()

    if count is None:
        count_pages(pages, materials, extras, ask, note, result)
    else:
        count(pages, ask, note, result)
    result.ok = True
    result.reason = ""
    _keep(folder, pages, result, note)
    result.kept = str(folder)
    return result


def _still_listed(frames, sleep, note) -> bool:
    """Is Natro's item marker still on the list's edge, on any look over
    MARK_WAIT (its wait for the red damage vignette, which hides it)? The
    world shows it on none of 8,999 frames (the module note)."""
    if _marked(frames, note, sleep, _crop_of(frames, note)) is None:
        return False
    note("inventory: Natro's item marker is still on the list's edge — "
         "calling the list open")
    return True


def _world_back(frames, sleep, note) -> bool:
    """THE WORLD IS BACK when the HUD's Honey and Pollen pills are on screen
    (vision/screenstate.hud_present, the test every HUD reading starts with):
    the list's strip looking like the world is not enough on its own, since
    something else could cover the screen. Two looks, half a second apart:
    MEASURED, 5 of the 1,879 saved route frames of attempts 400-445 read no
    HUD (scratch account/hudnoise.py), so one miss is not a covered screen;
    two in a row at that rate would be about one in 140,000, were the misses
    independent."""
    from ..vision import screenstate as ss
    for look in range(2):
        frame = quests._grab(frames, note)
        try:
            if frame is not None and ss.hud_present(frame):
                return True
        except Exception:
            pass
        if look == 0:
            sleep(0.5)
    note("inventory: the list looks shut but the HUD is not on screen — "
         "calling the world not back")
    return False


# A WORLD THIS BUSY CANNOT BE TOLD FROM A LIST BY HOW MUCH CHANGED: in a field
# under a running pattern it moves 77-99% by itself (MEASURED 2026-10-03 07:22
# and 10:43, Glue), more than any list beats by the margin. There the marker,
# which the world never shows (rule 7), decides alone; on a calm pad (the bee
# menu measured the world at 27-39%) both tests stand.
MOVING_WORLD = 0.6


def _may_turn(vin, before, page, motion: float) -> str:
    """May the wheel turn now? "" if so, else why not. Not after a Take Over
    (the owner's hands; the input would be dropped anyway, brain/controls),
    not when the list's part of the screen is back to the world -- a wheel
    over the world zooms the camera; `motion` is the world's own, as for the
    open test -- and not without Natro's item marker on the list's edge,
    the pixel sign Natro itself scrolls on (rule 2)."""
    if getattr(vin, "stale", False):
        return "the owner took the controls"
    if page is None:
        return (f"no look at the list showed Natro's item marker for "
                f"{MARK_WAIT:.0f} s")
    if motion < MOVING_WORLD and quests.changed_fraction(before, page) < max(
            quests.CHANGED_TO_OPEN, motion + quests.CLOSED_MARGIN):
        return "the list's part of the screen looks like the world again"
    if not _rows_of(page):
        return "Natro's item marker is not on the list's edge"
    return ""


def _turn(vin, notches: int) -> bool:
    """Turn the wheel NOW, or not at all (rule 6): False, and nothing sent,
    unless an input would go out without waiting."""
    if not getattr(vin, "may_send", lambda: True)():
        return False
    # THE POINTER IS PUT BACK OVER THE LIST BEFORE EVERY TURN, with a pixel's
    # motion: a wheel turn goes to what Roblox last saw hovered. MEASURED
    # 2026-10-11 07:17 mid-gather: the probe notch (just after the park) moved
    # the list 100 px, then two bursts of 10 up and a notch down moved nothing,
    # mid-list -- read as "at the top" and "the end", the Glitter not found.
    # ponytail: the cause is inferred (token pick-ups redraw the list and drop
    # its hover); if a re-park does not cure it, single notches are next.
    try:
        x, y = inv.SCROLL_AT
        vin.move_mouse(x + 1, y)
        vin.move_mouse(x, y)
    except Exception:
        pass
    vin.scroll(notches)
    return True


def _marked(frames, note, sleep, page):
    """`page`, or a newer look at the list, showing Natro's item marker;
    None when none does within MARK_WAIT (see there)."""
    for look in range(MARK_LOOKS):
        if page is not None and _rows_of(page):
            return page
        if look + 1 < MARK_LOOKS:
            sleep(MARK_WAIT / (MARK_LOOKS - 1))
            page = _crop_of(frames, note)
    return None


def _probe(vin, frames, sleep, note, beside_motion: float, result,
           before, motion: float):
    """ONE NOTCH UP, AND LOOK (rule 5). Returns (how, the list after):
    "moved" -- the list scrolled under the wheel, so it reaches the list;
    "top" -- neither the list nor the world moved, the list was already at
    its top; "world" -- the list did not move but the world beside it did,
    more than it moves by itself, so the notch went to the camera and is
    taken back; "reversed" -- the list moved the wrong way; "held" -- the
    checks before a turn (`_may_turn` on a fresh look, then `_turn`) said
    no, and nothing was sent; "unsure" -- anything else. Judged over
    SETTLE_SECONDS, the interval `beside_motion` was measured over, and kept
    in `result.probe` so it can be measured."""
    # A FRESH LOOK SHOWING THE MARKER, as before every turn: the pointer
    # was parked over the list since the last one, and that move waits a
    # Pause out.
    pre = None
    for look in range(MARK_LOOKS):
        pre = quests._grab(frames, note)
        if pre is not None and _rows_of(inv.crop(pre)):
            break
        if look + 1 < MARK_LOOKS:
            sleep(MARK_WAIT / (MARK_LOOKS - 1))
    if pre is None:
        result.probe = {"held": "no frame to look at before the notch"}
        return "held", None
    pre_list, pre_beside = inv.crop(pre).copy(), _beside(pre).copy()
    del pre
    why = _may_turn(vin, before, pre_list if _rows_of(pre_list) else None,
                    motion)
    if why or not _turn(vin, -1):
        result.probe = {"held": why or HELD}
        return "held", None
    sleep(SETTLE_SECONDS)
    post = quests._grab(frames, note)
    if post is None:
        return "unsure", None
    now, world = inv.crop(post).copy(), quests.changed_fraction(
        pre_beside, _beside(post))
    del post, pre_beside
    moved, score = shift_between(pre_list, now)
    result.probe = {"moved_px": round(moved, 1), "match": round(score, 3),
                    "beside_changed": round(world, 3),
                    "beside_by_itself": round(beside_motion, 3)}
    note(f"inventory: one notch up moved the list {-moved:+.0f} px (match "
         f"{score:.2f}); the world beside it changed {world:.0%}, against "
         f"{beside_motion:.0%} by itself")
    if score >= SHIFT_MATCH and moved <= -1.0:
        return "moved", now
    if score >= SHIFT_MATCH and moved >= 1.0:
        return "reversed", now
    if world > beside_motion + WORLD_MARGIN:
        result.probe["undone"] = _turn(vin, 1)
        note("inventory: the notch went to the camera — "
             + ("one notch back" if result.probe["undone"] else
                "the notch back was NOT sent: " + HELD))
        return "world", now
    if score >= SHIFT_MATCH:
        return "top", now
    return "unsure", now


def _ask(ask, image, question, note):
    try:
        return ask(image, question)
    except Exception as exc:
        note(f"inventory: the model did not answer ({exc})")
        return None


def _transcribe(ask, image, note, question: str | None = None):
    return (_ask(ask, image, question or inv.TRANSCRIBE, note)
            if image is not None else None)


def _keep(folder: Path, pages, result: InventoryRead, note) -> None:
    """Every page's picture and words, for the measurement the module note
    names, capped at KEEP_READS reads."""
    try:
        import cv2
        folder.mkdir(parents=True, exist_ok=True)
        for i, (image, text) in enumerate(pages):
            cv2.imwrite(str(folder / f"page-{i:02d}.png"), image)
            (folder / f"page-{i:02d}.txt").write_text(str(text or ""))
        (folder / "read.json").write_text(json.dumps({
            "counts": result.counts, "unsure": result.unsure,
            "seen": result.seen, "pages": len(pages),
            "complete": result.complete, "px_per_notch": result.px_per_notch,
            "item_rows": [_rows_of(image) for image, _t in pages],
            "probe": result.probe, "changed": round(result.changed, 3),
            "reason": result.reason, "menu_open": result.menu_open,
            "no_marker": result.no_marker}, indent=1))
        reads = sorted(p for p in folder.parent.iterdir() if p.is_dir())
        for old in reads[:-KEEP_READS]:
            for f in old.iterdir():
                f.unlink()
            old.rmdir()
    except Exception as exc:
        note(f"inventory: could not keep the pages ({exc})")


def _code(paths=None) -> str:
    """This code, for the give-up (GIVE_UP_AFTER): the two inventory
    modules' bytes, since a fix to the marker test is a change to one -- or
    `paths`, for another menu read this way (act/beemenu's own modules)."""
    import hashlib
    digest = hashlib.sha1()
    for path in (paths or (Path(__file__), Path(inv.__file__))):
        try:
            digest.update(path.read_bytes())
        except OSError:
            pass
    return digest.hexdigest()[:12]


def _tried(path) -> dict:
    try:
        body = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def mark_dirty(path, why: str, clock=time.time) -> None:
    """Note in a read's file (var/inventory.json, var/bees.json) that what it
    counted has changed since -- an egg bought, an egg hatched -- so the next
    errand reads it again whatever its age, and nothing plans on the old count
    meanwhile (brain/goals.slot_waits). A read writes the file anew, without it."""
    from ..files import atomic_write
    body = _tried(path)
    body["dirty"] = f"{why} at {time.strftime('%H:%M', time.localtime(clock()))}"
    body["dirty_at"] = clock()
    atomic_write(Path(path), json.dumps(body, indent=1))


def dirty(path) -> str:
    """Why a read's file is out of date (`mark_dirty`), or ""."""
    return str(_tried(path).get("dirty") or "")


def note_try(path: Path, result: InventoryRead, clock=time.time,
             code_paths=None) -> dict:
    """var/inventory_tried.json: the last try, read or not, and how many in
    a row on this code backed out for want of Natro's marker (see
    GIVE_UP_AFTER). Returns what it wrote."""
    from ..files import atomic_write
    last = _tried(path)
    code = _code(code_paths)
    run = int(last.get("no_marker_in_a_row") or 0) if last.get("code") == code else 0
    body = {"at": clock(), "ok": bool(result.ok), "reason": str(result.reason),
            "menu_open": bool(result.menu_open), "code": code,
            "no_marker_in_a_row": run + 1 if result.no_marker else 0,
            "kept": str(result.kept), "complete": bool(result.complete)}
    atomic_write(Path(path), json.dumps(body, indent=1))
    return body


def not_due(path: Path, skip_seconds: float, clock=time.time,
            code_paths=None) -> str:
    """Why the last try says not to try now, or "": it gave up on this code,
    or it was under `skip_seconds` ago, whatever it found."""
    last = _tried(path)
    run = int(last.get("no_marker_in_a_row") or 0)
    if run >= GIVE_UP_AFTER and last.get("code") == _code(code_paths):
        if code_paths:
            return (f"the list's rows were not seen on the last {run} tries, "
                    f"so it is not tried again until its code changes")
        return (f"Natro's item marker was not on the list on the last {run} "
                f"tries, so it is not tried again until the inventory code "
                f"changes (the pages are in var/inventory/)")
    try:
        age = clock() - float(last.get("at") or 0.0)
    except (TypeError, ValueError):
        return ""
    if 0 <= age < skip_seconds:
        return (f"tried {age / 60:.0f} min ago"
                + ("" if last.get("ok") else
                   f", and did not read it ({str(last.get('reason'))[:100]})"))
    return ""


# A COUNT THAT MOVED WHILE IT WAS READ. MEASURED 2026-10-06 22:17 (var/inventory/
# 20261006-221716): "Treat: x30019" on one page and "Treat: 30020" on the next --
# a treat came in from the leaves between them -- each reading agreeing with its
# own page, and 30,019 Treats went down as unknown: the quest's 300 were not fed
# ("0 Treat counted"). Readings this close are one count, and the smaller is kept.
COUNT_DRIFT_MIN = 2
COUNT_DRIFT_SHARE = 0.001


def _drifted(values) -> int | None:
    """The smallest of `values` when they differ, but by no more than a count
    moves while it is read (COUNT_DRIFT_*); else None."""
    nums = sorted({int(v) for v in values
                   if isinstance(v, int) or str(v).strip().isdigit()})
    if len(nums) > 1 and nums[-1] - nums[0] <= max(COUNT_DRIFT_MIN,
                                                   COUNT_DRIFT_SHARE * nums[-1]):
        return nums[0]
    return None


def count_pages(pages, materials: dict, extras: dict | None, ask, note,
                result: InventoryRead) -> None:
    """The counts of `pages` [(image, transcription)], into `result`:
    `materials` by two agreeing readings each (a transcription and a
    closed question, or two questions); `extras` by two pages' agreeing
    transcriptions, or one and a question."""
    # THE COUNTS: two agreeing readings each -- the geometric reading
    # (`geometric_counts`) one of them where it read the row.
    closed: dict = {}
    from_text: dict = {}
    geo: dict = {}
    labels = {**{k: v for k, v in (extras or {}).items()}, **materials}
    for image, _text in pages:
        try:
            for key, value in geometric_counts(image, labels).items():
                geo.setdefault(key, []).append(value)
        except Exception as exc:
            note(f"inventory: the rows' own counts could not be read ({exc})")
            break
    for i, (image, text) in enumerate(pages):
        for key, value in inv.counts_in(text, materials).items():
            from_text.setdefault(key, set()).add(value)
        for key in sorted(inv.names_in(text, materials)):
            answer = _ask(ask, image, inv.count_question(materials[key]), note)
            closed.setdefault(key, []).append((i, answer, inv.answer_count(answer)))
    # THE EXTRAS (brain/stash's consumables): the transcription's own count
    # when two pages agree -- the list's pages overlap, so most rows appear
    # twice -- and one closed question when only one page names it.
    extras = {k: v for k, v in (extras or {}).items() if k not in materials}
    extra_reads: dict = {}
    for i, (image, text) in enumerate(pages):
        for key, value in inv.counts_in(text, extras).items():
            extra_reads.setdefault(key, []).append((i, value))
        for key, cap in inv.caps_in(text, {**materials, **extras}).items():
            result.caps[key] = cap
    for key, reads in sorted(extra_reads.items()):
        values = [v for _i, v in reads]
        twice = {v for v in values if values.count(v) >= 2}
        if len(twice) == 1:
            result.counts[key] = twice.pop()
            continue
        both = {v for v in values if v in geo.get(key, [])}
        if len(both) == 1:
            result.counts[key] = both.pop()
            continue
        if len(set(values)) == 1:
            i = reads[0][0]
            answer = _ask(ask, pages[i][0], inv.count_question(extras[key]), note)
            if inv.answer_count(answer) == values[0]:
                result.counts[key] = values[0]
                continue
        drift = _drifted(values)
        if drift is not None:
            result.counts[key] = drift
            continue
        result.unsure[key] = [str(v) for v in values]
    result.seen = sorted(set(closed) | set(from_text) | set(extra_reads))
    for key in sorted(set(closed) | set(from_text)):
        answers = [n for _i, _a, n in closed.get(key, []) if n is not None]
        seen_geo = geo.get(key, [])
        agreed = ({n for n in answers if n in from_text.get(key, set())}
                  or {n for n in seen_geo if n in from_text.get(key, set()) or n in answers}
                  or {n for n in answers if answers.count(n) >= 2}
                  or {n for n in seen_geo if seen_geo.count(n) >= 2})
        drift = _drifted(agreed or set(answers) | from_text.get(key, set()) | set(seen_geo))
        if len(agreed) == 1:
            result.counts[key] = agreed.pop()
        elif drift is not None:
            result.counts[key] = drift
        else:
            result.unsure[key] = [a for _i, a, _n in closed.get(key, [])] + \
                sorted(from_text.get(key, set()))


# A COUNT THAT JUMPS FOR ONE READ AND FALLS BACK. MEASURED 2026-10-19..21
# (runs 1067-1167): royal_jelly read 7 -> 17 -> 7 and 7 -> 21 -> 7, moon_charm
# 11 -> 36 -> 11 (run-1167 21:47 then 22:24), each pair of readings agreeing
# on the wrong row. A rise past the last count by more than this, with no
# purchase on record since, keeps its last count (also noted in `doubted` and
# `unsure` as [last, new]) until a second read says about the same new number.
# ponytail: quest rewards and sprouts also raise counts with no purchase;
# those wait one read (about 35 min, run-1167) at the old count.
SPIKE_MIN = 5
SPIKE_SHARE = 0.5


def doubted(prev: dict, counts: dict, bought_since: bool, zeroed=()) -> dict:
    """{key: [last, new]} for each of `counts` that rose past its last count
    in `prev` (a var/inventory.json body) by more than SPIKE_*, unless the
    new number is at least the one doubted last time less SPIKE_MIN (a real
    gain, maybe still rising or spent from since), anything was bought since,
    or the key is one of `zeroed` whose last count was a written 0 (a restock
    from none: holding it at 0 would refuse the rescue that needs it)."""
    if bought_since:
        return {}
    items = prev.get("items") or {}
    unsure = prev.get("unsure") or {}
    out = {}
    for key, new in counts.items():
        last = (items.get(key) or {}).get("count")
        seen = [str(v) for v in unsure.get(key) or []]
        if last is None and seen:
            try:
                last = min(int(str(v).replace(",", "")) for v in seen)
            except ValueError:
                last = None
        last_doubt = (prev.get("doubted") or {}).get(key)
        # A STEADY RISE IS BELIEVED ON ITS SECOND READ. Replayed 2026-10-21
        # over runs 1053-1167: requiring the second read within 5 of the
        # first held tickets at 5 from 06:41 to 14:17 (runs 1103-1108) while
        # the reads said 77, 83, 90, 115. 7 -> 17 -> 7 is still held.
        if last is None or str(new) in seen or (key in zeroed and int(last) == 0) or (
                last_doubt and int(new) >= int(last_doubt[1]) - SPIKE_MIN):
            continue                # the second read at or past the doubted number
        if int(new) > int(last) + max(SPIKE_MIN, SPIKE_SHARE * int(last)):
            out[key] = [str(last), str(new)]
    return out


def write(path: Path, result: InventoryRead, labels: dict, clock=time.time,
          zero_unseen=()) -> dict:
    """var/inventory.json: the agreed counts, what else was seen, and when.
    Written only from a read that got past the check that it is the list.
    Returns the counts held back as `doubted` ({key: [last, new]}).
    `zero_unseen`: keys counted 0 when a read to the list's end never saw
    them -- the game lists no row for an item none are held of. MEASURED
    runs 1067-1167: all 13 complete reads without a Whirligig row came after
    the count fell to 1-2, and every hotbar press after them was refused."""
    from ..files import atomic_write
    if not result.ok:
        return {}
    path = Path(path)
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev = {}
    if not isinstance(prev, dict):
        prev = {}
    try:
        since = float(prev.get("read_at") or 0.0)
        rows = json.loads(path.with_name("purchases.json").read_text(encoding="utf-8"))
        bought = any(r.get("ok") and float(r.get("at") or 0) >= since for r in rows)
    except FileNotFoundError:
        bought = False              # nothing ever bought
    except (OSError, ValueError, TypeError, AttributeError):
        bought = True               # no ledger read: nothing is doubted
    # A Blender craft collected since is a gain too (var/blender.json "made":
    # [at, item, qty]). The run-1059 18:31 holds (enzymes 16 -> 51, glitter
    # 9 -> 16, jelly_beans 8 -> 15) look like crafts.
    try:
        made = json.loads(path.with_name("blender.json").read_text(encoding="utf-8")).get("made") or []
        bought = bought or any(float(m[0]) >= since for m in made)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, AttributeError, IndexError, KeyError):
        bought = True
    counts = dict(result.counts)
    if result.complete:
        for k in zero_unseen:
            if k not in counts and k not in result.unsure and k not in result.seen:
                counts[k] = 0
    held = doubted(prev, counts, bought, zeroed=zero_unseen)
    counts = {**counts, **{k: int(a) for k, (a, _b) in held.items()}}
    now = clock()
    # THE READS' COUNTS, KEPT (brain/goals.material_rates: how fast each
    # material comes, for the goal's slowest input)
    from ..brain.goals import READS_KEPT
    reads = [e for e in prev.get("reads") or () if isinstance(e, list)][-(READS_KEPT - 1):]
    reads.append([now, {k: int(v) for k, v in sorted(counts.items())}])
    atomic_write(path, json.dumps({
        "read_at": now,
        "items": {k: {"count": v, "label": labels.get(k, k)}
                  for k, v in sorted(counts.items())},
        "caps": dict(sorted(result.caps.items())),
        "unsure": {**result.unsure, **held}, "doubted": held,
        "seen": result.seen, "pages": result.pages,
        "complete": result.complete, "kept": result.kept,
        "note": ("a material not in `items` is unknown, not zero (a Whirligig "
                 "a complete read never saw is written 0); `unsure` "
                 "holds the readings that did not agree"),
        "reads": reads,
    }, indent=1))
    return held


# ---- using an item: one click on its icon ----------------------------------
#
# THE OWNER, 2026-10-01/02: "use stuff", and the bot "can spend my honey
# tickets and other recourses without my permission". The list's rows are 90 px
# apart, each marked at its left edge by Natro's item marker -- MEASURED on
# var/inventory/20261002-220224/page-01.png: the markers come three to a row
# (12, 33, 54 / 97, 118, 139 / ...), the row's title sits from the first one
# less 5 for 32 px over x 96..306 (read exactly by tesseract: Honeysuckle,
# Whirligig, Field Dice, Smooth Dice, Jelly Beans, Red Extract, Blue Extract,
# Glitter, Glue), and the icon holds x 5..90 with the count ("x18") at its
# foot. An item is used by ONE click on its icon -- the row found by its own
# title, read exactly, so a Whirligig (which teleports home) or a Honeysuckle
# (a switch) is never clicked for another -- and believed used only when the
# count on the icon fell by one.
ROW_PITCH = 90
ROW_TITLE = (96, -6, 306, 32)           # x0, dy0, x1, dy1 from the row's first marker
ROW_COUNT = (40, 46, 94, 76)            # the "x18" at the icon's foot (white, outlined)
ROW_ICON = (48, 40)                     # the click, from the row's first marker
USE_SETTLE_S = 1.2
# THE ITEM'S OWN QUESTION. MEASURED 2026-10-03 00:26 (the first Glitter, var/
# incidents/20261003-002653-hud-hold): a click on the icon opens "Use
# Glitter?" with Yes and No over a dimmed screen -- the HUD with it, so the
# world guard, after 60 s unanswered, stopped the run. At 1920x1080: the blue
# panel x 742..1178, y 434..623; Yes, green, x 779..944 and No, red, x 977..
# 1142, both y 564..613. Yes only on an exact "Use <item>?"; anything else
# that opened there is answered No.
DIALOG_PANEL = (742, 434, 1178, 623)
DIALOG_TITLE = (760, 452, 1160, 548)
# THE QUESTION'S OWN LINE, when the game adds a second: MEASURED 2026-10-09
# 11:45 (var/shoplook/20261009-114554-jelly-roll-asked.jpg) the box read
# "Transform Rascal Bee? / (Auto-Jelly is ON)", the one-line read of the whole
# title gave '" huie-Jelly ON' (three Royal Jelly rolls answered No for it), and
# this top half reads 'Transform Rascal Bee?' exactly.
DIALOG_TITLE_TOP = (760, 452, 1160, 506)
DIALOG_TITLE_BOTTOM = (760, 500, 1160, 548)    # the second line, read apart (dialog_question)
DIALOG_YES = (779, 564, 944, 613)
DIALOG_NO = (977, 564, 1142, 613)


def _share(frame, box, colour: str) -> float:
    import cv2
    import numpy as np
    if frame is None:
        return 0.0
    x0, y0, x1, y1 = box
    patch = frame[y0:y1, x0:x1, :3]
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(np.ascontiguousarray(patch), cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    if colour == "green":
        m = (h >= 40) & (h <= 85) & (s >= 120) & (v >= 90)
    elif colour == "red":
        m = ((h <= 8) | (h >= 170)) & (s >= 150) & (v >= 120)
    else:                                  # the panel's blue
        m = (h >= 100) & (h <= 120) & (s >= 150) & (v >= 160)
    return float(m.mean())


def dialog_open(frame) -> bool:
    """The Yes/No question is on screen: its blue panel, green Yes, red No."""
    return (_share(frame, DIALOG_PANEL, "blue") >= 0.35
            and _share(frame, DIALOG_YES, "green") >= 0.5
            and _share(frame, DIALOG_NO, "red") >= 0.5)


# A QUESTION READ THROUGH ITS FONT'S NOISE. MEASURED 2026-10-06 04:31: "Transform
# Commander Bee?" was read 'transforneceommander', not the exact words, and the
# jelly was answered No. A read is taken for `want` only when the whole is at
# least QUESTION_SIMILAR like it, the bee's own name at least NAME_SIMILAR, it
# is no more than QUESTION_SLACK letters longer (so "Gifted Commander Bee" is not
# "Commander Bee"), and it says nothing of a gift or the auto-jelly. Other bees
# score 0.44 or less on the name (Diamond, Demon, Tabby against Commander).
QUESTION_SIMILAR = 0.8
NAME_SIMILAR = 0.85
QUESTION_SLACK = 2


def question_matches(read, want: str, name: str) -> bool:
    """Is `read` the question `want` (naming the bee `name`), as noisy OCR gives it?"""
    import difflib
    letters = lambda t: re.sub(r"[^a-z]", "", str(t or "").lower())  # noqa: E731
    got, exp, bee = letters(read), letters(want), letters(name)
    if not got or not exp or not bee:
        return False
    if got == exp:
        return True
    if "gift" in got or "auto" in got or len(got) > len(exp) + QUESTION_SLACK:
        return False
    if difflib.SequenceMatcher(None, got, exp).ratio() < QUESTION_SIMILAR:
        return False
    if bee.endswith("bee") and len(bee) >= 7:
        bee = bee[:-3]                # every label ends "Bee"; the name is before it
    span = len(bee)
    best = max(difflib.SequenceMatcher(None, got[i:i + span], bee).ratio()
               for i in range(max(1, len(got) - span + 1)))
    return best >= NAME_SIMILAR


def dialog_question(frame, ocr) -> str:
    import re
    norm = lambda t: re.sub(r"[^a-z0-9 ]", "", " ".join(str(t or "").lower().split())).strip()  # noqa: E731
    whole = norm(ocr(frame, DIALOG_TITLE))
    # THE AUTO-JELLY NOTICE IS THE BOX'S SECOND LINE, NOT THE QUESTION
    # (DIALOG_TITLE_TOP): the first line read alone -- and the notice kept on
    # the end, so a Yes held to an exact question (question_matches refuses
    # "auto") is never given while the game would roll on by itself. The owner
    # chose one roll at a time (2026-10-09, "A"): Auto-Jelly off in Settings.
    # "jelly" alone: a Transform question never says it, and the live OCR
    # gave the notice as 'huiejelly son' (2026-10-09 12:30)
    # BUT "USE JELLY BEANS?" SAYS "jelly" TOO and is a plain question: it was
    # cut to its garbled top line + " autojelly on" and refused 7 times on
    # 2026-10-13 (09:33-13:29, 'lo loll daanced autojelly on'), Auto-Jelly off
    # or on. A notice never names the beans.
    if ("auto" in whole or "jelly" in whole) and "jellybean" not in whole.replace(" ", ""):
        top = norm(ocr(frame, DIALOG_TITLE_TOP))
        if top:
            return top + " autojelly on"
    # A TWO-LINE QUESTION READ WHOLE CAN COME BACK EMPTY while each line reads
    # clean: MEASURED 2026-10-13 (audit-2026-10-13.md #4) -- 46 Royal Jelly rolls
    # refused in 20 h and 4 Sticker Stack visits wasted, the box '' and the top
    # line 'Add "Purple Point... Sticker" to the' (var/places/sticker_stack-
    # r*-asked-no-054012.jpg). Then the lines are read apart, the notice test
    # kept on the bottom one, so an Auto-Jelly roll still never gets a Yes.
    if not whole:
        top = norm(ocr(frame, DIALOG_TITLE_TOP))
        bottom = norm(ocr(frame, DIALOG_TITLE_BOTTOM))
        if top and ("auto" in bottom or ("jelly" in bottom
                                          and "jellybean" not in bottom.replace(" ", ""))):
            return top + " autojelly on"
        return " ".join(t for t in (top, bottom) if t)
    return whole


def answer(vin, frame, yes: bool) -> bool:
    """Click Yes or No -- only on a frame where that button shows its colour."""
    box = DIALOG_YES if yes else DIALOG_NO
    if _share(frame, box, "green" if yes else "red") < 0.5:
        return False
    x0, y0, x1, y1 = box
    return vin.click((x0 + x1) // 2, (y0 + y1) // 2) is not False
# THE COUNT IS SEEN TO CHANGE, NOT READ. MEASURED on the page above: the count
# is white with a black outline over the icon's light box, and tesseract reads
# nothing there; but "x18" becoming "x17" moves its pixels, and a click that
# did nothing moves none. Mean absolute change over the count's box, 0..255.
COUNT_CHANGED = 6.0


def row_tops(page) -> list:
    """Every item row's first marker on a page of the list (crop coords) --
    the title from 6 px above it (the first row's marker sits 5 px lower)."""
    tops, last = [], None
    for mark in inv.item_rows(page):
        if last is None or mark - last > 30:
            tops.append(int(mark))
        last = mark
    return tops


def _text_at(page, top: int, box, ocr) -> str:
    x0, dy0, x1, dy1 = box
    return str(ocr(page, (x0, top + dy0, x1, top + dy1)) or "")


def _title(page, top: int, ocr) -> str:
    import re
    return re.sub(r"[^a-z0-9 ]", "", " ".join(
        _text_at(page, top, ROW_TITLE, ocr).lower().split())).strip()


def _count_patch(page, top: int):
    x0, dy0, x1, dy1 = ROW_COUNT
    if page is None or top + dy1 > page.shape[0]:
        return None
    return page[top + dy0:top + dy1, x0:x1, :3].astype("int16")


# THE COUNT, READ FROM ITS OWN PIXELS (a third reading beside the model's
# two). MEASURED on the page above: the count's white fill reads V >= 245,
# S <= 12 against the icon box's ~221, and tesseract (vision/beemenu's binary
# and language, digits and "x/" only) reads the fill alone right on 8 of 9
# rows -- "x1" came back "x", nothing -- and never wrong.
COUNT_FILL_V, COUNT_FILL_S = 245, 12
COUNT_BOX = (36, 50, 98, 78)            # x0, dy0, x1, dy1 from the row's first marker


# THE THIN 1. MEASURED 2026-10-03 on the measured page and live: the reader
# loses a 1 beside the x ("x1" read "x", "x17" read "7", 01:06) and never adds
# a digit, and no one setting reads every row (fill threshold, scale and a
# 2 px widening each miss a different one). So four settings are read and the
# largest kept -- 9 of 9 rows right on the page -- and "x17" -> "x16" reads
# 17 -> 16 however the 1 fares.
COUNT_READS = ((0, 3, 245), (0, 4, 240), (2, 3, 240), (2, 4, 245))   # (widen px, scale, V)


def _one_count(crop, widen: int, scale: int, fill_v: int, run=None) -> int | None:
    import re
    import subprocess
    import cv2
    import numpy as np
    from ..vision.beemenu import LANGUAGE, TESSERACT
    hsv = cv2.cvtColor(np.ascontiguousarray(crop), cv2.COLOR_BGR2HSV)
    fill = ((hsv[..., 2] >= fill_v) & (hsv[..., 1] <= COUNT_FILL_S)).astype(np.uint8) * 255
    if not fill.any():
        return None
    if widen:
        fill = cv2.dilate(fill, np.ones((1, widen), np.uint8))
    img = cv2.resize(255 - fill, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    img = cv2.copyMakeBorder(img, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255)
    ok, png = cv2.imencode(".png", img)
    if not ok:
        return None
    try:
        out = (run or subprocess.run)(
            [TESSERACT, "stdin", "stdout", "-l", LANGUAGE, "--psm", "7",
             "-c", "tessedit_char_whitelist=xX0123456789/"],
            input=png.tobytes(), capture_output=True, timeout=10.0)
    except (OSError, subprocess.SubprocessError):
        return None
    raw = out.stdout
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    found = re.search(r"(\d+)", text)
    if not found:
        return None
    digits = found.group(1)
    # A CAP'S SLASH LOST: "27/100" read "27100". MEASURED 2026-10-21 (run-1167
    # and runs 998-1008): Jelly Beans "the count read 27100 -> 26", 73100 and
    # 72100 before. No "/" was read, so 1-3 digits then "100" is a count over
    # the 100 cap. A read "x" means an uncapped count ("x1100" is 1100).
    # ponytail: a true uncapped "x1100" whose "x" is also lost reads 1; only
    # the 100 cap has been seen losing its slash.
    lost = re.fullmatch(r"(\d{1,3})100", digits)
    if lost and "/" not in text and "x" not in text.lower():
        return int(lost.group(1))
    return int(digits)


def row_count(page, top: int, run=None) -> int | None:
    """The count drawn on a row's icon ("x18"; "21/100" gives 21), or None:
    the largest of COUNT_READS' readings, since a reading only ever loses
    digits."""
    x0, dy0, x1, dy1 = COUNT_BOX
    if page is None or top + dy1 > page.shape[0]:
        return None
    crop = page[top + dy0:top + dy1, x0:x1, :3]
    reads = [_one_count(crop, w, sc, v, run) for w, sc, v in COUNT_READS]
    reads = [n for n in reads if n is not None]
    return max(reads) if reads else None


def geometric_counts(page, labels: dict, ocr=None, run=None) -> dict:
    """{key: count} for every row of `page` whose title is one of `labels`
    ({key: label}), its count read from the icon's own pixels."""
    if ocr is None:
        from . import shoplook
        ocr = shoplook._ocr_line
    import re
    by_title = {re.sub(r"[^a-z0-9 ]", "", " ".join(str(v).lower().split())).strip(): k
                for k, v in (labels or {}).items()}
    out = {}
    for top in row_tops(page):
        if top + ROW_TITLE[1] < 0:
            continue
        key = by_title.get(_title(page, top, ocr))
        if key is None:
            continue
        n = row_count(page, top, run)
        if n is not None:
            out[key] = n
    return out


def _title_of(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9 ]", "", " ".join(str(name).lower().split())).strip()


def _edits(a: str, b: str) -> int:
    """Levenshtein distance between two short titles."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ONE LETTER MISREAD, AND ONLY ONE ROW LIKE IT. MEASURED 2026-10-03 06:39:
# tesseract read the Magic Bean's row "madic bean" (page 02 of that use), so
# the exact title found nothing and the bean was never planted. A row one
# edit from the name is taken when it is the only such row and no other on
# the page is within two -- "jelly beans" is nine from "magic bean", and a
# Whirligig is never a Honeysuckle by one letter.
NEAR_TITLE_MIN = 6


def find_row(page, name: str, ocr) -> int | None:
    """The top of the whole row titled `name` on a page -- exactly, else
    one letter off when no other row is near it (see above) -- or None."""
    want = _title_of(name)
    titles = []
    for top in row_tops(page):
        if top + ROW_COUNT[3] > page.shape[0] or top + ROW_TITLE[1] < 0:
            continue                          # a row cut by the page's edge
        title = _title(page, top, ocr)
        if title == want:
            return top
        titles.append((top, title))
    if len(want) < NEAR_TITLE_MIN:
        return None
    near = [(top, _edits(title, want)) for top, title in titles]
    ones = [top for top, d in near if d == 1]
    if len(ones) == 1 and sum(1 for _top, d in near if d <= 2) == 1:
        return ones[0]
    return None


@dataclass
class ItemUse:
    ok: bool = False
    reason: str = ""
    before: int | None = None
    after: int | None = None
    menu: InventoryRead | None = None

    def describe(self) -> str:
        return f"used one: {self.reason}" if self.ok else f"not used: {self.reason}"


def use_item(vin, frames, name: str, *, ocr=None, sleep=time.sleep, on_note=None,
             keep_dir: Path = KEEP_DIR, clock=time.time) -> ItemUse:
    """Open the inventory, find `name`'s row by its title, click its icon
    once, see its count fall, and shut the menu (the read's own rules 1-7).
    `ocr(image, box) -> str` reads one line (act/shoplook's tesseract)."""
    from . import shoplook
    read_line = ocr or shoplook._ocr_line
    note = on_note or (lambda text: None)
    out = ItemUse()

    def ask(image, question=None):
        # THE PAGE'S WORDS FOR THE READ'S OWN CHECK (`looks_like_inventory`):
        # the row titles, read exactly, one a line
        return "\n".join(_title(image, top, read_line) + ": 1"
                          for top in row_tops(image))

    def on_page(page) -> bool:
        x, y, _w, _h = inv.INVENTORY_BOX
        top = find_row(page, name, read_line)
        if top is None:
            return False
        out.before = row_count(page, top)
        note(f"inventory: {name} at row y {top} ({out.before} held) — clicking its icon")
        if vin.click(x + ROW_ICON[0], y + top + ROW_ICON[1]) is False:
            out.reason = "the click was held back by the owner's Pause or Take Over"
            return True
        sleep(USE_SETTLE_S)
        frame = frames()
        if not dialog_open(frame):
            out.reason = "the click on its icon opened no question"
            return True
        asked = dialog_question(frame, read_line)
        want_q = "use " + _title_of(name)
        # A PLANTER ASKS "Place ...?" (MEASURED 2026-10-10 00:13: 'place blue clay
        # planter' answered No as not 'use blue clay planter'): its own verb, the
        # same exact name after it
        if "planter" in want_q and asked == "place " + _title_of(name):
            want_q = asked
        if asked != want_q:
            answer(vin, frame, yes=False)
            sleep(USE_SETTLE_S)
            out.reason = f"the question read {asked!r}, not {want_q!r} -- answered No"
            return True
        if not answer(vin, frame, yes=True):
            answer(vin, frame, yes=False)
            out.reason = "the Yes button was not where it was measured -- answered No"
            return True
        sleep(USE_SETTLE_S)
        if dialog_open(frames()):
            answer(vin, frames(), yes=False)
            out.reason = "the question was still open after Yes -- answered No"
            return True
        again = _crop_of(frames, note)
        out.after = row_count(again, top) if again is not None else None
        # A FALL IS THE USE. MEASURED 2026-10-03 00:43: after Yes on "Use
        # Glitter?" the count read 18 -> 7 -- "x17" with its thin 1 lost, as
        # "x1" read "x" on the page measured above. The reader drops digits
        # and never adds them, so after the question asked and answered, a
        # count that fell at all is the use; one that did not move is not.
        # A PLANTER'S "Place ...?" ANSWERED YES AND CLOSED IS THE PLACING.
        # MEASURED 2026-10-11 00:25: the last Blue Clay went into Rose Field,
        # its row vanished and the next item (also x1) slid into its place --
        # read "1 -> 1", logged a failure, the planter left unrecorded in the field
        if asked.startswith("place "):
            out.ok, out.reason = True, (f"answered Yes to {asked!r} and the question "
                                        f"closed (a planter: its row may be gone)")
        elif out.before is not None and out.after is not None:
            if out.after < out.before:
                out.ok, out.reason = True, (f"answered Yes to {asked!r}; the count read "
                                            f"{out.before} -> {out.after}")
            else:
                out.reason = (f"answered Yes to {asked!r} but the count read "
                              f"{out.before} -> {out.after}")
        else:
            out.ok, out.reason = True, (f"answered Yes to {asked!r} and the question "
                                        f"closed; the count was not read")
        return True
    result = InventoryRead()
    _read_menu(vin, frames, ask, {}, sleep, note, result, keep_dir, clock, None,
               INVENTORY, lambda pages, ask_, note_, result_: None, on_page=on_page)
    out.menu = result
    if not out.ok and not out.reason:
        out.reason = result.reason or f"no row titled {name!r} in the list"
    return out


# HATCHING AN EGG ON A HIVE CELL. THE WIKI (Tutorial, File:Moveegg3.png, read
# 2026-10-03): open the egg menu, then "click and drag an egg onto one of the
# honeycomb cells"; while it is held the cells it can go on show green, and
# placing it hatches it "as long as you confirm". An egg let go over a bee
# REPLACES that bee (wiki Egg, since 2019-09-28). So the row is found by its
# own title, the egg is held over `cell` and let go only when `lit(frame)` --
# the frame under the held egg -- passes, else carried back over the list
# (platform/input drag's `check`), and the question the drop asks is answered
# Yes only where `accept(question)` says so, No otherwise. Nothing else is
# clicked, and a run that does not know the question's words yet passes an
# `accept` that says no to all of them.
DROP_WAIT_S = 1.5
DROP_LOOK_S = 0.1


@dataclass
class Hatch:
    ok: bool = False
    dropped: bool = False
    reason: str = ""
    question: str = ""
    before: int | None = None
    after: int | None = None
    held: object = field(default=None, repr=False)   # the frame under the held egg
    asked: object = field(default=None, repr=False)  # the frame with its question
    menu: InventoryRead | None = None

    def describe(self) -> str:
        return f"hatched: {self.reason}" if self.ok else f"not hatched: {self.reason}"


def hatch_egg(vin, frames, name: str, cell: tuple, *, lit, accept, ocr=None,
              sleep=time.sleep, on_note=None, keep_dir: Path = KEEP_DIR,
              clock=time.time, on_drop=None) -> Hatch:
    """Open the inventory, find `name`'s row by its title, drag its icon to
    `cell` (x, y on the screen) and drop it there only when `lit` passes,
    then answer the question it asks (see above); the menu shut after.
    `on_drop(frame) -> (ok, reason)` answers whatever the drop opened in
    place of the Yes/No question (act/feed's Feed box); `accept` is then
    not asked."""
    from . import shoplook
    read_line = ocr or shoplook._ocr_line
    note = on_note or (lambda text: None)
    out = Hatch()

    def ask(image, question=None):
        return "\n".join(_title(image, top, read_line) + ": 1"
                          for top in row_tops(image))

    def on_page(page) -> bool:
        x, y, _w, _h = inv.INVENTORY_BOX
        top = find_row(page, name, read_line)
        if top is None:
            return False
        out.before = row_count(page, top)
        sx, sy = x + ROW_ICON[0], y + top + ROW_ICON[1]

        def check() -> bool:
            # THE GAME TAKES A MOMENT TO LIGHT THE CELL UNDER THE POINTER:
            # MEASURED 2026-10-03, the empty cell read green 0.15 s after the
            # pointer reached it (08:27) and the hover's white on the next try
            # (08:46). So the check looks again until DROP_WAIT_S has passed.
            deadline = clock() + DROP_WAIT_S
            while True:
                frame = frames()
                out.held = frame
                if lit(frame):
                    return True
                if clock() >= deadline:
                    return False
                sleep(DROP_LOOK_S)
        note(f"inventory: {name} at row y {top} ({out.before} held) — dragging it "
             f"to ({int(cell[0])}, {int(cell[1])})")
        if vin.drag(sx, sy, float(cell[0]), float(cell[1]), check=check) is False:
            out.reason = ("the cell did not show it could take the egg, so it was "
                          "carried back and let go over the list (or the owner held "
                          "the drag back)")
            return True
        out.dropped = True
        sleep(USE_SETTLE_S)
        frame = frames()
        out.asked = frame
        if on_drop is not None:
            out.ok, out.reason = on_drop(frame)
            if out.ok:
                again = _crop_of(frames, note)
                out.after = row_count(again, top) if again is not None else None
            return True
        if not dialog_open(frame):
            out.reason = "the drop opened no question"
            return True
        out.question = dialog_question(frame, read_line)
        if not accept(out.question):
            answer(vin, frame, yes=False)
            sleep(USE_SETTLE_S)
            out.reason = f"the question read {out.question!r} -- answered No"
            return True
        if not answer(vin, frame, yes=True):
            answer(vin, frame, yes=False)
            out.reason = "the Yes button was not where it was measured -- answered No"
            return True
        sleep(USE_SETTLE_S)
        if dialog_open(frames()):
            answer(vin, frames(), yes=False)
            out.reason = "the question was still open after Yes -- answered No"
            return True
        again = _crop_of(frames, note)
        out.after = row_count(again, top) if again is not None else None
        out.ok = True
        out.reason = (f"answered Yes to {out.question!r}"
                      + (f"; the count read {out.before} -> {out.after}"
                         if out.before is not None and out.after is not None else ""))
        return True
    result = InventoryRead()
    _read_menu(vin, frames, ask, {}, sleep, note, result, keep_dir, clock, None,
               INVENTORY, lambda pages, ask_, note_, result_: None, on_page=on_page)
    out.menu = result
    if not out.ok and not out.reason:
        out.reason = result.reason or f"no row titled {name!r} in the list"
    return out


def preview_egg(vin, frames, name: str, over: tuple, *, ocr=None, sleep=time.sleep,
                on_note=None, keep_dir: Path = KEEP_DIR, clock=time.time) -> Hatch:
    """The egg picked up and held over the hive at `over`, the frame there
    kept (`held`), and carried back and let go over the list: which cells
    light up for it, before any is dropped on. Nothing is asked, nothing
    hatches (platform/input drag_seek's `find` says no)."""
    from . import shoplook
    read_line = ocr or shoplook._ocr_line
    note = on_note or (lambda text: None)
    out = Hatch()

    def ask(image, question=None):
        return "\n".join(_title(image, top, read_line) + ": 1"
                          for top in row_tops(image))

    def on_page(page) -> bool:
        x, y, _w, _h = inv.INVENTORY_BOX
        top = find_row(page, name, read_line)
        if top is None:
            return False
        out.before = row_count(page, top)
        sx, sy = x + ROW_ICON[0], y + top + ROW_ICON[1]

        def look():
            out.held = frames()
            return None                       # never let go over the hive
        note(f"inventory: {name} at row y {top} ({out.before} held) — held over "
             f"({int(over[0])}, {int(over[1])}) for a picture, then carried back")
        landed = vin.drag_seek(sx, sy, float(over[0]), float(over[1]), look)
        out.dropped = landed is not None
        out.ok = out.held is not None and not out.dropped
        out.reason = ("held over the hive, pictured, and let go over the list"
                      if out.ok else "no picture with the egg held" if not out.dropped
                      else "it was let go somewhere -- it should not have been")
        return True
    result = InventoryRead()
    _read_menu(vin, frames, ask, {}, sleep, note, result, keep_dir, clock, None,
               INVENTORY, lambda pages, ask_, note_, result_: None, on_page=on_page)
    out.menu = result
    if not out.ok and not out.reason:
        out.reason = result.reason or f"no row titled {name!r} in the list"
    return out
