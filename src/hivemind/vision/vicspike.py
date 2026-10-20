"""The Vicious Bee's spike, seen in a field (ROADMAP Q3b / M5).

WHY. Touching the spike calls the bee up (the owner, 2026-10-21, with a
screenshot showing the stinger summoning the Vicious Bee). Q3's blind
zigzag came back 'absent' 20 of 20 nights (var/vicious.json, 13-25 Oct) --
walking a field without looking is a coin toss over a 2:35 night. Seeing the
spike turns the search into one look per field.

WHAT IT LOOKS LIKE. MEASURED 2026-10-26 on the owner's screenshot
(var/reference/vicious_spike_owner_2026-10-21.png, a night Clover-like field:
the grass reads BGR (31, 76, 21), night_mod's night green): ONE smooth blob,
HSV H 95-106, S 20-59 (median 57), V 154-190, 36x122 px; a cone -- 6 px wide
at the tip, 20 px at the base, the width growing steadily along its length --
leaning a little, and standing in the flowers. The white flowers next to it
share its hue under the night light (H 98-112) but are paler (S median 26)
and round. Nothing here is textured, which is why keypoint matching (SIFT/ORB
from that one crop) does not find it: scripts/score_vicspike.py measures that.

AND IN OUR OWN FRAMES. Its first version, run over every kept hunt frame,
found spikes in two hunts recorded 'absent' (2026-10-15 07:05 and 2026-10-23
20:42, Clover) and on a night route frame (attempt-669): 8 labelled frames,
scripts/score_vicspike.py SPIKES. They are 3-21 px wide, 23-61 px tall.

HOW (our own rule): pale-blue pixels -> blobs (a short vertical close joins
a thin one JPEG broke) -> keep the ones shaped like a spike standing up
(long, solid, near upright, tip narrower than base, not too saturated) whose
BASE stands in field grass. The colour alone flags ~3.7 blobs a frame (walls,
glass, bubbles, wings, text); the shape and the base remove them.

SCORED 2026-10-26 (scripts/score_vicspike.py, 1,361 frames: kept hunt
frames + route frames whose start view was night; vision/night.is_night on
each frame itself calls only 405 of them night -- hunts run on past dawn.
False alarms: 4/405 night frames, 25/956 day ones):
                    real spikes  pasted spikes  frames with a false alarm
  colour rule (Q3b)     6/8      455/1139 (40%)    1142/1361 (84%)
  SIFT, owner's crop    0/8        0/280   (0%)       6/300   (2%)
  this                  7/8      731/1139 (64%)      29/1361  (2.1%)
The 8 real frames were FOUND by this detector's first version and tuned
on, so 7/8 is in-sample, not a recall: the live crops are the first fair
test. The one real miss stands against the night sky with its base hidden
by the field's edge. The pasted ones it misses are mostly the smallest (<40 px:
44/87) and ones pasted on dense flowers.

ponytail: 8 real frames from 3 sightings, all at the hunt's eye-level camera
-- a lookout looking down sees it at other angles (MAX_LEAN_DEG). Every hit
is kept as a crop (keep_crop) so new spikes, and the owner's yes/no on them,
grow the labelled set; a small trained detector can follow once it is big.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

# The spike's colour. MEASURED on the owner's frame (H 95-106, S 20-59, V
# 154-190) and on the spikes in our own kept frames (SPIKES in
# scripts/score_vicspike.py; JPEG q70, 3-21 px wide): H 72-115, S 15-75, V
# 140-195 (5th-95th percentiles of their bright pixels). S >= 25 leaves out
# most of the white flowers (S ~26 under the night light).
LO = (70, 25, 135)
HI = (118, 95, 255)
# Thin spikes break into pieces in the mask (JPEG); a short vertical close
# joins them (they stand upright, see MAX_LEAN_DEG).
CLOSE = (1, 5)                   # kernel width, height (px)
# Its mean saturation: the 7 real spikes it finds read 41-53, its false
# alarms (glass, wings, bees' stripes) a median of 71. MEASURED 2026-10-26
# (scripts/score_vicspike.py): <= 62 halves the false alarms (75 -> 31 hits
# on 1,361 frames), keeps all 7 real ones and 730 of 741 pasted ones.
MAX_MEAN_S = 62
# Its shape. MEASURED on the owner's frame: area 1,207 px at 105 px long,
# elongation 6.4, solidity 0.97, fill of its rotated box 0.69, tip/base width
# 0.3, leaning 13 degrees; ours: 23-60 px long, leaning up to ~25 degrees.
MIN_AREA, MAX_AREA = 20, 6000
MIN_LENGTH = 14
MIN_ELONGATION = 3.5
MIN_SOLIDITY = 0.7
FILL = (0.4, 0.95)
MAX_TAPER = 0.85         # top end's width / bottom end's: the tip is up
# ponytail: upright from the hunt's eye-level camera. A lookout looking down
# sees it at other angles: widen this when the lookout's frames say so.
MAX_LEAN_DEG = 40
# The base stands in field, not on a wall, a bee or the sky: grass around
# the bottom end. Grass MEASURED on the owner's frame BGR (31, 76, 21) = HSV
# H ~52; vision/night's night grass is RGB (23, 72, 30). Not a ring all
# round: a spike at the field's far edge has the night sky behind it (three
# of ours do). Real ones read 0.29-0.64, false alarms a median of 0.02.
GRASS_LO, GRASS_HI = (40, 90, 35), (85, 255, 160)
MIN_BASE_GRASS = 0.25
# The HUD at 1920x1080 (top bar and buffs, the hotbar), where a pale-blue
# icon would otherwise pass: no field is ever there.
HUD_TOP, HUD_BOTTOM = 110, 940


class Spike(NamedTuple):
    x: int                   # its base (where to walk), frame pixels
    y: int
    length: int              # px along its long side
    lean: float              # degrees from upright
    taper: float             # top width / bottom width
    base_grass: float


def _shape(pts: np.ndarray) -> tuple[float, float, float, float, np.ndarray]:
    """(length, width, lean degrees, top/bottom width, base point) of a blob's
    pixels, along its principal axis."""
    c = pts.mean(0)
    rel = pts - c
    w, v = np.linalg.eigh(np.cov(rel.T))
    axis = v[:, 1] if v[1, 1] >= 0 else -v[:, 1]          # points down the frame
    along = rel @ axis
    across = rel @ np.array([-axis[1], axis[0]])
    length = float(np.ptp(along) + 1)
    width = float(np.ptp(across) + 1)
    lean = float(np.degrees(np.arccos(min(1.0, abs(axis[1])))))
    lo, hi = np.percentile(along, [30, 70])
    top = np.ptp(across[along <= lo]) + 1
    bottom = np.ptp(across[along >= hi]) + 1
    base = c + axis * along.max()
    return length, width, lean, float(top / bottom), base


def find(frame) -> list[Spike]:
    """Every spike-shaped pale-blue blob standing in a field, best first."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    img = np.ascontiguousarray(frame[:, :, :3])
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, LO, HI)
    h, w = img.shape[:2]
    mask[:int(HUD_TOP * h / 1080)] = 0
    mask[int(HUD_BOTTOM * h / 1080):] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones(CLOSE[::-1], np.uint8))
    grass = cv2.inRange(hsv, GRASS_LO, GRASS_HI)
    n, lab, st, _c = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in st[i])
        if not MIN_AREA <= area <= MAX_AREA or max(bw, bh) < MIN_LENGTH:
            continue
        ys, xs = np.nonzero(lab[y:y + bh, x:x + bw] == i)
        if hsv[ys + y, xs + x, 1].mean() > MAX_MEAN_S:
            continue
        pts = np.stack([xs + x, ys + y], 1).astype(np.float32)
        length, width, lean, taper, base = _shape(pts)
        if (length < MIN_LENGTH or length / width < MIN_ELONGATION or lean > MAX_LEAN_DEG
                or taper > MAX_TAPER or not FILL[0] <= area / (length * width) <= FILL[1]):
            continue
        if area / max(1.0, cv2.contourArea(cv2.convexHull(pts))) < MIN_SOLIDITY:
            continue
        r = int(max(8, length / 3))
        bx, by = int(base[0]), int(base[1])
        patch = grass[max(0, by - r):by + r, max(0, bx - r):bx + r]
        share = float((patch > 0).mean()) if patch.size else 0.0
        if share < MIN_BASE_GRASS:
            continue
        out.append(Spike(bx, by, int(length), round(lean, 1), round(taper, 2), round(share, 2)))
    return sorted(out, key=lambda s: (-s.base_grass, s.taper))


def keep_crop(frame, spike: Spike, folder, tag: str) -> Path | None:
    """The spike's neighbourhood saved as <folder>/<tag>-spike-<x>-<y>.png --
    the labelled set's raw material (the owner's yes/no on each)."""
    try:
        r = max(48, spike.length)
        y0, x0 = max(0, spike.y - r), max(0, spike.x - r)
        crop = frame[y0:spike.y + r, x0:spike.x + r, :3]
        path = Path(folder) / f"{tag}-spike-{spike.x}-{spike.y}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), crop)
        return path
    except Exception:
        return None
