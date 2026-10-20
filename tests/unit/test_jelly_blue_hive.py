"""Royal Jelly for a blue hive (the owner, 2026-10-21, agreed to using Royal
Jelly to swap the Basic, Crimson and Cobalt bees for blue ones): which bees the
rolls go on, in what order, and which roll is kept (brain/hivejudge)."""
from pathlib import Path

import yaml

import hivemind
from hivemind.brain import hivejudge, hiveplan

ROOT = Path(hivemind.__file__).resolve().parents[2]
KNOW = ROOT / "data" / "knowledge"


def load(name):
    return yaml.safe_load((KNOW / name).read_text(encoding="utf-8"))


TYPES = load("bee_types.yaml")["types"]
PLAN = load("blue_hive_plan.yaml")
# An example 40-bee hive (made up): 14 Bubble, 9 Diamond, one each of
# Basic, Crimson and Cobalt; the other 14 are wanted fill.
HIVE = {"bubble": 14, "diamond": 9, "basic": 1, "crimson": 1, "cobalt": 1,
        "bucko": 3, "ninja": 2, "bumble": 1, "cool": 2, "music": 2, "baby": 1,
        "tabby": 1, "bear": 1, "looker": 1}


def test_the_40_bee_hive_rolls_basic_then_crimson_then_cobalt():
    assert sum(HIVE.values()) == 40
    j = hivejudge.judge(HIVE, 40, types=TYPES, plan=PLAN, items=load("items.yaml"))
    assert list(j.jelly_on) == ["basic", "crimson", "cobalt"]
    assert j.jelly_kept == {}
    # Stage 1's comp (13-14 Bubble, 5 Diamond) is in: the guide's want is left
    assert j.jelly_hits_for == ["diamond"]
    assert [b for b, _r in hiveplan.jelly_targets(HIVE, PLAN)] == ["diamond"]


def keep(bee, gifted=False, hits=("diamond",)):
    t = TYPES.get(bee) or {}
    return hivejudge.keep_roll(bee, t.get("rarity", ""), t.get("colour", ""), gifted,
                               hits=hits, never_run=PLAN["never_run"])


def test_a_roll_is_kept_on_a_blue_epic_or_better_a_legendary_a_gift_or_a_mythic():
    for bee in ("bubble", "bucko", "diamond", "ninja", "tadpole", "buoyant", "music"):
        assert keep(bee), bee
    assert keep("rad", gifted=True)                      # any gifted bee
    assert keep("shy", gifted=True)


def test_a_roll_rolls_on_from_a_rare_a_colourless_epic_a_red_or_a_never_run_bee():
    for bee in ("bumble", "cool", "rad", "bomber", "commander", "demo",
                "frosty", "shy", "lion", "demon", None):
        assert not keep(bee), bee


def test_run_farm_keeps_by_the_rule_only_without_a_hive_plan():
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert "elif not plan_on and not beecard.gifted(card) and (blue_keep := hivejudge.keep_roll(" in src
    # the scan's guard is still there: a gifted cell is never a target
    assert "if is_gifted:\n                    found = []" in src


def test_a_missed_bee_rests_whatever_the_judged_list_does():
    now, rest = 1_792_490_790.0, 3 * 3600.0
    state = {"targets": ["rad"], "missed": {"rad": now - 600}}
    assert hivejudge.unmissed(["rad"], state, now, rest) == []
    assert hivejudge.unmissed(["rad", "rage"], state, now, rest) == ["rage"]
    # the old single stamp stands for every bee without its own
    assert hivejudge.unmissed(["rad"], {"missed_at": now - 600}, now, rest) == []
    assert hivejudge.unmissed(["rad"], {"missed_at": now - rest}, now, rest) == ["rad"]
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert "judged_now ==" not in src
    assert 'state.pop("missed_at", None)\n            got = ' not in src


def test_a_newly_judged_bee_is_not_rested_by_the_stored_targets_miss():
    # bookkeeping review: after a Rad miss the judged list became crimson and
    # cobalt; the rest check must ask about those, not the stored ['rad']
    now, rest = 1_792_490_790.0, 3 * 3600.0
    state = {"targets": ["rad"], "missed": {"rad": now - 600}}
    assert hivejudge.unmissed(["crimson", "cobalt"], state, now, rest) == ["crimson", "cobalt"]
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert "now_t = list(jelly_targets()[2]) or state.get(\"targets\")" in src
    assert "hivejudge.unmissed(now_t, state, time.time()," in src
