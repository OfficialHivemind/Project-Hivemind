

def test_a_slot_bought_moves_the_next_slot_goal_on(tmp_path):
    # 2026-10-03 06:01: the bot bought the 35th slot; with 34 bees still, the
    # goal kept offering "Hive Slot (bee 35)" until an egg hatched in it
    import json as _json
    from hivemind.brain import goals as g
    slots = {35: 209_117_953, 36: 283_309_237}
    assert g.slots_bought(tmp_path, slots) == 0
    (tmp_path / "purchases.json").write_text(_json.dumps([
        {"item": "Hive Slot", "price": 209_117_953, "ok": True},
        {"item": "Hive Slot", "price": 283_309_237, "ok": False}]))
    assert g.slots_bought(tmp_path, slots) == 35
    data = {"default_order": ["hive_slot"], "goals": {}}
    nxt = g.with_next_slot(data, max(34, g.slots_bought(tmp_path, slots)), slots)
    assert nxt["default_order"] == ["hive_slot_36"]


def test_a_slot_waits_for_the_last_slots_bee_and_for_an_egg(tmp_path):
    # MEASURED 2026-10-03 09:59: 35 bees, no egg held, 399M honey -- and the
    # plan said "buying it" for slot 36 while run_farm's guard refused it
    import json as _json
    from hivemind.brain import goals as g
    (tmp_path / "purchases.json").write_text(_json.dumps([
        {"item": "Hive Slot", "price": 209_117_953, "ok": True}]))
    assert "still waits for its bee" in g.slot_waits(tmp_path, 34)
    assert "no Basic Egg is held" in g.slot_waits(tmp_path, 35)
    # var/inventory.json's rows are {count, label}; the Honey Mask takes five
    # Gold Eggs, and the slot's egg is the guide's Basic Egg
    (tmp_path / "inventory.json").write_text(_json.dumps(
        {"items": {"gold_egg": {"count": 1, "label": "Gold Egg"}}}))
    assert "no Basic Egg is held" in g.slot_waits(tmp_path, 35)
    (tmp_path / "inventory.json").write_text(_json.dumps(
        {"items": {"basic_egg": {"count": 1, "label": "Basic Egg"}}}))
    assert g.slot_waits(tmp_path, 35) == ""
    # an egg hatched since the read: its count of one is not believed
    from hivemind.act import inventory
    inventory.mark_dirty(tmp_path / "inventory.json", "the Basic Egg hatched")
    assert "not been read again since the Basic Egg hatched" in g.slot_waits(tmp_path, 35)
    assert inventory.dirty(tmp_path / "inventory.json").startswith("the Basic Egg hatched")
    (tmp_path / "inventory.json").write_text(_json.dumps(
        {"items": {"basic_egg": {"count": 1, "label": "Basic Egg"}}}))   # a read rewrites it
    assert g.slot_waits(tmp_path, 35) == ""
    # a feed or a jelly roll changes neither the bees counted nor the eggs held
    # (MEASURED 2026-10-07 10:21-11:00: each window's feed held the slot back)
    inventory.mark_dirty(tmp_path / "inventory.json", "30 Pineapple fed")
    inventory.mark_dirty(tmp_path / "bees.json", "1 Royal Jelly rolled")
    assert g.slot_waits(tmp_path, 35) == ""
    inventory.mark_dirty(tmp_path / "inventory.json", "a Basic Egg bought")
    assert "since a Basic Egg bought" in g.slot_waits(tmp_path, 35)


def test_only_a_basic_egg_fills_the_next_slot(tmp_path):
    # THE OWNER, 2026-10-10: no egg but the Basic is spent -- Silver and Star
    # Eggs are saved (a Star Egg waits until every other type is gifted)
    import json as _json
    from hivemind.brain import goals as g
    (tmp_path / "purchases.json").write_text(_json.dumps([
        {"item": "Hive Slot", "price": 209_117_953, "ok": True}]))
    (tmp_path / "inventory.json").write_text(_json.dumps(
        {"items": {"silver_egg": {"count": 1, "label": "Silver Egg"}}}))
    assert g.slot_egg_held({"silver_egg": 1}) is None
    assert g.slot_egg_held({"star_egg": 1, "silver_egg": 1, "basic_egg": 2}) == ("basic_egg", "Basic Egg")
    assert g.slot_egg_held({"basic_egg": 2}) == ("basic_egg", "Basic Egg")
    assert g.slot_egg_held({"gold_egg": 5}) is None


def test_only_basic_and_event_bee_eggs_may_hatch():
    from hivemind.brain import goals as g

    class Shipped:      # the shipped defaults, not whoever runs the test's own settings
        def get(self, key, default=None):
            return default
    s = Shipped()
    assert g.egg_may_hatch("Basic Egg", s) and g.egg_may_hatch("Festive Bee Egg", s)
    for saved in ("Silver Egg", "Gold Egg", "Diamond Egg", "Star Egg", "Mythic Egg", ""):
        assert not g.egg_may_hatch(saved, s)


