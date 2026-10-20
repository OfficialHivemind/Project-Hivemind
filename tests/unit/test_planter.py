"""Planters: placed where the gather starts, harvested there once grown (act/planter)."""
from __future__ import annotations

from hivemind.act import planter as p

OWNED = {"Blue Clay Planter"}
H = 3600.0


def test_a_bought_planter_is_placed_in_the_field_and_harvested_there_grown():
    state: dict = {}
    assert p.next_step(state, "pine_tree", (), 0.0) is None          # not bought
    assert p.next_step(state, "pine_tree", OWNED, 0.0) == ("place", "blue_clay_planter")
    state = p.placed(state, "blue_clay_planter", "pine_tree", 0.0)
    # the wiki's rule (N1-N3): 6 h / (1 + 0.25 x Pine Tree's 85% blue) = 4.948 h
    # (Natro's table said 4.96)
    assert abs(p.grow_s("blue_clay_planter", "pine_tree") - 6 / 1.2125 * H) < 1e-6
    assert p.next_step(state, "pine_tree", OWNED, 4.9 * H) is None
    assert p.next_step(state, "rose", OWNED, 9 * H) is None           # out elsewhere
    assert p.next_step(state, "pine_tree", OWNED, 4.96 * H) == ("harvest", "blue_clay_planter")
    state = p.harvested(state, "blue_clay_planter", 4.96 * H)
    assert state["harvests"][-1]["field"] == "pine_tree"
    assert p.next_step(state, "pine_tree", OWNED, 4.96 * H) == ("place", "blue_clay_planter")


def test_a_failed_placing_waits_and_a_planter_never_found_is_written_off():
    state = p.failed({}, "blue_clay_planter", 0.0)
    assert p.next_step(state, "pine_tree", OWNED, 0.5 * H) is None
    assert p.next_step(state, "pine_tree", OWNED, 1.0 * H) == ("place", "blue_clay_planter")
    state = p.placed(state, "blue_clay_planter", "pine_tree", 0.0)
    for _ in range(p.MISSES_TO_GIVE_UP - 1):
        state = p.missed(state, "blue_clay_planter", 5 * H)
        assert "blue_clay_planter" in state["out"]
    state = p.missed(state, "blue_clay_planter", 5 * H)
    assert "blue_clay_planter" in state["lost"] and not state["out"]
    assert p.next_step(state, "pine_tree", OWNED, 9 * H) is None      # not placed again


def test_the_prompt_is_read_loosely():
    assert p.harvest_prompt("Harvest Blue Clay Planter")
    assert p.harvest_prompt("harvestblue clayplanter")
    assert not p.harvest_prompt("Use Glitter")
    assert not p.harvest_prompt(None)


def test_an_owned_paper_planter_is_placed_and_harvested_after_an_hour():
    from hivemind.act import planter as p
    state = p.next_step({}, "pine_tree", {"Paper Planter"}, 0.0)
    assert state == ("place", "paper_planter")
    out = p.placed({}, "paper_planter", "pine_tree", 0.0)
    assert p.next_step(out, "pine_tree", {"Paper Planter"}, 3599.0) is None
    assert p.next_step(out, "pine_tree", {"Paper Planter"}, 3600.0) == ("harvest", "paper_planter")


def test_seek_steers_toward_the_bar_and_reverses_exactly():
    from hivemind.act import planter as p
    assert p.seek_keys(None, 1920) == "w"
    assert p.seek_keys(960, 1920) == "w"
    assert p.seek_keys(300, 1920) == "wa"
    assert p.seek_keys(1700, 1920) == "wd"
    assert p.reverse_keys("wa") == "sd" and p.reverse_keys("w") == "s"


def test_a_second_planter_goes_to_a_different_nectar():
    from hivemind.act import planter as p
    out = p.placed({}, "blue_clay_planter", "pine_tree", 0.0)     # comforting
    assert p.next_step(out, "bamboo", {"Paper Planter"}, 10.0) is None       # comforting too
    assert p.next_step(out, "pumpkin", {"Paper Planter"}, 10.0) == ("place", "paper_planter")


def test_the_loot_walk_ends_where_it_began():
    from hivemind.act import planter as p
    step = {"w": (0, 1), "s": (0, -1), "a": (-1, 0), "d": (1, 0)}
    assert tuple(map(sum, zip(*(step[k] for k in p.LOOT_LEGS)))) == (0, 0)


def test_the_loot_look_turns_a_full_circle():
    from hivemind.act import planter as p
    assert p.LOOT_QUARTERS * p.LOOT_TURN_TAPS == p.SEEK_TURNS == 8     # 45 degrees a tap


def test_the_harvest_prompt_reads_from_its_first_line():
    # MEASURED 2026-10-10 23:56: the two-line prompt read only as its first line
    from hivemind.act import planter as p
    assert p.harvest_prompt("harvestp ïr êtglrue clay")
    assert p.harvest_prompt("harvesl r iêlrue clay i")
    assert p.harvest_prompt("Harvest Blue Clay Planter")
    assert not p.harvest_prompt("Make Honey") and not p.harvest_prompt("d")


def test_a_full_nectar_takes_no_planter():
    from hivemind.act import planter as p
    owned = {"Paper Planter"}
    assert p.next_step({}, "pumpkin", owned, 0.0, levels={"satisfying": 95.0}) == ("place", "paper_planter")
    assert p.next_step({}, "pumpkin", owned, 0.0, levels={"satisfying": 100.0}) is None
    assert p.next_step({}, "pumpkin", owned, 0.0, levels={}) == ("place", "paper_planter")
    # a grown 1 h Paper Planter: 1 h x 0.75 of the 24 h bar x NECTAR_SCALE 0.7
    # (Natro's estimator said 3.125%; planter.nectar_added's comment says why not)
    assert abs(p.nectar_added("paper_planter", "pumpkin") - 0.75 * 100 / 24 * 0.7) < 1e-6


