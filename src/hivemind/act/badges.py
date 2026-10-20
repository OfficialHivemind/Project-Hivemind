"""The badge menu: opened, looked at, kept, and closed -- claiming comes next.

THE OWNER, 2026-09-28: "make it able to claim badges". A badge gives tickets
and a permanent boost once claimed (BSS wiki, Badges: "Obtaining a non-event
badge awards Tickets and a permanent boost"; 15 of them open the Badge
Bearer's Guild, and with it the Mega Memory Match), and it is claimed in the
badge menu.

NOTHING OF THAT MENU HAS BEEN SEEN ON THIS MACHINE, so this is the LOOK that
comes first, under act/quests' rules (see that module for why each exists):
no keys; one click on the measured HUD button -- the fourth, the rosette
(vision/questmenu.BUTTONS, confirmed from the owner's screenshots), never the
Robux shop beside it; nothing believed until the transcription reads like the
badge menu; the only way out is the button it came in by (Roblox's own Shop,
run-1005, by its own X: act/quests.close_roblox_overlay); a menu left open is
said to be. It keeps the frame and its text in var/badges/<stamp>/ and says
whether a "claim" is on the page. The claim itself -- clicking one exact
"Claim" read on the frame, and checking the reward feed's "earned the ...
badge" after -- is built against those frames, not before.

OFF UNTIL THE OWNER WATCHES THE FIRST ONE: `badges.look` (world/settings).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ..vision import questmenu
from . import quests

BUTTON = "badges"
# The badge tiers (the wiki's badge rims) and the words of the menu itself:
# two different ones make a page a badge page.
BADGE_WORDS = ("badge", "badges", "cadet", "hotshot", "ace", "master",
               "grandmaster", "pollen from", "collect")
BADGE_WORDS_MINIMUM = 2
CLAIM_WORDS = ("claim", "press to collect")
# A BADGE READY TO COLLECT: its progress bar all green, no red left. MEASURED
# 2026-10-07 04:02 (var/badges/20261007-040220/page-01.jpg): the Blue Flower
# Badge read "250,000,000 / 250,000,000 Complete! Press To Collect." -- green
# 72% of x 10-230 across its rows (the rest its white words), red 0 -- and
# every other bar red 41-61%. Pressing it collects the tier (x25 tickets).
BAR_X = (10, 297)                       # the whole bar, to its end under the ticket
BAR_GREEN_MIN, BAR_RED_MAX = 0.35, 0.004
BAR_ROWS_MIN = 25
KEEP_DIR = Path(__file__).resolve().parents[3] / "var" / "badges"
# THE WHOLE LIST, NOT ITS FIRST PAGE. MEASURED 2026-10-07 03:22 (var/badges/
# 20261007-032232): the first page holds Honey, Quest, Battle, Ability, Goo and
# Playtime; the field badges -- what the Guild's sprinklers count, 10 Hotshot
# for the Silver Soakers -- are below it (the owner, 2026-10-06: "claim
# achievement badges ... work towards super saturator"). The list fills x 0-310,
# y 170-970 of that frame, so the wheel is turned with the pointer at its
# middle -- a wheel over the world zooms the camera instead. A page that moved
# less than END_CHANGE from the one before is the list's end.
LIST_POINT = (150, 600)
# ...and each page below the first read off the list alone: MEASURED 2026-10-07
# 03:48, the whole screen's transcription of page 1 was the Cub Buddy's
# notification ("Buddy made some gifts! +1 Treat"), not the list
LIST_BOX = (0, 170, 320, 970)            # x0, y0, x1, y1
PAGE_NOTCHES = 5
PAGES_MOST = 8
END_CHANGE = 0.02
ALL_EVERY_S = 6 * 3600.0         # every page this often; the first page each run
ALL_STAMP = "all_pages.json"


@dataclass
class BadgeLook:
    ok: bool = False
    text: str = ""
    claimable: bool = False          # the page names a claim
    reason: str = ""
    menu_open: bool = False          # pessimistic, as act/quests
    changed: float = 0.0
    kept: str = ""
    pages: int = 1
    collected: int = 0               # bars pressed that were then no longer full

    def describe(self) -> str:
        if not self.ok:
            return f"did not look at the badges: {self.reason}"
        head = (f"collected {self.collected} complete badge(s)" if self.collected
                else "the badge menu shows a claim" if self.claimable
                else "the badge menu shows no claim on its first page" if self.pages == 1
                else f"the badge menu shows no claim on its {self.pages} pages")
        return head + (" — MENU STILL OPEN" if self.menu_open else "")


def looks_like_badges(text: str) -> bool:
    low = " ".join(str(text or "").lower().split())
    return sum(1 for w in BADGE_WORDS if w in low) >= BADGE_WORDS_MINIMUM


def wanted(settings) -> bool:
    """Off unless the owner has switched it on: nothing of this menu has been
    seen here yet (see the module's note)."""
    if settings is None:
        return False
    try:
        return bool(settings.bool("badges.look"))
    except Exception:
        return False


def look(vin, frames, transcribe, *, sleep=time.sleep, on_note=None,
         settings=None, keep_dir: Path = KEEP_DIR, stamp=None) -> BadgeLook:
    """Open the badge menu, read and keep its first page, close it."""
    note = on_note or (lambda text: None)
    result = BadgeLook()
    if not wanted(settings):
        result.reason = "badges.look is off in the settings"
        return result
    try:
        return _look(vin, frames, transcribe, sleep, note, result, keep_dir,
                     stamp or time.strftime("%Y%m%d-%H%M%S"))
    finally:
        quests._park(vin, note)


def _look(vin, frames, transcribe, sleep, note, result, keep_dir, stamp):
    x, y = questmenu.button_at(questmenu.BUTTONS.index(BUTTON))
    # THE ROSETTE IS LOOKED AT FIRST (act/quests.ready_to_click). MEASURED
    # run-1005 18:15:16: a Roblox "Shop now" toast lay over it and this click
    # opened Roblox's Robux Shop instead.
    before, why = quests.ready_to_click(vin, frames, BUTTON, sleep=sleep, note=note)
    if before is None:
        result.reason = why
        return result
    note(f"opening the badge menu: clicking ({x}, {y}), the rosette")
    try:
        sent = vin.click(x, y)
    except Exception as exc:
        result.reason = f"the click failed: {exc}"
        return result
    if sent is False:
        result.reason = ("the click was held back by the owner's Pause or Take "
                         "Over — nothing was clicked")
        return result
    sleep(quests.SETTLE_SECONDS)
    after = quests._grab(frames, note)
    result.changed = quests.changed_fraction(before, after)
    if result.changed < quests.CHANGED_TO_OPEN:
        result.reason = (f"nothing opened — only {result.changed:.1%} of the screen "
                         f"changed; no further clicking is done on a guess")
        return result
    result.menu_open = True
    try:
        # THE LIST ALONE, the first page too: MEASURED 04:15, the whole screen's
        # read of it was 'Buddy' (the Cub Buddy's name over the world)
        x0, y0, x1, y1 = LIST_BOX
        result.text = transcribe(after[y0:y1, x0:x1]) or ""
    except Exception as exc:
        note(f"could not transcribe the panel: {exc}")
    result.kept = _keep(keep_dir / stamp, after, result.text, note)
    if not looks_like_badges(result.text):
        shop = questmenu.roblox_overlay(after)
        result.reason = ((f"{quests.OVERLAY_NAMES[shop[0]]} opened, not the badge menu"
                          if shop else
                          f"something opened but it does not read like the badge "
                          f"menu (read {result.text[:80]!r})") + " — backing out")
        quests._close(vin, frames, before, result, sleep, note, x, y,
                      opened=after, what="badge menu")
        return result
    after = _collect(vin, frames, sleep, note, result, after, keep_dir / stamp, 0)
    if _all_due(keep_dir):
        # (the close is judged against the page it is on, not the first)
        kept, after = _the_rest(vin, frames, transcribe, sleep, note, result,
                                keep_dir / stamp, after)
        result.pages = 1 + kept
    low = result.text.lower()
    result.claimable = any(w in low for w in CLAIM_WORDS)
    result.ok = True
    note(result.describe())
    quests._close(vin, frames, before, result, sleep, note, x, y,
                  opened=after, what="badge menu", gone=_list_gone(after))
    return result


def _list_gone(opened):
    """The badge list's own sign for quests._close: its border down x 307
    (vision/questlist.side_panel). MEASURED 2026-10-13/14: two reads called
    the menu closed (attempts 947 05:29, 990 08:16) and the list was still on
    the next route's start frame 11-12 s later -- the Pine Tree walk out of
    990 then landed in Spider. No opinion when the open page showed no border."""
    from ..vision import questlist
    try:
        if questlist.side_panel(opened) != "badges":
            return None
    except Exception:
        return None
    return lambda now: questlist.side_panel(now) != "badges"


def full_bars(frame) -> list:
    """(x, y) of each progress bar in the list with no red left: a badge
    whose tier is complete and waits to be pressed."""
    import cv2
    import numpy as np
    if frame is None:
        return []
    x0, y0, x1, y1 = LIST_BOX
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[y0:y1, x0 + BAR_X[0]:x0 + BAR_X[1], :3]),
                       cv2.COLOR_BGR2HSV)
    h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = ((h >= 45) & (h <= 75) & (sat >= 120) & (v >= 150)).mean(axis=1)
    red = (((h <= 8) | (h >= 170)) & (sat >= 100) & (v >= 150)).mean(axis=1)
    out, start, gap = [], None, 0
    for i, ok in enumerate(list((green >= BAR_GREEN_MIN) & (red <= BAR_RED_MAX)) + [False] * 4):
        if ok:
            start, gap = (i if start is None else start), 0
        elif start is not None:
            gap += 1
            if gap > 3:
                end = i - gap
                if end - start + 1 >= BAR_ROWS_MIN:
                    out.append((x0 + (BAR_X[0] + BAR_X[1]) // 2, y0 + (start + end) // 2))
                start, gap = None, 0
    return out


def _collect(vin, frames, sleep, note, result, page, folder: Path, n: int):
    """Each full bar on `page` pressed once and looked at again: collected
    when its place no longer holds a full bar. The page after, for the
    paging's change test."""
    for k, (x, y) in enumerate(full_bars(page)):
        note(f"badge menu: a complete badge at ({x}, {y}) — pressing its bar to collect it")
        if vin.click(x, y) is False:
            break
        sleep(quests.SETTLE_SECONDS)
        after = quests._grab(frames, note)
        if after is None:
            break
        _keep(folder, after, "", note, name=f"collect-{n:02d}-{k}")
        if not any(abs(yy - y) <= BAR_ROWS_MIN for _xx, yy in full_bars(after)):
            result.collected += 1
            note(f"badge menu: collected the badge at ({x}, {y})")
        else:
            note(f"badge menu: the bar at ({x}, {y}) is still full after the press")
        page = after
    return page


def _all_due(keep_dir: Path, now=None) -> bool:
    try:
        import json
        at = float(json.loads((Path(keep_dir) / ALL_STAMP).read_text()).get("at") or 0.0)
    except (OSError, ValueError, AttributeError):
        at = 0.0
    return (now or time.time()) - at >= ALL_EVERY_S


def _the_rest(vin, frames, transcribe, sleep, note, result, folder: Path, first):
    """The pages below the first, each kept as page-NN; their words joined to
    `result.text`. Stops at the list's end, at a page that does not read like
    the badges, or when the wheel is held back. (How many it kept, the frame
    of the last.)"""
    last, kept, ended = first, 0, False
    x0, y0, x1, y1 = LIST_BOX
    # THE TOP FIRST: the menu opens where it was left -- MEASURED 04:39 (run-713),
    # at the list's end, so the first turn down moved nothing, read as the end,
    # and the Blue Flower Badge higher up waited six hours. (Positive is down:
    # the 04:02 paging went Goo -> Mountain Top.)
    vin.move_mouse(*LIST_POINT)
    vin.scroll(-PAGE_NOTCHES * PAGES_MOST)
    sleep(quests.SETTLE_SECONDS)
    top = quests._grab(frames, note)
    if top is not None and quests.changed_fraction(first[y0:y1, x0:x1],
                                                   top[y0:y1, x0:x1]) >= END_CHANGE:
        try:
            text = transcribe(top[y0:y1, x0:x1]) or ""
        except Exception as exc:
            note(f"could not transcribe the badge list's top: {exc}")
            text = ""
        if not looks_like_badges(text):
            # (not the list: stopped, and not stamped -- the next run tries again)
            note(f"the badge list's top does not read like the badges ({text[:60]!r}) — stopping")
            note(f"badge menu: 1 page(s) read, not to its end, kept in {folder}")
            return kept, last
        _keep(folder, top, text, note, name="page-top")
        result.text += "\n" + text
        top = _collect(vin, frames, sleep, note, result, top, folder, 0)
        last, kept = top, kept + 1
    for n in range(1, PAGES_MOST):
        # a wheel the owner's Pause holds back moves nothing: the list's "end"
        vin.move_mouse(*LIST_POINT)
        vin.scroll(PAGE_NOTCHES)
        sleep(quests.SETTLE_SECONDS)
        page = quests._grab(frames, note)
        if page is None:
            break
        # THE LIST'S OWN PART: MEASURED 04:02, the world beside it moved and
        # pages 4-7 were page 4 again
        if quests.changed_fraction(last[y0:y1, x0:x1], page[y0:y1, x0:x1]) < END_CHANGE:
            ended = True
            break
        try:
            text = transcribe(page[y0:y1, x0:x1]) or ""
        except Exception as exc:
            note(f"could not transcribe badge page {n}: {exc}")
            break
        if not looks_like_badges(text):
            note(f"badge page {n} does not read like the badges ({text[:60]!r}) — stopping")
            break
        _keep(folder, page, text, note, name=f"page-{n:02d}")
        result.text += "\n" + text
        page = _collect(vin, frames, sleep, note, result, page, folder, n)
        last, kept = page, kept + 1
    else:
        ended = True
    # ONLY A LIST READ TO ITS END waits ALL_EVERY_S for the next
    if ended:
        try:
            import json
            (folder.parent / ALL_STAMP).write_text(json.dumps({"at": time.time(), "pages": kept + 1}))
        except OSError:
            pass
    note(f"badge menu: {kept + 1} page(s) read{'' if ended else ', not to its end'}, kept in {folder}")
    return kept, last


def _keep(folder: Path, frame, text: str, note, name: str = "page") -> str:
    """The page and its words, for the claim to be built against."""
    try:
        import cv2
        folder.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(folder / f"{name}.jpg"), frame[:, :, :3],
                    [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        (folder / f"{name}.txt").write_text(text or "")
        return str(folder)
    except Exception as exc:
        note(f"could not keep the badge page: {exc}")
        return ""
