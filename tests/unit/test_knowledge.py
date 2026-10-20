"""What the bot knows, and that it is small enough to actually use."""
from __future__ import annotations

from hivemind.brain import knowledge


def test_it_knows_which_fields_are_safe():
    """The most valuable fact it holds.

    A death empties the entire backpack, so for a bot that cannot fight,
    expected honey is pollen-per-hour times the chance of getting home with
    it. Sunflower and Dandelion are the two the wiki states have no mobs.
    """
    safe = knowledge.safe_fields()
    assert "sunflower" in safe and "dandelion" in safe
    assert "pine_tree" not in safe, (
        "Pine Tree has two mantises and a werewolf and must never read safe")


def test_it_knows_what_is_in_pine_tree():
    assert knowledge.dangers("pine_tree").count("mantis") == 2
    assert "werewolf" in knowledge.dangers("pine_tree")


def test_an_unknown_field_reports_nothing_rather_than_guessing():
    assert knowledge.dangers("not_a_real_field") == []


def test_the_navigation_briefing_fits_in_a_small_context():
    """The local model has a 4096-token context and an image fills much of it.

    A wiki dump is not an option; a few hundred tokens of the facts that
    change THIS decision is.
    """
    briefing = knowledge.for_navigation("hive")
    assert briefing, "no navigation briefing at all"
    assert len(briefing) // 4 < 400, "the briefing is too big to send"
    assert "honeycomb" in briefing, "it must say what the hive looks like"
    assert "Make Honey" in briefing, "it must name the prompt that confirms it"


def test_the_briefing_warns_about_the_shop():
    """The bot has walked into the shop repeatedly and pressed interact there."""
    assert "shop" in knowledge.for_navigation("hive").lower()


def test_the_field_briefing_puts_the_safe_ones_first():
    lines = knowledge.for_field_choice().splitlines()
    fields = [ln for ln in lines if ln.startswith("- ")]
    assert "SAFE" in fields[0], "a safe field must be the first suggestion"
    assert "empties the whole backpack" in knowledge.for_field_choice()


def test_missing_knowledge_degrades_quietly(monkeypatch):
    """A missing file must not break a run; it means "I do not know"."""
    monkeypatch.setattr(knowledge, "_load", lambda name: {})
    knowledge.world.cache_clear() if hasattr(knowledge.world, "cache_clear") else None
    assert knowledge.for_navigation("hive") == ""
    assert knowledge.safe_fields() == []


# ---------------------------------------------------------------------------
# Knowledge that grows
# ---------------------------------------------------------------------------
def test_it_can_learn_a_new_fact(tmp_path, monkeypatch):
    """A bot that discovers something and writes it into a code comment has
    not learned anything -- the model never reads code."""
    store = tmp_path / "learned.yaml"
    store.write_text("learned: []\n")
    monkeypatch.setattr(knowledge, "data",
                        lambda *parts: str(store) if parts[-1] == "learned.yaml"
                        else str(tmp_path / parts[-1]))
    knowledge._load.cache_clear()
    assert knowledge.remember("Pine Tree has two mantises.",
                              evidence="the wiki, and dying there repeatedly")
    assert any("two mantises" in e["fact"] for e in knowledge.learned())


def test_a_fact_without_evidence_is_refused(tmp_path, monkeypatch):
    """A rumour in a decision prompt is worse than a gap: it gets acted on."""
    store = tmp_path / "learned.yaml"
    store.write_text("learned: []\n")
    monkeypatch.setattr(knowledge, "data", lambda *p: str(store))
    knowledge._load.cache_clear()
    assert knowledge.remember("something true", evidence="") is False
    assert knowledge.remember("", evidence="I measured it") is False
    assert knowledge.learned() == []


def test_the_same_fact_is_not_learned_twice(tmp_path, monkeypatch):
    """Otherwise a loop fills the file and the briefing becomes noise."""
    store = tmp_path / "learned.yaml"
    store.write_text("learned: []\n")
    monkeypatch.setattr(knowledge, "data", lambda *p: str(store))
    knowledge._load.cache_clear()
    assert knowledge.remember("A prompt reads Claim Hive.", evidence="seen")
    assert knowledge.remember("A prompt reads Claim Hive.", evidence="seen") is False
    assert len(knowledge.learned()) == 1


def test_only_measured_facts_reach_the_model(tmp_path, monkeypatch):
    """The model cannot weigh confidence; it treats every line as true."""
    store = tmp_path / "learned.yaml"
    store.write_text("learned: []\n")
    monkeypatch.setattr(knowledge, "data", lambda *p: str(store))
    knowledge._load.cache_clear()
    knowledge.remember("This one was measured.", evidence="a live run")
    knowledge.remember("This one is a hunch.", evidence="a guess",
                       confidence="suspected")
    briefing = knowledge.for_playing()
    assert "was measured" in briefing
    assert "hunch" not in briefing, "an unmeasured fact reached the model"


def test_the_real_knowledge_base_is_what_the_bot_actually_found():
    """Guards the facts that were learned live, in the file the model reads."""
    # The tests above point `data` at a temp file and leave it in the cache.
    knowledge._load.cache_clear()
    facts = " ".join(e["fact"] for e in knowledge.learned())
    assert "Claim Hive" in facts
    assert "Make Honey" in facts
    assert "empties the entire backpack" in facts
