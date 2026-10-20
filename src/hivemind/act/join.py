"""Joining the owner's private server through the Roblox app's server browser.

This is the route the owner asked for -- open Bee Swarm's game page, scroll
down to Servers, and join the private server there -- and it is also the only
route that works. MEASURED: all four private-server
deeplink formats fail. Three return Join Error 524 ("You do not have permission
to join this experience") behind the Bee Swarm loading screen, and the
share-link form lands on the app home page. A PUBLIC join works by both URI
forms, which is what proves the account and the scheme are fine and isolates the
fault to the private-server code itself -- the share link's `code` is a
share-link id that Roblox resolves server-side, not the private server's
`linkCode`, and resolving it needs an authenticated API call we should not be
making. Navigating the UI the way a person does needs no credentials at all.

The path, and why each step is found the way it is:

  1. the Bee Swarm tile, first under "Continue" on the home page
  2. scroll until the "Servers" row is on screen -- found by template match, not
     by a scroll count, because the row's y depends on how much variable content
     ("People Also Join") sits above it
  3. click the View link on that row: right-aligned at a fixed x=1376
  4. wait for the drawer to load -- it shows "Loading" first
  5. scroll the drawer to the top, where "Your private servers" lives
  6. click the private server's Join button, found by COLOUR

Step 6 is the neat one. Every Join button in the drawer looks identical in shape
and text, but the one belonging to your own private server is drawn in Roblox
blue while the public-server ones are grey. MEASURED in HSV: the private button
is S=62, the public ones S=7. Masking on saturation finds exactly one button in
the whole panel, so there is nothing to disambiguate.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

import cv2

from ..vision import blobs, templates
from ..vision.color import Band
from ..vision import screen
from ..vision import screenstate as ss

# MEASURED on the loaded drawer: the private-server Join button sits at
# H=113 S=62 V=255, every public-server Join at H=115 S=7 V=226. Hue is
# identical; saturation is the whole signal, so the band is deliberately wide in
# H and V and tight only where it discriminates.
PRIMARY_BUTTON = Band("roblox-blue", (100, 60, 180), (130, 255, 255))

PANEL_X = 960            # the Servers drawer occupies the right half
VIEW_LINK_X = 1376       # right-aligned View link on the game page's rows
BSS_TILE = (193, 926)    # first tile under "Continue" -- the LAST game played
# THE "CONTINUE" ROW IS RECENT GAMES, NEWEST FIRST, so its first tile is Bee
# Swarm only while Bee Swarm was the last thing played. MEASURED 2026-09-22:
# the owner had another game open, and attempts 227-230 clicked that game's
# tile, opened its drawer, and found no private-server Join button in it. So
# the tile is now recognised by its thumbnail: `find_bss_tile`
# searches the row for data/templates/ui/bss_tile.png (cut from a home frame;
# it scores 1.00 on itself and 0.32 on the next-best tile) and the click goes
# where the thumbnail is.
#
# NOT FOUND MEANS NOTHING IS CLICKED. It used to mean "click the first tile as
# before", and MEASURED 2026-09-23 22:47:28 that click opened a Roblox AVATAR
# ITEM page with a blue "324" Robux buy button on it
# (var/join/224728-never_found_the_Servers_row.png) -- the thumbnails had not
# drawn yet at 7 s, and whatever sat at (193, 926) in that moment was not a
# game. Nothing was bought: the flow went looking for "Servers" and gave up.
# But a blind click on a screen that sells things is exactly what this
# project does not do, and the retry 90 s later found the tile at score 1.00.
# So the thumbnails are given time to draw, and if Bee Swarm's never appears
# the join fails loudly and the watchdog retries with a fresh app.
TILE_LOOKS = 10
TILE_LOOK_SECONDS = 1.5
# THE HOME GREW TALLER (MEASURED 2026-10-16 06:13, var/join/061304-...png):
# three rows of "Recommended For You" now sit ABOVE "Continue", which starts
# at y ~1013 with its tiles cut off by the screen's edge, so Bee Swarm's
# thumbnail was never in view and two joins in a row failed. After the first
# looks, the home is scrolled down a few notches between looks; the whole
# screen is still template-matched, so nothing unrecognised is ever clicked.
TILE_SCROLL_AFTER = 3          # looks before the first scroll
TILE_SCROLL_NOTCHES = 3        # per look after that (positive = down)
TILE_SCROLL_AT = (960, 600)
TILE_RECLICKS = 2              # more clicks on the tile when the first opened nothing
CONTINUE_ROW = (0, 855, 1920, 141)      # x, y, w, h: the row of tiles under "Continue"
TILE_THRESHOLD = 0.70
TILE_THRESHOLD_WHOLE = 0.85   # whole-screen search; see find_bss_tile
SERVERS_THRESHOLD = 0.90  # "Servers" scores 1.000; the "Server Size" decoy 0.695


@dataclass
class JoinResult:
    ok: bool
    reason: str
    trace: list[tuple[float, str]]


# MEASURED: the Join button is 63x32. A blue game THUMBNAIL on the app home page
# is 260x115 and passes an aspect-ratio test comfortably (2.26, well inside the
# button's own range), so aspect alone produced a false positive there. Height is
# what actually separates them -- a button is short whatever its label length.
BUTTON_MIN_H, BUTTON_MAX_H = 18, 60
BUTTON_MAX_W = 220


# MEASURED fraction of pixels darker than 60 across the top-right strip:
#   drawer open   0.986        (its header is a near-black bar)
#   app home      0.019
#   in game       0.110
#   game page     0.000
# Nothing observed lands between 0.11 and 0.99.
DRAWER_HEADER = (960, 0, 960, 44)
DRAWER_DARK_MIN = 0.60


def drawer_open(frame: np.ndarray) -> bool:
    """True when the Servers drawer's header bar is on screen."""
    x, y, w, h = DRAWER_HEADER
    strip = frame[y:y + h, x:x + w]
    if strip.size == 0:
        return False
    grey = cv2.cvtColor(strip[:, :, :3], cv2.COLOR_BGR2GRAY)
    return float((grey < 60).mean()) >= DRAWER_DARK_MIN


