"""A chase's walk home that pushes against a wall stops, and its pushes are not
walked back (act/chase `_record_leg`). MEASURED 2026-10-12 23:52:57: 24 looks of
"w" into a wall, then the reversal of all 25 legs walked 9 s out of Bamboo
into Blue Flower (var/incidents/20261012-235307-mob-sighting)."""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from hivemind.act import chase


class _WallOdometer:
    """Ground flow that moves for every key but "a": a wall on the way home."""

    def __init__(self):
        self.dx = self.dy = self.travel = 0.0
        self.samples = 0
        self.keys = ""

    def update(self, frame):
        self.samples += 1
        if "a" not in self.keys:
            self.dx -= 20.0 * (("d" in self.keys) - ("a" in self.keys))
            self.travel += 20.0

    def displacement(self):
        return None if self.samples == 0 else (-self.dx, -self.dy)


def test_a_walk_home_into_a_wall_stops_and_does_not_walk_its_pushes_back():
    odo, walked = _WallOdometer(), []

    @contextmanager
    def held(*keys):
        walked.append("".join(keys))
        odo.keys = "".join(keys)
        yield
        odo.keys = ""

    vin = type("Vin", (), {"held": staticmethod(held)})()
    result = chase.ChaseResult()
    for _ in range(2):                    # the detour: two steps right, both moved
        hold = chase._hold(vin, "d", chase.STEP_SECONDS, lambda s: None, lambda: 0, odo)
        chase._record_leg(result, "d", hold)
        result.steps += 1

    home = chase._walk_home_by_looking(result, vin, lambda s: None, lambda m: None,
                                       lambda: 0, None, None, odo, lambda: 0.0)

    assert home is False
    assert walked == ["d", "d", "a", "a"]          # two pushes, not 2 * 2 + 4
    assert result.legs == [("d", chase.STEP_SECONDS)] * 2


def test_under_haste_a_leg_is_walked_back_for_the_seconds_it_was_held():
    # research 2026-10-21: legs were kept as STEP_SECONDS, so at Haste x4 the
    # walk back held each reversed leg 4x the step it undid
    held = chase._step_seconds(4.0)
    assert held < chase.STEP_SECONDS
    result = chase.ChaseResult()
    assert chase._record_leg(result, "w", (5, 0.0, 30.0, 100.0), held)   # it moved
    slept = []

    @contextmanager
    def keys(*k):
        yield

    vin = type("Vin", (), {"held": staticmethod(keys)})()
    chase._walk_back(result, vin, slept.append, lambda m: None)
    assert slept == [held]


def test_a_walk_home_that_stops_just_outside_the_box_would_be_taken_as_home(monkeypatch):
    # research 2026-10-21: run-1164 18:16:17 gave up at +122, +40 px and that
    # one give-up ended the chasing for the trip
    class _Odo:
        def displacement(self):
            return (122.0, 40.0)              # every step lands back near the same spot

    monkeypatch.setattr(chase, "_hold", lambda *a, **k: (5, 1.0, 1.0, 100.0))   # moved
    vin = type("Vin", (), {})()
    said = []

    def walk(live):
        monkeypatch.setattr(chase, "CLOSE_ENOUGH_LIVE", live)
        result, carry = chase.ChaseResult(), [0.0, 0.0]
        result.steps = 1
        home = chase._walk_home_by_looking(result, vin, lambda s: None, said.append,
                                           lambda: None, None, None, _Odo(),
                                           lambda: 0.0, carry=carry)
        return home, carry

    assert walk(False) == (False, [0.0, 0.0])                  # look-only: says it, gives up
    assert any(m.startswith("chase would: take +122, +40 px as home") for m in said)
    assert walk(True) == (True, [122.0, 40.0])                 # live: home, leftover carried


def test_a_walk_home_whose_last_step_lands_in_the_box_is_home(monkeypatch):
    # research 2026-10-21: 22 of 124 give-ups ended with both axes <= 110 px;
    # the box was tested only before each step, never after the last one
    class _Odo:
        n = 0

        def displacement(self):
            self.n += 1
            return (300.0, 0.0) if self.n < 7 else (60.0, -20.0)   # 1 + 6 looks

    monkeypatch.setattr(chase, "_hold", lambda *a, **k: (5, 1.0, 1.0, 100.0))
    result, carry, said = chase.ChaseResult(), [0.0, 0.0], []
    result.steps = 1                                            # 2 * 1 + 4 = 6 looks
    home = chase._walk_home_by_looking(result, type("Vin", (), {})(), lambda s: None,
                                       said.append, lambda: None, None, None, _Odo(),
                                       lambda: 0.0, carry=carry)
    assert home is True
    assert carry == [60.0, -20.0]
    assert not any(m.startswith("gave up") for m in said)


