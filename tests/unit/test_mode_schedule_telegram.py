"""TG8: /mode is /plan by its B14 name; /schedule reads and changes
`schedule.pause` (B15) from the phone, checked with the bot's own parser,
only from the owner's chat."""
from __future__ import annotations

import datetime
import importlib.util
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
_spec = importlib.util.spec_from_file_location("telegram_alerts_tg8",
                                               ROOT / "scripts" / "telegram_alerts.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "SETTINGS", tmp_path / "settings.yaml")
    tg.SETTINGS.write_text("telegram.commands: true\n")
    monkeypatch.setattr(tg, "send", lambda text, keep=True: None)
    monkeypatch.setattr(tg, "env", lambda: {"TELEGRAM_CHAT": "1"})


def test_commands_parse(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert tg.command_in({"text": "/mode tickets"}) == "mode"
    assert tg.command_in({"text": "/schedule"}) == "schedule"
    assert tg.command_in({"text": "/schedule Mon-Fri 09:00-17:00"}) == "schedule"


def test_mode_is_plan(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(tg, "set_plan", lambda words, msg: seen.append(words) or "set")
    monkeypatch.setattr(tg, "plan_text", lambda: "PLAN")
    msg = {"text": "/mode tickets", "date": time.time(), "chat": {"id": 1}}
    assert tg.run_command("mode", msg) == "set" and seen == [" tickets"]
    assert tg.run_command("mode", dict(msg, text="/mode")) == "PLAN"


def test_schedule_shows_inside_or_outside():
    tue_10 = datetime.datetime(2026, 11, 3, 10, 0)
    assert "inside a window" in tg.schedule_text("Mon-Fri 09:00-17:00", tue_10)
    assert "outside" in tg.schedule_text("Mon-Fri 09:00-17:00", tue_10.replace(hour=18))
    assert tg.schedule_text("", tue_10).startswith("No schedule")
    assert "left out" in tg.schedule_text("25:00-26:00", tue_10)


def test_set_schedule_checks_then_sends(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(tg, "ask_bot", lambda *a, **kw: sent.append((a, kw)) or "Set: ok")
    msg = {"text": "/schedule x", "date": time.time(), "chat": {"id": 1}}
    assert "Nothing was changed" in tg.run_command("schedule", dict(msg, text="/schedule 9 to 5"))
    assert sent == []
    assert "Only the owner" in tg.run_command(
        "schedule", dict(msg, text="/schedule off", chat={"id": 2}))
    assert sent == []
    assert tg.run_command("schedule", dict(msg, text="/schedule  Mon-Fri 09:00-17:00")) == "Set: ok"
    assert tg.run_command("schedule", dict(msg, text="/schedule off")) == "Set: ok"
    assert [kw["value"] for _, kw in sent] == ["Mon-Fri 09:00-17:00", ""]
    assert all(a == ("set_setting", "remote") and kw["key"] == "schedule.pause"
               for a, kw in sent)


def test_schedule_works_without_yaml_in_process(tmp_path):
    """The alerts service runs on a python with no PyYAML: /schedule must do
    its YAML work in a venv child (as /settings and /buy do)."""
    import subprocess
    import sys
    code = ("import sys, datetime, importlib.util; sys.modules['yaml'] = None; "
            "s = importlib.util.spec_from_file_location('t', sys.argv[1]); "
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "print(m.schedule_text('Mon-Fri 09:00-17:00', datetime.datetime(2026, 11, 3, 10)))")
    r = subprocess.run([sys.executable, "-c", code, str(ROOT / "scripts" / "telegram_alerts.py")],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "HIVEMIND_TELEGRAM_ENV": str(tmp_path / "t.env"),
                            "PYTHONPATH": str(ROOT / "src")})
    assert r.returncode == 0, r.stderr
    assert "inside a window" in r.stdout
