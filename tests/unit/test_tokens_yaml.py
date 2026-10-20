"""tokens.yaml's lifetimes and per-hive ranking (vision/tokens Kinds)."""
from pathlib import Path

import hivemind

from hivemind.vision import tokens
from hivemind.vision.tokens import Kinds, load_kinds

# beside the CODE under test (the deploy gate copies tests into the live tree)
YAML = Path(hivemind.__file__).resolve().parents[2] / "data/knowledge/tokens.yaml"


def test_every_life_s_names_its_source():
    lines = [ln for ln in YAML.read_text(encoding="utf-8").splitlines()
             if ln.strip().startswith("life_s:")]
    assert len(lines) >= 9
    assert all("Module:Ability_Tokens" in ln for ln in lines)


def test_life_s_reads_the_table_and_unknown_falls_back():
    k = load_kinds(YAML, hive="blue")
    assert k.life_s("blue_boost") == 4.0 and k.life_s("honey") == 10.0
    assert k.life_s("unknown") == 4.0
    assert k.life_s("tabby_love") is None
    # the typed head's names with no row live as long as an unnamed coin
    assert k.life_s("black_blue_burst") == 4.0 and k.life_s("red_boost") == 4.0


def test_priority_by_hive_is_look_only():
    k = Kinds({"focus": {"priority": 10, "priority_by_hive": {"blue": 5}}}, hive="blue")
    assert tokens.PRIORITY_BY_HIVE_LIVE is False
    assert k.priority("focus") == 10


def test_priority_by_hive_falls_back_to_priority(monkeypatch):
    monkeypatch.setattr(tokens, "PRIORITY_BY_HIVE_LIVE", True)
    k = Kinds({"focus": {"priority": 10, "priority_by_hive": {"blue": 5}},
               "haste": {"priority": 10}}, hive="blue")
    assert k.priority("focus") == 5 and k.priority("haste") == 10
    assert Kinds(k.kinds, hive="red").priority("focus") == 10
    k.want(["focus"])
    assert k.priority("focus") == 1          # a quest still ranks first
