"""G12(a): Settings > Spending's `economy.honey_keep` -- honey the buyer never
spends. The goal is bought only from above it, and so is everything after it."""
from __future__ import annotations

from hivemind.brain import buyer
from hivemind.brain import goals as g


class Floor:
    def __init__(self, keep):
        self.keep = keep

    def get(self, key, fallback=None):
        return self.keep if key == "economy.honey_keep" else fallback

    def bool(self, key):
        return False

    def int(self, key):
        return self.keep if key == "economy.honey_keep" else 0


class Judged:
    jelly_on = {"cobalt": 1}
    jelly_hits_for = ["diamond"]
    jelly_rolls = 266.0


def slot():
    return g.Row(key="hive_slot_35", label="Hive Slot (bee 35)", shop="mountain_top_shop",
                 shop_label="Mountain Top Shop", cost=200_000_000, state=g.READY)


def shop(honey, keep):
    return buyer.plan_purchases(g.Plan(rows=[slot()], honey=honey), judgement=Judged(),
                                honey=honey, settings=Floor(keep))


def test_no_floor_is_as_before():
    first, jelly = shop(300_000_000, 0).purchases
    assert first.can_buy and jelly.ready and jelly.count == 100


def test_the_goal_waits_until_its_price_is_above_the_floor():
    got = shop(300_000_000, 150_000_000)
    first, jelly = got.purchases
    assert not first.can_buy and "50,000,000 honey short" in first.blocked
    assert got.kept == 350_000_000 and not jelly.ready


def test_the_surplus_jelly_comes_only_from_above_goal_and_floor():
    got = shop(300_000_000, 50_000_000)
    first, jelly = got.purchases
    assert first.can_buy
    # 50M above slot + floor: 5 lots of 10 at 1M each
    assert jelly.ready and jelly.count == 50


def test_unset_or_broken_settings_mean_no_floor():
    assert buyer.honey_floor(None) == 0
    assert buyer.honey_floor(Floor(-5)) == 0
