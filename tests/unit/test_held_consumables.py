"""G6: the items held and never used (brain/stash FIELD_USES): Red Extract on a
red quest step, Tropical Drinks and Jelly Beans in a boost (Jelly Beans also at
their cap), a Field Dice at the pad while no boost runs. Stingers and Oil stay
out (kept for the Cobalt Guard / the Diamond Mask)."""
from hivemind.brain.stash import Stash

CAT = {"red_extract": {"label": "Red Extract"}, "tropical_drink": {"label": "Tropical Drink"},
       "jelly_beans": {"label": "Jelly Beans", "cap": 100}, "field_dice": {"label": "Field Dice"},
       "stinger": {"label": "Stingers"}, "oil": {"label": "Oil"}}
# var/inventory.json, read 2026-10-12 20:00
HELD = {"red_extract": 9, "tropical_drink": 2, "jelly_beans": 92, "field_dice": 14,
        "stinger": 87, "oil": 7}


def use(s, key, boosted=False, last=None, now=0.0, red=""):
    return s.field_use(key, home_boosted=boosted, last_used=last, now=now, red_step=red).use


def test_red_extract_only_on_a_red_quest_step_and_not_while_one_works():
    s = Stash(catalogue=CAT, counts=dict(HELD))
    assert not use(s, "red_extract")
    assert not use(s, "red_extract", boosted=True)               # a boost is not a red step
    v = s.field_use("red_extract", home_boosted=False, last_used=None, now=0,
                    red_step="a quest owes 2,000,000 red pollen here")
    assert v.use and "red pollen" in v.why
    assert not use(s, "red_extract", last=0, now=599, red="step")
    assert use(s, "red_extract", last=0, now=601, red="step")
    s.reserved["red_extract"] = 100                              # the Crimson Guard, once it is next
    assert not use(s, "red_extract", red="step")


def test_tropical_drink_and_jelly_beans_in_a_boost_jelly_beans_at_their_cap():
    s = Stash(catalogue=CAT, counts=dict(HELD))
    assert not use(s, "tropical_drink") and use(s, "tropical_drink", boosted=True)
    assert not use(s, "jelly_beans") and use(s, "jelly_beans", boosted=True)
    assert not use(s, "jelly_beans", boosted=True, last=0, now=30)      # its beans' minute
    s.counts["jelly_beans"] = 100
    v = s.field_use("jelly_beans", home_boosted=False, last_used=None, now=0)
    assert v.use and "at its cap" in v.why


def test_a_field_dice_only_while_no_boost_runs_and_one_boost_at_a_time():
    s = Stash(catalogue=CAT, counts=dict(HELD))
    assert use(s, "field_dice")
    assert not use(s, "field_dice", boosted=True)
    assert not use(s, "field_dice", last=0, now=899)            # its own boost still runs
    assert use(s, "field_dice", last=0, now=901)
    s.counts["field_dice"] = 0
    assert not use(s, "field_dice")


def test_stingers_and_oil_are_never_field_consumables():
    s = Stash(catalogue=CAT, counts=dict(HELD))
    for key in ("stinger", "oil"):
        for boosted in (False, True):
            assert not use(s, key, boosted=boosted, red="step")


def test_the_catalogue_gives_jelly_beans_their_cap():
    from hivemind.datapaths import DATA_ROOT
    s = Stash.from_files(DATA_ROOT / "knowledge" / "consumables.yaml", DATA_ROOT / "missing.json")
    assert s.holding("jelly_beans").cap == 100
