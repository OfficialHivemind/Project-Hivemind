"""A22b: the walk home's speed timed off the ground; A22c: no flowers in any
direction means no timed route."""
from pathlib import Path

import pytest

import hivemind
from hivemind.act import motion
from hivemind.act.drift import LookRound


@pytest.fixture(autouse=True)
def _probe_applies(monkeypatch):
    """The scaling mechanism is tested switched ON; live it is look-only."""
    from hivemind.act import motion as _m
    monkeypatch.setattr(_m, "PROBE_APPLIES", True)


def test_live_default_is_look_only():
    """2026-10-16 07:41: a 0.49x reading stretched the legs and cost a rejoin."""
    import importlib
    from hivemind.act import motion as _m
    src = importlib.util.find_spec(_m.__name__).origin
    assert "PROBE_APPLIES = False" in open(src).read()


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def probe_rate(probe, clock, keys, px, n=10, dt=0.1):
    said = None
    for _ in range(n):
        said = probe.saw(keys, px) or said
        clock.t += dt
    return said


def test_trim_is_measured_over_expected_within_bounds():
    assert motion.trim_for(1.8, 2.0) == 0.9
    assert motion.trim_for(0.5, 2.0) == motion.PROBE_TRIM_BOUNDS[0]
    assert motion.trim_for(4.0, 1.8) == motion.PROBE_TRIM_BOUNDS[1]


def test_calm_walk_sets_the_baseline_then_haste_is_trimmed_to_it():
    clock = Clock()
    probe = motion.SpeedProbe(clock=clock)
    probe.begin("natro_home_blue_flower", 1.0)
    assert probe_rate(probe, clock, "w", 15.0) is None      # calm: baseline only
    assert probe.trim == 1.0
    probe.begin("natro_home_blue_flower", 2.0)               # icon: x10
    said = probe_rate(probe, clock, "w", 27.0)               # ground: 1.8x
    assert abs(probe.trim - 0.9) < 1e-9
    assert "measured 1.80x" in said and "icon said 2.00x" in said
    probe.begin(None, 1.0)                                   # next route: reset
    assert probe.trim == 1.0


def test_no_measurement_keeps_the_icon():
    clock = Clock()
    probe = motion.SpeedProbe(clock=clock)
    probe.begin("natro_home_pine_tree", 2.0)                 # no calm baseline
    assert "no calm walk" in probe_rate(probe, clock, "w", 30.0)
    assert probe.trim == 1.0
    probe.calm["natro_home_pine_tree"] = [15.0]
    probe.begin("natro_home_pine_tree", 2.0)
    probe.saw("w", 30.0)
    clock.t += 0.1
    assert "could not time" in probe.saw("a", 30.0)          # first hold ended early
    assert probe.trim == 1.0
    probe.begin("natro_home_pine_tree", 1.5)                 # x5: not probed
    assert probe_rate(probe, clock, "w", 30.0) is None and probe.trim == 1.0


def test_no_flowers_anywhere_is_nowhere():
    assert LookRound(shares={0: 0.0, 2: 0.0, 4: 0.004, 6: None}).nowhere
    assert not LookRound(shares={0: 0.0, 2: 0.3, 4: 0.0, 6: 0.0}).nowhere
    assert not LookRound(shares={0: None, 2: None}).nowhere   # unread: not known


def test_nowhere_takes_the_homing_branch_not_the_route():
    src = (Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py").read_text()
    assert "no_flowers = seen.nowhere" in src
    # the off-field branch: row search, then homing by sight, no route
    assert "elif off_field or no_flowers:" in src
