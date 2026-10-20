"""Simple mode (gui/simple): the switch flips the page and the mode is kept, a
count-up lands exactly on its value, and the Advanced panels still get every
event while Simple is shown. Offscreen. Nothing here reads or writes the real
~/.config/hivemind: the settings file, and Settings' default path, are a temp
file, and the Telegram tab gets an empty env file of its own."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

os.environ["HIVEMIND_TELEGRAM_ENV"] = str(Path(tempfile.mkdtemp()) / "telegram.env")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
import yaml  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels import settings as panel_mod  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "settings.yaml"
    monkeypatch.setattr(panel_mod, "CONFIG", path)
    monkeypatch.setattr(schema, "CONFIG", path)
    monkeypatch.setattr(schema.Settings.__init__, "__defaults__", (path,))
    return path


def _window():
    from hivemind.gui.bridge import EventBridge
    from hivemind.gui.window import MainWindow
    window = MainWindow(EventBridge())
    window.resize(1560, 940)
    return window


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


def _click(switch, half: int) -> None:
    QTest.mouseClick(switch, Qt.LeftButton, pos=QPoint(
        switch.width() // 4 + half * switch.width() // 2, switch.height() // 2))


def test_the_switch_flips_the_page_and_the_mode_is_kept(config):
    window = _window()
    assert window.mode == "simple"                     # the default
    assert window.pages.currentWidget() is window.simple
    _click(window.simple.mode_switch, 1)               # "Advanced"
    assert window.mode == "advanced"
    assert window.pages.currentWidget() is window.advanced
    assert yaml.safe_load(config.read_text())["gui.mode"] == "advanced"
    assert window.status.mode_switch.mode == window.simple.mode_switch.mode == "advanced"
    # a click on the side already shown asks for nothing
    _click(window.status.mode_switch, 1)
    assert window.mode == "advanced"
    window.close()

    again = _window()                                  # the next time it opens
    assert again.mode == "advanced"
    sent = []
    again.bridge.send = lambda event: sent.append(event) or True
    _click(again.status.mode_switch, 0)                # "Simple", from Advanced's bar
    assert again.mode == "simple"
    assert yaml.safe_load(config.read_text())["gui.mode"] == "simple"
    assert sent == []                                  # the window's own: not the bot's
    again.close()


def test_a_count_up_lands_exactly_on_its_value():
    from hivemind.gui.widgets import CountUp
    from hivemind.stream.show import human
    label = CountUp(repr, ms=150)
    label.show()
    label.set_number(0.1)
    assert label.text() == repr(0.0)                   # it rolls from zero, not jumps
    _pump(0.4)
    label.set_number(0.3)                              # 0.1 + 0.2 * 1.0 is not 0.3
    _pump(0.4)
    assert label.text() == repr(0.3) and label.value == 0.3
    honey = CountUp(human, ms=150)
    honey.show()
    honey.set_number(2_414_259_995)
    _pump(0.4)
    assert honey.text() == "2.41B"
    # out of sight it does not animate: the value is there at once
    honey.hide()
    honey.set_number(7_000)
    assert honey.text() == "7K"


def test_events_reach_the_advanced_panels_while_simple_is_shown(config):
    from hivemind.telemetry.events import (Considered, Log, Metric, Planter,
                                           TaskUpdate, Thought)
    config.write_text(yaml.safe_dump({"account.username": "Test_Bee_Keeper",
                                      "stream.hide_username": True}))
    window = _window()
    window.show()
    _pump(0.1)
    assert window.mode == "simple" and not window.advanced.isVisible()
    window.status.set_connected(True)                  # as the socket says it
    assert window.simple.header.chip.word.text() == "IDLE"
    thoughts = window.think._stream.count()
    window.handle(Metric(name="honey", value=1_234_567))
    window.handle(Thought(topic="think", text="weighing the fields"))
    window.handle(Considered(question="Which field next?", chosen="pine_tree",
                             rationale="measured 20,415 pollen/s over its last 10 "
                                       "trips here; 73% of its pollen is a good colour"))
    window.handle(TaskUpdate(name="gather", status="running", progress=0.94))
    window.handle(Planter(id="p1", seed="Paper Planter", field="Pine Tree",
                          growth=0.5, ready_at=time.time() + 1800))
    window.handle(Log(message="chat: Test_Bee_Keeper said hello", source="chat"))
    # ADVANCED HAS THEM, though it was never shown
    assert window.status.honey._value.text() == "1.2M"
    assert window.think._stream.count() > thoughts
    assert "p1" in window.planters._rows
    assert window.task_bar.value() == 94
    # and Simple drew them, in plain words
    assert window.simple.picture.caption.line._raw == "Gathering in Pine Tree · bag 94%"
    assert window.simple.planters.cells[0].name.text() == "Paper Planter"
    _pump(0.9)
    assert window.simple.honey.number.text() == "1.23M"
    # THROUGH THE GATE: the username never reaches Simple's feed
    rows = [item.text for item in window.simple.feed.items]
    assert any("hello" in text for text in rows)
    assert not any("Test_Bee_Keeper" in text for text in rows)
    # switching shows what was already there, nothing rebuilt
    window.show_mode("advanced", animate=False)
    assert window.advanced.isVisible() and window.status.honey._value.text() == "1.2M"
    window.close()
