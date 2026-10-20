"""ONE GREPPABLE LINE PER RUN: why it ended, and who asked (release gate step 2).

Every run log ends with exactly one

    RUN END: <category>: <detail>

so a day's runs can be told apart by grep (tools/runend_tally.py): the
owner's Stop, a disconnect, a claim miss, a failed start, a crash. Before
this, uptime and rejoins mixed all of them (docs/pending/release-gate.md
section 3), and two stops (run-1082 19 Oct 11:32, run-1206 24 Oct 23:59)
had no reason in any log (docs/pending/rejoins-a7.md).

The categories, from the A7 census: owner stop, stop signal/<SIG>,
keep-game stop, kicked/<reason code>, idle kick, no internet,
start failed, claim miss, stranded rejoin, world guard, session limit,
low memory, game guard, locked, crash, ended (the farm loop's own reason).

`StopFlag` is run_farm's `stop`: a threading.Event that keeps the FIRST
cause it was set for. `stop.set()` with no cause (the ~40 older call sites)
records the caller's file:line, so even those name the line that stopped.

WHO SENT IT:
  * a Stop down the event socket: the peer's pid from SO_PEERCRED (Linux
    unix sockets) and that pid's command line (`peer`). MEASURED from the
    logs: run-1082 and run-1206 printed "stop requested" without the signal
    handler's "finishing the current step" line, so those two were NOT
    signals -- a socket Stop (or a silent stop.set) is the likely path.
  * a signal: the sender's pid is in siginfo, which Python's signal.signal
    handlers never get. Only sigwaitinfo/signalfd see it, and both need the
    signal BLOCKED in every thread -- and a blocked mask is inherited by
    every program the bot starts: MEASURED 2026-10-26, Python 3.14 here,
    SIGTERM blocked then subprocess.run(['grep', 'SigBlk', '/proc/self/
    status']) -> 0000000000004000 (SIGTERM blocked in the child). Sober and
    the nested session would then ignore our own teardown's SIGTERM. So a
    signal names itself and the parent (the watchdog forwards GUI Stops and
    `kill`s of itself, and says "signalled" in attempts.log when it does);
    a signal with no "[overnight] signalled" beside it came straight at
    run_farm's pid from something else.
"""
from __future__ import annotations

import os
import socket
import struct
import sys
import threading

PREFIX = "RUN END: "


def proc(pid: int) -> str:
    """'pid N (cmd args)', the command line cut short and any link left out
    (Sober's argv can hold the private server's link: never into a log)."""
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as fh:
            argv = fh.read().decode("utf-8", "replace").split("\0")
    except (OSError, ValueError):
        return f"pid {pid} (gone, or no /proc)"
    argv = [a for a in argv if a]
    if not argv:
        return f"pid {pid}"
    shown = [os.path.basename(argv[0])] + [
        "<link>" if "://" in a or "code=" in a.lower() or "token" in a.lower() else a[:60]
        for a in argv[1:4]]
    return f"pid {pid} ({' '.join(shown)}{' ...' if len(argv) > 4 else ''})"


def peer(conn) -> str:
    """Who is on the other end of a unix socket: SO_PEERCRED's pid. '' where
    there is none (TCP on Windows, or a platform without it)."""
    if not hasattr(socket, "SO_PEERCRED") or getattr(conn, "family", None) != socket.AF_UNIX:
        return ""
    try:
        pid, _uid, _gid = struct.unpack(
            "3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
    except OSError:
        return ""
    return proc(pid)


def line(category: str, detail: str) -> str:
    """The one line; the detail on one line, so grep shows all of it."""
    return f"{PREFIX}{category}: {' '.join(str(detail).split()) or '-'}"


def from_report(stopped_because: str | None) -> tuple[str, str]:
    """The farm loop's own reason (brain/farm Report.stopped_because) as a cause."""
    why = stopped_because or "no reason given"
    if "could not claim a hive" in why:
        return "claim miss", why
    if why.startswith("stopped by an error"):
        return "crash", why
    return "ended", why


class StopFlag(threading.Event):
    """`stop`, remembering the first cause it was set (or noted) for.

    No lock: `set` runs in signal handlers too, where a lock the interrupted
    code holds would deadlock. ponytail: two causes in the same instant keep
    either one."""

    def __init__(self):
        super().__init__()
        self.cause_: tuple[str, str] | None = None

    def cause(self, category: str, detail: str = "") -> None:
        """Note why the run will end, without stopping it (a failed start
        still waits out its back-off; the first cause is what ended it)."""
        if self.cause_ is None:
            self.cause_ = (category, detail)

    def set(self, category: str | None = None, detail: str = "") -> None:
        if category is None:
            caller = sys._getframe(1)
            category, detail = "stopped", (f"stop.set() at "
                                           f"{os.path.basename(caller.f_code.co_filename)}:"
                                           f"{caller.f_lineno} (the log above it says why)")
        self.cause(category, detail)
        super().set()

    def end_line(self, code: int | None) -> str:
        category, detail = self.cause_ or ("ended", "no cause recorded")
        return line(category, f"{detail} (exit {code})")
