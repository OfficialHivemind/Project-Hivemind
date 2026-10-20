"""brain/goals.replan_lines + Watch.replan (ROADMAP G7): a rare drop re-plans
and says what changed, or that the plan holds. Made-up plans, no files."""
from __future__ import annotations

from hivemind.brain import goals
from hivemind.brain.goals import Plan, Row, replan_lines


def _plan(*rows):
    return Plan(rows=[Row(key=k, label=lbl, state=st, owned=own) for k, lbl, st, own in rows])


def test_next_goal_and_moved_states_are_told():
    before = _plan(("mask", "Diamond Mask", goals.BLOCKED, False),
                   ("belt", "Belt", goals.HONEY_READY, False))
    after = _plan(("mask", "Diamond Mask", goals.READY, False),
                  ("belt", "Belt", goals.HONEY_READY, False))
    lines = replan_lines("+1 Mythic Egg (now 1)", before, after)
    assert lines == [f"re-plan after +1 Mythic Egg (now 1): Diamond Mask "
                     f"{goals.BLOCKED} -> {goals.READY}"]
    after2 = _plan(("mask", "Diamond Mask", goals.READY, True),
                   ("belt", "Belt", goals.HONEY_READY, False))
    first = replan_lines("x", before, after2)[0]
    assert "next goal was the Diamond Mask, now the Belt" in first


def test_unchanged_plan_holds_and_no_plan_is_said():
    p = _plan(("belt", "Belt", goals.HONEY_READY, False))
    assert replan_lines("x", p, p) == [f"re-plan after x: the plan holds, next is "
                                       f"the Belt ({goals.HONEY_READY})"]
    assert replan_lines("x", None, p) == [f"re-plan after x: next is the Belt ({goals.HONEY_READY})"]
    assert replan_lines("x", p, None) == ["re-plan after x: could not plan"]


def test_watch_replan_ticks_and_says(tmp_path):
    said = []
    w = goals.Watch(tmp_path, say=said.append)
    before = _plan(("belt", "Belt", goals.BLOCKED, False))
    after = _plan(("belt", "Belt", goals.READY, False))
    w.plan = before
    w._said_shopping = ("old",)
    w._plan = lambda: after
    w._say_shopping = lambda plan: said.append("shopping")
    assert w.replan("+1 Star Jelly (now 2)") is after
    assert "shopping" in said
    assert said[-1] == f"re-plan after +1 Star Jelly (now 2): Belt {goals.BLOCKED} -> {goals.READY}"
