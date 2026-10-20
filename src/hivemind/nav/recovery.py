"""Getting unstuck, in escalating order of how much it costs.

A closed-loop walker detects being stuck quickly -- zero measured displacement
while a key is held means something is in the way. Detecting it is the easy part.
Choosing what to do about it is where macros go wrong in both directions: too
timid and the character grinds against a rock for hours, too aggressive and it
resets to spawn over a pebble and loses a forty-second walk.

So recovery is a LADDER, tried in order, each rung costing more than the last:

    1 jump          most obstacles in this game are ankle height
    2 sidestep      strafe out of a corner, then resume
    3 back off      reverse, then approach at a different angle
    4 reorient      turn the camera; the heading may be the problem
    5 reset         teleport to spawn. Loses all position, so it is LAST

The ladder resets on success, because the next obstacle is a different obstacle
and should get the cheap treatment first. It does NOT reset on a failed rung,
because retrying a jump that just failed is how a bot spends an hour jumping.

Rung 5 is special and is why this module knows about beliefs at all. A character
reset teleports to spawn, which makes every position-derived belief instantly
false -- and a bot that keeps navigating from a stale position after a reset
walks confidently in the wrong direction. So `reset` INVALIDATES those beliefs
rather than merely noting the event.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol


class Rung(str, Enum):
    JUMP = "jump"
    SIDESTEP = "sidestep"
    BACK_OFF = "back_off"
    REORIENT = "reorient"
    RESET = "reset"


# Ordered cheapest-first. The cost is what a failed attempt WASTES, which is not
# the same as how long the manoeuvre takes. Reorienting occupies only 1.2 s of
# wall clock but turns the camera, and every heading the navigator holds is
# relative to that camera -- so the real cost includes re-establishing which way
# is forward. Pricing it by its stopwatch time alone put it above two rungs that
# disturb less, which a test caught.
LADDER: tuple[tuple[Rung, float], ...] = (
    (Rung.JUMP, 0.6),        # most obstacles here are ankle height
    (Rung.SIDESTEP, 1.4),    # strafe out of a corner; heading is preserved
    (Rung.BACK_OFF, 2.0),    # reverse and re-approach; heading is preserved
    (Rung.REORIENT, 3.0),    # 1.2 s of turning, plus re-establishing heading
    (Rung.RESET, 45.0),      # teleports to spawn; loses the whole walk
)

# Beliefs that a character reset makes instantly false.
POSITION_BELIEFS = ("position", "field", "near_landmark", "heading")


class InputLike(Protocol):
    def press(self, *keys: str) -> None: ...
    def release(self, *keys: str) -> None: ...
    def tap(self, key: str, ms: int = 40) -> None: ...


@dataclass
class Attempt:
    rung: Rung
    at: float
    worked: bool | None = None       # None until the caller reports back


@dataclass
class Recovery:
    """Escalating unstick strategy with a memory of what has been tried."""

    inp: InputLike
    beliefs: object | None = None            # a BeliefStore, when available
    on_reset: Callable[[], None] | None = None
    history: list[Attempt] = field(default_factory=list)
    _step: int = 0

    # ---- choosing ---------------------------------------------------------
    @property
    def exhausted(self) -> bool:
        return self._step >= len(LADDER)

    def next_rung(self) -> Rung | None:
        return LADDER[self._step][0] if not self.exhausted else None

    def cost_so_far(self) -> float:
        return sum(cost for rung, cost in LADDER[: self._step])

    def succeeded(self) -> None:
        """Whatever we tried worked. The next obstacle starts cheap again."""
        if self.history:
            self.history[-1].worked = True
        self._step = 0

    def failed(self) -> None:
        """That rung did not work. Escalate rather than repeat it."""
        if self.history:
            self.history[-1].worked = False
        self._step += 1

    def reset_ladder(self) -> None:
        self._step = 0

    # ---- doing ------------------------------------------------------------
    def attempt(self, heading: str = "w", now: float | None = None) -> Rung | None:
        """Perform the next rung. Returns which one, or None when exhausted.

        The caller walks again afterwards and reports back with `succeeded()`
        or `failed()`; this module deliberately does not decide whether it
        worked, because only the odometer can tell.
        """
        rung = self.next_rung()
        if rung is None:
            return None
        self.history.append(Attempt(rung, time.time() if now is None else now))

        if rung is Rung.JUMP:
            self.inp.tap("space", ms=90)
            time.sleep(0.45)
        elif rung is Rung.SIDESTEP:
            side = "d" if len(self.history) % 2 else "a"
            self._hold(side, 0.55)
        elif rung is Rung.BACK_OFF:
            self._hold(self._opposite(heading), 0.8)
            self._hold("d" if len(self.history) % 2 else "a", 0.4)
        elif rung is Rung.REORIENT:
            # a short turn; the obstacle may only block this exact heading
            self.inp.tap("right", ms=220)
            time.sleep(0.3)
        elif rung is Rung.RESET:
            self._character_reset()
        return rung

    def _hold(self, key: str, seconds: float) -> None:
        self.inp.press(key)
        try:
            time.sleep(seconds)
        finally:
            self.inp.release(key)        # never leave a key held, even on error

    @staticmethod
    def _opposite(heading: str) -> str:
        flip = {"w": "s", "s": "w", "a": "d", "d": "a"}
        return "".join(flip.get(c, c) for c in heading)

    def _character_reset(self) -> None:
        """Teleport to spawn, and forget everything that depended on being here.

        This is the rung that costs a whole walk, and the one that silently
        breaks navigation if its consequences are not recorded: after a reset the
        bot is somewhere else entirely, so any position belief it keeps acting on
        points the wrong way.
        """
        if self.beliefs is not None:
            for name in POSITION_BELIEFS:
                try:
                    self.beliefs.invalidate(name)
                except Exception:
                    pass
        if self.on_reset:
            self.on_reset()

    # ---- reporting --------------------------------------------------------
    def describe(self) -> str:
        rung = self.next_rung()
        if rung is None:
            return ("every recovery has been tried and none worked — "
                    "this needs a human")
        return (f"stuck: trying {rung.value} "
                f"(rung {self._step + 1} of {len(LADDER)}, "
                f"{self.cost_so_far():.1f}s spent so far)")

    @property
    def resets(self) -> int:
        return sum(1 for a in self.history if a.rung is Rung.RESET)
