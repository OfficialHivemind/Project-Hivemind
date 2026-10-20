"""The Coconut Crab (act/crab): Natro's fight as timed steps, and when the
Coconut Field is open -- beaten, for 1.5 days; nothing else opens it."""
from __future__ import annotations

from hivemind.act import crab


def test_the_cycle_keeps_natros_rhythm_and_comes_back_to_the_middle():
    starts = [at for at, _ in crab.CYCLE]
    assert starts == sorted(starts) and starts[-1] < crab.CYCLE_S
    side = sum((s["studs"] if s["keys"] == "d" else -s["studs"])
               for _, steps in crab.CYCLE for s in steps if s["keys"] in "ad")
    assert side == 0                                    # as far left as right
    sweeps = [s for _, steps in crab.CYCLE for s in steps if s["keys"] in "ad"]
    assert len(sweeps) == 4 and all(s["studs"] == 112.0 for s in sweeps)


def test_the_loot_walk_is_natros_six_passes():
    steps = crab.loot_steps()
    assert len(steps) == 6 * 4 * 4
    assert {s["keys"] for s in steps} == {"w", "s", "a", "d"}


def test_a_kill_opens_the_field_for_a_day_and_a_half():
    state = crab.record({}, "killed", now=1000.0)
    assert crab.field_open(state, 1000.0 + crab.COOLDOWN_S - 1)
    assert not crab.field_open(state, 1000.0 + crab.COOLDOWN_S + 1)
    assert not crab.due(state, 1000.0 + crab.COOLDOWN_S - 1)
    assert crab.due(state, 1000.0 + crab.COOLDOWN_S)


def test_no_crab_seen_only_brings_the_next_look_and_a_lost_fight_waits():
    # MEASURED 2026-10-07 10:23: no health bar was seen because the character
    # was dead at the hive -- "absent" must never send trips into the field
    t = 1_791_300_000.0
    absent = crab.record({}, "absent", now=t)
    assert not crab.field_open(absent, t + 1.0)
    assert not crab.due(absent, t + crab.ABSENT_OPEN_S - 1)
    assert crab.due(absent, t + crab.ABSENT_OPEN_S)
    lost = crab.record({}, "died", now=t)
    assert not crab.field_open(lost, t + 1.0)
    assert not crab.due(lost, t + crab.LOST_RETRY_S - 1) and crab.due(lost, t + crab.LOST_RETRY_S)
    assert [x["result"] for x in crab.record(lost, "time", now=t + 5)["tries"]] == ["died", "time"]


def test_the_feed_says_it_is_beaten():
    assert crab.defeated("Defeated Coconut Crab! (+25 Battle Points)")
    assert crab.defeated("Defeated Coconut Crab!+100,000 Honey")
    assert not crab.defeated("Defeated Rhino Beetle! (+1 Battle Point)")
    assert not crab.defeated("+500 Honey (from Coconut Crab)")


def test_the_state_round_trips(tmp_path):
    path = tmp_path / "crab.json"
    assert crab.load(path) == {}
    crab.save(path, crab.record({}, "killed", now=7.0))
    assert crab.load(path)["killed_at"] == 7.0
