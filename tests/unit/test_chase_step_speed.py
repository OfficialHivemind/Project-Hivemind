"""A chase step under a speed buff is shorter, so it covers about the same ground
(act/chase._step_seconds; measured 2026-10-14: reach fell under Haste)."""
from __future__ import annotations

from hivemind.act import chase


def test_the_step_is_divided_by_the_speed_factor():
    base = chase.STEP_SECONDS
    assert chase._step_seconds(None) == base
    assert abs(chase._step_seconds(lambda: 2.0) - base / 2) < 1e-9
    assert abs(chase._step_seconds(2.0) - base / 2) < 1e-9


def test_a_bad_or_wild_reading_is_bounded():
    base = chase.STEP_SECONDS
    assert chase._step_seconds(lambda: 0.5) == base          # never longer than base
    assert chase._step_seconds(lambda: 40.0) == base / 4     # never under a quarter

    def broken():
        raise RuntimeError("no buff bar")
    assert chase._step_seconds(broken) == base
