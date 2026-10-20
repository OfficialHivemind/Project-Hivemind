"""The black box: bounded, and it keeps the frames BEFORE the failure."""
from __future__ import annotations

import numpy as np

from hivemind.telemetry.incidents import IncidentRecorder


def frame(value: int = 40):
    return np.full((64, 96, 3), value, np.uint8)


def test_the_window_cannot_grow_without_bound(tmp_path):
    """A recorder that accumulates for an eight-hour run is a fourth OOM.

    Three processes were OOM-killed on this machine holding 16-25 GB each, so
    a debugging aid that keeps frames has to be provably bounded.
    """
    rec = IncidentRecorder(tmp_path, window=10)
    for i in range(500):
        rec.push(frame(i % 250))
    assert len(rec.window) == 10


def test_frames_are_stored_encoded_not_raw(tmp_path):
    """A raw 1920x1080 BGRA frame is 8 MB; forty would be 330 MB live."""
    rec = IncidentRecorder(tmp_path, window=5)
    rec.push(np.full((1080, 1920, 3), 90, np.uint8))
    _, data = rec.window[0]
    assert isinstance(data, (bytes, bytearray))
    assert len(data) < 1080 * 1920 * 3 / 10, "that is not compressed"


def test_saving_writes_the_window_oldest_first(tmp_path):
    rec = IncidentRecorder(tmp_path, window=6)
    for i in range(6):
        rec.push(frame(10 * i))
    out = rec.save("death", "pollen fell 139,449 -> 0")
    assert out is not None and out.is_dir()
    jpgs = sorted(p.name for p in out.glob("*.jpg"))
    assert len(jpgs) == 6
    assert jpgs[0].startswith("000"), "the oldest frame must sort first"
    reason = (out / "reason.txt").read_text()
    assert "death" in reason and "139,449" in reason
    assert "LAST frame" in reason, "a reader must know which end is the moment"


def test_saving_an_empty_window_is_not_an_error(tmp_path):
    assert IncidentRecorder(tmp_path).save("nothing yet") is None


def test_a_bad_frame_is_counted_not_raised(tmp_path):
    """The black box must never be able to stop the run it is recording."""
    rec = IncidentRecorder(tmp_path, window=4)
    assert rec.push(None) is False
    assert rec.push(np.zeros((0, 0, 3), np.uint8)) is False
    assert rec.push("not a frame") is False
    assert len(rec.window) == 0
    assert rec.dropped == 3


def test_it_stops_filling_the_disk(tmp_path):
    rec = IncidentRecorder(tmp_path, window=2)
    rec.push(frame())
    rec.saved = 10_000
    assert rec.save("one too many") is None


def test_a_saved_moment_keeps_the_window_and_the_logs_last_lines(tmp_path):
    """"Save this moment" (ROADMAP BUG-PACK): the frames AND what the log said."""
    from hivemind.telemetry import incidents
    rec = IncidentRecorder(tmp_path / "incidents", window=4)
    for i in range(4):
        rec.push(frame(30 * i))
    log = tmp_path / "run-1256.log"
    log.write_text("".join(f"line {i}\n" for i in range(1000)), encoding="utf-8")
    out = rec.save_moment(log, "saved from the live view")
    assert out.name.endswith("-" + incidents.MANUAL)
    assert len(list(out.glob("*.jpg"))) == 4
    lines = (out / "log-tail.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == incidents.LOG_TAIL_LINES and lines[-1] == "line 999"
    assert "saved from the live view" in (out / "reason.txt").read_text()
    # no log (a hand run) or a missing one: the frames are still kept
    assert rec.save_moment(None) is not None
    assert rec.save_moment(tmp_path / "gone.log") is not None
