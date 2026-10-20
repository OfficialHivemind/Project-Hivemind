"""The boost window (brain/boostwindow): no errands while a field boost runs
where the trip gathered -- seen in the trip's own rate, not assumed."""
from __future__ import annotations

from hivemind.brain import boostwindow as bw

BLUE = ("blue_flower", "bamboo", "pine_tree", "stump")


def landed(**kw):
    args = dict(pressed_at=1000.0, now=1000.0 + 6 * 60, fields=BLUE,
                field="pine_tree", pollen=14_400_000, seconds=648.0,
                usual_rate=10_500.0)
    args.update(kw)
    return bw.boost_landed(**args)


def test_the_0200_boosted_trip_opens_the_window():
    # 2026-10-02 02:00: 14.4M pollen in 648 s, Pine Tree's usual ~10,500/s
    why = landed()
    assert why and "boost landed" in why and "pine tree" in why
    assert "9 min of it left" in why


def test_an_ordinary_fast_trip_does_not():
    # 05:02 the same night: 14,450 a second, no boost (1.38x)
    assert landed(pollen=int(14_450 * 300), seconds=300.0) == ""


def test_no_booster_pressed_means_no_window():
    assert landed(pressed_at=None) == ""


def test_too_little_of_the_boost_left_to_be_worth_a_trip():
    assert landed(now=1000.0 + bw.BOOST_SECONDS - 100) == ""
    assert landed(now=1000.0 + bw.BOOST_SECONDS + 60) == ""


def test_a_field_the_booster_does_not_boost():
    assert landed(field="strawberry") == ""
    assert landed(field=None) == ""


def test_an_unmeasured_trip_or_field_says_nothing():
    assert landed(pollen=None) == ""
    assert landed(seconds=10.0) == ""
    assert landed(usual_rate=None) == ""
    assert landed(usual_rate=0.0) == ""


# ---- what the game boosted, and whether to follow it --------------------

def test_the_feed_names_the_boosted_field_in_every_form_it_was_seen():
    import pathlib
    from hivemind.vision import whereami as w
    known = w.field_names(pathlib.Path(__file__).resolve().parents[2]
                          / "data" / "knowledge" / "world.yaml")
    # lines tesseract read off the frames kept after booster presses
    assert w.boost_in('Activated "Blue Flower Field Boost" x 3', known) == ("blue_flower", 3)
    assert w.boost_in('Activated "Pine Tree Forest Boost"', known) == ("pine_tree", 1)
    assert w.boost_in("Activated Pine TreeForest Boost", known) == ("pine_tree", 1)
    assert w.boost_in('Activated “Pineapple Patch Boost"” x 2', known) == ("pineapple", 2)
    assert w.boost_in('Activated "Bamboo Field Boost"', known) == ("bamboo", 1)
    assert w.boost_in("+587 Honey (from Pine Tree Forest)", known) is None
    assert w.boost_in('Activated "Haste" x 4', known) is None


def test_a_boost_on_blue_flower_or_bamboo_is_followed_from_pine_tree():
    field, why = bw.follow_the_boost("blue_flower", 3, "pine_tree")
    assert field == "blue_flower" and "1.5x" in why
    field, why = bw.follow_the_boost("bamboo", 1, "pine_tree")
    assert field == "bamboo" and "1.3x" in why


def test_a_boost_on_the_trips_own_field_or_a_non_blue_one_is_not():
    assert bw.follow_the_boost("pine_tree", 1, "pine_tree") == (None, "")
    field, why = bw.follow_the_boost("mushroom", 3, "pine_tree")
    assert field is None and "not a blue field" in why
    field, why = bw.follow_the_boost("pine_tree", 1, "bamboo")   # home bamboo, Pine x1 = 2x
    assert field == "pine_tree"
    assert bw.follow_the_boost(None, 0, "pine_tree") == (None, "")


def test_a_boost_the_feed_named_is_the_answer():
    why = landed(boosted="blue_flower", field="blue_flower", pollen=None)
    assert "the game boosted blue flower" in why
    assert landed(boosted="blue_flower", field="pine_tree") == ""


def test_the_feed_rows_are_read_one_at_a_time():
    import numpy as np
    from hivemind.vision import feed

    frame = np.zeros((1080, 1920, 3), np.uint8)
    # one pill in the feed's corner, the game's blue (H ~105, S/V high)
    frame[1030:1056, 1560:1900] = (200, 120, 40)

    class Out:
        stdout = b'Activated "Bamboo Field Boost"\n'
    texts = feed.row_texts(frame, run=lambda cmd, **kw: Out())
    assert texts == ['Activated "Bamboo Field Boost"']
    assert feed.row_texts(np.zeros((1080, 1920, 3), np.uint8)) == []


# ---- the press itself: measured odds, and the boost followed elsewhere ------

def _blue_booster():
    from hivemind.act.errands import Errand
    return Errand(name="blue_field_booster",
                  boosts={"blue_flower": 3.0, "bamboo": 1.0, "pine_tree": 1.0, "stump": 1.0})


