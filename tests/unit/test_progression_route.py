"""ROADMAP G10: your own progression route (brain/progression.customise,
settings progression.plan) -- put goals first, skip some, add your own, and
pick the route by name. The researched files are never changed."""
from __future__ import annotations

import copy

import yaml

from hivemind.brain import progression as prog
from hivemind.world.settings import Settings, defaults

EARLY = ("basic_eggs_to_25", "black_bear_egg_chains", "tool_ladder_early")


def _blue():
    return prog.load("blue")


def _early_ids(data):
    return [g["id"] for g in data["stages"][0]["goals"]]


def test_no_route_by_default_and_the_research_is_left_alone():
    assert defaults()["progression.plan"] == ""
    before = copy.deepcopy(_blue())
    out, notes = prog.customise(_blue(), {"first": ["tool_ladder_early"], "skip": ["basic_eggs_to_25"]})
    assert _blue() == before and notes == []
    assert out is not _blue()


def test_first_goes_first_in_your_order_and_skip_is_never_put_forward():
    out, _ = prog.customise(_blue(), {"first": ["tool_ladder_early", "black_bear_egg_chains"],
                                      "skip": ["basic_eggs_to_25"]})
    assert _early_ids(out)[:2] == ["tool_ladder_early", "black_bear_egg_chains"]
    # 12 bees: past the 10-bee gate the tool ladder waits behind
    nxt = [n.id for n in prog.next_goals(prog.Account(bees=12), 3, out)]
    assert nxt[:2] == ["tool_ladder_early", "black_bear_egg_chains"]
    assert "basic_eggs_to_25" not in [n.id for n in prog.next_goals(prog.Account(bees=12), 20, out)]


def test_your_own_goals_go_where_you_say():
    out, notes = prog.customise(_blue(), {"add": [
        {"id": "alt_30_bees", "label": "30 bees on the alt", "after": "black_bear_egg_chains"},
        {"id": "late_thing", "label": "Something late", "stage": "late"},
        {"id": "nowhere", "label": "Somewhere", "stage": "moon"},
        {"id": "basic_eggs_to_25", "label": "a twin"},
        {"label": "no id"}]})
    ids = _early_ids(out)
    assert ids[ids.index("black_bear_egg_chains") + 1] == "alt_30_bees"
    added = next(g for g in out["stages"][0]["goals"] if g["id"] == "alt_30_bees")
    assert added["kind"] == "custom" and added["source"] == ["your route"]
    assert "after" not in added and "stage" not in added
    late = next(s for s in out["stages"] if s["id"] == "late")
    assert "late_thing" in [g["id"] for g in late["goals"]]
    assert "nowhere" in [g["id"] for g in out["stages"][-1]["goals"]]
    joined = " | ".join(notes)
    assert "no stage 'moon'" in joined and "already a goal" in joined and "needs an id" in joined


def test_a_hand_written_route_cannot_break_the_plan():
    """Review 2026-10-26: `priority: high` broke every sort by priority, and
    `first: glider` was read letter by letter."""
    out, notes = prog.customise(_blue(), {
        "first": "tool_ladder_early", "skip": [True],
        "add": [{"id": "zz", "label": "ZZ", "stage": "early", "priority": "high"}]})
    assert _early_ids(out)[0] == "tool_ladder_early"
    assert next(g for g in out["stages"][0]["goals"] if g["id"] == "zz")["priority"] == 2
    assert any("'high' is not a number" in n for n in notes)
    assert not any("no goal 't'" in n or "True" in n for n in notes)
    assert prog.next_goals(prog.Account(bees=12), 30, out)


def test_unknown_ids_are_said_not_fatal():
    _, notes = prog.customise(_blue(), {"first": ["no_such"], "skip": ["nor_this"]})
    assert len(notes) == 2 and all("no goal" in n for n in notes)


def test_the_setting_picks_your_route_file_and_its_base(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVEMIND_CONFIG", str(tmp_path / "config"))
    route = prog.route_path("My Red Route")
    assert route.parent.name == "progression" and route.name == "my_red_route.yaml"
    route.parent.mkdir(parents=True)
    # the goal the researched red route puts SECOND for this account
    first = prog.next_goals(prog.Account(), 2, prog.load("red"))[1].id
    route.write_text(yaml.safe_dump({"name": "My red route", "base": "red", "first": [first]}),
                     encoding="utf-8")
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"progression.hive": "blue",
                                    "progression.plan": "My Red Route"}))
    got = prog.progress(tmp_path, Settings(path), n=1)
    assert got.hive == "red"
    assert got.next and got.next[0].id == first
    # a name with no file is the researched route, as before
    path.write_text(yaml.safe_dump({"progression.plan": "missing"}))
    assert prog.progress(tmp_path, Settings(path)).hive == "blue"


def test_a_goal_after_another_takes_its_priority_but_never_a_skip():
    """Goals sort by priority, so a goal put after a priority-1 goal must be a
    1 too, or it lands with the 2s. A route's own priority still wins."""
    out, _ = prog.customise(_blue(), {"add": [
        {"id": "mine", "label": "Mine", "after": "black_bear_egg_chains"},
        {"id": "mine3", "label": "Mine 3", "after": "black_bear_egg_chains", "priority": 3}]})
    goals = {g["id"]: g for g in out["stages"][0]["goals"]}
    assert goals["black_bear_egg_chains"]["priority"] == 1
    assert goals["mine"]["priority"] == 1 and goals["mine3"]["priority"] == 3
    nxt = [n.id for n in prog.next_goals(prog.Account(bees=12), 4, out)]
    assert nxt.index("mine") == nxt.index("black_bear_egg_chains") + 1
    skipped, _ = prog.customise(_blue(), {"skip": ["black_bear_egg_chains"],
                                          "add": [{"id": "m", "label": "M", "after": "black_bear_egg_chains"}]})
    m = next(g for g in skipped["stages"][0]["goals"] if g["id"] == "m")
    assert m["priority"] < prog.SKIP_PRIORITY
