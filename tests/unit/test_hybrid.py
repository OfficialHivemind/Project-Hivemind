"""brain/hybrid + data/knowledge/progression/alt_goals.yaml (ROADMAP G12):
one order for several one-click targets, shared steps once, cheapest first
where order is free, ETAs from measured rates only."""
from hivemind.brain import hybrid
from hivemind.brain import progression as prog
from hivemind.brain.session_goals import Rates


def ids(plan):
    return [s.id for s in plan.open]


def test_every_target_parses_and_every_ref_is_a_progression_goal():
    data = hybrid.load()
    tg = hybrid.targets(data)
    assert {"fuzzy_alt", "tad_alt", "tide_popper", "diamond_mask", "supreme_star_amulet"} <= set(tg)
    sources = {s["id"] for s in data["sources"]}
    for tid, t in tg.items():
        assert t["label"] and t["line"] and set(t["source"]) <= sources, tid
        for raw in t["steps"]:
            if raw.get("ref"):
                assert hybrid._find(raw["ref"], t["hive"]) is not None, (tid, raw["ref"])
        assert len(hybrid.steps(tid, data)) == len(t["steps"]), tid
    egg = data["bee_sources"]["mythic_egg"]
    assert egg["cost"]["tickets"] == 2500 and len(egg["hatches"]) == 6
    # every wanted bee is a Mythic an egg can hatch, and gifted <= wanted
    for t in tg.values():
        for bee, n in (t.get("gifted") or {}).items():
            assert bee in t["bees"] and n <= t["bees"][bee]
        assert set(t.get("bees") or {}) <= set(egg["hatches"])


def test_shared_steps_once_and_the_eggs_are_shared():
    fuzzy, tad = hybrid.merge(["fuzzy_alt"]), hybrid.merge(["tad_alt"])
    both = hybrid.merge(["fuzzy_alt", "tad_alt"])
    # the Porcelain Dipper is in once, for both
    dipper = [s for s in both.steps if s.id == "porcelain_dipper"]
    assert len(dipper) == 1 and dipper[0].targets == ["Fuzzy alt", "Tad alt"]
    assert len(ids(both)) == len(set(ids(both)))
    # one egg is any Mythic: the hybrid's eggs cost less than both alone
    f, t, b = (next(s for s in p.steps if s.id == hybrid.EGGS_ID).cost["tickets"]
               for p in (fuzzy, tad, both))
    assert t == 6 * 18 * 2500                         # the guide's 18 Tadpoles
    assert b < f + t
    # 45 Fuzzy + 18 Tadpole + 5 Buoyant do not fit: cut to 50 and said
    assert both.notes and "50" in both.notes[0]


def test_dependencies_hold_and_free_steps_go_cheapest_first():
    plan = hybrid.merge(["tide_popper", "diamond_mask", "supreme_star_amulet"])
    order = ids(plan)
    assert order.index("bubble_mask") < order.index("diamond_mask")
    assert (order.index("science_translator_1") < order.index("bucko_quests_150")
            < order.index("bucko_quests_250") < order.index("tide_popper"))
    amulets = [order.index(a) for a in ("silver_star_amulet", "gold_star_amulet",
                                        "diamond_star_amulet", "supreme_star_amulet")]
    assert amulets == sorted(amulets)
    # a Star Treat is fed after the egg, never before
    tad = ids(hybrid.merge(["tad_alt"]))
    assert tad.index(hybrid.EGGS_ID) < tad.index("star_treats_tadpole")


def test_etas_use_measured_rates_only():
    no_rate = hybrid.merge(["supreme_star_amulet"])
    assert all(s.eta_h is None and "honey" in s.waits_on for s in no_rate.open)
    plan = hybrid.merge(["supreme_star_amulet"], rates=Rates(honey_h=1e9))
    eta = {s.id: s.eta_h for s in plan.open}
    # honey is shared: each amulet waits for the ones before it
    assert eta["silver_star_amulet"] == 0.05
    assert eta["supreme_star_amulet"] == (50e6 + 250e6 + 1e9 + 10e9) / 1e9
    # a quest chain has no rate: it and what waits on it say so, the rest do not
    tp = hybrid.merge(["tide_popper", "supreme_star_amulet"], rates=Rates(honey_h=1e9))
    by = {s.id: s for s in tp.open}
    assert by["bucko_quests_250"].eta_h is None
    assert by["tide_popper"].eta_h is None and "250 Bucko Bee quests" in by["tide_popper"].waits_on
    assert by["gold_star_amulet"].eta_h is not None
    assert "not measured" in tp.say() and "Plan for: Tide Popper" in tp.say()


def test_owned_gear_and_bees_are_done():
    acct = prog.Account(bees=50, owned={"porcelain_dipper": "test", "bubble_mask": "test"})
    plan = hybrid.merge(["tad_alt"], acct=acct, rates=Rates(honey_h=1e9),
                        have={"bees": {"tadpole": 18, "fuzzy": 13, "buoyant": 5},
                              "gifted": ["fuzzy", "buoyant"]})
    done = {s.id for s in plan.steps if s.done}
    assert {"porcelain_dipper", "bubble_mask", "hive_slot<=50", hybrid.EGGS_ID,
            "star_treats_fuzzy", "star_treats_buoyant"} <= done
    assert "star_treats_tadpole" in ids(plan) and "diamond_mask" in ids(plan)


def test_from_files_without_reads_never_raises(tmp_path):
    plan = hybrid.from_files(["fuzzy_alt"], var_root=tmp_path)
    assert plan.open and all(s.eta_h is None for s in plan.open if s.cost.get("honey"))
