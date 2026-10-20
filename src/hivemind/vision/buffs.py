"""The buff bar: which buffs are up, and how many Haste stacks -- so a walk
can be timed at the speed the character actually has.

WHY. Every recorded route is a hold converted from studs at an assumed
walkspeed. Haste adds 10% movespeed per stack (Natro Macro's `Walk()`
formula, lib/Walk.ahk: `(1 + 0.1 * haste)`; this character MEASURED about
7%, HASTE_PER_STACK_MEASURED), so a character carrying six
stacks covers 60% more ground in the same hold and every leg overshoots --
the owner watched it ("on the field it was heavily to the right ... maybe
since it picked up a haste token"), data/knowledge/machines.yaml has recorded
it, and Natro's answer, reading the bar and rescaling, is the one built here.

WHAT THE BAR LOOKS LIKE, MEASURED 2026-09-22 on recorded frames at 1920x1080
(scripts/build_buff_templates.py has the frames and the labels):

    icons      38 px squares abutting from x = 0, rows 58..96, one per buff
    stack text white "xN" with a dark outline at the icon's bottom right;
               digits 12 px tall (rows 23..35 of the icon), the 'x' 9 px
    Haste      a grey running figure on a light grey square
    Melody     a black note on a white square (Natro tells them apart too)
    multiplier "x1.22"-style text on some icons uses a smaller font; not read

WHAT IT REFUSES TO GUESS. A digit with no template match makes the count
unreadable (None), never a nearest guess. Digits 0, 7 and 8 had no template
until 2026-09-27 (scripts/build_buff_templates.py LABELS), so every Haste of
x7, x8 or x10 read as unreadable and was walked as x1 -- in a third of the
saved frames the Haste icon carried such a count 41 times (22 x8, 15 x7, 4
x10) -- and an x8 could read as x3 (0.711 against the '3' template, over
DIGIT_MIN_SCORE). The log's "count unreadable" also covered a single stack,
which writes no count; `Haste.counted` tells them apart. SCANNED over a
third of the saved frames: with them, the 3,154 glyphs of those three shapes
read (the right digit 0.81-0.98, the next best at most 0.71), the 12 eights
that read as 3 read as 8, and no other glyph's reading changes. Coconut Haste,
Haste+, Oil and Smoothie -- the other terms in Natro's formula -- are not
read; the factor here is the Haste stacks and, since DESIGN 8dx, a bear morph
(`bear`, six of Natro's seven: the Gummy Bear morph has not been seen on
this account and has no template), and the result says so.
"""
from __future__ import annotations

import pathlib
import time
from dataclasses import dataclass, replace

import cv2
import numpy as np

