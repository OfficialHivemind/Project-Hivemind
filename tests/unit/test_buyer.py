"""What to buy next (brain/buyer): the owner's goal order first, Royal Jelly
from the honey above it, nothing the playbook calls a trap, and an honest
"needs a look" for every shop the bot has not bought at."""
from __future__ import annotations

from hivemind.brain import buyer
from hivemind.brain import goals as g


def plan(rows, honey):
    return g.Plan(rows=rows, honey=honey)


def slot(state=g.READY):
    return g.Row(key="hive_slot_35", label="Hive Slot (bee 35)", shop="mountain_top_shop",
                 shop_label="Mountain Top Shop", cost=209_117_953, state=state)


def mask(oil=16):
    return g.Row(key="bubble_mask", label="Bubble Mask", shop="blue_hq",
                 shop_label="Blue HQ", cost=100_000_000, state=g.HONEY_READY,
                 needs=[g.Need("oil", "Oil", 25, have=oil)])


class Judged:
    jelly_on = {"cobalt": 1, "crimson": 1, "demon": 1, "riley": 1}
    jelly_hits_for = ["diamond", "tadpole", "buoyant"]
    jelly_rolls = 266.0


def test_tonight_the_hive_slot_is_next_and_the_surplus_goes_to_jelly():
    # an example: 325,000,000 honey, the Hive Slot next in the order
    got = buyer.plan_purchases(plan([slot(), mask()], 325_000_000), judgement=Judged())
    first, jelly = got.purchases
    # the owner, 2026-10-02: honey and tickets are the bot's to spend, and
    # scripts/run_farm buys the next Hive Slot itself (mts_buy_due)
    assert first.key == "hive_slot_35" and first.ready and first.can_buy
    assert first.blocked == ""
    assert got.kept == 209_117_953 and got.kept_for == "Hive Slot (bee 35)"
    # 116M above the slot's honey: 11 lots of 10 at the cap, at most 100 a visit
    assert jelly.key == "royal_jelly" and jelly.count == 100 and jelly.ready
    assert jelly.honey == 100 * buyer.JELLY_PRICE_PLANNED
    assert "Cobalt" in jelly.why and "Diamond" in jelly.why
    text = "\n".join(got.lines())
    assert "209,117,953 of it kept for the Hive Slot" in text
    assert "buying 1: Hive Slot (bee 35) at the Mountain Top Shop" in text


def test_a_goal_short_of_materials_says_which():
    got = buyer.plan_purchases(plan([mask(oil=16)], 150_000_000), judgement=None)
    (p,) = got.purchases
    assert not p.ready and "Oil 16/25" in p.blocked


def test_saving_for_the_goal_leaves_no_honey_for_jelly():
    got = buyer.plan_purchases(plan([slot(g.SAVING)], 150_000_000), judgement=Judged())
    first, jelly = got.purchases
    assert "59,117,953 honey short" in first.blocked
    assert not jelly.ready and "above what the Hive Slot (bee 35) keeps" in jelly.blocked


def test_no_cell_to_jelly_means_no_jelly():
    class Nothing(Judged):
        jelly_on = {}
    got = buyer.plan_purchases(plan([slot()], 325_000_000), judgement=Nothing())
    assert [p.key for p in got.purchases] == ["hive_slot_35"]


def test_a_trap_is_never_planned_even_if_a_goal_names_it():
    egg = g.Row(key="diamond_egg", label="Diamond Egg", cost=0, state=g.READY)
    got = buyer.plan_purchases(plan([egg], 1_000_000_000))
    assert got.purchases == []


def test_only_what_the_bot_has_a_flow_for_is_its_to_buy():
    # the Hive Slot at the Mountain Top Shop, every Ticket Tent purchase --
    # not the Porcelain Dipper at the same shop, not the jelly (no route yet)
    assert buyer.bot_buys("mountain_top_shop", "hive_slot_35")
    assert not buyer.bot_buys("mountain_top_shop", "porcelain_dipper")
    assert buyer.bot_buys("ticket_tent", "festive_bee_egg")
    assert not buyer.bot_buys(buyer.JELLY_SHOP, "royal_jelly")
    dipper = g.Row(key="porcelain_dipper", label="Porcelain Dipper", shop="mountain_top_shop",
                   shop_label="Mountain Top Shop", cost=150_000_000, state=g.READY)
    got = buyer.plan_purchases(plan([dipper], 325_000_000))
    assert not got.purchases[0].can_buy and "yours to buy" in got.purchases[0].blocked