def test_the_rate_counts_only_time_that_earned():
    # research 2026-10-21: 134.6M/h said against the HUD's 238M/h -- breaks under
    # the 3 h sitting gap counted as farming, and a purchase kept its time
    from hivemind.brain import goals as G

    def row(at, honey):
        return {"at": at, "convert_note": f"honey settled at {honey:,}"}
    t0 = 1_000_000.0
    rows = [row(t0 + i * 600, 100_000_000 + i * 10_000_000) for i in range(10)]      # 60M/h
    rows += [row(t0 + 5400 + 7200 + i * 600, 190_000_000 + i * 10_000_000)            # a 2 h break
             for i in range(10)]
    rows.append(row(rows[-1]["at"] + 600, 50_000_000))                                # a purchase
    rate = G.balance_rate(rows)
    assert rate is not None and abs(rate.per_hour - 60_000_000) < 1
    assert rate.spent == 230_000_000


def test_the_mask_waits_on_its_moon_charms_not_its_honey():
    # 2026-10-22 replay of runs 1138-1174: the headline said the Diamond Mask
    # was ~16 h of honey away while its moon charms (2.8/h, 2,364 short) were
    # ~35 days away; with N=24 h the keep rule keeps nothing for it
    from hivemind.brain import goals as g
    reads = [[0.0, {"moon_charm": 100, "glitter": 1}],
             [36_000.0, {"moon_charm": 80, "glitter": 3}],    # 20 spent: no rate from a fall
             [72_000.0, {"moon_charm": 136, "glitter": 3}]]   # +56 in 20 h = 2.8/h
    rates = g.material_rates(reads)
    assert abs(rates["moon_charm"] - 2.8) < 1e-9 and abs(rates["glitter"] - 0.1) < 1e-9
    data = {"goals": {"diamond_mask": {"label": "Diamond Mask", "honey": 5_000_000_000,
                                       "materials": {"glitter": 5}}}}
    plan = g.build(data, honey=1_160_000_000, rate=g.Rate(per_hour=240_000_000, hours=13.5, readings=9, since=0.0, until=1.0),
                   order=["diamond_mask"], held={"glitter": (3, "the inventory")},
                   rates=rates)
    class Crafting:
        goal, lacking, cannot = "Diamond Mask", {"moon_charm": 2_364}, []
    g.with_blender(plan, Crafting(), rates)
    row = plan.first_open()
    assert row.eta_slowest[1] == "moon charm" and 800 < row.eta_slowest[0] < 900
    assert "slowest: moon charm" in plan.headline() and "(honey 16.0 h)" in plan.headline()
    keep, why = g.keep_within(plan, Crafting(), jelly_honey=3_250_000_000, hours=24)
    assert keep == 0 and "slowest moon charm" in why and "jelly not kept" in why


def test_an_input_with_no_rate_keeps_the_price_and_says_why():
    # review 2026-10-22: the live mask had its moon charm unknown, and the
    # rule named the honey as its slowest; one quiet hour must not read as never
    from hivemind.brain import goals as g
    assert g.material_rates([[0.0, {"moon_charm": 5}], [3600.0, {"moon_charm": 5}]]) == {}
    assert g.material_rates([[0.0, {"moon_charm": 5}], [10_800.0, {"moon_charm": 5}],
                             [21_600.0, {"moon_charm": 5}]]) == {"moon_charm": 0.0}
    data = {"goals": {"diamond_mask": {"label": "Diamond Mask", "honey": 5_000_000_000,
                                       "materials": {"glitter": 5}}}}
    plan = g.build(data, honey=1_160_000_000, order=["diamond_mask"],
                   rate=g.Rate(per_hour=240_000_000, hours=13.5, readings=9, since=0.0, until=1.0),
                   held={"glitter": (3, "the inventory")}, rates={})
    keep, why = g.keep_within(plan)
    assert keep == 5_000_000_000 and "kept: rate unknown for" in why and "honey" not in why
    g.say_slowest(plan)
    assert plan.first_open().next_step.count("rate unknown") == 1


def test_the_inventory_keeps_its_last_reads_for_the_rates(tmp_path):
    from hivemind.act import inventory
    path = tmp_path / "inventory.json"
    for i in range(g_reads := 70):
        r = inventory.InventoryRead()
        r.ok, r.counts = True, {"moon_charm": i}
        inventory.write(path, r, {}, clock=lambda i=i: 1000.0 * i)
    from hivemind.brain.goals import READS_KEPT
    import json as _json
    reads = _json.loads(path.read_text())["reads"]
    assert len(reads) == READS_KEPT and reads[-1] == [1000.0 * (g_reads - 1), {"moon_charm": 69}]