BAR_TOP, BAR_BOTTOM = 58, 96
ICON = 38
MAX_SLOTS = 12
# The stack text lives in this band of the icon (rows 22..36, right of x=10);
# glyphs smaller than GLYPH_MIN_AREA are outline specks or the small-font
# multiplier's dots.
TEXT_ROWS = (22, 37)
TEXT_LEFT = 9
GLYPH_MIN_AREA = 8
# A stack digit is 12 px tall; the 'x' is 9. The small multiplier font is 6-8.
DIGIT_HEIGHT = (11, 13)
# Normalised cross-correlation below this and the slot is not that icon.
# MEASURED 2026-09-22 over six frames (two with Haste up, four without): the
# Haste template scores 0.83 and 1.00 on the Haste slot and at most 0.49 on
# any other slot or on scenery. 0.75 sits between with room either side.
ICON_MIN_SCORE = 0.75
# Digit masks compared as binary shapes resized to a common box; below this
# the digit is unreadable. MEASURED on the sixteen labelled glyphs: the right
# digit scores 0.78-1.00, the nearest wrong one 0.35-0.57.
DIGIT_MIN_SCORE = 0.70
DIGIT_BOX = (8, 12)
# Natro's formula: 10% per Haste stack.
HASTE_PER_STACK = 0.10
# THIS CHARACTER GETS ABOUT 7% A STACK. MEASURED 2026-10-14 (var/night/run-
# 600..992.log, every "hive_offset: met the ramp after N studs"): with the
# hive slot unknown the walk out holds d from the pad until the ground flow
# reads blocked at the ramp's wall -- one fixed distance, timed by the bot's
# own flow (N = seconds x the walkspeed assumed). Without a buff it takes a
# median 3.29 s (39 walks, sd 0.16 s; 3.36 s over 21 at walkspeed 28). Under
# Haste it is faster by far less than 1 + 0.1 n: 31 of 37 Haste walks were
# slower than Natro's formula. At walkspeed 32.2 (a 0.2 s detection lag
# allowed): x1 1.04x (15 walks), x2 1.09x (4), x3 1.19x (2), x5 1.27x, x6
# 1.37x, x8 1.64x, x8 + a bear 1.67x (one each) against 1.1-2.02x; one gain
# fitted over all 42 buffed walks is 6.5-7.2% a stack (lag 0-0.2 s). A bear
# morph alone came in at 1.11x (4 walks) against `Bear.factor`'s 1.12x: kept.
# So the 11:16 Blender walk ("haste x10 ... 2.25x in all") held every leg for
# 1/2.25 of its base time at about 1.9x: some 16% short. The incident rings'
# pixel flow (var/incidents, 908 since 10-09) was tried as well and cannot
# say: a same-incident, same-direction speed ratio scatters 35%.
HASTE_PER_STACK_MEASURED = 0.068
# Which gain `Haste.factor` uses: "off" Natro's, "on" the measured one, "ab"
# the measured one in even hours (HOME_UNSTICK's style); the buff bar line
# says when it is the measured one.
# ponytail: one linear gain, 7 of its walks above x3; refit from the same log
# line once more walks under x5+ have landed or missed.
# A/B FROM 2026-10-14 ~12:00 (the lead's call): the measured gain in even
# hours, Natro's 10% in odd ones -- read per the integration note (Haste x3+
# walks: errand prompt misses, off-path checks, "did not get there", obby deaths).
# ENDED 13:10, BACK TO NATRO'S: the frames refute 6.8% where it matters. All
# three x10 walks held at the measured 1.7x OVERSHOT (12:36 Bamboo home's d68
# pressed into Blue Flower's right wall, the HQ arch at 495 px against a
# no-Haste median ~1005; 12:00 and 12:41 Blender leg 3 past the farthest
# no-Haste end), while 10 x5-x10 walks at Natro's factor ended on target. The
# ramp timing above cannot tell a gain from a fixed delay: 10% with ~0.85 s
# of lag fits it as well as 6.8% with none.
HASTE_GAIN = "off"


def haste_per_stack() -> float:
    """HASTE_PER_STACK, or HASTE_PER_STACK_MEASURED as HASTE_GAIN says."""
    if HASTE_GAIN == "on" or (HASTE_GAIN == "ab" and time.localtime().tm_hour % 2 == 0):
        return HASTE_PER_STACK_MEASURED
    return HASTE_PER_STACK

