import io
import threading
import time

from hivemind.telemetry import stallwatch


def test_a_stuck_main_thread_is_reported_with_stacks():
    out = io.StringIO()
    stallwatch.start(out=out, stall_s=0.3, sample_s=0.05)
    gate = threading.Event()
    gate.wait(1.0)          # the main thread sits on one line
    time.sleep(0.1)
    text = out.getvalue()
    assert "stall watch: the main thread has been at" in text
    assert "test_stallwatch.py" in text


def test_a_silent_main_loop_calls_on_stall_once_and_a_pause_does_not():
    out = io.StringIO()
    stallwatch.start(out=out, stall_s=60.0, sample_s=0.05)
    calls, held = [], {"on": True}
    try:
        stallwatch.arm(calls.append, held=lambda: held["on"], stall_s=0.3)
        time.sleep(0.6)                # paused: the silence does not count
        assert calls == []
        held["on"] = False
        for _ in range(8):             # beating: no stall
            stallwatch.beat()
            time.sleep(0.05)
        assert calls == []
        threading.Thread(target=stallwatch.beat).start()   # not the main thread's
        time.sleep(0.8)                # silent: told once, not every sample
        assert len(calls) == 1 and calls[0] >= 0.3
    finally:
        stallwatch.disarm()