def find_primary_buttons(frame: np.ndarray, panel_x: int = PANEL_X,
                         min_area: int = 800,
                         require_drawer: bool = True) -> list:
    """Every saturated (blue) button in the drawer, in `blobs.find`'s order."""
    if require_drawer and not drawer_open(frame):
        return []
    mask = PRIMARY_BUTTON.mask(frame[:, :, :3])
    mask[:, :panel_x] = 0
    found = blobs.find(mask, min_area=min_area, max_area=40_000,
                       min_aspect=1.2, max_aspect=6.0)
    return [b for b in found
            if BUTTON_MIN_H <= b.h <= BUTTON_MAX_H and b.w <= BUTTON_MAX_W]


def find_primary_button(frame: np.ndarray, panel_x: int = PANEL_X,
                        min_area: int = 800,
                        require_drawer: bool = True) -> blobs.Blob | None:
    """The one saturated (blue) button in the server drawer, or None.

    Gated on the drawer actually being open. Without that gate the app home page
    yields button-SIZED blue blobs inside game thumbnails (73x33 and 76x35 against
    the real button's 63x32), which no size or aspect rule can separate -- they
    really are the same shape. Asking "is the drawer even on screen" is the
    question that distinguishes them, and it is the honest one.
    """
    found = find_primary_buttons(frame, panel_x, min_area, require_drawer)
    return found[0] if found else None


# A CHOSEN SERVER BY ITS NAME (ROADMAP M11): a friend's private server the
# account may join sits in the same "Your private servers" list as their own,
# with the same blue Join [ASSUMED: no frame of a drawer with two private
# servers has been seen]. MEASURED on tests/fixtures/screens/
# servers_drawer_private.png (their own alone): one row per server, 64 px apart
# (the "Create a private server" row above at y 165); the row's avatar at
# x 976-1016, its name ("<owner>'s server") at x 1028, y 211-227, level with
# its Join (1841-1904 x 213-245), an edit pencil at x 1800-1834 and "1 of 6
# people max" under the name. So a row is read, by tesseract, from just right
# of the avatar to left of the pencil, half a row above the Join's centre to
# its bottom edge: tesseract read the whole row with the avatar and buttons
# in it as "<name>'s server". Two rows that both match are refused.
ROW_TEXT_X0 = 1020             # right of the row's avatar
ROW_TEXT_RIGHT_GAP = 45        # left of the edit pencil, which sits 41 px left of Join
ROW_TEXT_ABOVE = 32            # half the 64 px row
# LOOK-ONLY until a drawer with two private servers has been seen: the match
# is said ("would join row ...") and their own server's Join is clicked, as
# before. True clicks the matching row's Join.
JOIN_CHOSEN_LIVE = False