# THE ICON EMPTIES FROM THE TOP AS THE BUFF RUNS DOWN (DESIGN 8dx). A buff's
# light square is its remaining time: it drains from the top, and the world
# shows through the emptied part, while the figure and the stack count stay
# drawn over it. `find` correlates the icon's TOP 22 rows -- the part that
# goes first -- so a Haste that has run a little while scores nothing, and
# every hold under it overshoots by 10% a stack. MEASURED 2026-09-26 over
# every saved route and homing frame (10,382 frames): `haste()` as it was
# saw the icon on 395 of them, every one with its square still full; with
# the rule below it sees those 395 and 1,568 more, and a random 96 of the
# 1,568, looked at by eye, are all the Haste icon (drained from a sliver to
# all but 7 rows, the count read wherever one is drawn). The walks that
# went wide are in it: natro_out_strawberry at 09:39:44 and 09:47:51 today
# (attempts 438, 440) ran the 270-stud diagonal for its full 9.8 s under a
# drained Haste, and so did 07:23:12 on the 24th (359, x5), its hive-offset
# leg with it -- 432 and 438 at 09:27:36, with none, stayed on the path, and
# 324, whose Haste was still full and read, held it 9.0 s and stayed on it
# too. Mushroom's walks home that stopped at a fence short of the hives
# carried one too (445 x1, 410 x2, 437 x3), and 446, with none, had a bear
# morph up (`bear`, below): between them, the rest of that fence (DESIGN 8dx).
#
# Natro reads it the same way round: DetectMovespeed looks for the light
# square's colour (0xf0f0f0) in the icon's LOWER rows, and so still finds a
# Haste that has half run out (lib/Walk.ahk).
#
# The rule, on the rows the template knows (it was itself cut from a
# slightly drained icon, so its top DRAIN_KNOWN_FROM rows are scene) and away
# from the stack count's corner (DRAIN_TEXT_BOX):
#   * the drain line is the highest row from which every row below still
#     shows the light square where the template has it (LIGHT_*, at least
#     LIGHT_ROW_SHARE of that row's square pixels); at least
#     DRAIN_MIN_LIGHT_ROWS such rows, or there is nothing left to read;
#   * over the rows below it, figure and square together, the normalised
#     correlation with the template is DRAIN_MIN_NCC or more -- or
#     DRAIN_WEAK_NCC and the figure's grey (FIGURE_*) is where the template
#     has it on DRAIN_WEAK_RECALL of its pixels. MEASURED on the same scan
#     (slots 0-7, looked at by eye in random draws of 48 a band): at 0.9 or
#     more, 96 of 96 are Haste; between 0.5 and 0.9 the eye icon, dark
#     scenery and a grey slab turn up beside drained Hastes, and the ones at
#     0.8 or more show 0.01-0.26 of the figure; the 48 that pass only by the
#     weaker test are all Haste, drained to its last 5-9 rows.
# What it still misses is a Haste in its last seconds: MEASURED over the same
# frames, it lets go of 157 of 254 at a drain line of 24-31, with 3.7-7.4 s
# of the buff left (DRAIN_ROWS_PER_S). HasteTracker holds the last reading
# until its drain line says the square is empty.
#
# THE DRAIN LINE IS A CLOCK. MEASURED 2026-09-26 over every saved route and
# homing frame, each timed by its file's mtime (the file name's own stamp on
# 8,835 of 8,946 route frames, a second later on the rest): over 174 runs of
# 3+ frames with the Haste read and its line moving down (3+ s, 4+ rows), the
# line falls a median 1.895 rows a second (IQR 1.846-1.932; 1.895 on the 138
# that span 10+ rows), so the 38 rows are 20 s. It says when the buff ends:
# on the 134 frames that follow a let-go, the line in the Haste's slot is
# within 3 rows of where that rate puts it on 131 (median +0.2 rows), and on
# eight runs looked at by eye the icon goes 2.5-4.6 s after a last read at
# row 30-32, each between the frames either side of (ICON - line) / rate.
# A line at DRAIN_KNOWN_FROM says 15.8 s, the least a square that full has.
#
# A TWO-DIGIT COUNT ("x10") STARTS FURTHER LEFT. Its 'x' and dark outline
# reach column 10, inside the columns DRAIN_TEXT_BOX keeps for the figure, so
# a drained x10 correlated 0.77 and was read as no Haste at all. MEASURED
# 2026-10-13 19:04:58 (var/routes/attempt-971/190458-to_the_blender-00-start
# .jpg): Haste x10 in slot 5, drain line 18 (about 10 s left), "no haste".
# The Blender's walk did not wait it out, held the 270-stud diagonal at base
# speed under 2.0x, and ended in the Blue Flower field ("leg 3: only 0% of
# the ground under us is the yellow path", 190512-...-03-walk-sa270.jpg).
# With the box from TEXT_LEFT the same three frames score 0.99. Widened for a
# two-digit count only: SCANNED over attempts 900-971 (11,591 frames), this
# box for EVERY icon gains 162 drained x10 reads but loses 112 single-digit
# and no-count ones; the two-digit rule (11,608, run again) gains the same
# 162 -- 32 drawn at random, all Haste x10 by eye -- and changes no other read.
DRAIN_ROWS_PER_S = 1.9
DRAIN_KNOWN_FROM = 8
DRAIN_TEXT_BOX = (22, 17)          # rows from, columns from: the count's corner
LIGHT_MAX_SAT, LIGHT_MIN_VAL = 45, 200
LIGHT_ROW_SHARE = 0.5
DRAIN_MIN_LIGHT_ROWS = 3
DRAIN_MIN_NCC = 0.9
DRAIN_WEAK_NCC, DRAIN_WEAK_RECALL = 0.8, 0.45
FIGURE_MAX_SAT, FIGURE_MAX_DIFF = 50, 45
# Only icons whose template has a light square and a grey figure on it.
DRAINED_ICONS = ("haste",)

TEMPLATES = pathlib.Path(__file__).resolve().parents[3] / "data/templates/buffs"

_cache: dict = {}


def _template(name: str, colour: bool = False):
    key = f"colour:{name}" if colour else name
    if key not in _cache:
        path = TEMPLATES / f"{name}.png"
        flag = cv2.IMREAD_COLOR if colour else cv2.IMREAD_GRAYSCALE
        img = cv2.imread(str(path), flag) if path.exists() else None
        _cache[key] = img
    return _cache[key]


