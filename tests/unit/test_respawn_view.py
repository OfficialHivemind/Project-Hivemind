"""The view after EVERY respawn before a walk out (act/respawn.view_verdict),
and the walk refused at the pad when it stays off (act/routes before_route).

The numbers are the live ones: run-1092 on 19 Oct 2026, 21:09:13 read 72 px
off and respawned once more; that second respawn (var/respawn/210922-pad.jpg)
measures 211.8 px and was walked from unlooked-at -- natro_out_polar_bear
ended in the Mushroom Field, "only 6% of the ground under us is the yellow
path". 20:46:55 read 66 px and its second respawn measured 0.1 px.
"""
from pathlib import Path

import hivemind
from hivemind.act import respawn
from hivemind.act.routes import RouteRunner
from hivemind.nav.router import Edge, Router

SHIFT = 2.0      # run_farm RESPAWN_VIEW_MAX_SHIFT
REPO = Path(hivemind.__file__).resolve().parents[2]


def test_the_second_respawn_is_looked_at_too():
    # 21:09:13 -> 21:09:22: off, then still off -- respawned again, not walked
    assert respawn.view_verdict(72.0, 1, max_shift=SHIFT) == "again"
    assert respawn.view_verdict(211.8, 2, max_shift=SHIFT) == "again"
    # 20:46:55 -> 20:47:04: off, then the standard view
    assert respawn.view_verdict(66.0, 1, max_shift=SHIFT) == "again"
    assert respawn.view_verdict(0.1, 2, max_shift=SHIFT) == "ok"


def test_still_off_after_the_last_respawn_is_refused():
    last = respawn.VIEW_RESPAWNS
    assert last == 3
    assert respawn.view_verdict(211.8, last, max_shift=SHIFT) == "refuse"
    # 21:09:45's respawn read 0.5 px (210945-pad.jpg): walked, as before
    assert respawn.view_verdict(0.5, last, max_shift=SHIFT) == "ok"
    # an unmeasurable view (no frame, no template) is walked, as before
    assert respawn.view_verdict(None, last, max_shift=SHIFT) == "ok"


class _Inp:
    def __init__(self):
        self.events = []

    def press(self, *keys):
        self.events.extend(("press", k) for k in keys)

    def release(self, *keys):
        self.events.extend(("release", k) for k in keys)

    def release_all(self):
        pass

    def tap(self, key, ms=40):
        self.events.append(("tap", key))

    def held(self, *keys):
        from contextlib import contextmanager

        @contextmanager
        def hold():
            self.press(*keys)
            try:
                yield self
            finally:
                self.release(*keys)
        return hold()


def _router():
    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("natro_out_polar_bear", "hive", "polar_bear", 20.0, steps=[
        {"op": "walk", "keys": "w", "studs": 20.0}]))
    return r


def test_a_refusal_from_before_route_stops_the_route_before_its_first_step():
    inp = _Inp()
    run = RouteRunner(inp, _router(), walkspeed=1000.0)
    why = "natro_out_polar_bear: not walked — the view is still 212 px off"
    run.before_route = lambda name: why
    result = run.run("natro_out_polar_bear")
    assert not result.ok and result.reason == why
    assert inp.events == []                      # nothing pressed


def test_before_route_returning_none_still_walks():
    inp = _Inp()
    run = RouteRunner(inp, _router(), walkspeed=1000.0)
    run.before_route = lambda name: None
    assert run.run("natro_out_polar_bear").ok
    assert ("press", "w") in inp.events


def test_run_farm_checks_every_respawn_and_refuses_the_walk():
    src = (REPO / "scripts" / "run_farm.py").read_text()
    body = src[src.index("        def respawn_to_pad("):src.index("        def respawn_home(")]
    assert "if not again and off is not None" not in body     # the old once-only look
    assert "respawn_view_verdict(off, views" in body
    assert "views=views + 1" in body
    walk = src[src.index("        def respawn_before_the_walk_out("):
               src.index("        def forget_last_trip(")]
    assert 'homing.get("view_off")' in walk and "not walked" in walk
    assert "runner.before_route = before_route" in src


def test_a_stop_refuses_the_walk_out_before_and_after_the_respawn():
    """MEASURED 1109 14:49:10: a stop cut the walk onto the pad short and the
    route out was walked anyway, then logged as an errand miss."""
    src = (REPO / "scripts" / "run_farm.py").read_text()
    walk = src[src.index("        def respawn_before_the_walk_out("):
               src.index("        def forget_last_trip(")]
    assert walk.count('return f"{name}: not walked — stop requested"') == 2
    first_stop = walk.index("stop requested")
    assert first_stop < walk.index("respawn_to_pad(") < walk.rindex("stop requested")


def test_an_off_view_logs_the_drag_it_would_make_look_only():
    src = (REPO / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert "_respawn_view_shift[0] = None if best is None else best[2]" in src
    body = src[src.index("        def respawn_to_pad("):src.index("        def respawn_home(")]
    again = body[body.index('if view == "again":'):body.index('if view == "refuse":')]
    assert "(RESPAWN_VIEW_DRAG look)" in again and "inp." not in again   # logs only
