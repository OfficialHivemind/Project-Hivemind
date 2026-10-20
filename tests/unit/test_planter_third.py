"""The third planter (2026-10-12): every planter held goes out at once -- one
of each kind, three at most (wiki Planters) -- and the Plastic Planter is
bought for the third slot once its Magic Beans are held (brain/buyer)."""
from __future__ import annotations

from hivemind.act import planter as p
from hivemind.brain import buyer
from hivemind.brain import goals as g

H = 3600.0
# the nectar every trip ran under before (research 2026-10-12: under 4%)
LOW = dict.fromkeys(p.NECTAR_ORDER, 0.0)
REACH = {f for fs in p.NECTAR_FIELDS.values() for f in fs}
HELD = {"Blue Clay Planter", "Paper Planter", "Ticket Planter"}


def test_every_held_planter_goes_out_one_of_each_kind_three_at_most():
    state, fields = {}, []
    for _ in range(4):                      # the errand round: harvests, then places
        target = p.errand_target(state, HELD, LOW, REACH - set(fields), 0.0)
        if target is None:
            break
        what, key = p.next_step(state, target[0], HELD, 0.0, levels=LOW)
        assert what == "place"
        state = p.placed(state, key, target[0], 0.0)
        fields.append(target[0])
    # the reusable first, the single-use last; three nectars, none twice
    assert list(state["out"]) == ["blue_clay_planter", "paper_planter", "ticket_planter"]
    assert len({p.NECTAR[f] for f in fields}) == 3


def test_every_nectar_at_its_minimum_still_takes_a_held_planter_the_lowest():
    # Natro's stage 2: a planter does not idle in the bag above the minimums
    levels = {"comforting": 75.0, "motivating": 85.0, "refreshing": 81.0,
              "satisfying": 90.0, "invigorating": 45.0}
    field, why = p.errand_target({}, {"Paper Planter"}, levels, REACH, 0.0)
    assert p.NECTAR[field] == "invigorating" and "the lowest" in why
    assert p.errand_target({}, {"Paper Planter"}, dict.fromkeys(levels, 100.0), REACH, 0.0) is None


def test_the_ticket_and_plastic_planters_go_by_natros_rows():
    # natro_macro.ahk <Field>Planters: Ticket (2, 1, 2 h), Plastic (1, 1, 2 h) everywhere
    assert abs(p.nectar_added("ticket_planter", "pine_tree") - 2 * H * 2.0 / 864) < 1e-9
    assert abs(p.nectar_added("plastic_planter", "rose") - 2 * H * 1.0 / 864) < 1e-9
    assert p.grow_s("ticket_planter", "clover") == p.grow_s("plastic_planter", "clover") == 2 * H


def test_a_planter_the_inventory_counts_in_the_bag_is_neither_out_nor_lost():
    # var/planters.json 2026-10-12 20:20: out in Pine Tree since 16:43 (the place
    # said Yes), lost in Rose since 10-11 22:46; the 20:01 read: "Blue Clay Planter 1/1"
    state = {"out": {"blue_clay_planter": {"field": "pine_tree", "at": 1791794598.6,
                                           "misses": 0, "grow": 39260.2}},
             "lost": {"blue_clay_planter": {"field": "rose", "at": 1791679419.7,
                                            "lost_at": 1791728816.1}}}
    fixed = p.reconcile(state, {"blue_clay_planter": 1}, 1791806505.4)
    assert not fixed["out"] and not fixed["lost"]
    assert p.errand_target(fixed, {"Blue Clay Planter"}, LOW, REACH, 1791806600.0) is not None
    # recorded after the read, or not counted: left as it is
    assert p.reconcile(state, {"blue_clay_planter": 1}, 1791700000.0) == state
    assert p.reconcile(state, {}, 1791806505.4) == state
    # a single-use one held says nothing of the one out
    paper = p.placed({}, "paper_planter", "pumpkin", 0.0)
    assert p.reconcile(paper, {"paper_planter": 5}, 10.0) == paper


def test_a_lost_planter_placed_or_harvested_again_is_not_lost():
    lost = {"lost": {"blue_clay_planter": {"field": "rose", "lost_at": 1.0}}}
    assert not p.placed(lost, "blue_clay_planter", "pine_tree", 2.0)["lost"]
    out = dict(lost, out={"blue_clay_planter": {"field": "pine_tree", "at": 0.0}})
    assert not p.harvested(out, "blue_clay_planter", 5 * H)["lost"]


def test_the_plastic_planter_waits_for_its_beans_and_spares_the_hive_slot():
    # 2026-10-12 20:00: 1,057,101,844 honey, 30 Soft Wax, no Magic Bean listed;
    # Hive Slot 42 keeps 2,375,844,017
    goal = g.Row(key="hive_slot_42", label="Hive Slot (bee 42)", shop="mountain_top_shop",
                 shop_label="Mountain Top Shop", cost=2_375_844_017, state=g.SAVING)
    held = {"soft_wax": 30}

    def plastic(**kw):
        got = buyer.plan_purchases(g.Plan(rows=[goal], honey=1_057_101_844), held=held, **kw)
        return [x for x in got.purchases if x.key == "plastic_planter"]
    (row,) = plastic()
    assert row.shop == "dapper_bear_shop" and not row.can_buy and "3 magic bean" in row.blocked
    held["magic_bean"] = 3
    (row,) = plastic()
    # 750,000 is under SIDE_FROM_KEPT_SHARE of the slot's honey: it may come out of it
    assert row.ready and row.can_buy and row.honey == 750_000
    assert not plastic(bought={"Plastic Planter"})


def test_one_planter_goes_to_pine_tree_while_under_two_whirligigs():
    # comforting over its minimum (not so full a planter there is harvested
    # early): the nectar choice alone would not pick Pine Tree
    levels = dict(LOW, comforting=85.0)
    assert p.errand_target({}, HELD, levels, REACH, 0.0)[0] != "pine_tree"
    assert p.errand_target({}, HELD, levels, REACH, 0.0, whirligigs=2)[0] != "pine_tree"
    field, why = p.errand_target({}, HELD, levels, REACH, 0.0, whirligigs=0)
    assert field == "pine_tree" and "Whirligigs 0" in why and "rejoin" in why
    # only one slot: with a planter out in Pine Tree the nectar goals take the rest
    state = p.placed({}, "blue_clay_planter", "pine_tree", 0.0)
    assert p.errand_target(state, HELD, levels, REACH, 0.0, whirligigs=1)[0] != "pine_tree"
    # Pine Tree out of reach: no redirect
    assert p.errand_target({}, HELD, levels, REACH - {"pine_tree"}, 0.0, whirligigs=0)[0] != "pine_tree"