def _digit_templates() -> dict[str, np.ndarray]:
    if "digits" not in _cache:
        found = {}
        for path in sorted((TEMPLATES / "digits").glob("*.png")):
            mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if mask is not None:
                found[path.stem] = cv2.resize(mask, DIGIT_BOX, interpolation=cv2.INTER_AREA)
        _cache["digits"] = found
    return _cache["digits"]


def slots(frame) -> list:
    """The bar's icon squares, left to right, MAX_SLOTS of them (empty slots
    are scenery; `find` tells them apart by template score)."""
    band = frame[BAR_TOP:BAR_BOTTOM, :, :3]
    return [band[:, i * ICON:(i + 1) * ICON] for i in range(MAX_SLOTS)
            if band.shape[1] >= (i + 1) * ICON]


def glyph_mask(icon) -> np.ndarray:
    """White text pixels in the icon (the stack count is white on anything)."""
    hsv = cv2.cvtColor(icon, cv2.COLOR_BGR2HSV)
    return ((hsv[..., 2] > 200) & (hsv[..., 1] < 60)).astype(np.uint8) * 255


def glyphs(icon) -> list[tuple[tuple[int, int, int, int], np.ndarray]]:
    """The digit glyphs of the stack count, left to right: each as its
    (x, y, w, h) box in icon coordinates and ITS OWN pixels as a binary mask.

    Its own pixels, not the box's: on the Haste icon the light-grey square
    itself passes the white test where JPEG has lifted it, and a box cut
    from the whole mask carries that background into the shape. MEASURED
    2026-09-22: an "x4" on a Haste icon scored under 0.7 from the box and
    0.9+ from the component. The 'x' (9 px tall, leftmost) is dropped; so is
    anything outside the digit band or not digit-height.
    """
    mask = glyph_mask(icon)
    top, bottom = TEXT_ROWS
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for k in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[k])
        if area < GLYPH_MIN_AREA or x < TEXT_LEFT or y < top or y + h > bottom:
            continue
        if not (DIGIT_HEIGHT[0] <= h <= DIGIT_HEIGHT[1]):
            continue                      # the 'x', a dot, an outline speck
        own = (labels[y:y + h, x:x + w] == k).astype(np.uint8) * 255
        out.append(((x, y, w, h), own))
    return sorted(out, key=lambda g: g[0])


def glyph_boxes(icon) -> list[tuple[int, int, int, int]]:
    """The boxes alone; see `glyphs`."""
    return [box for box, _ in glyphs(icon)]


