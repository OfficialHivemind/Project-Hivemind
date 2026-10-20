"""The next hive slot as a goal, priced from the hive (brain/goals.with_next_slot)."""
from __future__ import annotations

from hivemind.brain import goals

SLOTS = {27: 7_750_000, 35: 209_117_953, 50: 2_169_203_229_760}


def data(order=("honey_mask", "hive_slot", "bubble_mask")):
    return {"default_order": list(order),
            "goals": {"honey_mask": {"label": "Honey Mask", "honey": 1},
                      "bubble_mask": {"label": "Bubble Mask", "honey": 1}}}


def test_the_slot_for_the_next_bee_takes_its_place_in_the_order():
    out = goals.with_next_slot(data(), 34, SLOTS)
    assert out["default_order"] == ["honey_mask", "hive_slot_35", "bubble_mask"]
    body = out["goals"]["hive_slot_35"]
    assert body["honey"] == 209_117_953 and body["shop"] == "mountain_top_shop"
    assert body["label"] == "Hive Slot (bee 35)" and body["materials"] == {}


def test_each_slot_is_its_own_goal_so_a_bought_one_does_not_hide_the_next():
    a = goals.with_next_slot(data(), 26, SLOTS)
    b = goals.with_next_slot(data(), 34, SLOTS)
    assert "hive_slot_27" in a["goals"] and "hive_slot_35" in b["goals"]
    assert "hive_slot_27" not in b["goals"]


def test_a_full_hive_or_no_count_has_no_slot_goal():
    for bees in (50, None, 0):
        out = goals.with_next_slot(data(), bees, SLOTS)
        assert out["default_order"] == ["honey_mask", "bubble_mask"]
        assert not any(k.startswith("hive_slot") for k in out["goals"])


def test_an_order_without_the_slot_is_left_alone():
    d = data(order=("honey_mask", "bubble_mask"))
    assert goals.with_next_slot(d, 34, SLOTS) is d


def test_the_shipped_file_puts_the_bubble_mask_ahead_of_the_slot():
    # the owner, 2026-10-06: "i want bubble mask then diamond mask or whatever
    # blue hive guide says" (it was the slot first since 2026-10-01)
    order = goals.load()["default_order"]
    assert order.index("bubble_mask") < order.index("hive_slot<=42")
    assert order.index("hive_slot<=42") < order.index("diamond_mask")
    plan = goals.build(goals.with_next_slot(goals.load(), 39), honey=51_392_864)
    keys = [r.key for r in plan.rows]
    assert "hive_slot_40" in keys and "diamond_mask" in keys
    assert keys.index("bubble_mask") < keys.index("hive_slot_40") < keys.index("diamond_mask")
    assert plan.row("hive_slot_40").cost == 894_566_712


def test_a_slot_entry_with_a_cap_stands_aside_past_it_so_gear_comes_between():
    # the guides' order (docs/pending/blue_progression_research.md): slots to 42,
    # the Cobalt Guard, the Diamond Mask, then slots to 45, then the rest
    order = ("bubble_mask", "hive_slot<=42", "cobalt_guard", "diamond_mask",
             "hive_slot<=45", "crimson_guard", "hive_slot")
    slots = {40: 894_566_712, 43: 4_554_611_273, 46: 30_000_000_000}
    d = {"default_order": list(order), "goals": {}}
    assert goals.with_next_slot(d, 39, slots)["default_order"] == [
        "bubble_mask", "hive_slot_40", "cobalt_guard", "diamond_mask", "crimson_guard"]
    assert goals.with_next_slot(d, 42, slots)["default_order"] == [
        "bubble_mask", "cobalt_guard", "diamond_mask", "hive_slot_43", "crimson_guard"]
    assert goals.with_next_slot(d, 45, slots)["default_order"] == [
        "bubble_mask", "cobalt_guard", "diamond_mask", "crimson_guard", "hive_slot_46"]


def test_a_mythic_egg_is_hatched_only_with_its_setting_on():
    # research 2026-10-21: nothing uses a Mythic Egg; the owner left it to the research
    from hivemind.brain import goals as G

    class S:
        def __init__(self, on): self.on = on
        def get(self, key, default=None):
            return {"eggs.hatch_mythic": self.on, "eggs.save_diamond": True}.get(key, default)
    held = {"mythic_egg": 1, "basic_egg": 1}
    assert not G.egg_may_hatch("Mythic Egg", S(False))
    assert G.egg_may_hatch("Mythic Egg", S(True))
    assert G.slot_egg_held(held, S(False))[0] == "basic_egg"
    assert G.slot_egg_held(held, S(True)) == G.MYTHIC_EGG
    assert not G.egg_may_hatch("Star Egg", S(True))          # Star Eggs stay saved
