"""ROADMAP Q7: a goo quest's goo from gumdrops, the Gummy Bee's ability, or
both (settings quests.goo_source, brain/protips.gumdrops_for_goo)."""
from __future__ import annotations

from pathlib import Path

import hivemind
from hivemind.brain import protips
from hivemind.world import settings as settings_mod

REPO = Path(hivemind.__file__).resolve().parents[2]


def test_gumdrops_is_the_default_and_the_old_behaviour():
    assert settings_mod.defaults()["quests.goo_source"] == protips.GOO_FROM_GUMDROPS
    for owned in ("", "Gummy Bee", "Gummy Mask"):
        assert protips.gumdrops_for_goo("gumdrops", owned) == (True, "")
        assert protips.gumdrops_for_goo("both", owned) == (True, "")
        assert protips.gumdrops_for_goo(None, owned) == (True, "")


def test_the_gummy_bee_s_ability_throws_none_only_with_the_gummy_bee():
    throw, why = protips.gumdrops_for_goo(protips.GOO_FROM_GUMMY, "Gummy Bee")
    assert throw is False and "Gummy Bee's ability" in why
    for owned in ("", "Gummy Mask", "Gummy Boots"):
        throw, why = protips.gumdrops_for_goo(protips.GOO_FROM_GUMMY, owned)
        assert throw is True and "no Gummy Bee" in why


def test_the_setting_offers_exactly_the_three_sources():
    row = next(r for _, rows in settings_mod.SECTIONS for r in rows
               if r[0] == "quests.goo_source")
    assert row[2] == "choice" and row[3] == protips.GOO_FROM_GUMDROPS
    assert row[5] == [protips.GOO_FROM_GUMDROPS, protips.GOO_FROM_GUMMY,
                      protips.GOO_FROM_BOTH]
    assert "quests.goo_source" in settings_mod.READ_AT_EVERY_USE


def test_the_gumdrop_throw_asks_the_setting_before_every_throw():
    src = (REPO / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    body = src[src.index("def throw_a_gumdrop"):]
    body = body[:body.index("hotbar_press(inp, cap.capture, GUMDROP_SLOT")]
    assert 'protips.gumdrops_for_goo(settings.get("quests.goo_source")' in body
    assert "if not throw:" in body
