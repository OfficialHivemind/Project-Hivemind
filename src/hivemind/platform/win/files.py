"""Believing a pid, and the one-farm lock, on Windows (platform/api Processes).

hivemind/files says why (DESIGN 8du: a pidfile is a claim, not a fact) and
keeps the rule itself: `pid_running` and `atomic_write` are used from there
as they are. Only the two readers of a process and the lock differ:

  * identity = (command line, start time); the start time is psutil's
    create_time, which two processes sharing a pid never share [assumed:
    psutil reads the process creation time, stable for its life]. Of a
    Roblox process only the name stands in for the command line (no access to
    the game process: screen and input only, the plan 4c): a stale pidfile may name the game's pid after a reuse;
  * the lock is msvcrt.locking on one byte far past the end of the file.
    Windows byte locks are mandatory, so locking the pid text itself would
    make it unreadable to the GUI; a region past EOF may be locked [verified:
    LockFile, "You can lock bytes that are beyond the end of the current
    file"], and the OS lets go when the process dies however it dies
    [verified: LockFile remarks]. LK_NBLCK raises OSError when another
    process holds it [verified: Python msvcrt docs].
"""
from __future__ import annotations

import os
from pathlib import Path

import psutil

from ...files import atomic_write
from ...files import pid_running as _pid_running

__all__ = ["atomic_write", "process_identity", "process_parent", "pid_running", "take_lock"]

ROBLOX = "robloxplayerbeta.exe"
LOCK_OFFSET = 1 << 30          # a byte no pidfile ever reaches


def process_identity(pid: int) -> tuple[str, str] | None:
    """(command line, start time) of a live pid, or None if there is none."""
    try:
        p = psutil.Process(int(pid))
        name = p.name()
        start = f"{p.create_time():.3f}"
        if name.lower() == ROBLOX:
            return name, start
        try:
            # FORWARD SLASHES (RL6i): callers look for "scripts/run_farm.py"
            # and "src/hivemind/watchdog.py", but Windows spells our own
            # launches with backslashes (C:\...\scripts\run_farm.py), so
            # pid_running never matched our own watchdog or farm.
            line = " ".join(p.cmdline()).replace("\\", "/")
        except (psutil.AccessDenied, psutil.ZombieProcess):
            line = name                    # another user's process: its name is enough
        return line, start
    except (psutil.Error, ValueError, OSError):
        return None


def process_parent(pid: int) -> int | None:
    try:
        return psutil.Process(int(pid)).ppid()
    except (psutil.Error, ValueError, OSError):
        return None


def pid_running(path, script: str, identity=None, start_path=None) -> int | None:
    """hivemind/files.pid_running with this module's identity."""
    return _pid_running(path, script, identity or process_identity, start_path)


def take_lock(path):
    """Hold `path` under an exclusive lock and write "<pid> <start>" into it;
    the open handle, or None when another process holds it (files.take_lock)."""
    import msvcrt
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    try:
        os.lseek(handle.fileno(), LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    found = process_identity(os.getpid())
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()} {found[1] if found else ''}".strip() + "\n")
    handle.flush()
    return handle
