"""Writing files without the half-written-file failure mode.

The GUI settings panel rewrote ~/.config/hivemind/settings.yaml in place on
every single change -- and a QLineEdit fires textChanged once per keystroke, so
that is a rewrite per character. A kill, a crash or a full disk anywhere in
that window left a truncated document, and the next launch died with a
traceback before the window appeared. The router has the same exposure for
measured distances.

Write to a temporary file in the same directory, flush it to the platter, then
rename. rename(2) within a filesystem is atomic, so a reader sees either the
old file or the new one and never a partial one.

The other half: files that NAME A PROCESS (the watchdog's pidfile, the farm's
lock), which are believed only while the process they name is still the one
that wrote them. See `pid_running`.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write(path: Path | str, text: str, mode: int | None = None) -> None:
    """Replace `path` with `text`, atomically.

    `mode` sets the permissions explicitly, which matters for anything holding
    a private-server link: mkstemp creates 0600, so leaving it alone is the
    safe default rather than inheriting a umask.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent),
                                     prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())       # survive a power cut, not just a crash
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)          # atomic within one filesystem
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


# ---- files that name a process ---------------------------------------------
# A PIDFILE IS A CLAIM, NOT A FACT (DESIGN 8du). `var/night/watchdog.pid` is
# removed only when the watchdog exits normally, so a SIGKILL, an OOM kill or a
# reboot leaves it behind -- and pids wrap. MEASURED on this machine: pid_max is
# 4194304, run_farm was pid 650725 on 09-21 (var/night/watchdog.log), the
# watchdog 4035962 on 09-23 (restart-watchdog.log) and 92348 on 09-25, so the
# counter went all the way round in about two days. A stale file then names
# whatever got the number next, the owner's game included, and the GUI's Stop
# used to SIGKILL that process's whole group. So a pid read from a file is
# believed only while that process is still running the script that wrote it
# and started when the file says it did.

# ON WINDOWS THE PROCESS READERS AND THE ONE-FARM LOCK ARE platform/win/files'
# (psutil create_time, msvcrt): every `from hivemind.files import ...` --
# gui/launcher (which may not import platform itself), run_farm, preflight,
# and pid_running's default identity -- gets them with no change at the call.
# Linux: the /proc and flock bodies below, untouched (RL6 phase 3 wiring).
WINDOWS = os.name == "nt"


def _win():
    from .platform.win import files
    return files


def process_identity(pid: int) -> tuple[str, str] | None:
    """(command line, start time) of a live pid, or None if there is none.

    The start time is field 22 of /proc/<pid>/stat, clock ticks since boot;
    two processes that share a pid never share it. Field 2 is the command
    name in parentheses and may itself contain spaces, so the count starts
    after the last ')'.
    """
    if WINDOWS:
        return _win().process_identity(pid)
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
        stat = Path(f"/proc/{int(pid)}/stat").read_text()
    except (OSError, ValueError):
        return None
    after = stat.rsplit(")", 1)[-1].split()      # field 3 onwards
    start = after[19] if len(after) > 19 else ""
    return raw.replace(b"\0", b" ").decode(errors="replace"), start


def process_parent(pid: int) -> int | None:
    """The parent pid of a live `pid` (field 4 of /proc/<pid>/stat), or None.

    Counted after the last ')' for the same reason as `process_identity`.
    """
    if WINDOWS:
        return _win().process_parent(pid)
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text()
        return int(stat.rsplit(")", 1)[-1].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def pid_running(path: Path | str, script: str,
                identity=process_identity,
                start_path: Path | str | None = None) -> int | None:
    """The pid in `path`, if that process is still `script`, else None.

    The file holds "<pid>" or "<pid> <start time>". `start_path`, when given,
    is a second file holding the start time alone, for a pidfile that has to
    stay one bare number (the watchdog's: scripts/overnight.sh says why).
    With a start time both must match; without one (every file written
    before 2026-09-26) the command line alone must. `identity` is injectable
    so a test never has to trust a real pid.
    """
    try:
        parts = Path(path).read_text().split()
        pid = int(parts[0])
    except (OSError, ValueError, IndexError):
        return None
    if start_path is not None and len(parts) == 1:
        try:
            parts += Path(start_path).read_text().split()[:1]
        except OSError:
            pass
    if pid <= 0:
        return None
    found = identity(pid)
    if found is None:
        return None
    cmdline, start = found
    if script not in cmdline:
        return None
    if len(parts) > 1 and parts[1] != start:
        return None
    return pid


def take_lock(path: Path | str):
    """Hold `path` under an exclusive flock and write "<pid> <start>" into it.

    Returns the open handle -- the lock lasts exactly as long as it does, and
    the kernel drops it when the process dies however it dies -- or None when
    another process holds it. Opened for append so a refused attempt cannot
    wipe the holder's pid before finding out it was refused.
    """
    if WINDOWS:
        return _win().take_lock(path)
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    found = process_identity(os.getpid())
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()} {found[1] if found else ''}".strip() + "\n")
    handle.flush()
    return handle


@contextlib.contextmanager
def locked(handle):
    """Hold an exclusive lock on an open file for a read-modify-write
    (brain/owned, brain/sight): fcntl.flock, waiting for it, as those did.
    Windows: msvcrt.locking on win/files' byte past EOF, LK_LOCK (which
    retries for about 10 s, then raises OSError [verified: msvcrt docs]).
    ponytail: a 10 s ceiling on Windows; loop on LK_LOCK if a writer ever
    holds it longer."""
    if WINDOWS:
        import msvcrt
        from .platform.win.files import LOCK_OFFSET
        handle.flush()
        os.lseek(handle.fileno(), LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield handle
        finally:
            os.lseek(handle.fileno(), LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl
    fcntl.flock(handle, fcntl.LOCK_EX)
    try:
        yield handle
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)

