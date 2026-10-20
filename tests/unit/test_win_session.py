"""RL6 phase 3: win/session on a fake user32 and a fake process list (runs on
Linux; nothing here has touched a real Windows yet). What matters: the right
deep link, only OUR Roblox window is ever adopted or ended (pid AND start
time), the owner's own Roblox never is, and the client area is sized."""
from __future__ import annotations

import json
import types

import pytest

from hivemind.platform import api
from hivemind.platform.win import _user32 as w
from hivemind.platform.win import session as ws

HIS_PID, OUR_PID, LAUNCHER_PID = 500, 600, 590
HIS_HWND, OUR_HWND, OUR_POPUP = 0x50, 0x60, 0x61


class Proc:
    def __init__(self, procs, pid):
        self.procs, self.pid = procs, pid
        if pid not in procs:
            raise FakePsutil.NoSuchProcess(pid)
        self.info = {"name": procs[pid][0], "create_time": procs[pid][1]}

    def name(self):
        return self.procs[self.pid][0]

    def create_time(self):
        return self.procs[self.pid][1]

    def terminate(self):
        self.procs.ended.append(self.pid)
        del self.procs[self.pid]

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminate()

    def cmdline(self):
        raise AssertionError("a Roblox process's command line was read")


class Procs(dict):
    ended: list


class FakePsutil:
    class Error(Exception):
        pass

    class NoSuchProcess(Error):
        pass

    class TimeoutExpired(Error):
        pass

    def __init__(self):
        self.procs = Procs({HIS_PID: ("RobloxPlayerBeta.exe", 100.0)})
        self.procs.ended = []

    def Process(self, pid):
        return Proc(self.procs, pid)

    def process_iter(self, attrs):
        return [Proc(self.procs, pid) for pid in list(self.procs)]


class FakeUser32:
    def __init__(self, ps):
        self.ps = ps
        self.windows = {HIS_HWND: (HIS_PID, "Roblox")}     # hwnd -> (pid, title)
        self.fg = None
        self.client = (1600, 900)
        self.style = 0x14CF0000                            # an overlapped window
        self.iconic = False
        self.calls = []
        self.sent = []

    def EnumWindows(self, cb, _):
        for hwnd in list(self.windows):
            cb(hwnd, 0)
        return 1

    def IsWindow(self, hwnd):
        return hwnd in self.windows

    def IsWindowVisible(self, hwnd):
        return 1

    def GetWindowThreadProcessId(self, hwnd, ref):
        ref._obj.value = self.windows.get(hwnd, (0, ""))[0]
        return 1

    def GetWindowTextW(self, hwnd, buf, n):
        buf.value = self.windows.get(hwnd, (0, ""))[1]
        return len(buf.value)

    def GetForegroundWindow(self):
        return self.fg

    def SetForegroundWindow(self, hwnd):
        self.fg = hwnd
        return 1

    def SetProcessDpiAwarenessContext(self, ctx):
        self.calls.append("dpi")
        return 1

    def GetClientRect(self, hwnd, ref):
        ref._obj.left = ref._obj.top = 0
        ref._obj.right, ref._obj.bottom = self.client
        return 1

    def GetWindowRect(self, hwnd, ref):
        r = ref._obj
        r.left, r.top, r.right, r.bottom = 10, 20, 1626, 959
        return 1

    def MonitorFromWindow(self, hwnd, flags):
        return 1

    def GetMonitorInfoW(self, mon, ref):
        m = ref._obj.rcMonitor
        m.left, m.top, m.right, m.bottom = 0, 0, 1920, 1080
        return 1

    def GetWindowLongW(self, hwnd, index):
        assert index == ws.GWL_STYLE
        return self.style

    def SetWindowLongW(self, hwnd, index, value):
        self.style = value
        return 1

    def SetWindowPos(self, hwnd, after, x, y, cx, cy, flags):
        self.calls.append(("pos", hwnd, after, x, y, cx, cy, flags))
        if not flags & ws.SWP_NOSIZE:
            self.client = (cx, cy)
        return 1

    def IsIconic(self, hwnd):
        return self.iconic

    def ShowWindow(self, hwnd, cmd):
        self.calls.append(("show", hwnd, cmd))
        self.iconic = False
        return 1

    def SendInput(self, n, arr, size):
        for ev in arr[:n]:
            self.sent.append((ev.ki.wScan, ev.ki.dwFlags))
        return n


