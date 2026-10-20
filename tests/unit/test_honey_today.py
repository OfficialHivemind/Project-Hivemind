"""ROADMAP P4: the day's one honey/h number (benchmark.today / today_line)
on made-up trips -- today vs yesterday vs the 7 days before, too little data
today says so, and the line's wording. The card's headline is drawn from it."""
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import hivemind

REPO = Path(hivemind.__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("benchmark_p4", REPO / "scripts" / "benchmark.py")
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

# 10:00 local on a fixed day: today has 10 hours, the windows are whole days
NOW = dt.datetime(2026, 10, 14, 10, 0).timestamp()
MIDNIGHT = dt.datetime(2026, 10, 14).timestamp()


def fake_var(var: Path, today_trips: int = 50) -> Path:
    """A trip every 600 s: 10M a trip (60M/h) the days before yesterday,
    15M (90M/h) yesterday, 12M (72M/h) today. FAKE, never the owner's."""
    (var / "night").mkdir(parents=True)
    rows, bal = [], 1_000_000_000
    t = MIDNIGHT - 8 * 86400
    end = MIDNIGHT + 600 * today_trips
    while t < end:
        t += 600
        g = 12_000_000 if t >= MIDNIGHT else 15_000_000 if t >= MIDNIGHT - 86400 else 10_000_000
        rows.append({"FAKE": True, "at": t, "attempt": int(t // 86400), "seconds": 500,
                     "decision_id": f"1-{int((t - 600) * 1000)}", "context": {"honey": bal},
                     "convert_note": f"honey settled at {bal + g:,}"})
        bal += g
    (var / "trips.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    stamp = dt.datetime.fromtimestamp(MIDNIGHT).strftime("%Y-%m-%d %H:%M:%S")
    (var / "night" / "attempts.log").write_text(
        f"[overnight] attempt 9 starting {stamp} -> /fake/run-9.log\n"
        f"[overnight] attempt 9 exited 0 after {5 * 3600}s\n")
    return var


def test_today_yesterday_and_the_week(tmp_path):
    d = bm.today(fake_var(tmp_path / "var"), NOW)
    assert abs(d["today"] - 72e6) < 1e6
    assert abs(d["yesterday"] - 90e6) < 1e6
    assert abs(d["week"] - (6 * 60e6 + 90e6) / 7) < 1e6        # the 7 days before today
    assert d["vs_week_pct"] == 12.0
    assert d["running_hours"] == 5.0 and d["uptime_pct"] == 50.0      # 5 h of 10
    line = bm.today_line(d)
    assert line.startswith("Honey/hr today: 72M (yesterday 90M · 7-day 64.3M) 🟢▲ 12% vs 7-day")
    assert line.endswith("running 5.0 h, uptime 50%")
    assert "🟢" not in bm.today_line(d, emoji=False)


def test_too_little_data_today_says_so(tmp_path):
    d = bm.today(fake_var(tmp_path / "var", today_trips=3), NOW)
    assert d["today"] is None and d["readings"] < bm.MIN_TODAY_READINGS
    assert d["vs_week_pct"] is None and d["week"] is not None
    line = bm.today_line(d)
    assert line.startswith("Honey/hr today: not enough data yet today")
    assert "▲" not in line and "▼" not in line


def test_an_empty_var_and_the_formatting(tmp_path):
    (tmp_path / "v").mkdir()
    d = bm.today(tmp_path / "v", NOW)
    assert d["today"] is d["yesterday"] is d["week"] is None
    assert "(yesterday - · 7-day -)" in bm.today_line(d)
    down = {"today": 98.2e6, "yesterday": 92.5e6, "week": 103e6, "readings": 40,
            "min_readings": 6, "vs_week_pct": -4.7, "running_hours": None}
    assert bm.today_line(down) == ("Honey/hr today: 98.2M (yesterday 92.5M · 7-day 103M) "
                                   "🔴▼ 5% vs 7-day")
    assert [bm._short(v) for v in (1.5e9, 431_000, 12)] == ["1.5B", "431K", "12"]


def test_the_cli_prints_the_line_and_writes_nothing(tmp_path, capsys):
    var = fake_var(tmp_path / "var")
    before = sorted(p.name for p in var.iterdir())
    assert bm.main(["--today", "--var", str(var), "--now", str(NOW)]) == 0
    assert capsys.readouterr().out.startswith("Honey/hr today: 72M")
    assert sorted(p.name for p in var.iterdir()) == before


def test_the_card_draws_the_headline(tmp_path):
    sys.path.insert(0, str(REPO / "scripts"))
    import daily_card
    d = bm.today(fake_var(tmp_path / "var"), NOW)
    out = daily_card.render({"hours": 24, "today": d}, tmp_path / "card.png", "FAKE")
    assert out.stat().st_size > 10_000