def squash(text: str) -> str:
    """Letters and digits only, lower case: "someone’s  Server" and the
    OCR's "someones server" compare equal."""
    return "".join(c for c in str(text or "").casefold() if c.isalnum())


def row_box(button) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1): where the name of `button`'s row is (ROW_TEXT_*)."""
    return (ROW_TEXT_X0, max(0, int(button.cy) - ROW_TEXT_ABOVE),
            int(button.x) - ROW_TEXT_RIGHT_GAP, int(button.y + button.h))


def find_named_button(frame: np.ndarray, name: str, ocr) -> tuple:
    """(button, text read, why): the one blue Join whose row reads `name`,
    or None with why not. `ocr(frame, box) -> str`."""
    want = squash(name)
    if not want:
        return None, "", "no name to look for"
    buttons = find_primary_buttons(frame)
    if not buttons:
        return None, "", "no private-server Join in the drawer"
    reads = [(b, str(ocr(frame, row_box(b)) or "")) for b in buttons]
    hits = [(b, text) for b, text in reads if want in squash(text)]
    if len(hits) == 1:
        return hits[0][0], " ".join(hits[0][1].split()), ""
    seen = "; ".join(repr(" ".join(t.split())[:40]) for _, t in reads)
    if not hits:
        return None, "", f"no row reads '{name}' (rows read: {seen})"
    return None, "", f"{len(hits)} rows read '{name}', so none is clicked (rows read: {seen})"


def find_bss_tile(frame: np.ndarray, tile: np.ndarray | None):
    """Where Bee Swarm's thumbnail is on the Roblox home, or None.

    THE WHOLE SCREEN, NOT A FIXED BAND. MEASURED 2026-09-24 03:04:57
    (var/join/030457-never_found_the_Servers_row.png): with a Friends row
    drawn above it, the Continue row sat at y 370-580 -- Bee Swarm its first
    tile -- and the fixed band at y 855-996 held "Discover Avatars" instead.
    That is also what the blind click at 22:47:28 hit: (193, 926) was an
    avatar item. Searched over the whole screen the thumbnail scores 1.00
    at (192, 436); on a screen without it the best anything scores is 0.30
    (the 22:47 avatar page), so TILE_THRESHOLD_WHOLE sits far from both.
    """
    if tile is None or frame is None:
        return None
    try:
        return templates.find(frame, tile, threshold=TILE_THRESHOLD_WHOLE)
    except Exception:
        return None


# THE POINTER'S SPACE IS THE OUTPUT'S, NOT THE FRAME'S. MEASURED 2026-10-21
# 01:36 (var/join/013631): the app home was captured at 1280x720, a click aimed
# at the search box's x 675 put the pointer at ~455 (675 / 1.5) -- input is the
# 1920x1080 output (VIEW_LINK_X and the defaults are in it). A frame position is
# scaled by output/frame before it is clicked; a 1920 frame is unchanged.
# The sum lives in vision/screen (RL3), with every other 1920x1080 conversion.
def to_input(frame, x, y) -> tuple[int, int]:
    """A position in `frame` as the pointer's (output) coordinates."""
    return screen.to_base(frame, x, y)


