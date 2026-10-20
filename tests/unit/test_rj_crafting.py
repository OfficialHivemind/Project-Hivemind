"""Royal Jelly for the Blender (act/blender.crafting, brain/buyer): the jelly
the next goal's short materials take, bought before the rolls' jelly and from
the honey above the goal's own price. THE OWNER, 2026-10-13: the bot must learn
it one day, as jelly is used for crafting too. Numbers shaped like a
var/inventory.json read on the test account."""
from __future__ import annotations

from hivemind.act import blender
from hivemind.act.feed import item_of
from hivemind.brain import buyer
from hivemind.brain import goals as g

LABELS = {"sunflower_seed": "Sunflower Seed", "royal_jelly": "Royal Jelly",
          "pineapple": "Pineapple", "gumdrops": "Gumdrops"}
HELD = {"royal_jelly": 89, "pineapple": 6810, "sunflower_seed": 1935, "gumdrops": 17}


def _need(material, label, gives, need, have):
    return g.Need(material, label, need, have=have,
                  sources=[{"kind": "drop"}, {"kind": "blender", "gives": gives}])


def belt():
    return g.Row(key="honeycomb_belt", label="Honeycomb Belt", shop="ace_shop",
                 shop_label="Ace Shop", cost=75_000_000, state=g.HONEY_READY, needs=[
                     _need("enzymes", "Enzymes", "50 Pineapples + 10 Royal Jelly", 50, 5),
                     _need("glue", "Glue", "50 Gumdrops + 10 Royal Jelly", 50, None),
                     _need("oil", "Oil", "50 Sunflower Seeds + 10 Royal Jelly, 5 minutes", 25, 7)])


def _jelly(got):
    return [p for p in got.purchases if p.shop == buyer.JELLY_SHOP]


class Judged:
    jelly_on = {"basic": 1}
    jelly_hits_for = ["diamond"]
    jelly_rolls = 266.0


def test_the_belts_crafts_take_1130_jelly_and_the_glue_waits_on_gumdrops():
    got = blender.crafting([belt()], HELD, LABELS, item_of)
    assert got.goal == "Honeycomb Belt" and got.jelly == 1130     # (45 + 50 + 18) x 10
    assert got.lacking == {"gumdrops": 2483}
    # what the rolls leave (run_farm jelly_keep) is all of it: 89 <= 1,130, no roll
    assert HELD["royal_jelly"] <= got.jelly


def test_the_blenders_jelly_is_bought_first_and_kept_with_the_goal():
    plan = g.Plan(rows=[belt()], honey=2_300_000_000)
    got = buyer.plan_purchases(plan, judgement=Judged(), held=HELD,
                               crafting=blender.crafting(plan.rows, HELD, LABELS, item_of))
    craft, rolls = _jelly(got)
    assert craft.count == 100 and craft.ready and not craft.can_buy     # no buy flow yet
    assert "1,050 to buy" in craft.why and "Honeycomb Belt" in craft.why
    assert craft.blocked == buyer.JELLY_NO_FLOW
    assert got.kept == 75_000_000 + 1050 * buyer.JELLY_PRICE_PLANNED
    assert not rolls.ready and "come first" in rolls.blocked


def test_the_goals_own_price_stays_reachable():
    plan = g.Plan(rows=[belt()], honey=80_000_000)       # 5M above the belt's 75M
    got = buyer.plan_purchases(plan, held=HELD,
                               crafting=blender.crafting(plan.rows, HELD, LABELS, item_of))
    (craft,) = _jelly(got)
    assert not craft.ready and "5,000,000 honey above what the Honeycomb Belt keeps" in craft.blocked


def test_with_the_jelly_held_the_rolls_buy_again():
    held = dict(HELD, royal_jelly=1130)
    plan = g.Plan(rows=[belt()], honey=2_300_000_000)
    got = buyer.plan_purchases(plan, judgement=Judged(), held=held,
                               crafting=blender.crafting(plan.rows, held, LABELS, item_of))
    (rolls,) = _jelly(got)
    assert rolls.ready and rolls.count == 100 and got.kept == 75_000_000


def test_below_the_goals_price_the_jelly_is_never_a_negative_count():
    # Simple mode once read "Royal Jelly READY · WAITS · -70M honey"
    plan = g.Plan(rows=[belt()], honey=60_000_000)       # 15M below the belt
    got = buyer.plan_purchases(plan, held=HELD,
                               crafting=blender.crafting(plan.rows, HELD, LABELS, item_of))
    (craft,) = _jelly(got)
    assert craft.count > 0 and craft.honey > 0 and not craft.ready
