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

MEASURED 2026-10-26 (var/night/run-*.log, every "stall watch:" line): 49 of
49 were not hangs -- 33 the start-up's own waits (the network wait of runs
1211-1243), 16 a gather pattern's pause steps (act/routes `time.sleep`),
sampled at the same line again and again. So the frame alone cannot end a
run. THE HEARTBEAT can: the main loop calls `beat()` at every step it
finishes (each line it says, each route step), and once `arm`ed, a silence
of `BEAT_STALL_S` -- not counting a pause or a Take Over (`held`) -- calls
`on_stall` once (run_farm `main_stalled`: the stacks, one Telegram line,
the exit).
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
# HOW LONG THE MAIN LOOP MAY GO WITHOUT FINISHING A STEP. MEASURED 2026-10-26
# over the last 300 runs (to run-1248), from the join to the teardown, every
# timestamped line but the whereami thread's: median gap 1 s, p99 37 s,
# p99.9 114 s; one gap over 20 min, run-1088's hang; then gathers (1067 s,
# Stump; a pattern's route steps beat) and the fights capped at 15 min
# (act/commando, act/crab MAX_FIGHT_S 900 s: 901 s seen). 20 min is the
# longest fight plus 5 min. ponytail: a loop that may run quiet past ~19 min
# needs its own `beat()`.
BEAT_STALL_S = 20 * 60.0

_beat = {"at": time.monotonic()}
_armed: dict = {}


def beat() -> None:
    """The main loop finished a step. Other threads' calls are ignored."""
    if threading.current_thread() is threading.main_thread():
        _beat["at"] = time.monotonic()


def arm(on_stall, held=lambda: False, stall_s: float = BEAT_STALL_S) -> None:
    """From now on a main loop silent `stall_s` while not `held()` calls
    `on_stall(seconds silent)`, once per silence. Needs `start` running."""
    _beat["at"] = time.monotonic()
    _armed.update(on_stall=on_stall, held=held, stall_s=float(stall_s), told=None)


def disarm() -> None:
    _armed.clear()


def _check(now: float) -> None:
    on_stall = _armed.get("on_stall")
    if on_stall is None:
        return
    try:
        held = bool(_armed["held"]())
    except Exception:
        held = False
    if held:                       # a pause or a Take Over is not a stall
        _beat["at"] = now
        return
    at = _beat["at"]
    if now - at >= _armed["stall_s"] and _armed.get("told") != at:
        _armed["told"] = at
        on_stall(now - at)


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
            try:
                _check(now)
            except Exception as exc:          # the watch itself never dies
                print(f"    stall watch: the heartbeat check failed ({exc})",
                      file=out, flush=True)
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
