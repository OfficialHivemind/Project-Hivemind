"""A survey leg may be several steps run as one Routine (run_farm survey_by_walk):
the Panda's jump-into-the-ladder leg (run_farm PANDA_JUMP_RIGHT) holds D while
tapping space three times, and the run lifts D at its end whatever ended it --
a held key can never outlast its leg."""
from __future__ import annotations

from hivemind.act import routes
from hivemind.act.routes import RouteRunner
from hivemind.nav.router import Router, Routine
from tests.unit.test_routes import FakeInput

JUMP_RIGHT = ({"op": "key_down", "keys": "d"}, {"op": "pause", "seconds": 0.25},
              {"op": "jump"}, {"op": "pause", "seconds": 0.45},
              {"op": "jump"}, {"op": "pause", "seconds": 0.45},
              {"op": "jump"}, {"op": "pause", "seconds": 0.45},
              {"op": "key_up", "keys": "d"})


def _run(steps, monkeypatch):
    monkeypatch.setattr(routes.time, "sleep", lambda s: None)
    inp = FakeInput()
    r = Router(path="/nonexistent", measurements=None)
    r.routines["survey_leg"] = Routine(name="survey_leg", steps=[dict(x) for x in steps])
    result = RouteRunner(inp, r, walkspeed=1000.0).run("survey_leg")
    return inp, result


def test_d_is_held_through_three_jumps_then_lifted(monkeypatch):
    inp, _ = _run(JUMP_RIGHT, monkeypatch)
    assert [e for e in inp.events if e[0] in ("press", "tap", "release")] == [
        ("press", "d"), ("tap", "space"), ("tap", "space"), ("tap", "space"), ("release", "d")]
    assert not inp.held_keys


def test_a_leg_cut_before_its_key_up_still_lifts_the_key(monkeypatch):
    inp, result = _run(JUMP_RIGHT[:-1], monkeypatch)
    assert ("release", "d") in inp.events and not inp.held_keys
    assert any("still down at the end" in n for n in result.notes), result.notes
