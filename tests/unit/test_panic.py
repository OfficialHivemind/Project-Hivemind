"""The panic hotkey.

This is the only safety layer that survives the process being stuck, so the
tests focus on it degrading honestly: when it cannot watch the keyboard it must
SAY so rather than appear to work, because a panic button you believe in and
that does nothing is worse than none at all.
"""
import os

import pytest

from hivemind.platform.panic import PanicWatcher, key_code


def test_known_key_names_resolve():
    pytest.importorskip("evdev")
    assert key_code("F12") is not None
    assert key_code("f12") == key_code("F12")


def test_unknown_key_name_is_reported_not_guessed():
    pytest.importorskip("evdev")
    w = PanicWatcher(on_panic=lambda: None, key="NOT_A_KEY")
    assert w.available is False
    assert "unknown key" in w.reason


def test_no_readable_devices_reports_unavailable():
    fired = []
    w = PanicWatcher(on_panic=lambda: fired.append(1)).start(paths=[])
    assert w.available is False
    assert w.reason
    w.stop()


@pytest.mark.skipif(os.name == "nt", reason="evdev is Linux (win/panic has its own tests)")
def test_permission_failure_explains_the_fix():
    """The common real-world case: not in the 'input' group."""
    w = PanicWatcher(on_panic=lambda: None)
    w.find_devices(paths=["/dev/input/definitely-not-a-device"])
    assert "input" in w.reason


def test_trigger_calls_the_callback():
    fired = []
    PanicWatcher(on_panic=lambda: fired.append(1)).trigger()
    assert fired == [1]


def test_a_failing_callback_does_not_kill_the_watcher():
    """The last line of defence must survive its own handler raising."""
    def boom():
        raise RuntimeError("handler exploded")
    w = PanicWatcher(on_panic=boom)
    w.trigger()
    w.trigger()
    assert w.fired == 2


def test_stop_is_safe_when_never_started():
    PanicWatcher(on_panic=lambda: None).stop()


def test_finds_a_real_keyboard_on_this_machine():
    """Not a unit test so much as a check that the panic key would work here."""
    pytest.importorskip("evdev")
    import evdev
    if not evdev.list_devices():
        pytest.skip("no input devices visible")
    w = PanicWatcher(on_panic=lambda: None)
    devices = w.find_devices()
    for d in devices:
        d.close()
    if not devices:
        pytest.skip(f"panic key unavailable here: {w.reason}")
    assert devices
