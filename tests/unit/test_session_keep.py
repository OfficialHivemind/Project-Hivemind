"""The game kept across a restart (platform/session, act/bootstrap): a run
asked to keep it writes the session down, and the next attaches only to a
compositor and a game that are provably ours (the owner's list, 2026-10-02,
item 18: every deploy that rejoined reset their Wealth Clock streak)."""
from __future__ import annotations

import json
import os

from hivemind.act import bootstrap
from hivemind.platform import session as sm


def _ours(monkeypatch, tmp_path, compositor=True, game=True, socket=True):
    monkeypatch.setattr(sm, "RUNTIME", tmp_path)
    if socket:
        (tmp_path / "wayland-1").write_text("")
    monkeypatch.setattr(sm, "ours_compositor", lambda pid, cfg: compositor)
    monkeypatch.setattr(sm, "game_in", lambda sig: game)


def _record(path):
    sm.keep_session(path, socket="wayland-1", signature="abc_1", hypr_pid=4242,
                    game_pid=4343, joined_at=1000.0)


def test_a_kept_session_is_read_back_when_it_is_ours(monkeypatch, tmp_path):
    _ours(monkeypatch, tmp_path)
    path = tmp_path / "session.json"
    _record(path)
    got = sm.kept_session(path, "/cfg")
    assert got["socket"] == "wayland-1" and got["hypr_pid"] == 4242
    assert got["joined_at"] == 1000.0


def test_nothing_is_kept_that_cannot_be_proved_ours(monkeypatch, tmp_path):
    path = tmp_path / "session.json"
    for kw in ({"compositor": False}, {"game": False}, {"socket": False}):
        sub = tmp_path / str(len(kw) + hash(str(kw)) % 1000)
        sub.mkdir()
        _ours(monkeypatch, sub, **kw)
        _record(path)
        assert sm.kept_session(path, "/cfg") is None, kw
    path.write_text("not json")
    assert sm.kept_session(path, "/cfg") is None
    assert sm.kept_session(tmp_path / "missing.json", "/cfg") is None


def test_this_process_is_no_compositor_of_ours():
    assert not sm.ours_compositor(os.getpid(), "/home/x/.config/hivemind/nested.lua")


def test_a_pid_no_longer_ours_is_never_signalled(monkeypatch):
    sent = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
    assert sm.end_pid(4242, lambda: False) is False and sent == []


class _Closable:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


class _Game:
    pid = 4343

    def __init__(self):
        self.terminated = 0

    def terminate(self):
        self.terminated += 1


class _Session:
    socket, signature = "wayland-1", "abc_1"

    def __init__(self):
        self.stopped = 0

    def compositor_pid(self):
        return 4242

    def kept_fields(self):
        # what win/session has and bootstrap.detach asks for on Windows
        return None

    def stop(self):
        self.stopped += 1


def _ready():
    return bootstrap.Ready(_Session(), _Closable(), _Closable(), _Closable(), None,
                           True, "in game", 1.0, _Game(), None)


def test_detach_keeps_the_game_and_writes_it_down(monkeypatch, tmp_path):
    # THE LINUX RECORD (socket, signature, compositor pid). Pinned, because on
    # Windows detach takes the win/session branch below and this fake's
    # kept_fields() is None there (MEASURED 2026-10-21 on Windows: red).
    monkeypatch.setattr(bootstrap.current, "WINDOWS", False)
    monkeypatch.setattr(bootstrap.time, "sleep", lambda s: None)
    ready = _ready()
    path = tmp_path / "session.json"
    assert ready.detach(path, joined_at=1234.0)
    assert ready.session.stopped == 0 and ready._game.terminated == 0
    assert ready.input.closed == 1 and ready.capture.closed == 1 and ready.conn.closed == 1
    body = json.loads(path.read_text())
    assert body["hypr_pid"] == 4242 and body["game_pid"] == 4343
    assert body["joined_at"] == 1234.0 and body["signature"] == "abc_1"


def test_detach_on_windows_keeps_the_game_by_its_pid_and_start_time(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.current, "WINDOWS", True)
    monkeypatch.setattr(bootstrap.time, "sleep", lambda s: None)
    ready = _ready()
    ready.session.kept_fields = lambda: {"started": "5.000", "hwnd": 77}
    path = tmp_path / "session.json"
    assert ready.detach(path, joined_at=1234.0)
    assert ready.session.stopped == 0 and ready._game.terminated == 0
    body = json.loads(path.read_text())
    assert body["game_pid"] == 4242 and body["started"] == "5.000" and body["hwnd"] == 77
    assert "socket" not in body and "hypr_pid" not in body


def test_detach_on_windows_with_no_game_of_ours_ends_it_as_close_does(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.current, "WINDOWS", True)
    monkeypatch.setattr(bootstrap.time, "sleep", lambda s: None)
    ready = _ready()                                 # kept_fields() is None
    path = tmp_path / "session.json"
    assert ready.detach(path) is False and not path.exists()
    assert ready.session.stopped == 1 and ready._game.terminated == 1


def test_close_still_ends_the_game_and_the_compositor(monkeypatch):
    monkeypatch.setattr(bootstrap.time, "sleep", lambda s: None)
    ready = _ready()
    ready.close()
    assert ready.session.stopped == 1 and ready._game.terminated == 1


def test_a_failed_start_is_not_kept(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap.time, "sleep", lambda s: None)
    ready = _ready()
    ready.ok = False
    path = tmp_path / "session.json"
    assert ready.detach(path) is False and not path.exists()
    assert ready.session.stopped == 1 and ready._game.terminated == 1


def test_the_game_is_launched_under_its_own_session_parent(monkeypatch):
    """19 Oct: bwrap's --die-with-parent made run_farm the game's parent, so a
    keep-the-game restart killed it. The game now runs under `setsid sh`."""
    from hivemind.platform import session as S
    seen = {}

    class P:
        pid = 1

    def fake_popen(argv, **kw):
        seen["argv"] = argv
        return P()
    monkeypatch.setattr(S.subprocess, "Popen", fake_popen)
    s = S.Session.__new__(S.Session)
    s.socket = "wayland-9"
    s.launch_game()
    argv = seen["argv"]
    assert argv[:2] == ["setsid", "sh"] and argv[5] == S.SOBER


def test_bootstrap_launches_the_game_through_outliving():
    """The live launch is act/bootstrap's own Popen, not Session.launch_game --
    the 42595f6 fix missed it (19 Oct 09:0x: bwrap still run_farm's child)."""
    from pathlib import Path
    import hivemind
    from hivemind.platform import session as S
    src = (Path(hivemind.__file__).parent / "act" / "bootstrap.py").read_text()
    assert "session_mod.outliving(argv)" in src
    assert S.outliving(["x", "y"])[:2] == ["setsid", "sh"] and S.outliving(["x"])[-1] == "x"


def test_the_record_on_disk_is_unchanged(monkeypatch, tmp_path):
    """RL6 phase 2 step 4: keep_session takes the Linux fields as **extra,
    and writes the same JSON, key for key and in the same order."""
    monkeypatch.setattr(sm.time, "time", lambda: 5000.0)
    path = tmp_path / "session.json"
    sm.keep_session(path, socket="wayland-1", signature="abc_1", hypr_pid="4242",
                    game_pid=4343, joined_at=1000.0, note="x")
    old = {"socket": "wayland-1", "signature": "abc_1", "hypr_pid": 4242,
           "game_pid": 4343, "joined_at": 1000.0, "kept_at": 5000.0, "note": "x"}
    assert path.read_text() == json.dumps(old, indent=1)
