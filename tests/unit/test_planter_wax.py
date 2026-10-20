"""P9 act/planter wax cycles: the wiki's guaranteed wax pairs, their cooldown
claimed by a full harvest, and the look-only pick the plan line says."""
from hivemind.act import planter as pl
from hivemind.brain import nectarplan as np_

DAY = 86400.0
ALL = list(pl.FIELD_COLOURS)


def test_every_wax_pair_names_a_known_planter_and_field():
    for (key, field), (wax, n, days) in pl.WAX_DROPS.items():
        assert key in pl.PLANTERS and field in pl.FIELD_COLOURS
        assert wax in pl.WAX_RANK and n >= 1 and days >= 0
    assert pl.WAX_LIVE is False


def test_a_full_harvest_claims_the_month_a_short_one_does_not():
    now = 1_000_000.0
    grow = pl.grow_s("blue_clay_planter", "spider")
    st = pl.placed({}, "blue_clay_planter", "spider", now)
    short = pl.harvested(st, "blue_clay_planter", now + grow / 2)
    assert "blue_clay_planter@spider" not in (short.get("wax") or {})
    full = pl.harvested(st, "blue_clay_planter", now + grow + 60)
    assert full["wax"]["blue_clay_planter@spider"] == now + grow + 60
    due = lambda st, t: {(k, f) for k, f, *_ in pl.wax_due(st, t)}
    assert ("blue_clay_planter", "spider") not in due(full, now + 29 * DAY)
    assert ("blue_clay_planter", "spider") in due(full, now + grow + 30 * DAY + 60)


def test_the_pick_is_rarest_first_one_per_planter_and_says_the_swap():
    lines = pl.wax_pick({}, ["blue_clay_planter"], [("blue_clay_planter", "pine_tree")],
                        ALL, 0.0)
    # Clover's Caustic before Spider's Swirled, one line for the one planter
    assert lines == ["wax would: put the Blue Clay Planter in clover for its Caustic Wax "
                     "instead of pine tree"]
    # a field already taken or with no route is passed over
    out = {"out": {"red_clay_planter": {"field": "clover", "at": 0.0}}}
    assert "spider" in pl.wax_pick(out, ["blue_clay_planter"], [], ALL, 0.0)[0]
    assert pl.wax_pick({}, ["blue_clay_planter"], [], ["pine_tree"], 0.0) == []
    same = pl.wax_pick({}, ["red_clay_planter"], [("red_clay_planter", "clover")], ALL, 0.0)
    assert same == ["wax would: the plan's Red Clay Planter in clover also gets its Caustic Wax"]


def test_the_day_plan_carries_the_wax_lines():
    levels = {n: 10.0 for n in pl.NECTAR_ORDER}
    got = np_.plan({}, ["Blue Clay Planter"], {}, levels, ALL, 0.0)
    assert got["wax"] and all(w.startswith("wax would: ") for w in got["wax"])
