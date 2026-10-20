"""U19, the boost AI: measured gains from synthetic trips and presses, and the
verdicts the boost keeper is gated by. Loaded from the tree under test."""
import importlib.util
import pathlib
import sys

import hivemind

_dir = pathlib.Path(hivemind.__file__).resolve().parent / "brain"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", _dir / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod            # a dataclass looks its module up
    spec.loader.exec_module(mod)
    return mod


ai = _load("boostai")
bk = _load("boostkeeper")

T0 = 1_000_000.0


def trip(at, field, rate, boosted=None, gather=300.0):
    return {"at": at, "aimed_at": field, "credited": field, "pollen": rate * gather,
            "gather_seconds": gather, "seconds": gather + 60.0, "boosted": boosted}


def ledger(field="pine_tree", pairs=6, base=10_000.0, boosted=18_000.0):
    """`pairs` boosted trips, each pressed just before, between unboosted ones."""
    trips, presses = [], []
    for i in range(pairs):
        t = T0 + i * 3600.0
        trips += [trip(t - 1500, field, base), trip(t - 1200, field, base)]
        presses.append({"at": t - 100, "booster": "blue_field_booster", "field": field})
        trips.append(trip(t + 400, field, boosted, boosted=field))
    return trips, presses


def test_a_boost_is_measured_against_the_same_fields_unboosted_trips():
    gains = ai.measure(*ledger())
    g = gains["pine_tree"]
    assert round(g.ratio, 2) == 1.8 and g.pairs == 6 and g.base_rate == 10_000.0
    assert round(g.extra_rate) == 8_000


def test_too_few_boosted_trips_is_not_measured():
    assert ai.measure(*ledger(pairs=ai.MIN_PAIRS - 1)) == {}


def test_a_trip_a_boost_only_partly_covered_is_neither():
    trips, presses = ledger()
    # pressed mid-trip: boosted for its last few minutes only
    trips.append(trip(T0 + 50_000, "pine_tree", 99_000.0))
    presses.append({"at": T0 + 50_000 - 200, "booster": "blue_field_booster",
                    "field": "pine_tree"})
    assert round(ai.measure(trips, presses)["pine_tree"].ratio, 2) == 1.8


def test_a_glitter_boosted_trip_is_kept_out_of_the_baseline():
    trips, presses = ledger()
    trips.append(trip(T0 + 30, "pine_tree", 50_000.0, boosted="pine_tree"))
    assert round(ai.measure(trips, presses)["pine_tree"].ratio, 2) == 1.8


def test_glitter_pays_only_where_measured():
    gains = ai.measure(*ledger())
    ok, why = ai.item_pays("glitter", "pine_tree", gains, seconds=600)
    assert ok and "x1.80" in why and "4,800,000" in why
    ok, why = ai.item_pays("glitter", "rose", gains, seconds=600)
    assert not ok and "not measured" in why


def test_a_field_dice_needs_its_landings_read():
    gains = ai.measure(*ledger())
    ok, why = ai.item_pays("field_dice", "pine_tree", gains, seconds=900, landings={})
    assert not ok and "not measured" in why
    ok, _ = ai.item_pays("field_dice", "pine_tree", gains, seconds=900,
                         landings={"pine_tree": 2, "rose": 8})
    assert ok
    # landing only where the trip would not gather adds nothing
    ok, _ = ai.item_pays("field_dice", "rose", gains, seconds=900,
                         landings={"pine_tree": 10})
    assert not ok


def test_a_booster_pays_when_its_odds_beat_the_walk():
    gains = ai.measure(*ledger())
    assert ai.booster_pays("pine_tree", gains, p_land=0.5, boosted_s=600, detour_s=60)[0]
    assert not ai.booster_pays("pine_tree", gains, p_land=0.05, boosted_s=600, detour_s=60)[0]
    assert not ai.booster_pays("rose", gains, p_land=1.0, boosted_s=600, detour_s=0)[0]


def test_stack_target_is_the_biggest_measured_gain_among_open_fields():
    t1, p1 = ledger("pine_tree", base=10_000, boosted=18_000)
    t2, p2 = ledger("bamboo", base=10_000, boosted=30_000)
    gains = ai.measure(t1 + t2, p1 + p2)
    assert ai.stack_target(gains)[0] == "bamboo"
    assert ai.stack_target(gains, {"pine_tree"})[0] == "pine_tree"
    assert ai.stack_target({})[0] is None


