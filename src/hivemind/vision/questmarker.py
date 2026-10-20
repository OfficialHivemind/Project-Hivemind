"""The "!" that floats over a quest giver with a quest to give.

WHY. A giver's route can end a few studs short of the prompt with the giver in
plain sight: the Panda Bear's ends at the foot of his yellow platform, and
the marker over him is on screen at the route's end (var/bears/panda_bear-
look1-153722.jpg, (1019, 96); look8, (1802, 43)) while the ground-level search
walks the other way. Where the marker is says which way he is.

WHAT IT LOOKS LIKE, MEASURED 2026-10-01 on the 19 frames it is found in: an
orange bar over an orange dot, outlined dark -- hue 15-21 (OpenCV's 0-180,
5th-95th percentile), saturation 149-201, value 222-255; 13-25 px wide and
51-92 px tall (bar, gap and dot) at 1920x1080 near his platform. The yellow
round it is outside the hue band -- his platform's face hue 23-25 (value
117-203), the ground 25-26 -- and the bar must also be thin and tall, have
its dot below, wear its outline and stand alone: orange text (the Ant
Challenge meter's "8,000", damage numbers) has neighbours on its line, the
marker none.

HOW WELL, on the saved frames: 19 of the 458 in var/bears, every one a Panda
frame with the marker in view; none of 4,200 Pine Tree gathering frames
(today's 28 var/incidents/20261001-1*-mob-sighting, honey tokens and damage
numbers in them), 371 Ant Challenge frames or 534 route frames of
attempt-556; 2 of attempt-557's 1,163, the Panda route's last two, the
marker over him.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

FRAME_SIZE = (1920, 1080)
# Sizes are pixels of a 1920x1080 frame, the capture's own; the band scales.
# The band looked in: below the top HUD's rows, above the hotbar.
TOP, BOTTOM = 30, 960
# The marker's orange: a bright, saturated hue band (see the module note).
HUE = (12, 22)
MIN_SATURATION = 130
MIN_VALUE = 205
# The bar: thin and tall, mostly filled -- and up to the size a marker a few
# studs away is: MEASURED 2026-10-07 04:32 (var/shoplook/20261007-0432*-
# panda_bear_ladder_by_sight_2:248794-leg7-climb11/13), on the Panda's block
# his "!" was 35x95 and 48x126 (its dot 41x34), past the old 30x100, and the
# climb walked by him blind. The larger limits added only those close-ups
# (6 of 1,005 kept survey frames).
BAR_W = (5, 70)
BAR_H = (22, 200)
BAR_MIN_ASPECT = 2.2
BAR_MIN_FILL = 0.45
# The dot: about square, under the bar's middle, close below it.
DOT_SIDE = (4, 60)
DOT_ASPECT = (0.6, 1.6)
DOT_MIN_FILL = 0.5
DOT_MAX_GAP = 0.5           # of the bar's height
DOT_MAX_OFFSET = 0.6        # of the bar's width, at least 4 px
# The outline: a share of dark pixels in the ring round the bar.
OUTLINE_PAD = 3
OUTLINE_MAX_VALUE = 90
OUTLINE_MIN_SHARE = 0.08
# Alone on its line: orange beside it, within 1.5 bar heights either way,
# as a share of the bar's own box.
BESIDE_SPAN = 1.5
BESIDE_MAX = 0.25


@dataclass
class Marker:
    x: int            # the bar's centre, frame pixels
    y: int            # the bar's top
    w: int
    h: int            # bar, gap and dot
    outline: float
    beside: float

    def describe(self) -> str:
        return f"a quest marker at ({self.x}, {self.y}), {self.w}x{self.h} px"


def find(frame) -> list[Marker]:
    """Every quest marker on screen, left to right; [] when none."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    h, w = frame.shape[:2]
    sy = h / FRAME_SIZE[1]
    top, bottom = int(TOP * sy), int(BOTTOM * sy)
    roi = np.ascontiguousarray(frame[top:bottom, :, :3])
    if roi.size == 0:
        return []
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = ((hue >= HUE[0]) & (hue <= HUE[1]) & (sat >= MIN_SATURATION)
            & (val >= MIN_VALUE)).astype(np.uint8)
    count, _labels, stats, _centres = cv2.connectedComponentsWithStats(mask, 8)
    bars, dots = [], []
    for i in range(1, count):
        x, y, bw, bh, area = (int(v) for v in stats[i][:5])
        fill = area / float(bw * bh)
        if (BAR_W[0] <= bw <= BAR_W[1] and BAR_H[0] <= bh <= BAR_H[1]
                and bh / bw >= BAR_MIN_ASPECT and fill >= BAR_MIN_FILL):
            bars.append((x, y, bw, bh))
        elif (DOT_SIDE[0] <= bw <= DOT_SIDE[1] and DOT_SIDE[0] <= bh <= DOT_SIDE[1]
              and DOT_ASPECT[0] <= bh / bw <= DOT_ASPECT[1] and fill >= DOT_MIN_FILL):
            dots.append((x, y, bw, bh))
    found: list[Marker] = []
    for x, y, bw, bh in bars:
        cx = x + bw / 2.0
        for dx, dy, dw, dh in dots:
            gap = dy - (y + bh)
            if not (abs((dx + dw / 2.0) - cx) <= max(4.0, bw * DOT_MAX_OFFSET)
                    and 0 <= gap <= bh * DOT_MAX_GAP and dw <= bw * 1.6):
                continue
            ring = val[max(0, y - OUTLINE_PAD):y + bh + OUTLINE_PAD,
                       max(0, x - OUTLINE_PAD):x + bw + OUTLINE_PAD]
            outline = float((ring < OUTLINE_MAX_VALUE).mean()) if ring.size else 0.0
            span = int(BESIDE_SPAN * bh)
            x0, x1 = max(0, x - span), min(mask.shape[1], x + bw + span)
            band = mask[y:y + bh + gap + dh, x0:x1].astype(bool)
            band[:, (x - x0):(x - x0 + bw)] = False
            beside = float(band.sum()) / float(max(1, bw * bh))
            if outline >= OUTLINE_MIN_SHARE and beside <= BESIDE_MAX:
                found.append(Marker(x=x + bw // 2, y=y + top, w=bw,
                                    h=bh + gap + dh, outline=round(outline, 2),
                                    beside=round(beside, 2)))
            break
    return sorted(found, key=lambda m: m.x)


