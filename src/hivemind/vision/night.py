"""Night or day, read off the floor in front of the hive.

WHY IT EXISTS. The Vicious Bee hunts only at night (wiki Rogue_Vicious_Bee:
"a high chance to spawn when it turns nighttime"), and data/knowledge/
playbook.yaml `night_vicious_bee` listed "telling night from day" as the
missing piece. Night is short -- "Night lasts 2 minutes 35 seconds" (wiki
Nighttime) -- so nothing on a clock can say when it is; the screen has to.

THE COLOURS ARE THE MACROS'. Natro looks for a solid patch of night grass,
0x17481F (nm_image_assets/night/bitmaps.ahk on NatroMacro main, fetched
2026-10-12; submacros/background.ahk:179-226 `nm_CheckNight`, and
natro_macro.ahk:18228 `nm_confirmNight` at the hive after a reset): the
same green at night is (23, 72, 30), and the day's grass is (47, 117, 57),
within a tolerance of 6.

THE LINES ARE MEASURED, ON THE HIVE PAD'S VIEW ONLY. Every natro_out_* route's
`00-start` frame in var/routes (3,957 of them, 2026-10-12) is the
squared-up view from our pad just before a walk -- the moment a hunt is
decided. In the lower half of each: the day frames read 1-2% night green
(shade) beside 0.1-2% day green; the night frames 3-15% night green and no
day green (99th percentile 0.0003). NIGHT_MIN 0.03 with DAY_MAX 0.0005 calls
406 of them night (10.3%) -- the share a 2:35 night takes of a 10-30 minute
day (wiki) -- in 297 runs (frames under 6 min apart), the longest 145 s:
never longer than the night itself. A view that shows neither green (a menu,
another camera) is not night. Off the pad these lines are unmeasured.

THE SKY HAS THE LAST WORD WHERE IT SHOWS (ROADMAP NIGHT-SKY, 2026-10-27;
docs/pending/nightsky.md, scripts/score_nightsky.py). The day sky is one flat
light blue (BGR 227,206,159, +-2 over 6,000+ frames), the night sky black
with a few stars. MEASURED on the cannon flight of every natro_out_*cannon*
route (3,005; it shows open sky): on the 2,209 trips where the flight read
one sky, the floor on the pad ~10 s before missed 23 of 265 nights and
called 26 days night; 18 of those 49 checked by eye, the sky was right every
time. Outside flights (shops, menus, hive looks, hunts, fields: 37,000+
frames) the sky said day 0 times and night 54, all night scenes by eye. On
the pad no sky shows (0 of 6,646 start frames change verdict), so there the
floor still decides -- unless the camera looks up (look_up, look-only).
"""
from __future__ import annotations

import cv2
import numpy as np

NIGHT_RGB = (23, 72, 30)      # night grass; Natro 0x17481F is (23, 72, 31)
DAY_RGB = (47, 117, 57)       # day grass
TOLERANCE = 6                 # per channel
NIGHT_MIN = 0.03              # share of the lower half (see the module note)
DAY_MAX = 0.0005

# THE SKY PATCHES, y 136-200 on 1920x1080: x 520-640 (right of the top-left
# icons) and x 1280-1760 (right of the Honey/Pollen pills, left of the "?"),
# as shares of the frame (the 3D world, not GUI: vision/screen). ponytail:
# measured on 1920x1080 only; at 1280x720 the icons (to ~340 px) and the "?"
# (dx -615, vision/screen) still end outside them.
SKY_BOXES = ((0.271, 0.126, 0.333, 0.185), (0.667, 0.126, 0.917, 0.185))
SKY_DARK = 10                 # a night-sky pixel: every channel under this
SKY_NIGHT_MIN = 0.9           # share of EACH patch (both must agree, see sky())
DAY_SKY_BGR = (227, 206, 159)
DAY_SKY_TOL = 25
SKY_DAY_MIN = 0.9
# The lower half's mean; under it the black is a menu's dimming or a black
# frame. MEASURED (1/4-size frames): night cannon flights >= 25.5, dimmed
# menus and black frames <= 23. SKY_DARK 6-15 and SKY_NIGHT_MIN 0.9-0.95 gave
# the same trip verdicts (+-1 of 265 nights).
LOWER_MIN = 25.0

# THE LOOK UP, for a view with no sky in it. LOOK-ONLY: with NIGHT_SKY_LIVE
# False the bot only says "night sky would: ...". ASSUMED: turned round (yaw
# 4, away from the hive) and tilted up a tap (PageDown looks up, act/camera;
# two from spawn put the camera in the floor), the patch is open sky. The
# first live frames settle it (docs/pending/nightsky.md).
NIGHT_SKY_LIVE = False
SKY_LOOK = {"yaw": 4, "pitch": -1}


def _share(low: np.ndarray, rgb: tuple) -> float:
    r, g, b = rgb
    lo = np.array([b - TOLERANCE, g - TOLERANCE, r - TOLERANCE])
    hi = np.array([b + TOLERANCE, g + TOLERANCE, r + TOLERANCE])
    return float((cv2.inRange(low, lo, hi) > 0).mean())


def shares(frame) -> tuple[float, float] | None:
    """(night green, day green) as shares of the frame's lower half; None
    without a frame."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    low = np.ascontiguousarray(frame[frame.shape[0] // 2:, :, :3])
    return _share(low, NIGHT_RGB), _share(low, DAY_RGB)


def sky(frame) -> str | None:
    """"day" when both patches are the day sky's blue, "night" when both are
    night-sky black, else None (no sky in view: the hive, a wall, a menu --
    or sky on one side only: a near bubble is the day blue, a near wall in
    shade night black)."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    h, w = frame.shape[:2]
    patches = [frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w), :3]
               .reshape(-1, 3).astype(np.int16) for x0, y0, x1, y1 in SKY_BOXES]
    if any(p.size == 0 for p in patches):
        return None
    if all((np.abs(p - DAY_SKY_BGR).max(axis=1) < DAY_SKY_TOL).mean() >= SKY_DAY_MIN
           for p in patches):
        return "day"
    if (all((p.max(axis=1) < SKY_DARK).mean() >= SKY_NIGHT_MIN for p in patches)
            and float(frame[h // 2:, :, :3].mean()) >= LOWER_MIN):
        return "night"
    return None


def is_night(frame) -> bool:
    """The sky when it is in view, else the floor in front of the hive."""
    seen = sky(frame)
    if seen is not None:
        return seen == "night"
    got = shares(frame)
    return got is not None and got[0] >= NIGHT_MIN and got[1] < DAY_MAX


def look_up(camera, capture, pose_of, say) -> str | None:
    """The sky's word after turning to it (SKY_LOOK, through act/camera so the
    view is put back on every way out), or None. LOOK-ONLY while
    NIGHT_SKY_LIVE is False: says what it would do and moves nothing.
    `pose_of(**SKY_LOOK)` builds act/camera's Pose (vision does not import act)."""
    if not NIGHT_SKY_LIVE:
        say(f"night sky would: turn the camera {SKY_LOOK['yaw'] * 45} degrees and tilt it "
            f"up {-SKY_LOOK['pitch']} tap to read the sky, then put it back")
        return None
    with camera.looking(pose_of(**SKY_LOOK)):
        return sky(capture())
