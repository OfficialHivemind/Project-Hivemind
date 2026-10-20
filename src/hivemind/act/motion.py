"""Holding a key while measuring what the ground did.

Every walk in this project used to be `hold the key, sleep, release` -- and
nothing looked at the world in between. The ground's optical flow
(`vision.flow`) reads about 15 px per frame while the character walks and
about 1 px when it is pushing on a wall (MEASURED, vision/flow GROUND_ROI
table and act/orient's closure sweep), so a hold that samples the flow as it
goes knows two things a timer never can: how far the character actually
moved, and whether it moved at all.

`hold_measuring` is that hold. The chase comes home by it (act/chase) and the
homing loop tells a step that walked from a step that leaned on a wall by it
(act/homing). Both need the sampling to happen INSIDE the hold: Lucas-Kanade
flow tracks a few pixels between consecutive frames and would lose a whole
0.35 s step taken as one 90 px jump.
"""
from __future__ import annotations

import time

# How often the ground is photographed while a key is held. The flow tracker
# was measured at about 15 px per frame at this cadence while walking.
SAMPLE_SECONDS = 0.06
# Below this much ground motion PER ACCEPTED FRAME the held key is moving
# nothing: vision/flow.BLOCKED_FLOW_PX (2.5) is the same measurement made by
# the route runner; a blocked key reads about 1 px, an open one 7-17.
BLOCKED_PER_FRAME_PX = 3.0


def hold_measuring(vin, keys: str, seconds: float, sleep, frames, odometer):
    """Hold `keys` for `seconds`, feeding `odometer` (a vision.flow.Odometer)
    the whole time.

    Returns `(accepted, scene_dx, scene_dy, travel)`: how many frames' flow
    the odometer accepted during the hold, how far the ground moved on screen
    as a vector (+x right, +y down), and how far it moved regardless of
    direction (the per-frame median point motion, summed -- walking straight
    ahead spreads the ground outward and can leave the vector near zero while
    the world plainly moved). None when there is no odometer.
    """
    if odometer is None:
        with vin.held(*keys):
            sleep(seconds)
        return None
    before = (odometer.samples, odometer.dx, odometer.dy,
              float(getattr(odometer, "travel", 0.0)))
    n = max(1, round(seconds / SAMPLE_SECONDS))
    with vin.held(*keys):
        for _ in range(n):
            sleep(seconds / n)
            try:
                frame = frames()
            except Exception:
                frame = None
            if frame is not None:
                try:
                    odometer.update(frame)
                except Exception:
                    pass
    return (odometer.samples - before[0],
            odometer.dx - before[1], odometer.dy - before[2],
            float(getattr(odometer, "travel", 0.0)) - before[3])


def stuck(hold) -> bool | None:
    """Did the held key move nothing? None when the hold was unmeasured (no
    odometer, or the ground gave the flow nothing to track) -- an unmeasured
    hold is reported as unmeasured, never as stuck."""
    if hold is None or hold[0] == 0:
        return None
    return (hold[3] / hold[0]) < BLOCKED_PER_FRAME_PX


# ---- A22b: the walk home's real speed, measured off the ground ---------------
# The runner shortens every hold by the buff bar's factor (vision/buffs: Haste
# 10% a stack, Natro's). MEASURED 2026-10-15 (A22, runs 988 07:53 and 1015
# 06:22): walks home that set off under Haste x8-x10 after the 32 s wait missed
# -- the icon's stack count is not the speed the character walked. So the
# first PROBE_SECONDS of a walk home's first hold are timed off the ground flow
# the runner already samples (`on_motion`), as px/s, and compared with the same
# route's same first seconds walked with no buff this session: their ratio is
# the speed walked, and the factor the runner divides by is trimmed to it while
# the Haste lasts. The same route's start, not one baseline per key: flow
# magnitude depends on the scene (run_farm's "PACED WALKING IS OFF").
PROBE_SECONDS = 0.75
PROBE_MIN_SAMPLES = 4
PROBE_FAST_FACTOR = 1.8       # Haste x8 at Natro's 10% a stack
# ponytail: the runner samples the flow at 10 Hz, so x2 ground slides ~2x as far
# per sample and Lucas-Kanade may under-read it; the trim is held to these
# bounds (calibration knob) until the corpus says how far to trust it.
PROBE_TRIM_BOUNDS = (0.6, 1.5)
PROBE_CALM_KEEP = 5           # calm rates kept per route, the median used


# LOOK-ONLY since 2026-10-16 07:41 (run-1029): its first live reading said
# 0.49x under Haste 1.91x, the legs were stretched x1.67, the walk overshot
# the pad into a wall and the run REJOINED. The 10 Hz ground samples
# under-read fast motion (the risk noted when it was built). It logs what it
# would do until its readings are checked against walks that land.
PROBE_APPLIES = False


class SpeedProbe:
    """`begin(route, factor)` before every route (None: not a walk home),
    `saw(keys, px)` from the runner's `on_motion`; `trim` is what the buff
    factor is multiplied by while the Haste is up (1.0 unless measured)."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.calm: dict[str, list[float]] = {}
        self.begin(None, 1.0)

    def begin(self, route: str | None, factor: float) -> None:
        self.route, self.expected = route, float(factor)
        self.keys, self.samples, self.trim = None, [], 1.0

    def saw(self, keys: str, px) -> str | None:
        """Take one flow sample; returns a line to log when the probe ends."""
        if self.route is None or px is None:
            return None
        if self.keys is None:
            self.keys = keys
        if keys != self.keys:           # the first hold ended before the probe
            return self._done(None)
        self.samples.append((self.clock(), float(px)))
        span = self.samples[-1][0] - self.samples[0][0]
        if span < PROBE_SECONDS:
            return None
        if len(self.samples) < PROBE_MIN_SAMPLES:
            return self._done(None)
        # each sample is the motion since the one before, so the first only
        # marks the start of the clock
        return self._done(sum(p for _, p in self.samples[1:]) / span)

    def _done(self, rate: float | None) -> str | None:
        route, expected = self.route, self.expected
        self.route = None
        if rate is None or rate <= 0:
            return (f"walk home: could not time the speed off the ground "
                    f"(icon said {expected:.2f}x) — legs at the icon's speed"
                    if expected >= PROBE_FAST_FACTOR else None)
        if expected <= 1.0:
            kept = self.calm.setdefault(route, [])
            kept.append(rate)
            del kept[:-PROBE_CALM_KEEP]
            return None
        calm = sorted(self.calm.get(route, []))
        if expected < PROBE_FAST_FACTOR:
            return None
        if not calm:
            return (f"walk home: no calm walk of {route} timed this session to "
                    f"compare with (icon said {expected:.2f}x) — legs at the "
                    f"icon's speed")
        would = trim_for(rate / calm[len(calm) // 2], expected)
        if PROBE_APPLIES:
            self.trim = would
        return (f"walk home: measured {rate / calm[len(calm) // 2]:.2f}x speed "
                f"(icon said {expected:.2f}x), legs "
                + (f"scaled x{1 / self.trim:.2f}" if PROBE_APPLIES else
                   f"NOT scaled (look-only; would be x{1 / would:.2f})"))


def trim_for(measured: float, expected: float) -> float:
    """The factor's correction, measured/expected within PROBE_TRIM_BOUNDS."""
    low, high = PROBE_TRIM_BOUNDS
    return min(high, max(low, measured / expected)) if expected > 0 else 1.0
