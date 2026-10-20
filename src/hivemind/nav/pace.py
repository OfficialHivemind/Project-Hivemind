"""How fast are we ACTUALLY moving, compared to how fast the recording assumed?

THE PROBLEM, spotted by the owner while watching a live run: "on the field it
was heavily to the right that could be maybe sinceit picked up a haste token
here and there or mayber other reasons idk".

He is right, and it is the known weakness of every timed macro. A route step
says "hold W for `studs / walkspeed` seconds". That is exact only while the
character moves at exactly `walkspeed`. Bee Swarm hands out Haste tokens, Oil,
Super Smoothie and field boosts, any of which make the same hold cover more
ground -- so a route drifts further off with every leg, and the drift is worst
on the longest ones. It is why the gather pattern ends somewhere other than
where it started even though its own step list sums to zero displacement.

WHY THIS MEASURES INSTEAD OF INFERRING. BSSAI solves it by reading the buff
bar and computing what the speed OUGHT to be from the icons and their stack
counts. That works, and it needs a labelled icon for every buff in the game,
plus the arithmetic for how they combine, plus an update whenever the game
adds one. The buff bar is real and this project can already find it -- tiles
38 px wide at y=57..95, MEASURED on our own frames -- but naming which tile is
Haste needs ground truth nobody here has.

Optical flow needs none of that. If the character is moving twice as fast, the
world slides past twice as fast, whatever is causing it -- haste, a field
boost, a buff added next year. The project plan said this from the start: the
other macros integrate an INFERRED speed, and the thing that makes this one
different is measuring the real displacement.

WHAT IT CANNOT DO, STATED PLAINLY. Without a ground-plane calibration there is
no conversion from pixels to studs, so this cannot say "we are going 42 studs
per second". It can only say "we are going 1.4x as fast as this same kind of
step usually goes", which is exactly the number needed to shorten a hold. A
ratio needs no calibration; a speed does.

AND IT REFUSES WHEN IT DOES NOT KNOW. Flow magnitude depends on the scene as
well as the speed -- a wall close to the camera slides faster than a distant
field -- so a single sample means little. It reports a correction only once it
has a stable baseline built from many walks, and returns exactly 1.0
otherwise, which leaves the recorded timing untouched.
"""
from __future__ import annotations

import statistics
from collections import deque

# Below this many completed walks there is no baseline worth trusting, and the
# recorded timings are used unchanged.
MIN_SAMPLES = 12

# How many recent walks define "normal". Long enough to be stable, short
# enough to follow a real change in the character's speed.
WINDOW = 60

# A correction outside this range is not believable as a speed change and is
# far more likely to be a scene effect -- a wall filling the view, a camera
# turn, a cutscene. Clamping keeps a bad measurement from turning a 300-stud
# walk into a 30-stud one.
MIN_MULTIPLIER, MAX_MULTIPLIER = 0.6, 2.5

# Flow below this is not movement, it is noise; samples there are discarded
# rather than dragging the baseline down.
MIN_FLOW_PX = 0.6


class PaceMeter:
    """Learns the usual flow rate of a walk, and reports deviations from it.

    One meter per key combination: walking forward and strafing produce
    different amounts of flow for the same speed, so mixing them would make
    the baseline meaningless.
    """

    def __init__(self, min_samples: int = MIN_SAMPLES, window: int = WINDOW):
        self.min_samples = int(min_samples)
        self.rates: dict[str, deque] = {}
        self.window = int(window)
        self.corrections = 0

    def observe(self, keys: str, flow_px: float, seconds: float) -> None:
        """Record one completed hold: `flow_px` of movement over `seconds`."""
        if not keys or seconds <= 0 or flow_px < MIN_FLOW_PX:
            return
        rate = flow_px / seconds
        self.rates.setdefault(keys, deque(maxlen=self.window)).append(rate)

    def baseline(self, keys: str) -> float | None:
        """The usual rate for these keys, or None if not enough is known."""
        seen = self.rates.get(keys)
        if not seen or len(seen) < self.min_samples:
            return None
        return statistics.median(seen)

    def multiplier(self, keys: str, flow_px: float, seconds: float) -> float:
        """How much faster than usual we are moving. 1.0 means "no idea".

        Multiply a hold's remaining time by 1/this to cover the recorded
        distance at the speed actually being travelled.
        """
        if seconds <= 0 or flow_px < MIN_FLOW_PX:
            return 1.0
        usual = self.baseline(keys)
        if usual is None or usual <= 0:
            return 1.0
        ratio = (flow_px / seconds) / usual
        if ratio < MIN_MULTIPLIER or ratio > MAX_MULTIPLIER:
            return 1.0          # not believable as a speed change
        if abs(ratio - 1.0) > 0.12:
            self.corrections += 1
        return ratio

    def describe(self) -> str:
        known = {keys: round(statistics.median(rates), 1)
                 for keys, rates in self.rates.items()
                 if len(rates) >= self.min_samples}
        if not known:
            total = sum(len(r) for r in self.rates.values())
            return (f"no baseline yet ({total} samples, need "
                    f"{self.min_samples} per key combination)")
        return (f"baseline px/s {known}, {self.corrections} walks "
                f"seen off-pace")
