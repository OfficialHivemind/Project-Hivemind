"""scripts/progress_report.py on a small var/: honey earned is the balance's
rises (a purchase's fall is spent, not lost), hand-ins and finished quests
come from the run log, purchases from purchases.json/owned.json."""
import importlib.util
import json
import time
from pathlib import Path

import hivemind

ROOT = Path(hivemind.__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("progress_report", ROOT / "scripts" / "progress_report.py")
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)

NOW = time.mktime(time.strptime("2026-10-20 12:00:00", "%Y-%m-%d %H:%M:%S"))


def make_var(tmp: Path) -> Path:
    var = tmp / "var"
    (var / "night").mkdir(parents=True)
    t0 = NOW - 6 * 3600
    balances = [1_000_000_000, 1_100_000_000, 900_000_000, 1_000_000_000]   # a 200M purchase
    rows = [{"at": t0 + 600 * i, "attempt": 7, "seconds": 500, "gather_seconds": 300,
             "pollen": 5_000_000, "action": "gather", "credited": "pine_tree",
             "aimed_at": "pine_tree", "converted": True, "deaths": 1 if i == 1 else 0,
             "convert_note": f"honey settled at {b:,}"} for i, b in enumerate(balances)]
    (var / "trips.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    start = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0 - 60))
    (var / "night" / "attempts.log").write_text(
        f"[overnight] attempt 7 starting {start} -> {var}/night/run-7.log\n")
    clock = time.strftime("%H:%M:%S", time.localtime(t0 + 100))
    (var / "night" / "run-7.log").write_text(
        f"    {clock}  a dialogue was read at the Polar Bear, so it leaves the queue\n"
        f"    {clock}  hand-in queue: polar bear: 'Polar Bear: Exotic Salad' shows finished — first\n"
        f"    {clock}  asking for a rejoin\n")
    (var / "purchases.json").write_text(json.dumps([
        {"at": t0 + 700, "item": "Hive Slot", "price": 200_000_000, "currency": "Honey", "ok": True},
        {"at": t0 + 800, "item": "300 Gumdrops", "price": 100, "currency": "Tickets", "ok": False},
        {"at": t0 - 86400 * 3, "item": "Old", "price": 1, "currency": "Honey", "ok": True}]))
    (var / "owned.json").write_text(json.dumps({"items": {"helmet": {"state": "confirmed", "at": t0}},
                                                "drops": [{"after_at": t0, "amount": 5, "verdict": "no match"}]}))
    (var / "quests.json").write_text(json.dumps({"read_at": t0, "quests": [{"name": "Star Journey 2"}]}))
    (var / "bees.json").write_text(json.dumps({"total": 42, "gifted": ["a", "b"], "read_at": t0}))
    return var


def test_report_from_a_small_var(tmp_path):
    d = pr.report(make_var(tmp_path), NOW, 24.0)
    assert d["honey"]["earned"] == 200_000_000 and d["honey"]["spent"] == 200_000_000
    assert d["bought"] == ["Hive Slot (200,000,000 honey)"] and d["buy_fails"] == 1
    assert d["owned_new"] == ["helmet (confirmed)"] and d["unexplained"] == [5]
    assert d["handins"] == ["Polar Bear"] and d["finished"] == ["Polar Bear: Exotic Salad"]
    assert d["deaths"] == 1 and d["day"]["rejoins"] == 1
    text = pr.text(d, telegram=True)
    for part in ("+200M", "not counted as a loss", "Hive Slot", "1 hand-ins (Polar Bear x1)",
                 "Star Journey 2", "42 bees", "pine tree 100%", "1 rejoins, 1 deaths"):
        assert part in text, part


def test_empty_var_says_so_not_zero(tmp_path):
    var = tmp_path / "var"
    var.mkdir()
    text = pr.text(pr.report(var, NOW, 24.0))
    assert "no confirmed convert" in text and "Bought: nothing" in text
