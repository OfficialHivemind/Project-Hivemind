"""Capture must be safe to call from several threads at once.

MEASURED, and it aborted the process rather than raising:

    wl_display_dispatch_queue: Assertion `ret == -1 || ret > 0' failed

That happened the first time three threads wanted frames concurrently -- the
live-view streamer at 20 Hz, the clicker's HUD gate, and the mob watch looking
during every held key. `capture()` installs listeners and pumps the Wayland
queue, and two of those interleaved corrupt each other. An abort cannot be
caught, so the only defence is not letting it happen.

These tests use a stand-in rather than a real compositor: the thing being
tested is the serialisation, not the Wayland protocol.
"""
from __future__ import annotations

import threading
import time

import pytest

from hivemind.platform.wl.screencopy import ScreenCopy


class FakeCapture(ScreenCopy):
    """Bypasses __init__ and records whether two calls ever overlap."""

    def __init__(self):
        self._lock = threading.RLock()
        self._waits = {}           # per-thread lock waits (ScreenCopy.lock_waits)
        self.inside = 0
        self.overlaps = 0
        self.calls = 0

    def _capture_locked(self, region, timeout):
        self.calls += 1
        self.inside += 1
        if self.inside > 1:
            self.overlaps += 1
        time.sleep(0.002)          # the real one takes ~13 ms
        self.inside -= 1
        return "frame"


def test_concurrent_captures_never_overlap():
    cap = FakeCapture()
    threads = [threading.Thread(target=lambda: [cap.capture() for _ in range(20)])
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert cap.calls == 80
    assert sum(n for n, _, _ in cap.lock_waits().values()) == 80
    assert cap.overlaps == 0, (
        f"{cap.overlaps} overlapping captures — libwayland aborts the whole "
        f"process when this happens, and an abort cannot be caught")


def test_the_lock_is_reentrant():
    """A caller already holding it must not deadlock itself."""
    cap = FakeCapture()
    with cap._lock:
        assert cap.capture() == "frame"


# --- the output race at startup -------------------------------------------
# MEASURED 2026-09-22: attempts 143 and 168 each died two seconds in with
# "compositor advertised no wl_output" -- a nested Hyprland started moments
# earlier had not created its output yet. Each death costs a relaunch and a
# rejoin, about 45 s, for a race that resolves in a few hundred milliseconds.

class _Conn:
    """A connection whose output appears after N roundtrips."""

    def __init__(self, appears_after: int = 2):
        self.outputs: list[object] = []
        self.globals = {"zwlr_screencopy_manager_v1": object(),
                        "wl_shm": object()}
        self._left = appears_after
        self.roundtrips = 0

    def require(self, *interfaces):
        pass

    def roundtrip(self):
        self.roundtrips += 1
        self._left -= 1
        if self._left <= 0 and not self.outputs:
            self.outputs.append(object())


def test_it_waits_for_an_output_that_arrives_late(monkeypatch):
    from hivemind.platform.wl import screencopy as sc
    monkeypatch.setattr(sc, "OUTPUT_POLL_SECONDS", 0.001)
    conn = _Conn(appears_after=3)

    sc.ScreenCopy(conn)          # must not raise

    assert conn.roundtrips >= 3, "it gave up without dispatching the queue"


def test_it_still_gives_up_and_says_how_long_it_waited(monkeypatch):
    """A wait that never ends is worse than a clean failure the watchdog
    can restart from."""
    from hivemind.platform.wl import screencopy as sc
    monkeypatch.setattr(sc, "OUTPUT_POLL_SECONDS", 0.001)
    monkeypatch.setattr(sc, "OUTPUT_WAIT_SECONDS", 0.02)
    conn = _Conn(appears_after=10_000)

    with pytest.raises(sc.CaptureFailed) as caught:
        sc.ScreenCopy(conn)

    assert "of waiting" in str(caught.value), str(caught.value)


def test_an_output_already_there_costs_no_wait(monkeypatch):
    from hivemind.platform.wl import screencopy as sc
    conn = _Conn(appears_after=0)
    conn.outputs.append(object())

    sc.ScreenCopy(conn)

    assert conn.roundtrips == 0, "it waited for something already present"
