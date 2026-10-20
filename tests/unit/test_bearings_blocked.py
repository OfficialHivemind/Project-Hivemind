""""Pushing against something" is a claim about now (world/bearings).

run-531, 2026-09-28: a leg that ended against the red cannon left the claim
standing for 894 s through a bug run and a whole gather, because the route
runner reports motion only while a key is held.
"""
from __future__ import annotations

from hivemind.world import bearings
from hivemind.world.bearings import Bearings


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_a_push_is_timed_while_the_reports_come():
    clock = Clock()
    b = Bearings(clock=clock)
    for _ in range(30):                   # 3 s of blocked reports at the runner's 10 Hz
        b.saw_motion("w", 0.0)
        clock.t += 0.1
    assert 2.8 <= b.blocked_seconds <= 3.1


def test_the_claim_lapses_when_the_reports_stop():
    clock = Clock()
    b = Bearings(clock=clock)
    b.saw_motion("w", 0.0)
    clock.t += 1.0
    b.saw_motion("w", 0.0)
    clock.t += bearings.MOTION_FRESH_S + 0.5          # the hold ended, nothing reports
    assert b.blocked_seconds == 0.0
    assert "pushing against something" not in b.describe() if hasattr(b, "describe") else True


def test_moving_again_clears_it():
    clock = Clock()
    b = Bearings(clock=clock)
    b.saw_motion("w", 0.0)
    clock.t += 1.0
    b.saw_motion("w", 50.0)
    assert b.blocked_seconds == 0.0