# A GIVER'S PAD: the white, blue-rimmed disc in front of a bear, the one place
# their "Talk to" prompt shows. MEASURED 2026-10-07 15:47 (var/shoplook/20261007-
# 15*-spirit_bear_survey_ramp_jump-leg2-mark*): steering at her "!" brought the
# character beside the Spirit Bear, at her pad's edge, with no prompt, and on
# past; her pad read 37,547 px of white at x 1254 (mark5), 70,951 (mark8) and
# 216,115 at x 1513 (mark9), against at most 3,735 in the field surveys' frames.
PAD_MIN_PX = 30_000
PAD_WHITE = 225              # each channel at least this
PAD_MAX_SPREAD = 25          # and this close to one another: white, not pale colour
PAD_BAND = (0.35, 0.88)      # of the frame's height: below the horizon, above the hotbar


def pad_x(frame):
    """The x of the largest white disc low in the view (a giver's pad), or
    None when there is none of PAD_MIN_PX."""
    if frame is None:
        return None
    h = frame.shape[0]
    px = frame[..., :3].astype(np.int16)
    lo, hi = px.min(axis=2), px.max(axis=2)
    mask = ((lo >= PAD_WHITE) & (hi - lo < PAD_MAX_SPREAD)).astype(np.uint8)
    mask[:int(h * PAD_BAND[0])] = 0
    mask[int(h * PAD_BAND[1]):] = 0
    n, _labels, stats, centres = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return None
    best = max(range(1, n), key=lambda i: stats[i, cv2.CC_STAT_AREA])
    if stats[best, cv2.CC_STAT_AREA] < PAD_MIN_PX:
        return None
    return int(centres[best][0])