def test_booster_timing_lands_the_stack_before_the_end():
    boosts = {"blue_field_booster": ("pine_tree",)}
    assert "now" in ai.booster_timing("pine_tree", 0, {"blue_field_booster": -5}, boosts)
    assert "last minutes" in ai.booster_timing("pine_tree", 600, {"blue_field_booster": 100}, boosts)
    assert "after" in ai.booster_timing("pine_tree", 100, {"blue_field_booster": 900}, boosts)
    assert ai.booster_timing("rose", 100, {"blue_field_booster": 0}, boosts) == ""


def test_the_keeper_keeps_up_only_the_kinds_chosen():
    box = {"at": T0 - (bk.BOOST_SECONDS - 30), "field": "pine_tree", "stacks": 1}
    args = dict(on=True, field="pine_tree", boosts=bk.left_of(box, T0), trip_seconds=300,
                spare={"glitter": 2, "field_dice": 2},
                boosters_ready={"blue_field_booster": ("pine_tree",)})
    assert [a for a, _ in bk.due(**args)] == ["blue_field_booster", "glitter"]
    assert [a for a, _ in bk.due(**args, kinds=("glitter", "field_dice"))] == ["glitter"]
    assert [a for a, _ in bk.due(**args, kinds=("field_dice",))] == ["field_dice"]
    assert bk.due(**args, kinds=()) == []


def test_a_boost_is_followed_only_where_measured_to_beat_home():
    # research 2026-10-21, Pine Tree home: Bamboo boosted ~43.9k/s, Blue Flower x3 ~19.8k/s
    G = ai.Gain
    gains = {"pine_tree": G("pine_tree", 1.73, 18, 28_900.0),
             "bamboo": G("bamboo", 1.45, 9, 30_300.0),
             "blue_flower": G("blue_flower", 3.54, 7, 5_600.0)}
    assert ai.follow_target(gains, {"bamboo": 600.0}, "pine_tree")[0] == "bamboo"
    f, why = ai.follow_target(gains, {"blue_flower": 600.0}, "pine_tree")
    assert f is None and "blue flower boosted 19,824/s under 33,235" in why           # the x3 guess said follow
    assert ai.follow_target(gains, {"bamboo": 100.0}, "pine_tree")[0] is None   # too little left
    assert ai.follow_target(gains, {"bamboo": 600.0}, "pine_tree", {"pine_tree"})[0] is None   # shut
    assert ai.follow_target(gains, {"pumpkin": 600.0}, "pine_tree")[0] is None  # not measured


def test_a_booster_press_is_priced_by_the_rule_the_trip_follows():
    # U19b, 21 Oct 18:40: the blue booster pressed for Pine Tree landed on Bamboo
    G = ai.Gain
    gains = {"pine_tree": G("pine_tree", 1.73, 18, 28_900.0),
             "bamboo": G("bamboo", 1.45, 9, 30_300.0),
             "blue_flower": G("blue_flower", 3.54, 7, 5_600.0)}
    assert round(ai.follow_gain(gains, "bamboo", "pine_tree", 834.0), 2) == 0.52
    assert ai.follow_gain(gains, "blue_flower", "pine_tree", 834.0) == 0.0  # stays: no gain
    assert ai.follow_gain(gains, "bamboo", "pine_tree", 100.0) == 0.0       # too little left
    assert ai.follow_gain(gains, "pumpkin", "pine_tree", 834.0) == 0.0      # not measured
    assert ai.MOVES_LIVE is False                                           # look-only until seen live


def test_the_trip_follows_the_boost_by_the_measured_rule_only_when_live():
    src = (pathlib.Path(hivemind.__file__).resolve().parents[2]
           / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert 'return bool(boostai.MOVES_LIVE) and boost_ai_mode() == "act"' in src
    follow = src[src.index("def boost_to_follow("):src.index("def boost_running(")]
    assert "boostai.follow_target(boost_gains(), {boosted: left}, planned)" in follow
    press = src[src.index("def _resources_use_booster("):]
    assert "boostai.follow_gain(boost_gains(), other, target, boosted)" in press
    assert "boost AI would: {'press' if ai_worth else 'skip'}" in press
