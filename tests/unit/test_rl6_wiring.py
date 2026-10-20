"""RL6 phase 3 wiring: the callers reach the Windows modules through
platform/current and hivemind/files, and Roblox losing the foreground is a
pause (brain/controls GuardedInput + FocusGuard), not a crash. Linux keeps
the exact objects and behaviour it had (test_platform_api checks the modules)."""
from __future__ import annotations

import json
import threading
import time
import types

import os

import pytest

from hivemind import files
from hivemind.act import bootstrap
from hivemind.brain.controls import Controls, FocusGuard, GuardedInput
from hivemind.platform import api, current
from hivemind.telemetry.events import Action, Command


# ---- hivemind/files ----------------------------------------------------------------
@pytest.mark.skipif(os.name == "nt", reason="flock is Linux; Windows locks with msvcrt")
def test_locked_is_flock_on_linux(tmp_path):
    with open(tmp_path / "l", "a") as h, files.locked(h):
        import fcntl
        with open(tmp_path / "l", "a") as other, pytest.raises(OSError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)      # held
    with open(tmp_path / "l", "a") as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)          # let go


def test_locked_on_windows_locks_the_byte_past_eof(monkeypatch, tmp_path):
    import os
    import sys
    from hivemind.platform.win import files as wf
    calls = []
    fake = types.SimpleNamespace(LK_LOCK=1, LK_UNLCK=0,
                                 locking=lambda fd, mode, n: calls.append(
                                     (mode, os.lseek(fd, 0, os.SEEK_CUR), n)))
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(files, "WINDOWS", True)
    with open(tmp_path / "l", "a") as h, files.locked(h):
        calls.append("inside")
    assert calls == [(1, wf.LOCK_OFFSET, 1), "inside", (0, wf.LOCK_OFFSET, 1)]


def test_process_readers_and_lock_are_win_files_on_windows(monkeypatch):
    from hivemind.platform.win import files as wf
    monkeypatch.setattr(files, "WINDOWS", True)
    monkeypatch.setattr(wf, "process_identity", lambda pid: ("python watchdog.py", "12.000"))
    monkeypatch.setattr(wf, "process_parent", lambda pid: 77)
    monkeypatch.setattr(wf, "take_lock", lambda path: "handle")
    assert files.process_identity(5) == ("python watchdog.py", "12.000")
    assert files.process_parent(5) == 77 and files.take_lock("x") == "handle"


def test_pid_running_default_identity_follows(monkeypatch, tmp_path):
    """pid_running's default `identity` is bound at definition: it must still
    end up on Windows' reader."""
    from hivemind.platform.win import files as wf
    monkeypatch.setattr(files, "WINDOWS", True)
    monkeypatch.setattr(wf, "process_identity", lambda pid: ("py run_farm.py", "9.000"))
    (tmp_path / "p").write_text("4242 9.000\n")
    assert files.pid_running(tmp_path / "p", "run_farm.py") == 4242


# ---- GameNotFocused is a pause ---------------------------------------------------------
class Raw:
    """A WinInput stand-in: refuses while `front` is False, letting go of all."""

    def __init__(self):
        self.front, self.sent, self.down = True, [], set()

    def _check(self):
        if not self.front:
            self.down.clear()
            raise api.GameNotFocused("input refused: 'Discord' is in front")

    def press(self, *keys):
        self._check()
        self.down |= set(keys)
        self.sent.append(("press",) + keys)

    def release(self, *keys):
        self.down -= set(keys)
        self.sent.append(("release",) + keys)

    def release_all(self):
        self.down.clear()

    def tap(self, key, *a, **k):
        self._check()
        self.sent.append(("tap", key))

    def scroll(self, steps=1, horizontal=False):
        self._check()
        self.sent.append(("scroll", steps))


def made(raw):
    controls = Controls(vin=raw, running=True)
    said = []
    guard = FocusGuard(controls, lambda: raw.front, lambda m, warn=False: said.append(m))
    return controls, guard, GuardedInput(raw, controls, poll=0.01, on_unfocused=guard.lost), said


def back_in_front_soon(raw, guard, after=0.05):
    def later():
        time.sleep(after)
        raw.front = True
        guard.tick()
    t = threading.Thread(target=later)
    t.start()
    return t


def test_a_refused_press_pauses_and_goes_out_when_roblox_is_back():
    raw = Raw()
    controls, guard, inp, said = made(raw)
    raw.front = False
    t = back_in_front_soon(raw, guard)
    assert inp.press("w") is True
    t.join()
    assert raw.sent == [("press", "w")] and inp.unfocused == 1
    assert not controls.paused and guard.pauses == 1
    assert "paused: input refused" in said[0] and "resuming" in said[-1]


def test_a_stale_key_is_dropped_after_the_wait():
    raw = Raw()
    controls, guard, inp, _ = made(raw)
    raw.front = False
    t = back_in_front_soon(raw, guard)
    assert inp.tap("e") is False                  # decided on a frame from before the pause
    t.join()
    assert raw.sent == [] and inp.dropped == 1


