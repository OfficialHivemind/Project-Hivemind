"""brain/experiment pattern_ab (ROADMAP T3/P5): per-field pattern A/B in hour
blocks, promoting a challenger only when it is clearly better."""
import json
import random
from pathlib import Path

import pytest

import hivemind
from hivemind.brain import experiment as E

ROOT = Path(hivemind.__file__).resolve().parents[2]
TRIPS = Path.home() / "Hivemind" / "var" / "trips.jsonl"
H = 3600.0


def trip(at, pattern, rate, landed=True, **kw):
    row = {"at": at, "pattern": pattern, "aimed_at": "pine_tree", "credited": "pine_tree",
           "gather_seconds": 200.0, "pollen": int(rate * 200), "deaths": 0,
           "routes": [{"kind": "home", "outcome": "landed" if landed else "elsewhere"}]}
    row.update(kw)
    return row


def world(gain=0.0, landed_b=1.0, hours=40, seed=1):
    """Two arms taking hour turns by block_arm, three trips an hour, the
    hour's own luck shared by its trips (as buffs and the server are)."""
    rng, rows = random.Random(seed), []
    for h in range(hours):
        at = 1_000_000 * H + h * H
        arm = E.block_arm(at, ["own", "new"])
        luck = rng.gauss(1.0, 0.1)
        for k in range(3):
            rate = 30_000 * luck * rng.gauss(1.0, 0.05) * (1 + gain if arm == "new" else 1)
            rows.append(trip(at + 600 * k, arm, rate,
                             landed=arm == "own" or rng.random() < landed_b))
    return rows, at + H


@pytest.mark.parametrize("arms", [["a", "b"], ["a", "b", "c"], list("abcde")])
def test_each_arm_gets_every_hour_of_the_day(arms):
    # a field's own pattern plus the 4 own shapes is 5 arms
    seen = {arm: set() for arm in arms}
    for h in range(24 * len(arms)):
        seen[E.block_arm(h * H, arms)].add(h % 24)
    assert all(s == set(range(24)) for s in seen.values())


def test_a_clearly_better_pattern_is_promoted():
    rows, now = world(gain=0.3)
    got = E.pattern_ab(rows, ["own", "new"], now)
    assert got["winner"] == got["walk"] == "new"
    assert got["verdicts"]["new"]["gain_ci"][0] > 0
    assert got["line"].startswith("promote new")


def test_no_difference_promotes_nothing_and_keeps_taking_turns():
    rows, now = world(gain=0.0)
    got = E.pattern_ab(rows, ["own", "new"], now)
    assert got["winner"] is None and got["verdicts"]["new"]["verdict"] == "unsure"
    assert got["turns"] == ["own", "new"] and got["walk"] == E.block_arm(now, ["own", "new"])


def test_more_pollen_but_missed_walks_home_is_not_promoted():
    rows, now = world(gain=0.3, landed_b=0.5)
    got = E.pattern_ab(rows, ["own", "new"], now)
    assert got["verdicts"]["new"]["verdict"] == "worse" and got["winner"] is None
    assert got["turns"] == ["own"] and got["walk"] == "own"


def test_too_few_hours_never_promote():
    rows, now = world(gain=0.5, hours=10)
    got = E.pattern_ab(rows, ["own", "new"], now)
    assert got["verdicts"]["new"]["verdict"] == "too few" and got["winner"] is None
    assert "too few" in got["line"]


def test_what_counts_in_a_block():
    rows = [trip(0, "p", 10_000),
            trip(1, "p", 99_000, deaths=1),                      # died: out
            trip(2, "p", 99_000, gather_seconds=30.0),          # too short: out
            trip(3, "p", 99_000, credited="pumpkin"),           # mis-delivered: out
            trip(4, "p", 10_000, credited="rose", aimed_at="rose_field"),   # alias: in
            trip(5, "p", 10_000, routes=[], recoveries=["jump", "go_home"],
                 gather_ended="the pollen counter has not risen for 86s off the flowers"),
            trip(6, "q", 99_000)]                               # another arm
    (block,) = E.pattern_blocks(rows, ["p"])["p"]
    assert block["trips"] == 3 and block["pollen"] == 3 * 10_000 * 200
    assert (block["landed"], block["judged"], block["drift"]) == (2, 2, 1)


