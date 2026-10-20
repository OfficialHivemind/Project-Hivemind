"""brain/arms: the per-field convert and chase arms -- off by default, and the
chase arm can only ever turn chasing OFF."""
from __future__ import annotations

import random

import hivemind
from hivemind.brain import arms as A


def make(tmp_path, seed=1):
    return A.Arms(tmp_path / "experiments.json", rng=random.Random(seed))


def test_off_by_default_the_trip_runs_on_the_owners_settings(tmp_path):
    assert A.ARMS_LIVE is False
    a = make(tmp_path)
    assert a.begin("pine_tree", 0.9, True) == {A.CONVERT_AT: 0.9, A.CHASE: 1.0}
    assert a.begin("clover", 0.9, False)[A.CHASE] == 0.0
    assert a.would("pine_tree", True).startswith("arms would (pine_tree): convert at ")


def test_live_picks_from_the_arm_values_and_never_turns_chasing_on(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "ARMS_LIVE", True)
    a = make(tmp_path)
    for _ in range(40):
        use = a.begin("pine_tree", 0.9, True)
        assert use[A.CONVERT_AT] in A.VALUES[A.CONVERT_AT]
        assert use[A.CHASE] in (0.0, 1.0)
        assert a.begin("cactus", 0.9, False)[A.CHASE] == 0.0      # off stays off
        assert "chase" not in a.would("cactus", False)


def test_a_trip_files_its_honey_a_second_under_what_it_ran_with(tmp_path):
    a = make(tmp_path)
    a.begin("pine_tree", 0.9, True)
    said = a.learn({"honey": 30_000_000, "seconds": 600})
    assert said == ["convert at 0.9", "chase 1"]
    exp = a.exps[A.CONVERT_AT]
    arm = next(x for x in exp.arms if x.value == 0.9)
    assert arm.tries == 1 and abs(arm.reward - 0.5) < 1e-9     # 50k/s over the 100k scale
    assert a.learn({"honey": 1, "seconds": 1}) == []           # nothing begun: nothing filed


def test_an_unmeasured_trip_or_an_off_arm_value_teaches_nothing(tmp_path):
    a = make(tmp_path)
    a.begin("pine_tree", 0.9, True)
    assert a.learn({"honey": None, "seconds": 600}) == []
    a.begin("pine_tree", 0.75, False)                          # 75% is not an arm value
    assert a.learn({"honey": 9_000_000, "seconds": 300}) == ["chase 0"]


def test_run_farm_wires_the_arms_off_by_default_and_only_ever_stops_chasing():
    from pathlib import Path
    src = (Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py").read_text(
        encoding="utf-8")
    assert "field_arms = arms_mod.Arms(EXPERIMENTS_FILE)" in src
    assert "if arms_mod.ARMS_LIVE:" in src and "field_arms.learn(row)" in src
    # the chase arm is asked only where chasing is already on, and can only add a stop
    assert "chase_here = bool(chase_on) and not chase_off_here()" in src
    assert 'last_plan["arm_no_chase"] = chase_here and not use[arms_mod.CHASE]' in src
