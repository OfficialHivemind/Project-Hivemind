"""TG3: /setgoal changes the session goals from the phone (brain/session_goals
.set_from_words, the Goals tab's Add + Check in words), only from the owner's
chat; /goals and /buy already answer."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import time
from pathlib import Path

from hivemind.brain import session_goals as sg

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
_spec = importlib.util.spec_from_file_location("telegram_alerts_setgoal",
                                               ROOT / "scripts" / "telegram_alerts.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)


def test_words_add_set_and_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "report", lambda var_root=None, settings=None: "R")
    assert sg.set_from_words("honey 500M", tmp_path, now=100.0) == "R"
    sg.set_from_words("quest Polar  Bear", tmp_path)
    sg.set_from_words("hours 4", tmp_path)
    got = sg.load(tmp_path)
    assert got["hours"] == 4.0
    assert got["goals"] == [{"kind": "honey", "amount": 500e6},
                            {"kind": "quest", "giver": "polar bear"}]
    sg.set_from_words("clear", tmp_path)
    assert sg.load(tmp_path)["goals"] == []


def test_bad_words_change_nothing(tmp_path):
    sg.set_from_words("honey 1B", tmp_path)
    before = sg.load(tmp_path)
    assert "not an amount" in sg.set_from_words("honey lots", tmp_path)
    assert "not a horizon" in sg.set_from_words("hours 500", tmp_path)
    assert sg.set_from_words("", tmp_path) == sg.SETGOAL_USE
    assert sg.set_from_words("item", tmp_path) == sg.SETGOAL_USE
    assert sg.load(tmp_path) == before


def test_setgoal_is_a_command_for_the_owner_only(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "SETTINGS", tmp_path / "settings.yaml")
    tg.SETTINGS.write_text("telegram.commands: true\n")
    assert tg.command_in({"text": "/setgoal honey 2B"}) == "setgoal"
    monkeypatch.setattr(tg, "send", lambda text, keep=True: None)
    monkeypatch.setattr(tg, "env", lambda: {"TELEGRAM_CHAT": "1"})
    seen = []
    monkeypatch.setattr(sg, "set_from_words", lambda words: seen.append(words) or "ok")
    msg = {"text": "/setgoal honey 2B", "date": time.time(), "chat": {"id": 1}}
    assert tg.run_command("setgoal", msg) == "ok" and seen == [" honey 2B"]
    assert "Only the owner" in tg.run_command("setgoal", dict(msg, chat={"id": 2}))
    assert seen == [" honey 2B"]
