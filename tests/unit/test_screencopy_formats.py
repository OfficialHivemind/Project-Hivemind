"""Frames come out BGRA whatever byte order the compositor's shm buffer has.

MEASURED 2026-10-19 (RL1b, docs/pending/universal-linux.md): a wlroots 0.20
compositor (cage and labwc, headless, GLES2) offers only shm XBGR8888, where
Hyprland offers XRGB8888. Before the swap the bot refused every frame there
("compositor offered no supported format").
"""
from __future__ import annotations

import threading

import pytest

from hivemind.platform.wl import screencopy as sc


class _Frame:
    def __init__(self, cap, fmt):
        self.dispatcher, self.cap, self.fmt = {}, cap, fmt

    def copy(self, _buf):     # one colour, R=30 G=20 B=10, in the offered byte order
        px = bytes([10, 20, 30, 255]) if self.fmt in sc._SWAPPED else bytes([30, 20, 10, 255])
        self.cap._pool.mem[:16] = px * 4

    def destroy(self):
        pass


class _Obj:
    def __getattr__(self, _):
        return lambda *a, **k: _Obj()


class _Cap(sc.ScreenCopy):
    def __init__(self, fmt):
        self._lock, self._waits, self._pool, self._shm = threading.RLock(), {}, None, _Obj()
        self.fmt = fmt
        self._mgr = self
        self._output = None
        self._conn = _Obj()

    def capture_output(self, _overlay, _output):
        self.frame = _Frame(self, self.fmt)
        return self.frame

    def _wait(self, state, timeout):      # the compositor's events, in order
        d = self.frame.dispatcher
        d["buffer"](self.frame, self.fmt, 4, 1, 16)
        d["buffer_done"](self.frame)
        d["ready"](self.frame)


@pytest.mark.parametrize("fmt", [sc.SHM_XRGB8888, sc.SHM_ARGB8888,
                                 sc.SHM_XBGR8888, sc.SHM_ABGR8888])
def test_every_offered_format_comes_out_bgra(fmt):
    img = _Cap(fmt).capture()
    assert img.shape == (1, 4, 4)
    assert tuple(img[0, 0]) == (30, 20, 10, 255)      # B, G, R, A