def _shape_score(mask: np.ndarray, template: np.ndarray) -> float:
    a = cv2.resize(mask, DIGIT_BOX, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    b = template.astype(np.float32) / 255.0
    inter = float((a * b).sum())
    union = float(np.maximum(a, b).sum())
    return inter / union if union > 0 else 0.0


def stacks(icon) -> int | None:
    """The stack count written on the icon, or None when there is none to
    read or a digit is not one this has a template for."""
    found = glyphs(icon)
    if not found:
        return None
    templates = _digit_templates()
    if not templates:
        return None
    digits = ""
    for (x, y, w, h), glyph in found:
        # a '1' is 2 px wide against 7-8 for the rest: width is part of the shape
        best, score = None, 0.0
        for ch, tpl in templates.items():
            s = _shape_score(glyph, tpl)
            if ch == "1" and w > 4:
                s *= 0.5
            if ch != "1" and w <= 3:
                s *= 0.5
            if s > score:
                best, score = ch, s
        if best is None or score < DIGIT_MIN_SCORE:
            return None
        digits += best
    try:
        return int(digits)
    except ValueError:
        return None


@dataclass(frozen=True)
class Found:
    slot: int
    score: float


def _count_left(icon) -> int:
    """The first column of the count's corner: TEXT_LEFT for a two-digit
    count, else DRAIN_TEXT_BOX's (see A TWO-DIGIT COUNT above)."""
    return TEXT_LEFT if len(glyphs(icon)) >= 2 else DRAIN_TEXT_BOX[1]


def _drain_masks(name: str, left: int = DRAIN_TEXT_BOX[1]):
    """(template as float, figure mask, square mask) for a DRAINED_ICONS
    template, on the rows it knows and away from the count's corner, which
    starts at column `left`."""
    key = f"drain:{name}:{left}"
    if key not in _cache:
        tpl = _template(name)
        if tpl is None or tpl.shape != (ICON, ICON):
            _cache[key] = None
        else:
            t = tpl.astype(np.float32)
            rows = np.arange(ICON)[:, None] * np.ones((1, ICON))
            cols = np.ones((ICON, 1)) * np.arange(ICON)[None, :]
            text = (rows >= DRAIN_TEXT_BOX[0]) & (cols >= left)
            known = (rows >= DRAIN_KNOWN_FROM) & ~text
            # The last row and the first column carry the neighbours' colour
            # in a JPEG (measured: saturation 33-61 on a full square).
            figure = known & (t < 200) & (rows <= ICON - 4)
            square = known & (t >= 225) & (rows <= ICON - 2) & (cols >= 1)
            _cache[key] = (t, figure, square)
    return _cache[key]


def drain_line(icon, name: str = "haste") -> int | None:
    """The drain line of a DRAINED_ICONS slot: the highest row, from
    DRAIN_KNOWN_FROM down, from which every row below still shows the light
    square where the template has it (ICON when the bottom row does not).
    None without the template or a whole slot."""
    if icon is None or icon.shape[:2] != (ICON, ICON):
        return None
    masks = _drain_masks(name, _count_left(icon))
    if masks is None:
        return None
    square = masks[2]
    hsv = cv2.cvtColor(icon, cv2.COLOR_BGR2HSV)
    light = (hsv[..., 1] < LIGHT_MAX_SAT) & (hsv[..., 2] > LIGHT_MIN_VAL)
    line = ICON
    for r in range(ICON - 1, DRAIN_KNOWN_FROM - 1, -1):
        row = square[r]
        if not row.any():
            continue
        if float(light[r][row].mean()) < LIGHT_ROW_SHARE:
            break
        line = r
    return line


def drained_score(icon, name: str = "haste") -> float:
    """How well a slot matches `name`'s icon when its square may have
    drained from the top (see DRAIN_KNOWN_FROM): the correlation over the
    rows still full, when the rule passes, else 0.0."""
    line = drain_line(icon, name)
    if line is None:
        return 0.0
    t, figure, square = _drain_masks(name, _count_left(icon))
    hsv = cv2.cvtColor(icon, cv2.COLOR_BGR2HSV).astype(np.float32)
    gray = cv2.cvtColor(icon, cv2.COLOR_BGR2GRAY).astype(np.float32)
    full_rows = sum(1 for r in range(line, ICON) if square[r].any())
    if full_rows < DRAIN_MIN_LIGHT_ROWS:
        return 0.0
    below = (np.arange(ICON)[:, None] >= line) & (figure | square)
    a = gray[below] - gray[below].mean()
    b = t[below] - t[below].mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    ncc = float((a * b).sum() / denom) if denom > 0 else 0.0
    if ncc >= DRAIN_MIN_NCC:
        return ncc
    grey = (hsv[..., 1] < FIGURE_MAX_SAT) & (np.abs(gray - t) < FIGURE_MAX_DIFF)
    recall = float(grey[figure].mean()) if figure.any() else 0.0
    if ncc >= DRAIN_WEAK_NCC and recall >= DRAIN_WEAK_RECALL:
        return ncc
    return 0.0


def find(frame, name: str, min_score: float = ICON_MIN_SCORE) -> Found | None:
    """Which slot holds the named icon, by normalised correlation of the
    icon's upper part (above the stack text) against its template -- and,
    for an icon that drains (DRAINED_ICONS), of the part still full."""
    tpl = _template(name)
    if tpl is None:
        return None
    top = TEXT_ROWS[0]
    ref = tpl[:top, :].astype(np.float32)
    best: Found | None = None
    for i, icon in enumerate(slots(frame)):
        gray = cv2.cvtColor(icon, cv2.COLOR_BGR2GRAY)[:top, :].astype(np.float32)
        if gray.shape != ref.shape:
            continue
        a = gray - gray.mean()
        b = ref - ref.mean()
        denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
        score = float((a * b).sum() / denom) if denom > 0 else 0.0
        if score < min_score and name in DRAINED_ICONS:
            score = max(score, drained_score(icon, name))
        if score >= min_score and (best is None or score > best.score):
            best = Found(slot=i, score=score)
    return best


@dataclass(frozen=True)
class Haste:
    present: bool
    stacks: int | None            # None: absent, or present with no readable count
    score: float = 0.0
    # Seconds of the buff left by its drain line (DRAIN_ROWS_PER_S). None:
    # absent, or the line cannot be read -- MEASURED, the 4 of 1,963 read
    # frames with fewer than DRAIN_MIN_LIGHT_ROWS light rows are a full icon
    # under a red or yellow tint over the whole bar (attempts 344, 410, 412).
    remaining_s: float | None = None
    # Whether the icon carried any count glyphs at all. A single stack writes
    # none, so `stacks` None with `counted` False is x1 read, not a count
    # that could not be read; `describe` says which.
    counted: bool = False

    @property
    def factor(self) -> float:
        """Natro's `(1 + 0.1 * haste)`, or the measured gain (HASTE_GAIN). An
        unreadable count is treated as ONE stack -- the icon is there, so the
        character is at least that fast -- which is what Natro does too ("no
        multiplier, therefore 1x")."""
        if not self.present:
            return 1.0
        return 1.0 + haste_per_stack() * (self.stacks if self.stacks is not None else 1)

    def describe(self) -> str:
        if not self.present:
            return "no haste"
        count = (f"x{self.stacks}" if self.stacks is not None else
                 "count unreadable, taken as x1" if self.counted else
                 "no count on the icon, taken as x1")
        left = (f", about {self.remaining_s:.0f}s left" if self.remaining_s is not None
                else "")
        per = haste_per_stack()
        gain = ("" if per == HASTE_PER_STACK else
                f" at the measured {per:.1%} a stack")
        return (f"haste {count} (icon score {self.score:.2f}{left}) — walking "
                f"{self.factor:.1f}x{gain}")


class HasteTracker:
    """`haste()` with a short memory, because the icon FADES.

    MEASURED 2026-09-22 22:24 (run 246, frames 222403-222409): the Haste
    icon's template score climbed 0.43 -> 0.61 -> 0.76 -> 0.90 -> 0.97 and
    fell 0.80 -> 0.74 -> 0.66 -> 0.63 over six seconds while the buff was
    up at x3 -- the icon is drawn with a fade in and, near its end, a fade
    out (or a pulse), so a single read flips between "haste x3" and "no
    haste" from one second to the next. The runner divides holds by the
    factor, so a flicker is a leg walked at the wrong speed. A present
    reading is therefore held for `hold_seconds` through dips; a genuine end
    is caught that much later, which under-walks a leg briefly rather than
    over-walking it.

    Much of the slow fall is no fade (DESIGN 8dx): the square drains from
    the top as the buff runs down, which `find` now reads through
    (DRAIN_KNOWN_FROM) until its last 3.7-7.4 s. So a reading whose line
    was read is held for exactly as long as that line says is left
    (`remaining_s`, counting down), which MEASURED is when the icon goes
    (DRAIN_ROWS_PER_S). A fixed 2.5 s was short: of the 254 times the reader
    lost a Haste in the saved frames, the line said 3.2 s or more were left
    on 252 (median 6.3 s); the other 2 are the tinted frames. `hold_seconds`
    is kept for a reading whose line could not be read.
    """

    def __init__(self, hold_seconds: float = 2.5):
        self.hold_seconds = float(hold_seconds)
        self._last: Haste | None = None
        self._last_at: float = 0.0

    def _now(self, frame):
        return haste(frame)

    def read(self, frame, now: float | None = None) -> Haste:
        import time as _time
        now = _time.monotonic() if now is None else now
        current = self._now(frame)
        if current.present:
            self._last, self._last_at = current, now
            return current
        if self._last is not None:
            gone = now - self._last_at
            left = self._last.remaining_s
            if left is None and gone <= self.hold_seconds:
                return self._last
            if left is not None and left - gone > 0:
                return replace(self._last, remaining_s=left - gone)
        self._last = None
        return current


def haste(frame) -> Haste:
    """Is the Haste buff up, and with how many stacks? One read, no memory;
    see HasteTracker for the fade."""
    if frame is None:
        return Haste(present=False, stacks=None)
    hit = find(frame, "haste")
    if hit is None:
        return Haste(present=False, stacks=None)
    icon = slots(frame)[hit.slot]
    count = stacks(icon)
    line = drain_line(icon, "haste")
    rows_left = ICON - line if line is not None else 0
    return Haste(present=True, stacks=count if count is None or count >= 1 else None,
                 score=hit.score, counted=bool(glyphs(icon)),
                 remaining_s=(rows_left / DRAIN_ROWS_PER_S
                              if rows_left >= DRAIN_MIN_LIGHT_ROWS else None))


# THE BEAR MORPHS (DESIGN 8dx). The Bear Bee turns the character into a
# bear for a while, and Natro's formula adds four to the base movespeed for
# it: `(base_movespeed + ... + (bear ? 4 : 0))` (lib/Walk.ahk, which looks for
# any of seven morphs' icons, pBMBearBrown ... pBMBearMother). So at base 28 a
# morph is 14% more ground per second, and an unread one walks every leg
# that much long. MEASURED 2026-09-26: Mushroom's walks home that stopped at
# the white fence short of the hives walked their 46-stud sideways leg with a
# morph up on 407, 410 and 446 (by eye and by this reader), and none of the
# eight that landed did.
#
# WHAT IS READ. Four morphs have been seen on this account's bar, from
# attempt 362 on: brown, black, polar and panda. Each is the bear's face
# filling the square, so it is matched whole (colour, rows BEAR_ROWS,
# columns BEAR_COLS), and ALONG the bar rather than slot by slot, because the
# icons slide when one ahead of them expires: MEASURED, a slot-aligned match
# missed a bear mid-slide on 5 frames that the sliding one reads (attempts
# 364, 371 twice, 419, 438). The templates are each morph's undrained look
# (scripts/build_bear_templates.py: the per-pixel 90th percentile of every
# instance on attempts 362-419). MEASURED over every saved route and homing
# frame (10,804): the best match along the bar is 0.88 or more on 918 frames
# and at most 0.69 on every other; 96 drawn at random from the 918, looked at
# by eye, are all bear faces, and the 40 between 0.50 and the line are flat
# scenery (a yellow wall, a dark floor), parts of other icons, and one polar
# bear half drawn mid-slide (407 at 00:02:25, 0.53). Held out: the 1,405
# frames of attempts 420-450 read 0.88 or more on 197 -- 60 drawn, all bears
# -- and at most 0.61 on the rest. BEAR_MIN_SCORE sits in the gap.
#
# AND THE RARE TWO, from attempt 850 on (a gifted Bear Bee: Mother or Science,
# BSS wiki): the Science Bear (golden fur, grey goggles) and the Mother Bear
# (cream, pink cheeks), both matching Natro's pBMBearScience/pBMBearMother
# colours, were on the bar unread -- every old template scores at most 0.76 on
# them -- so a walk under one ran 14% long and `wait_out_the_morph` never
# waited (970 18:41, 975 20:39). Same method, attempts 840-959 (193 and 179
# instances). MEASURED 2026-10-14 over every saved frame (165,821): they win
# on 763 (science 0.86-1.00, mother 0.90-1.00; held out, attempts 960+,
# 0.94/0.95 and up); on the 16,462 frames an old kind reads they reach 0.75
# at most (a brown face; the old kind 0.13 or more ahead, never beaten); every
# other frame scoring 0.45 or more, looked at by eye, is a bear face caught
# popping in or mid-slide (6 of them a rare one, 0.56-0.69, unread as the old
# kinds' are). Their drained rows read 0.92/0.93 of the undrained look and
# fall 1.29/1.28 rows a second (32/26 runs), so BEAR_DRAINED and
# BEAR_DRAIN_ROWS_PER_S hold. NOT A BEAR: the cartoon puppy's head on a pale
# yellow square is Puppy Love (Puppy Bee's buff, the BEES' movespeed); it
# scores under 0.45 on every template and is rightly left out (994 12:41).
# Gummy has not been seen (no bar near Natro's pBMBearGummy) and is not read.
#
# AND FOR HOW LONG. A morph's square drains from the top like the Haste's,
# but the face is drawn over all of it, so the drained rows show as the face
# darkened: MEASURED, rows at 0.84-0.94 of the undrained look against
# 0.98-1.02 (brown and black the darkest, polar the least). The drain line is
# one past the lowest row under BEAR_DRAINED of the template's brightness,
# and it falls BEAR_DRAIN_ROWS_PER_S: over 62 runs of 3+ read frames (3+ s,
# 4+ rows, frames timed by mtime) the median is 1.28 rows a second (IQR
# 1.24-1.33; 1.29 on the 18 runs of 10+ frames), 1.29 on attempts 362-419
# and 1.26 on 420-450, held out; so a morph lasts about 30 s. It says when
# the icon goes: on 41 of the 43 times the reader lost a bear, the line's
# time left had run out by the next frame (within 1 s); the other two were
# an icon half drawn mid-slide (370, 407), which the tracker holds through.
# The reader holds on to the end: 24 of the 43 let-gos are at the last row.
BEAR_KINDS = ("brown", "black", "polar", "panda", "science", "mother")
BEAR_MOVESPEED = 4.0
BEAR_MIN_SCORE = 0.77
BEAR_ROWS, BEAR_COLS = (6, 37), (1, 37)
BEAR_DRAINED = 0.95
BEAR_DRAIN_ROWS_PER_S = 1.28


@dataclass(frozen=True)
class Bear:
    present: bool
    kind: str | None = None       # one of BEAR_KINDS
    score: float = 0.0
    # Seconds of the morph left by its drain line; None when absent.
    remaining_s: float | None = None

    def factor(self, walkspeed: float) -> float:
        """Natro's `(base_movespeed + (bear ? 4 : 0))` over the base: a morph
        adds BEAR_MOVESPEED to the walkspeed, not a share of it."""
        if not self.present:
            return 1.0
        base = max(1.0, float(walkspeed))
        return (base + BEAR_MOVESPEED) / base

    def describe(self) -> str:
        if not self.present:
            return "no bear morph"
        left = (f", about {self.remaining_s:.0f}s left" if self.remaining_s is not None
                else "")
        return (f"{self.kind} bear morph (icon score {self.score:.2f}{left}, "
                f"+{BEAR_MOVESPEED:g} movespeed)")


class BearTracker(HasteTracker):
    """`bear()` with the same memory as HasteTracker: a reading is held for
    as long as its drain line says, through a frame on which the bar is
    mid-slide."""

    def _now(self, frame):
        return bear(frame)


def bear_drain_line(icon, kind: str) -> int | None:
    """One past the lowest row (0..ICON-2) whose mean grey is under
    BEAR_DRAINED of the undrained template's; 0 for a full square. None
    without the template or a whole icon."""
    tpl = _template(f"bear_{kind}", colour=True)
    if tpl is None or icon is None or icon.shape[:2] != (ICON, ICON):
        return None
    grey = cv2.cvtColor(np.ascontiguousarray(icon[..., :3]), cv2.COLOR_BGR2GRAY)
    rows = grey.astype(np.float32)[:, 2:ICON - 2].mean(axis=1)
    ref = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY).astype(np.float32)[:, 2:ICON - 2].mean(axis=1)
    ratio = rows / np.maximum(ref, 1.0)
    low = [r for r in range(ICON - 1) if ratio[r] < BEAR_DRAINED]
    return (max(low) + 1) if low else 0


