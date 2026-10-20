"""scripts/simulate.py (ROADMAP P12) on a synthetic var/: the planner replay
reproduces the live picks (weak-quest alternation included), a quest-first
rule is priced against the top score with its break-even quest worth, and the
token replay prices chases from their lessons."""
import importlib.util
import json
from pathlib import Path

import hivemind

ROOT = Path(hivemind.__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("simulate", ROOT / "scripts" / "simulate.py")
sim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim)

T0 = 1_792_000_000.0
QF = "quests first (quests.first), so it ranks ahead of the rest"


def cands(quest_first: bool):
    slow = {"field": "stump", "score": 4000.0, "rate": 4000.0, "reachable": True,
            "why": QF if quest_first else ""}
    fast = {"field": "pine_tree", "score": 30000.0, "rate": 30000.0, "reachable": True, "why": ""}
    return [slow, fast] if quest_first else [fast, slow]


def trip(i, chosen, quest_first=True, attempt=1):
    pollen = 9_000_000 if chosen == "pine_tree" else 1_200_000
    return {"at": T0 + 600 * i, "attempt": attempt, "chosen_by": "planner", "action": "gather",
            "chosen": chosen, "credited": chosen, "candidates": cands(quest_first),
            "seconds": 600.0, "gather_seconds": 300.0, "pollen": pollen, "deaths": 0,
            "converted": True, "honey": 2 * pollen,
            "convert_note": f"converted — honey settled at 5,000,000 (+{2 * pollen:,}) 15s after the press",
            "context": {"capacity": 10_000_000}}


def write_var(tmp: Path, rows, log="", lessons=()):
    (tmp / "night").mkdir()
    (tmp / "school-coins").mkdir()
    (tmp / "trips.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (tmp / "night" / "run-1.log").write_text(log, encoding="utf-8")
    (tmp / "school-coins" / "lessons.jsonl").write_text(
        "\n".join(json.dumps(r) for r in lessons) + "\n", encoding="utf-8")


def test_planner_replay_and_quest_pricing(tmp_path):
    # live: the weak quest field every other trip (rank top stump, then pine tree)
    rows = [trip(i, "stump" if i % 2 == 0 else "pine_tree") for i in range(12)]
    write_var(tmp_path, rows)
    res = sim.simulate(tmp_path, 7.0, [0.0])
    rules = {r["rule"]: r for r in res["planner"]["rules"]}
    assert abs(res["planner"]["hpp"] - 2.0) < 1e-9          # from the read gains
    assert rules["live, replayed (rank + weak-quest alternation)"]["same_as_live"] == 1.0
    assert rules["rank's top only (no alternation)"]["same_as_live"] == 0.5
    top = rules["top score, quests not first"]
    assert top["same_as_live"] == 0.5 and top["vs_live"] > 0.5
    # break-even: the extra field honey/h over the quest trips/h live gives up
    v = res["planner"]["fields"]
    hrs = 600 / 3600
    live_h = (v["pine_tree"]["honey_h"] + v["stump"]["honey_h"]) / 2
    expect = (v["pine_tree"]["honey_h"] - live_h) / (6 / (12 * hrs))
    assert abs(top["break_even_quest"] - expect) / expect < 1e-6
    assert "## 1. Planner" in sim.report(res)


def test_token_replay_prices_chases(tmp_path):
    log = "\n".join([
        "    23:07:44  token brain: chase honey#9 at (1000, 600) — honey#9 scores 40 — highest eligible",
        "    23:07:44  token brain value would: chase honey at (1000, 600) (+4,126/s: worth 30,914, "
        "detour 2.3s, gather 1,000/s, risk 0.05)",
        "    23:07:44  token brain would: skip honey#9 at (1000, 600) — a honey token 300 px out, past the 220 px leash",
        "    23:07:50  token brain: chase unknown#12 at (900, 700) — unknown#12 scores 60 — highest eligible",
        "    23:07:55  token brain: hold — at the anchor and nothing worth walking to",
    ])
    lessons = [
        {"attempt": 1, "x": 1000, "y": 600, "kind": "honey", "outcome": "collected",
         "evidence": "honey rose 50,000 in 1.3s against 10,000 expected from the trickle"},
        {"attempt": 1, "x": 900, "y": 700, "kind": "unknown", "outcome": "unknown",
         "evidence": "a unknown leaves no mark this can read on the HUD"},
    ]
    write_var(tmp_path, [trip(0, "pine_tree", quest_first=False)], log, lessons)
    t = sim.simulate(tmp_path, 7.0, [0.0])["tokens"]
    assert t["decisions"] == {"chase": 2, "hold": 1} and t["priced"] == 2
    assert t["gate_same_as_live"] == 0.5
    rules = {r["rule"]: r for r in t["rules"]}
    honey0 = rules["honey-token weight 0 (no honey chases)"]
    assert honey0["dropped"] == 1
    # dropping the honey chase loses its 40,000 lump less its detour's gathering
    assert honey0["delta_h_low"] < 0
    assert rules["value chooser live (drop its skips)"]["dropped"] == 0


def test_value_replay_matches_its_log():
    v = {"worth": 30_914.0, "gather": 2_479.0, "detour": 2.8, "risk": 0.05}
    assert sim.replay_value(v) == "chase"
    assert sim.replay_value({**v, "worth": 1_000.0}) == "skip"
