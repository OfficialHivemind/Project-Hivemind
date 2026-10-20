"""Noticing that the character is being attacked, from the red over the screen.

WHAT IT IS. When a mob has the character in range the game draws a large
translucent red disc over the world, centred near the player. It is the
loudest thing on the screen and it means one thing. The mob itself may be
half-hidden, its nameplate may be off the top of the frame, but the disc is
there, and it is there BEFORE the health bar starts falling.

MEASURED 2026-09-21 on the incident windows, taking the largest connected
red region of the world (HUD rows excluded) in the LAST frame of each:

    attacked   051548   302,518 px   18.8% of the world    one disc, 810x554
    attacked   023452   637,970 px   39.6%                 one disc, 1308x840
    attacked   223853   118,742 px    7.4%                 one disc, 588x447
    normal     000336     7,697 px    0.5%                 a red token cube
    median over all 63 windows: 1.0% red in the centre crop

The gap between "the biggest red thing is a cube" and "the biggest red thing
is a disc over the player" is more than an order of magnitude, so the
threshold sits comfortably inside it. One connected region, not a fraction of
red pixels: the Rose Field is red flowers, many small blobs, and the Pepper
Patch is worse. Neither has been measured here, which is why the rule is
"one large region that contains the centre" and not "a lot of red".

WHAT IT IS FOR. `brain/threat.ThreatWatch` cuts a held walk short when it
sees a mob, so the character leaves where the lunge was aimed. Its only eye
so far was the nameplate reader, which on this client fired 7 times in 8 at
floating damage numbers and missed the beetle standing in front of it. This
is the second eye, and it looks at the thing that cannot be mistaken for
text.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# The world: below the HUD pills, above the hotbar. Same rows the nameplate
# and token detectors use.
WORLD_TOP = 100
WORLD_BOTTOM = 980

# Red in OpenCV's 0..179 hue, which wraps: both ends of the circle.
RED_LOW = 8
RED_HIGH = 170
MIN_SATURATION = 60
MIN_VALUE = 120

# The largest red region must cover at least this share of the world to be
# the disc. MEASURED: discs 7.4-39.6%, the biggest non-disc red thing 0.5%.
MIN_DISC_FRACTION = 0.04

# ...and its bounding box must contain the screen centre, because the disc is
# drawn around the player and a red thing elsewhere is a red thing elsewhere.
CENTRE = (0.5, 0.55)


@dataclass(frozen=True)
class Hurt:
    """The attack disc, where it is, and how much of the world it covers."""
    x: int
    y: int
    w: int
    h: int
    fraction: float

    def describe(self) -> str:
        return (f"a red attack disc {self.w}x{self.h} covering "
                f"{self.fraction:.0%} of the world")


def find(frame: np.ndarray) -> Hurt | None:
    """The attack disc if it is on screen, else None."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    world = frame[WORLD_TOP:WORLD_BOTTOM, :, :3]
    if world.size == 0:
        return None
    hsv = cv2.cvtColor(world, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    red = (((h <= RED_LOW) | (h >= RED_HIGH)) & (s > MIN_SATURATION)
           & (v > MIN_VALUE)).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(red, 8)
    if count < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, hh, area = (int(q) for q in stats[i][:5])
    fraction = area / float(world.shape[0] * world.shape[1])
    if fraction < MIN_DISC_FRACTION:
        return None
    cx, cy = frame.shape[1] * CENTRE[0], frame.shape[0] * CENTRE[1] - WORLD_TOP
    if not (x <= cx <= x + w and y <= cy <= y + hh):
        return None
    return Hurt(x=x, y=y + WORLD_TOP, w=w, h=hh, fraction=fraction)


def attacked(frame: np.ndarray) -> bool:
    return find(frame) is not None


# ---- the character's own health bar ------------------------------------------
#
# WHAT IT IS. Roblox draws the player's health as a rounded bar at the top
# right, only while the character is hurt: full health shows nothing. The fill
# is green, then yellow, orange and red as it falls, over a translucent grey
# track with a dark outline. docs/GAPS.md 5 said "nothing reads the player's
# own health, so combat.retreat_health cannot work"; this is that reader.
#
# MEASURED 2026-09-25 on the saved windows (scratchpad bugrun/hp_eval.py, all
# 1920x1080 JPEGs):
#
#     outline        x 1780-1903, y 24-43; the track inside x 1783-1900,
#                    y 27-40, read on its middle rows y 30-37
#     drawn          the middle rows brighter than the outline's rows above
#                    (y 23-27) and below (y 40-44) by more than 25 in value,
#                    in at least 90% of the columns: 0.94-1.00 when a bar is
#                    there, at most 0.25 (top) and 0.59 (bottom) on all 37
#                    fixture screens (tests/fixtures/screens)
#     fill           saturation and value both >= 150 at its left end
#                    (yellow H 22-30 S 245 V 236; green H 58-70 S 155-229;
#                    red H 4-7 S 255); the track under the brightest red
#                    attack tint read S 147-156 at V 140-146, under the gate
#     how far it goes  columns that stay within 12 of the fill's hue, 60 of
#                    its saturation and 50 of its value, from the left
#
# Checked by eye on a 48-crop sheet (bugrun/hp_sheet.jpg): every reading
# matched the bar drawn, including red stubs of 3% and empty tracks read 0.
# Over the 18 death windows the series fall to 0 before the deaths (063652:
# 0.54 -> 0.0; 154239: 0.46 -> 0.0; 20260924-041618: 0.32 -> 0.0) and rise
# about 1% a second after them (055153: 0.37 -> 0.49 in ~11 s, the game's
# regeneration). On 1,815 frames of recent mob-sighting windows it found a
# bar 15 times; nothing on any fixture.
HP_BOX = (1770, 18, 1912, 50)              # x0, y0, x1, y1 of the crop read
HP_TRACK = (1783, 1900)                    # the fill's first and last column
HP_EDGE_ROWS = ((23, 28), (40, 45))        # outline rows above and below
HP_MID_ROWS = (30, 38)
HP_EDGE_COLUMNS = (1786, 1897)
HP_EDGE_CONTRAST = 25
HP_EDGE_SHARE = 0.9
HP_FILL_MIN = 150                          # saturation and value
HP_FILL_TOLERANCE = (12, 60, 50)           # hue, saturation, value
HP_FRAME = (1080, 1920)                    # measured at this size only


def own_health(frame: np.ndarray) -> float | None:
    """The character's health, 0..1, or None when no bar is drawn.

    None means full health or a frame this cannot read (another size, a
    menu over the corner) -- never "dead". 0.0 is a drawn, empty bar.
    """
    if frame is None or getattr(frame, "shape", None) is None:
        return None
    if tuple(frame.shape[:2]) != HP_FRAME:
        return None
    x0, y0, x1, y1 = HP_BOX
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1, :3], cv2.COLOR_BGR2HSV).astype(np.int32)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    cols = np.arange(HP_EDGE_COLUMNS[0] - x0, HP_EDGE_COLUMNS[1] - x0)
    (t0, t1), (b0, b1) = HP_EDGE_ROWS
    m0, m1 = HP_MID_ROWS[0] - y0, HP_MID_ROWS[1] - y0
    mid = np.median(val[m0:m1, cols], axis=0)
    top = val[t0 - y0:t1 - y0, cols].min(axis=0)
    bottom = val[b0 - y0:b1 - y0, cols].min(axis=0)
    if (np.mean(mid - top > HP_EDGE_CONTRAST) < HP_EDGE_SHARE
            or np.mean(mid - bottom > HP_EDGE_CONTRAST) < HP_EDGE_SHARE):
        return None
    track = np.arange(HP_TRACK[0] - x0, HP_TRACK[1] - x0)
    h = np.median(hue[m0:m1, track], axis=0)
    s = np.median(sat[m0:m1, track], axis=0)
    v = np.median(val[m0:m1, track], axis=0)
    rh, rs, rv = np.median(h[:4]), np.median(s[:4]), np.median(v[:4])
    if rs < HP_FILL_MIN or rv < HP_FILL_MIN:
        return 0.0
    dh_max, ds_max, dv_max = HP_FILL_TOLERANCE
    end = 0
    for i in range(len(track)):
        dh = abs(float(h[i]) - rh)
        dh = min(dh, 180.0 - dh)
        if dh <= dh_max and abs(float(s[i]) - rs) <= ds_max \
                and abs(float(v[i]) - rv) <= dv_max:
            end = i + 1
        else:
            break
    return end / float(len(track))
