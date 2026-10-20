"""Haste's per-stack gain: Natro's 10%, or the measured ~7% (vision/buffs
HASTE_GAIN; MEASURED 2026-10-14 over the ramp walks' "met the ramp after N
studs"). The runner divides every timed walk by this factor."""
from __future__ import annotations

import pytest

from hivemind.vision import buffs


def test_the_gain_switch(monkeypatch):
    x10 = buffs.Haste(present=True, stacks=10)
    monkeypatch.setattr(buffs, "HASTE_GAIN", "off")
    assert x10.factor == pytest.approx(2.0) and "measured" not in x10.describe()
    monkeypatch.setattr(buffs, "HASTE_GAIN", "on")
    assert x10.factor == pytest.approx(1.68)
    assert "at the measured 6.8% a stack" in x10.describe()
    # with a bear, as the runner multiplies them: 11:16's "2.25x" is ~1.89x
    bear = buffs.Bear(present=True, kind="black")
    assert x10.factor * bear.factor(32.2) == pytest.approx(1.889, abs=0.005)
    assert buffs.Haste(present=False, stacks=None).factor == 1.0
