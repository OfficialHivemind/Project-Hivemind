"""The Sticker Stack's keep-list (brain/stickers, data/knowledge/stickers.yaml)."""
from hivemind.brain import stickers


def test_rare_stickers_are_kept_and_the_commonest_new_type_goes_first():
    # the owner, 2026-10-07: "what stickers not to use due to rarity"
    t = stickers.load()
    assert len(t["stickers"]) == 260
    for rare in ("Glowing Smile", "Cyan Star", "Shining Star", "Leo Star Sign",
                 "Play Button", "Auryn"):
        assert stickers.keep(rare, t), rare
    assert not stickers.keep("Waxing Crescent Moon", t)       # the wiki: rare, not more
    assert stickers.keep("A Sticker Nobody Listed", t)          # unknown: never on a guess
    held = ["Glowing Smile", "Waxing Crescent Moon", "Lanceolate Leaf",
            "Waxing Crescent Moon", "Flying Rad Bee"]
    out = stickers.stackable(held, stacked=["Lanceolate Leaf"], table=t)
    assert out == sorted(out, key=lambda n: (t["stickers"][n]["rarity"], n))
    assert "Glowing Smile" not in out and "Lanceolate Leaf" not in out
    assert out.count("Waxing Crescent Moon") == 1 and "Flying Rad Bee" in out
