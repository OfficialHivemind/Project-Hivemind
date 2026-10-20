"""scripts/landing_rate.py (A6): one verdict per gather trip's walk home from
the run log's own lines, the worst one winning, and the day's line."""
import importlib.util
import sys

import hivemind
from pathlib import Path

ROOT = Path(hivemind.__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("landing_rate", ROOT / "scripts" / "landing_rate.py")
lr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lr)


def _trip(field, *body, off=False):
    lines = [f"    12:00:00  the trip aimed at {field} and the game credited {field} "
             f"while it was out; the ground moved (+0, +0) px net"]
    if off:
        lines.append(f"    12:00:01  {lr.OFF_FIELD}, so the character is not in {field} any more")
    return lines + list(body) + ["    12:05:00  cycle 3: 1 pollen"]


def test_walk_verdicts_and_rate():
    raw = (_trip("pine tree", "    12:01:00  to hive: arrived — on our own hive pad")
           + _trip("pepper", "    look 0: no hive in view (0 yellow px), turning",
                   "    12:02:00  to hive: did not get there — turned a full circle and "
                   "never saw the hive's yellow wall (most was 5,637 px over all 9 looks)",
                   "    12:02:01  respawned onto our own pad (stranded, instead of a rejoin)",
                   off=True)
           + _trip("bamboo", "    look 0: no hive in view (0 yellow px), turning",
                   "    12:01:00  to hive: arrived — on our own hive pad")
           + _trip("stump", "    12:01:00  whirligig home: on our pad 0.3s after the press")
           + _trip("pepper", "    12:01:00  whirligig rescue: on our pad 0.4s after the press",
                   "    12:01:30  could not reach the hive 1 times — asking for a rejoin")
           + ["    12:06:00  the trip aimed at clover and the game credited clover"])  # no cycle yet
    ws = lr.walks([(1_000.0 + i, line) for i, line in enumerate(raw)])
    assert [(w["field"], w["verdict"], w["off"]) for w in ws] == [
        ("pine_tree", "landed", False), ("pepper", "rescued", True),
        ("bamboo", "sight", False), ("stump", "whirligig", False),
        ("pepper", "rejoin", False)]
    assert ws[1]["why"] == "turned a full circle and never saw the hive's yellow wall"
    # the planned Whirligig is no walk: 2 landed (one by sight) of 4 counted
    assert lr.rate(ws) == (2, 4, 50.0)
    line = lr.today_line(ws)
    assert line.startswith("Walks home today: 50% landed (2 of 4)"), line
    assert "worst pepper 0 of 2, 1 began off the field" in line, line
    assert "rescued (off-field start)" in lr.report(ws)
    assert lr.today_line([]) == "Walks home today: none judged yet"


def test_pepper_chase_stop_is_look_only_and_said_once_a_trip():
    """STRAND_NO_CHASE (walkhome98): Pepper's off-field strands come with chasing;
    look-only it chases as before and says so once a trip."""
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert "STRAND_NO_CHASE = frozenset({\"pepper\"})" in src
    assert "STRAND_NO_CHASE_LIVE = True" in src
    body = src[src.index("def chase_off_here"):src.index("def loot_chase_once")]
    # the fixed no-chase fields first, then the strand fields, which stop only when live
    assert body.index("in NO_CHASE_FIELDS") < body.index("in STRAND_NO_CHASE")
    assert "if STRAND_NO_CHASE_LIVE:\n                    return True" in body
    assert 'last_plan.get("strand_said") != last_plan.get("trip_began")' in body
    assert "no chase would: skip the token chases" in body