@pytest.mark.skipif(not TRIPS.exists(), reason="the owner's ledger is not on this machine")
def test_replayed_ledger_a_copy_of_itself_is_not_promoted_but_a_real_gain_is():
    # var/trips.jsonl up to 27 Oct (the measurement in this commit):
    # Pine Tree's own pattern, its hours split into two made-up arms
    end = 1793047406.7
    rows = []
    for line in TRIPS.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("pattern") == "natro_pattern_pine_tree_as_natro" and row["at"] <= end:
            rows.append(dict(row, pattern=E.block_arm(row["at"], ["A", "B"])))
    same = E.pattern_ab(rows, ["A", "B"], end)
    assert same["verdicts"]["B"]["verdict"] == "unsure" and same["winner"] is None
    boosted = [dict(r, pollen=int(r["pollen"] * 1.4)) if r["pattern"] == "B" and r.get("pollen")
               else r for r in rows]
    assert E.pattern_ab(boosted, ["A", "B"], end)["winner"] == "B"


def test_ships_shadow_and_is_wired_into_the_hourly_look_back():
    assert E.PATTERN_AB_LIVE is False
    farm = (ROOT / "scripts/run_farm.py").read_text(encoding="utf-8")
    assert "pattern_ab_hour(rows_all, now)" in farm
    assert "pattern_ab_seen.get(target) if experiment.PATTERN_AB_LIVE else None" in farm


# ---- AI-N5: the per-field pick, shape first, then the champion's twin ------
def three_arms(gain_c=0.0, hours=120, seed=2):
    """own, b, c by block_arm; `b` 30% worse (so it drops out), `c` `gain_c`."""
    rng, rows = random.Random(seed), []
    for h in range(hours):
        at = 1_000_000 * H + h * H
        arm = E.block_arm(at, ["own", "b", "c"])
        luck = rng.gauss(1.0, 0.1)
        k = {"own": 1.0, "b": 0.7, "c": 1 + gain_c}[arm]
        rows += [trip(at + 600 * i, arm, 30_000 * luck * rng.gauss(1.0, 0.05) * k)
                 for i in range(3)]
    return rows, at + H


def test_no_champion_yet_means_stage_one_and_no_twin():
    rows, now = world(gain=0.0)
    got = E.field_pick(rows, ["own", "new"], lambda n: n + "_twin", now)
    assert got["stage"] == 1 and got["champion"] is None
    assert got["walk"] == E.pattern_ab(rows, ["own", "new"], now)["walk"]   # unchanged


def test_a_promoted_shape_then_meets_its_twin():
    rows, now = three_arms(gain_c=0.4)
    got = E.field_pick(rows, ["own", "b", "c"], {"c": "c75"}.get, now)
    assert got["champion"] == "c" and got["stage"] == 2
    assert got["turns"] == ["c", "c75"] and got["walk"] in ("c", "c75")
    assert "not walked yet: c75" in got["line"]
    assert "the shape is settled: promote c" in got["line"]


def test_own_pattern_is_champion_only_when_every_challenger_is_worse():
    rows, now = three_arms(gain_c=-0.3)
    got = E.field_pick(rows, ["own", "b", "c"], {"own": "own_spot"}.get, now)
    assert got["champion"] == "own" and got["turns"] == ["own", "own_spot"]
    # no challengers at all (Stump: no own shapes) is not "all worse"
    assert E.field_pick(rows, ["own"], {"own": "own_spot"}.get, now)["stage"] == 1


def test_a_champion_without_a_twin_stays_stage_one():
    rows, now = three_arms(gain_c=0.4)
    got = E.field_pick(rows, ["own", "b", "c"], lambda n: None, now)
    assert got["stage"] == 1 and got["champion"] == "c" and got["walk"] == "c"


def test_the_pick_is_wired_with_the_twin_and_a_twin_is_no_bandit_arm():
    farm = (ROOT / "scripts/run_farm.py").read_text(encoding="utf-8")
    assert "experiment.field_pick(" in farm and "patterns_mod.twin(n)" in farm
    assert 'arm["arm"] is not None' in farm
