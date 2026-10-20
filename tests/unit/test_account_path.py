"""The shipped account.yaml is a blank template; the player's own file in the
config dir wins (the owner, 2026-10-20: their progress is not shipped)."""
from pathlib import Path

import yaml

import hivemind
from hivemind.brain import knowledge

REPO = Path(hivemind.__file__).resolve().parents[2]


def test_shipped_account_is_a_blank_template():
    data = yaml.safe_load((REPO / "data/knowledge/account.yaml").read_text())
    assert data["hive"]["level"] is None and data["hive"]["bees"] is None
    assert data["inventory"] == {} and data["badges"] == {}
    assert data["codes"]["all_redeemed"] is False


def test_config_dir_account_wins(tmp_path, monkeypatch):
    monkeypatch.setattr("hivemind.datapaths.config_dir", lambda: tmp_path)
    assert knowledge.account_path() == Path(knowledge.data("knowledge", knowledge.ACCOUNT_FILE))
    (tmp_path / knowledge.ACCOUNT_FILE).write_text("hive:\n  level: 10\n  bees: 34\n")
    assert knowledge.account_path() == tmp_path / knowledge.ACCOUNT_FILE
    assert knowledge.account()["hive"]["bees"] == 34
    assert knowledge.standing().bees == 34
