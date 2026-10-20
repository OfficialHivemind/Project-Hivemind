"""The capture handshake is retried, not trusted (GAPS #7; the camera diag
died on it at 22:20 on 2026-09-22 with 'invalid output')."""
from __future__ import annotations

import pytest

from hivemind.act import bootstrap
from hivemind.platform.wl.screencopy import CaptureFailed


class Conn:
    def __init__(self): self.closed = False

    def close(self): self.closed = True


def test_a_failing_first_capture_is_retried_with_a_fresh_connection():
    conns = []
    tries = {"n": 0}

    def make_conn():
        c = Conn(); conns.append(c); return c

    class Cap:
        def __init__(self, ok): self.ok = ok

        def capture(self):
            if not self.ok:
                raise RuntimeError("Failed with error: 71")
            return object()

    def make_capture(conn):
        tries["n"] += 1
        return Cap(ok=tries["n"] >= 3)

    said = []
    conn, cap = bootstrap.connect_capture(make_conn, make_capture, sleep=lambda s: None, say=said.append)
    assert tries["n"] == 3
    assert conns[0].closed and conns[1].closed and not conns[2].closed
    assert any("reconnecting, try 1 of" in t for t in said) and any("succeeded on try 3" in t for t in said)


def test_a_capture_that_cannot_be_built_is_retried_too():
    n = {"k": 0}

    def make_capture(conn):
        n["k"] += 1
        if n["k"] == 1:
            raise CaptureFailed("compositor advertised no wl_output")

        class Cap:
            def capture(self): return object()
        return Cap()

    conn, cap = bootstrap.connect_capture(Conn, make_capture, sleep=lambda s: None, say=lambda t: None)
    assert n["k"] == 2


def test_every_try_failing_raises_the_last_error():
    class Cap:
        def capture(self): raise RuntimeError("Failed with error: 71")
    with pytest.raises(RuntimeError, match="71"):
        bootstrap.connect_capture(Conn, lambda c: Cap(), tries=3, sleep=lambda s: None, say=lambda t: None)


def test_a_frame_of_none_counts_as_a_failure():
    calls = {"n": 0}

    class Cap:
        def capture(self):
            calls["n"] += 1
            return None if calls["n"] == 1 else object()
    bootstrap.connect_capture(Conn, lambda c: Cap(), sleep=lambda s: None, say=lambda t: None)
    assert calls["n"] == 2
