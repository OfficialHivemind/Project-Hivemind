"""Stats > Graphs and Compare (gui/panels/graphs, ROADMAP U17) on CLEARLY FAKE
data: a made-up var/ in a temp folder, never the owner's. Every number on the
charts must be the benchmark's own, a period with nothing behind it must say
"Not enough data yet", and Export PNG must write a picture."""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels import graphs  # noqa: E402

APP = QApplication.instance() or QApplication([])
FIELDS = {"pine_tree": 30_000, "bamboo": 24_000, "rose": 9_000, "pumpkin": 15_000}


def fake_var(var: Path, now: float, days: float = 3.0, seed: int = 7) -> Path:
    """A made-up var/: a trip every 10 minutes for `days`, honey rising,
    four fields at fixed made-up rates, one run per day with its log. Every
    row says FAKE so it can never pass for the owner's."""
    rng = random.Random(seed)
    (var / "night").mkdir(parents=True, exist_ok=True)
    rows, attempts, bal = [], [], 1_000_000_000
    start = now - days * 86400
    n = int(days * 86400 // 600)
    for i in range(n):
        at = start + 600 * (i + 1)
        attempt = 1 + int((at - start) // 86400)
        field = list(FIELDS)[(i // 6) % len(FIELDS)]
        gain = int(rng.gauss(12_000_000, 3_000_000) * (1.3 if at > now - 86400 else 1.0))
        read, bal = bal, bal + max(0, gain)
        rows.append({
            "FAKE": "made-up test data", "at": at, "attempt": attempt,
            "decision_id": f"{attempt}-{int((at - 500) * 1000)}", "action": "gather",
            "aimed_at": field, "credited": field, "converted": rng.random() < 0.9,
            "deaths": 0, "seconds": 500, "gather_seconds": 300,
            "pollen": FIELDS[field] * 300 * rng.uniform(0.8, 1.2),
            "context": {"honey": read},
            "convert_note": f"converted — honey settled at {bal:,} (+{gain:,})",
            "routes": [{"kind": "out", "outcome": "landed", "seconds": 40},
                       {"kind": "home", "seconds": 50,
                        "outcome": "landed" if rng.random() < 0.88 else "elsewhere"}]})
    (var / "trips.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for a in range(1, int(days) + 2):
        t0 = start + (a - 1) * 86400
        if t0 > now:
            break
        length = int(min(86400, now - t0))
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0))
        attempts.append(f"[overnight] attempt {a} starting {stamp} -> /fake/run-{a}.log\n"
                        f"[overnight] attempt {a} exited 0 after {length}s\n")
        clock = time.strftime("%H:%M:%S", time.localtime(t0 + 5))
        (var / "night" / f"run-{a}.log").write_text(
            f"  === bootstrap ===\n    {clock}  in game after 5s\n")
    (var / "night" / "attempts.log").write_text("".join(attempts))
    (var / "blender.json").write_text(json.dumps(
        {"made": [[now - 3600 * k, "glitter", 1] for k in range(1, 6)]}))
    return var


@pytest.fixture
def now():
    return time.time()


def test_the_numbers_are_the_benchmarks(tmp_path, now):
    data = graphs.load(fake_var(tmp_path / "var", now), now, work=tmp_path / "nowork")
    labels = [p[0] for p in graphs.periods(data)]
    assert labels[:4] == ["Last 24 hours", "The 24 hours before", "Today", "Yesterday"]
    assert not any(l.startswith("Before update") for l in labels)     # no deploys here
    w = graphs.window(data, now - 86400, now)
    s = w["summary"]
    assert s["trips"] == 144 and s["honey_per_hour"] > 0
    # the hourly points average back to the benchmark's honey/h for the day
    pts = w["honey"][graphs.HOUR]
    assert 20 <= len(pts) <= 25
    b = graphs.bench()
    assert s == b.summary(w["units"], now - 86400, now, data["runs"], None,
                          data["captures"], data["crafts"])
    # the fields are ranked by pollen a second, the fake rates come back
    rates = {f: r for f, r, _ in w["fields"]}
    assert list(rates)[0] == "pine_tree" and abs(rates["pine_tree"] - 30_000) < 3_000
    assert w["time"] and w["time"]["gather"] > 0                # the run logs' split
    assert set(w["rates"][graphs.HOUR]) == {"landing", "success"}


def test_an_empty_var_says_not_enough_data(tmp_path, now):
    var = tmp_path / "empty"
    var.mkdir()
    data = graphs.load(var, now, work=tmp_path / "nowork")
    w = graphs.window(data, now - 86400, now)
    assert w["summary"]["trips"] == 0 and w["honey"][graphs.HOUR] == [] and w["fields"] == []
    ui = graphs.StatsGraphs(var=var, work=tmp_path / "nowork")
    ui._spawn = lambda job: job()
    ui.refresh()
    assert "No trips recorded yet" in ui.source.text()
    assert ui.charts.isHidden() and not ui.empty.isHidden()      # no empty boxes
    assert not ui.export_button.isEnabled()
    assert ui.honey_chart.is_empty() and ui.field_chart.is_empty()
    assert ui.honey_chart.empty_text == "Not enough data yet"


def test_a_long_period_does_not_work_out_the_time_split(tmp_path, now):
    data = graphs.load(fake_var(tmp_path / "var", now), now, work=tmp_path / "nowork")
    assert graphs.window(data, now - 30 * 86400, now)["time"] is None


def test_the_pages_draw_compare_and_export(tmp_path, now):
    ui = graphs.StatsGraphs(var=fake_var(tmp_path / "var", now), work=tmp_path / "nowork")
    ui._spawn = lambda job: job()
    ui.refresh()                                       # load, then both pages
    assert ui.period.currentText() == "Last 24 hours"
    assert not ui.honey_chart.is_empty() and not ui.field_chart.is_empty()
    assert not ui.time_chart.is_empty() and "trips" in ui.kpis.text()
    # ROADMAP P4: today's honey/h headline with yesterday and the 7-day average
    assert not ui.today.isHidden() and "Honey/hr today" in ui.today.text()
    assert "7-day" in ui.today.text()
    ui.daily.click()
    assert ui.honey_chart.step == graphs.DAY
    # compare: yesterday vs today, side by side, with the benchmark's verdict
    assert (ui.side_a.currentText(), ui.side_b.currentText()) == ("Yesterday", "Today") \
        or ui.side_a.currentText() == "Yesterday"
    ui.side_a.setCurrentText("The 24 hours before")
    ui.side_b.setCurrentText("Last 24 hours")
    texts = ui.table_texts()
    assert "Honey per hour" in texts and "better" in texts      # the fake +30%
    assert not ui.cmp_fields.is_empty() and not ui.cmp_time.is_empty()
    ui.swap()
    assert ui.side_a.currentText() == "Last 24 hours"
    texts = ui.table_texts()
    assert "worse" in texts
    out = tmp_path / "graphs.png"
    ui.graphs_sheet.resize(1100, 700)
    assert ui.export_png(ui.graphs_sheet, out) and out.stat().st_size > 1000


def test_a_deploy_gives_before_and_after(tmp_path, now):
    var = fake_var(tmp_path / "var", now)
    (var / "benchmark.json").write_text(json.dumps(
        {"deploys": [{"at": now - 86400, "sha": "abc1234def", "subject": "fake"}]}))
    data = graphs.load(var, now, work=tmp_path / "nowork")
    labels = {p[0]: p[1:] for p in graphs.periods(data)}
    before = next(k for k in labels if k.startswith("Before update abc1234"))
    assert labels[before] == (now - 2 * 86400, now - 86400)


def test_a_demo_never_says_press_start(tmp_path, monkeypatch):
    """The Windows Claude's release check, 2026-10-22: set_running put
    "Press Start" back over the demo text."""
    monkeypatch.setenv("HIVEMIND_DEMO", "1")
    ui = graphs.StatsGraphs(var=tmp_path / "var", work=tmp_path / "nowork")
    for on in (False, True, False):
        ui.set_running(on)
        assert "Press Start" not in ui.empty.line.text()
        assert ui.empty.line.text() == graphs.EMPTY_DEMO
