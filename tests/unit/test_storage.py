"""telemetry/storage (guard, retention) and the incident recorder's thinning."""
import os
import time

import numpy as np

from hivemind.telemetry import incidents, storage


def test_guard_stops_frames_and_says_so_once(monkeypatch, tmp_path, capsys):
    state = {"at": -1e18, "ok": True, "told": False}
    monkeypatch.setattr(storage, "free_gb", lambda path: 12.0)
    monkeypatch.setattr(storage, "floor_gb", lambda path, gb: gb)
    t = [0.0]
    assert not storage.frames_allowed(tmp_path, clock=lambda: t[0], state=state)
    t[0] = 120.0
    assert not storage.frames_allowed(tmp_path, clock=lambda: t[0], state=state)
    assert capsys.readouterr().out.count(storage.LOW_DISK_LINE) == 1
    monkeypatch.setattr(storage, "free_gb", lambda path: 50.0)
    t[0] = 130.0                        # cached for a minute
    assert not storage.frames_allowed(tmp_path, clock=lambda: t[0], state=state)
    t[0] = 200.0
    assert storage.frames_allowed(tmp_path, clock=lambda: t[0], state=state)


def test_guard_never_raises(monkeypatch, tmp_path):
    def boom(path):
        raise OSError("gone")
    monkeypatch.setattr(storage, "free_gb", boom)
    state = {"at": -1e18, "ok": True, "told": False}
    assert storage.frames_allowed(tmp_path / "nope", state=state)


def _recorder(tmp_path, n=150, fps=13.8):
    t = [0.0]
    rec = incidents.IncidentRecorder(tmp_path, clock=lambda: t[0])
    frame = np.zeros((8, 8, 3), np.uint8)
    for i in range(n):
        t[0] = i / fps
        rec.push(frame)
    return rec


def test_thinned_save_keeps_the_moment_and_the_numbers(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "frames_allowed", lambda path: True)
    out = _recorder(tmp_path).save("mob-sighting", "bar", lead_every=5)
    names = sorted(p.name for p in out.glob("*.jpg"))
    idx = [int(n[:3]) for n in names]
    assert idx[-1] == 149 and idx[0] == 0 and 75 in idx
    assert set(range(105, 150)) <= set(idx)            # chase.py's frames
    assert 60 <= len(idx) <= 75                         # ~69 of 150
    assert "Thinned" in (out / "reason.txt").read_text()
    full = _recorder(tmp_path).save("death", "x")
    assert len(list(full.glob("*.jpg"))) == 150
    assert "Thinned" not in (full / "reason.txt").read_text()


def test_no_save_while_disk_low(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "frames_allowed", lambda path: False)
    assert _recorder(tmp_path).save("death") is None
    assert not any(tmp_path.iterdir())


def _unit(root, name, size, age_s, now, is_dir=True):
    path = root / name
    if is_dir:
        path.mkdir(parents=True)
        (path / "000.jpg").write_bytes(b"x" * size)
    else:
        root.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    os.utime(path, (now - age_s, now - age_s))
    return path


def test_plan_deletes_oldest_and_spares_the_protected(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "KEEP_NEWEST", 2)
    now = time.time()
    inc = tmp_path / "incidents"
    day = 86400
    old = [_unit(inc, f"0{i}0000-mob-sighting", 1000, (10 - i) * day, now)
           for i in range(6)]          # 6 x 1000 B, oldest first
    (old[1] / storage.KEEP_MARK).write_text("")
    os.utime(old[1], (now - 9 * day, now - 9 * day))
    _unit(tmp_path / "hotbar", "a-stack1.jpg", 1000, 20 * day, now, is_dir=False)
    _unit(tmp_path / "night", "run-1.log", 10_000, 30 * day, now, is_dir=False)
    words = {"020000"}                  # a doc names var/incidents/020000
    p = storage.plan(tmp_path, 3000 / 1e9, words, now=now)
    assert p.total == 7000 and "night" not in p.by_root
    gone = [u.path.name for u in p.doomed]
    # hotbar's only file is among its newest 2; 010000 KEEP, 020000 named,
    # 040000/050000 newest: 000000 and 030000 are all that may go
    assert gone == ["000000-mob-sighting", "030000-mob-sighting"]
    assert storage.apply(p) >= 2000
    assert not old[0].exists() and old[1].exists() and old[2].exists()


def test_plan_stops_at_budget(tmp_path):
    now = time.time()
    for i in range(30):
        _unit(tmp_path / "routes", f"attempt-{i}", 1000, 86400 * (40 - i), now)
    p = storage.plan(tmp_path, 25_000 / 1e9, set(), now=now)
    assert [u.path.name for u in p.doomed] == [f"attempt-{i}" for i in range(5)]


def test_referenced_reads_names_and_stamps(tmp_path):
    (tmp_path / "docs/pending").mkdir(parents=True)
    (tmp_path / "docs/pending/x.md").write_text(
        "see var/incidents/233202 and var/shoplook/20261004-223849-blender-\n"
        "and var/routes/attempt-296 (natro_home_spider)")
    words = storage.referenced(tmp_path)
    assert storage._is_referenced("233202-death", words)
    assert storage._is_referenced("20261004-223849-blender-make.jpg", words)
    assert storage._is_referenced("attempt-296", words)
    assert not storage._is_referenced("attempt-29", words)


def test_retention_off_by_default(tmp_path):
    from hivemind.world.settings import defaults
    assert defaults()["storage.retention_gb"] == 0
    assert storage.maybe_prune(tmp_path, tmp_path, 0) is None
    assert not (tmp_path / storage.STAMP_FILE).exists()


def test_gui_measure_names_the_biggest(tmp_path):
    from hivemind.gui.panels.storage import measure
    (tmp_path / "incidents").mkdir()
    (tmp_path / "incidents" / "a.jpg").write_bytes(b"x" * 3_000_000)
    (tmp_path / "fed.json").write_text("{}")
    text = measure(tmp_path)
    assert text.startswith("var holds 0.0 GB: incidents 0.0 GB")
    assert "GB free on the disk" in text


def test_a_small_disk_is_not_full_for_being_small(tmp_path):
    import shutil
    total = shutil.disk_usage(tmp_path).total / 1e9
    assert abs(storage.floor_gb(tmp_path) - min(20.0, total / 10)) < 1e-6
