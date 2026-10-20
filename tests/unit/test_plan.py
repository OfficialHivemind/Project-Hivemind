"""brain/plan: the one-plan recipes, apply/undo, the goals prepend, status."""
from __future__ import annotations

import json

import pytest
import yaml

from hivemind.brain import goals as goals_plan
from hivemind.brain import plan
from hivemind.world.settings import (LOCKED, NOT_WIRED, SECRET, SECTIONS,
                                     Settings, defaults)

SCHEMA = {e[0]: e for _, entries in SECTIONS for e in entries}


def test_every_recipe_key_is_a_live_wired_setting_of_the_right_type():
    for choice, recipe in plan.RECIPES.items():
        for key, value in recipe.items():
            assert key in SCHEMA, (choice, key)
            assert key not in NOT_WIRED and key not in LOCKED and key not in SECRET, (choice, key)
            assert key in plan.LIVE or key in plan.EXTRA_KEYS, (choice, key)
            assert type(value) is type(SCHEMA[key][3]), (choice, key)
    assert set(plan.RECIPES) == set(SCHEMA["plan.goal"][5]) == set(plan.CHOICES)
    assert not plan.RECIPES["custom"]
    assert plan.RECIPES["macro"] == {"mode.macro": True}
    assert plan.RECIPES["progress"].get("combat.bosses") is None    # never switched on


def test_a_quest_plan_turns_on_its_bear_only():
    got = plan.resolve("quests", "Bucko Bee")
    assert got["quests.bucko"] is True and got["quests.first"] is True
    assert "quests.polar" not in got
    assert plan.giver_key("black bear") == "quests.black_bear"
    assert plan.giver_key("nobody") is None


def _config(tmp_path, body=None):
    path = tmp_path / "cfg" / "settings.yaml"
    path.parent.mkdir()
    if body is not None:
        path.write_text(yaml.safe_dump(body))
    return path


def test_custom_writes_nothing_and_an_old_file_is_custom(tmp_path):
    path = _config(tmp_path, {"quests.enabled": True})
    before = path.read_bytes()
    assert Settings(path).get("plan.goal") == "custom"
    assert plan.apply("custom", config=path) == {"changed": {}, "kept": {}, "skipped": []}
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        plan.apply("nonsense", config=path)


def test_apply_writes_the_recipe_keeps_yours_and_undo_restores(tmp_path):
    path = _config(tmp_path, {"combat.bug_runs": True, "economy.planters": True})
    out = plan.apply("honey", config=path)
    s = Settings(path)
    assert s.get("plan.goal") == "honey"
    assert s.get("economy.boosters") is True and s.get("gather.follow_boost") is True
    # their own non-default switch, with no plan before: theirs
    assert out["kept"] == {"combat.bug_runs": (True, False)}
    assert s.get("combat.bug_runs") is True
    assert plan.conflicts(path) == {"combat.bug_runs": (True, False)}
    # given back, the plan takes it
    plan.apply("honey", config=path, take=("combat.bug_runs",))
    assert Settings(path).get("combat.bug_runs") is False
    # A -> B -> undo is A again
    a = dict(Settings(path).values)
    plan.apply("tickets", config=path)
    assert Settings(path).get("economy.boosters") is True         # tickets leaves it
    assert Settings(path).get("combat.commando") is True
    plan.undo(path)
    assert Settings(path).values == a
    # a hand change after a plan survives the next plan
    yaml_body = yaml.safe_load(path.read_text())
    yaml_body["gather.chase_tokens"] = False
    path.write_text(yaml.safe_dump(yaml_body))
    out = plan.apply("progress", config=path)
    assert out["kept"]["gather.chase_tokens"] == (False, True)


def test_the_plan_target_goes_first_in_the_goal_order(tmp_path):
    s = {"plan.goal": "item", "plan.target": "Tide Popper", "goals.order": ""}
    assert plan.targets(s) == ["Tide Popper"]
    got = plan.prepend(s, [], {"default_order": ["porcelain_dipper"]})
    assert got == ["Tide Popper", "porcelain_dipper"]
    assert plan.prepend({"plan.goal": "honey", "plan.target": "x"}, ["a"], {}) == ["a"]
    built = goals_plan.from_files(settings=s, var_root=tmp_path, first=[],
                                  rows=[], clock=lambda: 0.0)
    assert [r.key for r in built.rows][0] == "tide_popper"


def test_a_target_only_the_progression_knows_stays_in_the_order(tmp_path):
    """Supreme Star Amulet is in the progression files, not goals.yaml: the
    Fuzzy alt plan's order must keep it, not drop it as unknown."""
    s = {"plan.goal": "item", "plan.target": "Supreme Star Amulet", "goals.order": ""}
    built = goals_plan.from_files(settings=s, var_root=tmp_path, first=[],
                                  rows=[], clock=lambda: 0.0)
    assert [r.key for r in built.rows][0] == "supreme_star_amulet"
    assert built.unknown_names == []


