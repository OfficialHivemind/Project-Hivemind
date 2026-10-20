"""Game guard on Windows (platform/api GameGuard): is the owner playing a
game of his own right now? platform/gameguard says why it exists (the two
crashes beside his game) and what it does with the answer (pause, never
resume by itself); Watch and games_of are that module's, used as they are.

WHAT COUNTS, mirroring the Linux list, among HIS processes only (psutil's
username equal to ours):
  * a Steam game: Steam's own registry value HKCU\\Software\\Valve\\Steam
    RunningAppID, non-zero while a game runs [assumed: widely used by
    overlays and status tools; not in any Valve document];
  * Minecraft: a java.exe / javaw.exe whose command line says minecraft;
  * his own Roblox: a RobloxPlayerBeta.exe while no game of OURS runs.
    Windows Roblox keeps one client [assumed: its single-instance mutex], so
    with ours up the one Roblox is the bot's, as with Sober on Linux.
    `ours` is the pid of the game this bot launched or kept: `check` reads
    it from win/session's OURS_FILE (believed only while that pid still has
    the start time written there, so a reused pid is never "ours");
  * `guard.games`: names he adds, matched to a process name with or
    without ".exe";
  * NEW ON WINDOWS: whatever has the foreground and fills its whole monitor
    (an exclusive or borderless fullscreen game), except the desktop shell,
    OBS (he streams the bot with it) and Roblox itself (judged above).
    Here a second fullscreen app could not share the PC with the bot anyway:
    both need the foreground.

ANTI-CHEAT (the plan, 4c): of a Roblox process only its name is read --
no cmdline, environ or memory_maps, no handle that reads its memory. The
command line is read only of java processes.
"""
from __future__ import annotations

import os
from typing import Callable, Iterable

import psutil

from ..gameguard import Watch, games_of
from . import _user32 as w

__all__ = ["Watch", "games_of", "playing", "check", "steam_app", "fullscreen_app"]

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


def playing(games=(), ours: Iterable[int] = (), procs=None,
            steam: Callable[[], str | None] | None = steam_app,
            fullscreen: Callable[[], str | None] | None = fullscreen_app) -> str | None:
    """What the owner is playing, as a name for a message, or None."""
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
    ours_up = False
    for p in procs if procs is not None else psutil.process_iter(["name", "username"]):
        info = p.info
        if me is None or info.get("username") != me:
            continue                                   # not his (or unknown)
        name = (info.get("name") or "").lower()
        if name == ROBLOX:
            if p.pid in ours:
                ours_up = True
            roblox = roblox or "Roblox (your own)"
            continue                                   # its name only, nothing more
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
        return roblox
    return fullscreen() if fullscreen else None


def check(settings) -> str | None:
    """`playing` as the settings ask: None when guard.enabled is off."""
    if not settings.bool("guard.enabled"):
        return None
    from .session import our_game
    ours = our_game()
    return playing(games_of(settings.get("guard.games")), ours=() if ours is None else (ours,))
