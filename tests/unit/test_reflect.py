"""brain/reflect: the hour looked back on, the leaks ranked by measured minutes."""
from hivemind.brain import reflect


def trip(at, seconds, honey=0, pollen=0, routes=(), deaths=0, ended="", converted=True):
    return {"at": at, "seconds": seconds, "honey": honey, "pollen": pollen,
            "converted": converted, "routes": list(routes), "deaths": deaths,
            "gather_ended": ended, "gather_seconds": seconds, "credited": "pine_tree"}


def test_the_biggest_measured_leak_is_the_focus():
    rows = [trip(1000, 600, honey=9_000_000, pollen=6_000_000),
            trip(2000, 300, routes=[{"kind": "home", "target": "clover",
                                     "outcome": "elsewhere", "seconds": 60}],
                 converted=False),
            trip(2500, 100, honey=1, pollen=5, routes=[
                {"kind": "errand", "target": "honey_bee", "outcome": "elsewhere", "seconds": 30},
                {"kind": "errand", "target": "ant_pass", "outcome": "unknown", "seconds": 30}])]
    got = reflect.review(rows, now=3000)
    assert got.trips == 3 and got.converted == 2
    assert got.focus.what == "the walk home from clover"         # 1 + 5 minutes
    assert [l.what for l in got.leaks] == ["the walk home from clover",
                                           "the errand walk to honey bee"]
    assert abs(got.per_hour - 9_000_001 / (1000 / 3600)) < 1


def test_an_unmeasured_honey_with_pollen_is_not_a_trip_for_nothing():
    rows = [trip(1000, 600, honey=None, pollen=3_000_000, converted=False)]
    assert reflect.review(rows, now=1100).leaks == []


def test_lessons_count_what_keeps_going_wrong(tmp_path):
    rows = [trip(1000, 300, routes=[{"kind": "home", "target": "clover",
                                     "outcome": "elsewhere", "seconds": 60}], converted=False)]
    got = reflect.review(rows, now=1100)
    reflect.remember(tmp_path / "l.json", got, 1100)
    said = reflect.remember(tmp_path / "l.json", got, 4700)
    assert "2 hour(s)" in said and "the top one 2" in said
    assert reflect.recurring(tmp_path / "l.json")[0][0] == "the walk home from clover"


def test_honey_is_weighed_by_the_nectar_it_ran_under():
    rows = [dict(trip(i, 100, honey=h, pollen=1), nectar={"comforting": lv})
            for i, (h, lv) in enumerate([(9000, 80), (9000, 70), (9000, 60),
                                          (3000, 10), (3000, 20), (3000, 0)])]
    hi, lo, nh, nl = reflect.nectar_effect(rows, "comforting")
    assert (hi, lo, nh, nl) == (90.0, 30.0, 3, 3)
    assert reflect.nectar_effect(rows[:4], "comforting") is None


def test_field_minutes_carries_only_the_leaks_the_planner_prices_nowhere_else():
    """decide.LEAK_FEEDBACK reads these: off the flowers and nothing gathered,
    by field; not route misses (p_land) nor deaths (survival_over)."""
    rows = [trip(1000, 600, ended="the pollen counter has not risen", converted=False),
            trip(1700, 300, routes=[{"kind": "home", "target": "clover",
                                     "outcome": "elsewhere", "seconds": 60}], converted=False),
            trip(2100, 200, deaths=1, converted=False)]
    got = reflect.review(rows, now=2200)
    assert reflect.field_minutes(got) == {"pine_tree": 10.0}
    assert reflect.field_minutes(reflect.review([], now=10)) == {}
