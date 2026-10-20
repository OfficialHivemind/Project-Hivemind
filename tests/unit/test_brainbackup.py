"""ROADMAP S5: the brain backup copies the learned state, not the debug
frames, once a day, keeps the newest KEEP, and never raises."""
from __future__ import annotations

import os

from hivemind.telemetry import brainbackup as bb


def _tree(tmp_path):
    var, data = tmp_path / "var", tmp_path / "data"
    (var / "fieldsense").mkdir(parents=True)
    (var / "incidents" / "x").mkdir(parents=True)
    (data / "knowledge").mkdir(parents=True)
    (var / "skill_stats.json").write_text("{}")
    (var / "trips.jsonl").write_text("{}\n")
    (var / "sober.log").write_text("log")
    (var / "fieldsense" / "live-0001.npz").write_bytes(b"np")
    (var / "incidents" / "x" / "f.jpg").write_bytes(b"jpg")
    (data / "knowledge" / "learned.yaml").write_text("learned: []")
    return var, data


def test_off_when_no_folder(tmp_path):
    var, data = _tree(tmp_path)
    assert bb.maybe_backup(var, data, "") is None
    assert bb.maybe_backup(var, data, "  ") is None


def test_copies_the_brain_only(tmp_path):
    var, data = _tree(tmp_path)
    line = bb.maybe_backup(var, data, tmp_path / "bk")
    assert line.startswith("backup: 4 brain files")
    (copy,) = (tmp_path / "bk").iterdir()
    got = {str(p.relative_to(copy)) for p in copy.rglob("*") if p.is_file()}
    assert got == {"var/skill_stats.json", "var/trips.jsonl",
                   "var/fieldsense/live-0001.npz", "data/knowledge/learned.yaml"}


def test_once_a_day_and_keeps_newest(tmp_path, monkeypatch):
    var, data = _tree(tmp_path)
    dest = tmp_path / "bk"
    assert bb.maybe_backup(var, data, dest, now=1e9)
    assert bb.maybe_backup(var, data, dest) is None          # not due yet
    monkeypatch.setattr(bb, "KEEP", 2)
    for i in range(1, 4):
        for old in bb._copies(dest):                           # age them a day
            os.utime(old, (0, 0))
        assert bb.maybe_backup(var, data, dest, now=1e9 + i * bb.EVERY_S)
    assert len(bb._copies(dest)) == 2


def test_refuses_var_and_never_raises(tmp_path, monkeypatch):
    var, data = _tree(tmp_path)
    assert "inside var" in bb.maybe_backup(var, data, var / "bk")
    monkeypatch.setattr(bb, "MAX_FILE_MB", 0)
    assert "skipped: " in bb.maybe_backup(var, data, tmp_path / "bk")
    monkeypatch.setattr(bb, "_sources", lambda *a: 1 / 0)
    assert bb.maybe_backup(var, data, tmp_path / "bk2").startswith("backup: failed")
