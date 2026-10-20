"""Closed-loop movement.

    walk_studs(40, "w")

presses W, watches the ground go past, and releases when it has actually
travelled 40 studs. Not "holds W for 40/speed seconds and hopes".

What that buys, none of which needs special-casing:
  * haste tokens, slopes and lag change the speed -- the loop just ends sooner
    or later, because it is counting distance, not time
  * knockback and collisions subtract real distance, so they are compensated
  * walking into a rock reads zero progress and raises Stuck within ~0.5 s,
    instead of the character grinding against it for 13 seconds

The one thing a closed loop must get right is overshoot: we can only sample at
the capture rate, so we release one tick EARLY based on the observed per-tick
rate rather than after crossing the line.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np

from .odometry import WorldOdometer


class Stuck(RuntimeError):
    """No measurable progress: terrain, a closed gate, or a lost character."""


class InputLike(Protocol):
    def press(self, *keys: str) -> None: ...
    def release(self, *keys: str) -> None: ...


@dataclass
class WalkResult:
    requested: float
    travelled: float
    dx: float
    dz: float
    ticks: int
    seconds: float
    stuck: bool = False

    @property
    def error(self) -> float:
        return self.travelled - self.requested


def walk_studs(
    distance: float,
    keys: str | tuple[str, ...],
    *,
    vin: InputLike,
    frames: Callable[[], np.ndarray],
    odo: WorldOdometer,
    timeout: float = 30.0,
    stall_ticks: int = 6,
    stall_studs: float = 0.15,
    clock: Callable[[], float] = time.monotonic,
) -> WalkResult:
    """Hold `keys` until `distance` studs have actually been covered."""
    keys = (keys,) if isinstance(keys, str) else tuple(keys)
    odo.reset()
    t0 = clock()
    ticks = 0
    stalled = 0
    rate = 0.0            # studs per tick, smoothed - used to release early

    # Reference frame BEFORE pressing anything. Taking it after the first
    # press loses one tick of travel, which shows up as a consistent overshoot
    # of exactly one capture interval.
    odo.update(frames())

    # press INSIDE the try, so a partial press cannot escape before the
    # finally is armed. Same defect as VirtualInput.held() had.
    try:
        vin.press(*keys)
        while True:
            step = odo.update(frames())
            ticks += 1
            travelled = odo.displacement

            if step is not None and step.ok:
                inc = step.distance
                rate = inc if rate == 0.0 else 0.6 * rate + 0.4 * inc
                stalled = 0 if inc > stall_studs else stalled + 1
            else:
                stalled += 1

            # release a tick early: crossing the line mid-tick means overshoot
            if travelled + rate * 0.5 >= distance:
                break
            if stalled >= stall_ticks:
                raise Stuck(f"no progress for {stalled} ticks after "
                            f"{travelled:.1f}/{distance:.1f} studs")
            if clock() - t0 > timeout:
                raise Stuck(f"timed out after {travelled:.1f}/{distance:.1f} studs")
    finally:
        vin.release(*keys)

    return WalkResult(distance, odo.displacement, odo.dx, odo.dz,
                      ticks, clock() - t0)
