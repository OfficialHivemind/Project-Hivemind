"""Start from the phone (ROADMAP U23): Telegram /play leaves a request file,
the open window takes it through start on boot's gates, and while
PHONE_START_LIVE is off it only answers 'would: ...'. No Qt, no network,
temp files only."""
from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))

from hivemind.gui import autostart  # noqa: E402

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("telegram_alerts_play",
                                               ROOT / "scripts" / "telegram_alerts.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)

NOW = 1_000_000.0


def ask(tmp_path, at=NOW):
    path = tmp_path / autostart.PHONE_START
    path.write_text(f"{at:.0f}\n")
    return path


def test_ships_look_only():
    assert autostart.PHONE_START_LIVE is False


def test_no_request_does_nothing(tmp_path):
    assert autostart.phone_start(tmp_path / "none", False, lambda: "", NOW) == (False, "")


def test_look_only_says_would_and_takes_the_request(tmp_path):
    path = ask(tmp_path)
    go, text = autostart.phone_start(path, False, lambda: "", NOW + 3)
    assert not go and text.startswith("would: start farming")
    assert not path.exists()


def test_live_presses_play_only_through_the_gates(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "PHONE_START_LIVE", True)
    assert autostart.phone_start(ask(tmp_path), False, lambda: "", NOW)[0] is True
    go, text = autostart.phone_start(ask(tmp_path), False,
                                     lambda: "you are playing another game", NOW)
    assert not go and "another game" in text
    go, text = autostart.phone_start(ask(tmp_path), True, lambda: "", NOW)
    assert not go and "already" in text
    go, text = autostart.phone_start(ask(tmp_path, NOW - 600), False, lambda: "", NOW)
    assert not go and "old" in text


def test_play_command_writes_the_request(tmp_path, monkeypatch):
    path = tmp_path / "night" / autostart.PHONE_START
    monkeypatch.setattr(autostart, "phone_path", lambda: path)
    cmds = tmp_path / "commands.yaml"                # telegram.commands ships off
    cmds.write_text("telegram.commands: true\n")
    msg = {"chat": {"id": 1, "type": "private"}, "text": "/play"}
    assert tg.command_in(msg, settings=cmds) == "play"
    assert tg.command_in(msg, settings=None) is None
    assert "/play" in tg.HELP
    assert "Asked Hivemind" in tg.ask_play(now=NOW)
    assert autostart.phone_start(path, False, lambda: "", NOW)[1].startswith("would:")
