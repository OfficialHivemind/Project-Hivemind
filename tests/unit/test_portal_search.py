"""P1 (act/routes PORTAL_SEARCH): a blue-portal press whose panel never said
"Enter the Portal" steps left and reads again before it gives the walk up --
attempts 889 21:59 and 898 10:04 stood a stud or few right of the prompt."""
from __future__ import annotations

from contextlib import contextmanager

from hivemind.act import routes as R
from hivemind.act.routes import RouteRunner
from hivemind.nav.router import Edge, Router


class _Keys:
    def __init__(self):
        self.walked, self.taps = [], []

    @contextmanager
    def held(self, *keys):
        self.walked.append("".join(keys))
        yield

    def tap(self, key, ms=40):
        self.taps.append(key)


def _run(monkeypatch, panels, switch="on"):
    """Run the portal step with the panel reading `panels` in turn (the last
    repeats); the clock jumps a second a read so each wait ends quickly."""
    clock = [0.0]
    monkeypatch.setattr(R.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(R.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + max(s, 0.01)))
    monkeypatch.setattr(R, "PORTAL_SEARCH", switch)
    left = list(panels)

    def panel():
        clock[0] += 1.0
        return left.pop(0) if len(left) > 1 else left[0]

    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("natro_home_bamboo", "bamboo", "hive", 1.0, steps=[
        {"op": "interact_when", "expect": ["portal"], "why": "the blue portal home", "wait": 6.0}]))
    keys = _Keys()
    return RouteRunner(keys, r, walkspeed=100000.0, panel_text=panel).run("natro_home_bamboo"), keys


def test_a_step_left_finds_the_portal_the_route_stopped_beside(monkeypatch):
    # 6 reads of the dispenser (the 6 s wait), one more after the first step, then the door
    out, keys = _run(monkeypatch, ["Use the Blueberry Dispenser"] * 8 + ["Enter the Portal"])
    assert out.ok, out.reason
    assert keys.taps == ["e"] and set(keys.walked) == {"a"}
    assert any(n.startswith("P1 portal search") and "use the blueberry dispenser" in n
               for n in out.notes), out.notes


def test_no_portal_after_the_search_presses_nothing_and_fails(monkeypatch):
    out, keys = _run(monkeypatch, [""])
    assert not out.ok and "nothing was pressed" in out.reason
    assert keys.taps == [] and keys.walked == ["a"] * R.PORTAL_SEARCH_STEPS
    assert sum(n.startswith("P1 portal search") for n in out.notes) == 1, out.notes


def test_off_stops_at_the_door_as_before(monkeypatch):
    out, keys = _run(monkeypatch, [""], switch="off")
    assert not out.ok and keys.walked == [] and keys.taps == []
