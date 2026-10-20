"""Frame capture over zwlr_screencopy_unstable_v1.

One wl_shm pool, allocated once and reused for every frame. This matters: the
naive implementation allocates a full-resolution buffer per frame, which is
about a gigabyte per second of pointless copying at 30fps. `grim` cannot avoid
it because it is a new process each time.

Region capture is the other big win -- grabbing the 400x200 HUD instead of the
whole 1920x1080 screen is ~35x less data, and the compositor copies less too.
"""
from __future__ import annotations

import contextlib
import mmap
import os
import select
import threading
import time
from dataclasses import dataclass

import numpy as np

from ..api import CaptureFailed, CaptureTimeout  # noqa: F401  (re-exported: RL6)
from .connection import WlConnection

# How long one frame may take before we give up. Generous next to a real
# capture (single-digit ms) and short next to the walker's own 30s budget, so
# a wedged compositor surfaces as an error the caller can act on rather than
# as a hang that outlives every timeout above it.
CAPTURE_TIMEOUT_S = 5.0

# wl_shm.format values we can consume directly as BGRA/BGRX byte order.
SHM_ARGB8888, SHM_XRGB8888 = 0, 1
# ...and the two in RGBA byte order, swapped to BGRA after the copy. MEASURED
# 2026-10-19 (RL1b, docs/pending/universal-linux.md): a wlroots 0.20
# compositor (cage, headless, GLES2 on a Mesa driver) offers ONLY shm XBGR8888 --
# Hyprland offers XRGB8888, so on Hyprland nothing here changes.
SHM_ABGR8888, SHM_XBGR8888 = 0x34324241, 0x34324258
_SWAPPED = {SHM_ABGR8888, SHM_XBGR8888}
_SUPPORTED = {SHM_ARGB8888, SHM_XRGB8888} | _SWAPPED


# HOW LONG TO WAIT FOR THE COMPOSITOR TO ADVERTISE AN OUTPUT. A nested
# Hyprland launched moments ago needs a beat; the race resolves in a few
# hundred milliseconds, and the alternative is losing the whole run to a
# relaunch and rejoin. See ScreenCopy.__init__.
OUTPUT_WAIT_SECONDS = 5.0
OUTPUT_POLL_SECONDS = 0.2


@dataclass
class _Pool:
    fd: int
    size: int
    pool: object
    mem: mmap.mmap


