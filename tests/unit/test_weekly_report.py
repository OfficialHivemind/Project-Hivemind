"""ROADMAP P6: the weekly report (benchmark.weekly / weekly_text, Telegram
/weekly). A week that earns more than the one before is called better, a
settled experiment arm is named and an unsettled one is not, and /weekly
answers with the script's text (or says why there is none)."""
import importlib.util
import json
import os
import random
import tempfile
import time
from pathlib import Path

import hivemind

ROOT = Path(hivemind.__file__).resolve().parents[2]


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bm = _load("benchmark_weekly", "benchmark.py")
os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
tg = _load("telegram_alerts_weekly", "telegram_alerts.py")
T0 = 1_791_000_000.0


def _trips(n, gain, start, bal, rng):
    out = []
    for i in range(n):
        g = max(0, int(rng.gauss(gain, gain * 0.2)))
        out.append({"at": start + 1800 * i, "attempt": 1,
                    "decision_id": f"1-{int((start + 1800 * i - 500) * 1000)}",
                    "action": "gather", "aimed_at": "pine_tree", "credited": "pine_tree",
                    "converted": True, "deaths": 0, "seconds": 500, "gather_seconds": 300,
                    "pollen": g // 2, "context": {"honey": bal},
                    "convert_note": f"converted — honey settled at {bal + g:,} (+{g:,})",
                    "routes": [{"kind": "home", "outcome": "landed"}]})
        bal += g
    return out, bal


def test_a_better_week_and_a_settled_arm(tmp_path):
    var, rng = tmp_path / "var", random.Random(4)
    var.mkdir()
    a, bal = _trips(336, 10_000_000, T0, 1_000_000_000, rng)          # 7 days, 1 trip / 30 min
    b, _ = _trips(336, 15_000_000, T0 + bm.WEEK_S, bal, rng)
    (var / "trips.jsonl").write_text("".join(json.dumps(r) + "\n" for r in a + b))
    (var / "experiments.json").write_text(json.dumps({
        "convert_at": {"90": {"tries": 40, "reward": 30}, "100": {"tries": 35, "reward": 14}},
        "sprinkler_jump": {"0.2": {"tries": 4, "reward": 3}, "_contexts": {}}}))
    w = bm.weekly(var, T0 + 2 * bm.WEEK_S, work=tmp_path / "work", boot=300)
    assert w["honey"]["verdict"] == "better" and 40 < w["honey"]["pct"] < 60, w["honey"]
    text = bm.weekly_text(w)
    assert "Honey/hr: " in text and "(better;" in text
    assert "Tried: no updates this week." in text
    assert "Experiment convert_at: 90 leads (reward 0.75)" in text
    assert "Experiment sprinkler_jump: still trying (4 tries" in text


def test_too_little_data_says_so(tmp_path):
    var = tmp_path / "var"
    var.mkdir()
    rows, _ = _trips(10, 10_000_000, T0 + bm.WEEK_S, 1_000_000_000, random.Random(1))
    (var / "trips.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    text = bm.weekly_text(bm.weekly(var, T0 + 2 * bm.WEEK_S, work=tmp_path / "work", boot=50))
    assert "no week-on-week verdict (too few trips: 0 trips the week before, 10" in text


def test_the_weekly_command_sends_the_scripts_text(monkeypatch):
    sent, ran = [], []
    monkeypatch.setattr(tg, "send", sent.append)
    monkeypatch.setattr(tg.subprocess, "run", lambda argv, **kw: ran.append(argv) or type(
        "R", (), {"returncode": 0, "stderr": "", "stdout": "Weekly report, x\n"})())
    msg = {"chat": {"id": 1}, "text": "/weekly", "date": time.time()}
    assert tg.run_command("weekly", msg) == "Weekly report, x"
    assert ran[0][1].endswith("benchmark.py") and ran[0][2:] == ["--weekly"]
    monkeypatch.setattr(tg.subprocess, "run", lambda argv, **kw: type(
        "R", (), {"returncode": 1, "stderr": "boom\nValueError: bad", "stdout": ""})())
    assert tg.run_command("weekly", msg) == "The weekly report could not be made (ValueError: bad)."
    assert "weekly" in tg.COMMANDS and "/weekly" in tg.HELP and len(sent) == 2
