"""The playbook (data/knowledge/playbook.yaml): every tip is sourced, and a
tip marked FOLLOWED names code that exists -- so "taught" cannot quietly
become a claim the bot does not keep."""
from __future__ import annotations

import pathlib

import pytest

from hivemind.brain import knowledge

ROOT = pathlib.Path(__import__("hivemind").__file__).resolve().parents[2]
# expert: a pro player's answer relayed by the owner (the pro tester, round 1,
# 19 Oct 2026) -- a prior the bot's own measurement overrides
CONFIDENCE = {"wiki", "guide", "measured", "owner", "expert", "unconfirmed"}


def rules():
    knowledge._load.cache_clear()
    return knowledge.playbook()


def test_the_playbook_loads_with_unique_ids():
    got = rules()
    assert len(got) >= 8
    ids = [r["id"] for r in got]
    assert len(ids) == len(set(ids)), "duplicate rule ids"


@pytest.mark.parametrize("rule", rules(), ids=lambda r: r.get("id", "?"))
def test_every_rule_is_sourced_and_says_what_it_is(rule):
    for key in ("id", "topic", "says", "source", "confidence", "taught"):
        assert rule.get(key), f"{rule.get('id')}: no {key}"
    assert rule["confidence"] in CONFIDENCE, rule["confidence"]
    assert rule["taught"] in knowledge.TAUGHT, rule["taught"]
    if rule["taught"] != "followed":
        assert rule.get("next"), f"{rule['id']}: a rule not followed says what it needs"


@pytest.mark.parametrize("rule", [r for r in rules() if r.get("taught") == "followed"],
                         ids=lambda r: r.get("id", "?"))
def test_a_followed_rule_names_code_that_exists(rule):
    refs = rule.get("followed_by") or []
    assert refs, f"{rule['id']}: followed, but by nothing"
    for ref in refs:
        path, _, symbol = str(ref).partition(":")
        target = ROOT / path
        assert target.exists(), f"{rule['id']}: {path} does not exist"
        if symbol:
            assert symbol in target.read_text(), f"{rule['id']}: {symbol} not in {path}"


def test_the_briefing_is_small_and_puts_followed_rules_first():
    text = knowledge.playbook_briefing("items")
    lines = text.splitlines()
    assert 1 <= len(lines) <= 4 and all(line.startswith("- ") for line in lines)
    assert "Micro-Converter" in lines[0]
    assert knowledge.playbook_rule("buy_royal_jelly")["taught"] == "needs_a_look"
    assert knowledge.playbook_rule("no such rule") == {}