def test_alt_plans_read_their_targets_from_the_hook_file(tmp_path, monkeypatch):
    alts = tmp_path / "alt_goals.yaml"
    alts.write_text(yaml.safe_dump({
        "fuzzy_alt": {"targets": ["Fuzzy Bee"], "on": {"combat.bosses": True,
                                                       "safety.never_chat": False}},
        "tad_alt": {"targets": ["Tadpole Bee", "Fuzzy Bee"]}}))
    real = plan.alt_goals
    monkeypatch.setattr(plan, "alt_goals", lambda path=None: real(alts))
    assert plan.alt_targets("hybrid") == ["Fuzzy Bee", "Tadpole Bee"]
    got = plan.resolve("fuzzy_alt")
    assert got["combat.bosses"] is True and "safety.never_chat" not in got
    assert plan.targets({"plan.goal": "tad_alt"}) == ["Tadpole Bee", "Fuzzy Bee"]
    assert plan.alt_targets("fuzzy_alt", {}) == []        # no file: the progress recipe


def test_status_on_fixture_files(tmp_path):
    var = tmp_path / "var"
    (var / "progression").mkdir(parents=True)
    (var / "bees.json").write_text(json.dumps(
        {"total": 30, "read_at": 900.0, "gifted": [],
         "bees": {"rad": 6, "rascal": 2, "bumble": 1, "basic": 3}}))
    (var / "purchases.json").write_text(json.dumps(
        [{"item": "Honey Mask", "ok": True, "at": 400.0}, {"item": "x", "ok": False}]))
    (var / "progression" / "milestones.jsonl").write_text(
        json.dumps({"text": "30 bees", "at": 600.0}) + "\n")
    (var / "trips.jsonl").write_text(json.dumps({
        "at": 1000.0, "action": "gather", "chosen": "Pine Tree", "aimed_at": "Pine Tree",
        "candidates": [{"field": "Pine Tree", "why": "blue pollen for Bucko"}]}) + "\n")
    s = {**defaults(), "plan.goal": "item", "plan.target": "Tide Popper"}
    got = plan.status(var, s, clock=lambda: 1060.0)
    assert set(got) == {"now", "why", "next", "goal", "proof"}
    assert got["now"] == "Gathering at Pine Tree (1 min ago)"
    assert got["why"] == "blue pollen for Bucko"
    assert got["goal"]["hive"] == "red" and "guessed" in got["goal"]["hive_why"]
    assert got["next"][0]["state"] == "no"
    assert {"what": "250 Gifted Bucko Bee quests", "state": "?"} in got["next"]   # unparsed: '?'
    assert got["proof"][0].startswith("bought Honey Mask")
    assert any("30 bees" in p for p in got["proof"])
    # nothing written yet: still a status, never an error
    empty = plan.status(tmp_path / "none", defaults(), clock=lambda: 0.0)
    assert empty["now"] == "" and empty["proof"] == [] and empty["goal"]["id"] == "custom"


def test_the_hive_colour_guess_sets_the_route(tmp_path):
    (tmp_path / "bees.json").write_text(json.dumps({"bees": {"bubble": 4, "rad": 1}}))
    assert plan.hive_colour(tmp_path)[0] == "blue"
    assert plan.resolve("progress", var_root=tmp_path)["progression.hive"] == "blue"
    assert "progression.hive" not in plan.resolve("macro", var_root=tmp_path)
    assert plan.hive_colour(tmp_path / "nope")[0] is None


def test_the_installers_seed_is_not_counted_as_yours(tmp_path):
    """A fresh install's settings.yaml is safe-first-run.yaml (mode.macro on,
    errands off): the first plan click must win over it, not keep it all
    (FOUND 2026-10-26 in the plan-gui --demo render: Hybrid kept macro mode)."""
    from hivemind.datapaths import data
    path = _config(tmp_path)
    path.write_text(data("presets", "safe-first-run.yaml").read_text(encoding="utf-8"))
    out = plan.apply("progress", config=path)
    assert out["kept"] == {}
    s = Settings(path)
    assert s.get("mode.macro") is False and s.get("quests.enabled") is True


def test_remote_sets_checks_and_undoes_in_plain_words(tmp_path):
    """Telegram's /plan, as the bot runs it (run_farm on_command -> remote)."""
    path = _config(tmp_path, {})
    said = plan.remote("Honey", config=path)
    assert said.startswith("Plan set: Make the most honey.") and "/plan undo" in said
    assert Settings(path).get("plan.goal") == "honey"
    plan.remote("quests", "bucko", config=path)
    s = Settings(path)
    assert s.get("plan.goal") == "quests" and s.get("plan.target") == "bucko"
    assert s.get("quests.bucko") is True
    assert plan.remote("undo", config=path).startswith("Undone:")
    assert Settings(path).get("plan.goal") == "honey"
    # an unknown name is never guessed: the closest names, and nothing written
    before = path.read_bytes()
    said = plan.remote("honny", config=path)
    assert "honey" in said and said.endswith("Nothing was changed.")
    assert "Bucko Bee" in plan.check("quests", "bukco")
    assert "Tide Popper" in plan.check("item", "tide poper")
    assert plan.check("item", "Tide Popper") == "" and plan.check("tickets") == ""
    assert path.read_bytes() == before
    # custom: only the plan's own key, every switch stays
    honey = {k: v for k, v in Settings(path).values.items() if not k.startswith("plan.")}
    assert plan.remote("custom", config=path).startswith("Plan: Your own setup")
    s = Settings(path)
    assert s.get("plan.goal") == "custom"
    assert {k: v for k, v in s.values.items() if not k.startswith("plan.")} == honey
