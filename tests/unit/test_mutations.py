import random

from hivemind.brain import knowledge, mutations


def test_file_parses_and_every_id_is_ours():
    d = mutations.load()
    types = knowledge._load("bee_types.yaml")["types"]
    rarities = {t["rarity"] for t in types.values()}
    muts = d["mutations"]
    assert len(muts) == 11
    assert abs(sum(m["weight"] for m in muts.values()) - 5.8) < 1e-9   # the wiki's BaseChance sum
    for kind, m in muts.items():
        assert m["lo"] <= m["hi"][0] <= m["hi"][1], kind
        assert m["unit"] in ("pct", "flat"), kind
    for colour, rules in d["worth"].items():
        assert colour in ("blue", "red", "white")
        for rule in rules:
            assert rule.get("bees") or rule.get("rarity"), rule
            assert rule["why"] and rule["source"], rule
            for bee in rule.get("bees") or ():
                assert bee in types, (colour, bee)
            assert set(rule.get("rarity") or ()) <= rarities, rule
            for w in rule["want"]:
                assert w["kind"] in muts, (colour, w)
                assert w["min"] is None or muts[w["kind"]]["lo"] <= w["min"] <= muts[w["kind"]]["hi"][1]
            assert set(rule.get("avoid") or ()) <= set(muts), rule
    for order in d["order"]["blue"].values():
        assert order
    assert set(d["royal_jelly_rarity"]) <= rarities


def test_bounds_grow_with_level():
    assert mutations.bounds("movespeed", 1) == (2.0, 4.0)
    assert mutations.bounds("movespeed", 25) == (2.0, 6.0)
    assert mutations.bounds("convert_amount_pct", 99) == (10.0, 30.0)   # clamped


def test_biased_roll_matches_a_simulation():
    rng = random.Random(1)
    k = mutations.INFLUENCE
    rolls = [rng.random() * (1 - rng.random() * k) for _ in range(200_000)]
    for x in (0.1, 0.3, 0.5, 0.7, 0.9):
        sim = sum(r <= x for r in rolls) / len(rolls)
        assert abs(mutations._below(x) - sim) < 0.005, x


def test_chance_and_costs():
    share = 0.1 / 5.8
    assert abs(mutations.chance_at_least("movespeed", None, 18) - share) < 1e-12
    assert mutations.chance_at_least("movespeed", 7, 25) == 0.0
    assert mutations.chance_at_least("movespeed", 4, 25) > mutations.chance_at_least("movespeed", 4, 5)
    # a Bitterberry keeps the bee; a Royal Jelly must land the bee too
    bb = mutations.expected_uses("convert_amount_pct", None, 18, "diamond")
    rj = mutations.expected_uses("convert_amount_pct", None, 18, "diamond", "royal_jelly")
    assert round(bb) == 5800 and rj > 1000 * bb
    assert mutations.expected_uses("ability_rate_pct", None, 18, "tabby", "royal_jelly") == float("inf")


def test_worth_and_plan_for_the_blue_hive():
    assert mutations.worth("blue", "diamond")["want"][0] == {"kind": "convert_amount_pct", "min": 25}
    assert "convert_amount_pct" in mutations.worth("blue", "tabby")["avoid"]
    assert mutations.worth("blue", "hasty")["want"][0]["kind"] == "movespeed"   # by rarity
    assert mutations.worth("blue", "basic") is None
    picks = mutations.plan("blue", {"diamond": 9, "bubble": 12, "basic": 0})
    assert [p["bee"] for p in picks] == ["bubble", "diamond"]
    line = mutations.would_lines(picks, level_known=False)[1]
    assert line.startswith("mutations would chase Convert Amount% 25+ on Diamond Bee (x9) at level 18")


def test_a_value_above_the_levels_top_waits_instead_of_costing_inf():
    # an example level-10 hive: CA% tops out at ~20.6 there
    picks = mutations.plan("blue", {"diamond": 9}, level=10)
    assert picks[0]["ready"] > 10
    line = mutations.would_lines(picks)[0]
    assert line.startswith("mutations would wait: Convert Amount% 25+ on Diamond Bee (x9)")
    assert "inf" not in line and f"from level {picks[0]['ready']}" in line
    assert mutations.plan("blue", {"diamond": 1}, level=25)[0]["ready"] == 25
