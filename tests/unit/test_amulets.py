from hivemind.brain import amulets


def test_every_amulet_is_cited_and_well_formed():
    d = amulets.load()
    ids = {s["id"] for s in d["sources"]}
    for g in d["groups"].values():
        assert set(g["source"]) <= ids
    assert len(d["amulets"]) == 26
    for aid, a in d["amulets"].items():
        assert a["group"] in d["groups"], aid
        for s in amulets.stats(aid):
            assert s["stat"] and s["type"], (aid, s)
            if "range" in s:
                assert s["range"][0] <= s["range"][1], (aid, s)


def test_datamined_values_survived_the_conversion():
    # Module:Amulet Stats/data: Supreme Star Blue Pollen 0.15-0.7, x2.5 capacity.
    st = {s["stat"]: s for s in amulets.stats("supreme_star")}
    assert st["Blue Pollen"]["range"] == [0.15, 0.7]
    assert st["Capacity"]["op"] == "mul" and st["Capacity"]["range"] == [2.5, 2.5]
    assert "Pop Star" in st


def test_roll_quality_places_values_and_skips_off_colour():
    q = amulets.roll_quality("supreme_star", {"Blue Pollen": 0.7, "Convert Rate": 1.05,
                                              "Red Pollen": 0.7, "Nope": 1}, "blue")
    assert q["per_stat"] == {"Blue Pollen": 1.0, "Convert Rate": 0.0}
    assert q["score"] == 0.5 and q["skipped"] == ["Red Pollen"] and q["unknown"] == ["Nope"]


def test_compare_same_amulet_by_roll_and_tiers_by_tier():
    old = ("supreme_star", {"Blue Pollen": 0.3})
    better = ("supreme_star", {"Blue Pollen": 0.6})
    assert amulets.compare(old, better, "blue")["choice"] == "replace"
    assert amulets.compare(better, old, "blue")["choice"] == "keep"
    assert amulets.compare(better, better, "blue")["choice"] == "keep"   # tie keeps
    assert amulets.compare(("silver_ant", {}), ("gold_ant", {}))["choice"] == "replace"
    assert amulets.compare(("gold_ant", {}), ("bronze_ant", {}))["choice"] == "keep"
    assert amulets.compare(("moon", {}), ("gold_ant", {}))["choice"] == "keep"
