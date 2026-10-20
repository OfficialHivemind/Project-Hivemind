"""GLIDE_CALM_LEG: the Pine Tree walk home waits out a strong buff before its
8-stud ledge leg (`calm: true`), not only at the run-up (act/routes)."""
from __future__ import annotations

import contextlib
import time as real_time
import types

from hivemind.act import routes
from hivemind.act.routes import RouteRunner
from hivemind.nav.router import Edge, Router

TAIL = [                         # natro_home_pine_tree from the snow ramp
    {"op": "walk", "keys": "a", "studs": 8.0, "calm": True},
    {"op": "key_down", "keys": "w"}, {"op": "coast", "studs": 24.0},
    {"op": "key_up", "keys": "w"},
]


class Input:
    def __init__(self, reads_so_far=lambda: 0):
        self.events = []
        self.reads_so_far = reads_so_far

    def press(self, *keys):
        self.events.append(("press", keys))
        self.pressed_after = getattr(self, "pressed_after", {})
        self.pressed_after.setdefault(keys, self.reads_so_far())

    def release(self, *keys):
        self.events.append(("release", keys))

    def tap(self, key):
        self.events.append(("tap", key))

    def release_all(self):
        pass

    @contextlib.contextmanager
    def held(self, *keys):
        self.press(*keys)
        try:
            yield
        finally:
            self.release(*keys)


def _run(monkeypatch, factors, name="natro_home_pine_tree", steps=TAIL):
    reads = list(factors)
    clock = [100.0]
    monkeypatch.setattr(routes, "GLIDE_CALM", "on")
    monkeypatch.setattr(routes, "GLIDE_CALM_STRICT", "off")
    fake = types.SimpleNamespace(**{k: getattr(real_time, k) for k in dir(real_time)
                                    if not k.startswith("_")})
    fake.sleep = lambda s: clock.__setitem__(0, clock[0] + s)
    fake.monotonic = lambda: clock[0]
    monkeypatch.setattr(routes, "time", fake)
    seen = []

    def factor():
        seen.append(1)
        return reads.pop(0) if len(reads) > 1 else reads[0]
    vin = Input(lambda: len(seen))
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge(name, "pine_tree", "hive", 816.8, steps=[dict(s) for s in steps]))
    runner = RouteRunner(vin, r, walkspeed=32.2, movespeed_factor=factor,
                         glide_at_base=lambda: True)
    return runner.run(name), vin


def test_the_ledge_leg_waits_before_a_goes_down(monkeypatch):
    result, vin = _run(monkeypatch, [2.0, 2.0, 2.0, 1.0])
    waits = [n for n in result.notes if "before the calm leg" in n]
    assert len(waits) == 1 and "2.00x to drop -- 1.00x" in waits[0]
    assert vin.events[0] == ("press", ("a",))        # nothing pressed while it waited
    assert vin.pressed_after[("a",)] >= 4             # "a" went down after the factor dropped


def test_no_buff_no_wait(monkeypatch):
    result, vin = _run(monkeypatch, [1.0])
    assert not any("waited" in n for n in result.notes)
    assert vin.events[0] == ("press", ("a",))


def test_only_a_glide_route_waits(monkeypatch):
    result, _ = _run(monkeypatch, [2.0, 1.0], name="natro_out_pine_tree")
    assert not any("waited" in n for n in result.notes)


def test_the_route_marks_its_ledge_leg():
    steps = next(e.steps for e in Router().edges if e.name == "natro_home_pine_tree")
    calm = [s for s in steps if s.get("calm")]
    assert len(calm) == 1 and calm[0]["keys"] == "a" and calm[0]["studs"] == 8.0
    after = steps[steps.index(calm[0]) + 1]
    assert after["op"] == "key_down"                  # the run-up follows it


def test_an_always_calm_leg_waits_on_any_route(monkeypatch):
    # act/commando.CALM_AT: the Commando walk's d7 after the hedge, no glide behind it
    steps = [{"op": "walk", "keys": "d", "studs": 7.0, "calm": "always"},
             {"op": "walk", "keys": "a", "studs": 90.0}]
    result, vin = _run(monkeypatch, [2.0, 2.0, 2.0, 1.0], name="commando_via", steps=steps)
    waits = [n for n in result.notes if n.startswith("calm: waited")]
    assert len(waits) == 1 and "before the d leg" in waits[0] and "2.00x to drop -- 1.00x" in waits[0]
    assert vin.events[0] == ("press", ("d",)) and vin.pressed_after[("d",)] >= 4