def test_a_carried_leftover_buys_the_walk_home_more_looks(monkeypatch):
    # research 2026-10-21: the 2 * steps + 4 budget ignored the carry
    class _Odo:
        def displacement(self):
            return (500.0, 0.0)                 # +300 px with the carry: never home

    monkeypatch.setattr(chase, "_hold", lambda *a, **k: (5, 1.0, 1.0, 100.0))
    result, said = chase.ChaseResult(), []
    result.steps = 1
    chase._walk_home_by_looking(result, type("Vin", (), {})(), lambda s: None,
                                said.append, lambda: None, None, None, _Odo(),
                                lambda: 0.0, carry=[-200.0, 0.0])
    assert any(m.startswith("gave up homing by sight after 9 looks") for m in said)


class _StrideOdometer:
    """A character whose 'a'/'d' moves STRIDE px per full step (proportional
    to the seconds held) -- wider than the 220 px box."""
    STRIDE = 280.0

    def __init__(self, x):
        self.x = x                           # where we are, relative to home

    def displacement(self):
        return (self.x, 0.0)


def _stride_walk(monkeypatch, live, start=168.0):
    odo, said, holds = _StrideOdometer(start), [], []

    def hold(vin, keys, seconds, sleep, frames, odometer):
        move = _StrideOdometer.STRIDE * seconds / chase.STEP_SECONDS
        move *= ("d" in keys) - ("a" in keys)
        odo.x += move
        holds.append((keys, round(seconds, 3)))
        return (5, -move, 0.0, abs(move))    # the ground moves the other way

    monkeypatch.setattr(chase, "_hold", hold)
    monkeypatch.setattr(chase, "PROPORTIONAL_HOME_LIVE", live)
    # the step sizing alone: close-enough (live since 2026-10-22) would end the bounce
    monkeypatch.setattr(chase, "CLOSE_ENOUGH_LIVE", False)
    result = chase.ChaseResult()
    result.steps = 1
    home = chase._walk_home_by_looking(result, type("Vin", (), {})(), lambda s: None,
                                       said.append, lambda: None, None, None, odo,
                                       lambda: 0.0)
    return home, holds, said


def test_a_fixed_step_wider_than_the_box_oscillates_and_a_sized_one_lands(monkeypatch):
    # research 2026-10-21: give-ups were x-only, |dx| median 168 px, both signs
    home, holds, said = _stride_walk(monkeypatch, live=False)
    assert home is False                                  # +168, -112, +168, ...
    assert len(holds) == 6
    assert any(m.startswith("chase would: hold") and "last step x 280" in m for m in said)
    assert "last step x 280" in [m for m in said if m.startswith("gave up")][0]

    home, holds, said = _stride_walk(monkeypatch, live=True)
    assert home is True
    assert holds == [("a", chase.STEP_SECONDS),           # one full, one sized
                     ("d", pytest.approx(0.4 * chase.STEP_SECONDS))]


def test_a_sized_step_presses_no_key_on_an_axis_already_inside_the_box():
    keys, _ = chase._proportional_step(-211.0, -46.0, chase.STEP_SECONDS, None)
    assert chase.keys_towards(211.0, 46.0) == "sd"        # the crab it replaces
    assert keys == "d"
    # and is never shorter than MIN_STEP_FRACTION of a step
    last = ("d", chase.STEP_SECONDS, (5, -280.0, 0.0, 280.0))
    _, held = chase._proportional_step(-120.0, 0.0, chase.STEP_SECONDS, last)
    assert abs(held - chase.STEP_SECONDS * 120 / 280) < 1e-9
    _, held = chase._proportional_step(-20.0, -130.0, 0.1, ("w", 0.1, (5, 0.0, 800.0, 800.0)))
    assert held == chase.MIN_STEP_FRACTION * 0.1


def test_a_diagonal_step_is_rescaled_before_sizing_a_straight_one():
    # "sd" moved 200 px on x in a full step: a straight "d" moves ~283 px a step
    last = ("sd", chase.STEP_SECONDS, (5, -200.0, -200.0, 283.0))
    _, held = chase._proportional_step(-150.0, 0.0, chase.STEP_SECONDS, last)
    assert held == pytest.approx(chase.STEP_SECONDS * 150 / (200 / chase.DIAGONAL_AXIS_SHARE))


def test_the_drift_walk_back_whose_last_look_lands_in_the_box_is_home(monkeypatch):
    # run_farm's gather-drift caller: steps=0, no carry, RETURN_LOOKS looks
    class _Odo:
        n = 0

        def displacement(self):
            self.n += 1
            return (300.0, 0.0) if self.n <= chase.RETURN_LOOKS else (60.0, -20.0)

    monkeypatch.setattr(chase, "_hold", lambda *a, **k: (5, 1.0, 1.0, 100.0))
    said = []
    home = chase._walk_home_by_looking(chase.ChaseResult(), type("Vin", (), {})(),
                                       lambda s: None, said.append, lambda: None, None,
                                       None, _Odo(), lambda: 0.0)
    assert home is True
    assert any(m.startswith(f"home by sight after {chase.RETURN_LOOKS} step(s)") for m in said)
