"""tools/week_check.py: one run log + attempts.log -> the week table."""
import importlib.util
import sys
import time
from pathlib import Path

import hivemind

ROOT = Path(hivemind.__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
_spec = importlib.util.spec_from_file_location("week_check", ROOT / "tools" / "week_check.py")
wc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wc)


def test_week_table(tmp_path):
    night = tmp_path / "night"
    night.mkdir()
    (night / "attempts.log").write_text(
        f"[overnight] attempt 7 starting 2026-10-27 10:00:00 -> {night}/run-007.log\n"
        "[overnight] attempt 7 exited 0 after 3600s\n", encoding="utf-8")
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "a.jpg").write_bytes(b"")
    aim = "the trip aimed at pepper and the game credited pepper while it was out"
    (night / "run-007.log").write_text("\n".join([
        "  in game after 40s",
        f"    10:01:00  {aim}",
        "    10:02:00  to hive: arrived — on our own hive pad",
        "    10:03:00  cycle 1: 5 pollen",
        f"    10:04:00  {aim}",
        "    10:05:00  to hive: did not get there — turned a full circle",
        "    10:05:10  whirligig rescue: on our pad",
        "    10:06:00  cycle 2: 5 pollen",
        "    10:07:00  asking for a rejoin",
        "    10:08:00  x would: walk [kept a.jpg]",
        "    10:09:00  Ant Challenge: 40 look(s) in 99s, last read round 12, score 9",
        "Traceback (most recent call last):",
        "ValueError: bad read 3",
        "    10:10:00  RUN END: kicked/277: lost",
    ]) + "\n", encoding="utf-8")
    t0 = time.mktime(time.strptime("2026-10-27 09:00", "%Y-%m-%d %H:%M"))
    out = wc.check(tmp_path, t0, t0 + 4 * 3600, looks=[("X_LIVE", ["x would:"])])
    assert "1/2 = 50.0%" in out and "FAIL   worst: pepper 1/2" in out
    assert "12 over 1 game(s)" in out and "1 traceback(s)" in out
    assert "traceback: ValueError: bad read N" in out
    assert "X_LIVE" in out and str(tmp_path / "frames" / "a.jpg") in out
    assert "RUN END: kicked/277 1" in out and "honey/h" in out
    line = next(r for r in out.splitlines() if "trips (cycle N:)" in r)
    assert line.split()[-3] == "2"
