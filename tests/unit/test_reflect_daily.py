"""brain/reflect.daily (P7): the day's top 3 honey/hr losses, each with a fix."""
from hivemind.brain import reflect


def trip(at, seconds, honey=0, pollen=0, routes=(), deaths=0, ended="", field="pine_tree"):
    return {"at": at, "seconds": seconds, "honey": honey, "pollen": pollen,
            "converted": honey > 0, "routes": list(routes), "deaths": deaths,
            "gather_ended": ended, "gather_seconds": seconds, "credited": field}


def miss(kind, target, seconds):
    return {"kind": kind, "target": target, "outcome": "elsewhere", "seconds": seconds}


DAY = [
    trip(1000, 3600, honey=36_000_000, pollen=30_000_000),          # 1 h of good trips
    trip(2000, 600, routes=[miss("home", "clover", 120)]),            # 10 min, nothing
    trip(3000, 300, routes=[miss("errand", "honey_bee", 60)]),        # 5 min, nothing
    trip(4000, 300, deaths=1, field="cactus"),                        # 5 min, nothing
    trip(5000, 120, routes=[miss("walk", "rose", 30)]),               # 2 min, nothing
]


def test_top_three_ranked_by_honey_per_hour_with_fixes():
    got, losses = reflect.daily(DAY, now=6000)
    assert got.trips == 5 and len(losses) == 3
    assert [l.leak.what for l in losses] == [
        "the walk home from clover", "the errand walk to honey bee", "dying in cactus"]
    # rate = 36M over 4920 s of trips; 12 lost minutes (10 + walk 2) priced at it
    hours = 4920 / 3600
    rate = 36_000_000 / hours
    assert abs(losses[0].honey_per_hour - rate * (12 / 60) / hours) < 1
    assert losses[0].honey_per_hour > losses[1].honey_per_hour >= losses[2].honey_per_hour
    assert "route home from clover" in losses[0].fix
    assert "honey bee" in losses[1].fix and "cactus" in losses[2].fix
    text = reflect.daily_text(got, losses)
    assert text.count("\n") == 3 and "(est.)" in text


def test_no_measured_honey_means_minutes_not_a_rate():
    got, losses = reflect.daily(DAY[1:], now=6000)
    assert losses and all(l.honey_per_hour is None for l in losses)
    assert "min" in reflect.daily_text(got, losses)


def test_old_trips_and_empty_days():
    got, losses = reflect.daily(DAY, now=6000 + 86400 * 2)
    assert reflect.daily_text(got, losses) == "Daily self-review: no trips today."
    got, losses = reflect.daily(DAY[:1], now=6000)
    assert losses == [] and "no measured losses" in reflect.daily_text(got, losses)


def test_every_leak_kind_review_writes_has_a_fix():
    for what in ("the walk home from x", "the errand walk to x", "the flight to x",
                 "the walk to x", "dying in x", "gathering off the flowers in x",
                 "a trip to x that gathered nothing"):
        fix = reflect.proposed_fix(what)
        assert fix and "x" in fix and "gathered nothing" not in fix
    assert reflect.proposed_fix("something new") == ""
