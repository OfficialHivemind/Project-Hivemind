"""The camera sweep for bubbles (act/camsweep, gather.rotate_camera): it gives
the heading back to the tap, turns nothing off the anchor, and the setting
gates it -- including the owner's old saved `true` from the dead bool."""
from __future__ import annotations

from hivemind.act import camsweep
from hivemind.brain.farm import Cycle
from hivemind.world import settings as settings_mod


class Compass:
    """run_farm's turn_camera as the walk home sees it: a tap count mod 8."""

    def __init__(self, at=3):
        self.heading, self.taps = at, []

    def turn(self, taps):
        self.taps.append(taps)
        self.heading = (self.heading + taps) % 8


def test_the_sweep_restores_the_heading():
    for width in (1, 2, 3):
        c = Compass()
        turned = camsweep.sweep(c.turn, at_anchor=True, taps=width, sleep=lambda s: None)
        assert turned == 4 * width and sum(c.taps) == 0 and c.heading == 3
        assert min(c.taps) == -1 and max(c.taps) == 1      # one tap at a time
    assert sum(camsweep.plan()) == 0


def test_stopped_or_raising_mid_sweep_still_gives_the_taps_back():
    for cut in range(1, 4):
        c, n = Compass(), {"i": 0}

        def stopped(cut=cut):
            n["i"] += 1
            return n["i"] > cut
        camsweep.sweep(c.turn, at_anchor=True, stopped=stopped, sleep=lambda s: None)
        assert c.heading == 3 and sum(c.taps) == 0
    c, calls = Compass(), {"n": 0}

    def flaky(taps):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("input died")
        c.turn(taps)
    try:
        camsweep.sweep(flaky, at_anchor=True, sleep=lambda s: None)
    except RuntimeError:
        pass
    assert c.heading == 3


def test_only_at_the_anchor():
    c = Compass()
    assert camsweep.sweep(c.turn, at_anchor=False, sleep=lambda s: None) == 0
    assert c.taps == []


def test_the_setting_gates_it():
    assert not camsweep.wanted("never", 1)
    assert not camsweep.wanted(True, 1)             # the dead bool's saved value
    assert not camsweep.wanted("typo", 1)
    assert camsweep.wanted("every pass", 2)
    assert camsweep.wanted("every other trip (A/B)", 3)
    assert not camsweep.wanted("every other trip (A/B)", 4)
    # the schema: wired, a choice of exactly camsweep's modes, default off
    key = "gather.rotate_camera"
    assert settings_mod.wired(key)
    assert settings_mod.defaults()[key] == camsweep.NEVER
    row = next(r for _s, rows in settings_mod.SECTIONS for r in rows if r[0] == key)
    assert row[2] == "choice" and tuple(row[5]) == camsweep.MODES


def test_the_old_saved_true_reads_never(tmp_path):
    f = tmp_path / "settings.yaml"
    f.write_text("gather.rotate_camera: true\n")
    s = settings_mod.Settings(f)
    assert s.get("gather.rotate_camera") == camsweep.NEVER


def test_the_trip_line_says_it_only_when_on():
    cyc = Cycle(number=1)
    assert "camera sweep" not in cyc.describe()
    cyc.camera_sweeps = 0
    assert "camera sweep: 0" in cyc.describe()
