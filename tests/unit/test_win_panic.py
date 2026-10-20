"""RL6 phase 3: the Windows panic key on a fake GetAsyncKeyState. The same
rules as tests/unit/test_panic.py: it degrades honestly and survives its
own callback."""
from __future__ import annotations

import threading

from hivemind.platform.win.panic import WinPanicWatcher, key_code


class Keyboard:
    """GetAsyncKeyState over a script of states, one per poll."""

    def __init__(self, states):
        self.states, self.asked, self.done = list(states), [], threading.Event()

    def GetAsyncKeyState(self, vk):
        self.asked.append(vk)
        if not self.states:
            self.done.set()
            return 0
        return self.states.pop(0)


def run(states, on_panic=lambda: None):
    kb = Keyboard(states)
    watch = WinPanicWatcher(on_panic=on_panic, poll_s=0.001, user32=kb).start()
    assert kb.done.wait(2)
    watch.stop()
    return watch, kb


def test_key_names():
    assert key_code("F12") == 0x7B and key_code("f1") == 0x70 and key_code("F24") == 0x87
    assert key_code("NOT_A_KEY") is None


def test_unknown_key_is_reported_not_guessed():
    w = WinPanicWatcher(on_panic=lambda: None, key="NOT_A_KEY").start()
    assert w.available is False and "unknown key" in w.reason


def test_fires_once_per_press_on_the_down_edge():
    fired = []
    # held across three polls, released, pressed again; -32768 is bit 15 as a SHORT
    w, kb = run([0, -32768, -32767, -32768, 0, 0, -32768, 0], lambda: fired.append(1))
    assert fired == [1, 1] and w.fired == 2
    assert set(kb.asked) == {0x7B}


def test_the_low_pressed_since_bit_alone_is_not_a_press():
    fired = []
    run([1, 1, 0], lambda: fired.append(1))
    assert fired == []


def test_a_failing_callback_does_not_kill_the_watcher():
    def boom():
        raise RuntimeError("handler exploded")
    w, _ = run([-32768, 0, -32768, 0], boom)
    assert w.fired == 2


def test_no_user32_says_so(monkeypatch):
    # On Windows user32 is really there (MEASURED 2026-10-21), so take it away.
    from hivemind.platform.win import panic as win_panic

    def no_dll(name):
        raise OSError(f"no {name}")
    monkeypatch.setattr(win_panic.w, "dll", no_dll)
    w = WinPanicWatcher(on_panic=lambda: None).start()      # Linux: no WinDLL
    assert w.available is False and "cannot read the keyboard" in w.reason


def test_a_broken_poll_reports_unavailable():
    class Broken:
        def GetAsyncKeyState(self, vk):
            raise OSError("desktop gone")
    w = WinPanicWatcher(on_panic=lambda: None, poll_s=0.001, user32=Broken()).start()
    for _ in range(200):
        if not w.available:
            break
        threading.Event().wait(0.005)
    assert w.available is False and "desktop gone" in w.reason


def test_stop_is_safe_when_never_started():
    WinPanicWatcher(on_panic=lambda: None).stop()
