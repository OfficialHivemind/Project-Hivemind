"""Optical-flow odometry: how far did we actually move?

Natro Macro is already closed-loop, but it closes the loop on an *inferred* speed
-- it screen-scrapes the buff bar, works out a haste multiplier, and integrates
distance = speed x time. Every modelling error (a slope, a bush, a lag spike, a
knockback) accumulates silently because nothing ever checks the world.

We measure the displacement instead. If you walked into a rock, flow reads ~0 and
we know within 100 ms, rather than arriving 40 studs off target.

Two robustness choices carry most of the weight:
  * the MEDIAN of the per-point vectors, never the mean -- bees, particles, other
    players and drifting clouds are all moving independently, and a mean is
    hostage to them
  * a forward-backward consistency check -- track each point forward then back,
    and discard any that fails to return near its origin. This is what kills the
    silently-wrong tracks that a status flag alone will happily report as good.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# WHERE TO LOOK FOR MOTION, and why it must not be "everywhere".
#
# MEASURED 2026-09-21 on 147 frames of the character walking a recorded route
# and 79 frames of a gathering pattern, straight from the incident recorder:
#
#     region                          walking     gathering   stuck at a wall
#     whole frame (no ROI)            0.01 px      0.02 px        0.00 px
#     world minus HUD (150..800)      0.69 px     15.44 px        0.00 px
#     the ground (this ROI)          15.06 px     18.20 px        0.00 px
#
# Over the whole frame the median vector is ~0 WHILE WALKING, because the HUD
# -- pills, hotbar, icons, feed -- is full of sharp corners and does not move,
# and the median belongs to whoever has the most points. Every live run before
# today built its tracker with no ROI, which is why `pace` never got a sample
# and why "measured walking" was switched off for breaking the cannon: it was
# never measuring the world. The ground in front of the character is the part
# of the scene with the most parallax, so it is where motion shows first.
GROUND_ROI = (300, 400, 1320, 560)          # x, y, w, h at 1920x1080

# Below this the character is not moving. MEASURED by act/orient's closure
# sweep: a blocked key reads about 1 px per frame and an open one 7-17 px, and
# the table above agrees (0.00 stuck, 15 walking). Not delicately placed.
BLOCKED_FLOW_PX = 2.5

LK = dict(winSize=(21, 21), maxLevel=3,
          criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
FEATURES = dict(maxCorners=140, qualityLevel=0.08, minDistance=12, blockSize=7)


@dataclass(frozen=True)
class FlowSample:
    dx: float                 # pixels, +x = scene moved right
    dy: float
    tracked: int              # points that survived every check
    spread: float             # median abs deviation; high = inconsistent scene
    ok: bool
    # Surviving correspondences in FULL-resolution frame coordinates, so callers
    # can reproject each point individually rather than trusting a single median
    # pixel delta. Perspective means a near point and a far point move by very
    # different pixel amounts for the same world displacement.
    pairs: np.ndarray | None = None   # (n, 2, 2): [[x0,y0],[x1,y1]] per point

    @property
    def magnitude(self) -> float:
        return float((self.dx ** 2 + self.dy ** 2) ** 0.5)

    @property
    def motion_px(self) -> float:
        """How much the tracked world moved, as the median of per-point lengths.

        Different from `magnitude`, which is the length of the median vector:
        when half the points slide left and half right (the camera turning
        about a point in the ROI) the median vector is ~0 but the world
        plainly moved. Per-point lengths answer "did anything move", which is
        the question a stuck detector asks. act/orient measures it this way.
        """
        if self.pairs is None or len(self.pairs) == 0:
            return self.magnitude
        d = self.pairs[:, 1, :] - self.pairs[:, 0, :]
        return float(np.median(np.linalg.norm(d, axis=1)))


class FlowTracker:
    """Frame-to-frame displacement of the ground plane."""

    def __init__(self, roi: tuple[int, int, int, int] | None = None,
                 min_tracked: int = 8, max_spread: float | None = None,
                 scale: float = 0.5):
        # max_spread is the PIXEL-space agreement gate, and it defaults to off
        # on purpose. Under perspective, ground points at different depths move
        # by wildly different pixel amounts for the same world motion -- 207 px
        # at 8 studs away versus 8 px at 60 studs, measured. Pixel disagreement
        # is therefore expected and correct, and gating on it rejects perfectly
        # good frames. The meaningful consistency check happens in WorldOdometer,
        # after reprojection, where every ground point genuinely should agree.
        # Only set this for a flat/orthographic scene.
        # roi excludes HUD and sky; scale downsamples for speed (flow is
        # scale-invariant if we divide the result back out)
        self.roi = roi
        self.min_tracked = min_tracked
        self.max_spread = max_spread
        self.scale = scale
        self._prev: np.ndarray | None = None

    def _prep(self, bgr: np.ndarray) -> np.ndarray:
        if self.roi:
            x, y, w, h = self.roi
            bgr = bgr[y:y + h, x:x + w]
        if bgr.ndim == 3:
            bgr = cv2.cvtColor(bgr[:, :, :3], cv2.COLOR_BGR2GRAY)
        if self.scale != 1.0:
            bgr = cv2.resize(bgr, None, fx=self.scale, fy=self.scale,
                             interpolation=cv2.INTER_AREA)
        return bgr

    def reset(self) -> None:
        self._prev = None

    def update(self, frame: np.ndarray) -> FlowSample | None:
        """Feed a frame. Returns displacement since the previous one, or None
        on the first frame."""
        gray = self._prep(frame)
        prev, self._prev = self._prev, gray
        if prev is None:
            return None
        return self._measure(prev, gray)

    def _measure(self, prev: np.ndarray, cur: np.ndarray) -> FlowSample:
        p0 = cv2.goodFeaturesToTrack(prev, **FEATURES)
        if p0 is None or len(p0) < self.min_tracked:
            return FlowSample(0.0, 0.0, 0, 0.0, False, None)

        p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, p0, None, **LK)
        # forward-backward check
        p0r, st2, _ = cv2.calcOpticalFlowPyrLK(cur, prev, p1, None, **LK)
        good = (st.ravel() == 1) & (st2.ravel() == 1)
        fb_err = np.linalg.norm((p0 - p0r).reshape(-1, 2), axis=1)
        good &= fb_err < 1.0

        if good.sum() < self.min_tracked:
            return FlowSample(0.0, 0.0, int(good.sum()), 0.0, False, None)

        d = (p1 - p0).reshape(-1, 2)[good]
        med = np.median(d, axis=0)
        s = 1.0 / self.scale

        # Two fixes in one line, both about the gate meaning what it says.
        #
        # Per-point EUCLIDEAN deviation, not a median over the flattened (N,2)
        # array: pooled, a scene with uniform dy and wildly varying dx reports
        # ~0 spread, because the N zero dy-deviations occupy the lower half of
        # the 2N values. (A 30px horizontal disagreement measured 0.16px.)
        #
        # ...and scaled to full-resolution pixels BEFORE the comparison. The
        # gate used to run on downscaled units while `spread` was reported
        # scaled, so max_spread was effectively 1/scale looser than its value
        # -- twice as permissive at the default scale=0.5, and the same
        # physical scene passed or failed purely by downsample factor.
        spread = float(np.median(np.linalg.norm(d - med, axis=1))) * s

        ok = self.max_spread is None or spread <= self.max_spread
        ox, oy = (self.roi[0], self.roi[1]) if self.roi else (0, 0)
        a = p0.reshape(-1, 2)[good] * s + (ox, oy)
        b = p1.reshape(-1, 2)[good] * s + (ox, oy)
        pairs = np.stack([a, b], axis=1).astype(np.float64)

        return FlowSample(float(med[0]) * s, float(med[1]) * s,
                          int(good.sum()), spread, ok, pairs)


class Odometer:
    """Accumulates flow into a distance travelled. Reset before each leg.

    `dx`, `dy` are the SCENE's motion on screen (+x = the ground slid right).
    `displacement()` turns that into the CHARACTER's own movement, which is
    what a walk back to where it started needs. This is the odometer the
    token chase comes home by: MEASURED 2026-09-22 19:45-19:54 (runs 237-239),
    an odometer read off matched token positions instead reported 8 returns
    of +2..+28 px after real 0.35 s steps that the ground flow puts at about
    90 px -- only the far, slow-sliding tokens survived its 90 px match gate,
    so the median belonged to them. The ground has no such bias.
    """

    def __init__(self, tracker: FlowTracker):
        self.tracker = tracker
        self.distance = 0.0     # pixels
        self.dx = 0.0
        self.dy = 0.0
        self.rejected = 0
        self.samples = 0        # frames whose flow was accepted since reset
        # How far the ground moved regardless of direction: the per-frame
        # median point motion, summed. `distance` sums the median VECTOR's
        # length, which walking straight ahead leaves near zero while the
        # ground spreads outward; this is the stuck detector's figure.
        self.travel = 0.0
        # A screen point carried along by the ground NEAR it (`follow`), or
        # None: where a token seen there should be after the frames since.
        self.point: tuple[float, float] | None = None

    def reset(self) -> None:
        self.tracker.reset()
        self.distance = self.dx = self.dy = 0.0
        self.rejected = 0
        self.samples = 0
        self.travel = 0.0
        self.point = None

    def follow(self, x: float, y: float) -> None:
        """From the next frame on, carry (x, y) with the tracked ground
        nearest it (`carried`); `point` then says where it went."""
        self.point = (float(x), float(y))

    def update(self, frame: np.ndarray) -> FlowSample | None:
        s = self.tracker.update(frame)
        if s is None:
            return None
        if s.ok:
            self.dx += s.dx
            self.dy += s.dy
            self.distance += s.magnitude
            self.travel += s.motion_px
            self.samples += 1
            if self.point is not None:
                self.point = carried(self.point, s)
        else:
            self.rejected += 1
        return s

    def displacement(self) -> tuple[float, float] | None:
        """The character's movement since reset, in screen px (x right, y down
        -- so forward, which carries the ground down the screen, reads as
        negative y, the same sense `act/chase.keys_towards` uses). None until
        one frame's flow has been accepted: an unmeasured walk is reported as
        unmeasured, never as zero."""
        if self.samples == 0:
            return None
        return (-self.dx, -self.dy)


# A TOKEN MOVES WITH THE GROUND AROUND IT, NOT WITH THE GROUND'S MEDIAN.
# Under perspective a far point slides a fraction of what a near one does
# for the same step, so a far token carried by the ROI's median vector is
# looked for where it never goes. MEASURED 2026-10-03 on 40 of the recorded
# token incidents (var/incidents/*token*, 844 token-steps of three frames,
# about one 0.35 s chase step; each token chained frame to frame as the
# truth): carried by the median motion of the FOLLOW_NEAREST tracked points
# nearest it, a token above y 450 landed 33 px from where it was found
# (median; 7% past the chase's 90 px match), against 48 px and 13% by the
# median vector -- no better than not moving it at all (47 px); at y
# 450-600, 48 px and 15% against 67 px and 25%. The loot chases after a kill
# lost exactly such far tokens: "lost sight of it 606-727 px out".
FOLLOW_NEAREST = 12


def carried(point: tuple[float, float], sample: FlowSample) -> tuple[float, float]:
    """`point` moved as the tracked ground nearest it moved in `sample` --
    or by the sample's median when it kept too few points to say."""
    x, y = float(point[0]), float(point[1])
    pairs = sample.pairs
    if pairs is None or len(pairs) < 3:
        return (x + sample.dx, y + sample.dy)
    start = pairs[:, 0, :]
    near = np.argsort(np.hypot(start[:, 0] - x, start[:, 1] - y))[:FOLLOW_NEAREST]
    mx, my = np.median(pairs[near, 1, :] - start[near], axis=0)
    return (x + float(mx), y + float(my))
