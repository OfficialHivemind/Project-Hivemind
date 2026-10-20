"""LEAN_LOOK (act/routes, docs/pending/reliability-2026-10-19.md): the Pine
Tree walk home's first legs are JUDGED as a lean would judge them -- ended
against the corner or still moving -- while the recorded timed walk runs
unchanged (look-only, the project's rule for anything that moves)."""
import time

from hivemind.act import routes as R
from hivemind.act.routes import RouteRunner
from hivemind.nav.router import Edge, Router



class FakeInput:
    def __init__(self):
        self.held_keys: set[str] = set()

    def held(self, *keys):
        inp = self

        class _Held:
            def __enter__(self):
                inp.held_keys.update(keys)

            def __exit__(self, *exc):
                inp.held_keys.difference_update(keys)
        return _Held()


def _wall_after(seconds):
    t0 = []

    def flow():
        t0[:] = t0 or [time.monotonic()]
        return 99.0 if time.monotonic() - t0[0] < seconds else 0.0
    return flow

PINE = "natro_home_pine_tree"


def _runner(flow, name=PINE):
    inp = FakeInput()
    router = Router(path="/nonexistent", measurements=None)
    router.add(Edge(name, "pine_tree", "hive", 300.0, steps=[
        {"op": "walk", "keys": "w", "studs": 30.0},
        {"op": "walk", "keys": "d", "studs": 120.0},
        {"op": "walk", "keys": "a", "studs": 120.0}]))
    runner = RouteRunner(inp, router, walkspeed=100.0, flow=flow)
    runner.watch_interval = 0.01
    return runner, inp


def _looks(result):
    return [n for n in result.notes if "lean look-only" in n]


def test_a_walk_that_ends_pressed_into_the_corner_says_so():
    # the landings: d300 ended in the corner rock (attempt-1067/000417-*-02-walk-d300.jpg)
    runner, _ = _runner(_wall_after(0.0))
    looks = _looks(runner.run(PINE))
    assert len(looks) == 2, looks                  # w and d, never the third leg
    assert "d for 120 studs, lean look-only: ended against the wall" in looks[1], looks


def test_a_walk_that_ends_in_open_floor_says_a_lean_would_hold_on_and_walks_as_recorded():
    # the misses: d300 ended short of the rock (attempt-1067/002346-, 003552-*-02-walk-d300.jpg)
    runner, inp = _runner(lambda: 99.0)
    t0 = time.monotonic()
    looks = _looks(runner.run(PINE))
    took = time.monotonic() - t0
    assert "ended still moving" in looks[1] and "a lean would have held on" in looks[1], looks
    # 0.3 + 1.2 + 1.2 s recorded: a lean would have run to its cap (3x) here
    assert 2.6 < took < 2.7 + 1.0, took
    assert inp.held_keys == set()


def test_other_routes_are_not_looked_at():
    runner, _ = _runner(lambda: 99.0, name="natro_home_rose_field")
    assert _looks(runner.run("natro_home_rose_field")) == []


def test_without_a_flow_reader_nothing_is_said():
    runner, _ = _runner(None)
    assert _looks(runner.run(PINE)) == []


def test_the_real_pine_route_starts_with_the_two_timed_corner_legs_looked_at():
    edge = next(e for e in Router().edges if e.name == PINE)
    walks = [(s.get("keys"), s.get("studs"), bool(s.get("lean"))) for s in edge.steps[:2]]
    assert walks == [("w", 124.0, False), ("d", 300.0, False)]
    assert R.LEAN_LOOK[PINE] == 2


def test_the_last_second_of_each_looked_leg_is_kept_with_its_flow():
    # LEAN_LOOK_TAIL_S: frames to replay the wall check offline; the third leg keeps none
    runner, inp = _runner(_wall_after(0.0))
    snaps, held_at_write = [], []

    def snapshot(label, frame=None):
        snaps.append(label)
        if "-tail-" in label:                      # _snap swallows errors: checked below
            held_at_write.append((frame, set(inp.held_keys)))
    runner.snapshot = snapshot
    runner.grab_frame = lambda: "frame"
    runner.run(PINE)
    tails = [s for s in snaps if "-tail-" in s]
    legs = {s.split("-tail-")[0] for s in tails}
    assert legs == {f"{PINE}-01", f"{PINE}-02"}, legs
    assert f"{PINE}-02-tail-01-px0.0" in tails
    assert sum(s.startswith(f"{PINE}-02-tail") for s in tails) >= 50   # ~1 s at 100 Hz
    # the frame grabbed in the hold, written once the keys are up
    assert held_at_write and all(w == ("frame", set()) for w in held_at_write)


def test_without_a_frame_grabber_no_tail_is_kept():
    runner, _ = _runner(_wall_after(0.0))
    snaps = []
    runner.snapshot = snaps.append
    runner.run(PINE)
    assert not any("-tail-" in s for s in snaps)
