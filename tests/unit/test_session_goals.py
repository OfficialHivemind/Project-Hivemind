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
