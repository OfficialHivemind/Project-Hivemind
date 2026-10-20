"""RL6 phase 3: win/capture with windows-capture and dxcam faked (runs on
Linux; no real Windows has run it). The contract is ScreenCopy's: BGRA
client pixels, regions, CaptureFailed/CaptureTimeout, never a hang, never
an ImportError for a missing library."""
from __future__ import annotations

import sys
import threading
import types

import numpy as np
import pytest

from hivemind.platform import api
from hivemind.platform.win import capture as wc

HWND = 0x77


class FakeUser32:
    origin = (108, 81)                      # client top-left on screen
    size = (1920, 1080)

    def ClientToScreen(self, hwnd, ref):
        ref._obj.x += self.origin[0]
        ref._obj.y += self.origin[1]
        return 1

    def GetClientRect(self, hwnd, ref):
        ref._obj.right, ref._obj.bottom = self.size
        return 1


class FakeDwm:
    frame = (100, 50)                       # window's extended frame left/top

    def DwmGetWindowAttribute(self, hwnd, attr, ref, size):
        assert attr == 9
        ref._obj.left, ref._obj.top = self.frame
        return 0


def window_frame():
    """A windowed game: 8 px border, 31 px title bar, then the client."""
    img = np.zeros((31 + 1080 + 8, 8 + 1920 + 8, 4), np.uint8)
    img[31:31 + 1080, 8:8 + 1920] = 200
    img[31 + 10, 8 + 20] = (1, 2, 3, 255)   # client pixel (20, 10)
    return img


def fake_wgc(monkeypatch, *, frames=True, fail_border=False):
    made = {}

    class Control:
        stopped = False

        def stop(self):
            Control.stopped = True

    class WindowsCapture:
        def __init__(self, **kw):
            if fail_border and kw.get("draw_border") is False:
                raise RuntimeError("border toggle unsupported")
            made["kw"] = kw
            self.handlers = {}

        def event(self, fn):
            self.handlers[fn.__name__] = fn
            return fn

        def start_free_threaded(self):
            made["cap"] = self
            if frames:
                frame = types.SimpleNamespace(frame_buffer=window_frame())
                self.handlers["on_frame_arrived"](frame, None)
            return Control()

    mod = types.ModuleType("windows_capture")
    mod.WindowsCapture = WindowsCapture
    monkeypatch.setitem(sys.modules, "windows_capture", mod)
    return made, Control


def make(**kw):
    return wc.WinCapture(lambda: HWND, user32=FakeUser32(), dwmapi=FakeDwm(), **kw)


def test_wgc_window_capture_crops_to_the_client_area(monkeypatch):
    made, _ = fake_wgc(monkeypatch)
    cap = make()
    assert cap.backend == "wgc"
    assert made["kw"] == {"cursor_capture": False, "draw_border": False, "window_hwnd": HWND}
    full = cap.capture()
    assert full.shape == (1080, 1920, 4) and full.dtype == np.uint8
    assert (full == 200).all(axis=2).sum() == 1920 * 1080 - 1
    part = cap.capture((20, 10, 5, 4))
    assert part.shape == (4, 5, 4) and tuple(part[0, 0]) == (1, 2, 3, 255)


def test_a_returned_frame_is_a_copy(monkeypatch):
    fake_wgc(monkeypatch)
    cap = make()
    a = cap.capture((0, 0, 4, 4))
    a[:] = 0
    assert (cap.capture((0, 0, 4, 4)) == 200).all()


def test_no_frame_is_a_timeout_not_a_hang(monkeypatch):
    fake_wgc(monkeypatch, frames=False)
    cap = make()
    with pytest.raises(api.CaptureTimeout):
        cap.capture(timeout=0.05)
    assert issubclass(api.CaptureTimeout, api.CaptureFailed)


