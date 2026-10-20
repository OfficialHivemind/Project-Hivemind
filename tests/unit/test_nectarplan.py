"""N4 brain/nectarplan: the field nudge toward a low nectar's planter, and the
look-only vial pick."""
from types import SimpleNamespace as A

from hivemind.act import planter as pl
from hivemind.brain import nectarplan as np_
from hivemind.world import settings as schema

LOW = {"comforting": 20.0, "motivating": 0.0, "refreshing": None,
       "satisfying": 90.0, "invigorating": 50.0}
OUT = {"blue_clay_planter": {"field": "pine_tree"}}


def alts(**scores):
    return [A(field=f, score=s, reachable=True) for f, s in scores.items()]


def test_low_is_read_levels_under_their_minimum_furthest_first():
    # motivating 80 under, comforting 50 under; refreshing unread is never low
    assert np_.low(LOW) == ["motivating", "comforting"]


def test_a_trip_goes_to_the_low_nectars_planter_when_it_costs_little():
    got = np_.field_for(LOW, OUT, alts(pineapple=100, pine_tree=90), "pineapple")
    assert got[0] == "pine_tree" and "comforting" in got[1] and "10% less" in got[1]


def test_no_nudge_when_it_costs_too_much_or_no_planter_grows_it():
    assert np_.field_for(LOW, OUT, alts(pineapple=100, pine_tree=80), "pineapple") is None
    assert np_.field_for(LOW, {}, alts(pineapple=100, pine_tree=99), "pineapple") is None
    full = dict(LOW, comforting=75.0)
    assert np_.field_for(full, OUT, alts(pineapple=100, pine_tree=99), "pineapple") is None


def test_a_quest_field_or_the_planters_own_field_stays():
    quest = [A(field="pineapple", score=100, reachable=True, quest_first=True),
             A(field="pine_tree", score=99, reachable=True)]
    assert np_.field_for(LOW, OUT, quest, "pineapple") is None
    assert np_.field_for(LOW, OUT, alts(pine_tree=100, pineapple=99), "pine_tree") is None


def test_the_vial_is_only_a_spare_one_and_never_overfills():
    assert np_.vial_to_use(LOW, {}) is None
    got = np_.vial_to_use(LOW, {"motivating_vial": 2, "comforting_vial": 1})
    assert got[:2] == ("motivating", "motivating_vial")
    assert np_.vial_to_use({"comforting": 69.0}, {"comforting_vial": 1}) is not None
    assert np_.VIAL_LIVE is False            # look-only until a vial is captured


def test_the_switch_ships_off_and_is_on_the_features_page():
    assert schema.defaults()["nectar.keep_up"] is False
    badge = {k: b for _, k, _, _, b in schema.FEATURES}
    assert badge["nectar.keep_up"] == "needs measuring"
    assert schema.wired("nectar.keep_up")


# ---- N1-N3: every planter's row, and the 24 h plan --------------------------
REACH = set(pl.NECTAR)
ZERO = dict.fromkeys(pl.NECTAR_ORDER, 0.0)


def test_every_planter_has_a_row_in_every_field_and_the_bonus_goes_by_nectar_type():
    for key in pl.PLANTERS:
        for field in pl.NECTAR:
            bonus, growth, hours = pl.table_row(key, field)
            assert bonus >= 0.75 and growth >= 1.0 and 0 < hours <= pl.PLANTERS[key][1]
    # Blue Clay: x1.2 Comforting and Refreshing only (wiki), wherever it grows
    assert pl.table_row("blue_clay_planter", "dandelion")[0] == 1.2       # comforting
    assert pl.table_row("blue_clay_planter", "stump")[0] == 1.0           # motivating
    # growth by the field's blue share: Dandelion 10% blue -> x1.025, not x1.25
    assert abs(pl.table_row("blue_clay_planter", "dandelion")[1] - 1.025) < 1e-9
    assert abs(pl.table_row("blue_clay_planter", "pine_tree")[1] - 1.2125) < 1e-9
    # a named-field planter: Planter Of Plenty x1.5 in Stump only, every nectar x1.5
    assert pl.table_row("planter_of_plenty", "stump")[1:] == (1.5, 16 / 1.5)
    assert pl.table_row("planter_of_plenty", "rose") == (1.5, 1.0, 16.0)
    # the wiki says these two by grow time: Tacky "-25% grow time", Pesticide "7 Hours"
    assert abs(pl.table_row("tacky_planter", "clover")[2] - 6.0) < 1e-9
    assert abs(pl.table_row("pesticide_planter", "spider")[2] - 7.0) < 1e-9
    # a grown planter gives the same nectar wherever it grew
    assert pl.nectar_added("blue_clay_planter", "pine_tree") == \
        pl.nectar_added("blue_clay_planter", "dandelion")


def test_the_plan_puts_the_blue_clay_on_comforting_and_beats_the_best_rate_pick():
    held = {"paper_planter": 40, "ticket_planter": 1}
    owned = {"Blue Clay Planter", "Paper Planter", "Ticket Planter"}
    got = np_.plan({}, owned, held, dict(ZERO, comforting=60.0), REACH, 0.0)
    assert ("blue_clay_planter", "pine_tree") in got["place"]
    assert len(got["place"]) == 3 and len({pl.NECTAR[f] for _k, f in got["place"]}) == 3
    assert got["score"] >= got["greedy"] and "Blue Clay Planter in pine tree" in got["why"]


