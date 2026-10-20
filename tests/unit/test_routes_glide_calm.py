"""W4: the Pine Tree walk home's run-up waits out a strong Haste (act/routes GLIDE_CALM)."""
from __future__ import annotations

import time as real_time
import types

from hivemind.act import routes
from hivemind.act.routes import RouteRunner
from hivemind.nav.router import Edge, Router

HOME = [                         # natro_home_pine_tree's glide, from its run-up
    {"op": "key_down", "keys": "w"}, {"op": "coast", "studs": 24.0},
    {"op": "jump_hold"}, {"op": "pause", "seconds": 0.2}, {"op": "jump_release"},
    {"op": "coast", "studs": 432.0}, {"op": "key_up", "keys": "w"},
]


class Input:
    def __init__(self):
        self.events = []
        self.pressed_at = []                          # routes' (fake) clock at each press

    def press(self, *keys):
        self.events.append(("press", keys))
        self.pressed_at.append(routes.time.monotonic())

    def release(self, *keys):
        self.events.append(("release", keys))

    def tap(self, key):
        self.events.append(("tap", key))

    def release_all(self):
        pass


def _home(monkeypatch, factors, name="natro_home_pine_tree", at_base=True, calm="on",
          changes=None, strict="off"):
    """Run the glide with the buff bar reading `factors` in turn (the last one sticks)."""
    reads = list(factors)
    clock = [100.0]                                   # past the factor cache's start
    monkeypatch.setattr(routes, "GLIDE_CALM", calm)
    monkeypatch.setattr(routes, "GLIDE_CALM_STRICT", strict)   # not by the clock's hour
    fake = types.SimpleNamespace(**{k: getattr(real_time, k) for k in dir(real_time)
                                    if not k.startswith("_")})
    fake.sleep = lambda s: clock.__setitem__(0, clock[0] + s)
    fake.monotonic = lambda: clock[0]                 # the factor cache's clock, too
    monkeypatch.setattr(routes, "time", fake)         # routes' own clock only
    vin = Input()
    seen = []

    def factor():
        f = reads.pop(0) if len(reads) > 1 else reads[0]
        seen.append((clock[0], f))
        return f

    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge(name, "pine_tree", "hive", 816.8, steps=[dict(s) for s in HOME]))
    runner = RouteRunner(vin, r, walkspeed=32.2, movespeed_factor=factor,
                         movespeed_changes=(lambda: changes) if changes else None,
                         glide_at_base=lambda: at_base)
    result = runner.run(name)
    return result, vin, seen


def test_a_strong_haste_is_waited_out_before_w_goes_down(monkeypatch):
    result, vin, seen = _home(monkeypatch, [2.0, 2.0, 2.0, 1.0])
    assert [f for _, f in seen][:4] == [2.0, 2.0, 2.0, 1.0]  # re-read every poll
    waits = [n for n in result.notes if "at the run-up" in n]
    assert waits and "2.00x to drop -- 1.00x at the jump" in waits[0]
    assert "jumped anyway" not in waits[0]
    assert vin.events[0] == ("press", ("w",))       # nothing pressed while it waited
    assert result.ok


def test_a_small_buff_jumps_at_once(monkeypatch):
    """1.10-1.20x landed 6 of 6 at walkspeed 32.2 (runs 813-900)."""
    result, _, _ = _home(monkeypatch, [1.2])
    assert not any("waited" in n for n in result.notes)
    assert any("1.20x at the run-up, at or under 1.25x: jumped at once" in n
               for n in result.notes)                 # the A/B's lenient arm, logged


def test_the_strict_arm_waits_out_a_small_buff(monkeypatch):
    """GLIDE_CALM_STRICT: 1.05-1.15x landed 33 of 41 against 1.00x's 154 of 167."""
    result, vin, _ = _home(monkeypatch, [1.12, 1.12, 1.0], strict="on")
    note = next(n for n in result.notes if "waited" in n)
    assert "1.12x to drop -- 1.00x at the jump [calm at 1.05x]" in note
    assert vin.events[0] == ("press", ("w",))


def test_the_strict_arm_by_the_hour():
    # (h // 2) % 2: crosses HOME_ALIGN's even/odd split, both arms in each
    assert [routes.glide_calm_factor(h) for h in (0, 1, 2, 3, 4)] == [1.25, 1.25, 1.05, 1.05, 1.25]


