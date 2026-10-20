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