def test_the_plan_beats_todays_errand_over_three_days():
    # today: errand_target's field (the nectar furthest under its minimum) and
    # next_step's planter (the first held) -- it sent the Blue Clay to Stump
    owned = {"Blue Clay Planter", "Paper Planter", "Ticket Planter"}
    held = {"paper_planter": 40, "ticket_planter": 1}
    counts = {"blue_clay_planter": 1, "paper_planter": 40, "ticket_planter": 1}
    start = dict(ZERO, comforting=60.0)
    title = {k: row[0] for k, row in pl.PLANTERS.items()}

    def today(st, left, lv, t):
        have = {title[k] for k, c in left.items() if c > 0}
        target = pl.errand_target(st, have, lv, REACH - {b.get("field") for b in
                                                       (st.get("out") or {}).values()}, t)
        step = target and pl.next_step(st, target[0], have, t, levels=lv)
        return (step[1], target[0]) if step and step[0] == "place" else None

    queue = {}

    def planned(st, left, lv, t):
        if queue.get("t") != t or not queue.get("place"):
            have = {title[k] for k, c in left.items() if c > 0} & owned
            queue.update(t=t, place=list(np_.plan(st, have, held, lv, REACH, t)["place"]))
        return queue["place"].pop(0) if queue["place"] else None

    before, _ = np_.simulate({}, counts, start, REACH, 0.0, choose=today, hours=72)
    after, _ = np_.simulate({}, counts, start, REACH, 0.0, choose=planned, hours=72)
    assert after > 1.2 * before              # MEASURED by tools/planter_plan_sim.py: +42%


def test_the_plan_says_why_nothing_goes_out():
    lost = {"lost": {"paper_planter": {"field": "pine_tree"}}}
    got = np_.plan(lost, {"Paper Planter"}, {"paper_planter": 40}, ZERO, REACH, 0.0)
    assert got["place"] == []
    assert any("Paper Planter is lost in pine tree" in b for b in got["blocked"])
    assert "no planter is held" in got["blocked"]
    assert np_.plan({}, {"Paper Planter"}, {}, dict.fromkeys(ZERO), REACH, 0.0) is None
    assert np_.PLAN_LIVE is False            # look-only until its log is checked live


def test_a_nectar_held_at_all_is_worth_the_buffs_minimum():
    # wiki Nectar: min + (max - min) x (t/86400)^0.7 -- the first % is worth most
    one = np_.day_value({"comforting": 1.0}) - np_.day_value({"comforting": 0.0})
    more = np_.day_value({"comforting": 51.0}) - np_.day_value({"comforting": 50.0})
    assert one > 10 * more
    assert np_.day_value({"comforting": 150.0}) == np_.day_value({"comforting": 100.0})


def test_a_worn_field_is_charged_extra_so_the_slot_goes_to_a_fresh_one(monkeypatch):
    # Blue Clay on Comforting: Pine Tree (0.85 blue) 4.95 h, Bamboo (0.75) 5.05 h.
    # 0.08 h of wear leaves Pine Tree ahead at face value; charged
    # (1 + WEAR_PENALTY) times, it falls behind Bamboo.
    worn = {"degradation": {"pine_tree": {"hours": 0.08, "at": 0.0}}}

    def comforting():
        opts = np_._options(worn, ["blue_clay_planter"], ZERO, REACH, 0.0)
        return next(f for _r, _k, f, n in opts if n == "comforting")

    assert np_.WEAR_PENALTY > 0 and comforting() == "bamboo"
    monkeypatch.setattr(np_, "WEAR_PENALTY", 0.0)
    assert comforting() == "pine_tree"


def test_the_plan_says_why_no_planter_went_in_a_field():
    worn = {"degradation": {f: {"hours": 5.0, "at": 0.0}
                            for f in pl.NECTAR_FIELDS["motivating"]}}
    reach = REACH - set(pl.NECTAR_FIELDS["invigorating"])
    got = np_.plan(worn, {"Paper Planter"}, {"paper_planter": 40},
                   dict(ZERO, comforting=100.0), reach, 0.0)
    assert len(got["place"]) == 1 and got["blocked"] == []
    why = "\n".join(got["unplaced"])
    assert "no planter placed in pine tree because comforting is full (100%)" in why
    assert "the field is worn 5.0 h, so a planter there grows 5.0 h longer" in why
    assert "no planter placed for invigorating because none of its fields" in why
    placed = pl.NECTAR[got["place"][0][1]]
    assert all(placed not in line for line in got["unplaced"])
    # no slot free: the plan's "blocked" says so, not a line a nectar
    full = {"out": {k: {"field": f, "at": 0.0} for k, f in
                    (("blue_clay_planter", "stump"), ("ticket_planter", "pine_tree"),
                     ("plastic_planter", "clover"))}}
    assert np_.plan(full, {"Paper Planter"}, {"paper_planter": 40}, ZERO, REACH, 0.0)["unplaced"] == []
