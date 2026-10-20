"""Night or day, read off the floor in front of the hive.

WHY IT EXISTS. The Vicious Bee hunts only at night (wiki Rogue_Vicious_Bee:
"a high chance to spawn when it turns nighttime"), and data/knowledge/
playbook.yaml `night_vicious_bee` listed "telling night from day" as the
missing piece. Night is short -- "Night lasts 2 minutes 35 seconds" (wiki
Nighttime) -- so nothing on a clock can say when it is; the screen has to.

THE COLOURS ARE THE MACROS'. Natro looks for a solid patch of night grass,
0x17481F (nm_image_assets/night/bitmaps.ahk on NatroMacro main, fetched
2026-10-12; submacros/background.ahk:179-226 `nm_CheckNight`, and
natro_macro.ahk:18228 `nm_confirmNight` at the hive after a reset), and
Fuzzy Macro for the same green at night, (23, 72, 30), only once the day's
(47, 117, 57) "ground" is gone (src/modules/macro.py:1169-1196
`isGrassNight`, tolerance 6).

THE LINES ARE MEASURED, ON THE HIVE PAD'S VIEW ONLY. Every natro_out_* route's
`00-start` frame in ~/Hivemind/var/routes (3,957 of them, 2026-10-12) is the
squared-up view from our pad just before a walk -- the moment a hunt is
decided. In the lower half of each: the day frames read 1-2% night green
(shade) beside 0.1-2% day green; the night frames 3-15% night green and no
day green (99th percentile 0.0003). NIGHT_MIN 0.03 with DAY_MAX 0.0005 calls
406 of them night (10.3%) -- the share a 2:35 night takes of a 10-30 minute
day (wiki) -- in 297 runs (frames under 6 min apart), the longest 145 s:
never longer than the night itself. A view that shows neither green (a menu,
another camera) is not night. Off the pad these lines are unmeasured.
"""
from __future__ import annotations

import cv2
import numpy as np

NIGHT_RGB = (23, 72, 30)      # Fuzzy isGrassNight "a"; Natro 0x17481F is (23, 72, 31)
DAY_RGB = (47, 117, 57)       # Fuzzy isGrassNight dayColors "ground"
TOLERANCE = 6                 # Fuzzy's `variance=6`
NIGHT_MIN = 0.03              # share of the lower half (see the module note)
DAY_MAX = 0.0005


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


def is_night(frame) -> bool:
    got = shares(frame)
    return got is not None and got[0] >= NIGHT_MIN and got[1] < DAY_MAX
