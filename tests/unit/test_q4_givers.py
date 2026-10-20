"""Q4 (docs/pending/quests-q4.md): the Spirit Bear, Dapper Bear and Riley Bee.

- A giver's route that has never landed is not walked again until it changes
  (brain/skills NEVER_LANDED_AFTER; run_farm `_giver_route_rests`).
- A survey walk -- a field's route cut short to reach a place, like Dapper's
  natro_out_stump to the Stump's rim -- waits out a speed buff first, as an
  errand's walk does (run_farm `wait_out_the_morph(place=True)`).
- Dapper's walks that never read his name rest him (GIVER_MISS_FILE).

run_farm.py is a script, so its source is read beside the imported package."""
from __future__ import annotations

import ast
import pathlib

import hivemind
from hivemind.brain import skills

RUN_FARM = pathlib.Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py"
TREE = ast.parse(RUN_FARM.read_text())


def _function(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)


def _calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == name]


def test_a_route_that_never_landed_is_left_until_it_changes():
    # var/skill_stats.json, 2026-10-19: natro_out_riley_bee 0 of 33, its window 0 of 7
    riley = skills.Skill(route="natro_out_riley_bee", elsewhere=33, recent=["elsewhere"] * 7)
    assert riley.quarantined and riley.never_lands
    # one landing ever, and it is only quarantined (the time-based rest still applies)
    brown = skills.Skill(route="natro_out_brown_bear", landed=1, elsewhere=48,
                         recent=["elsewhere"] * 10)
    assert brown.quarantined and not brown.never_lands
    # too few tries to say "never"
    assert not skills.Skill(route="x", elsewhere=4, recent=["elsewhere"] * 4).never_lands
    # a changed route starts its window afresh (`watch_steps`): not quarantined, tried again
    assert not skills.Skill(route="natro_out_riley_bee", elsewhere=33, recent=[]).never_lands
    # and the giver rest asks it before the time-based rest lets the walk go
    rests = _function("_giver_route_rests")
    src = ast.get_source_segment(RUN_FARM.read_text(), rests)
    assert src.index("never_lands") < src.index("GIVER_MISS_REST_SECONDS")


def test_a_survey_walk_waits_out_a_speed_buff_like_an_errand():
    wait = _function("wait_out_the_morph")
    assert [a.arg for a in wait.args.args] == ["name", "place"]
    src = ast.get_source_segment(RUN_FARM.read_text(), wait)
    assert "errand_walk = place or " in src
    for fn in ("survey_by_walk", "look_at_a_surveyed_shop"):
        calls = _calls(_function(fn), "wait_out_the_morph")
        assert calls and all(any(k.arg == "place" and k.value.value is True
                                 for k in c.keywords) for c in calls), fn


def test_dapper_rests_after_walks_that_never_read_his_name():
    due = _function("dapper_talk_due")
    resting = _calls(due, "_giver_resting")
    assert resting and resting[0].args[0].value == "dapper_bear"
    noted = _calls(_function("walk_to_dapper"), "_note_giver_miss")
    assert noted and noted[0].args[0].value == "dapper_bear"
