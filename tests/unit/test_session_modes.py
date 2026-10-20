"""ROADMAP B14 session modes: the 'bosses' plan and 'farm until X honey'."""
from __future__ import annotations

from hivemind.brain import plan
from hivemind.world.settings import settle


def test_boss_night_is_a_plan_that_turns_on_the_fights():
    got = plan.resolve("bosses")
    for key in ("combat.bosses", "combat.vicious", "combat.commando"):
        assert got[key] is True
    assert plan.label("bosses")[0] == "Boss night"
    assert plan.check("bosses", "") == ""


def test_honey_stop_needs_two_good_readings_at_the_target():
    stop = plan.HoneyStop()
    s = {"goals.stop_honey_m": 500}
    assert stop.tick(s, 600_000_000) == ""               # one reading is not enough
    assert stop.tick(s, None) == ""                      # a misread resets the count
    assert stop.tick(s, 600_000_000) == ""
    assert "500M" in stop.tick(s, 600_000_000)
    assert stop.tick(s, 400_000_000) == ""               # under the target again


def test_honey_stop_off_by_default_and_bounded():
    stop = plan.HoneyStop()
    for _ in range(3):
        assert stop.tick({"goals.stop_honey_m": 0}, 10**15) == ""
        assert stop.tick({}, 10**15) == ""
    assert settle("goals.stop_honey_m", -5)[0] == 0