# THE SEARCH BOX, when the home has no Bee Swarm tile. MEASURED 2026-10-21
# 01:20 (var/join/012029-never_found_the_Servers_row.png): after the owner played
# other games the home was all recommendations, and the share link landed on
# that same home ("did not reach the world (on app_home)"). Its box, as a share
# of the frame (1280x720: x 480-870, y 12-42), is read before Enter is pressed:
# never a blind Enter in a Roblox menu.
SEARCH_QUERY = "Bee Swarm Simulator"
SEARCH_BOX = (480 / 1280, 12 / 720, 870 / 1280, 42 / 720)
# WHERE THE TYPED QUERY IS READ BACK: a click on the bar opens a wider overlay
# (var/join/015201: its field x 290-925, the text from x 332), so the bar's own
# box caught only "...r" and the cursor ("- I").
SEARCH_READ_BOX = (300 / 1280, 12 / 720, 900 / 1280, 44 / 720)
SEARCH_LOOKS = 4
# THE TOP RESULT, read rather than matched. MEASURED 2026-10-21 02:17
# (var/join/021710): the results lead with a large "Bee Swarm Simulator / By
# Onett" card (not the home's thumbnail, so the template found nothing). Its
# title line (x 90-670, y 492-540 at 1280x720) reads "Bee Swarm Simulator By
# Onett"; only then is the card's picture clicked (x 380, y 320) -- never its
# blue Play button, which would join a public server.
TOP_RESULT_TEXT = (90 / 1280, 492 / 720, 670 / 1280, 540 / 720)
TOP_RESULT_PICTURE = (380 / 1280, 320 / 720)


@dataclass
class _Hit:
    centre: tuple
    score: float = 1.0


def top_result_is_bss(frame, ocr=None):
    """The top search result's picture centre (frame px) when its title line
    reads Bee Swarm Simulator by Onett, else None."""
    if ocr is None:
        from .shoplook import _ocr_line
        ocr = lambda f, box: _ocr_line(f, box, psm=6)
    h, w = frame.shape[:2]
    box = (int(TOP_RESULT_TEXT[0] * w), int(TOP_RESULT_TEXT[1] * h),
           int(TOP_RESULT_TEXT[2] * w), int(TOP_RESULT_TEXT[3] * h))
    text = " ".join(str(ocr(frame, box) or "").lower().split())
    if "bee swarm simulator" in text and "onett" in text:
        return _Hit((int(TOP_RESULT_PICTURE[0] * w), int(TOP_RESULT_PICTURE[1] * h)))
    return None


