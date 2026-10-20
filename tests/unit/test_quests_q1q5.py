"""Q1 + Q5 (docs/pending/quests-q1q5.md): a switched-off giver's finished quest
is not queued for a hand-in, and the fields only its quests want are named
(look-only, QUEST_FIELDS_BY_SWITCH_LIVE).

run_farm.py is a script, so its source is read beside the imported package."""
from __future__ import annotations

import ast
import pathlib

import hivemind
from hivemind.brain import questneeds
from hivemind.brain import questvalue as qv

RUN_FARM = pathlib.Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py"
SOURCE = RUN_FARM.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

# MEASURED 2026-10-24 22:59 (run-1206), the live menu read, cut to three quests
MENU = [
    {"name": "Weed Wacker 3", "requirements": [
        "Collect 400,000,000 Pollen from the Pepper Patch. 0/400,000,000",
        "Collect 200,000,000 Pollen from the Bamboo Field. 44,336/200,000,000",
        "Collect 100,000,000 Pollen from the Clover Field. 31,914/100,000,000"]},
    {"name": "Brown Bear: Bamb-Spide", "requirements": [
        "Collect 4,100,000 Pollen from the Bamboo Field. Complete!",
        "Collect 4,100,000 Pollen from the Spider Field. 54,503/4,100,000"]},
    {"name": "Bucko Bee: Medley", "requirements": [
        "Collect 13,000,000 Goo from the Bamboo Field. 2,020,807/13,000,000"]},
    {"name": "Some New Quest", "requirements": [
        "Collect 1,000 Pollen from the Rose Field. 0/1,000"]},
]
TABLE = {qv._key("Weed Wacker 3"): ("black_bear", {"honey": 1})}
OFF = {"black_bear", "brown_bear", "polar_bear"}     # settings.yaml, 24 Oct 22:43


def test_fields_only_a_switched_off_givers_quests_want():
    off = qv.fields_only_for_off(MENU, lambda g: g not in OFF, TABLE)
    # bamboo stays: Bucko (on) still wants its goo; rose: no known giver
    assert set(off) == {"pepper", "clover", "spider"}
    assert off["pepper"] == ["Weed Wacker 3"] and off["spider"] == ["Brown Bear: Bamb-Spide"]
    assert qv.fields_only_for_off(MENU, lambda g: True, TABLE) == {}


def test_giver_of_reads_the_prefix_then_the_wiki_table():
    assert qv.giver_of("Polar Bear: Trail Mix", {}) == "polar_bear"
    assert qv.giver_of("Weed Wacker 3", TABLE) == "black_bear"
    assert qv.giver_of("Repairing Robo Bear", TABLE) == ""


def test_fields_dropped_takes_pollen_and_goo():
    needs = questneeds.from_lines([r for q in MENU for r in q["requirements"]])
    assert needs.field_remaining("pepper") > 0 and "bamboo" in needs.goo
    needs.fields_dropped(["pepper", "bamboo"])
    assert needs.field_remaining("pepper") == 0 and "bamboo" not in needs.goo
    assert needs.field_remaining("clover") > 0


def test_switched_off_giver_is_not_queued_and_the_field_drop_is_look_only():
    rebuild = next(n for n in ast.walk(TREE)
                   if isinstance(n, ast.FunctionDef) and n.name == "rebuild_queue")
    body = ast.get_source_segment(SOURCE, rebuild)
    assert body.index("wanted_givers(settings, (g,))") < body.index('queue["ready"] = ready')
    assert "finished, but not handed in" in body
    # (wrapped in the quest stall guard's drop since rp/stallguard, also look-only)
    assert SOURCE.count("planner.quest_needs = stalls_dropped(off_givers_dropped("
                        "goo_where_gumdrops(") == 2
    assert "\nQUEST_FIELDS_BY_SWITCH_LIVE = False\n" in SOURCE
    assert "\nQUEST_STALL_LIVE = False\n" in SOURCE
