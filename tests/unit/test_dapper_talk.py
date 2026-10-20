"""Dapper Bear's hand-in (2026-10-14): "Liquid Motivation" finished 2026-10-13
and was never handed in -- no walk reached him (run_farm DAPPER_TALK_LEGS,
`walk_to_dapper`), and the hand-in queue carried the one quest twice, as
`dapper_bear` and `dapper`, because one requirement's line was cut off at
"Talk to Dapper" (brain/questneeds `giver_name`)."""
from __future__ import annotations

import ast
from pathlib import Path

from hivemind.brain import questneeds

RUN_FARM = Path(__file__).resolve().parents[2] / "scripts" / "run_farm.py"
TREE = ast.parse(RUN_FARM.read_text())

# var/quests.json, 2026-10-14: the menu's own lines for the quest
LIQUID_MOTIVATION = {"giver": "", "name": "Liquid Motivation", "requirements": [
    "Collect 2 Hours of Motivating Nectar. Complete! Talk to Dapper Bear.",
    "Collect 4,000,000 Pollen from the Spider Field. Complete! Talk to Dapper Bear.",
    "Collect 25 Tokens from Planters in the Mushroom Field. Complete! Talk to Dapper",
    "Collect 25 Tokens from Planters in the Spider Field. Complete! Talk to Dapper Bear.",
    "Collect 10 Bitterberry Tokens. Complete! Talk to Dapper Bear."]}


def test_a_cut_off_name_is_its_givers():
    assert questneeds.giver_name("Dapper") == "dapper_bear"
    assert questneeds.giver_name("Gifted Bucko") == "bucko_bee"     # then the alias
    assert questneeds.giver_name("black_bear") == "black_bear"
    assert questneeds.giver_name("gifted") == "gifted"              # two givers: left alone
    assert questneeds.giver_name("stick bug") == "stick_bug"        # not a known giver


def test_one_quest_is_queued_once():
    assert questneeds.ready_titles([LIQUID_MOTIVATION]) == {"dapper_bear": "Liquid Motivation"}
    needs = questneeds.from_lines(LIQUID_MOTIVATION["requirements"])
    assert needs.ready_to_hand_in == ("dapper_bear",)


def test_the_file_written_with_both_names_folds_to_the_earlier_wait():
    previous = {"read_at": 1791915092.0, "quests": [LIQUID_MOTIVATION], "ready_since": {
        "dapper_bear": {"quest": "Liquid Motivation", "at": 1791905379.0},
        "dapper": {"quest": "Liquid Motivation", "at": 1791915092.0}}}
    out, notes = questneeds.carry_ready(previous, [LIQUID_MOTIVATION], [], {}, now=1791920000.0)
    assert out == {"dapper_bear": {"quest": "Liquid Motivation", "at": 1791905379.0}}
    assert len(notes) == 1 and "waiting since" in notes[0], notes


def _consts(*names) -> dict:
    ns: dict = {}
    for node in TREE.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in names for t in node.targets):
            exec(compile(ast.Module([node], []), str(RUN_FARM), "exec"), ns)
    return ns


C = _consts("BLUE_HQ_LOOK_LEGS", "DAPPER_JUMP", "DAPPER_SHOP_LEGS", "DAPPER_CLIMB_LEGS",
            "DAPPER_TALK_LEGS", "DAPPER_TALK_RETRY_S")


def _steps(leg):
    return list(leg) if isinstance(leg, tuple) else [leg]


def test_the_walk_is_natros_climb_then_a_look_round_then_short_legs_away_from_the_rim():
    climb, legs = C["DAPPER_CLIMB_LEGS"], C["DAPPER_TALK_LEGS"]
    # the climb measured 2026-10-13 23:37: up to and including the third jump
    jumps = [i for i, leg in enumerate(climb) if {"op": "jump_hold"} in _steps(leg)]
    assert len(jumps) == 3 and jumps[-1] == len(climb) - 1
    assert legs[:len(climb)] == climb
    rest = legs[len(climb):]
    # a full turn first, so the walk after it keeps the climb's heading
    look = C["BLUE_HQ_LOOK_LEGS"]
    assert rest[:len(look)] == look
    assert sum({"right": 1, "left": -1}[s["direction"]] for s in look) % 8 == 0
    walks = [s for leg in rest[len(look):] for s in _steps(leg)]
    assert walks and all(s["op"] == "walk" for s in walks)
    # right and in: never back (s) or straight left (a) toward the rim's
    # Retro Swarm portal, and a read every 5 studs at most
    assert {s["keys"] for s in walks} <= {"w", "d", "wa", "wd"}
    assert all(s["studs"] <= 5.0 for s in walks)
    # MEASURED 2026-10-14 13:26: the door is straight ahead after three "d"s
    assert [s["keys"] for s in walks[:4]] == ["d", "d", "d", "w"]
    assert C["DAPPER_TALK_RETRY_S"] >= 3 * 3600


def _function(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)


def _called(node) -> set:
    return {getattr(n.func, "id", None) for n in ast.walk(node) if isinstance(n, ast.Call)}


def test_he_stays_in_the_hand_in_queue():
    by_walk = next(n.value for n in ast.walk(TREE) if isinstance(n, ast.Assign)
                   and any(getattr(t, "id", None) == "_by_walk" for t in n.targets))
    assert "dapper_bear" in {e.value for e in by_walk.elts}


def test_the_walk_stops_on_his_name_and_talks_there():
    fn = _function("walk_to_dapper")
    call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "survey_by_walk")
    names = {a.id for a in ast.walk(call) if isinstance(a, ast.Name)}
    assert {"DAPPER_SHOP_VIA", "DAPPER_SHOP_UPTO", "DAPPER_TALK_LEGS", "at_stop"} <= names
    kw = {k.arg: k.value for k in call.keywords}
    assert ast.literal_eval(kw["stop_on"]) == ("dapper",)
    assert "dapper_in_shop" in _called(fn)


def test_it_runs_only_while_owed_after_a_convert_once_a_window():
    gates = [n for n in ast.walk(TREE) if isinstance(n, ast.If)
             and "walk_to_dapper" in _called(ast.Module(n.body, []))]
    # the hand-in block opens for him, and the walk itself is gated (innermost)
    assert "dapper_talk_due" in _called(gates[0].test)
    assert {"dapper_talk_due", "shop_look_due"} <= _called(gates[-1].test)
    # the key changes once a DAPPER_TALK_RETRY_S window, so a walk that read no
    # prompt ("already looked at") is not walked again inside it
    key = next(n for n in ast.walk(TREE) if isinstance(n, ast.Assign)
               and any(getattr(t, "id", None) == "dapper_key" for t in n.targets))
    assert "DAPPER_TALK_RETRY_S" in {a.id for a in ast.walk(key) if isinstance(a, ast.Name)}
