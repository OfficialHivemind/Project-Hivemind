"""B7: a field is risky while its danger-3 bug-run mob (the Werewolf) is up,
read off the KillLog's booked kills; no kill on record is unknown, never a
skip; danger-2 mobs and the Mondo Chick never shut a field here. Look-only in
run_farm."""
from pathlib import Path

import hivemind
from hivemind.act import bugrun
from hivemind.brain import mobtable, threat

NOW = 1_000_000.0
WOLF_RESPAWN = mobtable.respawn("werewolf")


def _log(kills):
    return lambda field, slug: kills.get((field, slug), 0.0)


def test_mondo_never_killed_does_not_shut_mountain_top():
    # run-1285:50: "skip mountain top -- the Mondo Chick (danger 3) is
    # up there: no kill on record" on every trip. Now: unknown, no skip.
    assert threat.risky_mob_up("mountain_top", _log({}), NOW) is None
    # even a booked Mondo kill long ago does not count: not a bug-run timer mob
    old = {("mountain_top", "mondo_chick"): NOW - 7200}
    assert threat.risky_mob_up("mountain_top", _log(old), NOW) is None


def test_werewolf_with_no_kill_on_record_is_unknown():
    assert threat.risky_mob_up("pumpkin", _log({}), NOW) is None


def test_werewolf_up_161_min_after_its_last_kill():
    # run-1285:36: pumpkin, pine tree and cactus, "last killed 161 min ago"
    late = {("pumpkin", "werewolf"): NOW - 161 * 60}
    for field in ("pumpkin", "pine_tree", "cactus"):
        why = threat.risky_mob_up(field, _log(late), NOW)
        assert why and "Werewolf" in why and "last killed 161 min ago" in why


def test_werewolf_down_after_a_kill_until_its_respawn():
    killed = {("pumpkin", "werewolf"): NOW - 600}
    assert threat.risky_mob_up("pumpkin", _log(killed), NOW) is None
    assert threat.risky_mob_up("pine_tree", _log(killed), NOW) is None


def test_a_visit_is_not_a_kill(tmp_path):
    log = bugrun.KillLog(tmp_path / "k.json", clock=lambda: NOW)
    log._row("pumpkin", "werewolf")["last_try"] = NOW - 60   # visited, no kill
    assert log.last("pumpkin", "werewolf") == NOW - 60
    assert log.last_kill("pumpkin", "werewolf") == 0.0
    assert threat.risky_mob_up("pumpkin", log.last_kill, NOW) is None
    log.killed("pumpkin", ["werewolf"], at=NOW - WOLF_RESPAWN - 1)
    assert "last killed" in threat.risky_mob_up("pumpkin", log.last_kill, NOW)


def test_danger_two_fields_are_never_shut():
    late = {("rose", "scorpion"): NOW - 99999}
    assert threat.risky_mob_up("rose", _log(late), NOW) is None      # Scorpions
    assert threat.risky_mob_up("dandelion", _log({}), NOW) is None   # no mobs


def test_run_farm_wires_it_look_only_on_kills():
    src = (Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py")
    text = src.read_text(encoding="utf-8")
    assert "RISK_SKIP_LIVE = False" in text
    assert "or risky_mob_up(field))" in text
    assert "risky_mob_up(field, bugrun_log.last_kill," in text
