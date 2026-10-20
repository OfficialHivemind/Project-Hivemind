"""The think pane has to keep following the stream.

It is the panel the GUI is built around -- "see the Ai think" -- and it used to
stop following after about five thoughts and stay pinned near the top for the
rest of the session, without the user ever having scrolled.

The cause is worth remembering: reading the scroll range in the same call that
inserts a row gives the PRE-insert range, because Qt recomputes layout on a
later event-loop pass. Any test for this has to run a real event loop, or it
measures nothing.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtCore import QEventLoop, QTimer                       # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

from hivemind.gui.panels.think import ThinkPanel                    # noqa: E402
from hivemind.telemetry.events import Thought                       # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def settle(ms: int = 30) -> None:
    """Let Qt actually lay the widgets out."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def feed(panel: ThinkPanel, count: int, start: int = 0) -> None:
    for i in range(start, start + count):
        panel.add_thought(Thought(text=f"thought number {i}", topic=f"t{i}"))
        settle(2)


def test_it_keeps_following_new_thoughts(app):
    panel = ThinkPanel()
    panel.resize(400, 300)
    panel.show()
    settle()

    feed(panel, 40)
    settle(60)

    bar = panel._scroll.verticalScrollBar()
    assert bar.maximum() > 0, "the stream never grew; the test proves nothing"
    assert panel._stick, "stopped following without the user scrolling"
    assert bar.value() >= bar.maximum() - 24, (
        f"fell behind: value={bar.value()} maximum={bar.maximum()}")


def test_scrolling_away_stops_the_follow(app):
    """Following must not fight the user when they scroll back to read."""
    panel = ThinkPanel()
    panel.resize(400, 300)
    panel.show()
    settle()
    feed(panel, 30)
    settle(60)

    bar = panel._scroll.verticalScrollBar()
    bar.setValue(0)                       # the user scrolls to the top
    settle()
    assert not panel._stick

    feed(panel, 10, start=30)
    settle(60)
    assert bar.value() < bar.maximum() - 24, "yanked the view back down"


def test_scrolling_back_to_the_bottom_resumes_the_follow(app):
    panel = ThinkPanel()
    panel.resize(400, 300)
    panel.show()
    settle()
    feed(panel, 30)
    settle(60)

    bar = panel._scroll.verticalScrollBar()
    bar.setValue(0)
    settle()
    bar.setValue(bar.maximum())           # and back down again
    settle()
    assert panel._stick

    feed(panel, 10, start=30)
    settle(60)
    assert bar.value() >= bar.maximum() - 24


def test_the_chosen_option_has_a_check_not_a_colour_alone(app):
    """UI panel round 2 (2026-10-22): the pick was a green filled dot only."""
    from hivemind.gui.panels.think import DecisionCard
    from hivemind.gui.widgets import ElidedLabel
    from hivemind.telemetry.events import Considered, Option
    card = DecisionCard(Considered(question="Convert?", chosen="now",
                                   options=[Option("now", 2.0), Option("later", 1.0)]))
    names = {lab.text() for lab in card.findChildren(ElidedLabel)}
    assert names == {"✓ now", "○ later"}


def test_a_long_word_can_break():
    """Render probe, UI panel round 2 (2026-10-22): one 120-letter word widened the page."""
    from hivemind.gui.panels.think import breakable
    out = breakable("ok " + "x" * 100)
    assert out.startswith("ok ") and out.count("​") == 2
    assert out.replace("​", "") == "ok " + "x" * 100
    assert breakable("short words stay") == "short words stay"


def test_the_follow_lands_on_the_last_row_not_blank_space(app):
    """Usability triage 2026-10-26 #13: wrapped rows made the stream taller
    than its rows (1328 px for rows ending at 811), so the follow scrolled
    into blank space and the page looked empty."""
    panel = ThinkPanel()
    panel.resize(1000, 560)
    panel.show()
    for i in range(30):
        panel.add_thought(Thought(text=f"line {i} " + "Holding every planter to "
                                  "100%, field degradation is unverified. " * (i % 3),
                                  topic="economy"))
    settle(60)
    rows = [panel._stream.itemAt(i).widget() for i in range(panel._stream.count())]
    last = [w for w in rows if w is not None][-1]
    bar = panel._scroll.verticalScrollBar()
    assert bar.maximum() > 0, "the stream never grew; the test proves nothing"
    assert panel._inner.height() - last.geometry().bottom() < 24
    assert bar.value() == bar.maximum()


def test_a_cleared_pane_shows_its_empty_state_again(app):
    panel = ThinkPanel()
    feed(panel, 3)
    assert panel._placeholder is None
    panel.clear()
    settle()
    assert panel._placeholder is not None
    feed(panel, 1)                        # and the next thought still lands
    assert panel._placeholder is None and panel._rows == 1


def test_the_log_filters_by_topic_level_and_text_and_never_drops_a_row(app):
    """GUI polish 2026-10-27: the Log tab's filter row. It hides rows; clearing
    it shows every one again."""
    from hivemind.gui.panels.think import LogPanel
    panel = LogPanel()
    panel.add_thought(Thought(text="buff bar: haste x2", topic="walk"))
    panel.add_thought(Thought(text="convert: refused to press E", topic="farm"), "warn")
    panel.add_thought(Thought(text="sprinkler: placed", topic="gather"))
    panel.add_thought(Thought(text="the game crashed", topic="farm"), "error")
    shown = lambda: [r._base for r in panel.rows() if not r.isHidden()]  # noqa: E731
    assert len(shown()) == 4 and panel.shown.text() == ""
    panel.serious.setChecked(True)
    assert shown() == ["convert: refused to press E", "the game crashed"]
    assert panel.shown.text() == "2 of 4"
    panel.topic.setCurrentText("farm")
    panel.text.setText("CRASH")
    assert shown() == ["the game crashed"]
    panel.add_thought(Thought(text="crash course", topic="walk"), "error")  # filtered on arrival
    assert shown() == ["the game crashed"]
    panel.serious.setChecked(False)
    panel.topic.setCurrentIndex(0)
    panel.text.clear()
    assert len(shown()) == 5 and panel.shown.text() == ""
    assert [panel.topic.itemText(i) for i in range(panel.topic.count())] == [
        "All topics", "walk", "farm", "gather"]


def test_warnings_outlive_the_ordinary_rows_when_the_pane_trims(app, monkeypatch):
    """MEASURED offscreen 2026-10-27: run-1257's 1,433 log rows kept 6 of its
    14 warnings when the oldest row went whatever it was."""
    from hivemind.gui.panels import think
    monkeypatch.setattr(think, "MAX_ENTRIES", 5)
    panel = think.LogPanel()
    panel.add_thought(Thought(text="early warning", topic="farm"), "warn")
    feed(panel, 10)
    texts = [r._base for r in panel.rows()]
    assert texts[0] == "early warning" and len(texts) == 5
