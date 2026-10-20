"""Finding a mob by its health bar, because the mob itself is invisible to HSV.

WHY THIS IS THE BIGGEST THING IN THE PROJECT RIGHT NOW. The owner, watching a
live run: "i keep dying to the mantis since im walking in small radius so it
jumps on me and when i die i loose all pollen and go back to hive". Death
empties the backpack, so one Mantis costs an entire cycle's gathering -- more
than any routing or timing improvement can win back.

WHY NOT DETECT THE CREATURE. A Mantis is a dark green insect standing in dark
green pine trees, and the two HSV distributions overlap in all three channels.
What IS separable is its NAMEPLATE: a flat, unlit BillboardGui the game draws
without lighting, so its colours are constant.

WHAT THE FIRST VERSION GOT WRONG, and it is the reason this file was rewritten
on 2026-09-21. It looked for a flat green bar with a RED HEART to its left,
from four wiki screenshots of the PC client. This client draws no heart. It
draws white "HP: 26" INSIDE the bar. So the heart rule matched any small red
blob beside any flat green one -- and 57 "mob sightings" were saved over one
night, of which 7 in 8 checked by eye were floating "+N" damage numbers, the
hotbar, or a red token cube. It missed the Rhino Beetle standing in front of
the character in the same frame.

WHAT A NAMEPLATE ACTUALLY IS HERE, MEASURED on those saved frames:

    the bar body      HSV mode (64, 220, 232) -- a pure UI green
    grass, same frame S 85-132, V 87-134 -- far below it in both
    inside the bar    white text "HP: 26" covering 14% of it
    its shape         an axis-aligned rectangle, fill 0.92 of its box,
                      straight top and bottom edges, aspect 4-6
    below full health a dark-red remainder to the right of the green

And there are TWO kinds of plate with that green bar, and only one is a mob:

    "Rhino Beetle (Lvl 5)"  HP: 26        a mob        0.0% pink inside, all 14
    "Bloom (Lvl 1)"  488 / 500 + a flower  not a mob    2.2-4.8% pink, all 10

The pink is the flower icon the game draws in a Bloom's bar. That is the
whole discriminator, and on the 24 labelled bars it is exact.

A THIRD PLATE, A PLANTER'S, AND THE OWNER CAUGHT IT: planters were mistaken
for monsters, because a planter's green bar looks like a health bar
(2026-09-28). A planter draws the same UI-green bar with its OWN name and
growth inside it -- "Paper Planter (100.0%)" -- and nothing above it; a mob
has its name above the bar ("Ladybug (Lvl 2)") and a short "HP: 20" inside.
MEASURED 2026-09-28 on the bars `find_all` reported in 500 saved
mob-sighting windows (var/incidents, the last and middle frame of each), 193
bars, every one looked at: 15 planters, 178 mobs and Blooms.

    white across the bar's columns in the band above it   planters 0.0-0.54
      (LABEL_BAND bar heights, below the HUD pills)        mobs 0.83-1.0
    white text's width inside the bar                      planters 0.77-0.89
                                                           mobs mostly 0.32; up
                                                           to 0.98 where a big
                                                           HP number or an icon
                                                           overlaps it

Neither alone is safe -- a mob's HP can be "1,300,400,000", as wide as a
planter's name -- so a plate is a planter only when BOTH say so: no label
above AND wide text inside. 14 of the 15 planters, 0 of the 178 others. The
one missed sat under the buff icons, whose white reads as a label, and it
stays a mob: a planter taken for a mob costs a walk, a mob taken for a
planter can cost the backpack.

WHAT IT SCORES, on the saved windows (every 5th frame plus the last): 28 bars
in 13 windows, 12 checked by eye, 12 of 12 real nameplates. The zero-false-
positive measurement on the fixture screens (hive, shops, cannon, fields,
menus) is `tests/unit/test_nameplate.py`, and it is re-run on every change.

RECALL is still not a number. The beetle was found in six windows; how often it
is there and NOT found is unknown until the deaths stop coinciding with it.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# The bar body. MEASURED mode (64, 220, 232); the band is wide on hue because
# JPEG smears it, and tight on saturation and value because that is the gap
# between UI green and grass.
BAR_HUE = (45, 85)
BAR_MIN_SATURATION = 170
BAR_MIN_VALUE = 180

# Rows that are interface, not world.
WORLD_TOP = 100
WORLD_BOTTOM = 980
# ...and the outermost columns, which carry UI on this client.
WORLD_LEFT = 40
WORLD_RIGHT = 1880

# "HP: 26" splits the green into pieces; a horizontal close bridges the text.
# 61 px covers the widest text seen (a close beetle's "HP: 28" at 56 px tall).
BRIDGE_PX = 61

# The rectangle. MEASURED: close beetle 376x56, far one 66x14; fill 0.92.
MIN_H, MAX_H = 9, 70
MIN_W, MAX_W = 36, 420
MIN_ASPECT, MAX_ASPECT = 2.5, 9.5
MIN_FILL = 0.80          # of the bridged component within its own box
MIN_EDGE = 0.75          # top and bottom rows occupied: straight edges

# White text inside. MEASURED 14% on the real bar; a full-health bar with a
# short "HP: 100" reads lower, a Bloom's "1,069 / 1,130" higher.
WHITE_MIN_VALUE, WHITE_MAX_SATURATION = 200, 60
TEXT_MIN, TEXT_MAX = 0.03, 0.45

# The flower icon in a Bloom's bar. MEASURED 2.2-4.8% on Blooms, 0.0% on mobs.
PINK_HUE = (140, 175)
PINK_MIN_SATURATION, PINK_MIN_VALUE = 70, 120
BLOOM_MIN_PINK = 0.01

# A PLANTER'S PLATE (module docstring): no name label above, and its own text
# spanning most of the bar. The label is looked for in the LABEL_BAND bar
# heights above the bar, over the bar's columns, and never in the HUD pills'
# rows (vision/screenstate HONEY_REGION and POLLEN_REGION end at y 58), whose
# white text would read as a label for a plate just below them.
LABEL_BAND = 2.2
LABEL_BELOW_HUD = 60
LABEL_MIN_EXTENT = 0.6       # a mob's name spans 0.83-1.0 of its bar
PLANTER_MIN_TEXT_EXTENT = 0.6    # a planter's own name spans 0.77-0.89

# The dark-red remainder to the right of the green: missing health. Present
# on 9 of 14 mob bars (absent at full health), 0-1.5% on Blooms. Reported,
# not required.
TAIL_HUE_LOW, TAIL_HUE_HIGH = 10, 165
TAIL_MIN_SATURATION = 90
TAIL_VALUE = (40, 200)

# Kept for callers that pass it: nothing here reads it any more, because the
# row limits above are the measured ones and a `top` of 170 -- the old value
# -- would have cropped the beetle's own bar at y=186.
DEFAULT_TOP = WORLD_TOP


@dataclass(frozen=True)
class Nameplate:
    """One health bar on screen: where it is, and whose."""
    x: int
    y: int
    w: int
    h: int
    kind: str = "mob"            # "mob" | "bloom" | "planter"
    text: float = 0.0            # white fraction inside
    pink: float = 0.0            # pink fraction inside
    tail: float = 0.0            # dark-red fraction just to the right
    text_extent: float = 0.0     # the white text's width inside, of the bar's
    label: float = 0.0           # white's width in the band above, of the bar's

    @property
    def hostile(self) -> bool:
        return self.kind == "mob"

    @property
    def centre(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def aspect(self) -> float:
        return self.w / max(1, self.h)

    def describe(self) -> str:
        who = {"mob": "mob health bar", "bloom": "a Bloom's bar (not a mob)",
               "planter": "a planter's bar (not a mob)"}.get(self.kind, self.kind)
        hurt = f", {self.tail:.0%} depleted" if self.tail > 0.05 else ""
        return f"{who} {self.w}x{self.h} at {self.centre}{hurt}"


def _band(hsv, hue, smin, vmin, vmax=255):
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return (h >= hue[0]) & (h <= hue[1]) & (s >= smin) & (v >= vmin) & (v <= vmax)


def _tail(hsv):
    """The dark red of a bar's missing health (TAIL_*)."""
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return (((h <= TAIL_HUE_LOW) | (h >= TAIL_HUE_HIGH)) & (s >= TAIL_MIN_SATURATION)
            & (v >= TAIL_VALUE[0]) & (v <= TAIL_VALUE[1]))


