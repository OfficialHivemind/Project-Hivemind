"""X5: the Stick Bug Challenge (act/stickbug), look-only, off by default."""
from __future__ import annotations

from pathlib import Path

import yaml

import hivemind
from hivemind.act import stickbug
from hivemind.world.settings import SECTIONS

ROOT = Path(hivemind.__file__).resolve().parents[2]


class S:
    def __init__(self, on):
        self.on = on

    def bool(self, key):
        assert key == stickbug.SETTING
        return self.on


def test_off_by_default_and_silent_when_off():
    entry = [e for _, es in SECTIONS for e in es if e[0] == stickbug.SETTING]
    assert len(entry) == 1 and entry[0][3] is False
    assert stickbug.would(S(False), 30) is None


def test_look_only_and_clear_of_the_mondo_chick(monkeypatch):
    assert stickbug.STICK_BUG_LIVE is False
    live, said = stickbug.would(S(True), 30)
    assert not live and said.startswith("stick bug would:") and "look-only" in said
    for minute in (0, 14, 50, 59):
        live, said = stickbug.would(S(True), minute)
        assert not live and "not now" in said
    monkeypatch.setattr(stickbug, "STICK_BUG_LIVE", True)
    assert stickbug.would(S(True), 30)[0] is True


def test_the_knowledge_file_is_sourced():
    doc = yaml.safe_load((ROOT / "data" / "knowledge" / "stickbug.yaml").read_text())
    ids = {s["id"] for s in doc["sources"]}
    assert doc["challenge"]["free_every_h"] * 3600 == stickbug.FREE_EVERY_S
    assert doc["challenge"]["ticket_price"] == stickbug.TICKET_PRICE
    for section in ("npc", "challenge", "amulets"):
        assert set(doc[section]["source"]) <= ids
