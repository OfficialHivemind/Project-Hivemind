"""B6: the night plan's order and what it says, look-only."""
from pathlib import Path

import hivemind
from hivemind.brain import nightplan

NOW = 2_000_000.0


def test_order_and_due_vicious():
    steps = nightplan.plan(NOW, {"next_at": NOW - 1}, NOW - 4000, {})
    assert [j for j, _ in steps] == ["vicious_bee", "werewolf",
                                     "night_memory_match", "wild_windy_bee"]
    line = nightplan.would(steps)
    assert line.startswith("night plan would: hunt the Vicious Bee")
    assert "werewolf is up" in line                      # 4000 s > 3630 s respawn


def test_waits_and_unknowns_said_not_guessed():
    steps = dict(nightplan.plan(NOW, {"next_at": NOW + 1800}, 0.0,
                                {"last_play": {"night": NOW - 7200}}))
    assert steps["vicious_bee"].endswith("(next hunt in 30 min)")
    assert "unknown" in steps["werewolf"]
    assert "2.0 h ago" in steps["night_memory_match"]
    wolf = dict(nightplan.plan(NOW, {}, NOW - 30, {}))["werewolf"]
    assert "up in 60 min" in wolf


def test_look_only_and_wired():
    assert nightplan.NIGHT_PLAN_LIVE is False
    src = (Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py").read_text()
    assert "nightplan.would(nightplan.plan(" in src