def _extent(mask: np.ndarray, width: int) -> float:
    """How much of `width` the set columns of `mask` span, first to last."""
    if mask.size == 0:
        return 0.0
    cols = np.flatnonzero(mask.any(axis=0))
    return float(cols[-1] - cols[0] + 1) / max(1, width) if cols.size else 0.0


def find_all(frame: np.ndarray, top: int | None = None,
             world_top: int = WORLD_TOP) -> list[Nameplate]:
    """Every nameplate bar on screen, mob, Bloom and planter alike. Empty =
    none seen. `world_top` lowers the rows skipped as interface for a caller
    that has blanked the HUD itself (act/crab.bar: a boss's bar at y 14)."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    bgr = frame[:, :, :3]
    H, W = bgr.shape[:2]
    if H < world_top + MIN_H or W < WORLD_LEFT + MIN_W:
        return []
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    green = _band(hsv, BAR_HUE, BAR_MIN_SATURATION, BAR_MIN_VALUE).astype(np.uint8)
    green[:max(world_top, int(top or 0))] = 0
    green[WORLD_BOTTOM:] = 0
    green[:, :WORLD_LEFT] = 0
    green[:, WORLD_RIGHT:] = 0
    bridged = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((1, BRIDGE_PX), np.uint8))

    white = (hsv[:, :, 2] >= WHITE_MIN_VALUE) & (hsv[:, :, 1] <= WHITE_MAX_SATURATION)
    pink = _band(hsv, PINK_HUE, PINK_MIN_SATURATION, PINK_MIN_VALUE)
    tail = _tail(hsv)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(bridged, 8)
    found: list[Nameplate] = []
    for i in range(1, count):
        x, y, w, hh, area = (int(q) for q in stats[i][:5])
        if hh < MIN_H or hh > MAX_H or w < MIN_W or w > MAX_W:
            continue
        if not (MIN_ASPECT <= w / hh <= MAX_ASPECT):
            continue
        comp = labels[y:y + hh, x:x + w] == i
        if comp.mean() < MIN_FILL:
            continue
        if comp[0].mean() < MIN_EDGE or comp[-1].mean() < MIN_EDGE:
            continue
        inside_white = float(white[y:y + hh, x:x + w].mean())
        if not (TEXT_MIN <= inside_white <= TEXT_MAX):
            continue
        inside_pink = float(pink[y:y + hh, x:x + w].mean())
        right = tail[y:y + hh, x + w:min(W, x + w + w // 2)]
        tail_frac = float(right.mean()) if right.size else 0.0
        extent = _extent(white[y:y + hh, x:x + w], w)
        band_top = max(LABEL_BELOW_HUD, y - int(LABEL_BAND * hh))
        label = _extent(white[band_top:max(band_top, y - 1), x:x + w], w)
        if inside_pink >= BLOOM_MIN_PINK:
            kind = "bloom"
        elif label < LABEL_MIN_EXTENT and extent >= PLANTER_MIN_TEXT_EXTENT:
            kind = "planter"
        else:
            kind = "mob"
        found.append(Nameplate(x, y, w, hh, kind=kind, text=inside_white,
                               pink=inside_pink, tail=tail_frac,
                               text_extent=round(extent, 3), label=round(label, 3)))
    return found


# A HURT MOB'S WHOLE BAR, green AND dark red, for the Commando Chick's fight
# (run_farm fight_the_commando). WHY `find_all` MISSES IT: its rectangle is
# the GREEN alone, which shrinks with the mob's health, so a hurt enough bar
# fails MIN_W or MIN_ASPECT however plain it is. MEASURED 2026-10-13 13:53
# (var/commando/20261013-135246, 20 frames with the chick's bar): `find_all`
# saw it in 2, the two whose green was 0.34 and 0.41 of the bar, and in none
# of the 18 at 0.30 or under. The whole bar was 84x13 to 409x62; the end
# frame 0206.1-end-gone.jpg: bar 144x22 at (962, 307), green 33x22 (aspect 1.5 < 2.5, width 33 < 36), "HP: 5,812" in the red.
# Twelve 5 s strikes of "no bar" made that fight "gone" with the chick still
# a fifth alive (HP 13,434 on arrival, 5,812 at the end). The two-line name
# ("Commando Chick (Lvl 7) (HP / Saves)") is NOT the cause: the label band
# reads 0.76-1.0 on every one of those frames.
# HERE: green|dark-red is one mask, bridged as `find_all` does, each
# component's box trimmed to its longest run of rows, then columns, at least
# HURT_ROW_SHARE full (a mint gun barrel or a "-4" touching the bar widened
# 6 of the 20 boxes), then `find_all`'s own shape, fill, edge, text and
# label tests, and green at the LEFT end and red at the RIGHT end of it.
# MEASURED 2026-10-13 over 4,304 frames (3,000 sampled from var/incidents,
# all of var/frames2, var/commando, var/crab, var/beetle, var/bear, the test
# fixtures): 68 bars found, every one looked at, every one a real hurt bar
# (the chick's 20; Vicious Bee, Mantis, Werewolf, Spider, Mondo Chick...);
# their left-end green 0.78-1.0 and right-end red 0.85-1.0. A tilted red
# sign with a green stripe (incidents/20261012-175450-death/075_t+05.5s.jpg)
# reads 0.67 and 0.59 and is refused; a full Mantis bar beside an orange
# "+686" (20260927-042637-mob-sighting/149_t+10.8s.jpg) reads 0.60 red and
# is refused too, rightly: a full-health bar has no red end and `find` sees
# it. Use the two together. 13 ms a frame. NOT in the threat watch (yet):
# 5 of the 15 hurt bars in the sampled incidents were ones `find` missed,
# but a false walk-stop there was never measured against this.
HURT_ROW_SHARE = 0.5
HURT_MIN_END = 0.75          # left-end green and right-end red, of their columns


def _longest_run(flags) -> tuple[int, int]:
    """The longest run of True in a 1-D array as (start, stop); (0, 0) if none."""
    edges = np.flatnonzero(np.diff(np.concatenate(([0], np.asarray(flags, np.int8), [0]))))
    if edges.size == 0:
        return 0, 0
    k = int(np.argmax(edges[1::2] - edges[::2]))
    return int(edges[2 * k]), int(edges[2 * k + 1])


def hurt_bars(frame: np.ndarray) -> list[Nameplate]:
    """Every hurt mob's whole health bar (green on the left, dark red on the
    right, white text in it, a white name above), its box the whole bar and
    its `tail` the red share of it. Empty = none seen."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    hsv = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2HSV)
    green = _band(hsv, BAR_HUE, BAR_MIN_SATURATION, BAR_MIN_VALUE)
    red = _tail(hsv)
    white = (hsv[:, :, 2] >= WHITE_MIN_VALUE) & (hsv[:, :, 1] <= WHITE_MAX_SATURATION)
    bar = (green | red).astype(np.uint8)
    bar[:WORLD_TOP] = 0
    bar[WORLD_BOTTOM:] = 0
    bar[:, :WORLD_LEFT] = 0
    bar[:, WORLD_RIGHT:] = 0
    bridged = cv2.morphologyEx(bar, cv2.MORPH_CLOSE, np.ones((1, BRIDGE_PX), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(bridged, 8)
    found: list[Nameplate] = []
    for i in range(1, count):
        x, y, w, hh = (int(q) for q in stats[i][:4])
        if hh < MIN_H or w < MIN_W:
            continue
        comp = labels[y:y + hh, x:x + w] == i
        r0, r1 = _longest_run(comp.mean(axis=1) >= HURT_ROW_SHARE)
        if r1 - r0 < MIN_H:
            continue
        c0, c1 = _longest_run(comp[r0:r1].mean(axis=0) >= HURT_ROW_SHARE)
        x, y, w, hh = x + c0, y + r0, c1 - c0, r1 - r0
        if not (MIN_H <= hh <= MAX_H and MIN_W <= w <= MAX_W
                and MIN_ASPECT <= w / hh <= MAX_ASPECT):
            continue
        comp = labels[y:y + hh, x:x + w] == i
        if comp.mean() < MIN_FILL or comp[0].mean() < MIN_EDGE or comp[-1].mean() < MIN_EDGE:
            continue
        inside_white = float(white[y:y + hh, x:x + w].mean())
        if not (TEXT_MIN <= inside_white <= TEXT_MAX):
            continue
        end = max(2, w // 20)
        g, r = green[y:y + hh, x:x + w], red[y:y + hh, x:x + w]
        if g[:, :end].mean() < HURT_MIN_END or r[:, -end:].mean() < HURT_MIN_END:
            continue
        band_top = max(LABEL_BELOW_HUD, y - int(LABEL_BAND * hh))
        label = _extent(white[band_top:max(band_top, y - 1), x:x + w], w)
        if label < LABEL_MIN_EXTENT:
            continue
        found.append(Nameplate(x, y, w, hh, kind="mob", text=inside_white,
                               tail=float(r.mean()), label=round(label, 3),
                               text_extent=round(_extent(white[y:y + hh, x:x + w], w), 3)))
    return found


def find(frame: np.ndarray, top: int | None = None) -> list[Nameplate]:
    """Every MOB health bar on screen. Empty means "none seen", not "none there".

    Blooms and planters are dropped here on purpose: this is the function the
    threat watch calls, and a walk cut short beside a growing flower or a
    planter is a walk wasted.
    """
    return [p for p in find_all(frame, top=top) if p.hostile]


def present(frame: np.ndarray, top: int | None = None) -> bool:
    return bool(find(frame, top=top))


# A PLANTER'S BAR FROM AFAR, for the walk to it (run_farm seek_the_planter),
# never for the threat watch. MEASURED 2026-10-10 22:52 (var/planters/
# seek-20261010-225209-turn5.jpg, the owner pointed it out): the Blue Clay
# Planter's bar ~25 m off was 98x13 px, its green only an outline round DARK
# text ("Blue Clay Planter (100%)" drawn black at that size), so `find_all`'s
# fill and white-text tests both refused it. Here the bar's rows are closed
# vertically into a block and kept when the block is bar-shaped and holds
# dark text. A false find costs a walk that reads no "Harvest" prompt.
FAR_PLANTER_CLOSE = (13, 7)       # (rows, cols) closed: the outline into a block
FAR_PLANTER_H = (8, 22)
FAR_PLANTER_W = (50, 220)
FAR_PLANTER_ASPECT = (4.0, 13.0)
FAR_PLANTER_FILL = 0.75
FAR_PLANTER_DARK = (0.08, 0.6)    # share of the block darker than DARK_V
FAR_PLANTER_DARK_V = 100

# A GROWING PLANTER'S BAR IS PALE, and both passes above are blind to it.
# MEASURED 2026-10-13 21:29 (var/planters/seek-20261013-212933-turn0.jpg): the
# Blue Clay's "Blue Clay Planter (81.4%)" in plain view at x 25-370, y 544-592,
# and "no planter's bar was in view all the way round". Its fill reads HSV
# (53, 121, 213) (5-95%: H 52-55, S 92-130, V 198-218), its unfilled rest
# (51, 101, 119). NOT the white web washing it out: over the web's columns and
# over the black cave's it reads the same (53, 121, 213), and the far bar of
# turn6 (on a black wall) and turn7 (on grey) are as pale. It is the game's
# own colour for a planter still growing: the Paper at 51.3% (seek-20261012-
# 233557-turn0) reads (53, 111, 209) beside the Stump Snail's (66, 192, 208).
# Every bar found before was UI green (H 60-66, S 176-220, the 78 on
# var/planters), and every one of them that reads (25) reads "(100.0%)". So
# the seek, sent when the planner thinks a planter grown, saw only grown ones.
# HERE: the pale fill, bridged as `find_all` does, its box trimmed to the rows
# and then columns that are bar -- pale, white letter or dark letter edge --
# over PALE_ROW_SHARE (white flowers beside the bar widened 212933-turn1's
# 357x60 to 369x64), then `find_all`'s shape, edge and text tests, and no white
# in the top and bottom fifth (the letters sit in the middle; flowers do not).
# No label test: no mob's bar is pale, and the web above turn0 and the white
# flowers above turn1 read 1.0 as a label.
PALE_HUE = (50, 57)
PALE_SATURATION = (85, 145)
PALE_VALUE = (190, 230)
PALE_ROW_SHARE = 0.6
PALE_EDGE_ROWS = 2             # blurred rows at most trimmed off its top and bottom
PALE_MIN_ASPECT = 1.5          # the fill alone: a fifth grown is still found
PALE_MIN_FILL = 0.8            # the fill or a letter, of the box
PALE_MARGIN = 0.2              # the top and bottom fifth of its rows ...
PALE_MARGIN_WHITE = 0.1        # ... no row whiter than this
# ITS LETTERS ARE EDGED DARK (drawn dark when small); a white flower is not.
# MEASURED on the 29 pale bars found: dark (V < 100) 0.076-0.25 of the box;
# the two pale field strips with white flowers that passed every other test
# (routes attempt-540/090223-natro_home_pineapple-19-pause-.jpg, incidents
# 015453-mob-sighting/100_t+07.5s.jpg) 0.000.
PALE_MIN_DARK = 0.04


# A JUST-PLACED PLANTER'S BAR HAS NO FILL: "Blue Clay Planter (0.0%)" is all
# the unfilled colour. MEASURED 2026-10-22 on var/planters/place-*-unseen.jpg:
# 9 of 12 show a 0.0% bar (H 51, S 101, V 119 at its middle; 7 near, 533x74 at
# y 187, and 2 far, 132x19) and neither pass above saw one. Same tests as the
# pale fill (`_pale_planter_bars`), this colour instead. A bar part grown has
# this rest right of its fill; that rest is not a second bar (`_beside`).
# Look-only (AGENTS rule 4): the seek walks toward what it finds, so it is
# found only when ZERO_BAR_LIVE or asked (`find_planter_bars(zero=True)`).
ZERO_HUE = (48, 58)
ZERO_SATURATION = (70, 125)
ZERO_VALUE = (100, 140)
# STANDING ON IT, ZOOMED IN, it is bigger than any bar MAX_* was measured on
# (533x74 at 1920x1080, the 7 near ones above): up to this.
ZERO_MAX_W, ZERO_MAX_H = 560, 80
# ... and never under this wide. MEASURED 2026-10-22 (review): the smallest
# real 0.0% bars are 132x18; the one false box on 250 var/hotbar frames was a
# 55x10 green blob above the tiles (20261019-204257-stack2.jpg at 683, 957).
ZERO_MIN_W = 100
ZERO_BAR_LIVE = False


def _beside(box, boxes) -> bool:
    """`box` on the row of one of `boxes` and touching it (BRIDGE_PX)."""
    x, y, w, h = box
    return any(y < oy + oh and oy < y + h and x <= ox + ow + BRIDGE_PX
               and ox <= x + w + BRIDGE_PX for ox, oy, ow, oh in boxes)


def _pale_planter_bars(hsv, white, band=(PALE_HUE, PALE_SATURATION, PALE_VALUE),
                       most=(MAX_W, MAX_H)) -> list:
    """Every growing planter's pale bar (PALE_*) as (x, y, w, h): its fill
    only, the unfilled rest to its right not included. `band`: the colour
    (hue, saturation, value) of the bar's part looked for (ZERO_* the rest)."""
    (hue, sat, val), (max_w, max_h) = band, most
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    pale = ((h >= hue[0]) & (h <= hue[1]) & (s >= sat[0])
            & (s <= sat[1]) & (v >= val[0]) & (v <= val[1])).astype(np.uint8)
    pale[:WORLD_TOP] = 0
    pale[WORLD_BOTTOM:] = 0
    bridged = cv2.morphologyEx(pale, cv2.MORPH_CLOSE, np.ones((1, BRIDGE_PX), np.uint8))
    # THE BAR'S OWN PIXELS: the fill, or a letter -- greyer than the fill
    # (white, or blurred to grey: a far bar's small letters) or dark (their
    # edges). The fill alone covers 0.1 of a far bar's letter rows
    # (052624-turn6, 70x12), white and dark alone 0.49-0.54 (233557-turn1).
    inked = (bridged > 0) | (s < sat[0]) | (v < FAR_PLANTER_DARK_V)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(bridged, 8)
    found = []
    for i in range(1, count):
        x, y, w, hh = (int(q) for q in stats[i][:4])
        if hh < MIN_H or w < MIN_W:
            continue
        box = inked[y:y + hh, x:x + w]
        # one row short of it between two that are bar is bar too (a letter
        # row of 233557-turn5 read 0.59, one of 052624-turn6 0.47)
        rows = box.mean(axis=1) >= PALE_ROW_SHARE
        rows[1:-1] |= rows[:-2] & rows[2:]
        r0, r1 = _longest_run(rows)
        if r1 - r0 < MIN_H:
            continue
        c0, c1 = _longest_run(box[r0:r1].mean(axis=0) >= PALE_ROW_SHARE)
        if c1 - c0 < MIN_W:
            continue
        x, y, w, hh = x + c0, y + r0, c1 - c0, r1 - r0
        # A BLURRED EDGE ROW off the top or bottom: up to PALE_EDGE_ROWS of
        # them (233557-turn0's top row 0.21 of the fill, 212933-turn7's 0.01)
        share = (labels[y:y + hh, x:x + w] == i).mean(axis=1)
        top = next((k for k in range(PALE_EDGE_ROWS + 1) if share[k:k + 1].mean() >= MIN_EDGE), None)
        bot = next((k for k in range(PALE_EDGE_ROWS + 1)
                    if share[hh - 1 - k:hh - k].mean() >= MIN_EDGE), None)
        if top is None or bot is None:
            continue
        y, hh = y + top, hh - top - bot
        if not (MIN_H <= hh <= max_h and MIN_W <= w <= max_w
                and PALE_MIN_ASPECT <= w / hh <= MAX_ASPECT):
            continue
        if inked[y:y + hh, x:x + w].mean() < PALE_MIN_FILL:
            continue
        letters = white[y:y + hh, x:x + w]
        if not (TEXT_MIN <= letters.mean() <= TEXT_MAX
                and _extent(letters, w) >= PLANTER_MIN_TEXT_EXTENT
                and (v[y:y + hh, x:x + w] < FAR_PLANTER_DARK_V).mean() >= PALE_MIN_DARK):
            continue
        m = max(1, round(PALE_MARGIN * hh))
        rows = letters.mean(axis=1)
        if max(rows[:m].max(), rows[-m:].max()) > PALE_MARGIN_WHITE:
            continue
        found.append((x, y, w, hh))
    return found


def find_planter_bars(frame, zero: bool | None = None) -> list:
    """Every planter's bar on screen as (x, y, w, h): `find_all`'s planters,
    the far ones it cannot see (FAR_PLANTER_*), the pale ones of planters
    still growing (PALE_*, the fill only) and, if `zero` (ZERO_BAR_LIVE), the
    unfilled ones of planters just placed (ZERO_*)."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    plates = find_all(frame)
    out = [(p.x, p.y, p.w, p.h) for p in plates if p.kind == "planter"]
    hsv = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2HSV)
    green = _band(hsv, BAR_HUE, BAR_MIN_SATURATION, BAR_MIN_VALUE).astype(np.uint8)
    green[:WORLD_TOP] = 0
    green[WORLD_BOTTOM:] = 0
    rows, cols = FAR_PLANTER_CLOSE
    block = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((rows, cols), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(block, 8)
    dark = hsv[:, :, 2] < FAR_PLANTER_DARK_V
    # A MOB'S NAME ABOVE ITS BAR ("Spider (Lvl 4)" over "HP: 100", the one
    # false find in 600 route frames): the label test `find_all` uses
    white = (hsv[:, :, 2] >= WHITE_MIN_VALUE) & (hsv[:, :, 1] <= WHITE_MAX_SATURATION)
    for i in range(1, count):
        x, y, w, h = (int(q) for q in stats[i][:4])
        if not (FAR_PLANTER_H[0] <= h <= FAR_PLANTER_H[1]
                and FAR_PLANTER_W[0] <= w <= FAR_PLANTER_W[1]
                and FAR_PLANTER_ASPECT[0] <= w / h <= FAR_PLANTER_ASPECT[1]):
            continue
        comp = labels[y:y + h, x:x + w] == i
        if comp.mean() < FAR_PLANTER_FILL:
            continue
        share = float(dark[y:y + h, x:x + w][comp].mean())
        if not (FAR_PLANTER_DARK[0] <= share <= FAR_PLANTER_DARK[1]):
            continue
        band_top = max(LABEL_BELOW_HUD, y - int(LABEL_BAND * h))
        if _extent(white[band_top:max(band_top, y - 1), x:x + w], w) >= LABEL_MIN_EXTENT:
            continue
        if any(abs(x - ox) < w and abs(y - oy) < h for ox, oy, _w, _h in out):
            continue
        out.append((x, y, w, h))
    out += _pale_planter_bars(hsv, white)
    if ZERO_BAR_LIVE if zero is None else zero:
        # beside ANY plate is that plate's unfilled rest: a planter part
        # grown, or a mob's or Bloom's bar (the "Bloom (Lvl 1)" false find)
        seen = out + [(p.x, p.y, p.w, p.h) for p in plates]
        out += [b for b in _pale_planter_bars(hsv, white, (ZERO_HUE, ZERO_SATURATION, ZERO_VALUE),
                                            (ZERO_MAX_W, ZERO_MAX_H))
                if b[2] >= ZERO_MIN_W and not _beside(b, seen)]
    return out
