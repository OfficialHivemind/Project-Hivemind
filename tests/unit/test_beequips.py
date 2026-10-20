import pytest

from hivemind.brain import beequips, knowledge
from hivemind.datapaths import config_dir


def test_load_has_every_section():
    d = beequips.load()
    assert {"mechanics", "beequips", "rankings"} <= set(d)
    assert d["mechanics"]["waxes"]["caustic"]["success"] == 0.25
    assert len(d["beequips"]) >= 40


def test_rankings_point_at_real_beequips_and_bees():
    d = beequips.load()
    types = knowledge._load("bee_types.yaml")["types"]
    for colour, rows in d["rankings"].items():
        for row in rows:
            assert row["beequip"] in d["beequips"], (colour, row)
            for bee in row.get("wearers") or []:
                assert bee in types, (colour, row["beequip"], bee)
    for bid, eq in d["beequips"].items():
        if isinstance(eq.get("bees"), list):
            for bee in eq["bees"]:
                assert bee in types, (bid, bee)


def test_best_for_blue_ranks_pinecone_first_with_reasons():
    picks = beequips.best_for("blue")
    assert picks[0]["beequip"] == "pinecone" and picks[0]["rank"] == 1
    assert all(p["why"] for p in picks)


def test_best_for_a_bee_filters_and_appends_unranked():
    dia = [p["beequip"] for p in beequips.best_for("blue", "diamond")]
    assert dia.index("candy_ring") < dia.index("elf_cap")
    assert "pinecone" not in dia
    bubble = beequips.best_for("blue", "bubble")
    assert bubble[0]["beequip"] == "camphor_lip_balm"
    assert any(p["rank"] is None and p["beequip"] == "kazoo" for p in bubble)


def test_can_wear_respects_lists_and_colour():
    assert beequips.can_wear("reindeer_antlers", "puppy") is True
    assert beequips.can_wear("reindeer_antlers", "diamond") is False
    assert beequips.can_wear("thumbtack", "bubble") is False   # red only
    assert beequips.can_wear("paperclip", "bubble") is None    # prose rule


def test_plan_puts_owned_beequips_on_held_bees_one_each():
    bees = {"bubble": 13, "diamond": 2, "bear": 1}
    picks = beequips.plan("blue", bees, owned={"camphor_lip_balm": 1, "elf_cap": 5,
                                               "pinecone": 1}, level=20)
    got = [(p["beequip"], p["bee"]) for p in picks]
    assert got[0] == ("pinecone", "bear")
    assert ("camphor_lip_balm", "bubble") in got
    assert got.count(("elf_cap", "diamond")) == 2       # the ranking's count, and 2 Diamonds
    assert all(p["owned"] for p in picks)
    line = beequips.would_lines(picks)[0]
    assert line.startswith("beequips would: put Pinecone on a Bear Bee because")


def test_plan_never_puts_two_on_one_bee_or_a_gifted_item_on_an_ungifted_bee():
    picks = beequips.plan("blue", {"diamond": 1}, owned={"candy_ring": 1, "rose_headband": 1,
                                                         "snow_tiara": 1}, level=20)
    assert [p["beequip"] for p in picks] == ["candy_ring"]          # ranked first, one bee
    tiara = beequips.plan("blue", {"diamond": 3}, owned={"snow_tiara": 1}, level=20)
    assert tiara == []                                               # no gifted Diamond
    tiara = beequips.plan("blue", {"diamond": 3}, owned={"snow_tiara": 1},
                          gifted={"diamond"}, level=20)
    assert [(p["beequip"], p["bee"]) for p in tiara] == [("snow_tiara", "diamond")]


def test_plan_says_why_an_owned_beequip_stays_off_and_marks_the_unknown():
    picks = beequips.plan("blue", {"bubble": 3}, owned={"camphor_lip_balm": 1}, level=10)
    assert picks[0]["bee"] is None
    assert "level-12" in beequips.would_lines(picks)[0]
    unknown = beequips.plan("blue", {"bubble": 3, "bear": 1}, owned=None, level=10)
    assert [p["beequip"] for p in unknown] == ["pinecone"]   # lip balm too high: not said
    assert "if he had it" in beequips.would_lines(unknown)[0]
    assert beequips.would_lines([])[0].startswith("beequips would: nothing")


def test_account_beequips_are_unknown_until_read():
    if not (config_dir() / knowledge.ACCOUNT_FILE).exists():   # the blank template: needs the owner's own file
        pytest.skip("reads the owner's own account.yaml (config dir); this install has the blank template")
    acct = knowledge.account()["beequips"]
    assert beequips.owned_from_account() is None or isinstance(beequips.owned_from_account(), dict)
    assert {"soft", "hard", "swirled"} <= set(acct["waxes"])
