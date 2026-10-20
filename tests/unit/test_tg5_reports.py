"""TG5: the daily self-review (P7) and the weekly report (P6) on a clock, from
scripts/telegram_alerts.py's watch, behind telegram.reports. No network: send
and the weekly subprocess are patched; the ledger is a tmp file."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
spec = importlib.util.spec_from_file_location("telegram_alerts_tg5",
                                              ROOT / "scripts" / "telegram_alerts.py")
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)

ON = {"telegram.alerts": True, "telegram.reports": True}


def _at(hour, wday):
    return time.struct_time((2026, 11, 1, hour, 0, 0, wday, 305, -1))


def test_due_at_the_report_hour_only_with_both_switches_on():
    assert tg.reports_due(_at(tg.REPORT_HOUR, 2), ON) == ("daily",)
    assert tg.reports_due(_at(tg.REPORT_HOUR, tg.REPORT_WEEKDAY), ON) == ("daily", "weekly")
    assert tg.reports_due(_at(tg.REPORT_HOUR - 1, tg.REPORT_WEEKDAY), ON) == ()
    assert tg.reports_due(_at(tg.REPORT_HOUR, 2), {**ON, "telegram.reports": False}) == ()
    assert tg.reports_due(_at(tg.REPORT_HOUR, 2), {**ON, "telegram.alerts": False}) == ()
    assert tg.DEFAULTS["telegram.reports"] is False


def test_daily_review_reads_the_ledger_and_reports_are_sent(monkeypatch, tmp_path):
    now = 100_000.0
    rows = [{"at": now - 4000, "seconds": 3600, "honey": 36_000_000, "pollen": 1,
             "converted": True, "routes": [], "deaths": 0, "gather_seconds": 3600},
            {"at": now - 300, "seconds": 600, "honey": 0, "pollen": 0, "converted": False,
             "routes": [{"kind": "home", "target": "clover", "outcome": "elsewhere",
                         "seconds": 120}], "deaths": 0, "gather_seconds": 600}]
    (tmp_path / "trips.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(tg, "var", lambda *p: tmp_path.joinpath(*p))
    text = tg.daily_review_text(now)
    assert text.startswith("Daily self-review: 2 trip(s)") and "fix:" in text

    (tmp_path / "trips.jsonl").unlink()
    assert tg.daily_review_text(now) == "Daily self-review: no trips today."

    sent = []
    monkeypatch.setattr(tg, "send", sent.append)
    monkeypatch.setattr(tg, "weekly_text", lambda: "Weekly report: ...")
    tg.send_reports(("daily", "weekly"))
    assert sent == ["Daily self-review: no trips today.", "Weekly report: ..."]