@pytest.fixture
def env(monkeypatch, tmp_path):
    ps = FakePsutil()
    monkeypatch.setattr(ws, "psutil", ps)
    monkeypatch.setattr(ws.datapaths, "VAR_ROOT", tmp_path)
    monkeypatch.setattr(ws.time, "time", lambda: 1000.0)
    popened = []

    class Popen:
        def __init__(self, argv, **kw):
            popened.append((argv, kw))
            self.pid = LAUNCHER_PID

        def poll(self):
            return 0

    monkeypatch.setattr(ws.subprocess, "Popen", Popen)
    monkeypatch.setattr(ws, "protocol_command",
                        lambda: r'"C:\Users\user\AppData\Local\Roblox\Versions\version-1\RobloxPlayerBeta.exe" %1')
    u = FakeUser32(ps)
    return types.SimpleNamespace(ps=ps, u=u, popened=popened, var=tmp_path,
                                 session=ws.WinSession(user32=u))


def game_opens(env, title="Roblox"):
    """Roblox (the launcher re-exec'd: a pid other than the Popen's) opens its window."""
    env.ps.procs[OUR_PID] = ("RobloxPlayerBeta.exe", 1001.5)
    env.u.windows[OUR_POPUP] = (OUR_PID, "")                  # a helper window first in z-order
    env.u.windows[OUR_HWND] = (OUR_PID, title)


# ---- the link ---------------------------------------------------------------
def test_the_deep_links():
    assert ws.win_uri(None) == "roblox://placeId=1537690962"
    assert ws.win_uri("https://www.roblox.com/games/1537690962/Bee-Swarm-Simulator"
                      "?privateServerLinkCode=12345678901234567890123456789012") == (
        "roblox://placeId=1537690962&linkCode=12345678901234567890123456789012")
    assert ws.win_uri("https://www.roblox.com/share?code=abcdef0123456789abcdef0123456789"
                      "&type=Server") == (
        "roblox://navigation/share_links?code=abcdef0123456789abcdef0123456789&type=Server")
    job = "roblox://placeId=1537690962&gameInstanceId=1a2b"
    assert ws.win_uri(job) == job                              # lastserver's own URIs


def test_launch_command_from_the_protocol_handler():
    exe = r'"C:\R\RobloxPlayerBeta.exe"'
    uri = "roblox://placeId=1&linkCode=2"
    assert ws.launch_command(uri, command=f"{exe} %1") == f'{exe} "{uri}"'
    assert ws.launch_command(uri, command=f'{exe} "%1"') == f'{exe} "{uri}"'


def test_launch_command_falls_back_to_the_newest_player(tmp_path, monkeypatch):
    # not this PC's real roblox:// handler (MEASURED 2026-10-21: it was used)
    monkeypatch.setattr(ws, "protocol_command", lambda: None)
    for n, version in enumerate(("version-a", "version-b")):
        exe = tmp_path / version / "RobloxPlayerBeta.exe"
        exe.parent.mkdir()
        exe.write_text("")
        import os
        os.utime(exe, (n, n))
    newest = ws.newest_player(tmp_path)
    assert newest.parent.name == "version-b"
    assert ws.launch_command("roblox://x", command=None, player=newest) == [str(newest), "roblox://x"]


def test_not_installed_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(ws, "newest_player", lambda local=None: None)
    monkeypatch.setattr(ws, "protocol_command", lambda: None)   # nor the real handler
    with pytest.raises(RuntimeError, match="not installed"):
        ws.launch_command("roblox://x", command=None)


def test_launch_is_detached_and_remembers_who_was_there(env):
    proc = env.session.launch_game(None)
    (argv, kw), = env.popened
    assert argv.endswith('"roblox://placeId=1537690962"')
    assert kw["creationflags"] == ws.DETACHED_PROCESS | ws.CREATE_NEW_PROCESS_GROUP
    assert proc.pid == LAUNCHER_PID and env.session.before == {HIS_PID}


