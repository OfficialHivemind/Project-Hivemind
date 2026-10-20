"""Session goals' feasibility (ROADMAP G9): measured rates only."""
import os
import time

from hivemind.brain import session_goals as sg
from hivemind.brain.goals import Need, Row

RATES = sg.Rates(honey_h=94e6, honey_from="test", gather_share=0.5,
                 field_s={"bamboo": 1000.0})


def test_honey_yes_no_by_rate_times_hours():
    yes = sg.judge_honey(500e6, 8, RATES)
    assert yes.verdict == sg.YES and "752M in 8 h" in yes.reason
    assert sg.judge_honey(500e6, 5, RATES).verdict == sg.LIKELY   # 470M >= 80 %
    no = sg.judge_honey(2e9, 8, RATES)
    assert no.verdict == sg.NO and round(no.eta_h, 1) == 21.3


def test_unknown_rate_is_not_enough_data():
    v = sg.judge_honey(500e6, 8, sg.Rates())
    assert v.verdict == sg.UNKNOWN == "not enough data"
    row = Row(key="belt", label="Honeycomb Belt", short=10e6)
    assert sg.judge_item(row, 8, sg.Rates()).verdict == sg.UNKNOWN


def test_item_short_material_is_no_with_reason():
    row = Row(key="belt", label="Honeycomb Belt", short=1_316_000_000,
              needs=[Need("glue", "Glue", need=50, have=41)])
    v = sg.judge_item(row, 8, RATES)
    assert v.verdict == sg.NO
    assert "9 Glue short" in v.reason and "14.0 h" in v.reason
    assert sg.judge_item(Row(key="b", label="B", short=0), 8, RATES).verdict == sg.YES


def test_quest_steps_from_the_transcript():
    text = ("Polar Bear: Petal Tabbouleh\nCatch 50 Green Bloom Petals. 19/50\n"
            "Defeat 4 Rhino Beetles. Complete!\n"
            "Brown Bear: Bamboo\nCollect 7,200,000 Pollen from the Bamboo Field. 0/7,200,000\n"
            "Collect 2,200,000 Pollen from the Rose Field. Complete!\n")
    polar = sg.judge_quest("polar_bear", 8, text, RATES)
    assert polar.verdict == sg.UNKNOWN and "Catch 50" in polar.reason
    brown = sg.judge_quest("brown bear", 8, text, RATES)   # 7200 s / 0.5 = 4 h
    assert brown.verdict == sg.LIKELY and round(brown.eta_h, 1) == 4.0
    assert sg.judge_quest("brown bear", 3, text, RATES).verdict == sg.NO
    assert sg.judge_quest("onett", 8, text, RATES).verdict == sg.UNKNOWN


def test_session_window_and_first_keys(tmp_path):
    data = {"goals": {"honeycomb_belt": {"label": "Honeycomb Belt"}}}
    sg.save({"hours": 2, "goals": [{"kind": "item", "name": "Honeycomb Belt"}]},
            tmp_path, now=time.time())
    assert sg.first_keys(data, tmp_path) == ["honeycomb_belt"]
    assert sg.first_keys(data, tmp_path, now=time.time() + 3 * 3600) == []