def test_the_errand_harvests_first_then_plants_the_neediest_nectar():
    from hivemind.act import planter as p
    reach = {"pine_tree", "mushroom", "blue_flower", "pumpkin", "clover"}
    levels = {"comforting": 21.0, "motivating": 0.0, "refreshing": 75.0,
              "satisfying": 0.0, "invigorating": 0.0}
    # a grown planter goes first
    out = p.placed({}, "paper_planter", "pumpkin", 0.0)
    assert p.errand_target(out, set(), levels, reach, 3600.0)[0] == "pumpkin"
    # else the held Blue Clay goes to the nectar furthest under its minimum:
    # motivating (80 x 1.23) beats comforting ((70 - 21) x 1.35)
    got = p.errand_target({}, {"Blue Clay Planter"}, levels, reach, 0.0)
    assert got[0] == "mushroom" and "motivating" in got[1]
    # nothing read, nothing planted on a guess
    assert p.errand_target({}, {"Blue Clay Planter"}, {}, reach, 0.0) is None
    # a nectar already planted is left to that planter
    out = p.placed({}, "paper_planter", "mushroom", 0.0)
    # then satisfying (80 x 0.99) beats comforting ((70 - 21) x 1.35)
    assert p.errand_target(out, {"Blue Clay Planter"}, levels, reach, 10.0)[0] == "pumpkin"


def test_a_planter_is_harvested_early_only_when_its_nectar_would_overfill():
    from hivemind.act import planter as p
    st = p.placed({}, "blue_clay_planter", "pine_tree", 0.0)       # comforting
    full = p.grow_s("blue_clay_planter", "pine_tree")
    added = p.nectar_added("blue_clay_planter", "pine_tree")
    assert p.harvest_at(st, "blue_clay_planter", {"comforting": 40.0}) == (full, False)
    assert p.harvest_at(st, "blue_clay_planter", {"comforting": 99.5}) == (0.0, True)
    # (the Blue Clay adds 21%: from under 99 it never projects 120, so the 110
    # rung -- read 95, projected 116)
    assert 110.0 <= 95.0 + added < 120.0
    due, early = p.harvest_at(st, "blue_clay_planter", {"comforting": 95.0})
    assert early and abs(due - 0.75 * full) < 1e-6
    assert p.next_step(st, "pine_tree", set(), 0.0, levels={"comforting": 99.5}) == ("harvest", "blue_clay_planter")
    assert p.next_step(st, "pine_tree", set(), 0.0, levels={"comforting": 40.0}) is None


def test_the_errand_puts_the_blue_clay_where_it_does_best():
    from hivemind.act import planter as pl
    # comforting: Pine Tree (1.2 x 1.2125) beats Bamboo (1.2 x 1.1875)
    levels = {"comforting": 0.0, "motivating": 99.0, "refreshing": 99.0,
              "satisfying": 99.0, "invigorating": 99.0}
    got = pl.errand_target({}, {"Blue Clay Planter"}, levels, {"bamboo", "pine_tree"}, 0.0)
    assert got[0] == "pine_tree"


def test_ten_failed_placings_leave_the_planter_in_the_bag_until_one_works():
    from hivemind.act import planter as pl
    st = {}
    for i in range(pl.PLACE_FAILS_TO_STOP):
        st = pl.failed(st, "paper_planter", 0.0)
    assert pl.next_step(st, "pumpkin", {"Paper Planter"}, 10 * pl.PLACE_RETRY_S) is None
    st = pl.placed(st, "paper_planter", "pumpkin", 0.0)
    assert not pl.given_up(st, "paper_planter")


def test_a_harvest_wears_the_field_and_the_next_planter_there_grows_longer():
    from hivemind.act import planter as pl
    H = 3600.0
    full = pl.grow_s("blue_clay_planter", "pine_tree")                 # 4.948 h
    st = pl.placed({}, "blue_clay_planter", "pine_tree", 0.0)
    st = pl.harvested(st, "blue_clay_planter", full)                   # fully grown
    worn = pl.degradation_h(st, "pine_tree", full)
    assert abs(worn - (1.0 + full / H)) < 1e-3                         # 1 h + grow hours
    assert abs(pl.degradation_h(st, "pine_tree", full + 2 * H) - (worn - 2)) < 1e-3
    st = pl.placed(st, "blue_clay_planter", "pine_tree", full)
    assert abs(pl.planter_grow_s(st, "blue_clay_planter") - (full + worn * H)) < 1
    # a worn Pine Tree loses to a fresh Bamboo for the next comforting planter
    st2 = pl.harvested(pl.placed({}, "blue_clay_planter", "pine_tree", 0.0),
                       "blue_clay_planter", full)
    levels = {"comforting": 0.0, "motivating": 99.0, "refreshing": 99.0,
              "satisfying": 99.0, "invigorating": 99.0}
    got = pl.errand_target(st2, {"Blue Clay Planter"}, levels, {"bamboo", "pine_tree"}, full)
    assert got[0] == "bamboo"


def test_a_stuck_seek_steers_toward_the_bar_inside_the_middle():
    """2026-10-13 12:48: the bar 65 px left of the middle, the character not moving."""
    assert p.seek_keys(895, 1920) == "w"
    assert p.seek_keys(895, 1920, centre_px=0) == "wa"
    assert p.seek_keys(1000, 1920, centre_px=0) == "wd"