def bear(frame) -> Bear:
    """Is a bear morph up, which, and for how long? One read, no memory; see
    BearTracker."""
    if frame is None:
        return Bear(present=False)
    band = frame[BAR_TOP:BAR_BOTTOM, :ICON * MAX_SLOTS, :3]
    if band.shape[0] != ICON or band.shape[1] < ICON:
        return Bear(present=False)
    r0, r1 = BEAR_ROWS
    c0, c1 = BEAR_COLS
    strip = np.ascontiguousarray(band[r0:r1])
    best = None
    for kind in BEAR_KINDS:
        tpl = _template(f"bear_{kind}", colour=True)
        if tpl is None or tpl.shape[:2] != (ICON, ICON):
            continue
        res = cv2.matchTemplate(strip, np.ascontiguousarray(tpl[r0:r1, c0:c1]),
                                cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res[0], nan=0.0, posinf=0.0, neginf=0.0)
        x = int(np.argmax(res))
        if best is None or float(res[x]) > best[0]:
            best = (float(res[x]), kind, x - c0)
    if best is None or best[0] < BEAR_MIN_SCORE:
        return Bear(present=False)
    score, kind, left_x = best
    left_x = min(max(0, left_x), band.shape[1] - ICON)
    line = bear_drain_line(band[:, left_x:left_x + ICON], kind)
    return Bear(present=True, kind=kind, score=score,
                remaining_s=(ICON - line) / BEAR_DRAIN_ROWS_PER_S if line is not None
                else None)


def speed_changes(h: Haste, b: Bear, walkspeed: float) -> list[tuple[float, float]]:
    """How the movespeed factor `h.factor x b.factor(walkspeed)` changes as
    its buffs run out: (seconds from now, the factor from then on), soonest
    first. Each buff runs out on its own clock (`remaining_s`); one whose
    time cannot be read is taken to last."""
    parts = [(h.factor, h.remaining_s), (b.factor(walkspeed), b.remaining_s)]
    ends = sorted({left for f, left in parts if f != 1.0 and left is not None})
    out = []
    for at in ends:
        f = 1.0
        for factor, left in parts:
            if left is None or left > at:
                f *= factor
        out.append((at, f))
    return out