# ---- which window is ours ---------------------------------------------------------
def test_his_roblox_is_never_ours(env):
    s = env.session
    s.launch_game(None)
    assert s.game_hwnd() is None and not s.game_window_open()
    game_opens(env)
    assert s.game_hwnd() == OUR_HWND                           # the titled window, not the helper
    assert (s.pid, s.started) == (OUR_PID, "1001.500")
    assert "(ours)" in s.describe_windows() and f"pid {HIS_PID}" in s.describe_windows()
    body = json.loads((env.var / "night" / "roblox.json").read_text())
    assert (body["game_pid"], body["started"]) == (OUR_PID, "1001.500")
    assert ws.our_game() == OUR_PID


def test_a_roblox_started_before_our_launch_is_not_ours(env):
    s = env.session
    env.ps.procs[OUR_PID] = ("RobloxPlayerBeta.exe", 990.0)    # before launched_at (1000) - grace
    env.u.windows[OUR_HWND] = (OUR_PID, "Roblox")
    s.launch_game(None)
    s.before.discard(OUR_PID)
    assert s.game_hwnd() is None


def test_an_ended_game_is_never_replaced_by_another(env):
    s = env.session
    s.launch_game(None)
    game_opens(env)
    assert s.game_hwnd() == OUR_HWND
    del env.ps.procs[OUR_PID], env.u.windows[OUR_HWND], env.u.windows[OUR_POPUP]
    env.ps.procs[777] = ("RobloxPlayerBeta.exe", 1500.0)       # theirs, started later
    env.u.windows[0x77] = (777, "Roblox")
    assert s.game_hwnd() is None
    assert ws.our_game() is None                               # the record no longer matches


def test_focus_is_the_foreground_window(env):
    s = env.session
    s.launch_game(None)
    game_opens(env)
    env.u.fg = HIS_HWND
    assert s.game_focused() is False
    env.u.fg = OUR_HWND
    assert s.game_focused() is True


# ---- the window --------------------------------------------------------------------
def test_fullscreen_makes_a_1920x1080_borderless_client_and_takes_the_front(env):
    s = env.session
    s.launch_game(None)
    game_opens(env)
    s.fullscreen_focused()
    assert env.u.style & ws.WS_FRAME == 0
    assert ("pos", OUR_HWND, None, 0, 0, 1920, 1080,
            ws.SWP_NOZORDER | ws.SWP_FRAMECHANGED) in env.u.calls
    assert env.u.fg == OUR_HWND
    s.leave_fullscreen()
    assert env.u.style == 0x14CF0000
    assert env.u.calls[-1] == ("pos", OUR_HWND, None, 10, 20, 1616, 939,
                               ws.SWP_NOZORDER | ws.SWP_FRAMECHANGED)


def test_a_maximized_window_is_restored_sized_and_the_size_said(env):
    """Run 5: a maximized captioned window gave a 1920x1009 client."""
    s = env.session
    s.launch_game(None)
    game_opens(env)
    env.u.style |= ws.WS_MAXIMIZE
    env.u.client = (1920, 1009)
    said = s.fullscreen_focused(settle_s=0)
    assert ("show", OUR_HWND, ws.SW_RESTORE) in env.u.calls
    assert said == "roblox window: client 1920x1080, borderless yes"


def test_a_size_that_will_not_take_is_retried_then_said_loudly(env):
    s = env.session
    s.launch_game(None)
    game_opens(env)
    env.u.client = (1920, 1009)
    env.u.SetWindowPos = lambda *a: env.u.calls.append(("pos",) + a) or 1   # Roblox ignores it
    said = s.fullscreen_focused(tries=3, settle_s=0)
    assert len([c for c in env.u.calls if c[0] == "pos"]) == 3
    assert said.startswith("roblox window: client 1920x1009, borderless yes -- NOT 1920x1080")


