"""act/camera: the zoom/pitch/yaw tap count, poses put back, and the reset
after a spawn -- plus its one caller (brain/farm's gather view) and the gather
death that now tells the compass (docs/pending/camera.md)."""
from __future__ import annotations

import pytest

from hivemind.act.camera import AXES, HOME, ZOOM_GAP_S, Camera, Pose, yaw_taps
from hivemind.world.bearings import Bearings
from tests.unit.test_farm import (FakeHud, FakeInput, build, clock, honey,  # noqa: F401
                                  pollen, taps)


def cam():
    inp, slept = FakeInput(), []
    return Camera(inp, Bearings(), sleep=slept.append), inp, slept


def test_the_short_way_round():
    assert yaw_taps(0, 2) == 2 and yaw_taps(0, 6) == -2
    assert yaw_taps(6, 0) == 2 and yaw_taps(1, 7) == -2
    assert yaw_taps(0, 4) == 4                      # a half turn goes right
    assert yaw_taps(3, 3) == 0 and yaw_taps(0, 8) == 0


def test_taps_are_counted_and_yaw_is_the_compass():
    c, inp, slept = cam()
    c.tap("zoom", 2)
    c.tap("pitch", -1)
    c.tap("yaw", -1)
    assert taps(inp) == ["o", "o", "pagedown", "comma"]
    assert slept == [ZOOM_GAP_S, ZOOM_GAP_S, AXES["pitch"][2], AXES["yaw"][2]]
    assert c.pose == Pose(zoom=2, pitch=-1, yaw=7)
    assert c.bearings.heading_taps == 7         # one count, the compass's
    c.bearings.turned(2)                        # a route turned it
    assert c.pose.yaw == 1


def test_set_goes_pitch_zoom_yaw_and_leaves_none_axes_alone():
    c, inp, _ = cam()
    c.tap("yaw", 3)
    before = c.set(Pose(zoom=1, pitch=2))
    assert before == Pose(zoom=0, pitch=0, yaw=3)
    assert taps(inp)[3:] == ["pageup", "pageup", "o"]
    c.set(HOME)
    assert taps(inp)[6:] == ["pagedown", "pagedown", "i", "comma", "comma", "comma"]
    assert c.pose == HOME


def test_looking_puts_back_only_what_it_changed_even_on_a_raise():
    c, inp, _ = cam()
    c.tap("pitch", 1)
    with pytest.raises(RuntimeError):
        with c.looking(Pose(zoom=3, yaw=2)):
            assert c.pose == Pose(zoom=3, pitch=1, yaw=2)
            raise RuntimeError("the look failed")
    assert c.pose == Pose(zoom=0, pitch=1, yaw=0)
    assert taps(inp) == ["pageup", "o", "o", "o", "period", "period",
                         "i", "i", "i", "comma", "comma"]


def test_a_spawn_resets_yaw_keeps_zoom_and_pitch_and_is_not_turned_back():
    c, inp, _ = cam()
    with c.looking(Pose(zoom=2, yaw=2)):
        c.bearings.spawned()                    # died inside the look
        assert c.pose == Pose(zoom=2, pitch=0, yaw=0)
    # zoom put back (ASSUMED kept across a respawn); yaw left at spawn heading
    assert c.pose == HOME
    assert taps(inp) == ["o", "o", "period", "period", "i", "i"]
    assert c.bearings.spawns == 1


# ---- the one caller: brain/farm's gather view -------------------------------------

def gather(clock, inp, **kw):
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(640_000),
                          pollen(640_000), pollen(0)],
                  honey_script=[honey(10_000_000), honey(10_450_000)], honey_after_e=True)
    return build(clock, hud, inp=inp, **kw)


def test_the_gather_view_sends_the_same_keys_and_ends_counted_home(clock):
    """Byte for byte what `_swing` sent before it moved here: PageUp x tilt,
    then `o` x zoom 0.15 s apart, and PageDown x tilt then `i` x zoom after."""
    inp = FakeInput()
    loop, _, _, _ = gather(clock, inp, gather_tilt=1, gather_zoom=2)
    loop._swing(True)
    assert taps(inp) == ["pageup", "o", "o"]
    assert loop.camera.pose.zoom == 2 and loop.camera.pose.pitch == 1
    loop._swing(True)                           # asked twice: nothing
    loop._swing(False)
    loop._swing(False)
    assert taps(inp) == ["pageup", "o", "o", "pagedown", "i", "i"]
    assert loop.camera.pose == HOME


# ---- the reset: a gather death is a spawn ------------------------------------------

def test_a_gather_death_puts_the_compass_back_at_spawn_heading(clock):
    """MEASURED before this: after a gather death the compass kept the
    pattern's 270 degrees and the next walk 'squared up' 2 taps right of the
    true heading (12 times in the logs; run-1201 15:34 the Tunnel Bear walk
    ended at the honeycomb wall)."""
    compass = Bearings()
    compass.turned(6)
    hud = FakeHud(clock, [pollen(0), pollen(100_000), pollen(300_000), pollen(0)],
                  honey_script=[honey(1_000_000), honey(1_000_100), honey(1_000_200)])
    loop, _, _, _ = build(clock, hud, bearings=compass)
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.deaths == 1
    assert compass.spawns == 1 and compass.heading_taps == 0


def test_a_link_is_not_a_spawn(clock):
    compass = Bearings()
    compass.turned(6)
    hud = FakeHud(clock, [pollen(0), pollen(100_000), pollen(300_000), pollen(20_000),
                          pollen(60_000), pollen(600_000), pollen(0)],
                  honey_script=[honey(1_000_000), honey(1_000_100), honey(1_000_200),
                                honey(1_000_300), honey(1_300_000)])
    loop, _, _, _ = build(clock, hud, bearings=compass)
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.deaths == 0
    assert compass.spawns == 0


def test_a_held_back_tap_is_not_counted_and_a_raise_keeps_what_went_out():
    """The input says False when the owner's Pause or Take Over holds a key
    back (brain/controls): nothing moved, so nothing is counted -- and the
    undo does not zoom in past where the view started."""
    class Held(FakeInput):
        def tap(self, key, *a, **kw):
            if key == "o" and "o" in taps(self):
                return False                     # held back after the first
            return super().tap(key, *a, **kw)

    c = Camera(Held(), Bearings(), sleep=lambda s: None)
    c.tap("zoom", 3)
    assert taps(c.vin) == ["o"] and c.pose.zoom == 1

    class Breaks(FakeInput):
        def tap(self, key, *a, **kw):
            if len(taps(self)) == 2:
                raise RuntimeError("input gone")
            return super().tap(key, *a, **kw)

    c = Camera(Breaks(), Bearings(), sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        c.tap("pitch", 3)
    assert c.pose.pitch == 2
