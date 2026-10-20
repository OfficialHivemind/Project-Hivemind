"""The Panda Bear's ladder: dark log rungs up the face of his yellow block.

WHY. Five surveys pressed at it blind (run_farm PANDA_CLIMB*_LEGS) and none
climbed: the presses met it SIDE-ON -- the rungs' round ends face the camera
in var/shoplook/20261006-083434-panda_bear_ladder_climb-leg9-d.jpg -- while
the 03:09 look round from the nook saw it FACE-ON two camera taps right
(...-030951-panda_bear_ladder_survey-leg6-right.jpg, x 728-839). Where it is
on screen is what a walk into its face steers by.

WHAT IT LOOKS LIKE, MEASURED 2026-10-06 on that frame: log brown, hue 11-15
(OpenCV's 0-180), saturation 98-125, value 59-81 (to 105 in sun); rungs
about 30 px apart at ~25 studs, each a band of rows nine-tenths brown, with
two thin rails between them; and between the rungs the block's shaded face,
hue 24, saturation ~208, value 120-135. A ladder is a tall run of three or
more such bands with that yellow in the gaps: a fence or stairs has no yellow
behind it, a hive's comb no rungs, a brown mob neither.

HOW WELL, on the saved frames: the face-on view two taps right of the nook
and every look of the 23:07 walk in to its face (by_sight-leg6/leg7), none of
the side-on or close ones -- the one-tap view, at an angle, its rungs slanted
across a box wider than any, no longer since the band reaches up to 64;
8 of 661 other var/shoplook frames (machines and menus far from it).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

FRAME_SIZE = (1920, 1080)
# The band looked in: under the honey and pollen counters, above the hotbar.
# MEASURED 2026-10-06 23:07 (var/shoplook/20261006-2307*-panda_bear_ladder_by_
# sight-leg6-steer2): from 150 the ladder was lost as the walk in raised it to
# the frame's top (y 64-308); from 64 it is found there and on every push up to
# its face (climb0-4), and 8 of 661 other frames hit, against 6.
TOP, BOTTOM = 64, 930
# The logs' brown and the block's yellow (see the module note).
LOG_HUE, LOG_MIN_SATURATION, LOG_VALUE = (3, 22), 70, (25, 120)
FACE_HUE, FACE_MIN_SATURATION, FACE_MIN_VALUE = (20, 30), 150, 95
# Rungs and rails joined into one shape before it is judged.
JOIN = (9, 25)
# A ladder: at least this tall, taller than wide, with MIN_RUNGS rungs (rows
# at least RUNG_SHARE brown, two or more rows deep) and the face showing in
# the gaps (rows under GAP_SHARE brown) at FACE_IN_GAPS or more.
MIN_HEIGHT = 60
MIN_RUNGS = 3
RUNG_SHARE = 0.55
GAP_SHARE = 0.3
FACE_IN_GAPS = 0.35


@dataclass(frozen=True)
class Ladder:
    x: int          # its centre, frame pixels
    top: int
    bottom: int
    width: int


def _rungs(box) -> int:
    """Bands of rows mostly brown, each two or more rows deep."""
    on = box.mean(axis=1) >= RUNG_SHARE
    bands, run = 0, 0
    for row in on:
        if row:
            run += 1
            continue
        bands += run >= 2
        run = 0
    return bands + (run >= 2)


def find_ladder(frame) -> Ladder | None:
    """The biggest ladder in `frame`, or None."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[:, :, :3]), cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    logs = ((hue >= LOG_HUE[0]) & (hue <= LOG_HUE[1]) & (sat >= LOG_MIN_SATURATION)
            & (val >= LOG_VALUE[0]) & (val <= LOG_VALUE[1])).astype(np.uint8)
    face = ((hue >= FACE_HUE[0]) & (hue <= FACE_HUE[1]) & (sat >= FACE_MIN_SATURATION)
            & (val >= FACE_MIN_VALUE))
    scale = frame.shape[0] / FRAME_SIZE[1]
    logs[:int(TOP * scale)] = 0
    logs[int(BOTTOM * scale):] = 0
    joined = cv2.morphologyEx(logs, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, JOIN))
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(joined, 8)
    best, best_area = None, 0
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if h < MIN_HEIGHT * scale or h < 1.2 * w or w < 12 * scale:
            continue
        box = logs[y:y + h, x:x + w]
        if _rungs(box) < MIN_RUNGS:
            continue
        gaps = box.mean(axis=1) < GAP_SHARE
        if not gaps.any() or face[y:y + h, x:x + w][gaps].mean() < FACE_IN_GAPS:
            continue
        if area > best_area:
            best, best_area = Ladder(x=x + w // 2, top=y, bottom=y + h, width=w), area
    return best


def aim(spot: Ladder, frame_width: int, *, centre_px: int, ladder_studs: float,
        strafe_most: float, step_in: float, close_px: int):
    """The next move toward `spot`'s face, as (keys, studs): a strafe while
    it is more than `centre_px` off the frame's middle, sized by how many of
    its own widths (`ladder_studs` each) it is off, up to `strafe_most`; a
    step in when it is centred; None once it is `close_px` wide (at its foot)."""
    if spot.width >= close_px:
        return None
    off = spot.x - frame_width // 2
    if abs(off) <= centre_px:
        return "w", step_in
    studs = min(strafe_most, max(1.0, abs(off) / max(1, spot.width) * ladder_studs))
    return ("a" if off < 0 else "d"), round(studs, 1)


def climb_keys(mark_x, last_mark_x, spot, frame_width: int, *, mark_px: int,
               hold_px: int, centre_px: int, side_px: int | None = None):
    """The keys for one push up the ladder, and whether his "!" steered them:
    W, with A or D toward the "!" once it has held its place since the last
    push (within `hold_px`) -- MEASURED 2026-10-07 03:08, two pushes at the
    ladder's foot went W+A on a "!" no saved frame shows (a "+300" or a
    Bubble Mask bubble for one frame), while the real one held over three
    (23:46, x 1540, 1528, 1539) -- else toward the ladder while it is more
    than `centre_px` off the middle, else straight."""
    mid = frame_width // 2
    if mark_x is not None and last_mark_x is not None and abs(mark_x - last_mark_x) <= hold_px:
        off = mark_x - mid
        # (NO STRAFE ALONE: MEASURED 06:04 (run-715), with his "!" far AHEAD at x
        # 1405-1630 the D-only pushes walked the character into the wooden wall
        # beside the block's top; the 04:32 pass was the detector losing his close
        # "!", which its larger limits now keep -- `side_px`, None, is the switch)
        if side_px is not None and abs(off) > side_px:
            return ("a" if off < 0 else "d"), True
        return "w" + ("a" if off < -mark_px else "d" if off > mark_px else ""), True
    if spot is not None:
        off = spot.x - mid
        return "w" + ("a" if off < -centre_px else "d" if off > centre_px else ""), False
    return "w", False