def test_a_right_sized_client_is_left_alone(env):
    s = env.session
    s.launch_game(None)
    game_opens(env)
    env.u.client = (1920, 1080)
    assert s.fullscreen_focused() == "roblox window: client 1920x1080, borderless no"
    assert not [c for c in env.u.calls if c[0] == "pos"] and env.u.style == 0x14CF0000


def test_minimized_and_restored_below_without_activation(env):
    s = env.session
    assert s.host_window_minimized() is None and s.restore_below() is False
    s.launch_game(None)
    game_opens(env)
    env.u.iconic = True
    assert s.host_window_minimized() is True
    assert s.restore_below() is True
    assert ("show", OUR_HWND, ws.SW_SHOWNOACTIVATE) in env.u.calls
    assert env.u.calls[-1][2] == ws.HWND_BOTTOM and env.u.calls[-1][-1] & ws.SWP_NOACTIVATE
    assert env.u.fg is None                                    # nothing took the front


def test_release_alt_goes_out_without_the_foreground(env):
    env.u.fg = HIS_HWND
    assert env.session.release_alt() == "Alt_L up, Alt_R up"
    assert env.u.sent == [(0x38, 0x8 | 0x2), (0x38, 0x8 | 0x2 | 0x1)]


def test_start_is_dpi_aware(env):
    assert env.session.start() is env.session and "dpi" in env.u.calls


# ---- ending, keeping ----------------------------------------------------------------
def test_stop_ends_only_our_game(env):
    s = env.session
    s.launch_game(None)
    game_opens(env)
    s.game_hwnd()
    s.stop()
    assert env.ps.procs.ended == [OUR_PID] and HIS_PID in env.ps.procs
    assert not (env.var / "night" / "roblox.json").exists()


def test_clear_stale_ends_a_crashed_runs_game_only_when_pid_and_start_match(env):
    env.ps.procs[OUR_PID] = ("RobloxPlayerBeta.exe", 1001.5)
    ws.keep_session(env.var / "night" / "roblox.json", game_pid=OUR_PID, joined_at=None,
                    started="1001.500")
    assert ws.WinSession(user32=env.u).clear_stale() == 1
    assert env.ps.procs.ended == [OUR_PID]
    # a reused pid (another start time) -- their game now -- is left alone
    env.ps.procs[OUR_PID] = ("RobloxPlayerBeta.exe", 5000.0)
    ws.keep_session(env.var / "night" / "roblox.json", game_pid=OUR_PID, joined_at=None,
                    started="1001.500")
    assert ws.WinSession(user32=env.u).clear_stale() == 0
    assert env.ps.procs.ended == [OUR_PID] and OUR_PID in env.ps.procs


def test_the_kept_record_round_trips(env):
    s = env.session
    s.launch_game(None)
    game_opens(env)
    s.game_hwnd()
    path = env.var / "night" / "session.json"
    ws.keep_session(path, game_pid=s.pid, joined_at=900.0, **s.kept_fields())
    body = json.loads(path.read_text())
    assert list(body)[:3] == ["game_pid", "joined_at", "kept_at"]   # Linux's shape, minus its lead
    assert (body["started"], body["hwnd"]) == ("1001.500", OUR_HWND)
    record, why = ws.kept_session_why(path)
    assert why == "" and record["joined_at"] == 900.0
    back = ws.WinSession.attach(record)
    back.user32 = env.u
    assert back.game_hwnd() == OUR_HWND and back.compositor_pid() == OUR_PID
    del env.ps.procs[OUR_PID]
    assert ws.kept_session_why(path) == (None, f"game pid {OUR_PID} is not our Roblox any more")
    assert ws.kept_session_why(env.var / "none.json") == (None, "no kept-session record")
    assert back.kept_fields() is None


def test_it_fits_the_seam():
    assert api.differences(api.GameSession, ws.WinSession) == []
    assert api.differences(api.KeptGame, ws) == []


def test_top_windows_walks_enumwindows():
    class U:
        def EnumWindows(self, cb, _):
            for h in (3, 0, 5):
                cb(h, 0)
            return 1
    assert w.top_windows(U()) == [3, 5]
