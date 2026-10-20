"""S3 read health (telemetry/readhealth): a sudden break across kinds, normal
noise that must not trigger, slow drift, and safe mode calling the caller's
own pause. Synthetic records only; temp files; no network."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

from hivemind.telemetry import readhealth as rh

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]


class Clock:
    def __init__(self, t=1_760_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def feed(h, clock, kind, oks, gap=10.0, score=0.9):
    for ok in oks:
        clock.t += gap
        h.note(kind, ok, score)


def test_two_kinds_breaking_at_once_is_a_break():
    c = Clock()
    h = rh.ReadHealth(clock=c)
    feed(h, c, "honey digits", [True] * 20)          # healthy before
    c.t += rh.WINDOW_S
    feed(h, c, "honey digits", [False] * 9 + [True])
    feed(h, c, "hotbar tile", [False] * 8)
    bad = h.broken(rh.BASELINE)
    assert set(bad) == {"honey digits", "hotbar tile"}
    assert bad["hotbar tile"] == (8, 8)


def test_normal_noise_and_one_kind_alone_do_not_trigger():
    c = Clock()
    h = rh.ReadHealth(clock=c)
    # the measured worst days: 13% respawn misses, 5% pollen misses, spread out
    feed(h, c, "respawn landing", ([True] * 7 + [False]) * 4, gap=15)
    feed(h, c, "pollen digits", ([True] * 19 + [False]) * 3, gap=5)
    assert h.broken(rh.BASELINE) == {}
    # 10-07: the pollen counter alone failing 28 of 44 is not an update
    c.t += rh.WINDOW_S
    feed(h, c, "pollen digits", [False] * 28 + [True] * 16, gap=5)
    assert set(h.failing(rh.BASELINE)) == {"pollen digits"}
    assert h.broken(rh.BASELINE) == {}
    # too few reads say nothing; the feed (34% normal) never votes
    feed(h, c, "hotbar tile", [False] * 4, gap=1)
    feed(h, c, "feed line", [False] * 30, gap=1)
    assert h.broken(rh.BASELINE) == {}


def test_old_failures_leave_the_window():
    c = Clock()
    h = rh.ReadHealth(clock=c)
    feed(h, c, "honey digits", [False] * 10)
    feed(h, c, "hotbar tile", [False] * 10)
    assert h.broken(rh.BASELINE)
    c.t += rh.WINDOW_S + 1
    assert h.broken(rh.BASELINE) == {}


def test_flush_daily_and_baseline(tmp_path):
    path = tmp_path / "readhealth.jsonl"
    c = Clock()
    h = rh.ReadHealth(clock=c)
    feed(h, c, "hotbar tile", [True] * 9 + [False], score=0.99)
    assert h.flush(path) == 1
    feed(h, c, "hotbar tile", [True] * 10, score=0.95)
    h.flush(path)
    assert h.flush(path) == 0                         # nothing new
    day = rh._day(c.t)
    cell = rh.daily(path)[day]["hotbar tile"]
    assert (cell["n"], cell["ok"]) == (20, 19)
    assert cell["median"] == 0.95 and cell["p10"] == 0.95
    row = json.loads(path.read_text().splitlines()[0])
    assert row["rate"] == 0.9 and row["median"] == 0.99 and row["p10"] == 0.99
    # a kind with a day of its own replaces the measured default
    later = rh.baseline(path, today="2999-01-01")
    assert later["hotbar tile"] == 0.95 and later["pollen digits"] == rh.BASELINE["pollen digits"]
    assert "quests button" not in later                # unknown: cannot vote yet


def _days(path, kind, medians_by_day, n=100):
    with open(path, "a") as fh:
        for day, med in medians_by_day.items():
            fh.write(json.dumps({"day": day, "kind": kind, "n": n, "ok": n,
                                 "hist": {f"{med:.2f}": n}}) + "\n")


def test_drift_warns_on_a_slow_slide_only(tmp_path):
    path = tmp_path / "readhealth.jsonl"
    base = {f"2026-10-{d:02d}": 0.99 for d in range(1, 15)}
    _days(path, "hotbar tile", base)
    _days(path, "hotbar tile", {"2026-10-15": 0.93, "2026-10-16": 0.92, "2026-10-17": 0.92})
    # honey's content-driven 0.12 step (0.68 -> 0.57, measured) is not drift
    _days(path, "honey digits", {**{d: 0.68 for d in base},
                                 "2026-10-15": 0.57, "2026-10-16": 0.57, "2026-10-17": 0.57})
    out = rh.drift(path, today="2026-10-17")
    assert len(out) == 1 and out[0].startswith("hotbar tile median score 0.92")
    # too few recent reads: nothing said
    path2 = tmp_path / "few.jsonl"
    _days(path2, "hotbar tile", base)
    _days(path2, "hotbar tile", {"2026-10-17": 0.50}, n=10)
    assert rh.drift(path2, today="2026-10-17") == []


def test_safe_mode_keeps_frames_and_pauses_only_for_gather_reads():
    kept, paused, slept = [], [], []
    keep = lambda folder, label, note: kept.append((folder, label, note))   # noqa: E731
    why, line = rh.enter_safe_mode({"hotbar tile": (8, 8), "quests button": (5, 6)},
                                   keep, paused.append, sleep=slept.append, stamp="X")
    assert not paused and "no errands" in line and why.startswith("the game may have updated")
    assert [k[:2] for k in kept] == [("update-X", "frame0"), ("update-X", "frame1"),
                                     ("update-X", "frame2")] and slept == [2.0, 2.0]
    kept.clear()
    why, line = rh.enter_safe_mode({"pollen digits": (9, 10), "honey digits": (9, 10)},
                                   keep, paused.append, sleep=lambda s: None, stamp="Y")
    assert paused == [why] and "paused" in line and len(kept) == 3


def test_the_lines_reach_telegram_as_alerts():
    os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
    spec = importlib.util.spec_from_file_location("telegram_alerts_rh",
                                                  ROOT / "scripts" / "telegram_alerts.py")
    tg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tg)
    _why, line = rh.enter_safe_mode({"hotbar tile": (8, 8), "honey digits": (7, 9)},
                                    lambda *a: None, lambda r: None, sleep=lambda s: None)
    # alerts are off by default since U15b: the owner's file turns them on
    on = Path(tempfile.mkdtemp()) / "settings.yaml"
    on.write_text("telegram.alerts: true\n")
    kind, photo, msg = tg.triage("    03:10:00  " + line, {}, 0.0, settings=on)
    assert (kind, photo) == ("telegram.needs_you", True) and tg.PING_IF.search(msg)
    hit = tg.triage(f"{rh.DRIFT_LINE} hotbar tile median score 0.92 — a template", {}, 0.0,
                    settings=on)
    assert hit[:2] == ("telegram.alerts", False) and not tg.PING_IF.search(hit[2])