def test_keys_held_go_back_down_after_the_pause():
    raw = Raw()
    controls, guard, inp, _ = made(raw)
    inp.press("w")
    raw.front = False
    t = back_in_front_soon(raw, guard)
    inp.scroll(1)                                  # refused: WinInput let W go
    t.join()
    assert ("press", "w") == raw.sent[-2] and raw.sent[-1] == ("scroll", 1)
    assert raw.down == {"w"}


def test_a_stop_during_the_pause_ends_the_wait():
    raw = Raw()
    controls, guard, inp, _ = made(raw)
    raw.front = False
    threading.Timer(0.05, controls.handle, (Command(action=Action.STOP),)).start()
    assert inp.press("w") is False and raw.sent == []


def test_held_is_retried_too():
    raw = Raw()
    controls, guard, inp, _ = made(raw)
    import contextlib

    @contextlib.contextmanager
    def held(*keys):
        raw.press(*keys)
        try:
            yield
        finally:
            raw.release(*keys)
    raw.held = held
    raw.front = False
    t = back_in_front_soon(raw, guard)
    with inp.held("w"):
        assert raw.down == {"w"}
    t.join()
    assert raw.down == set() and raw.sent == [("press", "w"), ("release", "w")]


def test_without_on_unfocused_it_raises_as_before():
    raw = Raw()
    inp = GuardedInput(raw, Controls(vin=raw, running=True))
    raw.front = False
    with pytest.raises(api.GameNotFocused):
        inp.press("w")


def test_focus_guard_resumes_only_its_own_pause():
    raw = Raw()
    controls, guard, _, said = made(raw)
    raw.front = False
    guard.tick()
    assert controls.paused and guard.pauses == 1
    guard.tick()                                    # still away: one pause, said once
    assert guard.pauses == 1 and len(said) == 1
    controls.handle(Command(action=Action.TAKE_OVER))   # the owner pressed a button
    raw.front = True
    guard.tick()
    assert controls.handed_over and "leaving them" in said[-1]
    # the owner's own Pause is never undone by Roblox coming to the front
    controls.handle(Command(action=Action.PASS_BACK))
    controls.handle(Command(action=Action.PAUSE))
    guard.tick()
    assert controls.paused


# ---- bootstrap on Windows -----------------------------------------------------------------
class WinSessionStub:
    def __init__(self, opens_after=0):
        self.looks, self.opens_after, self.launched, self.sized = 0, opens_after, None, False
        self.pid, self.ok_fields = 600, {"started": "1.000", "hwnd": 7}

    def launch_game(self, link):
        self.launched = link
        return types.SimpleNamespace(pid=590)

    def game_window_open(self):
        self.looks += 1
        return self.looks > self.opens_after

    def describe_windows(self):
        return "no Roblox window"

    def fullscreen_focused(self):
        self.sized = True
        return "roblox window: client 1920x1080, borderless yes"

    def compositor_pid(self):
        return self.pid

    def kept_fields(self):
        return self.ok_fields


def test_windows_joins_by_link_or_else_a_public_server(monkeypatch):
    monkeypatch.setattr(bootstrap.time, "sleep", lambda s: None)
    said = []
    s = WinSessionStub()
    bootstrap._launch_windows(s, True, None, said.append)     # no link set: public, said
    assert s.launched is None and said[0] == bootstrap.WINDOWS_PUBLIC
    assert "roblox window: client 1920x1080, borderless yes" in said
    s = WinSessionStub(opens_after=2)
    server = types.SimpleNamespace(uri=lambda: "roblox://navigation/share_links?code=x&type=Server")
    game = bootstrap._launch_windows(s, True, server, lambda m: None)
    assert game.pid == 590 and s.launched.startswith("roblox://navigation")
    assert s.looks == 3 and s.sized                 # the window, then sized, before any capture
    s = WinSessionStub()
    bootstrap._launch_windows(s, False, None, lambda m: None)
    assert s.launched is None                       # a public start: the place itself


def test_windows_window_that_never_opens_fails_the_start(monkeypatch):
    clock = iter(range(0, 10_000, 100))
    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(bootstrap.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="never opened a window"):
        bootstrap._launch_windows(WinSessionStub(opens_after=10 ** 6), False, None, print)


def test_detach_on_windows_keeps_the_games_pid_and_start(monkeypatch, tmp_path):
    from hivemind.platform.win import session as ws
    monkeypatch.setattr(current, "WINDOWS", True)
    monkeypatch.setattr(current, "kept", ws)
    closed = []
    shut = types.SimpleNamespace(close=lambda: closed.append(1), stop=lambda: closed.append("stop"))
    s = WinSessionStub()
    s.stop = lambda: closed.append("session stop")
    ready = bootstrap.Ready(s, shut, shut, shut, None, True, "in game", 1.0, None, None,
                            joined_at=900.0)
    path = tmp_path / "session.json"
    assert ready.detach(path) is True
    body = json.loads(path.read_text())
    assert (body["game_pid"], body["joined_at"], body["started"], body["hwnd"]) == (
        600, 900.0, "1.000", 7)
    assert "session stop" not in closed             # the game is kept
    s.ok_fields = None                              # nothing of ours to keep: a full close
    assert ready.detach(tmp_path / "other.json") is False and "session stop" in closed
