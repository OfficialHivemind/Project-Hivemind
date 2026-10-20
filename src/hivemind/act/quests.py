"""Opening the quest menu, reading it, and closing it again — safely.

THE OWNER ASKED FOR THIS DIRECTLY: read the quests the account holds on
joining. `vision/questmenu.py` already knows where the button is and
how to parse the panel; nothing ever drove it. This is the driving half.

WHY A WIKI TABLE IS NOT AN ANSWER. `data/knowledge/quests.yaml` says which
quests EXIST. It cannot say which ones this account holds, how far along each
one is, or what is left to do -- and those are the only facts a planner can act
on. The screen knows. Asking the screen is the whole point.

THE RULES THIS FILE OBEYS, AND WHY EACH ONE IS THERE

  1. NEVER PRESS A KEY TO OPEN OR CLOSE A MENU. The Roblox escape menu carries
     Log Out, Leave and Exit as ordinary activatable tiles, and Enter activates
     whatever is focused. This module presses no keys at all -- not Escape, not
     Enter, not E. It clicks one position that was measured from a real frame,
     and it clicks that same position to close.

  2. VERIFY BEFORE READING. A click that opened something is not a click that
     opened the QUEST menu. The panel has to say so in its own words before a
     single quest is believed, because this project has already built a map out
     of thirteen places that were never there.

  3. BACK OUT RATHER THAN IMPROVISE. If what opened is not the quest menu, the
     only recovery attempted is clicking the same button again. Hunting for a
     close button on an unknown panel means clicking unknown things, and one of
     the unknown things in this game is "Leave".

  4. SAY SO WHEN THE MENU IS STUCK OPEN. A farm loop that walks a pattern with
     a menu covering the screen is pressing keys at something it cannot see.
     `QuestRead.menu_open` is how the caller finds out, and it is deliberately
     pessimistic: it stays True unless the screen was observed to go back to
     what it looked like before.

WHAT IS NOT MEASURED YET. Whether the pointer actually lands where it is told
inside the nested compositor. Pointer lock there is an open problem
(docs/DESIGN.md), and `act/clicker.py` sidesteps it by clicking without moving.
So this verifies rather than assumes: if nothing changes on screen, it reports
that the button did not open anything instead of pretending it read an empty
quest list.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ..vision import questmenu


# How much of the screen must change for "something opened". MEASURED intent
# rather than value: a full-screen menu covers most of the frame, and normal
# gameplay between two frames a second apart changes far less than a tenth of
# it even while walking. Shares questmenu's constant so there is one number.
CHANGED_TO_OPEN = questmenu.MIN_PANEL_FRACTION

# A pixel has "changed" when it moves by more than this. JPEG noise and the
# game's own idle animation sit well below it.
PIXEL_DELTA = 28

# HOW MUCH NEARER THE WORLD THAN THE MENU a frame must be to count as closed.
# Two points of the frame: the menu, measured when it opened, changes a large
# share of it (the open test needs a tenth), so a closed menu sits far nearer
# `before` than `opened`, and a menu still open sits nearer `opened`.
CLOSED_MARGIN = 0.02

# How long to let the menu animate in before looking at it.
SETTLE_SECONDS = 1.2

# HOW MANY TIMES THE SAME OPEN MENU IS TRANSCRIBED. Two: the quest state
# cannot change between two frames a moment apart, so a difference between
# their transcriptions is a miss, and taking the better of the two loses
# nothing. One read decides the whole session's quest needs -- MEASURED
# 2026-09-23, a read that dropped one requirement's "Complete!" had the
# planner chasing 1,818,181 red pollen that was already collected.
READS = 2
# Long enough for the panel to be redrawn, short enough that nothing has
# happened. The menu is modal; the world behind it is not moving.
BETWEEN_READS = 0.4

# WHERE THE POINTER MUST BE LEFT, and this is a safety rule rather than tidiness.
#
# `Input.click()` with no coordinates clicks WHEREVER THE POINTER ALREADY IS --
# `platform/input.focus_game` says so in its own docstring: "it lands on
# whatever is under the cursor". `act/clicker.py` uses exactly that form to
# swing the collecting tool, several times a second, for the whole gathering
# stint.
#
# So leaving the pointer on the quest button after reading the menu would hand
# the tool clicker a button to press a few hundred times a trip, toggling the
# menu open and shut over the character's own screen. Every exit from this
# module puts the pointer back in the middle of the world, where a stray click
# is just another tool swing.
PARKED = (960, 540)


@dataclass
class QuestRead:
    """What happened, and what was read. Never a half-read quest."""
    ok: bool = False
    quests: list = field(default_factory=list)
    text: str = ""
    # EVERY TRANSCRIPTION OF THE SAME OPEN MENU, in order. `text` is the first
    # one, kept for callers that only want one. See READS.
    texts: list = field(default_factory=list)
    reason: str = ""
    menu_open: bool = False          # pessimistic: True unless seen to close
    changed: float = 0.0             # fraction of the screen that moved
    # The list was read to its end (act/questscroll ListPages.whole); None
    # when nothing below its first page was looked at.
    whole: bool | None = None

    def describe(self) -> str:
        if self.ok:
            head = f"read {len(self.quests)} quest(s) from the menu"
            return head if not self.menu_open else head + " — MENU STILL OPEN"
        return f"did not read the quests: {self.reason}"


def changed_fraction(before, after) -> float:
    """How much of the screen moved between two frames, in 0..1."""
    if before is None or after is None:
        return 0.0
    if getattr(before, "shape", None) != getattr(after, "shape", None):
        return 0.0
    a = before[:, :, :3].astype(np.int16)
    b = after[:, :, :3].astype(np.int16)
    moved = np.abs(a - b).max(axis=2) > PIXEL_DELTA
    return float(moved.mean())


def wanted(settings) -> bool:
    """Does the owner want quests read at all? `quests.enabled` in the GUI.

    Defaults to yes when the setting cannot be read, because the owner asked
    for this twice -- read the quests, then get quests working -- and a failure
    to read a config file is
    not a reason to stop doing what they asked for.
    """
    if settings is None:
        return True
    try:
        return bool(settings.bool("quests.enabled"))
    except Exception:
        return True


def read_quests(vin, frames, transcribe, *, sleep=time.sleep,
                on_note=None, settle: float = SETTLE_SECONDS,
                settings=None, reads: int = READS,
                transcribe_list=None) -> QuestRead:
    """Open the quest menu, read it, close it, and park the pointer.

    `frames()` returns the current frame. `transcribe(frame)` returns the text
    the vision model sees in it, or None. `vin.click(x, y)` is the only input
    this ever uses -- and, with `quests.scroll` on and `transcribe_list` (a
    picture of part of the list -> its text) given, the wheel over the list
    (act/questscroll) -- and the pointer is always left at `PARKED` — see the
    note there for why that is not housekeeping.
    """
    note = on_note or (lambda text: None)
    result = QuestRead()
    if not wanted(settings):
        result.reason = "quests.enabled is off in the settings"
        return result
    try:
        return _read(vin, frames, transcribe, sleep, note, settle, result,
                     reads=reads, settings=settings,
                     transcribe_list=transcribe_list)
    finally:
        _park(vin, note)


def _park(vin, note) -> None:
    """Put the pointer back in the middle of the world. See PARKED."""
    try:
        vin.move_mouse(*PARKED)
    except Exception as exc:
        note(f"could not park the pointer: {exc}")


def _read(vin, frames, transcribe, sleep, note, settle,
          result: QuestRead, reads: int = READS, settings=None,
          transcribe_list=None) -> QuestRead:

    spot = questmenu.quest_button()
    if spot is None:
        result.reason = ("which button opens the quests is not confirmed, and "
                         "clicking an unconfirmed one is how a bot finds the "
                         "Leave button")
        return result
    x, y = spot

    before, why = ready_to_click(vin, frames, "quests", sleep=sleep, note=note)
    if before is None:
        result.reason = why
        return result

    note(f"opening the quest menu: clicking ({x}, {y})")
    try:
        sent = vin.click(x, y)
    except Exception as exc:
        result.reason = f"the click failed: {exc}"
        return result
    if sent is False:
        # HELD BACK BY THE OWNER'S PAUSE OR TAKE OVER (brain/controls
        # STALE_AFTER_A_WAIT): nothing was clicked, so nothing opened.
        result.reason = ("the click was held back by the owner's Pause or "
                         "Take Over — nothing was clicked")
        return result
    sleep(settle)

    after = _grab(frames, note)
    result.changed = changed_fraction(before, after)
    if result.changed < CHANGED_TO_OPEN:
        # Nothing opened. Do NOT click again looking for it, and do not press
        # anything: the most likely cause is that the pointer did not land
        # where it was told, and repeating a blind click is how that becomes
        # a click on something else.
        result.reason = (f"nothing opened — only {result.changed:.1%} of the "
                         f"screen changed. The button may not have been hit; "
                         f"no further clicking is done on a guess")
        return result

    result.menu_open = True
    # READ THE SAME OPEN MENU MORE THAN ONCE.
    #
    # The quest state cannot change between two frames taken a moment apart,
    # so any difference between two transcriptions of them is a
    # TRANSCRIPTION MISS, and taking the better of the two loses nothing.
    #
    # MEASURED 2026-09-23: one read of this account's menu wrote down
    # "Collect 3,000,000 White Pollen" with no verdict, while an earlier read
    # of the same quest had "Collect 3,000,000 White Pollen. Complete!". A
    # single read decides the whole session's quest needs, and a requirement
    # whose "Complete!" is missed reads as entirely outstanding -- which
    # pulls the planner toward fields for pollen it does not need. See
    # `brain/questneeds.load`, which merges the readings by taking the
    # furthest progress for each requirement.
    for attempt in range(1, max(1, int(reads)) + 1):
        frame = after if attempt == 1 else _grab(frames, note)
        if frame is None:
            continue
        try:
            one = transcribe(frame) or ""
        except Exception as exc:
            note(f"could not transcribe the panel: {exc}")
            continue
        if one:
            result.texts.append(one)
        if attempt < max(1, int(reads)):
            sleep(BETWEEN_READS)
    text = result.texts[0] if result.texts else ""
    result.text = text

    if not questmenu.looks_like_quests(text):
        result.reason = (f"something opened but it does not say it is the "
                         f"quest menu (read {text[:80]!r}) — backing out "
                         f"rather than reading it as quests")
        _close(vin, frames, before, result, sleep, note, x, y, opened=after)
        return result

    result.quests = questmenu.parse(text)
    result.ok = True
    note(f"quest menu says: {len(result.quests)} quest(s)")
    if not result.quests:
        _keep_unparsed(after, result.texts, note)
    # THE REST OF THE LIST, below what the panel shows (act/questscroll). Only
    # on a page that read as quests, and closed against the menu as it was
    # last seen open: the wheel leaves it back at the top.
    below, last_open = None, after
    if result.quests and transcribe_list is not None:
        from . import questscroll            # it imports this module
        if questscroll.wanted(settings):
            below = questscroll.read_below(vin, frames, sleep, note, after)
            note(below.describe())
            result.whole = below.whole
            last_open = below.last if below.last is not None else after
    _close(vin, frames, before, result, sleep, note, x, y, opened=last_open,
           gone=_list_gone(last_open))
    if below is not None and len(below.pages) > 1:
        _read_whole_list(result, below, transcribe_list, reads, note)
    return result


def _list_gone(opened):
    """The quest list's own sign for `_close`: its scrollbar's border
    (vision/questlist.has_scrollbar). MEASURED on the eight kept close
    failures of 2026-09-27 to 10-01 (var/quest_reads/close-*): the border on
    every open frame and on every frame after the last click -- where the
    menu was open -- and on none of the world before; on the track's rows it
    matches 99.9% of an open menu's and 0.4% of the world's. The one of
    02:52:14 cost a rejoin: 57% of the panel gone after the first click, under
    the 60% bar in a scene moving 27% by itself, and the second click opened
    it again. No opinion when the open menu showed no scrollbar."""
    from ..vision import questlist
    try:
        had = questlist.has_scrollbar(opened)
    except Exception:
        had = False
    if not had:
        return None
    return lambda now: not questlist.has_scrollbar(now)


def _read_whole_list(result: QuestRead, below, transcribe_list, reads, note) -> None:
    """The whole list, read from its pictures with the menu shut. It replaces
    the first page's reading only when it reads as quests and finds at least
    as many; both readings stay in `texts` for questneeds to merge."""
    from . import questscroll
    # ONCE, NOT READS TIMES: READS reads two FRAMES of the open menu, which can
    # differ; the pieces are the same pictures every time, and MEASURED on the
    # first live read (scroll-20260930-225820) the model read them identically
    # twice -- six model calls where three said it all.
    texts, canvas, pieces = questscroll.transcribe(below, transcribe_list, 1, note)
    kept = questscroll.keep(below, canvas, pieces, texts, note)
    # THE FIRST PAGE KEPT IS NOT THE WHOLE LIST, though every page was
    # pictured. MEASURED run-1059 18:44 (19 Oct): 9 pages pictured to the end,
    # 1 quest read where the read before had 13 -- and `whole` said True, so
    # nothing downstream (questneeds.keep_unlisted, carry_ready) knew.
    if not texts:
        result.whole = False
        return
    whole = questmenu.parse(texts[0])
    if not questmenu.looks_like_quests(texts[0]) or len(whole) < len(result.quests):
        note(f"quest list: the whole list read as {len(whole)} quest(s), not more "
             f"than the first page's {len(result.quests)} — keeping the first page's")
        result.whole = False
        return
    note(f"quest list: the whole list read — {len(whole)} quest(s), where the "
         f"first page showed {len(result.quests)}" + (f"; kept in {kept}" if kept else ""))
    result.texts = list(texts) + list(result.texts)
    result.text = texts[0]
    result.quests = whole


# WHERE A READ THAT FOUND NO QUESTS IS KEPT, so the next look at the problem
# starts from the screen and the words rather than from a count. MEASURED
# 2026-09-24: the start-of-session read at 00:29 found five quests, and the
# post-convert re-reads at 00:49 and 01:10 in the same session found zero,
# with the menu open and closing normally -- and neither the frame nor the
# transcript was kept, so there was nothing to say why. Capped at
# UNPARSED_KEEP files so a night of failures cannot fill the disk.
UNPARSED_DIR = __import__("pathlib").Path(__file__).resolve().parents[3] / "var" / "quest_reads"
UNPARSED_KEEP = 20


def _keep_unparsed(frame, texts, note) -> None:
    try:
        import cv2
        UNPARSED_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        if frame is not None:
            cv2.imwrite(str(UNPARSED_DIR / f"{stamp}.jpg"), frame[:, :, :3],
                        [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        (UNPARSED_DIR / f"{stamp}.txt").write_text(
            "\n\n----\n\n".join(str(t) for t in texts))
        kept = sorted(UNPARSED_DIR.iterdir())
        for old in kept[:-UNPARSED_KEEP * 2]:
            old.unlink()
        note(f"no quests parsed — the frame and transcript are in "
             f"var/quest_reads/{stamp}.*")
    except Exception:
        pass


def _keep_close_failure(what, before, opened, now, note) -> None:
    try:
        import cv2
        UNPARSED_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        for label, frame in (("before", before), ("open", opened), ("after", now)):
            if frame is not None:
                cv2.imwrite(str(UNPARSED_DIR / f"close-{stamp}-{label}.jpg"),
                            frame[:, :, :3], [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        note(f"the {what}'s frames before, open and after the clicks are in "
             f"var/quest_reads/close-{stamp}-*.jpg")
    except Exception:
        pass


# THE MENU'S OWN BOX. A busy scene -- the hive during a convert, bees and bubbles
# everywhere -- moves a third of the frame by itself, so the whole-frame test
# below cannot tell a closed menu from an open one: run-534 06:59:46 measured
# "34% from the world, 35% from the menu" after the click that (by the next
# one's figures) had closed it, clicked again, reopened it, and stopped for a
# rejoin. The menu itself is a static panel, and where it is is where the screen
# changed when it opened: the columns more than half of whose pixels changed,
# and within them the rows more than half of whose pixels did. MEASURED on the
# two kept close failures (var/quest_reads/close-065946-*, close-115254-*):
# inside that box the open menu against the world is 0.999 and 0.899 changed,
# and against the menu open again 0.303 and 0.306. So a box this changed from
# the open frame is a closed menu, whatever the world did.
PANEL_CLOSED_FROM_OPEN = 0.6
PANEL_MIN_SHARE = 0.02          # a box smaller than this of the frame is no panel


def _longest_run(indices):
    if indices.size == 0:
        return None
    runs = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
    run = max(runs, key=len)
    return int(run[0]), int(run[-1]) + 1


def _panel_box(before, opened):
    """(rows, columns) slices of the panel that appeared, or None."""
    if before is None or opened is None or getattr(before, "shape", None) != getattr(opened, "shape", None):
        return None
    moved = np.abs(before[:, :, :3].astype(np.int16)
                   - opened[:, :, :3].astype(np.int16)).max(axis=2) > PIXEL_DELTA
    cols = _longest_run(np.flatnonzero(moved.mean(axis=0) > 0.5))
    if cols is None:
        return None
    x0, x1 = cols
    rows = _longest_run(np.flatnonzero(moved[:, x0:x1].mean(axis=1) > 0.5))
    if rows is None:
        return None
    y0, y1 = rows
    if (x1 - x0) * (y1 - y0) < PANEL_MIN_SHARE * moved.size:
        return None
    return (slice(y0, y1), slice(x0, x1))


def _grab(frames, note):
    try:
        return frames()
    except Exception as exc:
        note(f"capture failed: {exc}")
        return None


OVERLAY_NAMES = {"shop": "Roblox's Robux Shop", "promo": "Roblox's \"Shop now\" promo toast"}


def close_roblox_overlay(vin, frames, *, sleep=time.sleep, note=lambda text: None,
                         frame=None) -> tuple[bool, str]:
    """Roblox's own overlays (vision/questmenu.roblox_overlay) closed by their
    own X, one click each, looked at again: (nothing of Roblox's is left, what
    was done -- "" when none showed). Never a key, never a second click on an
    X that did not close it. MEASURED run-1005 18:15: the Robux Shop, opened by
    a click meant for the rosette, stayed over every walk for five minutes."""
    said = []
    for _ in range(2):              # the shop, and a toast behind it
        found = questmenu.roblox_overlay(frame if frame is not None else _grab(frames, note))
        frame = None
        if found is None:
            return True, "; ".join(said)
        kind, (x, y) = found
        name = OVERLAY_NAMES.get(kind, kind)
        if said and said[-1].startswith(f"closed {name}"):
            break
        try:
            if vin.click(x, y) is False:
                said.append(f"{name} is open; the click on its X was held back")
                return False, "; ".join(said)
        except Exception as exc:
            said.append(f"{name} is open and its X could not be clicked ({exc})")
            return False, "; ".join(said)
        _park(vin, note)
        sleep(0.8)
        now = questmenu.roblox_overlay(_grab(frames, note))
        if now is not None and now[0] == kind:
            said.append(f"{name} is open and one click on its X at ({x}, {y}) did not close it")
            return False, "; ".join(said)
        said.append(f"closed {name} by its X at ({x}, {y})")
    return questmenu.roblox_overlay(_grab(frames, note)) is None, "; ".join(said)


# THE ROBLOX CHAT BOX LEFT OPEN (ROADMAP A12). Read by the stream gate's own
# test (stream/privacy.chat_may_be_open: the chat icon's blue unread badge is
# drawn only while the chat window is shut), on a frame with the HUD up --
# MEASURED 2026-10-26 on tests/fixtures/screens: without the HUD the test fires
# on the loading screens and the join-error modal (no badge on a dark pill),
# never on in_game, the hive, the field or the menus; 0 of 3,000 route frames
# of attempts 1100-1299 fired. NEVER SEEN OPEN: 0 of 358,353 saved frames
# (privacy's note), so "no badge" is all there is, and it is also what a chat
# the owner read and shut looks like until a new message comes. So the frame is
# kept (CHAT_DIR) for measuring the window itself, and the recovery is
# look-only: ONE Escape (it unfocuses a chat input; on the world it opens
# Roblox's menu, which privacy.menu_in_frame sees -- then one more Escape shuts
# it, as act/routes._leave_menu does), never Enter, which would send the line.
CHAT_ESCAPE_LIVE = False
CHAT_DIR = UNPARSED_DIR.parent / "stuckkeys"
CHAT_KEEP_MOST = 5            # frames a process keeps: one owner-read chat repeats every walk
_chat_kept = []


def chat_open(frame) -> bool:
    """The chat icon on Roblox's top bar has no unread badge, in the world."""
    if frame is None or tuple(frame.shape[:2]) != questmenu.FRAME_HW:
        return False
    from ..stream import privacy
    from ..vision import screenstate

    def rgb(box):
        x, y, w, h = box
        return frame[y:y + h, x:x + w, :3][..., ::-1]
    return bool(privacy.chat_may_be_open(rgb(privacy.TOPBAR_PILL), rgb(privacy.CHAT_BADGE))
                and screenstate.hud_present(frame))


