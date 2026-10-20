"""Swinging the collecting tool while the bees work.

THE OWNER SPOTTED THIS WHILE WATCHING A LIVE RUN: the bot was not using its
pollen-collecting tool. They are right, and it was costing most of the income.

In Bee Swarm two things gather pollen at once. The bees do it on their own,
which is what the first successful run measured (+780 pollen/sec in the Pine
Tree field). The PLAYER also gathers by swinging a tool at the flowers -- and
the test account owns the Golden Rake, one of the better ones. A bot that never clicks
collects only the bee half.

WHY THIS IS NOT BeeTuxMacro'S CLICKER

`clicker.sh` clicks every 0.3 s, forever, for the whole session. That is a
perfectly periodic signal with zero variance running for hours, which is the
single most distinctive thing any macro on this platform does -- a human's
click intervals are never a delta function. The project plan calls it out by
name as the worst signature in the existing macro and asks for event-driven
clicking with log-normal jitter instead. This is that:

  * it clicks only while gathering, not for the whole session
  * intervals are drawn from a log-normal distribution, which is the shape
    human inter-click intervals actually take -- right-skewed, never negative,
    occasionally long
  * it refuses to click at all unless a caller-supplied gate says the world is
    on screen

THE GATE IS A SAFETY FEATURE, NOT A NICETY. A left click lands wherever the
pointer is. In the world that swings a tool and is free. On a menu it presses
whatever is under the cursor, and the Roblox menu carries **Leave** and **Log
Out** as ordinary buttons. So the same rule the reset path follows applies
here: do not send the input unless something has LOOKED and confirmed the
screen is the world.

MEAN_INTERVAL IS NOT MEASURED ON THIS ACCOUNT. Tools have their own cooldown
and clicking faster than it is wasted motion, but no source in this repo
establishes the Golden Rake's. 0.35 s is close to BeeTuxMacro's 0.3 s, which
is known to work in practice, and it is a parameter so a measurement can
replace it.
"""
from __future__ import annotations

import random
import threading
import time

# See the docstring: near BeeTuxMacro's working 0.3 s, but not measured here.
MEAN_INTERVAL = 0.35
# Spread of the log-normal in log space. 0.35 gives intervals mostly between
# about 0.2 s and 0.7 s with an occasional longer one -- human-shaped rather
# than a metronome.
INTERVAL_SIGMA = 0.35
MIN_INTERVAL = 0.12
# WHERE EVERY SWING LANDS, not wherever the pointer was left. MEASURED
# 2026-10-03 03:01:51 (var/loot_misses/20261003-030153-0.jpg): an item use
# closed the inventory with a click on its button at (27, 128), the pointer
# stayed there, and from then on each swing of the trip pressed that button
# -- the list opened and shut three times a second over the field, and not
# one click swung the tool. The quest menu's read leaves it on (83, 128) the
# same way. So the click carries its own point: the arena floor between the
# dialogs (y 434-623) and the hotbar (y ~980), as the Ant Challenge already
# aims (run_farm ANT_CHALLENGE_POINTER).
SWING_POINT = (960, 880)


class Clicker:
    """Clicks the collecting tool on a jittered interval, while allowed.

    `can_click()` is asked before every single click and must return True for
    one to be sent. It is not cached: a menu can open at any moment, and a
    gate checked once at startup would be worthless a second later.

    Runs on its own thread so gathering can walk at the same time, and is a
    context manager so it cannot outlive the block that started it.
    """

    def __init__(self, vin, can_click=None, mean: float = MEAN_INTERVAL,
                 sigma: float = INTERVAL_SIGMA, rng: random.Random | None = None,
                 sleep=time.sleep, at: tuple[int, int] | None = SWING_POINT):
        self.vin = vin
        self.at = at                  # see SWING_POINT; None clicks in place
        self.can_click = can_click or (lambda: False)
        self.mean = float(mean)
        self.sigma = float(sigma)
        self.rng = rng or random.Random()
        self.sleep = sleep
        # Whether to spread the clicks like a human or run them flat.
        # See interval(); set from safety.jitter via jitter_from().
        self.humanise = True
        self.clicks = 0
        self.refused = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def interval(self) -> float:
        """One interval. Log-normal when humanised, flat when not.

        `safety.jitter` is what chooses, and until now nothing read it. The
        jitter is the whole reason this class exists rather than a `sleep 0.3`
        loop: BeeTuxMacro's `clicker.sh` clicks on a perfect 0.3 s metronome
        for the entire session, and a delta function at 300 ms is the most
        distinctive thing a client can emit. Log-normal is the shape human
        inter-click intervals actually take -- right-skewed, never negative.

        Turning it off is therefore a real choice with a real cost, which is
        why the setting exists and why it defaults to on. Switched off, the
        interval is simply the mean, floored the same way.
        """
        if not self.humanise:
            return max(MIN_INTERVAL, self.mean)
        value = self.rng.lognormvariate(0.0, self.sigma) * self.mean
        return max(MIN_INTERVAL, value)

    def jitter_from(self, settings) -> None:
        """Read `safety.jitter`. Defaults to humanising if it cannot be read."""
        try:
            self.humanise = bool(settings.bool("safety.jitter"))
        except Exception:
            self.humanise = True

    def tick(self) -> bool:
        """One decision. Returns whether a click was actually sent."""
        try:
            allowed = bool(self.can_click())
        except Exception:
            allowed = False           # a broken gate must not start clicking
        if not allowed:
            self.refused += 1
            return False
        if self.at is not None:
            self.vin.click(*self.at)
        else:
            self.vin.click()
        self.clicks += 1
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.interval())

    def start(self) -> "Clicker":
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="hivemind-clicker")
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def describe(self) -> str:
        return (f"{self.clicks} clicks sent, {self.refused} refused because "
                f"the world was not on screen")

    def __enter__(self): return self.start()
    def __exit__(self, *exc): self.stop()
