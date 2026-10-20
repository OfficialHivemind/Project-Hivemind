"""RL6 phase 3: win/gameguard on a faked process list. Mirrors the Linux
rules (tests/unit/test_gameguard.py), and checks that a Roblox process is
never asked for more than its name."""
from __future__ import annotations

import types

import pytest

from hivemind.platform.win import _user32 as w
from hivemind.platform.win import gameguard as gg

ME, HIM_NOT = "PC\\owner", "NT AUTHORITY\\SYSTEM"


class Proc:
    def __init__(self, name, pid=100, user=ME, cmdline=(), started=0.0):
        self.pid, self._cmd = pid, list(cmdline)
        self.info = {"name": name, "username": user, "create_time": started}

    def cmdline(self):
        if self.info["name"].lower() == gg.ROBLOX:
            raise AssertionError("a Roblox process's command line was read")
        return self._cmd


@pytest.fixture(autouse=True)
def me(monkeypatch):
    fake = types.SimpleNamespace(
        Process=lambda pid=None: types.SimpleNamespace(username=lambda: ME, name=lambda: "x.exe"),
        Error=Exception, process_iter=None)
    monkeypatch.setattr(gg, "psutil", fake)


def look(procs, **kw):
    kw.setdefault("steam", None)
    kw.setdefault("fullscreen", None)
    kw.setdefault("windowed", None)
    return gg.playing(procs=procs, **kw)


def test_nothing_running_is_nothing():
    assert look([Proc("chrome.exe"), Proc("Discord.exe")]) is None


def test_steam_game_from_the_registry_value():
    assert look([], steam=lambda: "730") == "a Steam game (app 730)"


def test_minecraft_by_its_java_command_line():
    assert look([Proc("javaw.exe", cmdline=["-Dminecraft.launcher.brand=prism"])]) == "Minecraft"
    assert look([Proc("java.exe", cmdline=["-jar", "server-tools.jar"])]) is None


def test_his_own_roblox_counts_only_while_ours_is_not_up():
    procs = [Proc("RobloxPlayerBeta.exe", pid=4242)]
    assert look(procs) == "Roblox (your own)"
    assert look(procs, ours=[4242]) is None


def test_the_tray_roblox_is_not_a_game_but_one_still_opening_is():
    # MEASURED 2026-10-26 on Windows 11: Roblox's tray process (AppState/
    # TrayMode) ran 3.6 h with no game window, and the guard said "you're
    # playing Roblox", so the bot could never start beside the tray.
    now = 10_000.0
    tray = Proc("RobloxPlayerBeta.exe", pid=4242, started=now - 13_000)
    opening = Proc("RobloxPlayerBeta.exe", pid=4343, started=now - 5)
    asked = []

    def none_windowed(pids):
        asked.append(set(pids))
        return set()
    clock = lambda: now                                 # noqa: E731
    assert look([tray], windowed=none_windowed, clock=clock) is None
    assert look([tray], windowed=none_windowed, clock=clock,
                fullscreen=lambda: "eldenring") == "eldenring"    # the rest still looked at
    assert look([tray, opening], windowed=none_windowed, clock=clock) == gg.WINDOWLESS
    assert asked[-1] == {4242, 4343}
    # a window of theirs, however old the process: their game
    assert look([tray], windowed=lambda pids: {4242}, clock=clock) == "Roblox (your own)"
    # ours up: neither is theirs, and no window is looked for
    n = len(asked)
    assert look([tray, opening], ours=[4343], windowed=none_windowed, clock=clock) is None
    assert len(asked) == n
    # the watchdog's ledger line still reads as a game-guard stop
    assert gg.WINDOWLESS.startswith("Roblox (your own")


class WindowList:
    """user32 for windowed_pids: hwnd -> (pid, visible)."""
    def __init__(self, windows):
        self.windows = windows

    def EnumWindows(self, proc, _):
        for hwnd in self.windows:
            proc(hwnd, None)
        return 1

    def IsWindowVisible(self, hwnd):
        return self.windows[hwnd][1]

    def GetWindowThreadProcessId(self, hwnd, ref):
        ref._obj.value = self.windows[hwnd][0]
        return 1


def test_windowed_pids_counts_visible_windows_only():
    u = WindowList({0x10: (4242, False), 0x11: (4242, False), 0x20: (4343, True), 0x30: (99, True)})
    assert gg.windowed_pids({4242, 4343}, u) == {4343}
    assert gg.windowed_pids({4242}, u) == set()


def test_windowed_pids_assumes_windows_when_it_cannot_list_them():
    class Broken:
        def EnumWindows(self, *a):
            raise OSError("user32.dll: not Windows")
    assert gg.windowed_pids([1, 2], Broken()) == {1, 2}


def test_other_users_processes_are_not_his():
    assert look([Proc("RobloxPlayerBeta.exe", user=HIM_NOT),
                 Proc("javaw.exe", user=None, cmdline=["minecraft"])]) is None


def test_guard_games_match_with_or_without_exe():
    assert look([Proc("Unturned.exe")], games=["unturned"]) == "unturned"
    assert look([Proc("Unturned.exe")], games=["unturned.exe"]) == "unturned"
    assert look([Proc("Unturned.exe")]) is None


def test_a_fullscreen_foreground_app_counts_last():
    assert look([], fullscreen=lambda: "eldenring") == "eldenring"
    assert look([Proc("javaw.exe", cmdline=["minecraft"])],
                fullscreen=lambda: "eldenring") == "Minecraft"


class FakeUser32:
    def __init__(self, window=(0, 0, 1920, 1080), monitor=(0, 0, 1920, 1080), pid=777):
        self.window, self.monitor, self.pid = window, monitor, pid

    def GetForegroundWindow(self):
        return 0x55

    def GetWindowRect(self, hwnd, ref):
        ref._obj.left, ref._obj.top, ref._obj.right, ref._obj.bottom = self.window
        return 1

    def MonitorFromWindow(self, hwnd, flags):
        assert flags == w.MONITOR_DEFAULTTONEAREST
        return 1

    def GetMonitorInfoW(self, mon, ref):
        r = ref._obj.rcMonitor
        r.left, r.top, r.right, r.bottom = self.monitor
        return 1

    def GetWindowThreadProcessId(self, hwnd, ref):
        ref._obj.value = self.pid
        return 1


def test_fullscreen_app_needs_the_whole_monitor():
    names = {777: "EldenRing.exe"}
    assert gg.fullscreen_app(FakeUser32(), names.get) == "eldenring"
    windowed = FakeUser32(window=(100, 100, 1500, 900))
    assert gg.fullscreen_app(windowed, names.get) is None


def test_fullscreen_shell_obs_and_roblox_are_not_games():
    for name in ("explorer.exe", "obs64.exe", "RobloxPlayerBeta.exe"):
        assert gg.fullscreen_app(FakeUser32(), lambda pid: name) is None


def test_check_obeys_guard_enabled(monkeypatch):
    class S:
        def __init__(self, on):
            self.on = on

        def bool(self, key):
            return self.on

        def get(self, key):
            return "unturned"
    from hivemind.platform.win import session as ws
    monkeypatch.setattr(gg, "playing", lambda games, ours=(): f"saw {games} ours {list(ours)}")
    monkeypatch.setattr(ws, "our_game", lambda: None)
    assert gg.check(S(False)) is None
    assert gg.check(S(True)) == "saw ['unturned'] ours []"
    # the Roblox win/session launched (or kept) is the bot's, not their
    monkeypatch.setattr(ws, "our_game", lambda: 4242)
    assert gg.check(S(True)) == "saw ['unturned'] ours [4242]"