class ScreenCopy:
    """Capture full outputs or regions into numpy arrays."""

    def __init__(self, conn: WlConnection, output_index: int = 0):
        conn.require("zwlr_screencopy_manager_v1", "wl_shm")
        # WAIT FOR THE OUTPUT INSTEAD OF GIVING UP ON THE FIRST LOOK.
        #
        # `outputs` is filled by registry events, and a nested Hyprland
        # started moments ago may not have created its output yet. Failing
        # here ends the whole run: MEASURED 2026-09-22, attempts 143 and 168
        # both died two seconds in with "compositor advertised no wl_output",
        # and each death costs a full relaunch and rejoin -- about 45 s -- for
        # a race that resolves in a few hundred milliseconds.
        #
        # A roundtrip per try rather than a bare sleep, because the events
        # only arrive when the queue is dispatched.
        waited = 0.0
        while not conn.outputs and waited < OUTPUT_WAIT_SECONDS:
            time.sleep(OUTPUT_POLL_SECONDS)
            waited += OUTPUT_POLL_SECONDS
            try:
                conn.roundtrip()
            except Exception:
                break
        if not conn.outputs:
            raise CaptureFailed(
                f"compositor advertised no wl_output after "
                f"{waited:.1f}s of waiting")
        self._conn = conn
        self._mgr = conn.globals["zwlr_screencopy_manager_v1"]
        self._shm = conn.globals["wl_shm"]
        self._output = conn.outputs[output_index]
        self._pool: _Pool | None = None
        # ONE CAPTURE AT A TIME, ALWAYS.
        #
        # MEASURED THE HARD WAY, 2026-09-20: libwayland aborted the whole
        # process with
        #
        #     wl_display_dispatch_queue: Assertion `ret == -1 || ret > 0' failed
        #
        # the first time three threads wanted frames at once -- the live-view
        # streamer at 20 Hz, the tool clicker checking the HUD before each
        # click, and the new mob watch looking 10 times a second during every
        # held key. A wl_display and its queue are not safe to dispatch from
        # several threads, and `capture()` dispatches: it creates a frame
        # object, installs listeners, flushes and pumps the queue until the
        # frame lands. Two of those interleaved corrupt each other's state,
        # and the failure is an abort rather than an exception, so nothing
        # upstream can catch it.
        #
        # The "compositor offered no supported format" errors that had been
        # written off as transient were the mild version of the same race.
        #
        # A lock here rather than in each caller, because it has to hold for
        # every caller including ones not written yet -- and a capture is
        # ~13 ms, so contention costs latency, never correctness.
        self._lock = threading.RLock()
        self._waits: dict[str, list] = {}

    # ---- shm pool, allocated once and grown only when needed --------------
    def _ensure_pool(self, size: int) -> _Pool:
        if self._pool and self._pool.size >= size:
            return self._pool
        if self._pool:
            self._pool.mem.close()
            os.close(self._pool.fd)
        fd = os.memfd_create("hivemind-frame", os.MFD_CLOEXEC)
        os.ftruncate(fd, size)
        mem = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        self._pool = _Pool(fd, size, self._shm.create_pool(fd, size), mem)
        return self._pool

    # ---- waiting -----------------------------------------------------------
    def _wait(self, state: dict, timeout: float) -> None:
        """Pump the Wayland queue until the frame lands, or give up.

        `display.dispatch(block=True)` is wl_display_dispatch, which sits in
        poll() with no deadline. Instead we poll the display fd ourselves and
        only dispatch once it is readable -- at which point the blocking
        dispatch returns immediately.
        """
        deadline = time.monotonic() + timeout
        poller = select.poll()
        fd = self._conn.display.get_fd()
        poller.register(fd, select.POLLIN)
        while not state["done"]:
            # drain what is already queued before waiting on the socket,
            # otherwise a complete frame can sit unread while we poll
            self._conn.display.dispatch(block=False)
            if state["done"]:
                return
            # FLUSH. dispatch(block=False) is wl_display_dispatch_pending,
            # which does not write to the socket -- and the buffer_done
            # callback we just ran issued a `copy` REQUEST. Without this the
            # request sits in the output buffer, the compositor never hears
            # about it, nothing more arrives, and the poll below waits out the
            # whole deadline. (The old blocking dispatch flushed implicitly,
            # which is why this only appeared once the poll was added.)
            self._conn.flush()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CaptureTimeout(
                    f"no frame from the compositor within {timeout:.1f}s")
            events = poller.poll(remaining * 1000.0)
            if not events:
                continue                      # re-check the deadline and loop
            _, flags = events[0]
            if flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                raise CaptureFailed("the Wayland connection dropped")
            self._conn.display.dispatch(block=True)   # readable: returns at once

    # ---- capture -----------------------------------------------------------
    def capture(self, region: tuple[int, int, int, int] | None = None,
                timeout: float = CAPTURE_TIMEOUT_S) -> np.ndarray:
        """Return one frame as an (h, w, 4) BGRA array.

        Blocks until ready or `timeout` elapses. The deadline is not optional
        politeness: callers hold keys across this call (walk_until holds W and
        captures inside its loop), so a capture that never returns defeats the
        walker's own timeout, defeats AppUI.wait_for's timeout, and -- because
        wl_display_dispatch blocks inside a C call -- cannot even be broken by
        Ctrl-C. A frame that does not arrive has to become an exception.
        """
        asked = time.monotonic()
        with self._lock:
            # HOW LONG EACH THREAD WAITED FOR THE LOCK, counted under it. The
            # live view takes this lock 30 times a second (DESIGN 8eb), and
            # the one way to know it is not starving the bot's own looks is to
            # count what they waited. Bounded: one row per thread name.
            waited = time.monotonic() - asked
            name = threading.current_thread().name
            row = self._waits.get(name)
            if row is None and len(self._waits) < 32:
                row = self._waits[name] = [0, 0.0, 0.0]
            if row is not None:
                row[0] += 1
                row[1] += waited
                row[2] = max(row[2], waited)
            return self._capture_locked(region, timeout)

    def lock_waits(self) -> dict[str, tuple[int, float, float]]:
        """{thread name: (captures, seconds waited for the lock, the most)}.
        Read without the lock, so asking never waits for a capture; a row
        read mid-update is at most one capture out."""
        return {name: tuple(row) for name, row in list(self._waits.items())}

    def _capture_locked(self, region, timeout: float) -> np.ndarray:
        if region:
            x, y, w, h = region
            frame = self._mgr.capture_output_region(0, self._output, x, y, w, h)
        else:
            frame = self._mgr.capture_output(0, self._output)

        state: dict = {"done": False, "failed": False, "spec": None,
                       "buffer": None, "error": None}

        def on_buffer(_f, fmt, width, height, stride):
            if state["spec"] is None and fmt in _SUPPORTED:
                state["spec"] = (fmt, width, height, stride)

        def on_buffer_done(_f):
            # EVERYTHING in here must be guarded. pywayland's dispatcher
            # (pywayland/dispatcher.py) catches every exception, prints a
            # traceback and returns 0 -- so an OSError from memfd_create,
            # ftruncate or mmap would never reach capture(). Without this
            # guard the copy request is never issued, the compositor has
            # nothing further to send, and the wait blocks forever on a
            # perfectly live connection.
            try:
                spec = state["spec"]
                if spec is None:
                    raise CaptureFailed("compositor offered no supported format")
                fmt, width, height, stride = spec
                pool = self._ensure_pool(stride * height)
                buf = pool.pool.create_buffer(0, width, height, stride, fmt)
                state["buffer"] = buf
                _f.copy(buf)
            except Exception as exc:
                state["error"] = exc
                state["failed"] = True
                state["done"] = True

        def on_ready(_f, *_):  state["done"] = True
        def on_failed(_f):     state["failed"] = True; state["done"] = True

        frame.dispatcher["buffer"] = on_buffer
        frame.dispatcher["buffer_done"] = on_buffer_done
        frame.dispatcher["ready"] = on_ready
        frame.dispatcher["failed"] = on_failed

        self._conn.flush()
        try:
            self._wait(state, timeout)
        except BaseException:
            # release the frame object on the way out, including on timeout,
            # so a slow compositor does not leak one per failed capture
            if state["buffer"] is not None:
                with contextlib.suppress(Exception):
                    state["buffer"].destroy()
            with contextlib.suppress(Exception):
                frame.destroy()
            raise

        if state["error"] is not None:
            raise CaptureFailed(
                f"capture failed: {state['error']}") from state["error"]
        if state["failed"] or state["spec"] is None:
            raise CaptureFailed("compositor refused the capture")

        fmt, width, height, stride = state["spec"]
        pool = self._pool
        arr = np.frombuffer(pool.mem, dtype=np.uint8, count=stride * height)
        # copy: the pool is reused, so the caller must not alias it (the
        # channel swap's fancy index copies too)
        img = arr.reshape(height, stride // 4, 4)[:, :width, :]
        img = img[..., [2, 1, 0, 3]] if fmt in _SWAPPED else img.copy()

        if state["buffer"] is not None:
            state["buffer"].destroy()
        frame.destroy()
        return img

    def close(self) -> None:
        if self._pool:
            self._pool.mem.close()
            os.close(self._pool.fd)
            self._pool = None
