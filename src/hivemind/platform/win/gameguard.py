"""Game guard on Windows (platform/api GameGuard): is the user playing a
game of their own right now? platform/gameguard says why it exists (the two
test-PC crashes beside another game) and what it does with the answer (pause, never
resume by itself); Watch and games_of are that module's, used as they are.

WHAT COUNTS, mirroring the Linux list, among the user's own processes only (psutil's
username equal to ours):
  * a Steam game: Steam's own registry value HKCU\\Software\\Valve\\Steam
    RunningAppID, non-zero while a game runs [assumed: widely used by
    overlays and status tools; not in any Valve document];
  * Minecraft: a java.exe / javaw.exe whose command line says minecraft;
  * the user's own Roblox: a RobloxPlayerBeta.exe while no game of OURS runs.
    Windows Roblox keeps one client [assumed: its single-instance mutex], so
    with ours up the one Roblox is the bot's, as with Sober on Linux.
    One whose processes own no visible window counts only while it is
    younger than TRAY_AFTER_S (a game still opening, WINDOWLESS): an older
    one is Roblox's system-tray updater, not a game (its windows are
    listed through user32, the process is not opened);
    `ours` is the pid of the game this bot launched or kept: `check` reads
    it from win/session's OURS_FILE (believed only while that pid still has
    the start time written there, so a reused pid is never "ours");
  * `guard.games`: names the user adds, matched to a process name with or
    without ".exe";
  * NEW ON WINDOWS: whatever has the foreground and fills its whole monitor
    (an exclusive or borderless fullscreen game), except the desktop shell,
    a recorder such as OBS and Roblox itself (judged above).
    Here a second fullscreen app could not share the PC with the bot anyway:
    both need the foreground.

NO ACCESS TO THE GAME PROCESS, SCREEN AND INPUT ONLY (the plan, 4c): of a
Roblox process only its name and start
time are read (as win/session does) --
no cmdline, environ or memory_maps, no handle that reads its memory. The
command line is read only of java processes.
"""
from __future__ import annotations

import os
import time
from typing import Callable, Iterable

import psutil

from ..gameguard import Watch, games_of
from . import _user32 as w

__all__ = ["Watch", "games_of", "playing", "check", "steam_app", "fullscreen_app",
           "windowed_pids", "WINDOWLESS"]

ROBLOX = "robloxplayerbeta.exe"
JAVA = {"java.exe", "javaw.exe"}
NOT_GAMES = {"explorer.exe", "obs64.exe", "obs32.exe", "obs.exe", ROBLOX,
             "searchhost.exe", "startmenuexperiencehost.exe", "lockapp.exe"}


def steam_app() -> str | None:
    """The running Steam game's app id, or None."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _ = winreg.QueryValueEx(key, "RunningAppID")
    except (ImportError, OSError):
        return None
    return str(value) if value and str(value) != "0" else None


def _stem(name: str) -> str:
    return name[:-4] if name.endswith(".exe") else name


def fullscreen_app(user32=None, name_of: Callable[[int], str] | None = None) -> str | None:
    """The process name of a foreground window that fills its monitor, or None."""
    try:
        user32 = user32 or w.dll("user32")
        hwnd = w.foreground(user32)
        if not hwnd or not w.fills_its_monitor(user32, hwnd):
            return None
        pid = w.window_pid(user32, hwnd)
    except OSError:
        return None
    if not pid or pid == os.getpid():
        return None
    try:
        name = (name_of or (lambda p: psutil.Process(p).name()))(pid).lower()
    except (psutil.Error, OSError):
        return None
    return None if name in NOT_GAMES else _stem(name)


def windowed_pids(pids: Iterable[int], user32=None) -> set[int]:
    """Which of `pids` own a visible top-level window (user32 only: the
    process itself is not opened). Every one of them when the windows
    cannot be listed, so a failure keeps the plain "playing" message."""
    pids = {int(p) for p in pids}
    try:
        user32 = user32 or w.dll("user32")
        return {pid for pid in (w.window_pid(user32, h) for h in w.top_windows(user32)
                                if user32.IsWindowVisible(h)) if pid in pids}
    except OSError:
        return pids


# ROBLOX'S TRAY PROCESS IS NOT A GAME. MEASURED 2026-10-26 (the Windows
# platform check, docs/pending/windows-platform-check.md): a
# RobloxPlayerBeta.exe had run for 3.6 h owning only two hidden windows (a
# 16x16 one and 'Default IME') and no game window; its Player log said
# "AppState/TrayMode", "Systray initialized", "Starting background update
# timers" and joined nothing, and the logs folder held one such ~6.5 KB
# Player log every 4 h for days. That is Roblox's system-tray updater, and
# the guard called it "you're playing Roblox (your own)" -- the words the
# owner's first Windows run logged on 2026-10-19 (gui/launcher LEDGER_SAYS),
# so with the tray on the bot could never start. Now a Roblox of theirs counts
# while one of its processes has a visible window, or while a windowless
# one is younger than TRAY_AFTER_S (a game still opening: a stop, said as
# WINDOWLESS). ponytail: TRAY_AFTER_S is an estimate [assumed: a game's
# window opens well inside 2 minutes]; the tray one was measured at hours.
TRAY_AFTER_S = 120.0
WINDOWLESS = "Roblox (your own, still opening: no window yet)"


def playing(games=(), ours: Iterable[int] = (), procs=None,
            steam: Callable[[], str | None] | None = steam_app,
            fullscreen: Callable[[], str | None] | None = fullscreen_app,
            windowed: Callable[[set[int]], set[int]] | None = windowed_pids,
            clock: Callable[[], float] = time.time) -> str | None:
    """What the owner is playing, as a name for a message, or None.
    `windowed` None counts every Roblox of theirs, windows or not."""
    extra = {g.lower() for g in games}
    ours = {int(p) for p in ours}
    app = steam() if steam else None
    if app:
        return f"a Steam game (app {app})"
    try:
        me = psutil.Process().username()
    except (psutil.Error, OSError):
        me = None
    roblox = None
    his: dict[int, float] = {}                         # their Roblox pids: their start times
    ours_up = False
    for p in procs if procs is not None else psutil.process_iter(
            ["name", "username", "create_time"]):
        info = p.info
        if me is None or info.get("username") != me:
            continue                                   # not theirs (or unknown)
        name = (info.get("name") or "").lower()
        if name == ROBLOX:
            if p.pid in ours:
                ours_up = True
            else:
                his[p.pid] = info.get("create_time") or 0.0
            roblox = roblox or "Roblox (your own)"
            continue                                   # its name and start time only
        if name in JAVA:
            try:
                line = " ".join(p.cmdline()).lower()
            except (psutil.Error, OSError):
                line = ""
            if "minecraft" in line:
                return "Minecraft"
        if extra & {name, _stem(name)}:
            return _stem(name)
    if roblox and not ours_up:
        if windowed is None or windowed(set(his)):
            return roblox
        if any(clock() - started < TRAY_AFTER_S for started in his.values()):
            return WINDOWLESS
        # only the tray's windowless Roblox: not a game (TRAY_AFTER_S)
    return fullscreen() if fullscreen else None


def check(settings) -> str | None:
    """`playing` as the settings ask: None when guard.enabled is off."""
    if not settings.bool("guard.enabled"):
        return None
    from .session import our_game
    ours = our_game()
    return playing(games_of(settings.get("guard.games")), ours=() if ours is None else (ours,))
