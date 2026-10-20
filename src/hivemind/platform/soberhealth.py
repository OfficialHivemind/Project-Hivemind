"""Sober and compositor health (ROADMAP A11): how the game went, named from what
the bot already captures, and how often a stop for it may relaunch.

THE RECOVERY IS THE ONE THAT ALREADY EXISTS: the world guard (brain/alive)
stops the run, the teardown ends OUR Sober through its own process handle and
then the nested session (act/bootstrap Ready.close), and the watchdog relaunches
20 s later. Nothing here signals Sober by name (DESIGN 8ds). What this adds:

* SOBER'S OWN "Crash" WINDOW AT A START. MEASURED 2026-10-26 01:04-17:49
  (run-1211..1243): 33 starts in a row; run-1215's window list shows a window
  "title: Crash", "class: sober_services" filling the session, and Sober's
  log (var/sober.log, data/sober/sober_logs/2026-10-26_15-01-26.log) ends
      FATAL: Crash: Failed to fetch remote manifest required for operation. ...
      FATAL: Crash: Previous error is fatal, trying to show GUI error dialog...
      FATAL: Crash: Aborting...
  Each start still waited act/bootstrap APP_TIMEOUT (150 s) for an app home
  that could not come ("attempt 1211 exited 1 after 200s"). `crash_line` reads
  the first FATAL line and the start ends at once, said by its cause.
* SOBER'S SPLASH, OR A BLACK SCREEN, MID-GAME. MEASURED 2026-10-20 18:18:33
  (run-1116, var/incidents/20261020-181833-hud-hold): all 150 frames of 10.8 s
  byte-identical, mean 17.0, spread 0.7 -- flat dark grey, one small line
  "Thanks fufexan!" at the bottom. The world guard already stopped on it (no
  HUD, 16 s); `screen_kind` names it in the stop.
* FROZEN FRAMES WITH THE HUD UP: nothing caught these before; the world guard
  passes any frame with the HUD drawn. `Frozen` times how long the screen has
  not changed by one sampled byte (FROZEN_AFTER, FROZEN_LIVE in brain/alive).
* THE NESTED COMPOSITOR LOST: every capture then fails ("the Wayland
  connection dropped", run-225.log), and the world guard took a failed capture
  as no evidence, forever. `compositor_alive` asks /proc for its pid.

And a relaunch for any of these is rate-limited: `relaunch_wait`.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import startfails

CRASH_SIGN = "FATAL: Crash: "
# Black: MEASURED none on disk; ASSUMED a mean this low is no picture at all.
BLACK_MEAN = 4.0
# Flat and dark: Sober's splash (above) at mean 17.0, spread 0.7. ASSUMED margins.
FLAT_SPREAD = 3.0
DARK_MEAN = 40.0
# Every SAMPLE-th pixel each way: 240 x 135 of a 1920x1080 frame.
SAMPLE = 8
# NEVER MORE THAN THIS MANY HEALTH RELAUNCHES AN HOUR. MEASURED 2026-10-26 over
# var/night/run-*.log (attempts 1-1247): 10 runs stopped "the world has been off
# screen" (163, 433, 444, 603, 888, 892, 1031, 1116, 1129, 1167), never two in an
# hour, so this cap never held up one of them; it holds up a loop of them.
MAX_PER_HOUR = 3
HOUR = 3600.0


def crash_line(sober_log: str) -> str:
    """The cause in Sober's first "FATAL: Crash:" line, or ''."""
    for line in sober_log.splitlines():
        at = line.find(CRASH_SIGN)
        if at >= 0:
            return line[at + len(CRASH_SIGN):].strip()
    return ""


def screen_kind(frame) -> str:
    """'' for a picture; else which empty screen it is, in words."""
    try:
        small = frame[::SAMPLE, ::SAMPLE, :3]
        mean, spread = float(small.mean()), float(small.std())
    except Exception:
        return ""
    if mean < BLACK_MEAN:
        return "a black screen"
    if spread < FLAT_SPREAD and mean < DARK_MEAN:
        return "a flat dark screen, like Sober's splash (run 1116)"
    return ""


class Frozen:
    """How long the screen has not changed by one sampled byte. Only watched
    time counts: looks more than `gap` apart start the count again (brain/alive
    UNWATCHED_GAP)."""

    def __init__(self, gap: float):
        self.gap = gap
        self.sig: bytes | None = None
        self.since = 0.0
        self.last: float | None = None

    def see(self, frame, now: float) -> float:
        try:
            sig = hashlib.blake2b(frame[::SAMPLE, ::SAMPLE].tobytes(),
                                  digest_size=16).digest()
        except Exception:
            return 0.0                    # not a frame we can sample
        if sig != self.sig or self.last is None or now - self.last > self.gap:
            self.sig, self.since = sig, now
        self.last = now
        return now - self.since


def compositor_alive(session) -> bool | None:
    """Is the nested session's compositor process still there? None when it
    cannot be told (Windows: no compositor; no pid known).
    ponytail: a pid reused within seconds reads alive; the farm loop's blind
    reads (brain/farm BLIND_READS_ALLOWED) still end that run."""
    if os.name == "nt":
        return None
    try:
        pid = session.compositor_pid()
    except Exception:
        return None
    if not pid:
        return None
    return Path(f"/proc/{int(pid)}").exists()


def relaunch_wait(path: Path, now: float) -> float:
    """Seconds to wait before relaunching after a health stop so no more than
    MAX_PER_HOUR relaunches fall in any hour; the relaunch is noted in `path`."""
    times = [float(t) for t in startfails.load(path).get("times", [])
             if now - float(t) < HOUR]
    wait = 0.0 if len(times) < MAX_PER_HOUR else max(0.0, times[-MAX_PER_HOUR] + HOUR - now)
    startfails.save(path, {"times": times + [now + wait]})
    return wait
