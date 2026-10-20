"""ROADMAP H13d: where a new bee goes (brain/hiveplanner.hatch_slot)."""
import re
from pathlib import Path

import hivemind
from hivemind.brain import hiveplanner as hp
from hivemind.world.settings import READ_AT_EVERY_USE, SECTIONS

SCHEMA = {e[0]: e for _, entries in SECTIONS for e in entries}

ROOT = Path(hivemind.__file__).resolve().parents[2]
PLAN = {1: "bubble", 2: "bubble", 6: "bubble", 7: "diamond", 8: "diamond"}
READ = {1: "bubble", 2: "basic", 3: "rad", 4: "basic", 5: "basic"}   # 5 bees, slots 1-5


def test_plan_order_and_filled_slots_skipped():
    # slots 6..8 bought and empty: 6 is planned and lowest
    assert hp.hatch_slot(PLAN, READ, 100.0, 8, 5) == (6, "planned: bubble, next in plan order")
    # slot 6 filled since (read again): 7 is next
    assert hp.hatch_slot(PLAN, {**READ, 6: "basic"}, 100.0, 8, 6)[0] == 7


def test_unplanned_empty_slots_fall_back():
    slot, why = hp.hatch_slot({1: "bubble"}, READ, 100.0, 7, 5)
    assert slot is None and "6, 7" in why


def test_stale_or_missing_read_falls_back():
    assert hp.hatch_slot(PLAN, READ, 100.0, 8, 5, last_hatch_at=200.0)[0] is None
    assert hp.hatch_slot(PLAN, {}, 0.0, 8, 5)[0] is None
    # a bee hatched since the read: the read names 5, the menu counts 6
    assert hp.hatch_slot(PLAN, READ, 100.0, 8, 6)[0] is None
    # a read slot beyond the slots bought: not believed
    assert hp.hatch_slot(PLAN, {**READ, 9: "rad"}, 100.0, 8, 6)[0] is None


def test_no_plan_falls_back():
    assert hp.hatch_slot({}, READ, 100.0, 8, 5) == (None, "there is no Hive Plan")


def test_the_setting_is_off_by_default_and_read_live():
    key, _label, kind, default, _help, choices = SCHEMA["hive.new_bees"]
    assert kind == "choice" and default == hp.HATCH_ANY
    assert choices == [hp.HATCH_ANY, hp.HATCH_PLAN]
    assert key in READ_AT_EVERY_USE


def test_the_aimed_drag_ships_look_only():
    farm = (ROOT / "scripts" / "run_farm.py").read_text()
    assert re.search(r"^HATCH_AIM_LIVE = False$", farm, re.M)
    assert "hatch by plan would: put the egg in slot" in farm