def test_card_builds_offscreen(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from hivemind.gui.panels.session_goals import SessionGoalsPanel, honey_amount
    assert honey_amount("500M") == 500e6 and honey_amount("x") is None
    card = SessionGoalsPanel(var_root=tmp_path)
    card.value.setEditText("500M")
    card.add_goal()
    got = card.check()
    assert [v.verdict for v in got] == [sg.UNKNOWN]          # no benchmark here
    assert "500M honey: NOT ENOUGH DATA" in card.result.text()
    assert sg.load(tmp_path)["goals"] == [{"kind": "honey", "amount": 500e6}]
    assert app is not None


# ---- ROADMAP P20: a stale benchmark says its age, a very old one is dropped --
NOW = 1_800_000_000.0                       # a fake clock: nothing reads time.time()
DAY = 86400.0


def _bench(var, at, honey=94e6):
    import json
    (var / "benchmark.json").write_text(json.dumps({
        "generated_at": at,
        "baseline": {"honey_per_hour": honey, "running_hours": 40,
                     "fields": {"bamboo": {"pollen_per_s": 1000.0, "gather_min": 60}}},
        "time": {"slices": {"gather": {"pct": 50.0}}}}), encoding="utf-8")


def test_fresh_benchmark_says_no_age(tmp_path):
    _bench(tmp_path, NOW - 20 * 3600)
    r = sg.rates_from_files(tmp_path, now=NOW)
    assert r.honey_h == 94e6 and round(r.honey_age_h) == 20 and not r.dropped
    v = sg.judge_honey(500e6, 8, r)
    assert v.verdict == sg.YES and "days ago" not in v.reason


def test_stale_benchmark_says_how_old(tmp_path):
    _bench(tmp_path, NOW - 3 * DAY)
    r = sg.rates_from_files(tmp_path, now=NOW)
    honey = sg.judge_honey(500e6, 8, r)
    assert honey.verdict == sg.YES                         # still judged, but dated
    assert "(the benchmark's 40 running hours, rates from 3 days ago)" in honey.reason
    item = sg.judge_item(Row(key="b", label="B", short=200e6), 8, r)
    assert "honey short, about" in item.reason and "rates from 3 days ago" in item.reason
    text = ("Brown Bear: Bamboo\n"
            "Collect 7,200,000 Pollen from the Bamboo Field. 0/7,200,000\n")
    quest = sg.judge_quest("brown bear", 8, text, r)
    assert quest.verdict == sg.LIKELY and "rates from 3 days ago" in quest.reason
    # the edge: exactly STALE_H is still fresh
    _bench(tmp_path, NOW - sg.STALE_H * 3600)
    assert sg.ago(sg.rates_from_files(tmp_path, now=NOW).honey_age_h) == ""


def test_very_old_benchmark_is_not_enough_data(tmp_path):
    _bench(tmp_path, NOW - 10 * DAY)
    r = sg.rates_from_files(tmp_path, now=NOW)
    assert r.honey_h is None and r.field_s == {} and r.gather_share is None
    v = sg.judge_honey(500e6, 8, r)                         # would be a YES at 94M/h
    assert v.verdict == sg.UNKNOWN
    assert "10 days old, over 7; re-run scripts/benchmark.py --nightly" in v.reason
    item = sg.judge_item(Row(key="b", label="B", short=200e6), 8, r)
    assert item.verdict == sg.UNKNOWN and "10 days old" in item.reason
    got = sg.feasibility([{"kind": "honey", "amount": 500e6}], 8, tmp_path, now=NOW)
    assert [g.verdict for g in got] == [sg.UNKNOWN]
    # the same file judged on its own day is a confident YES again
    fresh = sg.feasibility([{"kind": "honey", "amount": 500e6}], 8, tmp_path,
                           now=NOW - 10 * DAY + 3600)
    assert [g.verdict for g in fresh] == [sg.YES]


def test_card_without_generated_at_uses_the_files_time(tmp_path):
    import json
    (tmp_path / "benchmark.json").write_text(json.dumps(
        {"baseline": {"honey_per_hour": 94e6}}), encoding="utf-8")
    os.utime(tmp_path / "benchmark.json", (NOW - 9 * DAY, NOW - 9 * DAY))
    assert sg.rates_from_files(tmp_path, now=NOW).honey_h is None
    os.utime(tmp_path / "benchmark.json", (NOW - 3600, NOW - 3600))
    assert sg.rates_from_files(tmp_path, now=NOW).honey_h == 94e6


def test_old_trip_rate_fallback_is_dropped_too(tmp_path, monkeypatch):
    from hivemind.brain import goals
    rate = goals.Rate(per_hour=50e6, hours=3.0, readings=9, since=0.0, until=NOW - 9 * DAY)
    monkeypatch.setattr(goals, "balance_rate", lambda rows: rate)
    r = sg.rates_from_files(tmp_path, now=NOW)              # no benchmark.json at all
    assert r.honey_h is None and "trips' honey rate is 9 days old" in r.dropped
    rate.until = NOW - 3 * DAY
    r = sg.rates_from_files(tmp_path, now=NOW)
    assert r.honey_h == 50e6
    assert "(3.0 h of trips, rates from 3 days ago)" in sg.judge_honey(1e9, 8, r).reason