def close_chat(vin, frames, *, sleep=time.sleep, note=lambda text: None, frame=None) -> str:
    """The chat box shut before a walk (see CHAT_ESCAPE_LIVE): what was seen
    and done, "" when the badge is there."""
    from ..stream import privacy
    frame = _grab(frames, note) if frame is None else frame
    if not chat_open(frame):
        return ""
    kept = ""
    if len(_chat_kept) < CHAT_KEEP_MOST:
        try:
            import cv2
            CHAT_DIR.mkdir(parents=True, exist_ok=True)
            path = CHAT_DIR / f"chat-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
            cv2.imwrite(str(path), frame[:, :, :3], [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            _chat_kept.append(path)
            kept = f", frame kept as var/stuckkeys/{path.name}"
        except Exception:
            pass
    seen = f"the chat icon has no unread badge: the chat box may be open{kept}"
    if not CHAT_ESCAPE_LIVE:
        return (f"{seen} -- chat would: press Escape once, and once more only if "
                f"Roblox's menu shows after it; never Enter (CHAT_ESCAPE_LIVE off)")
    try:
        if vin.tap("escape") is False:
            return f"{seen}; the Escape was held back"
        sleep(0.8)
        if privacy.menu_in_frame(_grab(frames, note)):
            vin.tap("escape")
            sleep(0.8)
            return f"{seen}; one Escape opened Roblox's menu instead -- shut it with a second"
    except Exception as exc:
        return f"{seen}; Escape could not be pressed ({exc})"
    return f"{seen}; pressed Escape once to leave it"


def ready_to_click(vin, frames, name: str, *, sleep=time.sleep, note=lambda text: None,
                   before=None):
    """(the frame to judge the click against, or None, and why not): Roblox's
    overlays closed first, then HUD button `name` looked at where it was
    measured (vision/questmenu.button_check). Nothing is clicked on the button
    unless it shows plainly."""
    before = _grab(frames, note) if before is None else before
    if before is None:
        return None, "no frame to compare against"
    if questmenu.roblox_overlay(before) is not None:
        clear, said = close_roblox_overlay(vin, frames, sleep=sleep, note=note, frame=before)
        note(said)
        if not clear:
            return None, said
        before = _grab(frames, note)
    ok, mine, other = questmenu.button_check(before, name)
    if not ok:
        return None, (f"the {name} button is not plainly where it was measured (match "
                      f"{mine:.2f}, best other button {other:.2f}) — nothing clicked")
    return before, ""


def _close(vin, frames, before, result, sleep, note,
           x: int, y: int, attempts: int = 2, opened=None,
           what: str = "quest menu", motion: float = 0.0, gone=None) -> None:
    """Click the same button until the screen looks like it did before.

    `result` is anything with a `menu_open` flag; `what` names the menu in
    the notes. act/inventory closes the item menu with this too (DESIGN 8ea),
    and passes `motion`: how much the world alone changed between two frames
    taken before the menu was opened. A screen no further from `before` than
    that (and CLOSED_MARGIN) is the world, whatever the menu measured.

    The same button, and only the same button. Whatever is on screen, the one
    thing known about this position is that it was safe to click a moment ago.

    `gone(frame)`, when given, is the menu's OWN sign: True that it is gone,
    False that it is still there, None for no opinion -- and it is believed
    over the pixel tests below, which a busy scene can fool either way.

    CLOSED MEANS NEARER THE WORLD THAN THE MENU, not "within a tenth of the
    frame from before". MEASURED 2026-09-23 23:52:50-23:53:03 (run-339): the
    20-minute re-read opened the menu, transcribed it twice -- about twenty
    seconds of model time -- and the close check then compared the screen
    with a frame from before all that, on a hive pad with bees flying round
    it. It called the menu still open, clicked again (which, if the first
    click HAD closed it, opens it), gave up, and the session stopped for a
    rejoin 40 minutes in, twenty minutes short of the Wealth Clock's first
    payout. World movement adds to both distances alike; the menu itself is
    static. So with the open frame to hand, the menu is closed when the
    screen is clearly closer to `before` than to `opened` -- and the old
    absolute test still counts as closed on its own.
    """
    now = None
    if opened is not None and questmenu.roblox_overlay(opened) is not None:
        # NOT THE MENU BUT ROBLOX'S: the button it came in by does not close it
        # (run-1005 18:15, two rosette clicks, "1% from the menu"). Its own X.
        clear, said = close_roblox_overlay(vin, frames, sleep=sleep, note=note, frame=opened)
        note(said)
        now = _grab(frames, note)
        if not clear or now is None:
            note(f"the {what} did not close — {said or 'no frame to check'}")
            _keep_close_failure(what, before, opened, now, note)
            return
        if changed_fraction(before, now) < CHANGED_TO_OPEN:
            result.menu_open = False
            return
        opened = now                # what is left is judged as below
    box = _panel_box(before, opened)
    for attempt in range(1, attempts + 1):
        try:
            vin.click(x, y)
        except Exception as exc:
            note(f"could not click to close: {exc}")
            return
        sleep(0.8)
        now = _grab(frames, note)
        # NO FRAME IS NOT A CLOSED MENU: changed_fraction(before, None) is
        # 0.0, which the test below read as "closed after 1 click". Look
        # again without clicking (a click on a closed menu opens it), and
        # with nothing to look at, leave it open -- rule 4 is pessimistic.
        for _ in range(2):
            if now is not None:
                break
            sleep(0.5)
            now = _grab(frames, note)
        if now is None:
            note(f"no frame to check the close against — calling the {what} "
                 f"still open")
            return
        from_before = changed_fraction(before, now)
        from_open = changed_fraction(opened, now) if opened is not None else 0.0
        panel_gone = (changed_fraction(opened[box], now[box])
                      if box is not None else 0.0)
        sign = None
        if gone is not None:
            try:
                sign = gone(now)
                if sign is False:
                    # ONE MORE LOOK BEFORE ANOTHER CLICK: a frame caught while
                    # the menu is still on its way out would have the next
                    # click open it again -- the very failure this sign ends.
                    sleep(0.8)
                    again = _grab(frames, note)
                    if again is not None and gone(again):
                        now, sign = again, True
            except Exception:
                sign = None
        if sign is True or sign is None and (from_before < CHANGED_TO_OPEN or (
                opened is not None
                and from_before + CLOSED_MARGIN < from_open) or (
                motion > 0 and from_before <= motion + CLOSED_MARGIN) or (
                panel_gone >= PANEL_CLOSED_FROM_OPEN)):
            result.menu_open = False
            note(f"{what} closed after {attempt} click(s) "
                 f"({from_before:.0%} from the world, {from_open:.0%} from the menu"
                 + (f", {panel_gone:.0%} of its panel gone" if box is not None else "")
                 + ("; its own sign says it is gone" if sign is True else "") + ")")
            return
        note(f"the {what} still looks open after click {attempt} "
             f"({from_before:.0%} from the world, {from_open:.0%} from the menu"
             + (f", {panel_gone:.0%} of its panel gone" if box is not None else "")
             + ("; its own sign says it is still there" if sign is False else "") + ")")
    note(f"the {what} did not close — saying so rather than pressing keys "
         f"at a screen that is covered")
    # THE THREE FRAMES THE VERDICT WAS DRAWN FROM ARE KEPT. MEASURED
    # 2026-09-27 08:35 (attempt 489): "38% from the world, 40% from the menu"
    # after the first click and "49% ... 31%" after the second -- which looks
    # like a first click that closed it and a second that reopened it -- and
    # the run stopped for a rejoin with no frame to say which.
    _keep_close_failure(what, before, opened, now, note)


# THE PANELS A WALK OUT MAY FIND OPEN, and the HUD button that is each one's
# own way out (vision/questmenu.BUTTONS). Never the Robux shop's.
SIDE_PANEL_BUTTONS = ("quests", "badges")


def close_side_panel(vin, frames, *, sleep=time.sleep, note=lambda text: None) -> str:
    """A HUD side panel left open before a route sets off, closed by ONE click
    on its own button and looked at again; "" when none is open.

    MEASURED 2026-10-05..14 (vision/questlist.side_panel's note): with the badge
    list open on a route's start frame 6 of 15 runs landed elsewhere -- 4 of 6
    flights, 3 of them the Pine Tree flight in a row (attempt 1004 17:50-17:59)
    -- against 449 of 2,738 with none. One click only: a second on a panel the
    first did close opens it again (`_close`). A panel whose border is not one
    of SIDE_PANEL_BUTTONS' is said and left."""
    from ..vision import questlist
    frame = _grab(frames, note)
    if questmenu.roblox_overlay(frame) is not None:
        # MEASURED run-1005: all 10 route starts 18:15-18:20 set off under the
        # Robux Shop; 3 walk misses and a stop followed.
        clear, said = close_roblox_overlay(vin, frames, sleep=sleep, note=note, frame=frame)
        if not clear:
            return said + " — the route sets off with it open"
        frame = _grab(frames, note)
        which = questlist.side_panel(frame)
        return said if which is None else said + "; " + close_side_panel(
            vin, frames, sleep=sleep, note=note)
    which = questlist.side_panel(frame)
    if which is None:
        return ""
    if which not in SIDE_PANEL_BUTTONS:
        return ("a side panel is open over the world (its border is not the quest "
                "or badge list's) — not clicked, the route sets off anyway")
    x, y = questmenu.button_at(questmenu.BUTTONS.index(which), frame)
    try:
        vin.click(x, y)
    except Exception as exc:
        return f"the {which} list is open and could not be clicked shut ({exc})"
    _park(vin, note)
    sleep(0.8)
    if questlist.side_panel(_grab(frames, note)) == which:
        return (f"the {which} list was left open and one click on its button did "
                f"not close it — the route sets off with it open")
    return f"the {which} list was left open over the world — closed it with its own button"
