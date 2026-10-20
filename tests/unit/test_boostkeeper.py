"""B19, the boost keeper: its decisions from synthetic boost reads."""
import importlib.util
import pathlib

import hivemind

_path = pathlib.Path(hivemind.__file__).resolve().parent / "brain" / "boostkeeper.py"
_spec = importlib.util.spec_from_file_location("boostkeeper_under_test", _path)
bk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bk)

NOW = 10_000.0
BOOSTERS = {"blue_field_booster": ("pine_tree", "bamboo", "blue_flower")}


def box(left, field="pine_tree", stacks=2):
    return {"at": NOW - (bk.BOOST_SECONDS - left), "field": field, "stacks": stacks}


def due(left, *, on=True, spare=None, ready=None, trip=300.0):
    return bk.due(on=on, field="pine_tree", boosts=bk.left_of(box(left), NOW),
                  trip_seconds=trip, spare=spare or {}, boosters_ready=ready or {})


def test_refreshes_before_the_boost_runs_out_mid_trip():
    acts = due(40.0, spare={"glitter": 3})
    assert acts == [("glitter", "Glitter on pine tree (boost 40 s left)")]


def test_nothing_while_the_boost_lasts_the_trip():
    assert due(800.0, spare={"glitter": 3}, ready=BOOSTERS) == []


def test_nothing_when_no_items_are_held():
    assert due(40.0, spare={"glitter": 0, "field_dice": 0}) == []


def test_booster_first_and_only_when_off_cooldown_and_it_boosts_the_field():
    acts = due(40.0, spare={"glitter": 1}, ready=BOOSTERS)
    assert [a for a, _ in acts] == ["blue_field_booster", "glitter"]
    # on cooldown: not in boosters_ready, so not offered
    assert [a for a, _ in due(40.0, spare={"glitter": 1})] == ["glitter"]
    # a booster whose set does not hold the field
    assert due(40.0, ready={"red_field_booster": ("strawberry",)}) == []


def test_dice_only_without_glitter():
    assert [a for a, _ in due(40.0, spare={"glitter": 1, "field_dice": 5})] == ["glitter"]
    assert [a for a, _ in due(40.0, spare={"field_dice": 5})] == ["field_dice"]


def test_off_means_no_actions():
    assert due(40.0, on=False, spare={"glitter": 3}, ready=BOOSTERS) == []


def test_expired_boost_and_stacks():
    assert bk.left_of(box(-5.0), NOW) == {}
    assert bk.stacked(box(40.0), "pine_tree", NOW) == 3
    assert bk.stacked(box(40.0), "bamboo", NOW) == 1
    assert "no boost running" in due(-5.0, spare={"glitter": 1})[0][1]