def test_no_buff_jumps_at_once(monkeypatch):
    result, _, _ = _home(monkeypatch, [1.0])
    assert not any("at the run-up" in n for n in result.notes)


def test_the_bar_stays_1_25_and_the_cap_35s():
    """Counted once per walk home (runs 1100-1172): 1.00x landed 104 of 107,
    1.05-1.25x 37 of 41, so 1.05 is only GLIDE_CALM_STRICT's A/B arm; all 4
    waits that hit the old 20 s cap missed, so the cap is 35 s."""
    assert routes.GLIDE_CALM_FACTOR == 1.25 and routes.GLIDE_CALM_MAX_S == 35.0


def test_the_wait_is_capped_then_it_jumps_as_before(monkeypatch):
    result, vin, _ = _home(monkeypatch, [2.0])
    note = next(n for n in result.notes if "at the run-up" in n)
    assert f"waited {routes.GLIDE_CALM_MAX_S:.1f}s" in note and "jumped anyway" in note
    assert ("press", ("w",)) in vin.events


def test_off_or_without_the_base_timing_it_is_todays_jump(monkeypatch):
    for kw in ({"calm": "off"}, {"at_base": False}):
        result, _, _ = _home(monkeypatch, [2.0, 1.0], **kw)
        assert not any("at the run-up" in n for n in result.notes)


def test_other_routes_never_wait(monkeypatch):
    result, _, _ = _home(monkeypatch, [2.0, 1.0], name="natro_home_rose_field")
    assert not any("at the run-up" in n for n in result.notes)


def test_a_buff_ending_at_the_run_up_is_only_noted_while_look_only(monkeypatch):
    """GLIDE_STEADY: 1152 10:18, a 2.00x with its bear morph about 1 s left."""
    result, vin, _ = _home(monkeypatch, [1.12], changes=[(1.0, 1.0)])
    note = next(n for n in result.notes if "glide steady" in n)
    assert "would wait 1.0s" in note and "1.12x becomes 1.00x" in note
    assert vin.events[0] == ("press", ("w",)) and result.ok


def test_live_it_waits_until_nothing_ends_soon(monkeypatch):
    monkeypatch.setattr(routes, "GLIDE_STEADY_LIVE", True)
    result, _, _ = _home(monkeypatch, [1.12, 1.12, 1.12, 1.12, 1.0], changes=[(1.0, 1.0)])
    note = next(n for n in result.notes if "glide steady" in n)
    assert "1.12x to run out -- 1.00x at the jump" in note and "jumped anyway" not in note


def test_a_fresh_haste_does_not_hold_the_jump(monkeypatch):
    """1160 15:08 / 1145 07:44 landed with Haste "about 16s left"."""
    monkeypatch.setattr(routes, "GLIDE_STEADY_LIVE", True)
    result, _, _ = _home(monkeypatch, [1.2], changes=[(16.0, 1.0)])
    assert not any("glide steady" in n for n in result.notes)


def test_live_a_change_that_never_clears_is_capped_with_w_up(monkeypatch):
    """GLIDE_STEADY_MAX_S: a forecast stuck at "1 s left" (a noisy morph clock)."""
    monkeypatch.setattr(routes, "GLIDE_STEADY_LIVE", True)
    result, vin, seen = _home(monkeypatch, [1.12], changes=[(1.0, 1.0)])
    note = next(n for n in result.notes if "glide steady" in n)
    assert f"waited {routes.GLIDE_STEADY_MAX_S:.1f}s" in note and "jumped anyway" in note
    assert vin.events[0] == ("press", ("w",))         # nothing pressed while it waited
    assert vin.pressed_at[0] - seen[0][0] >= routes.GLIDE_STEADY_MAX_S


def test_live_a_haste_that_rose_during_the_wait_is_waited_out_again(monkeypatch):
    """1161 16:10: Haste x4 to x8 while it stood at the run-up (Hasty bees)."""
    monkeypatch.setattr(routes, "GLIDE_STEADY_LIVE", True)
    reads = [1.12] * 4 + [2.0] * 30 + [1.0]
    result, vin, _ = _home(monkeypatch, reads, changes=[(1.0, 1.0)])
    again = [n for n in result.notes if "after the steady wait" in n]
    assert again and "2.00x to drop -- 1.00x at the jump" in again[0], result.notes
    assert vin.events[0] == ("press", ("w",))
