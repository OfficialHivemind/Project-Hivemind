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
