"""Gumdrops for the Blender's Glue (brain/buyer): bought at the Gumdrop Shop
only while the next goal's Glue lacks them and goals.yaml says the bot does
that source, and not thrown for goo once bought (gumdrops_kept). The account
as MEASURED 2026-10-14 07:28 (var/inventory.json): Glue 1/50 for the
Honeycomb Belt, 13 Gumdrops, 975 Royal Jelly, the Enzymes and Oil held."""
from __future__ import annotations

import copy


def _plan(shop_bot: str = "does"):
    from hivemind.brain import buyer, goals
    data = copy.deepcopy(goals.load())
    for src in data["materials"]["glue"]["sources"]:
        if src.get("place") == buyer.GUMDROP_SHOP:
            src["bot"] = shop_bot
    held = {"enzymes": (50, "read"), "oil": (25, "read"), "glue": (1, "read")}
    return goals.build(data, honey=1_900_000_000, order=["honeycomb_belt"], held=held)


def test_the_belts_glue_buys_gumdrops_and_keeps_what_it_bought():
    from hivemind.brain import buyer
    held = {"gumdrops": 13, "royal_jelly": 975, "enzymes": 50, "oil": 25, "glue": 1}
    made = buyer.crafting_from_files(_plan(), held)
    assert made.takes == {"gumdrops": 2450, "royal_jelly": 490}
    lacking, why = buyer.gumdrops_for_the_blender(_plan(), made)
    assert lacking == 2437 and "49 Glue for the Honeycomb Belt take 2,450 Gumdrops, 13 held" in why
    # `bot: yours` in goals.yaml stops the buying
    assert buyer.gumdrops_for_the_blender(_plan("yours"), made) == (0, "")
    # 300 bought stay for 6 Glue; today's odd 13 still go to goo, down to the keep of 10
    assert buyer.gumdrops_kept(313, 2450, 10) == 300
    assert buyer.gumdrops_kept(13, 2450, 10) == 10
    assert buyer.gumdrops_kept(313, 0, 10) == 10
