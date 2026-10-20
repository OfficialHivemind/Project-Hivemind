"""Sober and compositor health (ROADMAP A11). See platform/soberhealth.py."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hivemind.brain import alive
from hivemind.brain.alive import FROZEN_AFTER, GONE_AFTER, WorldGuard
from hivemind.platform import soberhealth as sh

# Sober's own log of a failed start, 2026-10-26 15:01 (sober_logs), trimmed.
CRASHED_LOG = """\
info: app: lifecycle: update_flags_from_remote_manifest delta=0.02ms
ERROR: download: couldn't download resource from: https://sober.vinegarhq.org/app (error=Could not resolve hostname)
FATAL: Crash: Failed to fetch remote manifest required for operation. Check your internet connection.
FATAL: Crash: Previous error is fatal, trying to show GUI error dialog...
info: UIServicesConduit: will execute ui service binary
FATAL: Crash: Aborting...
"""
SPLASH = Path.home() / "Hivemind/var/incidents/20261020-181833-hud-hold/guard_frame.png"


def test_the_first_crash_line_is_the_cause():
    assert sh.crash_line(CRASHED_LOG).startswith("Failed to fetch remote manifest")
    assert sh.crash_line("info: app: all fine\n") == ""


def test_empty_screens_are_named_and_a_picture_is_not():
    assert sh.screen_kind(np.zeros((1080, 1920, 4), np.uint8)) == "a black screen"
    grey = np.full((1080, 1920, 3), 17, np.uint8)
    assert "splash" in sh.screen_kind(grey)
    rng = np.random.default_rng(0)
    assert sh.screen_kind(rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)) == ""
    assert sh.screen_kind(object()) == ""


def test_the_real_splash_of_run_1116_is_named():
    if not SPLASH.exists():
        pytest.skip("the owner's incident frame is not on this machine")
    import cv2
    assert "splash" in sh.screen_kind(cv2.imread(str(SPLASH)))


def test_frozen_counts_watched_time_only():
    f = sh.Frozen(gap=3.0)
    a = np.zeros((1080, 1920, 3), np.uint8)
    assert f.see(a, 0.0) == 0.0
    assert f.see(a, 2.0) == 2.0
    assert f.see(a, 4.0) == 4.0
    assert f.see(a, 10.0) == 0.0, "a 6 s gap nobody watched counted as frozen"
    b = a.copy()
    b[::8, ::8] = 1
    assert f.see(b, 11.0) == 0.0, "a changed screen still counted as frozen"
    assert f.see(object(), 12.0) == 0.0


class Sess:
    def __init__(self, pid):
        self.pid = pid

    def compositor_pid(self):
        return self.pid


def test_the_compositor_is_asked_by_its_pid(tmp_path):
    import os
    assert sh.compositor_alive(Sess(os.getpid())) is True
    assert sh.compositor_alive(Sess(2 ** 22 + 12345)) is False
    assert sh.compositor_alive(Sess(None)) is None


def test_relaunches_are_capped_per_hour(tmp_path):
    path = tmp_path / "relaunches.json"
    assert [sh.relaunch_wait(path, t) for t in (0, 60, 120)] == [0, 0, 0]
    assert sh.relaunch_wait(path, 180) == pytest.approx(sh.HOUR - 180)
    # the next one is spaced from the held one, not from now
    assert sh.relaunch_wait(path, 200) == pytest.approx(sh.HOUR + 60 - 200)
    assert sh.relaunch_wait(path, 10 * sh.HOUR) == 0


# ---- the world guard ---------------------------------------------------------
class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def guard(frames, **kw):
    clock, stopped, said = Clock(), [], []
    g = WorldGuard(frames, lambda f: True, on_gone=lambda: stopped.append(1),
                   emit=said.append, clock=clock, check_every=0.0, **kw)
    g.sleep = lambda s: None
    return g, clock, stopped, said


def watch(g, clock, seconds, step=0.5):
    for _ in range(int(seconds / step)):
        clock.t += step
        g.check()


def test_a_lost_compositor_is_the_game_gone_at_once():
    def dropped():
        raise RuntimeError("the Wayland connection dropped")

    g, clock, stopped, said = guard(dropped, compositor=lambda: False)
    assert g.check() is True and stopped == [1]
    assert "compositor" in g.describe()
    g, clock, stopped, _ = guard(dropped, compositor=lambda: True)
    watch(g, clock, 60)
    assert stopped == [], "a failed capture with the compositor up stopped the run"


def test_frozen_frames_are_only_said_while_look_only():
    still = np.zeros((1080, 1920, 3), np.uint8)
    g, clock, stopped, said = guard(lambda: still)
    watch(g, clock, FROZEN_AFTER + GONE_AFTER + 10)
    assert stopped == []
    would = [e for e in said if "frozen frames would" in getattr(e, "message", "")]
    assert len(would) == 1


def test_frozen_frames_stop_the_run_once_live(monkeypatch):
    monkeypatch.setattr(alive, "FROZEN_LIVE", True)
    still = np.full((1080, 1920, 3), 90, np.uint8)
    g, clock, stopped, _ = guard(lambda: still)
    watch(g, clock, FROZEN_AFTER - 1)
    assert stopped == [], "stopped before FROZEN_AFTER"
    watch(g, clock, GONE_AFTER + 3)
    assert stopped == [1]
    assert "has not changed" in g.describe()


def test_a_moving_world_never_freezes(monkeypatch):
    monkeypatch.setattr(alive, "FROZEN_LIVE", True)
    n = [0]

    def moving():
        n[0] += 1
        return np.full((1080, 1920, 3), n[0] % 200, np.uint8)

    g, clock, stopped, _ = guard(moving)
    watch(g, clock, 120)
    assert stopped == []


# ---- the start ---------------------------------------------------------------
def test_a_crash_ends_the_start_wait_at_once():
    from hivemind.act.appui import AppUI
    from hivemind.vision import screenstate as ss

    ui = AppUI(inp=None, capture=None)
    looks = []
    ui.screen = lambda frame=None: looks.append(1) or ss.Screen.LOADING
    state = ui.wait_for(ss.Screen.APP_HOME, timeout=60, poll=0.0,
                        give_up=lambda: len(looks) >= 2)
    assert state is ss.Screen.LOADING and len(looks) == 2
