"""Measuring how fast we are really going, without a calibration."""
from __future__ import annotations

from hivemind.nav.pace import PaceMeter


def teach(meter, keys="w", rate=20.0, n=20):
    for _ in range(n):
        meter.observe(keys, flow_px=rate, seconds=1.0)
    return meter


def test_it_refuses_to_correct_until_it_has_a_baseline():
    """A recorded timing is better than a correction from two samples."""
    meter = PaceMeter()
    meter.observe("w", flow_px=20.0, seconds=1.0)
    meter.observe("w", flow_px=20.0, seconds=1.0)
    assert meter.baseline("w") is None
    assert meter.multiplier("w", flow_px=40.0, seconds=1.0) == 1.0


def test_it_spots_moving_faster_than_usual():
    """This is haste: the same hold now covers more ground."""
    meter = teach(PaceMeter())
    assert abs(meter.multiplier("w", flow_px=28.0, seconds=1.0) - 1.4) < 0.01


def test_it_spots_moving_slower_than_usual():
    meter = teach(PaceMeter())
    assert abs(meter.multiplier("w", flow_px=16.0, seconds=1.0) - 0.8) < 0.01


def test_keys_are_kept_apart():
    """Strafing and walking forward show different flow at the same speed, so
    one baseline for both would be meaningless."""
    meter = PaceMeter()
    teach(meter, "w", 20.0)
    teach(meter, "a", 50.0)
    assert meter.baseline("w") != meter.baseline("a")
    assert meter.multiplier("a", flow_px=50.0, seconds=1.0) == 1.0


def test_an_unbelievable_reading_is_ignored_not_obeyed():
    """A wall filling the view slides fast; that is not the character moving.

    Obeying it would turn a 300-stud walk into a 30-stud one, which is a
    worse failure than the drift this is meant to fix.
    """
    meter = teach(PaceMeter())
    assert meter.multiplier("w", flow_px=400.0, seconds=1.0) == 1.0
    assert meter.multiplier("w", flow_px=1.0, seconds=1.0) == 1.0


def test_noise_is_not_movement():
    meter = PaceMeter()
    for _ in range(40):
        meter.observe("w", flow_px=0.1, seconds=1.0)
    assert meter.baseline("w") is None, "standing still became a baseline"


def test_an_unknown_key_combination_never_corrects():
    meter = teach(PaceMeter())
    assert meter.multiplier("sd", flow_px=99.0, seconds=1.0) == 1.0


def test_it_says_when_it_has_nothing_to_say():
    assert "no baseline yet" in PaceMeter().describe()
    assert "baseline px/s" in teach(PaceMeter()).describe()
