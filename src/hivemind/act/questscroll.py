"""Reading the rest of the quest list: the wheel a notch at a time, each move checked.

THE OWNER'S STANDING ASK: "do his quests". The panel shows 36-43% of his list
(vision/questlist, MEASURED on the kept open menus 2026-09-27 to 30), so the
quests below it -- and the last steps of the one it cuts, as the Science Bear's
"Craft 50 Ingredients with the Blender" and "Defeat 50 Ants" were -- were never
read. act/quests calls `read_below` with the menu open and read, and after the
close has `transcribe` read the whole list from the pictures.

THE RULES ARE act/inventory's, whose wheel reads the item list (see there for
the measurement behind each one):
  1. ONLY OVER THE LIST, AND ONLY WHILE THE LIST IS THERE. The pointer is parked
     over the list first (vision/inventory.SCROLL_AT: Natro's (30, 200) and its 8 px
     offset -- a wheel over the world zooms the camera), and before every turn
     the scrollbar must still be on screen (vision/questlist.has_scrollbar).
  2. ONE NOTCH BEFORE A BURST. The first turn is one notch, and the wheel goes
     on only if the list moved under it. A notch the world beside the list
     answered instead is the camera: it is taken back, one notch the other
     way, and nothing more is turned.
  3. EVERY MOVE MEASURED, NONE ASSUMED. A page is kept at the row its own
     measured move puts it (questlist.vertical_shift); a page that matches the
     one before it less than SHIFT_MATCH stops the scroll there, because its
     place in the list would be a guess. The end of the list is a turn that
     moves nothing.
  4. THE WHEEL TURNS NOW OR NOT AT ALL, as in act/inventory rule 6: not after
     the owner's Take Over, and only while an input would go out without
     waiting (GuardedInput.may_send).
  5. BACK TO THE TOP BEFORE THE CLOSE. The close compares the screen with the
     menu as it was last seen open (`last`), and the next read -- and the
     owner's own look at his quests -- starts from the top.

WHAT THE FIRST LIVE READS KEEP, for what a kept frame could not show: how far a
notch moves the list, and the pages, the stitched list, its pieces and what
was read from them (var/quest_reads/scroll-<stamp>/, the last KEEP_READS).

OFF UNTIL SEEN WORKING: `quests.scroll` (world/settings).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..vision import questlist as ql
from . import quests
from ..vision.inventory import SCROLL_AT

# Natro's pause for a scroll to finish (act/inventory AFTER_SCROLL).
AFTER_SCROLL = 0.5
# A page is three quarters of the panel past the last, so a quarter is
# pictured twice and the measure has room (questlist.vertical_shift).
PAGE_ADVANCE = 0.75
# A PAGE IS PLACED ON A MATCH THIS GOOD, below vision/questlist.SHIFT_MATCH (the
# first notch's test, list or camera, keeps that). MEASURED 2026-10-06 on the
# five kept reads (var/quest_reads/scroll-20261006-1535..1733): consecutive pages
# matched 0.939-0.986 at their true move, and nothing more than 10 px off it
# scored above 0.552 -- while 4 of the day's 24 reads stopped at 0.86-0.89 ("its
# place in the list would be a guess"), a bee or a sparkle over the band, and one
# of those dropped the Panda's finished quest (brain/questneeds carry_ready).
PAGE_MATCH = 0.8
# How far past the expected move a page is looked for.
SHIFT_SLACK = 24
MAX_NOTCHES = 60
TOP_BURST = 10
MAX_TOP_BURSTS = 10
# The world beside the list, for what a notch did to the camera.
BESIDE_X = 400
KEEP_DIR = Path(__file__).resolve().parents[3] / "var" / "quest_reads"
KEEP_READS = 5
HELD = "the owner paused or has the controls"
FITS = "the panel shows the whole list"


@dataclass
class ListPages:
    pages: list = field(default_factory=list)     # [(list image, its top row)]
    complete: bool = False                        # reached the list's end
    px_per_notch: float | None = None
    back_at_top: bool = False
    notches: int = 0
    last: object = None                           # the menu as last seen open
    reason: str = ""                              # why it stopped short
    probe: dict = field(default_factory=dict)

    @property
    def whole(self) -> bool:
        """Every row of the list was pictured: scrolled to its end, or the
        panel showed it all."""
        return self.complete or self.reason == FITS

    def describe(self) -> str:
        if len(self.pages) <= 1:
            return f"the rest of the quest list was not read: {self.reason}"
        head = (f"pictured the quest list in {len(self.pages)} pages, "
                f"{self.px_per_notch:.0f} px a notch, "
                + ("to its end" if self.complete else f"not to its end ({self.reason})"))
        return head + ("; back at the top" if self.back_at_top
                       else "; NOT back at the top")


def wanted(settings) -> bool:
    """`quests.scroll`, off unless the owner switched it on."""
    if settings is None:
        return False
    try:
        return bool(settings.bool("quests.scroll"))
    except Exception:
        return False


def _turn(vin, notches: int) -> bool:
    """Turn the wheel NOW, or not at all (rule 4)."""
    if getattr(vin, "stale", False):
        return False
    if not getattr(vin, "may_send", lambda: True)():
        return False
    vin.scroll(notches)
    return True


def _beside(frame):
    return frame[:, BESIDE_X:, :3]


def read_below(vin, frames, sleep, note, opened) -> ListPages:
    """Picture the list below the page `opened` shows, then go back to its top."""
    out = ListPages(last=opened)
    if opened is None:
        out.reason = "no frame of the open menu"
        return out
    out.pages.append((ql.list_crop(opened), 0))
    t = ql.thumb(opened)
    if t is None:
        out.reason = "no scrollbar on the list"
        return out
    if t.fits:
        out.reason = FITS
        return out
    if not t.at_top:
        out.reason = f"the list did not open at its top (thumb at {t.top})"
        return out
    try:
        vin.move_mouse(*SCROLL_AT)
    except Exception as exc:
        out.reason = f"could not park the pointer over the list: {exc}"
        return out
    sleep(AFTER_SCROLL)
    try:
        return _scroll(vin, frames, sleep, note, out)
    finally:
        _back_to_top(vin, frames, sleep, note, out)


def _scroll(vin, frames, sleep, note, out: ListPages) -> ListPages:
    # THE WORLD'S OWN MOTION BESIDE THE LIST, over the interval a notch is
    # judged across (act/inventory BASELINE_LOOKS: bees cross it by themselves).
    a = quests._grab(frames, note)
    sleep(AFTER_SCROLL)
    b = quests._grab(frames, note)
    if a is None or b is None or not ql.has_scrollbar(b):
        out.reason = "the list's scrollbar was not on screen before the first notch"
        return out
    motion = quests.changed_fraction(_beside(a), _beside(b))
    del a
    # ONE NOTCH (rule 2).
    if not _turn(vin, 1):
        out.reason = HELD
        return out
    out.notches += 1
    sleep(AFTER_SCROLL)
    c = quests._grab(frames, note)
    if c is None:
        out.reason = "no frame after the first notch"
        return out
    moved, score = ql.vertical_shift(ql.list_crop(b), ql.list_crop(c))
    world = quests.changed_fraction(_beside(b), _beside(c))
    out.probe = {"moved_px": moved, "match": round(score, 3),
                 "beside_changed": round(world, 3), "beside_by_itself": round(motion, 3)}
    note(f"quest list: one notch moved the list {moved} px (match {score:.2f}); the "
         f"world beside it changed {world:.0%}, against {motion:.0%} by itself")
    if score < ql.SHIFT_MATCH or moved < 1:
        if world > motion + quests.CLOSED_MARGIN:
            undone = _turn(vin, -1)
            out.notches -= 1 if undone else 0
            out.probe["undone"] = undone
            out.reason = ("the notch went to the camera, not the list — "
                          + ("taken back" if undone else f"NOT taken back ({HELD})"))
        else:
            out.reason = "the notch moved neither the list nor the world"
        out.last = c
        return out
    out.px_per_notch = float(moved)
    out.pages.append((ql.list_crop(c), moved))
    out.last = c
    top, last = moved, ql.list_crop(c)
    view = last.shape[0]
    step = max(1, int(PAGE_ADVANCE * view / out.px_per_notch))
    most = int(step * out.px_per_notch) + SHIFT_SLACK
    while out.notches < MAX_NOTCHES:
        if not ql.has_scrollbar(out.last):
            out.reason = "the list's scrollbar left the screen"
            return out
        if not _turn(vin, step):
            out.reason = HELD
            return out
        out.notches += step
        sleep(AFTER_SCROLL)
        now = quests._grab(frames, note)
        if now is None:
            out.reason = "no frame while scrolling"
            return out
        page = ql.list_crop(now)
        moved, score = ql.vertical_shift(last, page, most=most)
        if score < PAGE_MATCH:
            out.reason = (f"a page matched the one before it only {score:.2f} — "
                          f"its place in the list would be a guess")
            return out
        out.last = now
        if moved < 1:
            out.complete = True
            return out
        top += moved
        out.pages.append((page, top))
        last = page
    out.reason = f"{MAX_NOTCHES} notches turned"
    return out


def _back_to_top(vin, frames, sleep, note, out: ListPages) -> None:
    """Up in bursts until the thumb is at the top -- only when the list was
    seen to move under the wheel, and never again once a burst moves nothing:
    a wheel that is not reaching the list is zooming the camera."""
    if out.px_per_notch is None:
        out.back_at_top = out.notches <= 0
        return
    was = ql.thumb(out.last) if out.last is not None else None
    for _burst in range(MAX_TOP_BURSTS):
        if out.last is not None and not ql.has_scrollbar(out.last):
            note("quest list: the scrollbar is not on screen — not turning the wheel")
            return
        if not _turn(vin, -TOP_BURST):
            note(f"quest list: {HELD} — not scrolling back to the top")
            return
        sleep(AFTER_SCROLL)
        now = quests._grab(frames, note)
        if now is None:
            continue
        out.last = now
        t = ql.thumb(now)
        if t is not None and t.at_top:
            out.back_at_top = True
            return
        if t is None or (was is not None and t.top >= was.top):
            note("quest list: a burst up did not move the list — not turning the "
                 "wheel again")
            return
        was = t
    note("quest list: not back at the top after "
         f"{MAX_TOP_BURSTS * TOP_BURST} notches up")


def transcribe(out: ListPages, transcribe_list, reads: int, note) -> tuple[list, object, list]:
    """(one text of the whole list per read, the stitched list, its pieces);
    no texts when the list could not be cut safely or a piece was not read."""
    canvas = ql.stitch(out.pages)
    view = out.pages[0][0].shape[0]
    pieces = ql.chunks(canvas, most=view)
    if pieces is None:
        note("quest list: no safe row to cut the stitched list on — the first page is used")
        return [], canvas, []
    texts = []
    for _read in range(max(1, int(reads))):
        parts = []
        for piece in pieces:
            try:
                text = transcribe_list(piece) or ""
            except Exception as exc:
                note(f"quest list: could not transcribe a piece: {exc}")
                text = ""
            if not text.strip():
                parts = None
                break
            parts.append(text.strip())
        if parts:
            texts.append("\n".join(parts))
    return texts, canvas, pieces


def keep(out: ListPages, canvas, pieces, texts, note, folder: Path | None = None,
         clock=time.time) -> str:
    """The pages, the stitched list, its pieces and what was read, for the
    first live reads to be measured by; the last KEEP_READS are kept."""
    root = Path(folder) if folder is not None else KEEP_DIR
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
    where = root / f"scroll-{stamp}"
    try:
        import cv2
        where.mkdir(parents=True, exist_ok=True)
        for i, (image, top) in enumerate(out.pages):
            cv2.imwrite(str(where / f"page{i:02d}-top{top}.jpg"), image,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if canvas is not None:
            cv2.imwrite(str(where / "list.png"), canvas)
        for i, piece in enumerate(pieces or []):
            cv2.imwrite(str(where / f"piece{i:02d}.png"), piece)
        (where / "texts.txt").write_text("\n\n----\n\n".join(texts or []))
        (where / "read.json").write_text(json.dumps({
            "tops": [top for _img, top in out.pages], "px_per_notch": out.px_per_notch,
            "complete": out.complete, "back_at_top": out.back_at_top,
            "notches": out.notches, "reason": out.reason, "probe": out.probe}, indent=1))
        kept = sorted(p for p in root.glob("scroll-*") if p.is_dir())
        for old in kept[:-KEEP_READS]:
            for f in old.iterdir():
                f.unlink()
            old.rmdir()
        return str(where)
    except Exception as exc:
        note(f"quest list: could not keep the read: {exc}")
        return ""
