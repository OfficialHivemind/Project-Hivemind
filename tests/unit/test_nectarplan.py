"""N4 brain/nectarplan: the field nudge toward a low nectar's planter, and the
look-only vial pick."""
from types import SimpleNamespace as A

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
