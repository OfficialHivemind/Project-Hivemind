"""Streaming what the bot sees to the GUI, without choking the socket.

The GUI has always had a live-view panel and has never had anything to show,
because nothing emitted `Frame` events. The owner asked for it directly: a
live view for the AI, at a frame rate good enough to see clearly.

TWO DIFFERENT "LIVE VIEWS", AND THEY WANT OPPOSITE THINGS

The AI's view is already as good as it gets: every decision reads a fresh
1920x1080 frame straight from `zwlr_screencopy`, measured at ~75 fps, in full
resolution with no compression. Nothing here touches that path, and nothing
should -- clarity for the model is resolution and freshness, not frame rate,
and it already has both.

The HUMAN's view is a different problem. Sending full frames over the event
socket would put megabytes per second through a channel carrying text, and
would tie the GUI's frame rate to the bot's. So this writes JPEGs to one file
and sends the PATH, which is what `telemetry.events.Frame` was designed for.

THE PICTURE AND THE BOXES RUN APART (DESIGN 8eb). The owner: the stream mode
view was choppy. Over 222 run logs the view
made 13.9 frames a second of the 20 asked for, and it was not even: the
overlay pass (the detection boxes) ran on the same thread on one frame in
three and took 84 ms, so two frames came 50 ms apart and the third over
100 ms later. Now the picture loop only captures, encodes and announces, on
a deadline, and the overlay pass runs on its own thread on the newest frame at
the rate it ran before. The boxes on a frame are the newest the overlay pass
has finished, so no frame carries its own: MEASURED with an 84 ms pass
(DESIGN 8eb), they are 0.1 to 0.3 s behind the picture, median 0.2, at 20 or
30 fps. Before, when the pass ran on the frame it drew on, they were 0 to
0.16 s behind, median 0.11, and one frame in three had its own. `describe`
reports the lag live.

It also degrades rather than interfering: if encoding or writing fails, the
streamer counts the failure and carries on. A live view that can stop the bot
is worse than no live view.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path

from ..datapaths import runtime_dir
from ..world import aimode
from .events import Frame, Log

# 30 FRAMES A SECOND BY DEFAULT, up from 20 (DESIGN 8eb). A frame is the
# capture (10 ms, the median of 245 run logs' "fps of work" lines) and a
# 3.0 ms encode (ENCODING, below), about 13 ms of a 33 ms frame. The capture
# holds the screencopy lock the bot's own looks also take, which is what keeps
# this at 30 and not 60: at 30 the live view holds that lock 30% of the time
# (at 20, 20%). MEASURED in the offline replay (three runs each, DESIGN
# 8eb), the bot's own 10 Hz look -- the real ThreatWatch through the same
# lock -- took 49.7 ms and made 6.64 looks a second at 30; 48.7 and 6.66
# beside the old view at 20; 46.4 and 6.81 with no view at all; 50.9 and 6.58
# at 60, where the GUI's decoding doubles (0.26 to 0.49 of a core). The
# replay's capture is a steady 10 ms and the real one waits for the nested
# compositor's next frame of a 60 Hz output, so at 60 there is no slack.
# `describe` reports the lock waits live.
#
# The OWNER'S VIEW is what this number controls. The BOT'S view is not: every
# decision reads a fresh full-resolution frame straight from screencopy,
# uncompressed, at whatever moment it asks. Raising this does not make the bot
# see better, and lowering it would not make it see worse.
DEFAULT_FPS = 30.0
# ENCODING: THE FRAME AS CAPTURED, FULL SIZE, ALL FOUR CHANNELS. MEASURED on
# saved 1920x1080 frames (DESIGN 8eb), CPU per frame at 30 a second:
#   frame[:, :, :3] (as before)       11.1 ms  -- 8 of it copying the slice,
#                                                 which is not contiguous
#   the BGRA frame itself              3.1 ms  -- the same JPEG bytes: the
#                                                 encoder drops alpha itself
#   shrunk to 1280x720 first          20.7 ms  (2.9 ms of wall time: OpenCV's
#                                                 thread pool spins after it)
# So the picture is not shrunk here even though no view shows more than the
# stream's 1280x720: the GUI decodes at the size its views need
# (gui/panels/liveview), and the boxes stay in the frame's own pixels.
# THE BOXES' RATE, in ms between overlay passes (`perf.overlay_ms`). 216 is
# the rate they ran at: one frame in three at the 13.9 fps the view made
# (2,524,551 frames over the 181,597 s the live view ran in 222 run logs,
# from their own timestamps -- the logs' "fps of work" leaves out the sleep
# after each fast frame, so it read 16.7). Keeping it keeps the overlay's
# cost to the bot where it was -- 84 ms a pass (28 ms a frame, times three),
# 62 to 110 measured offline -- and keeps `vision.pinned`'s lessons, which
# the pass teaches, at the spacing they were learned at.
DEFAULT_OVERLAY_MS = 216
# THE FRAME HOOK'S RATE. `on_frame` feeds the incident recorder, whose window
# is 150 frames (telemetry/incidents.DEFAULT_WINDOW), and the locator.
# MEASURED over the newest 400 saves in var/incidents, those 150 frames
# spanned a median 10.8 s (quartiles 10.1 to 11.3): 13.8 frames a second,
# which the run logs agree with (13.9). A faster picture must not shorten the
# black box's seconds, so the hook keeps its 13.8.
TAP_FPS = 13.8
# LOW CPU MODE (once `perf.low_power`, ux report #10; now the Eco AI mode,
# world/aimode): the view
# runs at most 15 fps -- still above TAP_FPS, so the black box and the
# locator get the frames they always got -- and the boxes at most every
# 432 ms, twice DEFAULT_OVERLAY_MS. ASSUMED: about half of each one's CPU
# (both costs scale with their rate, per the measures above); not measured live.
LOW_POWER_FPS = 15.0
LOW_POWER_OVERLAY_MS = 432
DEFAULT_QUALITY = 70          # JPEG; 154 KB a 1920x1080 frame
# How often the view reports its own rate in the run log: once after the
# first minute, so a run shows it early, then every half hour.
REPORT_FIRST_S = 60.0
REPORT_EVERY_S = 1800.0
# The frame spacings kept for the report, about twenty seconds at 30 fps.
SPACINGS_KEPT = 600


class _Pace:
    """Due every `seconds` on average, whatever rate it is asked at.

    Keeps its phase while it is less than one period late, so asked 30 times
    a second for 20 it takes two frames in three rather than every other one;
    after a longer stall it starts a new phase instead of catching up in a
    burst.
    """

    def __init__(self, seconds: float):
        self.seconds = max(0.0, float(seconds))
        self.due = 0.0

    def ready(self, now: float) -> bool:
        if now < self.due:
            return False
        late = now - self.due
        self.due = (self.due if late < self.seconds else now) + self.seconds
        return True


class _Overlay:
    """The overlay pass on its own thread, on the newest frame it was handed.

    `offer` never waits: a frame offered while the pass is running, or before
    it is due, is not taken. `result` is (screen, detections, at) from the
    last pass that finished, `at` being the `now` its frame was offered with
    (None before the first), so the view can say how far behind the picture
    its boxes are. `dropped` counts frames offered when a pass was due but
    the last one was still running -- the stale frames this one-slot worker
    let go rather than queue -- and `most` is the slowest pass, seconds.
    """

    def __init__(self, work, every: float):
        self.work = work
        self.pace = _Pace(every)
        self.result: tuple = ("", [], None)
        self.ran = 0
        self.spent = 0.0
        self.most = 0.0
        self.dropped = 0
        self._frame = None
        self._busy = False
        self._stopped = False
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None

    def offer(self, frame, now: float) -> bool:
        with self._cond:
            if self._busy or self._frame is not None:
                if now >= self.pace.due:
                    self.dropped += 1
                return False
            if not self.pace.ready(now):
                return False
            self._frame = (frame, now)
            self._cond.notify()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="hivemind-liveview-boxes")
            self._thread.start()
        return True

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._frame is None and not self._stopped:
                    self._cond.wait()
                if self._stopped:
                    return
                (frame, at), self._frame = self._frame, None
                self._busy = True
            began = time.monotonic()
            try:
                screen, found = self.work(frame)
                self.result = (screen, found, at)
            except Exception:
                self.result = ("", [], at)   # never let the overlay stop the view
            took = time.monotonic() - began
            self.spent += took
            self.most = max(self.most, took)
            self.ran += 1
            with self._cond:
                self._busy = False

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)


def _low_power(settings) -> bool:
    """The Eco AI mode (world/aimode); False for a settings object that
    cannot say."""
    return aimode.is_eco(settings)


def _percentile(values, fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


class LiveView:
    """Writes the latest frame to a file and announces it.

    `frames()` returns a BGRA/BGR array. `emit(event)` is the same sink the
    rest of the bot narrates through.
    """

    @staticmethod
    def fps_from(settings, fallback: float = DEFAULT_FPS) -> float:
        """`perf.capture_fps`, which decides how hard this pushes the machine.

        Every frame is a screencopy from the nested compositor, a JPEG encode
        and a write. On 2026-09-20 a fourth concurrent screencopy client killed
        the game twice (docs/DESIGN.md 8a), so the rate this runs at is a
        stability setting and not a cosmetic one -- which is exactly why it
        should be reachable from the GUI rather than frozen in a constant.

        Clamped to something sane: below half a frame a second the live view is
        not live, and above 60 it is pushing the compositor for a picture
        nobody can see change.
        """
        try:
            value = float(settings.int("perf.capture_fps"))
        except Exception:
            return fallback
        fps = min(60.0, max(0.5, value)) if value > 0 else fallback
        return min(fps, LOW_POWER_FPS) if _low_power(settings) else fps

    @staticmethod
    def overlay_seconds_from(settings,
                             fallback: float = DEFAULT_OVERLAY_MS / 1000.0) -> float:
        """`perf.overlay_ms`: the time between overlay passes, in seconds.

        It replaces `perf.overlay_every` ("every Nth frame"), which stopped
        describing anything once the boxes left the picture's thread: the
        pass now runs on its own clock, so its cost does not grow with the
        frame rate. Clamped to 50..3000 ms; a pass takes 62 to 110 ms, so
        below that it simply runs back to back.
        """
        try:
            value = int(settings.int("perf.overlay_ms"))
        except Exception:
            return fallback
        seconds = min(3000, max(50, value)) / 1000.0 if value > 0 else fallback
        return max(seconds, LOW_POWER_OVERLAY_MS / 1000.0) if _low_power(settings) \
            else seconds

    def __init__(self, frames, emit, path: str | Path | None = None,
                 fps: float = DEFAULT_FPS, quality: int = DEFAULT_QUALITY,
                 overlay_seconds: float = DEFAULT_OVERLAY_MS / 1000.0,
                 tap_fps: float = TAP_FPS,
                 screen_of=None, on_frame=None, detect=None, lock_waits=None):
        self.path = Path(path) if path else runtime_dir() / "hivemind-live.jpg"
        self.frames = frames
        self.emit = emit
        self.fps = max(0.5, float(fps))
        self.interval = 1.0 / self.fps
        self.quality = int(quality)
        self.screen_of = screen_of
        # Anything else that wants the same frame -- the incident recorder
        # takes this, so there is ONE capture feeding both the GUI and the
        # black box rather than two loops competing for the compositor. At
        # most `tap_fps` a second: see TAP_FPS.
        self.on_frame = on_frame
        self._tap = _Pace(1.0 / max(0.5, float(tap_fps)))
        self.tapped = 0
        # `detect(frame) -> [{kind,x,y,w,h,label}]`. Injected rather than
        # imported: telemetry must not depend on vision (the layering test
        # enforces it), and the overlay is the GUI's business, not this
        # module's.
        self.detect = detect
        # THE OVERLAY ON ITS OWN THREAD, NOT ON EVERY Nth FRAME. MEASURED
        # 2026-09-22: at one frame in one, four runs made 7.3 to 8.4 fps of
        # the 20 asked for; at one in three, 222 runs made 13.9, unevenly
        # (DESIGN 8eb). Detection is what makes the view USEFUL, so it is
        # not switched off -- it is decoupled. The picture streams at its
        # own rate and each frame carries the newest finished boxes, which
        # are 0.1 to 0.3 s behind it (the module docstring).
        self.overlay = (_Overlay(self._boxes, overlay_seconds)
                        if detect is not None or screen_of is not None else None)
        # `lock_waits()` -> {thread name: (captures, waited s, most s)}, the
        # screencopy lock's own count (platform/wl/screencopy). What this
        # view costs the bot's own looks is how long THEY wait for it.
        self.lock_waits = lock_waits
        self.sent = 0
        # WHERE THE TIME ACTUALLY GOES, totalled in seconds so `describe`
        # can report the per-frame cost of each stage. Added because the
        # first guess at why the rate was low blamed the JPEG encode; the
        # encode's 11 ms turned out to be 8 ms of copying (ENCODING).
        self.spent = {"capture": 0.0, "encode": 0.0, "tap": 0.0, "total": 0.0}
        self.failures = 0
        # when the loop started and the spacing of recent captures, for the
        # rate this view actually achieved and how even it was
        self._started: float | None = None
        self._last_capture: float | None = None
        self._spacings: deque = deque(maxlen=SPACINGS_KEPT)
        # how far behind its frame's capture each sent frame's boxes were
        self._box_ages: deque = deque(maxlen=SPACINGS_KEPT)
        self.late = 0                 # frames over 1.5 intervals after the last
        self._report_at = REPORT_FIRST_S
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _boxes(self, frame) -> tuple:
        """One overlay pass: the screen state and the boxes. Runs on the
        overlay's thread."""
        screen = ""
        if self.screen_of is not None:
            try:
                screen = str(self.screen_of(frame))
            except Exception:
                screen = ""
        found = []
        if self.detect is not None:
            try:
                found = list(self.detect(frame))
            except Exception:
                found = []          # never let the overlay stop the view
        return screen, found

    def once(self) -> bool:
        """Capture, write, announce. True if a frame was sent."""
        try:
            began = time.monotonic()
            frame = self.frames()
            if frame is None or getattr(frame, "size", 0) == 0:
                return False
            captured = time.monotonic()
            stamp = time.time()
            self.spent["capture"] += captured - began
            if self._last_capture is not None:
                spacing = captured - self._last_capture
                self._spacings.append(spacing)
                if spacing > 1.5 * self.interval:
                    self.late += 1
            self._last_capture = captured
            # THE BOXES' PASS IS OFFERED THE FRAME FIRST, before the encode,
            # so the boxes start as soon after the capture as they can.
            # `offer` never waits.
            if self.overlay is not None:
                self.overlay.offer(frame, captured)
            sent = self._send(frame, stamp, captured)
            # THE FRAME HOOK WHETHER OR NOT THE PICTURE WAS WRITTEN: the
            # camera's file must not gate the black box or the locator, as a
            # black box must never stop the camera. After the write, not
            # before it: the hook costs 3.0 to 4.8 ms on the frames it runs
            # on (the offline replays' "frame hook 1.4 to 2.2" a frame, at
            # 13.8 of 30; most of it the incident JPEG), and in front of the
            # write that would sit between the capture and the GUI's
            # picture, shown 25 ms after the capture with a 99th percentile
            # of 11.3 to 19.7 ms already spent (gui/panels/liveview).
            if self.on_frame is not None and self._tap.ready(captured):
                tapping = time.monotonic()
                try:
                    self.on_frame(frame)
                    self.tapped += 1
                except Exception:
                    pass          # a black box must never stop the camera
                self.spent["tap"] += time.monotonic() - tapping
            self.spent["total"] += time.monotonic() - began
            return sent
        except Exception:
            self.failures += 1
            return False

    def _send(self, frame, stamp: float, captured: float) -> bool:
        """Encode, write and announce one captured frame. A failure is
        counted and returns False; it never raises."""
        try:
            import cv2
            # THE FRAME AS CAPTURED: see ENCODING.
            height, width = frame.shape[:2]
            # Write to a temp name and rename, so the GUI never opens a file
            # that is half-written. os.replace is atomic within a filesystem.
            temp = self.path.with_suffix(".part.jpg")
            encoding = time.monotonic()
            ok = cv2.imwrite(str(temp), frame,
                             [cv2.IMWRITE_JPEG_QUALITY, self.quality])
            if not ok:
                self.failures += 1
                return False
            os.replace(temp, self.path)
            self.spent["encode"] += time.monotonic() - encoding
            screen, detections, boxes_at = (self.overlay.result
                                            if self.overlay is not None
                                            else ("", [], None))
            if boxes_at is not None:
                self._box_ages.append(captured - boxes_at)
            # STAMPED AT THE CAPTURE, so the GUI can show frames at the
            # spacing they were taken at (gui/panels/liveview).
            self.emit(Frame(at=stamp, path=str(self.path), width=int(width),
                            height=int(height), screen=screen,
                            detections=detections))
            self.sent += 1
            return True
        except Exception:
            self.failures += 1
            return False

    def _run(self) -> None:
        # ON A DEADLINE, NOT "SLEEP WHAT IS LEFT": each capture starts one
        # interval after the last one was due, so a slow frame does not push
        # every later one back. A frame more than a whole interval behind
        # starts a new phase rather than a burst of catch-up captures.
        self._started = due = time.monotonic()
        while not self._stop.is_set():
            self.once()
            now = time.monotonic()
            if now - self._started >= self._report_at:
                self._report_at += REPORT_EVERY_S
                try:
                    self.emit(Log(message=f"live view: {self.describe()}",
                                  source="liveview"))
                except Exception:
                    pass
            due += self.interval
            if now - due > self.interval:
                due = now
            self._stop.wait(max(0.0, due - now))

    def start(self) -> "LiveView":
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="hivemind-liveview")
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        if self.overlay is not None:
            self.overlay.stop()

    def describe(self) -> str:
        line = (f"{self.sent} frames streamed to {self.path}"
                + (f", {self.failures} failed" if self.failures else ""))
        if not self.sent:
            return line
        per = {k: v * 1000.0 / self.sent for k, v in self.spent.items()}
        rest = max(0.0, per["total"] - per["capture"] - per["encode"] - per["tap"])
        line += (f" — {1000.0 / max(per['total'], 1e-6):.1f} fps of work"
                 f" ({per['total']:.0f}ms/frame: capture {per['capture']:.0f},"
                 f" encode {per['encode']:.1f},"
                 f" frame hook {per['tap']:.1f}, rest {rest:.1f})")
        if self._started is not None and self.sent > 1:
            ran = max(1e-6, (self._last_capture or self._started) - self._started)
            line += f"; made {(self.sent - 1) / ran:.1f} fps of {self.fps:g} asked"
        if self._spacings:
            spacings = list(self._spacings)
            line += (f", spacing median {1000 * _percentile(spacings, 0.5):.0f} ms,"
                     f" 95th {1000 * _percentile(spacings, 0.95):.0f} ms,"
                     f" {self.late} frames over 1.5x late")
        if self.overlay is not None and self.overlay.ran:
            line += (f"; boxes {self.overlay.ran} passes, "
                     f"{1000 * self.overlay.spent / self.overlay.ran:.0f} ms each"
                     f" (slowest {1000 * self.overlay.most:.0f}),"
                     f" {self.overlay.dropped} due frames dropped while one ran")
            if self._box_ages:
                ages = list(self._box_ages)
                line += (f", median {1000 * _percentile(ages, 0.5):.0f} ms"
                         f" behind the picture (95th"
                         f" {1000 * _percentile(ages, 0.95):.0f})")
        waits = self._lock_line()
        if waits:
            line += f"; {waits}"
        return line

    def _lock_line(self) -> str:
        """What the screencopy lock cost the bot's own looks, from its count."""
        if self.lock_waits is None:
            return ""
        try:
            counts = self.lock_waits()
        except Exception:
            return ""
        others = [row[:3] for name, row in counts.items()
                  if name != "hivemind-liveview"]
        live = counts.get("hivemind-liveview")
        captures = sum(n for n, _, _ in others)
        if not captures:
            return ""
        waited = sum(w for _, w, _ in others)
        most = max(m for _, _, m in others)
        line = (f"the bot's own {captures} captures waited "
                f"{1000 * waited / captures:.1f} ms on average for the "
                f"capture lock, {1000 * most:.0f} ms at most")
        if live and live[0]:
            line += f" (this view's: {1000 * live[1] / live[0]:.1f} ms)"
        return line

    def __enter__(self): return self.start()
    def __exit__(self, *exc): self.stop()