def test_the_measured_odds_replace_one_in_four(tmp_path):
    # 2026-10-02: 70 read presses of the blue booster -- Stump never came up
    import json
    from hivemind.act.errands import booster_worth
    log = tmp_path / "boosts.jsonl"
    rows = ([{"booster": "blue_field_booster", "field": "blue_flower", "stacks": 3}] * 30
            + [{"booster": "blue_field_booster", "field": "pine_tree", "stacks": 1}] * 21
            + [{"booster": "blue_field_booster", "field": "bamboo", "stacks": 1}] * 19
            + [{"booster": "blue_field_booster", "field": None, "stacks": 0}] * 27
            + [{"booster": "red_field_booster", "field": "mushroom", "stacks": 3}])
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    odds = bw.read_counts(log, "blue_field_booster")
    assert odds == {"blue_flower": 30, "pine_tree": 21, "bamboo": 19}
    worth, why = booster_worth(_blue_booster(), "pine_tree", 34, boosted_seconds=400,
                               detour_seconds=61, odds=odds)
    assert "pine tree on 21 of 70 read presses" in why
    assert "120s of gathering" in why and worth          # 21/70 x 1.0 x 400
    _w, before = booster_worth(_blue_booster(), "pine_tree", 34, boosted_seconds=400,
                               detour_seconds=61, odds={"pine_tree": 3})
    assert "1 in 4" in before                            # too few reads: the pool


def test_a_followed_boost_elsewhere_adds_its_gain():
    from hivemind.act.errands import booster_worth
    odds = {"blue_flower": 30, "pine_tree": 21, "bamboo": 19}
    elsewhere = {f: bw.follow_gain(f, int(s), "pine_tree")
                 for f, s in _blue_booster().boosts.items() if f != "pine_tree"}
    assert elsewhere["stump"] == 0.0                     # not blue-indexed: not followed
    assert round(elsewhere["blue_flower"], 2) == 0.48    # 0.77 x 4 / 2.08 - 1
    assert round(elsewhere["bamboo"], 2) == 0.34         # 1.39 x 2 / 2.08 - 1
    # 60 s of boosted gathering alone is 18 s at home, under a 30 s detour...
    worth, _why = booster_worth(_blue_booster(), "pine_tree", 34, boosted_seconds=60,
                                detour_seconds=30, odds=odds)
    assert not worth
    # ...the boosts it would follow make it 18 + 12.3 + 5.5 = 36 s
    worth, why = booster_worth(_blue_booster(), "pine_tree", 34, boosted_seconds=60,
                               detour_seconds=30, odds=odds, elsewhere=elsewhere)
    assert worth and "following it to blue flower or bamboo adds 18s" in why


def test_a_restart_inside_a_boost_finds_it_again(tmp_path):
    import json
    log = tmp_path / "boosts.jsonl"
    rows = [{"at": 1000.0, "booster": "blue_field_booster", "field": "pine_tree", "stacks": 1},
            {"at": 1500.0, "booster": "blue_field_booster", "field": "bamboo", "stacks": 1,
             "frame": "blue_field_booster-pressed-x.jpg"},           # history, not live
            {"at": 1200.0, "booster": "blue_field_booster", "field": "blue_flower", "stacks": 3}]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert bw.last_boost(log, 1300.0)["field"] == "blue_flower"
    assert bw.last_boost(log, 1200.0 + bw.BOOST_SECONDS + 1) is None   # all over
    assert bw.last_boost(tmp_path / "none.jsonl", 1300.0) is None


def test_measured_ratios_are_taken_over_the_same_days():
    day = 86400.0
    rows = []
    for i in range(12):        # bamboo, days 10-11: 5,600 a second
        rows.append({"at": 10 * day + i * 3600, "aimed_at": "bamboo", "credited": "bamboo",
                     "pollen": 5600 * 300, "gather_seconds": 300})
    for i in range(12):        # pine tree, the same days: 7,000
        rows.append({"at": 10 * day + i * 3600, "aimed_at": "pine_tree", "credited": "pine_tree",
                     "pollen": 7000 * 300, "gather_seconds": 300})
    for i in range(30):        # pine tree, a week later and stronger: 12,000 (not counted)
        rows.append({"at": 20 * day + i * 3600, "aimed_at": "pine_tree", "credited": "pine_tree",
                     "pollen": 12000 * 300, "gather_seconds": 300})
    rows.append({"at": 10 * day, "aimed_at": "blue_flower", "credited": "blue_flower",
                 "pollen": 545 * 300, "gather_seconds": 300})       # one trip: not enough
    got = bw.measured_ratios(rows, "pine_tree", ("pine_tree", "bamboo", "blue_flower"))
    assert set(got) == {"bamboo"} and round(got["bamboo"][0], 2) == 0.80 and got["bamboo"][1] == 12
    field, why = bw.follow_the_boost("bamboo", 1, "pine_tree", ratios=got)
    assert field == "bamboo" and "0.80 of pine tree over 12 measured trips" in why
    assert round(bw.follow_gain("bamboo", 1, "pine_tree", ratios=got), 2) == 0.60
    # blue flower still by the proxy
    assert "proxy" in bw.follow_the_boost("blue_flower", 3, "pine_tree", ratios=got)[1]
