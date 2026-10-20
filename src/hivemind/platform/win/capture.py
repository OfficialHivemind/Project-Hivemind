"""Frames of the Roblox window on Windows (platform/api Capture).

PRIMARY: windows-capture, Windows Graphics Capture of the game's WINDOW
[verified: PyPI windows-capture; `window_hwnd=` in its Python API]. WGC
captures the window's own content even when something covers it [verified:
the plan, section 3], so the bot's GUI or a toast over the game is never
read as game pixels. FALLBACK: dxcam (DXGI duplication of the monitor), for
a machine where WGC will not start (old Windows 10, a remote session); it
copies the screen, so anything on top of the game gets in.

Same contract as wl/screencopy.ScreenCopy: (h, w, 4) uint8 BGRA in client
pixels, `region` = (x, y, w, h) in those pixels, CaptureFailed /
CaptureTimeout from platform/api, one capture at a time under an RLock with
the same per-thread wait accounting (lock_waits). Both libraries are
imported lazily: a missing one is a CaptureFailed that names the pip
package, never an ImportError at import.

WGC IS CALLBACK-DRIVEN: frames arrive on its thread and the newest is kept.
It sends nothing while the window does not change, so the newest frame of
a static scene may be old -- the same picture, which is what a caller wants
[assumed: WGC delivers no frame for an unchanged window]. A minimized
window gives no frames at all (the window guard pauses for that, #27).
"""
from __future__ import annotations

import contextlib
import ctypes
import importlib
import threading
import time
from typing import Callable

import numpy as np

from ..api import CaptureFailed, CaptureTimeout
from . import _user32 as w

CAPTURE_TIMEOUT_S = 5.0
BACKENDS = ("wgc", "dxcam")
PACKAGES = {"wgc": "windows-capture", "dxcam": "dxcam"}
MODULES = {"wgc": "windows_capture", "dxcam": "dxcam"}


def _module(backend: str):
    try:
        return importlib.import_module(MODULES[backend])
    except ImportError as exc:
        raise CaptureFailed(f"{PACKAGES[backend]} is not installed "
                            f"(pip install {PACKAGES[backend]}): {exc}") from exc