def test_the_tent_purchase_is_planned_with_tickets():
    from hivemind.brain import buyer
    shop = buyer.plan_purchases(None, tickets=507)
    tent = [p for p in shop.purchases if p.shop == buyer.TENT_SHOP]
    assert tent and tent[0].label == "Festive Bee Egg" and tent[0].tickets == 500
    assert tent[0].ready and tent[0].can_buy and "500 tickets" in tent[0].describe()
    short = buyer.plan_purchases(None, tickets=300).purchases[-1]
    assert not short.ready and "200 tickets short" in short.describe()
    assert not [p for p in buyer.plan_purchases(None, tickets=507, bought={"Festive Bee Egg"}).purchases
                if p.shop == buyer.TENT_SHOP]


def test_a_slot_that_waits_for_an_egg_is_not_bought_and_says_why():
    row = slot()
    row.waits = "no egg is held to fill slot 36, so it would stand empty"
    first = buyer.plan_purchases(plan([row], 399_415_303)).purchases[0]
    assert first.ready and not first.can_buy and first.blocked == row.waits
    assert "buying it" not in first.describe()
    assert not row.card_due


def test_the_blue_clay_planter_waits_for_its_beans_beside_the_goals():
    # the owner, 2026-10-06: the best planter should be done too; it
    # waits on Magic Beans without holding the next goal back
    held = {"magic_bean": 0, "blue_extract": 50, "soft_wax": 30}
    got = buyer.plan_purchases(plan([slot(g.SAVING)], 650_000_000), held=held)
    assert got.first().key == "hive_slot_35"
    (planter,) = [p for p in got.purchases if p.key == "blue_clay_planter"]
    assert not planter.can_buy and "5 magic bean" in planter.blocked
    held["magic_bean"] = 5
    got = buyer.plan_purchases(plan([slot(g.SAVING)], 650_000_000), held=held)
    (planter,) = [p for p in got.purchases if p.key == "blue_clay_planter"]
    assert planter.ready and planter.can_buy and planter.shop == "blue_hq"
    # cheap beside a big goal (10M of 209M kept), it comes out of what it keeps;
    # beside the 100M mask it waits for honey above that
    got = buyer.plan_purchases(plan([slot(g.SAVING)], 150_000_000), held=held)
    (planter,) = [p for p in got.purchases if p.key == "blue_clay_planter"]
    assert planter.ready and planter.can_buy
    got = buyer.plan_purchases(plan([mask(oil=25)], 105_000_000), held=held)
    (planter,) = [p for p in got.purchases if p.key == "blue_clay_planter"]
    assert not planter.ready and "above what the Bubble Mask keeps" in planter.blocked
    # bought once, never again; and nothing said before the inventory is counted
    assert not [p for p in buyer.plan_purchases(plan([slot()], 650_000_000), held=held,
                                                bought={"Blue Clay Planter"}).purchases
                if p.key == "blue_clay_planter"]
    assert not [p for p in buyer.plan_purchases(plan([slot()], 650_000_000)).purchases
                if p.key == "blue_clay_planter"]



def test_the_plastic_planter_says_it_waits_for_its_counter_survey(tmp_path):
    # MEASURED run-1174: "Plastic Planter ... buying it" while run_farm said
    # its counter's way had not read "Open Shop"
    import json as _json
    held = {"magic_bean": 9, "blue_extract": 50, "soft_wax": 30}
    assert buyer.unsurveyed(tmp_path) == {"dapper_bear_shop"}
    got = buyer.plan_purchases(plan([slot(g.SAVING)], 650_000_000), held=held,
                               unreached=buyer.unsurveyed(tmp_path))
    (planter,) = [p for p in got.purchases if p.key == "plastic_planter"]
    assert planter.ready and not planter.can_buy and "Open Shop" in planter.describe()
    (tmp_path / "shoplook.json").write_text(_json.dumps({"looks": [
        {"shop": "dapper_shop_look_from_stump", "ok": True, "reads": ["Open Shop"]},
        {"shop": "dapper_shop_stairs_onto", "ok": True, "reads": ["Open Shop"]}]}))
    assert buyer.unsurveyed(tmp_path) == {"dapper_bear_shop"}   # not run_farm's survey read
    (tmp_path / "shoplook.json").write_text(_json.dumps({"looks": [
        {"shop": "dapper_shop_stairs_onto", "ok": True, "reads": ["leg3-0: Open Shop"]}]}))
    assert buyer.unsurveyed(tmp_path) == set()
    # the same survey key run_farm buys by (its last DAPPER_SHOP_SURVEY)
    import re
    from pathlib import Path
    import hivemind
    farm = (Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py"
            ).read_text(encoding="utf-8")
    assert re.findall(r'^DAPPER_SHOP_SURVEY = "(\w+)"', farm, re.M)[-1] == \
        buyer.NEEDS_SURVEY["dapper_bear_shop"]

