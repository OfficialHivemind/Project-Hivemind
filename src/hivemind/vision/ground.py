"""What the player is STANDING ON, which is what tells you which field it is.

WHY THIS EXISTS, MEASURED. `brain/observe.signature` takes a hue/saturation
histogram of the WHOLE screen and calls it a place. Against the owner's first
real mapping session -- eight places, taught by walking to every field himself
-- that descriptor does not separate anything:

    worst correlation between two views of the SAME place : -0.042
    best  correlation between views of DIFFERENT places   : +0.803
    the threshold it was being used with                  : +0.450

The two distributions overlap completely, so NO threshold works. That is not a
tuning problem, it is the wrong measurement. It was calibrated on a handful of
frames where the camera happened to be pointed the same way, and what it really
encodes is where the camera is looking, not where the player is.

WHAT THE WHOLE SCREEN ACTUALLY CONTAINS. Looking at one real frame: the HUD, a
translucent blue ability bubble over a third of the view, six damage numbers,
token sparkles, the shop in the distance, two other fields visible past it, and
sky. Almost none of it is where he is standing.

WHAT IS STABLE. Every field in this game is a distinct ground texture -- red
strawberries on green, white mushrooms, blue flowers, bamboo, cactus on sand,
snow on Mountain Top. The ground immediately around the character barely
changes when the camera turns, because the camera orbits the character and
keeps them centred. So the ground is the identity and the horizon is the noise.

THIS FILE MAKES NO CLAIM THAT IT WORKS. `scripts/measure_ground.py` scores it
against labelled frames the same way the number above was produced, and the
band constants here are whatever that measurement chose. If it does not
separate, it does not ship; see docs/DESIGN.md.
"""
from __future__ import annotations

import cv2
import numpy as np

# The patch of screen taken to be ground, as fractions of the frame so it
# survives a resolution change. Chosen to sit below the horizon and clear of
# every HUD element: the hotbar (bottom centre), the reward feed (bottom
# right) and the buff tray (top left). MEASURED geometry on 1920x1080:
# feed pills start at x=1565, hotbar tiles at y=975.
BAND_TOP, BAND_BOTTOM = 0.57, 0.88
BAND_LEFT, BAND_RIGHT = 0.08, 0.78

# Hue x saturation, same idea as `observe.signature`, but of the ground only.
# More hue bins than that one because fields differ mostly in flower colour and
# 12 bins puts red strawberries and orange pumpkins in the same bucket.
HUE_BINS, SAT_BINS = 24, 6
PATCH = (192, 108)           # the descriptor never needs more detail than this

# Sprites -- damage numbers, sparkles, token glints -- are bright and unsaturated
# or pure white. Dropping them keeps a busy frame comparable with a quiet one.
GLARE_VALUE = 245
DIM_VALUE = 25


def band(frame: np.ndarray) -> tuple[int, int, int, int]:
    """The ground rectangle for this frame, as (x0, y0, x1, y1)."""
    h, w = frame.shape[:2]
    return (int(w * BAND_LEFT), int(h * BAND_TOP),
            int(w * BAND_RIGHT), int(h * BAND_BOTTOM))


def patch(frame: np.ndarray) -> np.ndarray:
    x0, y0, x1, y1 = band(frame)
    return frame[y0:y1, x0:x1, :3]


def signature(frame: np.ndarray) -> np.ndarray:
    """A colour signature of the ground under the player.

    Compared with `likeness`, which is the same correlation metric the rest of
    the project uses, so the two descriptors can be scored side by side.
    """
    ground = patch(frame)
    if ground.size == 0:
        return np.zeros(HUE_BINS * SAT_BINS, dtype="float32")
    small = cv2.resize(ground, PATCH, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    value = hsv[:, :, 2]
    keep = ((value < GLARE_VALUE) & (value > DIM_VALUE)).astype(np.uint8)
    hist = cv2.calcHist([hsv], [0, 1], keep, [HUE_BINS, SAT_BINS],
                        [0, 180, 0, 256])
    return cv2.normalize(hist, hist).flatten().astype("float32")


def likeness(a: np.ndarray, b: np.ndarray) -> float:
    """+1 identical, 0 unrelated. Same metric as `brain.observe.likeness`."""
    if a is None or b is None or a.shape != b.shape:
        return -1.0
    return float(cv2.compareHist(np.asarray(a, dtype="float32"),
                                 np.asarray(b, dtype="float32"),
                                 cv2.HISTCMP_CORREL))


# THE STUMP FIELD'S NORTH RIM, where natro_out_stump's step 18 ("d 96") leaves
# the camera facing Dapper Bear's hill: the grey stone of the hill fills the
# upper middle of the view. MEASURED 2026-10-14 on every frame of that spot
# (var/routes/attempt-676,991,992 *-natro_out_stump-19-walk-d96.jpg and the
# Dapper walks' "-arrived" frames, var/shoplook/20261013-233714 and
# 20261014-132643): 0.78-0.82 of STUMP_RIM_BAND is grey; the walk of 14:08
# (20261014-140829-dapper_bear_talk:82961-arrived.jpg) that drifted into a
# blue-and-green walled corner by the Blue Flower field read 0.00 -- and its
# climb and door legs then ran where they do not belong. STUMP_RIM_MIN_GREY
# is the middle of that gap.
STUMP_RIM_BAND = (0.08, 0.35, 0.30, 0.85)      # y0, y1, x0, x1 as shares of the frame
STUMP_RIM_GREY_S_MAX = 40
STUMP_RIM_GREY_V = (70, 190)
STUMP_RIM_MIN_GREY = 0.5


def stump_rim_grey(frame: np.ndarray) -> float:
    """The share of STUMP_RIM_BAND that is the hill's grey stone."""
    h, w = frame.shape[:2]
    y0, y1, x0, x1 = STUMP_RIM_BAND
    band = frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w), :3]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    return float(((hsv[:, :, 1] < STUMP_RIM_GREY_S_MAX)
                  & (hsv[:, :, 2] > STUMP_RIM_GREY_V[0])
                  & (hsv[:, :, 2] < STUMP_RIM_GREY_V[1])).mean())
