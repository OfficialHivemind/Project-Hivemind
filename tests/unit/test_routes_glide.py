"""The Pine Tree glide, held as long as the owner's move.glide_scale says (act/routes GLIDES)."""
from __future__ import annotations

import pytest

from hivemind.act import routes
from hivemind.act.routes import RouteRunner
from hivemind.nav.router import Edge, Router


class Input:
    def __init__(self):
        self.events, self.held = [], set()

    def press(self, *keys):
        self.held.update(keys)
        self.events.append(("press", keys))

    def release(self, *keys):
        self.held.difference_update(keys)
        self.events.append(("release", keys))

    def tap(self, key):
        self.events.append(("tap", key))

    def release_all(self):
        self.held.clear()

    def move_mouse(self, x, y):
        pass


FLIGHT = [
    {"op": "key_down", "keys": "e"}, {"op": "pause", "seconds": 0.1}, {"op": "key_up", "keys": "e"},
    {"op": "key_down", "keys": "ds"}, {"op": "pause", "seconds": 0.925},
    {"op": "jump"}, {"op": "jump"}, {"op": "pause", "seconds": 4.5},
    {"op": "key_up", "keys": "s"}, {"op": "pause", "seconds": 0.5},
    {"op": "key_up", "keys": "d"}, {"op": "jump"},
    {"op": "camera", "direction": "left"}, {"op": "pause", "seconds": 2.0},
]
NATROS = (0.1, 0.925, 0.5, 2.0)


def _fly(monkeypatch, name, scale, factor=1.0, side=None):
    slept = []
    monkeypatch.setattr(routes.time, "sleep", lambda s: slept.append(round(s, 3)))
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge(name, "hive", "pine_tree", 286.7, steps=[dict(s) for s in FLIGHT]))
    runner = RouteRunner(Input(), r, walkspeed=28.0, movespeed_factor=lambda: factor,
                         glide_scale=scale, glide_side_scale=side)
    result = runner.run(name)
    pauses = [s for s in slept if s in NATROS or s > 1.0]
    result.slept = slept
    return pauses, result


def test_the_glide_alone_is_held_for_the_scale(monkeypatch):
    pauses, result = _fly(monkeypatch, "natro_out_pine_tree_via_red_cannon", lambda: 0.8)
    assert pytest.approx(4.5 * 0.8, abs=0.002) in pauses
    assert 4.5 not in pauses
    for natro in NATROS:                     # the launch, the d after and the settle keep Natro's
        assert natro in pauses
    assert any("glide: held 3.60s, not Natro's 4.50s (move.glide_scale 0.8)" in n
               for n in result.notes)


def test_at_one_it_is_natros_timing_and_says_nothing(monkeypatch):
    pauses, result = _fly(monkeypatch, "natro_out_pine_tree_via_red_cannon", lambda: 1.0)
    assert 4.5 in pauses
    assert not any("glide:" in n for n in result.notes)


def test_haste_does_not_change_it(monkeypatch):
    """The buff bar's speed was the wrong premise (GLIDES' note); only the scale moves it."""
    pauses, _ = _fly(monkeypatch, "natro_out_pine_tree_via_red_cannon", lambda: 1.0, factor=1.5)
    assert 4.5 in pauses and 0.925 in pauses and 0.5 in pauses


def _broken():
    raise RuntimeError("no settings")


@pytest.mark.parametrize("scale", [None, _broken, lambda: "x", lambda: 0.0, lambda: -1.0])
def test_unset_or_unreadable_is_natros(monkeypatch, scale):
    pauses, _ = _fly(monkeypatch, "natro_out_pine_tree_via_red_cannon", scale)
    assert 4.5 in pauses


def test_a_value_past_its_bounds_is_held_at_the_bound(monkeypatch):
    low, high = routes.GLIDE_SCALE_BOUNDS
    pauses, _ = _fly(monkeypatch, "natro_out_pine_tree_via_red_cannon", lambda: 0.01)
    assert pytest.approx(4.5 * low, abs=0.002) in pauses
    pauses, _ = _fly(monkeypatch, "natro_out_pine_tree_via_red_cannon", lambda: 9.0)
    assert pytest.approx(4.5 * high, abs=0.002) in pauses


def test_other_flights_keep_natros_glide(monkeypatch):
    pauses, result = _fly(monkeypatch, "natro_out_pineapple_via_red_cannon", lambda: 0.8)
    assert 4.5 in pauses and 0.925 in pauses
    assert not any("glide:" in n for n in result.notes)


def test_the_setting_is_read_at_every_use():
    from hivemind.world import settings as st
    assert "move.glide_scale" in st.READ_AT_EVERY_USE
    assert st.defaults()["move.glide_scale"] == 0.8        # MEASURED onto the flowers
    assert st.BOUNDS["move.glide_scale"][:2] == routes.GLIDE_SCALE_BOUNDS


# --- the sideways finish (GLIDE_SIDES, move.glide_side_scale) -------------------

def test_the_side_finish_alone_is_held_for_its_scale(monkeypatch):
    pauses, result = _fly(monkeypatch, "natro_out_pine_tree_via_red_cannon", lambda: 0.8,
                          side=lambda: 2.0)
    assert pytest.approx(4.5 * 0.8, abs=0.002) in pauses      # the glide's own knob
    assert 1.0 in result.slept                                # 0.5 s x 2
    assert 0.5 not in result.slept
    assert 0.925 in pauses and 0.1 in pauses and 2.0 in pauses
    assert any("glide: side held 1.00s, not Natro's 0.50s (move.glide_side_scale 2)" in n
               for n in result.notes)