def test_a_closed_window_is_reattached_then_fails_when_gone(monkeypatch):
    # 2026-10-19: Roblox's first window closed ~60 s into the owner's first
    # Windows launch; the capture now starts again on whatever window() names.
    made, _ = fake_wgc(monkeypatch, frames=False)
    window = {"hwnd": HWND}
    cap = wc.WinCapture(lambda: window["hwnd"], user32=FakeUser32(), dwmapi=FakeDwm())
    first = made["cap"]
    first.handlers["on_closed"]()
    frame = types.SimpleNamespace(frame_buffer=window_frame())
    threading.Timer(0.05, lambda: made["cap"].handlers["on_frame_arrived"](frame, None)).start()
    assert cap.capture((20, 10, 1, 1), timeout=2)[0, 0, 0] == 1
    assert made["cap"] is not first                     # a new capture, on the window found now
    window["hwnd"] = None                               # and with no window, it says so
    made["cap"].handlers["on_closed"]()
    with pytest.raises(api.CaptureFailed, match="closed"):
        cap.capture(timeout=1)


def test_a_frame_arriving_later_wakes_the_wait(monkeypatch):
    made, _ = fake_wgc(monkeypatch, frames=False)
    cap = make()
    frame = types.SimpleNamespace(frame_buffer=window_frame())
    threading.Timer(0.05, made["cap"].handlers["on_frame_arrived"], (frame, None)).start()
    assert cap.capture((20, 10, 1, 1), timeout=2)[0, 0, 0] == 1


def test_border_toggle_unsupported_retries_with_the_default(monkeypatch):
    made, _ = fake_wgc(monkeypatch, fail_border=True)
    assert make().backend == "wgc" and made["kw"]["draw_border"] is None


def test_close_stops_the_capture(monkeypatch):
    _, control = fake_wgc(monkeypatch)
    cap = make()
    cap.close()
    cap.close()                             # twice is fine
    assert control.stopped


def test_lock_waits_count_per_thread(monkeypatch):
    fake_wgc(monkeypatch)
    cap = make()
    cap.capture((0, 0, 1, 1))
    cap.capture((0, 0, 1, 1))
    assert cap.lock_waits()[threading.current_thread().name][0] == 2


def fake_dxcam(monkeypatch, *, empty=False):
    asked = []

    class Camera:
        released = False

        def grab(self, region=None, new_frame_only=True):
            asked.append((region, new_frame_only))
            if empty:
                return None
            left, top, right, bottom = region
            return np.full((bottom - top, right - left, 4), 7, np.uint8)

        def release(self):
            Camera.released = True

    mod = types.ModuleType("dxcam")
    mod.create = lambda output_idx=0, output_color="BGRA": Camera()
    monkeypatch.setitem(sys.modules, "dxcam", mod)
    return asked


def test_missing_wgc_falls_back_to_dxcam_in_screen_coordinates(monkeypatch):
    monkeypatch.setitem(sys.modules, "windows_capture", None)    # ImportError
    asked = fake_dxcam(monkeypatch)
    cap = make()
    assert cap.backend == "dxcam"
    img = cap.capture((20, 10, 5, 4))
    assert img.shape == (4, 5, 4)
    assert asked[-1] == ((128, 91, 133, 95), False)
    assert cap.capture().shape == (1080, 1920, 4)


def test_dxcam_with_nothing_times_out(monkeypatch):
    fake_dxcam(monkeypatch, empty=True)
    cap = make(backends=("dxcam",))
    with pytest.raises(api.CaptureTimeout):
        cap.capture(timeout=0.03)


def test_no_library_is_a_clear_capture_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "windows_capture", None)
    monkeypatch.setitem(sys.modules, "dxcam", None)
    with pytest.raises(api.CaptureFailed) as err:
        make()
    assert "pip install windows-capture" in str(err.value)
    assert "pip install dxcam" in str(err.value)


def test_no_game_window_fails_wgc(monkeypatch):
    fake_wgc(monkeypatch)
    monkeypatch.setitem(sys.modules, "dxcam", None)
    with pytest.raises(api.CaptureFailed, match="window was not found"):
        wc.WinCapture(lambda: None, user32=FakeUser32(), dwmapi=FakeDwm())
