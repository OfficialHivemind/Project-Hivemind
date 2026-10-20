"""WALK-CKP: a failed route check nudges toward what it saw and looks again
(act/routes `_check`, `seen_nudge`, CHECK_NUDGE_LIVE)."""
from __future__ import annotations

import contextlib
import time as real_time
import types
from pathlib import Path

import numpy as np
import pytest

from hivemind.act import routes
from hivemind.act.routes import RouteRunner, seen_nudge
from hivemind.nav.router import Edge, Router

BAND = (700, 880, 760, 1160)                      # run_farm on_the_path's band


def _mask(y0, y1, x0, x1):
    m = np.zeros((1080, 1920), dtype=bool)
    m[y0:y1, x0:x1] = True
    return m


def test_path_beside_the_character_is_a_sideways_nudge():
    # MEASURED shape (run 1248 20:06 treat leg 9): the path fills the left
    # of the frame at the character's height, the field the right.
    assert seen_nudge(_mask(600, 950, 150, 700), BAND)[0]["keys"] == "a"
    assert seen_nudge(_mask(600, 950, 1250, 1770), BAND)[0]["keys"] == "d"
    assert seen_nudge(_mask(600, 950, 150, 700), BAND)[0]["studs"] == routes.NUDGE_STUDS


def test_path_behind_or_ahead_or_too_little_gets_no_nudge():
    # Behind: the strip along the bottom edge (runs 1046-1049, the Shop's lawn).
    assert seen_nudge(_mask(990, 1060, 150, 700), BAND) is None
    # Ahead: a wall of the path's colour (runs 739, 767, 806).
    assert seen_nudge(_mask(500, 640, 600, 1300), BAND) is None
    # A few token-sized specks: nothing to steer by.
    assert seen_nudge(_mask(780, 800, 200, 260), BAND) is None
    # Only the hotbar's own yellow: ignored.
    assert seen_nudge(_mask(975, 1080, 700, 1340), BAND) is None


class Input:
    def __init__(self):
        self.events = []

    def press(self, *keys):
        self.events.append(("press", keys))

    def release(self, *keys):
        self.events.append(("release", keys))

    def tap(self, key):
        self.events.append(("tap", key))

    @contextlib.contextmanager
    def held(self, *keys):
        self.press(*keys)
        try:
            yield
        finally:
            self.release(*keys)

    def release_all(self):
        pass


NUDGE = [{"op": "walk", "keys": "a", "studs": 4.0}]


def _run(monkeypatch, looks, live):
    """natro_out_x: one walk with a check that answers `looks` in turn."""
    clock = [100.0]
    fake = types.SimpleNamespace(**{k: getattr(real_time, k) for k in dir(real_time)
                                    if not k.startswith("_")})
    fake.sleep = lambda s: clock.__setitem__(0, clock[0] + s)
    fake.monotonic = lambda: clock[0]
    monkeypatch.setattr(routes, "time", fake)
    monkeypatch.setattr(routes, "CHECK_NUDGE_LIVE", live)
    answers = list(looks)
    asked = []

    def check():
        asked.append(1)
        return answers.pop(0) if len(answers) > 1 else answers[0]

    r = Router(path="/nonexistent", measurements=None)
    r.add(Edge("natro_out_x", "hive", "x", 20.0,
               steps=[{"op": "walk", "keys": "w", "studs": 20.0, "check": "on_the_path"},
                      {"op": "walk", "keys": "d", "studs": 10.0}]))
    vin = Input()
    runner = RouteRunner(vin, r, walkspeed=32.2, checkpoints={"on_the_path": check})
    return runner.run("natro_out_x"), vin, asked


def _pressed(vin):
    return [k for e, k in vin.events if e == "press"]


def test_look_only_says_what_it_would_do_and_ends_the_route_as_before(monkeypatch, capsys):
    result, vin, asked = _run(monkeypatch, [(False, "off the path", NUDGE)], live=False)
    assert not result.ok and result.reason == "natro_out_x leg 1: off the path"
    assert len(asked) == 1 and _pressed(vin) == [("w",)]       # no nudge, no leg 2
    assert "check would: nudge 4 studs left and look again" in capsys.readouterr().out


def test_live_nudge_then_a_pass_carries_on(monkeypatch):
    result, vin, asked = _run(monkeypatch, [(False, "off the path", NUDGE),
                                            (True, "on the path")], live=True)
    assert result.ok and len(asked) == 2
    assert _pressed(vin) == [("w",), ("a",), ("d",)]          # walk, nudge, leg 2
    assert result.checks[-1].endswith("(look 2)")
    assert any("nudged 4 studs left after look 1" in n for n in result.notes)


def test_live_gives_up_after_the_last_look(monkeypatch):
    result, vin, asked = _run(monkeypatch, [(False, "off the path", NUDGE)], live=True)
    assert not result.ok and len(asked) == routes.CHECK_TRIES
    assert _pressed(vin).count(("a",)) == routes.CHECK_TRIES - 1


def test_a_check_with_nothing_to_steer_by_ends_at_once(monkeypatch):
    for answer in [(False, "nothing here"), (False, "nothing here", None)]:
        result, vin, asked = _run(monkeypatch, [answer], live=True)
        assert not result.ok and len(asked) == 1 and _pressed(vin) == [("w",)]


ROUTES = Path.home() / "Hivemind" / "var" / "routes"
# Kept failure frames (owner's machine only): the leg frame each failed check
# looked at, with what a person sees in it (docs/pending/walkckp.md).
FRAMES = {
    "attempt-1248/200608-natro_out_treat_dispenser-09-walk-wd80.jpg": "a",   # path on the left
    "attempt-1092/210935-natro_out_polar_bear-03-walk-sa270.jpg": "a",       # path on the left
    "attempt-1048/062803-natro_out_sticker_stack-03-walk-sa270.jpg": None,   # Shop lawn, path behind
    "attempt-806/105625-natro_out_treat_dispenser-09-walk-wd80.jpg": None,   # a wall ahead
}


@pytest.mark.parametrize("name,keys", FRAMES.items())
def test_kept_failure_frames(name, keys):
    cv2 = pytest.importorskip("cv2")
    frame = cv2.imread(str(ROUTES / name))
    if frame is None:
        pytest.skip("kept frames are on the owner's machine only")
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    path = ((hsv[:, :, 0] >= 20) & (hsv[:, :, 0] <= 35)          # run_farm on_the_path's mask
            & (hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 90))
    got = seen_nudge(path, BAND)
    assert (got[0]["keys"] if got else None) == keys
