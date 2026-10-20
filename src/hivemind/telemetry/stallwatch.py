"""Say WHERE the main thread is stuck (2026-10-19, run-1088).

MEASURED: run-1088 read the quest list at 14:18, then its main thread sat in
a futex wait for 57 min (no log line, Roblox kicked it idle at 14:37, SIGTERM
did nothing) while the live view kept streaming. ptrace is off on this box,
so nothing could say which line it was on. Now:

- `kill -USR2 <pid>` prints every thread's stack (faulthandler), and
- a watcher thread prints the stacks itself when the main thread's innermost
  frame (file, line) has not changed for STALL_S -- once, then every REPEAT_S.

It only prints; it never stops or restarts anything. A legitimately idle main
thread (a long pause loop) can trip it, which costs one stack in the log.
ponytail: diagnostic only; turn it into a restart once a real cause is known.
"""
from __future__ import annotations

import faulthandler
import signal
import sys
import threading
import time
import traceback

STALL_S = 600.0
REPEAT_S = 1800.0
SAMPLE_S = 15.0


def where(frame) -> tuple:
    return (frame.f_code.co_filename, frame.f_lineno) if frame is not None else ()


def start(out=None, stall_s: float = STALL_S, sample_s: float = SAMPLE_S) -> threading.Thread:
    out = out or sys.stdout
    if hasattr(signal, "SIGUSR2"):
        try:
            faulthandler.register(signal.SIGUSR2, file=out, all_threads=True)
        except (ValueError, RuntimeError, OSError, AttributeError):
            pass
    main_id = threading.main_thread().ident

    def watch():
        last, since, said = None, time.monotonic(), 0.0
        while True:
            time.sleep(sample_s)
            here = where(sys._current_frames().get(main_id))
            now = time.monotonic()
            if here != last:
                last, since, said = here, now, 0.0
                continue
            if now - since >= stall_s and (not said or now - said >= REPEAT_S):
                said = now
                print(f"    stall watch: the main thread has been at {here[0]}:{here[1]} "
                      f"for {int(now - since)} s -- every thread's stack follows", file=out, flush=True)
                names = {t.ident: t.name for t in threading.enumerate()}
                for ident, frame in sys._current_frames().items():
                    print(f"    -- thread {names.get(ident, ident)}", file=out)
                    print("".join("      " + line for line in traceback.format_stack(frame)),
                          file=out, flush=True)

    t = threading.Thread(target=watch, name="hivemind-stallwatch", daemon=True)
    t.start()
    return t