# ---- Settings > Spending (the owner, 2026-10-21: options, all off by default)
class Spend:
    def __init__(self, **on):
        self.on = {"economy.tickets.keep": 100, **on}

    def get(self, key, fallback=None):
        return self.on.get(key, fallback)

    def bool(self, key):
        return bool(self.on.get(key, False))

    def int(self, key):
        return int(self.on.get(key, 0))


def diamond_mask():
    return g.Row(key="diamond_mask", label="Diamond Mask", shop="diamond_room",
                 cost=5_000_000_000, state=g.SAVING,
                 needs=[g.Need("diamond_egg", "Diamond Egg", 5, have=2)])


def test_no_ticket_spend_unless_switched_on():
    got = buyer.plan_purchases(plan([diamond_mask()], 0), tickets=2_000,
                               held={"diamond_egg": 2, "magic_bean": 0}, settings=Spend())
    assert not [p for p in got.purchases if p.key in ("diamond_egg", "magic_bean")]
    # and no settings at all (the GUI's older callers): none either
    got = buyer.plan_purchases(plan([diamond_mask()], 0), tickets=2_000, held={"diamond_egg": 2})
    assert not [p for p in got.purchases if p.key == "diamond_egg"]


def test_diamond_eggs_only_for_the_goal_short_of_them_above_the_keep():
    on = Spend(**{"economy.tickets.diamond_eggs": True})
    # 2026-10-21: 170 tickets, 2 of the Mask's 5 held -- 330 short of one above the 100 kept
    (egg,) = buyer.ticket_purchases(plan([diamond_mask()], 0), 170, {"diamond_egg": 2}, on)
    assert not egg.can_buy and "330 tickets short" in egg.blocked
    (egg,) = buyer.ticket_purchases(plan([diamond_mask()], 0), 1_000, {"diamond_egg": 2}, on)
    assert egg.can_buy and egg.count == 2 and egg.label == "Diamond Egg"
    assert egg.shop == buyer.TENT_SHOP and "never hatched" in egg.why
    # never more than the goal takes, and none once held or owned
    (egg,) = buyer.ticket_purchases(plan([diamond_mask()], 0), 9_000, {"diamond_egg": 2}, on)
    assert egg.count == 3
    assert buyer.ticket_purchases(plan([diamond_mask()], 0), 9_000, {"diamond_egg": 5}, on) == []
    owned = diamond_mask()
    owned.owned = True
    assert buyer.ticket_purchases(plan([owned], 0), 9_000, {"diamond_egg": 0}, on) == []


def test_a_bought_diamond_egg_is_never_hatched_while_the_option_is_on():
    on = Spend(**{"economy.tickets.diamond_eggs": True, "eggs.save_diamond": False})
    assert g.diamond_saved(on)
    assert not g.egg_may_hatch("Diamond Egg", on)
    assert g.slot_egg_held({"diamond_egg": 3}, on) is None


def test_magic_beans_are_look_only():
    on = Spend(**{"economy.tickets.magic_beans": True})
    (bean,) = buyer.ticket_purchases(plan([], 0), 500, {"magic_bean": 0}, on,
                                     bought=("Blue Clay Planter",))
    assert bean.ready and not bean.can_buy and bean.count == 3
    assert "look-only" in bean.blocked and "60 tickets" in bean.blocked


def test_magic_beans_for_the_blender_when_no_planter_waits_on_them():
    class Crafting:
        lacking, goal = {"magic_bean": 94}, "Diamond Mask"
    on = Spend(**{"economy.tickets.magic_beans": True})
    (bean,) = buyer.ticket_purchases(plan([], 0), 170, {"magic_bean": 3}, on,
                                     bought=("Blue Clay Planter",), crafting=Crafting())
    assert bean.count == 3 and "Blender's crafts for the Diamond Mask (94 short)" in bean.why
    assert not bean.can_buy
