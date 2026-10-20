"""brain/questvalue: open quest steps priced from data/knowledge/quest_rewards.yaml
(ROADMAP B20). MEASURED 2026-10-21 on the live menu: Variety Fetcher 2 (>=136M)
first, Polar Bear's Scorpion Salad (160k) near the bottom."""
from __future__ import annotations

from hivemind.brain import questvalue as qv

TABLE = {qv._key("Scorpion Salad"): ("polar_bear", {"honey": 160000, "treat": 10,
                                                   "items": {"Polar Power": 1}}),
         qv._key("Variety Fetcher 2"): ("black_bear", {"honey": 125000000, "tickets": 5,
                                                      "royal_jelly": 10,
                                                      "items": {"Magic Bean": 1}})}


def test_steps_share_the_reward_by_work_left_and_rank_by_honey():
    menu = [{"name": "Polar Bear: Scorpion Salad",
             "requirements": ["Collect 300,000 Pollen from the Rose Field. Complete!",
                              "Defeat 12 Scorpions. 2/12"]},
            {"name": "Variety Fetcher 2",
             "requirements": ["Collect 100,000,000 Pollen from the Pepper Patch. 0/100,000,000",
                              "Collect 100,000,000 Pollen from the Pineapple Patch. Complete!"]},
            {"name": "Some New Quest", "requirements": ["Do a thing. 0/5"]}]
    rows = qv.ranked(menu, TABLE)
    # Polar Power is PRICED (ITEM_PRICES, research 2026-10-21), not ranked first:
    # 160k + 5M per stack still sits under Variety Fetcher's 136M
    assert [r.name for r in rows] == ["Variety Fetcher 2", "Polar Bear: Scorpion Salad",
                                      "Some New Quest"]
    vf = rows[0]
    assert vf.honey == 125e6 + 5 * 1e5 + 10 * 1e6 and "1 Magic Bean" in vf.unpriced
    assert len(vf.steps) == 1 and vf.steps[0].honey == vf.honey      # the only open step
    salad = rows[1]
    assert abs(salad.steps[0].left - 10 / 12) < 1e-9 and salad.steps[0].honey == 160000 + qv.ITEM_PRICES["Polar Power"]
    assert rows[2].honey is None and rows[2].describe().endswith("not on file")


def test_on_accept_items_are_not_counted_as_the_hand_in_reward():
    honey, unpriced = qv.priced({"honey": 1, "items": {"Glitter (on accept)": 2, "Glitter": 2}})
    assert honey == 1 and unpriced == ["2 Glitter"]


def test_the_shipped_table_loads():
    table = qv.load()
    assert len(table) > 250 and qv._key("Pleasant Pastimes") in table


def test_a_quest_field_earns_its_steps_honey_per_pollen_in_the_shadow_rank():
    from types import SimpleNamespace as N
    rows = [qv.QuestValue("VF2", "black_bear", 100e6, [], [qv.StepValue(
        "Collect 100,000,000 Pollen from the Pepper Patch. 0/100,000,000", 1.0, 100e6)])]
    bonus = qv.field_bonus(rows)
    assert bonus == {"pepper": (1.0, 100_000_000)}
    alts = [N(field="pine_tree", score=30000, rate=30000, reachable=True),
            N(field="pepper", score=20000, rate=20000, reachable=True),
            N(field="cactus", score=50000, rate=50000, reachable=False)]
    ranked = qv.shadow_rank(alts, bonus, capacity=10e6, hpp=1.7)
    assert [r[0] for r in ranked] == ["pepper", "pine_tree"]       # unreachable left out
    assert abs(ranked[0][2] - 20000.0) < 1e-6                      # 10M x 1.0 over 500 s


def _alts(rows):
    from types import SimpleNamespace as N
    return [N(field=f, score=s, rate=r, reachable=True) for f, s, r in rows]


def test_the_20_22_oct_quest_trips_cost_more_than_they_paid():
    """MEASURED var/trips.jsonl: the candidates (score, rate) and capacity the
    planner had for quests.first trips 20 Oct 16:35 (Strawberry), 21 Oct 21:26
    (Pepper), 22 Oct 03:02 (Stump); the menu lines from run-1115/1166/1180.
    hpp 1.3: those Strawberry trips made 1.18 and 1.44 honey a pollen."""
    table = qv.load()
    vf2 = {"name": "Variety Fetcher 2", "requirements": [
        "Collect 100,000,000 Pollen from the Pepper Patch. 0/100,000,000",
        "Collect 100,000,000 Pollen from the Pineapple Patch. Complete!",
        "Collect 100,000,000 Pollen from the Strawberry Field. 19,954,816/100,000,000"]}
    straw = qv.quest_trip(_alts([("strawberry", 2290.6, 5406.3), ("pine_tree", 14802.7, 25573.3),
                                 ("pumpkin", 6363.5, 13305.3)]),
                          "strawberry", qv.ranked([vf2], table), 8642025, 1.3)
    assert straw["best"] == "pine_tree" and straw["quest"] == ["Variety Fetcher 2"]
    assert straw["cost"] > 3 * straw["value"]            # ~26M lost for ~6.5M of quest
    assert 14_000 < straw["pays_at"] < 15_500            # vs 5,406/s measured

    vf2_pepper = {"name": "Variety Fetcher 2", "requirements": [
        "Collect 100,000,000 Pollen from the Pepper Patch. 0/100,000,000",
        "Collect 100,000,000 Pollen from the Pineapple Patch. Complete!",
        "Collect 100,000,000 Pollen from the Strawberry Field. Complete!"]}
    pepper = qv.quest_trip(_alts([("pepper", 3292.8, 6773.5), ("pine_tree", 29647.3, 52758.4),
                                  ("rose", 5082.1, 7317.8)]),
                           "pepper", qv.ranked([vf2_pepper], table), 8727469, 1.3)
    assert pepper["best"] == "pine_tree" and pepper["cost"] > pepper["value"]

    stumped = {"name": "Getting Stumped", "requirements": [
        "Collect 500,000,000 Pollen. 1,319,142/500,000,000",
        "Collect 300,000,000 Pollen from the Stump Field. 0/300,000,000"]}
    stump = qv.quest_trip(_alts([("stump", 1736.2, 3201.2), ("mountain_top", 21570.8, 38491.3),
                                 ("pine_tree", 17870.2, 33938.4)]),
                          "stump", qv.ranked([stumped], table), 10560237, 1.3)
    assert stump["best"] == "mountain_top" and stump["cost"] > 10 * stump["value"]


def test_a_quest_trip_that_pays_or_no_quest_field_is_left_alone():
    rows = [qv.QuestValue("Q", "black_bear", 100e6, [], [qv.StepValue(
        "Collect 10,000,000 Pollen from the Rose Field. 0/10,000,000", 1.0, 100e6)])]
    alts = _alts([("rose", 5000, 7000), ("pine_tree", 20000, 30000)])
    assert qv.quest_trip(alts, "rose", rows, 8e6, 1.3) is None      # 10 honey a pollen pays
    assert qv.quest_trip(alts, "pine_tree", rows, 8e6, 1.3) is None  # not a quest field
    assert qv.QUEST_TRIP_LIVE is False                               # shadow until checked
