"""$7: codes sent by Telegram (/code) are queued in var/codes.json and the bot
only says what redeeming them would do (act/codes, CODES_LIVE False)."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import time
from pathlib import Path

from hivemind.act import codes

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
_spec = importlib.util.spec_from_file_location("telegram_alerts_codes",
                                               ROOT / "scripts" / "telegram_alerts.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)


def test_queue_checks_the_code_and_skips_repeats(tmp_path):
    assert codes.would(tmp_path) is None
    assert codes.add(" Beesbuzz123 ", tmp_path).startswith("Queued Beesbuzz123")
    assert "already queued" in codes.add("beesbuzz123", tmp_path)
    for bad in ("", "x", "a b", "rm -rf", "Code;Enter", "A" * 41):
        assert codes.add(bad, tmp_path) == codes.USE
    assert codes.pending(tmp_path) == ["Beesbuzz123"]


def test_look_only(tmp_path, monkeypatch):
    assert codes.CODES_LIVE is False
    codes.add("38217", tmp_path)
    live, said = codes.would(tmp_path)
    assert not live and said.startswith("codes would:") and "38217" in said
    monkeypatch.setattr(codes, "CODES_LIVE", True)
    assert codes.would(tmp_path)[0] is True


def test_code_is_a_command_for_the_owner_only(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "SETTINGS", tmp_path / "settings.yaml")
    tg.SETTINGS.write_text("telegram.commands: true\n")
    assert tg.command_in({"text": "/code Roof"}) == "code" and "/code" in tg.HELP
    monkeypatch.setattr(tg, "env", lambda: {"TELEGRAM_CHAT": "1"})
    monkeypatch.setattr(tg, "var", lambda *p: tmp_path.joinpath(*p))
    msg = {"text": "/code Roof", "chat": {"id": 1}, "date": time.time()}
    assert tg.run_command("code", msg).startswith("Queued Roof")
    assert "Only the owner" in tg.run_command("code", dict(msg, chat={"id": 2}))
    assert codes.pending(tmp_path) == ["Roof"]