class WinCapture:
    def __init__(self, window: Callable[[], int | None], *, backends=BACKENDS,
                 user32=None, dwmapi=None):
        if user32 is None:
            user32 = w.dll("user32")
            w.dpi_aware(user32)            # physical pixels, as the capture is
        self._window, self._u, self._dwm = window, user32, dwmapi
        self._lock = threading.RLock()     # one capture at a time (see ScreenCopy)
        self._waits: dict[str, list] = {}
        self._new = threading.Condition()
        self._frame = None                 # WGC: the newest full-window frame
        self._closed: str | None = None
        self._control = self._cam = None
        failures = []
        for name in backends:
            try:
                getattr(self, f"_start_{name}")(_module(name))
                self.backend = name
                break
            except Exception as exc:       # the next backend, and say why at the end
                failures.append(f"{PACKAGES[name]}: {exc}")
        else:
            raise CaptureFailed("no capture backend started -- " + "; ".join(failures))

    # ---- backends ----------------------------------------------------------
    def _hwnd(self) -> int:
        hwnd = self._window()
        if not hwnd:
            raise CaptureFailed("the Roblox window was not found")
        return hwnd

    def _start_wgc(self, mod) -> None:
        hwnd = self._hwnd()
        last = None
        # draw_border=False hides the yellow capture border on Windows 11
        # [verified: IsBorderRequired]; where it cannot be changed (Windows 10)
        # it is asked for again with the default [assumed: that is the error].
        for border in (False, None):
            try:
                cap = mod.WindowsCapture(cursor_capture=False, draw_border=border,
                                         window_hwnd=int(hwnd))

                @cap.event
                def on_frame_arrived(frame, capture_control):
                    self._store(frame.frame_buffer)

                @cap.event
                def on_closed():
                    with self._new:
                        self._closed = "the game window's capture closed (window gone?)"
                        self._new.notify_all()

                self._control = cap.start_free_threaded()
                return
            except Exception as exc:
                last = exc
        raise CaptureFailed(f"Windows Graphics Capture would not start: {last}")

    def _start_dxcam(self, mod) -> None:
        # The game on the primary monitor [assumed], whose output is index 0
        # and whose origin is the virtual screen's (0, 0).
        self._cam = mod.create(output_idx=0, output_color="BGRA")
        if self._cam is None:
            raise CaptureFailed("dxcam.create returned nothing")

    def _store(self, buffer) -> None:
        # The buffer belongs to the library's frame [assumed: valid only
        # inside the callback], so it is copied. ponytail: one 8 MB copy per
        # arrived frame; throttle with minimum_update_interval if it shows.
        frame = np.array(buffer, dtype=np.uint8, copy=True)
        with self._new:
            self._frame = frame
            self._new.notify_all()

    # ---- the window's client area ------------------------------------------
    def _client_in_window(self, hwnd) -> tuple[int, int, int, int]:
        """x, y, w, h of the client area inside a WGC window frame, which spans
        the window's visible bounds, DWMWA_EXTENDED_FRAME_BOUNDS [assumed],
        title bar included when the game is windowed."""
        ox, oy = w.client_origin(self._u, hwnd)
        cw, ch = w.client_size(self._u, hwnd)
        left = top = None
        try:
            dwm = self._dwm or w.dll("dwmapi")
            rc = w.RECT()
            if dwm.DwmGetWindowAttribute(hwnd, w.DWMWA_EXTENDED_FRAME_BOUNDS,
                                         ctypes.byref(rc), ctypes.sizeof(rc)) == 0:
                left, top = rc.left, rc.top
        except OSError:
            pass
        if left is None:                   # unknown frame: assume borderless
            return 0, 0, cw, ch
        return max(0, ox - left), max(0, oy - top), cw, ch

    # ---- capture -----------------------------------------------------------
    def capture(self, region: tuple[int, int, int, int] | None = None,
                timeout: float = CAPTURE_TIMEOUT_S) -> np.ndarray:
        """One frame, (h, w, 4) BGRA, of the client area or `region` of it.
        Raises CaptureFailed, CaptureTimeout when nothing came in `timeout`."""
        asked = time.monotonic()
        with self._lock:
            waited = time.monotonic() - asked
            name = threading.current_thread().name
            row = self._waits.get(name)
            if row is None and len(self._waits) < 32:
                row = self._waits[name] = [0, 0.0, 0.0]
            if row is not None:
                row[0] += 1
                row[1] += waited
                row[2] = max(row[2], waited)
            try:
                if self.backend == "wgc":
                    return self._grab_wgc(region, timeout)
                return self._grab_dxcam(region, timeout)
            except CaptureFailed:
                raise
            except Exception as exc:       # a ctypes/library error is a failed frame
                raise CaptureFailed(f"capture failed: {exc}") from exc

    def lock_waits(self) -> dict[str, tuple[int, float, float]]:
        return {name: tuple(row) for name, row in list(self._waits.items())}

    # A CLOSED CAPTURE IS RE-AIMED, NOT FATAL (2026-10-19, the first
    # Windows launch): the capture attached to the window Roblox showed
    # first, that window closed ~60 s later and the start died with "the game
    # window's capture closed (window gone?)". When `window()` names a window
    # again, WGC is started on it afresh, up to REATTACH_TRIES times a run.
    REATTACH_TRIES = 5

    def _reattach(self) -> bool:
        if getattr(self, "_reattached", 0) >= self.REATTACH_TRIES or not self._window():
            return False
        self._reattached = getattr(self, "_reattached", 0) + 1
        with contextlib.suppress(Exception):
            if self._control is not None:
                self._control.stop()
        with self._new:
            self._closed, self._frame = None, None
        try:
            self._start_wgc(_module("wgc"))
        except Exception:
            return False
        return True

    def _grab_wgc(self, region, timeout: float) -> np.ndarray:
        if self._closed is not None:
            self._reattach()
        deadline = time.monotonic() + timeout
        with self._new:
            while self._frame is None and self._closed is None:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise CaptureTimeout(f"no frame from Windows Graphics Capture "
                                         f"within {timeout:.1f}s")
                self._new.wait(left)
            if self._closed is not None:
                raise CaptureFailed(self._closed)
            full = self._frame             # replaced, never written: safe to slice
        cx, cy, cw, ch = self._client_in_window(self._hwnd())
        x, y, rw, rh = region if region else (0, 0, cw, ch)
        return full[cy + y:cy + y + rh, cx + x:cx + x + rw, :4].copy()

    def _grab_dxcam(self, region, timeout: float) -> np.ndarray:
        hwnd = self._hwnd()
        ox, oy = w.client_origin(self._u, hwnd)
        if region:
            x, y, rw, rh = region
        else:
            x, y, (rw, rh) = 0, 0, w.client_size(self._u, hwnd)
        box = (ox + x, oy + y, ox + x + rw, oy + y + rh)      # left, top, right, bottom
        deadline = time.monotonic() + timeout
        while True:
            # new_frame_only=False: the newest frame even if unchanged
            # [verified: dxcam 0.3.0 README], so a static scene is no timeout.
            img = self._cam.grab(region=box, new_frame_only=False)
            if img is not None:
                return np.ascontiguousarray(img[:, :, :4])
            if time.monotonic() >= deadline:
                raise CaptureTimeout(f"no frame from dxcam within {timeout:.1f}s")
            time.sleep(0.005)

    def close(self) -> None:
        """Stop the capture. Never touches the game."""
        if self._control is not None:
            with contextlib.suppress(Exception):
                self._control.stop()
            self._control = None
        if self._cam is not None:
            with contextlib.suppress(Exception):
                self._cam.release()
            self._cam = None