def test_the_side_finish_at_one_says_nothing(monkeypatch):
    pauses, result = _fly(monkeypatch, "natro_out_pine_tree_via_red_cannon", lambda: 1.0,
                          side=lambda: 1.0)
    assert 0.5 in pauses
    assert not any("side held" in n for n in result.notes)


def test_the_side_finish_is_held_within_its_bounds(monkeypatch):
    low, high = routes.GLIDE_SIDE_BOUNDS
    _, result = _fly(monkeypatch, "natro_out_pine_tree_via_red_cannon", None, side=lambda: 99)
    assert any(f"side held {0.5 * high:.2f}s" in n for n in result.notes)
    _, result = _fly(monkeypatch, "natro_out_pine_tree_via_red_cannon", None, side=lambda: 0.1)
    assert any(f"side held {0.5 * low:.2f}s" in n for n in result.notes)
    assert round(0.5 * low, 3) in result.slept


def test_other_flights_keep_natros_side_finish(monkeypatch):
    pauses, result = _fly(monkeypatch, "natro_out_pineapple_via_red_cannon", None,
                          side=lambda: 3.0)
    assert 0.5 in pauses
    assert not any("glide:" in n for n in result.notes)


def test_the_side_setting_is_read_at_every_use():
    from hivemind.world import settings as st
    assert "move.glide_side_scale" in st.READ_AT_EVERY_USE
    assert st.defaults()["move.glide_side_scale"] == 2.0
    assert st.BOUNDS["move.glide_side_scale"][:2] == routes.GLIDE_SIDE_BOUNDS


# --- the walk home's glide (GLIDE_COASTS, move.home_glide_at_base) ----------------

HOME = [                         # natro_home_pine_tree's glide, from its run-up
    {"op": "key_down", "keys": "w"}, {"op": "coast", "studs": 24.0},
    {"op": "jump_hold"}, {"op": "pause", "seconds": 0.2}, {"op": "jump_release"},
    {"op": "coast", "studs": 432.0}, {"op": "key_up", "keys": "w"},
]


def _home(monkeypatch, name, at_base, factor=1.4, walkspeed=28.0):
    slept = []
    monkeypatch.setattr(routes.time, "sleep", lambda s: slept.append(round(s, 2)))
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge(name, "pine_tree", "hive", 816.8, steps=[dict(s) for s in HOME]))
    runner = RouteRunner(Input(), r, walkspeed=walkspeed, movespeed_factor=lambda: factor,
                         glide_at_base=at_base)
    result = runner.run(name)
    return slept, result


def test_the_home_glide_is_coasted_at_base_speed_under_a_buff(monkeypatch):
    slept, result = _home(monkeypatch, "natro_home_pine_tree", lambda: True)
    assert round(432 / 28.0, 2) in slept                  # 15.43 s, the buff left out
    assert round(432 / (28.0 * 1.4), 2) not in slept
    assert round(24 / (28.0 * 1.4), 2) in slept           # the run-up is a walk: buffed
    assert any("glide: coasted 432 studs for 15.43s at base speed, not 11.02s at the "
               "buff bar's 1.40x" in n for n in result.notes)


def test_off_it_is_timed_by_the_buff_as_before(monkeypatch):
    slept, result = _home(monkeypatch, "natro_home_pine_tree", lambda: False)
    assert round(432 / (28.0 * 1.4), 2) in slept
    assert not any("glide:" in n for n in result.notes)


def _broken_flag():
    raise RuntimeError("no settings")


def test_unset_or_unreadable_is_off(monkeypatch):
    for flag in (None, _broken_flag):
        slept, _ = _home(monkeypatch, "natro_home_pine_tree", flag)
        assert round(432 / (28.0 * 1.4), 2) in slept


def test_without_a_buff_it_says_nothing(monkeypatch):
    slept, result = _home(monkeypatch, "natro_home_pine_tree", lambda: True, factor=1.0)
    assert round(432 / 28.0, 2) in slept
    assert not any("glide:" in n for n in result.notes)


def test_another_routes_coast_keeps_its_buffed_timing(monkeypatch):
    slept, result = _home(monkeypatch, "natro_home_mushroom", lambda: True)
    assert round(432 / (28.0 * 1.4), 2) in slept
    assert not any("glide:" in n for n in result.notes)


def test_the_home_glide_setting_is_read_at_every_use_and_on_by_default():
    """On since a glide under a polar bear morph landed on the pad (run-562)."""
    from hivemind.world import settings as st
    assert "move.home_glide_at_base" in st.READ_AT_EVERY_USE
    assert st.defaults()["move.home_glide_at_base"] is True
    assert routes.GLIDE_COASTS == {"natro_home_pine_tree": 432.0}


def test_the_glide_keeps_its_own_speed_when_walkspeed_rises(monkeypatch):
    # move.walkspeed 32.2 for the gifted Hasty Bee (2026-10-09): the walk is
    # faster, the glider is not -- the coast stays the proven 15.43 s
    slept, _ = _home(monkeypatch, "natro_home_pine_tree", lambda: True, factor=1.0,
                     walkspeed=32.2)
    assert round(432 / 28.0, 2) in slept
    assert round(24 / 32.2, 2) in slept                   # the run-up walks at 32.2
