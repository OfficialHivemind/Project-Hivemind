"""M2b: the Mondo Chick's loot by sight (act/mondo), look-only by default."""
from __future__ import annotations

from pathlib import Path

import hivemind
from hivemind.act import mondo

ROOT = Path(hivemind.__file__).resolve().parents[2]


class S:
    def __init__(self, on):
        self.on = on

    def bool(self, key):
        assert key == mondo.SETTING
        return self.on


def test_the_kill_words():
    assert mondo.killed("Defeated Mondo Chick!")
    assert mondo.killed("+50 Honey (from Mountain Top Field) DefeatedMondoChick!")
    assert mondo.killed("Mondo Chick was captured")
    assert not mondo.killed("Defeated Commando Chick!")
    assert not mondo.killed("+1 Mondo Belt Bag")
    assert not mondo.killed(None)


def test_off_by_default_and_once_per_kill():
    w = mondo.Watch()
    live, said = w.heard("Defeated Mondo Chick!", "mountain_top", S(False), 0.0)
    assert not live and "combat.mondo_loot is off" in said
    assert w.heard("Defeated Mondo Chick!", "mountain_top", S(True), 5.0) is None
    assert w.heard("nothing", "mountain_top", S(True), 9999.0) is None


def test_look_only_until_the_constant_flips(monkeypatch):
    assert mondo.MONDO_LOOT_LIVE is False
    live, said = mondo.Watch().heard("Defeated Mondo Chick!", "mountain_top", S(True), 0.0)
    assert not live and said.startswith("mondo loot would: ")
    live, said = mondo.Watch().heard("Defeated Mondo Chick!", "pine_tree", S(True), 0.0)
    assert not live and "pine tree" in said and "no walk" in said
    monkeypatch.setattr(mondo, "MONDO_LOOT_LIVE", True)
    live, said = mondo.Watch().heard("Defeated Mondo Chick!", "mountain_top", S(True), 0.0)
    assert live and said.startswith("mondo loot: ")


def test_run_farm_wires_it_into_the_field_kill_loot():
    farm = (ROOT / "scripts" / "run_farm.py").read_text()
    assert "mondo_heard(text)" in farm
    assert 'seconds=kill.get("seconds", FIELD_LOOT_SECONDS)' in farm
    assert 'chases=kill.get("chases", bugrun.LOOT_SIGHT_CHASES)' in farm
