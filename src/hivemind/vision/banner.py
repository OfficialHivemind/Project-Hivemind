"""The game's top-centre notification panel, found by shape and colour.

WHY THIS IS THE UNBLOCKER

`act/hive.py` has refused to claim a hive since it was written, because it had
no way to tell an empty slot from a taken one and would not press a key on a
guess. The missing piece was assumed to be a "Claim Hive [C]" text prompt near
the bottom of the screen, which is where every search looked
(`diag_hive_slot.py`'s PROMPT_REGION is (560, 700, 800, 220)) and where nothing
was ever found.

That assumption was wrong twice over. RESEARCHED, 2026-09-20, and verified by a
second agent instructed to refute it: on tablet/iOS/Android the wiki documents
claiming a hive by "tapping the 'claim hive' button", and the claim affordance
is a large button at the TOP of the screen -- the `[C]`/`[E]` keyboard prompt is
the PC affordance. Sober runs the ANDROID build, so the mobile UI is the one on
screen. BeeTuxMacro's own probes agree and always did: its (638, 81) and
(719, 88) are at y~81-88 of a 768-high screen, i.e. the top, which scales to
y~114-124 in our 1920x1080 frames. The bottom-of-screen search was looking in
the wrong half of the picture the whole time.

WHAT IS MEASURED HERE

Across the twelve real frames in `tests/fixtures/screens/hive` -- six from the
slot sweep at 00:35 and six from the prompt run at 00:58 -- a panel matching
the rule below is present in exactly five and absent in exactly seven, with no
in-between case:

    slot_4, slot_3, slot_1, prompt_hop1, prompt_hop4   x=784 y=62 352x58
    the other seven                                     nothing

Every positive lands on the SAME pixel geometry, and its centre is x=960, which
is the exact horizontal centre of the frame. The text inside those five reads
"You've made 70,000,000 Honey" (figures here made up) -- identical in both
sessions 23 minutes apart, so it is a stored figure shown on join and NOT a live
conversion receipt (the honey HUD in the same frames read a different number).
This module therefore reports
that a panel is THERE. What it SAYS is a separate question for a text reader,
because the same container carries different messages.

THE DECOY IT REJECTS

A patch of blue sky through a window sits at x~1240-1256, y=0, about 190x130,
in frames with no panel at all. It is the same hue and a similar area, so
colour alone finds it. Two properties separate them and both are checked: the
panel is WIDE AND SHORT (aspect 6.1 against the sky patch's 1.4) and it is
CENTRED (within a few pixels of x=960, against the sky patch's ~1345). This is
the same discipline as `act/join.py`, where a blue game thumbnail is
button-shaped and is rejected on a property that actually differs.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import cv2

from .color import Band

# MEASURED on the five positives: H=105-112, S=175-210, V=225-245. The range is
# wider than that on purpose -- it has to survive the panel being drawn over
# grass, a wooden sign and a shop wall in those same five frames -- and it is
# the geometry below, not the colour, that does the discriminating.
PANEL_BLUE = Band("notification-blue", (100, 120, 120), (120, 255, 255))
# THE SAME PANEL TURNS RED WHEN THE THING IS ON COOLDOWN. MEASURED 2026-09-23
# 21:06:51 (`var/places/wealth_clock-210651.jpg`): the wealth clock recon
# arrived, the panel read "Use the Wealth Clock (57:22)" in a red box at the
# same place and size as the blue one, and this detector returned None -- so
# the recon reported "nothing on the panel" while standing at the thing it
# had walked 1,130 studs for. Over that box's saturated pixels: hue 0-2 and
# 178 (red straddles the hue wrap), saturation 150+, value 151+. The shape
# rules below are shared, and they are what keeps a red field or an attack
# disc from passing: a panel is wide, short and centred.
PANEL_RED = (Band("notification-red", (0, 120, 120), (8, 255, 255)),
             Band("notification-red-wrap", (172, 120, 120), (180, 255, 255)))
# AND RED NEEDS THE PANEL'S GEOMETRY TOO. SCANNED 2026-09-23 over 4,584 saved
# frames: the red rule alone found 16 panel-shaped blobs. Six were the panel,
# every one at exactly x=784 y=62 352x58 -- the same box the five blue
# positives measured in 2026-09-20. Ten were not: red flowers in the
# Strawberry Field at (785, 77, 312x73), (786, 58, 355x86), (768, 54,
# 326x58) and the like, and two attack discs filling the whole search band.
# Red is gated to the panel's measured box with slack.
PANEL_AT = (784, 62)
PANEL_SIZE = (352, 58)
RED_SLACK = (10, 12, 20, 20)     # x, y, w, h

# AND BLUE HAS A BOX OF ITS OWN NOW (audit 2026-09-26, senses F2). "The blue
# rule has never produced a false positive" stopped being true once the bot
# walked past blue skies and the Blue HQ: SCANNED 2026-09-26 over 2,101 saved
# frames (every fourth of var/routes, all of var/places and var/bears), it
# returned 137 boxes and 25 were not a panel -- 20 bands of sky or wall with
# their top edge at y=0 (up to 1920x220), the Blue HQ wall (581, 37, 682x183),
# a wall by the blueberry dispenser (735, 58, 553x162), blue hive cells
# (818, 171, 239x49) and the wall behind the strawberry dispenser twice
# (847, 96, 244x73; 762, 57, 368x99). read_panel crops what this returns, and
# a box from y=0 takes in the Honey and Pollen pills: the vision model then
# transcribed the HUD as a giver's prompt (run-318 18:17:07, run-354
# 05:39:10) and as a place's (run-343 00:06:05).
#
# Every real panel in the scan, one line or two, blue or red: top edge 51-77
# (the pills end above it), height 56-95, width 193-377, and white text over
# 0.079-0.240 of the box. The 25 above: top edge 0, 37, 96 or 171, or height
# 120-220, or width 473-1920 -- all but one; that one, 762, 57, 368x99, is
# inside every size and has white over 0.007 of it. Eight more boxes were
# real panels still sliding in (top edge 0-43, the pills inside them); those
# now wait for the next look.
PROMPT_TOP = (50, 80)
PROMPT_MAX_HEIGHT = 115
PROMPT_MAX_WIDTH = 420
PROMPT_MIN_WHITE = 0.06          # share of the box with V >= 200 and S <= 60
# THE TRANSLUCENT PANEL OFTEN COMES APART. Over the empty-bag pad it is drawn
# over the hive's own blue cells and the mask splits it into pieces, none
# panel-shaped on its own: of the 89 scanned frames the Make Honey template
# (screenstate.make_honey_present) confirmed, the old rule found the panel in
# 36. So when no single piece passes, the pieces lying inside the prompt's
# region are joined and the union is tested by every rule above: 82 of the
# 89, and 5 boxes on frames the template did not confirm -- each one a real
# "To Make Honey, Collect Pollen From Flower Fields" panel, looked at.
SPLIT_REGION = (760, 50, 1180, 150)   # x0, y0, x1, y1
SPLIT_MIN_AREA = 500
# AND A PANEL JOINED TO SOMETHING BLUE ABOVE OR BELOW IT IS CUT BACK TO ITS
# OWN ROWS. MEASURED 2026-09-27 11:09:47 (var/routes/attempt-493, `natro_out_
# strawberry_dispenser` leg 33): the route ended on the machine's pad under
# "Use the Strawberry Dispenser", and the light-blue post of the building
# behind the panel joined it in the mask -- one component, (853, 57, 282x163),
# too tall for a prompt -- so this found nothing, the errand read "no panel",
# the search walked off the pad and the route was booked as landing elsewhere.
# Across a row, the panel's own blue covers 0.93-1.00 of its width in the
# margins above and below the words (0.33-0.50 through them) and 0.61-0.64 on
# its anti-aliased edge rows; the post covers 0.13-0.15 and the hive cells
# under a Make Honey panel 0.02-0.21. So the rows from the first to the last
# solid one, plus their edge rows, are the panel, and every rule above is
# asked again of that box. SCANNED over the 19,163 saved frames: the cut finds
# a panel in 72 the rules alone did not, and every one is a real prompt.
TRIM_FULL_SHARE = 0.9
TRIM_EDGE_SHARE = 0.5
TRIM_MIN_HEIGHT = 50       # every real panel measured 56-95 tall

SEARCH_HEIGHT = 220        # the panel's bottom edge is y=120; this is generous
MIN_AREA = 4_000           # the five positives are 17,696-20,213
MIN_HEIGHT = 20
MIN_ASPECT = 3.0           # panel 6.1, sky-patch decoy 1.4
CENTRE_TOLERANCE = 60      # every positive centres on x=960 exactly


@dataclass(frozen=True)
class Panel:
    x: int
    y: int
    w: int
    h: int

    @property
    def centre(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        return frame[self.y:self.y + self.h, self.x:self.x + self.w]

    def describe(self) -> str:
        return f"notification panel {self.w}x{self.h} at ({self.x}, {self.y})"


def find(frame: np.ndarray) -> Panel | None:
    """The top-centre notification panel, or None.

    None means "no panel on screen", which is a fact about the screen and not
    about the world: it does NOT mean the character is not at a hive. Callers
    that need to know where they are must say so with a different observation.
    """
    if frame is None or frame.size == 0:
        return None
    band = frame[0:SEARCH_HEIGHT, :, :3]
    if band.size == 0:
        return None
    blue_mask = PANEL_BLUE.mask(band)
    blue = _panel_in(blue_mask, frame.shape[1], band)
    if blue is None:
        blue = _joined(blue_mask, frame.shape[1], band)
    if blue is None:
        blue = _trimmed(blue_mask, frame.shape[1], band)
    if blue is not None:
        return blue
    red = PANEL_RED[0].mask(band) | PANEL_RED[1].mask(band)
    found = _panel_in(red, frame.shape[1])
    return found if found is not None and _is_the_panels_box(found) else None


def _is_the_panels_box(panel: Panel) -> bool:
    """Within RED_SLACK of the box every real panel has measured in."""
    (ax, ay), (aw, ah) = PANEL_AT, PANEL_SIZE
    sx, sy, sw, sh = RED_SLACK
    return (abs(panel.x - ax) <= sx and abs(panel.y - ay) <= sy
            and abs(panel.w - aw) <= sw and abs(panel.h - ah) <= sh)


def _panel_in(mask: np.ndarray, frame_width: int,
              band: np.ndarray | None = None) -> Panel | None:
    """The largest panel-shaped component of `mask`, by the shared rules --
    and, given the `band` it was masked from, the prompt's own (blue)."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best: Panel | None = None
    best_area = 0
    for row in stats[1:count]:
        x, y, w, h, area = (int(v) for v in row[:5])
        if not _shaped(x, y, w, h, area, frame_width):
            continue
        if band is not None and not _prompt_like(band, x, y, w, h):
            continue
        if area > best_area:
            best, best_area = Panel(x, y, w, h), area
    return best