def search_for_the_game(ui, bss_tile, note):
    """Bee Swarm's tile found through Roblox's search, or None. Types the
    query ('/' opens the box), reads the box back, and only if it says "bee
    swarm" presses Enter; the result is clicked only on the tile template."""
    try:
        from .shoplook import _ocr_line
        # CLICK THE BOX, THEN TYPE. MEASURED 2026-10-21 01:25 (run-1134): '/'
        # alone left the box reading "Search" -- the query went nowhere.
        frame = ui.frame()
        h, w = frame.shape[:2]
        box = (int(SEARCH_BOX[0] * w), int(SEARCH_BOX[1] * h),
               int(SEARCH_BOX[2] * w), int(SEARCH_BOX[3] * h))
        ui.click(*to_input(frame, (box[0] + box[2]) // 2, (box[1] + box[3]) // 2), settle=1.0)
        ui.inp.type_text(SEARCH_QUERY)
        time.sleep(1.5)
        frame = ui.frame()
        h, w = frame.shape[:2]
        box = (int(SEARCH_READ_BOX[0] * w), int(SEARCH_READ_BOX[1] * h),
               int(SEARCH_READ_BOX[2] * w), int(SEARCH_READ_BOX[3] * h))
        typed = str(_ocr_line(frame, box, psm=7) or "")
    except Exception as exc:
        note(f"searching for Bee Swarm failed before Enter ({exc}) — clicking nothing")
        return None
    if "bee swarm" not in typed.lower():
        note(f"the search box reads {typed!r}, not the query — not pressing Enter")
        ui.back()
        return None
    note(f"Bee Swarm is not on the home — searched for it ({typed.strip()!r})")
    ui.submit()
    time.sleep(TILE_LOOK_SECONDS * 2)
    for _ in range(SEARCH_LOOKS):
        frame = ui.frame()
        hit = find_bss_tile(frame, bss_tile)
        if hit is not None:
            return hit
        try:
            hit = top_result_is_bss(frame)
        except Exception:
            hit = None
        if hit is not None:
            note("the top search result reads Bee Swarm Simulator by Onett — opening it")
            return hit
        time.sleep(TILE_LOOK_SECONDS)
    note("the search results show no tile that matches Bee Swarm's — clicking nothing")
    return None


def open_server_drawer(ui, servers_label: np.ndarray,
                       max_scrolls: int = 12, bss_tile: np.ndarray | None = None,
                       stage=None) -> bool:
    """From the app home, reach the game page and open its Servers drawer."""
    note = stage or (lambda text: None)
    ui.focus()
    if bss_tile is None:
        note("no Bee Swarm tile template is loaded, so there is nothing to "
             "recognise the game by — clicking nothing (data/templates/ui/"
             "bss_tile.png)")
        return False
    hit = None
    for look in range(1, TILE_LOOKS + 1):
        hit = find_bss_tile(ui.frame(), bss_tile)
        if hit is not None:
            break
        if look >= TILE_SCROLL_AFTER:
            ui.scroll(TILE_SCROLL_NOTCHES, at=TILE_SCROLL_AT)
        time.sleep(TILE_LOOK_SECONDS)
    if hit is None:
        hit = search_for_the_game(ui, bss_tile, note)
    if hit is None:
        note(f"Bee Swarm's thumbnail is not on the home after {TILE_LOOKS} "
             f"looks (scrolled down from look {TILE_SCROLL_AFTER}) — clicking nothing, because an unrecognised tile can be a "
             f"shop item (22:47:28). If this repeats, refresh data/templates/ui/"
             f"bss_tile.png from a home frame")
        return False
    note(f"Bee Swarm's tile at {hit.centre} (thumbnail score {hit.score:.2f}"
         + (f", look {look}" if look > 1 else "") + ")")
    ui.click(*to_input(ui.frame(), *hit.centre), settle=4.0)
    # A CLICK THAT ONLY FOCUSED THE WINDOW. MEASURED 2026-10-16 22:54-23:25
    # (var/join/225416, 232440, 232529): beside another game, with the keyboard
    # handed back to Steam, the tile click opened nothing -- the home stayed,
    # the Servers search then scrolled it away. The tile still in view where
    # it was clicked means the click did not land; click it again.
    for again in range(TILE_RECLICKS):
        still = find_bss_tile(ui.frame(), bss_tile)
        if still is None or abs(still.centre[0] - hit.centre[0]) > 20 \
                or abs(still.centre[1] - hit.centre[1]) > 20:
            break
        note(f"the game page did not open — the tile is still at {still.centre}; "
             f"clicking it again ({again + 1} of {TILE_RECLICKS})")
        ui.focus()
        ui.click(*to_input(ui.frame(), *still.centre), settle=4.0)

    for _ in range(max_scrolls):
        seen = ui.frame()
        hit = templates.find(seen, servers_label,
                             threshold=SERVERS_THRESHOLD)
        if hit is not None:
            ui.click(VIEW_LINK_X, to_input(seen, 0, hit.cy)[1], settle=2.0)
            return True
        ui.scroll(3, at=(960, 700))
    return False


def wait_until_still(ui, polls: int = 20, interval: float = 1.0) -> None:
    """Wait for the drawer to stop changing.

    It renders the word "Loading" before the list arrives, so acting on the
    first frame after the click would click empty space.
    """
    prev = None
    for _ in range(polls):
        frame = ui.frame()[:, :, :3]
        if prev is not None and np.array_equal(frame, prev):
            return
        prev = frame
        time.sleep(interval)


def arrived(ui) -> bool:
    """Has the world loaded while we were still poking at the menu?

    THE BUG THIS EXISTS FOR, seen live 2026-09-20. The app was genuinely on
    the home screen at 8 s, the join then WORKED, and this function kept
    scrolling and clicking for the next two minutes -- because nothing in the
    flow below asked whether it had already arrived. Those clicks and scrolls
    landed in the game world, and the owner found their character parked on a
    ledge above the map while the log still read "app home after 8s".

    A menu routine that cannot tell it has left the menu is dangerous in a way
    a failing one is not: failing is loud, and this was silent.
    """
    try:
        return ss.classify(ui.frame()) is ss.Screen.IN_GAME
    except Exception:
        return False


def join_private_server(ui, servers_label: np.ndarray,
                        timeout: float = 240.0,
                        bss_tile: np.ndarray | None = None,
                        name: str = "", ocr=None,
                        live: bool | None = None) -> JoinResult:
    """Full flow: app home -> private server -> in game. With `name`, the
    drawer row that reads it (`find_named_button`), else their own as before."""
    # EVERY STAGE SAYS SO. MEASURED 2026-09-22 19:27: attempt 227 printed
    # "app home after 11s" and then nothing for 339 seconds before "FAILED:
    # ended on app_home". Every stage below is bounded, so it was not a hang,
    # but five silent minutes with no line between stages meant the failure
    # could not be placed -- drawer never opened? list never settled? button
    # found where? click ignored? These lines cost nothing and answer that.
    def stage(text: str) -> None:
        print(f"    join: {text}", flush=True)

    if arrived(ui):
        return JoinResult(True, "already in game", ui.trace)
    if not open_server_drawer(ui, servers_label, bss_tile=bss_tile, stage=stage):
        return JoinResult(False, "never found the Servers row", ui.trace)
    stage("Servers drawer opened")

    wait_until_still(ui)
    stage("drawer settled")

    # Scroll the drawer to its top, where "Your private servers" sits, and
    # LOOK AFTER EACH BATCH rather than only at the end.
    #
    # MEASURED: two of four bootstraps in a row failed with "no Join button in
    # the drawer". The drawer populates asynchronously, so a fixed dozen
    # scrolls sometimes finishes before the private-server row has rendered,
    # and sometimes overshoots past it. Checking as we go costs nothing when
    # the button is already there and is the difference between a run that
    # starts and a night that does not.
    button = None
    for attempt in range(4):
        for _ in range(6):
            # Checked EVERY scroll, not once per batch: the world can load at
            # any moment, and every scroll after it does lands in the game.
            if arrived(ui):
                return JoinResult(True, "already in game", ui.trace)
            ui.scroll(-5, at=(PANEL_X, 600), settle=0.4)
        wait_until_still(ui)
        if arrived(ui):
            return JoinResult(True, "already in game", ui.trace)
        button = find_primary_button(ui.frame())
        if button is not None:
            break
        # nudge back down a little in case we scrolled past it
        ui.scroll(2, at=(PANEL_X, 600), settle=0.5)
        button = find_primary_button(ui.frame())
        if button is not None:
            break
    if button is None:
        return JoinResult(False, "no private-server Join button in the drawer",
                          ui.trace)
    if name:
        button = chosen_button(ui.frame(), name, button, stage, ocr=ocr,
                               live=JOIN_CHOSEN_LIVE if live is None else live)
    stage(f"Join button at ({int(button.cx)}, {int(button.cy)})")

    if arrived(ui):
        return JoinResult(True, "already in game", ui.trace)
    ui.click(*to_input(ui.frame(), int(button.cx), int(button.cy)), settle=2.0)
    stage(f"clicked it; waiting up to {timeout:.0f}s for the world")
    state = ui.wait_for(ss.Screen.IN_GAME, ss.Screen.MODAL, timeout=timeout)
    if state is ss.Screen.IN_GAME:
        return JoinResult(True, "in game", ui.trace)
    stage(f"the screen ended on {state.value}; screens seen: "
          + (" -> ".join(str(t) for t in ui.trace) if ui.trace else "none recorded"))
    return JoinResult(False, f"ended on {state.value}", ui.trace)


def chosen_button(frame, name: str, own, stage, *, ocr=None, live: bool = False):
    """The Join to click for the row `name`: its own when found and `live`,
    else `own` (their private server's, today's click) with the reason said.
    Never a Join whose row does not read `name`."""
    if ocr is None:
        from .shoplook import _ocr_line
        ocr = lambda f, box: _ocr_line(f, box, psm=6)
    try:
        hit, text, why = find_named_button(frame, name, ocr)
    except Exception as exc:
        hit, text, why = None, "", f"could not read the rows ({type(exc).__name__}: {exc})"
    if hit is None:
        stage(f"the server '{name}': {why} — joining your own private server instead")
        return own
    if not live:
        stage(f"would join row '{text}' at ({int(hit.cx)}, {int(hit.cy)}) — look-only "
              f"(JOIN_CHOSEN_LIVE off), so your own private server instead")
        return own
    stage(f"joining row '{text}'")
    return hit
