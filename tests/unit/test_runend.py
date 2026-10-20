import importlib.util
import os
import socket
from pathlib import Path

import hivemind
from hivemind.telemetry import runend

ROOT = Path(hivemind.__file__).resolve().parents[2]


def test_the_first_cause_wins_and_a_bare_set_names_its_line():
    stop = runend.StopFlag()
    stop.cause("start failed", "app never reached home")
    stop.set("stop signal/SIGTERM", "later")
    assert stop.is_set()
    assert stop.end_line(1) == "RUN END: start failed: app never reached home (exit 1)"
    bare = runend.StopFlag()
    bare.set()
    category, detail = bare.cause_
    assert category == "stopped" and "test_runend.py:" in detail


def test_no_cause_and_multiline_details_still_make_one_line():
    assert runend.StopFlag().end_line(0) == "RUN END: ended: no cause recorded (exit 0)"
    assert runend.line("crash", "boom\n  more") == "RUN END: crash: boom more"


def test_the_farm_loops_reason_is_sorted():
    assert runend.from_report("could not claim a hive, so ...")[0] == "claim miss"
    assert runend.from_report("stopped by an error: KeyError: 1")[0] == "crash"
    assert runend.from_report(None) == ("ended", "no reason given")


def test_a_socket_peer_is_named_by_its_pid():
    a, b = socket.socketpair(socket.AF_UNIX)
    try:
        said = runend.peer(a)
    finally:
        a.close(), b.close()
    assert said.startswith(f"pid {os.getpid()} (")


def test_a_link_in_a_command_line_never_reaches_the_log(tmp_path, monkeypatch):
    fake = tmp_path / "cmdline"
    fake.write_bytes(b"/usr/bin/sober\0roblox://placeId=1&linkCode=SECRET\0--x\0")
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: real_open(
        fake if str(p) == "/proc/42/cmdline" else p, *a, **k))
    assert runend.proc(42) == "pid 42 (sober <link> --x)"


def test_the_tally_counts_categories_per_day(tmp_path):
    spec = importlib.util.spec_from_file_location("runend_tally", ROOT / "tools/runend_tally.py")
    tally = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tally)
    (tmp_path / "run-001.log").write_text("x\nRUN END: owner stop: Stop (GUI) from pid 1\n")
    (tmp_path / "run-002.log").write_text("RUN END: kicked/277: lost: a: b\n")
    (tmp_path / "run-003.log").write_text("old log\n")
    got = tally.tally(sorted(tmp_path.glob("run-*.log")), day=lambda p: "d")
    assert got == {"d": {"owner stop": 1, "kicked/277": 1, tally.NONE: 1}}


def test_run_farm_ends_every_run_with_the_line():
    body = (ROOT / "scripts/run_farm.py").read_text(encoding="utf-8")
    tail = body[body.index('if __name__ == "__main__":'):]
    assert "print(STOP.end_line(code), flush=True)" in tail
    assert "except BaseException" in tail
    assert "stop = STOP" in body and "stop = threading.Event()" not in body