def _shaped(x: int, y: int, w: int, h: int, area: int, frame_width: int) -> bool:
    """The shared rules: big enough, wide and short, centred."""
    if area < MIN_AREA or h < MIN_HEIGHT:
        return False
    if w / max(1, h) < MIN_ASPECT:
        return False
    return abs((x + w / 2) - frame_width // 2) <= CENTRE_TOLERANCE


def _prompt_like(band: np.ndarray, x: int, y: int, w: int, h: int) -> bool:
    """Where a prompt sits, the size one is, and white words on it. See
    PROMPT_TOP."""
    if not (PROMPT_TOP[0] <= y <= PROMPT_TOP[1]):
        return False
    if h > PROMPT_MAX_HEIGHT or w > PROMPT_MAX_WIDTH:
        return False
    hsv = cv2.cvtColor(np.ascontiguousarray(band[y:y + h, x:x + w, :3]),
                       cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 2] >= 200) & (hsv[:, :, 1] <= 60)
    return float(white.mean()) >= PROMPT_MIN_WHITE


def _joined(mask: np.ndarray, frame_width: int,
            band: np.ndarray) -> Panel | None:
    """A panel the mask split into pieces, joined back. See SPLIT_REGION."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    x0, y0, x1, y1 = SPLIT_REGION
    parts = [tuple(int(v) for v in row[:5]) for row in stats[1:count]
             if int(row[4]) >= SPLIT_MIN_AREA
             and x0 <= int(row[0]) and int(row[0] + row[2]) <= x1
             and y0 <= int(row[1]) and int(row[1] + row[3]) <= y1]
    if len(parts) < 2:
        return None
    left = min(p[0] for p in parts)
    top = min(p[1] for p in parts)
    w = max(p[0] + p[2] for p in parts) - left
    h = max(p[1] + p[3] for p in parts) - top
    area = sum(p[4] for p in parts)
    if not _shaped(left, top, w, h, area, frame_width):
        return None
    if not _prompt_like(band, left, top, w, h):
        return None
    return Panel(left, top, w, h)


def _trimmed(mask: np.ndarray, frame_width: int,
             band: np.ndarray) -> Panel | None:
    """A panel joined to something blue above or below it, cut back to the
    rows between its solid margins. See TRIM_FULL_SHARE."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best: Panel | None = None
    best_area = 0
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i][:5])
        if area < MIN_AREA:
            continue
        mine = labels[y:y + h, x:x + w] == i
        share = mine.sum(axis=1) / float(w)
        solid = np.flatnonzero(share >= TRIM_FULL_SHARE)
        if solid.size == 0:
            continue
        top, bottom = int(solid[0]), int(solid[-1])
        while top > 0 and share[top - 1] >= TRIM_EDGE_SHARE:
            top -= 1
        while bottom < h - 1 and share[bottom + 1] >= TRIM_EDGE_SHARE:
            bottom += 1
        if top == 0 and bottom == h - 1:
            continue    # nothing to cut; the rules have already said no
        kept = mine[top:bottom + 1]
        cols = np.flatnonzero(kept.any(axis=0))
        px, py = x + int(cols[0]), y + top
        pw, ph = int(cols[-1] - cols[0]) + 1, bottom - top + 1
        kept_area = int(kept.sum())
        if ph < TRIM_MIN_HEIGHT:
            continue
        if not _shaped(px, py, pw, ph, kept_area, frame_width):
            continue
        if not _prompt_like(band, px, py, pw, ph):
            continue
        if kept_area > best_area:
            best, best_area = Panel(px, py, pw, ph), kept_area
    return best


def present(frame: np.ndarray) -> bool:
    return find(frame) is not None
