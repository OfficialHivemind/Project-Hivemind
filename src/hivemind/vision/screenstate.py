"""Which screen are we actually looking at?

Every action the agent takes is only valid on a particular screen: pressing W
means nothing on the app home page, and clicking "Join" means nothing in-game.
So before acting, the loop asks this module what it is looking at.

The first version of this check used mean brightness and saturation thresholds
and it was wrong in the most dangerous way -- it reported a private-server join
as successful when the screen actually held a "Join Error" dialog, because a
colourful app home page cleared its saturation bar. Thresholds over a whole
frame are guesses about content; structure is not. So every state here is
decided by a *specific* feature at a *measured* location:

  IN_GAME     the Honey counter parses as a number
  MODAL       a grey dialog panel with a light button inside it
  APP_HOME    the Roblox app's white content area
  LOADING     none of the above, and mostly dark

Measurements come from real 1920x1080 Sober captures (see docs/DESIGN.md 8a).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

from ..datapaths import data
from . import digits
from . import screen
from . import templates as templates_mod


class Screen(str, Enum):
    IN_GAME = "in_game"
    MODAL = "modal"
    APP_HOME = "app_home"
    LOADING = "loading"
    UNKNOWN = "unknown"


# --- modal dialog -------------------------------------------------------
# MEASURED on the Error 524 frame: the panel is a flat mid-grey rectangle at
# (706, 313) 638x357 and its button is near-white at (780, 609) 360x36. Roblox
# draws every one of these dialogs from the same widget, so we look for the
# *shape relationship* -- a wide grey panel containing a much lighter bar --
# rather than those exact coordinates, which differ per dialog height.
PANEL_GREY = (55, 85)        # inclusive grey range of the dialog body
PANEL_MIN_AREA = 20_000      # the measured panel is 107,635 px
PANEL_MIN_W, PANEL_MIN_H = 300, 120
BUTTON_MIN_LUMA = 200        # measured button interior is >200; panel is <85
BUTTON_MIN_AREA = 3_000      # measured button is 12,729 px
CENTRED_TOL = 0.15           # dialog centre must sit within 15% of frame centre


@dataclass(frozen=True)
class Modal:
    """A dialog box on screen, with the buttons found inside it."""
    x: int; y: int; w: int; h: int
    buttons: tuple[tuple[int, int, int, int], ...]   # (x, y, w, h) each

    @property
    def body(self) -> tuple[int, int, int, int]:
        """Region holding the message text, above the first button."""
        top = self.y + int(self.h * 0.15)
        bottom = min(b[1] for b in self.buttons) if self.buttons else self.y + self.h
        return (self.x, top, self.w, max(1, bottom - top))

    def button_centre(self, index: int = 0) -> tuple[int, int]:
        x, y, w, h = self.buttons[index]
        return (x + w // 2, y + h // 2)


def find_modal(frame: np.ndarray) -> Modal | None:
    """Locate a Roblox dialog panel, or None. Buttons are ordered top to bottom."""
    grey = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2GRAY)

    panel_mask = ((grey >= PANEL_GREY[0]) & (grey <= PANEL_GREY[1])).astype(np.uint8)
    n, _lbl, stats, _c = cv2.connectedComponentsWithStats(panel_mask, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < PANEL_MIN_AREA or w < PANEL_MIN_W or h < PANEL_MIN_H:
            continue
        if w >= frame.shape[1] * 0.95:      # a full-width band is a backdrop, not a panel
            continue
        if best is None or area > best[4]:
            best = (x, y, w, h, area)
    if best is None:
        return None

    px, py, pw, ph, _ = best
    # MEASURED: Roblox centres its dialogs. The Error 524 panel sits at centre
    # x=1025 against a frame centre of 960. In-game HUD panels do not: the one
    # on the walk-test frame centres at 448 and the escape menu at 1457, and
    # both were being reported as dialogs before this check existed.
    if abs((px + pw / 2) - frame.shape[1] / 2) > frame.shape[1] * CENTRED_TOL:
        return None

    inner = grey[py:py + ph, px:px + pw]
    btn_mask = (inner > BUTTON_MIN_LUMA).astype(np.uint8)
    bn, _bl, bstats, _bc = cv2.connectedComponentsWithStats(btn_mask, 8)
    buttons = []
    for i in range(1, bn):
        bx, by, bw, bh, barea = bstats[i]
        if barea < BUTTON_MIN_AREA or bw < 60 or bh < 12:
            continue
        buttons.append((px + int(bx), py + int(by), int(bw), int(bh)))
    if not buttons:
        # A grey panel with nothing to click is a splash or a backdrop, not a
        # dialog. The Sober startup screen was being reported as MODAL until
        # this check was added, which would have made the agent hunt for a
        # button that does not exist.
        return None
    buttons.sort(key=lambda b: b[1])
    return Modal(int(px), int(py), int(pw), int(ph), tuple(buttons))


# --- app home -----------------------------------------------------------
# MEASURED: the Roblox app home renders a light content area; the game world
# never does. Sampled over the central band to ignore the dark letterbox bars
# the nested compositor leaves when the app is not yet fullscreen.
# MEASURED median luminance of that band across every frame captured so far:
#   join-error 12 | headless 17 | Sober splash 41 | escape menu 46 | app home 247
# The split is bimodal with nothing between 46 and 247, so the median separates
# cleanly where the *mean* did not -- the splash screen's bright logo pulled its
# mean to 61, straddling the cutoff, while its median sat at 41 with the rest.
HOME_BAND = (0.25, 0.75)     # fraction of height to sample
HOME_MIN_LUMA = 150          # above this: app home
DARK_MAX_LUMA = 100          # below this: loading. Between the two: UNKNOWN,
                             # which means "not a screen we have measured".


def _band(frame: np.ndarray) -> np.ndarray:
    h = frame.shape[0]
    return frame[int(h * HOME_BAND[0]):int(h * HOME_BAND[1]), :, :3]


# --- the HUD itself -----------------------------------------------------
# MEASURED: fraction of pixels brighter than 170 inside the Honey and Pollen
# pills, over every frame captured so far.
#
#   in-game (3 frames)  40.6 - 45.6%      <- text on a translucent pill
#   app home                97.1 - 100%   <- flat white page
#   modal / splash / headless      0%     <- flat dark
#   escape menu                    0%
#
# Nothing observed lands between 0 and 40%, or between 46 and 97%, so this is a
# wide-margin test -- and unlike reading the counter it needs no templates.
# That matters: the digit reader returned "10,216,20?" on a genuinely in-game
# frame purely because the glyph 9 had never been seen, and two real joins were
# recorded as failures. Structure first, then read the value.
HONEY_REGION = (660, 22, 294, 36)
POLLEN_REGION = (958, 22, 300, 36)


def hud_region(frame: "np.ndarray", region) -> tuple[int, int, int, int]:
    """A pill's 1920x1080 region on `frame`: the pills hang from the top
    middle at a fixed size (vision/screen, MEASURED at 1280x720 too). Every
    reader of HONEY_REGION / POLLEN_REGION crops through this."""
    return screen.region(frame, region, screen.TOP)

# THE POLLEN BAR ITSELF, inside the pill, measured 2026-09-23 00:20 on frames
# whose numbers were legible: x 64..282 and rows 5..11 within POLLEN_REGION.
# The fill is GREEN low and RED high, the empty track is grey, and the white
# digits sit across the middle rows -- which is why the band is the six rows
# above them rather than the whole pill.
#
# WHY THIS EXISTS. MEASURED 2026-09-22 23:37 to 2026-09-23 00:22: with the
# backpack full the pill reads "1,208,419/1,205,886" and the digit reader
# returns "11?0?46/111???0" at 0.49 confidence -- seven digits either side of
# the slash defeat it. So the planner never saw 90%, never converted, and
# every trip for forty-five minutes gathered into a full bag: honey stuck at
# 7,256,845 across six attempts, "the pollen counter was unreadable 22x".
# The bar needs no OCR. Checked against five frames with legible numbers:
#
#     1,208,419/1,205,886 (over full)  ->  100.0%   (want 100%)
#     627,840/660,000                  ->   95.0%   (want 95.1%)
#     313,642/1,113,750                ->   27.5%   (want 28.2%)
#     57,261/1,113,750                 ->    4.1%   (want  5.1%)
#     7,214/1,113,750                  ->    0.0%   (want  0.6%)
#
# and it reads nothing at all on the app home, where there is no pill.
POLLEN_BAR = (64, 282, 5, 11)          # left, right, top, bottom in the region
BAR_FILL_MIN_SATURATION = 80
BAR_FILL_MIN_VALUE = 80
BAR_TRACK_MAX_SATURATION = 40
BAR_TRACK_VALUE = (60, 220)
# Below this many of the bar's columns recognised as either fill or track,
# there is no bar on screen to measure. MEASURED: a real pill recognises
# 130-218 of its 218 columns (a bright background can wash out part of the
# track); the app home recognises 0 and the escape menu 15.
BAR_MIN_COLUMNS = 60


# WHERE THE GAME PRINTS ITS OWN RATE, inside each counter's region.
#
# MEASURED 2026-09-23 08:15 from `var/hotbar/hotbar-slot1-after-081519.jpg`:
#
#     Honey  24,471,762  (+9/sec)     Pollen  21,401/1,191,713  (+71/sec)
#
# The game shows a LIVE RATE beside both counters and nothing in this project
# had ever read it. Every field rate in `brain/fieldnotes` is inferred instead
# -- counter deltas over long windows, with all the trouble that brings: the
# digits are illegible above a million (8aq), a token pickup lands as a lump
# inside one interval (8av), and the numerator and denominator have to be kept
# describing the same seconds (8au). This is the same quantity, printed by the
# game, exact.
#
# `(left, right)` within the counter's own region. Both counters put it in the
# same place: x 200-285 of a 300-wide region, which is where "(+71/sec)" and
# "(+9/sec)" were measured.
RATE_BOX = (200, 285)


def rate_in(frame: "np.ndarray", region, templates) -> int | None:
    """The `(+N/sec)` the game prints beside a counter, or None.

    The digit reader sees `(+71/sec)` as `??71/????` -- the parentheses, the
    plus and the letters are not digits and come back as `?`. The number is
    the run of digits immediately before the slash, which is the only place a
    number can be in that format.
    """
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    from . import digits as _digits
    rx, ry, _rw, rh = hud_region(frame, region)
    left, right = RATE_BOX
    roi = frame[ry:ry + rh, rx + left:rx + right, :3]
    if roi.size == 0:
        return None
    try:
        text, _score = _digits.read(roi, templates)
    except Exception:
        return None
    return rate_from_text(text)


def rate_from_text(text: str) -> int | None:
    """The number out of a `(+N/sec)` reading, whatever the reader made of
    the punctuation around it.

    Written apart from the crop so it can be tested on strings. What the
    digit reader actually returns, MEASURED 2026-09-23 over the saved
    incident windows (var/incidents/*-mob-sighting, 50 frames each):

        (+71/sec)    ->  ??71/????     the slash was recognised
        (+9/sec)     ->  ??9?????      it was not
        (+758/sec)   ->  ??758/5???    and the `s` of `sec` read as a 5
        (+1594/sec)  ->  ??1594/5???   on nearly every frame

    The first version refused any text with two digit runs, and that refused
    the third shape -- which is most frames: 1 or 2 readings out of 50 per
    window survived. The rule now: when there is a slash, the rate is the
    run of digits ENDING at it, and whatever follows is the letters of `sec`;
    with no slash, the box holds one number and two runs is a misread.
    """
    text = str(text or "")
    if "/" in text:
        before = text.split("/", 1)[0]
        runs_before = [r for r in "".join(c if c.isdigit() else " " for c in before).split()]
        if len(runs_before) != 1 or not before.rstrip("?")[-1:].isdigit():
            # two numbers before the slash, or none touching it: a misread,
            # not a rate -- the same refusal as the no-slash case
            return None
        try:
            return int(runs_before[0])
        except ValueError:
            return None
    runs = []
    current = ""
    for ch in text:
        if ch.isdigit():
            current += ch
        elif current:
            runs.append(current)
            current = ""
    if current:
        runs.append(current)
    if len(runs) != 1:
        return None
    try:
        return int(runs[0])
    except ValueError:
        return None

def pollen_bar_fill(frame: "np.ndarray") -> float | None:
    """How full the backpack looks, 0..1, from the bar's colours alone --
    or None when no bar can be found. No digits, so it survives a counter
    the reader cannot parse."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    rx, ry, _rw, _rh = hud_region(frame, POLLEN_REGION)
    left, right, top, bottom = POLLEN_BAR
    band = frame[ry + top:ry + bottom, rx + left:rx + right, :3]
    if band.size == 0 or band.shape[1] < BAR_MIN_COLUMNS:
        return None
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    sat = hsv[..., 1].astype(int)
    val = hsv[..., 2].astype(int)
    filled = ((sat > BAR_FILL_MIN_SATURATION) & (val > BAR_FILL_MIN_VALUE)).mean(axis=0) > 0.5
    lo, hi = BAR_TRACK_VALUE
    track = ((sat < BAR_TRACK_MAX_SATURATION) & (val > lo) & (val < hi)).mean(axis=0) > 0.5
    if int((filled | track).sum()) < BAR_MIN_COLUMNS:
        return None
    return float(filled.sum()) / float(right - left)
HUD_TEXT_LUMA = 170
HUD_BRIGHT_RANGE = (0.25, 0.70)
MIN_POLLEN_GLYPHS = 5        # "0/660,000" is 9; the store page manages only 7
SLASH_TALLER = 1.25          # slash is 16 px against digits at 11
# RELATIVE to the digits, not an absolute pixel count. MEASURED: Bee Swarm
# shrinks the Pollen text to fit more characters, so the same pill renders at
# two different sizes:
#
#     "445,372/660,000"   digits h 11 w 8    slash h 16 w 5
#     "0/660,000"         digits h 15 w 11   slash h 21 w 7
#
# An absolute `slash_w <= 6` passes the first and fails the second, so the HUD
# went undetected on every frame with a short pollen count -- which is every
# frame just after converting, i.e. exactly when the farm loop starts. The
# proportions are stable where the pixels are not: 5/8 = 0.63 and 7/11 = 0.64
# wide, 16/11 = 1.45 and 21/15 = 1.40 tall.
SLASH_NARROWER = 0.80        # slash is ~0.64 of a digit's width
LONG_COUNTER_GLYPHS = 13     # "15,068,506/10,560,237" is 16; the store page makes 7
LONG_COUNTER_SPREAD_PX = 3   # one height give or take: 8-9 px in the JPEGs; a raw, unblurred frame can read a glyph 1-2 px taller (01:25-01:29 runs 1175-1176 looped NO_HUD while their saved JPEGs passed at 1)


# A BLIND VIEW: THE CAMERA INSIDE THE WORLD. MEASURED 2026-10-02 over the
# 49 "chase did not start" incidents (var/incidents/*-token-nostart, 150
# frames each over 10.8 s): 47 of them hold frames where the camera has
# clipped into Pine Tree's trees or cliff -- the world region 70-100% near-
# black, no edges -- typically 3-7 of 15 sampled frames, against 5% of frames
# (12 of 60 windows) in ordinary gathering (the mob-sighting incidents). On
# one (222911) the target "honey#422" was born in such a frame, black with
# yellow specks, and nothing was ever at its spot. Night is no blinder: the
# 00:00-04:00 incidents' median dark share is 0.14-0.52 like the day's.
WORLD_BOX = (200, 130, 1720, 950)     # x0, y0, x1, y1: inside the HUD and the hotbar
BLIND_DARK_V = 45                     # HSV value under this is "near-black"
BLIND_DARK_SHARE = 0.6                # of the world box; normal frames read 0.07-0.35


def world_blind(frame: np.ndarray) -> bool:
    """The camera sees nothing of the world: most of the view is near-black
    (it has clipped inside a tree, a wall, the ground). Sightings made in such
    a frame are not tokens."""
    if frame is None or frame.ndim != 3:
        return False
    x0, y0, x1, y1 = WORLD_BOX
    world = frame[y0:y1, x0:x1, :3]
    if world.size == 0:
        return False
    value = cv2.cvtColor(np.ascontiguousarray(world), cv2.COLOR_BGR2HSV)[..., 2]
    return float((value < BLIND_DARK_V).mean()) >= BLIND_DARK_SHARE


def hud_present(frame: np.ndarray,
                regions: tuple[tuple[int, int, int, int], ...] =
                (HONEY_REGION, POLLEN_REGION)) -> bool:
    """True when the Honey and Pollen pills are both on screen.

    Brightness alone is NOT enough. The Bee Swarm *store page* -- which the agent
    passes through on its way to the server list -- reads 0.473 and 0.482 in
    these two regions, squarely inside the in-game band, and was classified as
    IN_GAME. So a second, structural test is required.

    That test is the slash. Pollen is always drawn as "current/capacity", so a
    genuine Pollen pill always contains a separator that is taller than the
    digits around it and narrow. MEASURED over every frame captured:

      in-game        15 components, median height 11, slash at h=16 w=5   -> yes
      game page       7 components, median height 19, nothing narrow      -> no
      game page (scrolled) 1 component                                    -> no
      app home        0 components                                        -> no

    This is a property of the game's own HUD rather than a tuned threshold,
    which is why it is worth the extra segmentation pass.
    """
    lo, hi = HUD_BRIGHT_RANGE
    for x, y, w, h in (hud_region(frame, r) for r in regions):
        roi = frame[y:y + h, x:x + w]
        if roi.size == 0:
            return False
        grey = cv2.cvtColor(roi[:, :, :3], cv2.COLOR_BGR2GRAY)
        if not lo <= float((grey > HUD_TEXT_LUMA).mean()) <= hi:
            return False

    # The POLLEN region the CALLER supplied, not the module default. The
    # structural slash test is the load-bearing half of this check -- it is
    # what stops the Bee Swarm store page being classified as IN_GAME -- and
    # it was always being run against the hard-coded 1920x1080 rectangle
    # regardless of the argument. data/calib/regions.yaml exists precisely to
    # carry measured per-layout regions, so any caller using it got a silent
    # false negative on a genuine in-game frame; symmetrically, a frame whose
    # supplied regions are blank could pass on the default rectangle.
    px, py, pw, ph = hud_region(frame, regions[-1])
    glyphs = digits.segment(frame[py:py + ph, px:px + pw], lost_commas=False)
    if len(glyphs) < MIN_POLLEN_GLYPHS:
        return False
    median_h = float(np.median([g.h for g in glyphs]))
    median_w = float(np.median([g.w for g in glyphs]))
    if any(g.h > median_h * SLASH_TALLER and g.w < median_w * SLASH_NARROWER
           for g in glyphs):
        return True
    # A LONG COUNTER HAS NO TALLER SLASH. MEASURED 2026-10-21 22:45 (run-1168,
    # var/incidents/20261021-224419-hud-missing; /run/user/1000/hivemind-live.jpg):
    # "15,068,506/10,560,237" -- 8 digits each side -- is drawn small, its 16
    # glyphs all 8 px high, slash included, so every read said NO_HUD with the
    # HUD in plain view; the run stopped, rejoined with the bag kept, and
    # looped (1168-1170). Only the HUD's counter makes that many glyphs of one
    # height: the store page makes 7 (see above).
    heights = [g.h for g in glyphs]
    return (len(glyphs) >= LONG_COUNTER_GLYPHS
            and max(heights) - min(heights) <= LONG_COUNTER_SPREAD_PX)


def classify(frame: np.ndarray, templates: digits.TemplateSet | None = None,
             honey_region: tuple[int, int, int, int] = HONEY_REGION) -> Screen:
    """Name the screen.

    The HUD check comes first and needs no templates; reading the counter is
    kept as a second route so a HUD relayout cannot blind the agent entirely.
    """
    if hud_present(frame):
        return Screen.IN_GAME

    if templates is not None and templates.chars:
        x, y, w, h = hud_region(frame, honey_region)
        roi = frame[y:y + h, x:x + w]
        if roi.size:
            text, score = digits.read(roi, templates)
            if digits.to_int(text) is not None and score >= 0.55:
                return Screen.IN_GAME

    if find_modal(frame) is not None:
        return Screen.MODAL

    luma = float(np.median(cv2.cvtColor(_band(frame), cv2.COLOR_BGR2GRAY)))
    if luma > HOME_MIN_LUMA:
        return Screen.APP_HOME
    if luma < DARK_MAX_LUMA:
        return Screen.LOADING
    return Screen.UNKNOWN


def load_templates(path: str | Path = "data/templates/digits") -> digits.TemplateSet | None:
    p = Path(path)
    try:
        return digits.TemplateSet.load(p)
    except (FileNotFoundError, NotADirectoryError):
        return None


# --- the respawn confirmation, and why it needs its own detector ------------
#
# BeeTuxMacro resets with Escape, R, Return, and a reset is what makes an
# open-loop route repeatable: it fixes both position AND heading. Four of the
# transpiled routes contain one.
#
# But Escape opens Roblox's in-game menu, and MEASURED on a real frame that
# menu carries **Leave** as an ordinary button, one place along from Respawn,
# next to Resume. Pressing Return there with the wrong thing focused quits the
# game or worse. Escaping out of the confirmation does NOT return to the world
# either -- it goes back to that same menu, so the dangerous screen is exactly
# where a retry would land.
#
# Both screens are the same large dark centred panel, so panel detection cannot
# tell them apart -- which is the whole reason a blind Return is unsafe. What
# distinguishes them is the "Don't Respawn" button, which exists ONLY on the
# confirmation. Measured against four real frames:
#
#     respawn confirmation   1.000
#     escape menu            0.326
#     in game                0.230
#     after Escape           0.326
#
# A margin of 0.67 between the screen we may press Return on and every screen
# we may not.
RESET_DIALOG_TEMPLATE = "dont_respawn.png"
RESET_DIALOG_THRESHOLD = 0.75


def reset_dialog_present(frame: np.ndarray,
                         template: np.ndarray | None = None,
                         threshold: float = RESET_DIALOG_THRESHOLD) -> bool:
    """True only when the respawn confirmation is on screen.

    Returns False when the template is unavailable. That is deliberate: the
    caller uses this to decide whether pressing Return is safe, and "I cannot
    tell" must mean "do not press it".
    """
    if template is None:
        path = data("templates", "ui", RESET_DIALOG_TEMPLATE)
        if not path.exists():
            return False
        template = cv2.imread(str(path))
        if template is None:
            return False
    return templates_mod.find(frame, template, threshold=threshold) is not None


# THE RESPAWN BUTTON ITSELF, for a confirmation that did not take Return.
# MEASURED 2026-09-27 11:18 (var/routes/attempt-493, four `reset-stuck`
# frames): the confirmation stayed up after two Returns 7.5 s apart, and again
# on the next try -- the eighth refusal in 128 respawns since attempt 460, all
# in pairs, and no second Return has ever got one through. In all four frames
# "Don't Respawn" matched at (965, 455) 213x60 at 0.989 and the Respawn
# button's dark-blue fill ran x 750-949, y 460-507 beside it, so its centre is
# (-116, +28) from the match's corner. Its fill is H 111-114, S ~198, V ~102;
# over the box below that blue covers 0.81 of it on the button (the white word
# is the rest) and 0.0 on the frame after the menu was left.
RESPAWN_BUTTON_OFFSET = (-116, 28)
RESPAWN_BUTTON_BOX = (40, 12)          # half-width, half-height, around it
RESPAWN_BUTTON_HSV = ((105, 120, 60), (125, 255, 255))
RESPAWN_BUTTON_MIN_FILL = 0.5


def respawn_button_point(frame: np.ndarray,
                         template: np.ndarray | None = None,
                         threshold: float = RESET_DIALOG_THRESHOLD
                         ) -> tuple[int, int] | None:
    """Where to click the respawn confirmation's Respawn button, or None.

    A point only when the confirmation is on screen (`reset_dialog_present`'s
    template, found here so the point comes from the same match) AND the
    button's own fill is where the measured layout puts it. None means do
    not click: nothing here guesses at a button.
    """
    if frame is None:
        return None
    if template is None:
        path = data("templates", "ui", RESET_DIALOG_TEMPLATE)
        if not path.exists():
            return None
        template = cv2.imread(str(path))
        if template is None:
            return None
    found = templates_mod.find(frame, template, threshold=threshold)
    if found is None:
        return None
    x = found.x + RESPAWN_BUTTON_OFFSET[0]
    y = found.y + RESPAWN_BUTTON_OFFSET[1]
    dx, dy = RESPAWN_BUTTON_BOX
    if x - dx < 0 or y - dy < 0 or y + dy >= frame.shape[0] or x + dx >= frame.shape[1]:
        return None
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[y - dy:y + dy + 1, x - dx:x + dx + 1, :3]),
                       cv2.COLOR_BGR2HSV)
    lo, hi = RESPAWN_BUTTON_HSV
    fill = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    if float((fill > 0).mean()) < RESPAWN_BUTTON_MIN_FILL:
        return None
    return int(x), int(y)


# THE HIVE'S OWN PROMPT, READ CHEAPLY ENOUGH TO POLL WHILE WALKING.
#
# "Make Honey" is what the top-centre panel says while standing on the pad
# this account owns (six reads over fifteen seconds, all identical,
# 2026-09-20), and it is gone one step off it. Reading it through the vision
# model costs about a second, which is fine once at the end of a route and
# useless as a stop signal for a key that is held down -- Natro's
# `nm_findHiveSlot` polls its bitmap continuously while holding Left along
# the hive row, and that is the job this exists for (act/hiverow).
#
# The crop is `prompt_make_honey.png` (data/templates/ui/README.md), from a
# frame at the hive after a respawn. MEASURED 2026-09-23 against the frames
# the route runner saves per leg: 0.839 on the leg that ended on the pad
# (var/routes/attempt-296/051720-natro_home_spider-10-walk-s6.jpg), 0.836 on
# each of var/hivepanel/on_*.png, and 0.245-0.313 on every other frame of
# that walk home. The band is where the prompt is drawn -- y=62 of 1080 on
# every hit -- with room for a taller HUD; searching only there is what
# makes this cheap.
MAKE_HONEY_TEMPLATE = "prompt_make_honey.png"
# THE SAME PAD WITH AN EMPTY BAG SAYS SOMETHING ELSE. MEASURED 2026-09-23
# 20:39:14 (`var/respawn/203914-spawn.jpg`): standing on the owner's pad with
# 0 pollen, the panel is a two-line blue banner, "To Make Honey, Collect
# Pollen From Flower Fields", with no E box -- and the "Make Honey" template
# reads 0.29 against it. Every post-respawn confirmation had failed on that
# (the bag is always empty after an errand), and a forward hold "found no
# pad" while standing on it. With 1,437 pollen the pad shows the E prompt
# again (0.295 for this template on `attempt-330/...-00-start.jpg`). Either
# banner means "on our own pad", so either template does.
MAKE_HONEY_EMPTY_TEMPLATE = "prompt_make_honey_empty.png"
MAKE_HONEY_THRESHOLD = 0.75
MAKE_HONEY_BAND_ROWS = 260
# THE EMPTY-BAG BANNER IS TRANSLUCENT, SO IT SCORES BY ITS BACKGROUND. MEASURED
# 2026-09-23 over 4,529 saved frames: every frame with the banner matched at
# x=782 -- 33 at (782, 60) scoring 0.63-0.69 (route frames, JPEG q70, the
# honeycomb wall showing through), two at 0.97-1.00, and one at (782, 70)
# scoring 0.608 with the owner's name on the wall showing through it
# (`attempt-281/021930-cannon-hop01.jpg`, on the pad at 03:19). The corpus
# p99 was 0.513 and nothing off the banner's column scored above 0.565. The
# game draws this prompt in one column, as it draws "Make Honey" at (854,
# 62), so the match is gated to that column with room for the ten-pixel
# shift, and the threshold sits between the weakest banner and the corpus.
MAKE_HONEY_EMPTY_THRESHOLD = 0.55
MAKE_HONEY_EMPTY_AT = (782, 60)
MAKE_HONEY_EMPTY_SLACK = (12, 14)         # px either side, x and y
# AND WHEN THE TEMPLATE IS UNSURE, THE BANNER'S OWN WORDS. On the pad the hive's
# honeycomb fills the view behind the translucent banner and the template falls
# short of its bar. MEASURED 2026-09-29 over var/respawn (758 respawn frames, the
# banner band read as text): 107 of the 146 kept as "spawn" show "To Make Honey,
# Collect Pollen From Flower Fields" -- they were ON our own pad with an empty
# bag, taken for the spawn point, and the walk forward then left the pad (22 of 39
# "could not walk onto the pad" in run-510..531) -- and scored 0.33-0.55 against
# this template, while the 81 kept without the banner scored at most 0.21 (and
# twice 0.53, whose words say no banner). So between these two scores the words
# decide: "make honey" with "collect" or "flower", read in the banner's band.
MAKE_HONEY_EMPTY_UNSURE = 0.30
MAKE_HONEY_EMPTY_WORDS_BOX = (700, 50, 1220, 125)
_MAKE_HONEY_CACHE: dict[str, np.ndarray | None] = {}


def _ui_template(name: str) -> np.ndarray | None:
    path = data("templates", "ui", name)
    key = str(path)
    if key not in _MAKE_HONEY_CACHE:
        _MAKE_HONEY_CACHE[key] = (cv2.imread(key) if path.exists() else None)
    return _MAKE_HONEY_CACHE[key]


def make_honey_present(frame: np.ndarray,
                       template: np.ndarray | None = None,
                       threshold: float = MAKE_HONEY_THRESHOLD) -> bool:
    """True only when the hive pad's own prompt is on screen -- "Make Honey"
    with pollen in the bag, or the empty-bag banner without.

    False when no template is available, for the same reason as
    `reset_dialog_present`: the caller stops a held key on this, and "I
    cannot tell" must never read as "we are there". A `template` passed in
    is the only one tried.
    """
    rows = min(int(MAKE_HONEY_BAND_ROWS), int(frame.shape[0]))
    band = (0, 0, int(frame.shape[1]), rows)
    if template is not None:
        return templates_mod.find(frame, template, threshold=threshold,
                                  region=band) is not None
    found = False
    full = _ui_template(MAKE_HONEY_TEMPLATE)
    if full is not None:
        found = templates_mod.find(frame, full, threshold=threshold,
                                   region=band) is not None
    empty = _ui_template(MAKE_HONEY_EMPTY_TEMPLATE)
    if not found and empty is not None:
        (ax, ay), (sx, sy) = MAKE_HONEY_EMPTY_AT, MAKE_HONEY_EMPTY_SLACK
        th, tw = empty.shape[:2]
        box = (max(0, ax - sx), max(0, ay - sy), tw + 2 * sx, th + 2 * sy)
        match = templates_mod.find(frame, empty, threshold=MAKE_HONEY_EMPTY_UNSURE,
                                   region=box)
        if match is not None:
            found = (float(match.score) >= MAKE_HONEY_EMPTY_THRESHOLD
                     or empty_bag_banner_says_so(frame))
    return found


def empty_bag_banner_says_so(frame, run=subprocess.run) -> bool:
    """The empty-bag banner's own words, "To Make Honey, Collect Pollen From
    Flower Fields", read in its band. See MAKE_HONEY_EMPTY_UNSURE."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return False
    h, w = frame.shape[:2]
    sx, sy = w / 1920.0, h / 1080.0
    x0, y0, x1, y1 = MAKE_HONEY_EMPTY_WORDS_BOX
    crop = frame[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx), :3]
    if crop.size == 0:
        return False
    grey = cv2.resize(cv2.cvtColor(np.ascontiguousarray(crop), cv2.COLOR_BGR2GRAY),
                      None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    ok, png = cv2.imencode(".png", grey)
    if not ok:
        return False
    try:
        out = run(["tesseract", "stdin", "stdout", "-l", "afr", "--psm", "6"],
                  input=png.tobytes(), capture_output=True, timeout=8.0)
    except (OSError, subprocess.SubprocessError):
        return False
    text = " ".join((out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes)
                     else str(out.stdout)).lower().split())
    return "make honey" in text and ("collect" in text or "flower" in text)


# THE RED CANNON'S PROMPT, READ CHEAPLY ENOUGH TO STOP A HELD KEY ON.
#
# `act/routes._cannon_approach` holds right from the hop's landing until the
# cannon's prompt shows, as Natro's `nm_gotoCannon` does (DESIGN 8dl), and
# the vision model's panel read is far too slow to end that hold. MEASURED in
# run-267.log: the hop-3 frame is 00:32:55 (attempt-267/003255-cannon-hop03),
# and the read that named the cannon ("I am at the red cannon") landed at
# 00:32:58 -- three seconds, which is 84 studs of a key held at 28 studs/s.
# This match costs 1.55-1.59 ms a look (MEASURED 2026-09-25, 500 calls of
# `red_cannon_prompt_score` on a decoded 1920x1080 frame, with and without
# the banner).
#
# The crop is `prompt_red_cannon.png` (data/templates/ui/README.md): the text
# box `vision.banner.find` returned, 283x58 at (853, 62), on
# var/routes/attempt-267/003300-natro_out_stump_via_red_cannon-03-cannon_approach-.jpg,
# the frame the model read as "fire the red cannon".
#
# THE GAP, MEASURED TWICE. First by the investigation (salvage/
# cannon_investigation.json, box (853, 62) +-(12, 14)): 108 of 5,756 saved
# frames scored 0.831-1.000, all cannon banners, and every other frame 0.429
# or less. Then again on 2026-09-25 with this function and this box, over
# 18,819 saved 1920x1080 frames -- all of var/routes (7,480), every other
# frame folder under var/ but incidents (3,060), one in forty of
# var/incidents (8,279); 4,830 files of other sizes skipped: 119 frames scored
# 0.829-1.000, and every one of the 119 is "Fire the Red Cannon", checked by
# eye on mosaics of the crops. The best of the other 18,700 scored 0.443 and
# 0.440, both "Talk to Black Bear" (incidents/002313-refused/100_t+09.8s.jpg,
# incidents/192746-refused/045_t+02.3s.jpg; Black Bear stands beside the
# cannon), then "Talk to Honey Bee" 0.429 (bears/honey_bee-051708.jpg) and
# "Talk to Polar Bear" 0.415. No frame scored between 0.443 and 0.829, and
# none came out NaN (an all-black or all-white frame scores 0.0). The
# threshold is the middle of that gap, (0.443 + 0.829) / 2 = 0.636, rounded
# up. The corpus is JPEG q70 and a live capture is not, so the approach logs
# the score it stopped on.
#
# THE BOX RUNS UP TO THE TOP OF THE FRAME because the banner slides in: five of
# the 119 caught it at y=16, 38 or 39 (attempt-270/003848, attempt-289/032108,
# frames2/175840) on its way to its resting y=62, so a frame caught mid-slide
# still counts. Across, every one of the 119 sat at x=853, so the column gets
# the make-honey banner's slack and no more. Natro looks for the same prompt
# in the top-centre 400x125 of the window (natro_macro.ahk:20392): this box's
# x 841-1148 is inside its 760-1160, and its y 0-134 is Natro's 125 rows and
# nine more, for the banner's lower slack.
RED_CANNON_TEMPLATE = "prompt_red_cannon.png"
RED_CANNON_THRESHOLD = 0.64
RED_CANNON_AT = (853, 62)
RED_CANNON_SLACK = (12, 14)           # px either side across; below the resting row


def _red_cannon_best(frame: np.ndarray | None,
                     template: np.ndarray | None):
    tpl = template if template is not None else _ui_template(RED_CANNON_TEMPLATE)
    if tpl is None or frame is None:
        return None
    (ax, ay), (sx, sy) = RED_CANNON_AT, RED_CANNON_SLACK
    th, tw = tpl.shape[:2]
    box = (max(0, ax - sx), 0, tw + 2 * sx, ay + sy + th)
    return templates_mod.find(frame, tpl, threshold=-1.0, region=box)


def red_cannon_prompt_score(frame: np.ndarray | None,
                            template: np.ndarray | None = None) -> float | None:
    """How well "Fire the Red Cannon" matches in its box right now, -1..1.

    None when there is no frame or no template, so a caller can tell "cannot
    look" from "looked and it is not there". The prompt is showing when the
    score is at least RED_CANNON_THRESHOLD; the score itself is returned so
    the approach can log how close a miss came.
    """
    match = _red_cannon_best(frame, template)
    return None if match is None else float(match.score)


def red_cannon_prompt_box(frame: np.ndarray | None,
                          template: np.ndarray | None = None):
    """Where "Fire the Red Cannon" is drawn, as a `templates.Match`, when it
    is showing (RED_CANNON_THRESHOLD); None otherwise.

    For the panel reader, when `vision.banner.find` misses the banner. It
    misses it over a blue background: MEASURED 2026-09-25, of the 119 saved
    frames this template scores 0.829-1.000 on, `banner.find` returns None on
    exactly four, and they are the four `natro_out_clover_via_red_cannon`
    frames taken right after the route's camera turn at the cannon
    (attempt-278/014836, -279/015310, -282/022409, -312/080144, scoring
    0.831-0.857), where the turn puts a wide patch of blue behind the
    banner. On the other 115 it returns the banner's own box, x 852-853,
    y 16-62, 282-284 wide by 58-62 tall -- the place this match finds it.
    """
    match = _red_cannon_best(frame, template)
    if match is None or match.score < RED_CANNON_THRESHOLD:
        return None
    return match
