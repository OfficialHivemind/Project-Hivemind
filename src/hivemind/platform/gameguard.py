"""Game guard (roadmap A14): is the user playing a game of their own right now?

WHY. Twice in testing the PC froze or crashed with the bot running beside
another game (once with little memory free, once a game plus a screen
recorder -> hard reboot). The rule was manual (never start the
bot beside another game); this makes it the bot's: a run PAUSES when a game
appears (never resumes by itself -- the user presses Resume or /resume), and no run starts while
one is up (run_farm's start, scripts/overnight.sh's gate).

WHAT COUNTS, read from /proc only (cmdline, comm, environ, status):
  * a Steam game: Steam's `reaper SteamLaunch AppId=<id>` wraps every launch,
    or a process carrying SteamAppId / SteamGameId / STEAM_COMPAT_APP_ID != 0
    (MEASURED 2026-10-14: the Steam client's own processes carry none of them);
  * Minecraft: a java whose command line says minecraft (Prism's
    -Dminecraft.launcher.brand, the libraries, the instance path);
  * the user's own Sober -- only while no compositor of OURS (nested Hyprland or
    headless labwc, by our config path) is alive. Sober
    refuses to run twice ("An instance of Sober is already running", session
    .py), so with ours up the one Sober there is the bot's (live, kept, or a
    crash's orphan that clear_stale ends with its compositor). Its environ
    cannot be read from outside the sandbox (session.game_in), hence this;
  * `guard.games`: names the user adds, matched to a process's comm or program name.
Only the user's own processes (the real uid in status, which a non-dumpable sandboxed
process still shows): the alt's Sober runs as its own user.
OBS is never a game: it is a recorder, often used to stream the bot.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

PROC = Path("/proc")
STEAM_ENV = (b"SteamAppId=", b"SteamGameId=", b"STEAM_COMPAT_APP_ID=")
SOBER_NAMES = {"sober", "org.vinegarhq.sober"}
NESTED_CONFIG = str(Path.home() / ".config/hivemind/nested.lua")   # session.Session.config_path
LABWC_CONFIG = str(Path.home() / ".config/hivemind/labwc")         # wlr_session.CONFIG_DIR


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


# The tag session.py's launcher gives the shell that starts the bot's Sober
# (`setsid sh -c '"$@"; exit $?' hivemind-game ...`); it waits on the game, so
# every process of the bot's Sober has it as an ancestor.
OURS_TAG = "hivemind-game"


def _ours(pid: str, proc: Path) -> bool:
    """Is `pid` under the bot's game launcher (OURS_TAG)?"""
    for _ in range(64):
        if OURS_TAG.encode() in _read(proc / pid / "cmdline"):
            return True
        parent = re.search(rb"\nPPid:\s+(\d+)", _read(proc / pid / "status"))
        if not parent or parent[1] in (b"0", b"1"):
            return False
        pid = parent[1].decode()
    return False


def games_of(text) -> list[str]:
    """guard.games as names: commas or spaces between them."""
    return [g for g in re.split(r"[,\s]+", str(text or "").lower()) if g]


def playing(games=(), proc: Path = PROC, nested_config: str = NESTED_CONFIG,
            uid: int | None = None, labwc_config: str = LABWC_CONFIG) -> str | None:
    """What the owner is playing, as a name for a message, or None."""
    uid = os.getuid() if uid is None else uid
    extra = {g.lower() for g in games}
    sober = theirs = None
    ours_up = False
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        owner = re.search(rb"\nUid:\s+(\d+)", _read(d / "status"))
        if not owner or int(owner[1]) != uid:
            continue
        argv = [a.decode("utf-8", "replace") for a in _read(d / "cmdline").split(b"\0") if a]
        if not argv:
            continue                                   # a kernel thread, or gone
        line = " ".join(argv)
        low = line.lower()
        prog = os.path.basename(argv[0]).lower()
        comm = _read(d / "comm").decode("utf-8", "replace").strip().lower()
        if (nested_config in line and "hyprland" in low) or (
                labwc_config in line and prog == "labwc"):     # either backend (RL1b)
            ours_up = True
        m = prog == "reaper" and re.search(r"SteamLaunch AppId=(\d+)", line)
        if m and m[1] != "0":
            common = re.search(r"steamapps/common/([^/]+)/", line)
            return common[1] if common else f"a Steam game (app {m[1]})"
        if prog.startswith("java") and "minecraft" in low:
            return "Minecraft"
        if extra & {prog, comm} or any(g[:15] == comm for g in extra):
            return prog if prog in extra else comm
        inner = os.path.basename(argv[argv.index("--") + 1]).lower() \
            if prog == "bwrap" and "--" in argv[:-1] else ""
        if SOBER_NAMES & {comm, prog, inner}:
            # NOT UNDER OUR LAUNCHER = THEIRS, even with our compositor up.
            # MEASURED 2026-10-20 18:18:50: they opened Roblox (parent systemd
            # --user) beside the bot's kept game; the bot's game went, and its
            # watchdog restarted it and launched its own Sober at 18:19:06.
            if not _ours(d.name, proc):
                # ponytail: a bot Sober orphaned from its launcher would read as
                # theirs and hold the bot off until it is closed; say so if seen.
                theirs = "Roblox (your own Sober)"
            elif sober is None:
                sober = "Roblox (your own Sober)"
        for var in _read(d / "environ").split(b"\0"):
            if var.startswith(STEAM_ENV):
                app = var.split(b"=", 1)[1].decode("utf-8", "replace")
                if app not in ("", "0"):
                    return f"a Steam game (app {app})"
    if theirs:
        return theirs
    return None if ours_up else sober


class Watch:
    """A running bot's half: `pause(name)` once a game is seen on two looks
    in a row (a process mid-exit is not a game), and not again until it is
    gone -- a Resume they press while still playing is theirs to make. Never
    resumes: they do."""

    def __init__(self, look, pause):
        self.look, self.pause = look, pause
        self.last = self.paused = None

    def tick(self) -> None:
        name = self.look()
        if name is None:
            self.paused = None
        elif name == self.last and self.paused is None:
            self.paused = name
            self.pause(name)
        self.last = name


def check(settings) -> str | None:
    """`playing` as the settings ask: None when guard.enabled is off."""
    if not settings.bool("guard.enabled"):
        return None
    return playing(games_of(settings.get("guard.games")))


if __name__ == "__main__":                              # read-only: what it sees now
    import sys
    found = playing(games_of(" ".join(sys.argv[1:])))
    print(f"game guard: {found or 'nothing being played'}")
