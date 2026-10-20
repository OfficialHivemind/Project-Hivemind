"""Reading HUD numbers by glyph template matching, not OCR.

Roblox draws the HUD in a fixed font at a fixed size. There are only ten digits,
a comma and a slash. Matching eleven small bitmaps is sub-millisecond and
essentially exact, where Tesseract costs 30-80 ms on the same strip and cheerfully
returns "1O0" for "100" on anti-aliased coloured text.

Glyph sizes differ per HUD element -- measured on a real frame, the Honey pill
draws digits at 15 px tall and the Pollen pill at 11 px -- so templates are
normalised to a common height before matching rather than assumed identical.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

NORM_H = 24          # every glyph is scaled to this height before comparison


@dataclass(frozen=True)
class Glyph:
    x: int; y: int; w: int; h: int
    image: np.ndarray          # binary mask of the glyph


# HUD text is WHITE. The backgrounds behind it are not, and that distinction
# is what this threshold is built on.
#
# MEASURED, 2026-09-20, on the first frame the bot ever earned anything in
# (`var/prove/end.png`, Pollen 103,439/688,050): a plain brightness threshold
# read it as "?03,439/688,050" -- the leading 1 lost. The pollen bar has a
# bright GREEN fill segment showing how full the backpack is, and at 15% full
# that segment sits directly under the first digits. Green is bright enough to
# pass a grey threshold, so the fill merged with the "1" into one blob, and a
# blob that wide is rejected as not-a-digit.
#
# The bar is only filled when pollen > 0, so this could not happen until the
# day the bot collected something. The reader worked perfectly for as long as
# it earned nothing.
#
# White has almost no saturation (MEASURED: S median 0 in the Pollen pill, 14
# in Honey) and the green fill has a great deal, so requiring LOW SATURATION as
# well as high value separates the text from any coloured background -- the
# green fill now, and whatever colour a future bar uses.
# MEASURED hue split on that same frame, and it is why the rule below excludes
# a COLOUR rather than excluding saturation in general:
#
#     Honey pill   gold digits   H 15-35, S median 127   (1,025 px)
#     Pollen pill  white digits  S median 0
#     Pollen bar   green fill    H 35-85, S median 168   (1,234 px)
#
# Honey's digits are gold, so a blanket "unsaturated only" rule erases them --
# it was tried, and it read Honey as the empty string. The fill is the only
# strongly-saturated GREEN in either pill, so that is what gets removed.
FILL_HUE_LOW, FILL_HUE_HIGH = 35, 85
FILL_SAT_MIN = 100


def binarise(roi: np.ndarray, thresh: int = 170) -> np.ndarray:
    """Bright pixels, minus the coloured progress fill behind the digits."""
    if roi.ndim != 3:
        return cv2.threshold(roi, thresh, 255, cv2.THRESH_BINARY)[1]
    bgr = roi[:, :, :3]
    # Brightness stays on the GREY conversion, not on HSV value. They are not
    # the same: V is max(B,G,R) and grey is a weighted sum, so V admits ~49
    # more anti-aliased edge pixels on gold text. Every digit template in
    # data/templates/digits was cut under the grey rule, and the fatter glyphs
    # that V produces correlate worse with them -- MEASURED: confidence on the
    # known 10,216,184 frame fell from 0.93 to 0.836, far enough to matter.
    # The green fill was the defect; the brightness basis was not.
    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, sat = hsv[:, :, 0], hsv[:, :, 1]
    bright = grey > thresh
    fill = ((hue >= FILL_HUE_LOW) & (hue < FILL_HUE_HIGH)
            & (sat >= FILL_SAT_MIN))
    return ((bright & ~fill).astype(np.uint8)) * 255


# Measured on a real 1920x1080 frame: Honey digits are 9-11 x 15 px with 72-97
# lit pixels; its comma is 4 x 7 with 19. The label text beside the value leaks a
# 3 x 4 speck of 8 pixels through the threshold, so MIN_H/MIN_AREA sit between
# the comma and that speck rather than at arbitrary round numbers.
MIN_H, MAX_H, MIN_W, MIN_AREA = 5, 30, 2, 12


# Adjacent glyphs can touch and become one connected component. MEASURED in the
# Pollen pill, where digits are 8 px wide: the leading "44" of 445,583 arrives as
# a single 18 px blob. A component this much wider than its neighbours is split
# into equal slices rather than dropped, because dropping it silently shortens
# the number -- 445,583 would read as 5,583.
SPLIT_RATIO = 1.6


def segment(roi: np.ndarray, thresh: int = 170,
            lost_commas: bool = True) -> list[Glyph]:
    """Split a HUD region into individual glyphs, left to right.

    `lost_commas=False` leaves out the commas the size filter dropped
    (`_lost_commas`): `screenstate.hud_present` measures glyph heights and
    was tuned on segmentation without them."""
    mask = binarise(roi, thresh)
    n, _lbl, stats, _c = cv2.connectedComponentsWithStats(mask, 8)
    kept: list[tuple[int, int, int, int]] = []
    small: list[tuple[int, int, int, int]] = []
    max_w = roi.shape[1] * 0.5
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        # reject the pill outline (spans the region) and label speckle
        if MIN_W <= w <= max_w and MIN_H <= h <= MAX_H and area >= MIN_AREA:
            kept.append((int(x), int(y), int(w), int(h)))
        elif w >= MIN_W and h >= 3 and area >= 4:
            small.append((int(x), int(y), int(w), int(h)))
    if not kept:
        return []
    kept.sort()

    # Judge "too wide" against the median width of the *digit-height* components
    # only. Punctuation would otherwise distort it in both directions: commas are
    # short and narrow, and the slash is TALLER than the digits (16 px against
    # 11 in the Pollen pill). Selecting by `max` height therefore picked the
    # slash alone as the reference and split every real digit in half -- 15
    # glyphs became 27. The median height is the digits, which is what we want.
    #
    # THE VALUE'S OWN GLYPHS set that size, not the rate suffix beside it
    # (VALUE_GAP: the same geometric cut `read` makes). MEASURED 2026-10-02 on
    # every Micro-Converter frame of the night: a short rate, "(+6,285/sec)",
    # renders in a BIGGER font than a long one, its parentheses 11 and 13 px
    # tall beside the value's 15; the median height of the whole pill fell to
    # 12, the "digit-height" set became those two parentheses, 2.5 px wide,
    # and every 10 px digit was cut in four -- Honey read as forty "?" in the
    # field and on the pad before each convert, whenever the honey rate was low.
    ref = _first_run(kept)
    if len(ref) < 3:
        ref = kept
    mid_h = float(np.median([h for _, _, _, h in ref]))
    widths = [w for _, _, w, h in ref if abs(h - mid_h) <= mid_h * 0.2]
    typical = float(np.median(widths)) if widths else float(np.median(
        [w for _, _, w, _ in ref]))

    out: list[Glyph] = [Glyph(x, y, w, h, mask[y:y + h, x:x + w].copy())
                        for x, y, w, h in (_lost_commas(kept, small, ref, mid_h)
                                           if lost_commas else ())]
    for x, y, w, h in kept:
        parts = int(round(w / typical)) if typical > 0 else 1
        if w < typical * SPLIT_RATIO or parts < 2:
            out.append(Glyph(x, y, w, h, mask[y:y + h, x:x + w].copy()))
            continue
        step = w / parts
        for k in range(parts):
            x0 = x + int(round(k * step))
            x1 = x + int(round((k + 1) * step))
            out.append(Glyph(x0, y, x1 - x0, h, mask[y:y + h, x0:x1].copy()))
    return sorted(out, key=lambda g: g.x)


# A COMMA THE SIZE FILTER DROPPED. MEASURED 2026-10-22 on the 10-digit honey
# font (12 px digits; var/routes/attempt-1154/104826-*-02-walk-d300.jpg and
# var/planters/seek-20261013-093245-push0.jpg): its commas are 4 x 6 with 11
# lit px, or 2 x 5 with 6, under MIN_AREA = 12 -- and the label speck MIN_AREA
# exists for is 3 x 4 with 8, so the area alone cannot tell them apart. Where
# they sit can: a comma hangs from the digits' baseline (top in the lower half
# of the digit band, bottom at or below the digits' bottom) with a digit 0-4 px
# either side; the speck sits mid-height beside the label, nowhere near a digit.
# Dropping the comma left a 9 px hole, over VALUE_GAP, and `leading_run` cut
# 1,234,567,890 to "1,234,567" -- a confident, 1000x wrong honey.
COMMA_TOUCH = 4


def _lost_commas(kept, small, ref, mid_h):
    """The `small` boxes shaped and placed like a comma between two digits."""
    band = [b for b in ref if abs(b[3] - mid_h) <= mid_h * 0.2]
    if not band or not small:
        return []
    top = float(np.median([y for _, y, _, _ in band]))
    bottom = float(np.median([y + h for _, y, _, h in band]))
    out = []
    for x, y, w, h in small:
        if h > mid_h * 0.6 or y < top + mid_h * 0.5 or y + h < bottom:
            continue
        # a slash's anti-aliased foot breaks off as a speck UNDER the slash
        # (MEASURED: "327,605/1955,877", incidents/235405-token/144_*)
        if any(kx < x + w and x < kx + kw for kx, _, kw, _ in kept):
            continue
        digit = [b for b in kept if abs(b[3] - mid_h) <= mid_h * 0.2]
        left = any(0 <= x - (kx + kw) <= COMMA_TOUCH for kx, _, kw, _ in digit)
        right = any(0 <= kx - (x + w) <= COMMA_TOUCH for kx, _, _, _ in digit)
        if left and right:
            out.append((x, y, w, h))
    return out


def _first_run(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """The first group of (x, y, w, h) boxes, sorted by x, cut at VALUE_GAP."""
    run = boxes[:1]
    for prev, this in zip(boxes, boxes[1:]):
        if this[0] - (prev[0] + prev[2]) > VALUE_GAP:
            break
        run.append(this)
    return run


# HOW FAR A TEMPLATE MAY SLIDE sideways over a glyph, in NORM_H pixels (one
# screen pixel at the 9 px Pollen font is 2.7 of them). Glyph and template were
# compared at ONE alignment, both left-justified. MEASURED 2026-10-26: one extra
# anti-aliased column on a glyph's left edge -- a JPEG chroma-smeared fill pixel
# under the leading "1" (golden/badge_menu_open-1026.jpg, a "1,0x4,xxx" count read
# "?,0?4,xxx", the 1 scored 0.40), or the soft rim of a "0" on the olive fill
# (routes/attempt-1201/152001-*-walk-w120.jpg, a "x,xxx,210/10,xxx,xxx" bag read
# "...21?/1?,..." at 0.40 and 0.47) -- shifted the whole glyph 2.7 px against
# its template, and a clean digit failed as "?".
# Only the ALIGNMENT slides; the compared window stays the whole glyph. A
# first try slid a narrow template freely inside a wide glyph and read the
# slash+2 blob of a "x,xxx,xxx/2,xxx,xxx" bag as a confident "7" (0.57,
# incidents/20260926-102314-mob-sighting/034_t+02.5s.jpg) where it had been "?".
# MEASURED over 4,923 HUD frames (routes 10xx-12xx, incidents): Pollen reads
# 275 more, Honey 11 more, no read lost, no value changed, every new pollen
# read within 0.03 of the bar; 34 vs 45 ms per honey+pollen pair.
SLACK = 3


def _normalise(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return np.zeros((NORM_H, NORM_H), np.uint8)
    scale = NORM_H / h
    return cv2.resize(img, (max(1, int(round(w * scale))), NORM_H),
                      interpolation=cv2.INTER_NEAREST)


class TemplateSet:
    """Labelled glyph bitmaps, persisted as PNGs so they can be eyeballed."""

    def __init__(self, templates: dict[str, list[np.ndarray]] | None = None):
        self.templates: dict[str, list[np.ndarray]] = templates or {}

    def add(self, char: str, glyph: np.ndarray) -> None:
        self.templates.setdefault(char, []).append(_normalise(glyph))

    @property
    def chars(self) -> list[str]:
        return sorted(self.templates)

    def classify(self, glyph: np.ndarray) -> tuple[str, float]:
        """Return (char, score). Score is normalised cross-correlation in [-1, 1]."""
        probe = _normalise(glyph)
        best, best_score = "?", -1.0
        for char, variants in self.templates.items():
            for t in variants:
                # pad both to one width (the narrower one's empty columns
                # still count against it), then let the template slide
                # SLACK either way; SLACK = 0 is the old single alignment
                w = max(probe.shape[1], t.shape[1])
                # (copyMakeBorder: np.pad cost 30 ms per honey+pollen pair)
                a = cv2.copyMakeBorder(probe, 0, 0, SLACK, SLACK + w - probe.shape[1],
                                       cv2.BORDER_CONSTANT, value=0)
                b = cv2.copyMakeBorder(t, 0, 0, 0, w - t.shape[1], cv2.BORDER_CONSTANT, value=0)
                score = float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED).max())
                if score > best_score:
                    best, best_score = char, score
        return best, best_score

    # ---- persistence ------------------------------------------------------
    def save(self, path: str | Path) -> None:
        path = Path(path); path.mkdir(parents=True, exist_ok=True)
        names = {",": "comma", "/": "slash", ".": "dot", "%": "percent"}
        index = {}
        for char, variants in self.templates.items():
            stem = names.get(char, char)
            for i, t in enumerate(variants):
                f = f"{stem}_{i}.png"
                cv2.imwrite(str(path / f), t)
                index[f] = char
        (path / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True))

    @classmethod
    def load(cls, path: str | Path) -> "TemplateSet":
        path = Path(path)
        index = json.loads((path / "index.json").read_text())
        ts = cls()
        for fname, char in index.items():
            img = cv2.imread(str(path / fname), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                ts.templates.setdefault(char, []).append(img)
        return ts


def read(roi: np.ndarray, templates: TemplateSet, min_score: float = 0.55,
         thresh: int = 170) -> tuple[str, float]:
    """Read a HUD region. Returns (text, lowest glyph confidence)."""
    glyphs = segment(roi, thresh)
    if not glyphs:
        return "", 0.0
    # Drop the rate suffix the HUD appends once the figure is moving. See
    # VALUE_GAP: the value's own glyphs sit 0-3 px apart and the suffix starts
    # 13-27 px later, so this is a geometric cut and not a guess about text.
    glyphs = leading_run(glyphs)
    commas = _comma_shaped(glyphs)
    chars, worst = [], 1.0
    for i, g in enumerate(glyphs):
        # A comma by shape is decided BEFORE the templates: MEASURED
        # 2026-10-22 (review), a comma `_lost_commas` put back classifies as
        # "2" with a high score ("589,037/82642,025"), and skipping the call
        # saves ~10 ms per honey+pollen pair (48.8 -> 38.7 ms).
        if i in commas:
            chars.append(",")
            continue
        c, score = templates.classify(g.image)
        chars.append(c if score >= min_score else "?")
        worst = min(worst, score)
    return "".join(chars), worst


# A COMMA BY ITS SHAPE when its template score is low. MEASURED 2026-10-22
# over 2,610 incident frames: 61 of the 81 failed Pollen reads were a comma
# alone, scored 0.49 against min_score 0.55 ("279?630/1130512",
# var/incidents/224713-mob-sighting/048_t+04.2s.jpg) -- it sits on the edge of
# the green fill, which eats its anti-aliased rim. Only a short, narrow glyph
# hanging from the baseline BETWEEN two glyphs qualifies, so a clipped digit
# (as tall as the band, or at the end of the run) still fails as "?"; and
# `to_int` rejects commas that are not in thousands groups.
def _comma_shaped(glyphs: list["Glyph"]) -> set[int]:
    tall = [g for g in glyphs if g.h > 0]
    if len(tall) < 3:
        return set()
    mid_h = float(np.median([g.h for g in tall]))
    band = [g for g in tall if abs(g.h - mid_h) <= mid_h * 0.2]
    if not band:
        return set()
    top = float(np.median([g.y for g in band]))
    bottom = float(np.median([g.y + g.h for g in band]))
    width = float(np.median([g.w for g in band]))
    def digit(g: "Glyph") -> bool:
        return abs(g.h - mid_h) <= mid_h * 0.2
    # MEASURED 2026-10-22: a speck beside the slash ("369,161/,1,130,512")
    # passed for a comma until both neighbours had to be digit-high.
    return {i for i, g in enumerate(glyphs[1:-1], 1)
            if g.h <= mid_h * 0.6 and g.w <= width * 0.6
            and g.y >= top + mid_h * 0.5 and g.y + g.h >= bottom
            and digit(glyphs[i - 1]) and digit(glyphs[i + 1])}


# MEASURED glyph gaps on the first earning frame, and this is what separates
# the value from the rate the HUD appends to it:
#
#     Honey   "16,201,128"      internal gaps 1-3 px,  then a gap of 27
#     Pollen  "103,439/688,050" internal gaps 0-2 px,  then a gap of 13
#
# The rate suffix -- "(+83/sec)", "(+780/sec)" -- only renders while the figure
# is MOVING, so it never appeared on a bot that collected nothing. Its
# parentheses are not in the template set, so it read as "??83?5???" and was
# concatenated onto the value, throwing away a reading whose digits were
# perfectly correct.
#
# A first attempt cut the string with a regex anchored at the start. That was
# WORSE and is recorded here so it is not tried again: when a comma failed to
# match, "16?201?128" trimmed to "16", turning 16 million into sixteen. A
# silently truncated number is the exact failure `to_int` refuses to produce.
# Splitting on the gap cannot do that -- an unreadable comma stays inside the
# run, so the reading fails as unreadable instead of shrinking.
VALUE_GAP = 8          # internal gaps reach 3; the suffix gap starts at 13


def leading_run(glyphs: list["Glyph"], gap: int | None = None) -> list["Glyph"]:
    """The first group of glyphs, cut where a wide gap starts the next one.

    The cut scales with the digits: 0.75 x their height, never under
    VALUE_GAP. MEASURED 2026-10-22: a comma the threshold loses leaves a hole
    of 0.6-0.75 digit heights (9 px at the 12 px 10-digit honey font, over
    VALUE_GAP 8, so "1,234,567,890" read 1,234,567); the gap before the rate
    suffix is 13 px at the 11 px Pollen font and 27 at 12-15 px Honey, but
    only 12-13 px at the 15 px Pollen font (review, 2026-10-22:
    var/incidents/20260928-205316-hud-hold, "0/2,962,170" read
    "0/2,962,170??18/????" at 0.9). ponytail: the window between the two is
    about 1 px at both ends; a font size outside 11-15 px needs remeasuring. A lost comma now stays inside the run and `to_int`'s group check
    fails the read, instead of the value shrinking."""
    if not glyphs:
        return []
    if gap is None:
        first = _first_run([(g.x, g.y, g.w, g.h) for g in glyphs])
        gap = max(VALUE_GAP, 0.75 * float(np.median([h for _, _, _, h in first])))
    run = [glyphs[0]]
    for prev, this in zip(glyphs, glyphs[1:]):
        if this.x - (prev.x + prev.w) > gap:
            break
        run.append(this)
    return run


_GROUPS = re.compile(r"\d{1,3}(,\d{3})+")


def to_int(text: str) -> int | None:
    """Parse a HUD number, or None if any glyph was not recognised.

    The None on "?" is the whole point. Stripping unknown glyphs instead would
    turn "445,3?2" into 44532 -- a number that is wrong by an order of magnitude
    and carries no sign of it. MEASURED: that is exactly what happened on a real
    frame whose Pollen was 445,372 while the glyph 7 had never been seen, and
    the backpack would have read as 7% full instead of 67%.

    A missing reading is recoverable: the caller looks again, or learns the
    glyph. A confidently wrong one is not.
    """
    if "?" in text:
        return None
    # Commas, when any were read, must be thousands groups. MEASURED
    # 2026-10-22 on the test account's routes attempts: reads shaped like "1,234,"
    # and "1,234567" were accepted and gave honey 1,234 and 1,234,567 against a
    # real 1.23 billion (figures made up, the shapes measured);
    # a comma lost or doubled means a glyph went missing or appeared, so the
    # number is not trusted. A read with no commas at all passes unchanged.
    if "," in text and not _GROUPS.fullmatch(text):
        return None
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None


def parse_fraction(text: str) -> tuple[int, int] | None:
    """'445,372/660,000' -> (445372, 660000)."""
    if "/" not in text:
        return None
    a, b = text.split("/", 1)
    ai, bi = to_int(a), to_int(b)
    return (ai, bi) if ai is not None and bi is not None else None
