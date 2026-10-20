"""The run controls must come back after a handover. See _apply_buttons."""
from __future__ import annotations

import pytest

from hivemind.gui.panels.status import (PASS_BACK_TEXT, TAKE_OVER_TEXT,
                                        StatusBar)


@pytest.fixture
def bar(qt_app):
    return StatusBar()


def test_taking_over_disables_the_run_controls(bar):
    bar.set_connected(True)       # Pause is a message: live only with a bot to hear it
    bar.set_status(running=True, paused=False)
    assert bar._pause.isEnabled()
    bar.set_handed_over(True)
    assert not bar._start.isEnabled()
    assert not bar._pause.isEnabled()
    assert not bar._stop.isEnabled()


def test_passing_back_brings_the_run_controls_back(bar):
    """REGRESSION. The old line read

        button.setEnabled(not handed_over and button.isEnabled()
                          if not handed_over else False)

    which on the way back evaluates to `button.isEnabled()` -- every button set
    to the value it already had. Taking over disabled Start, Pause and Stop and
    passing back never restored them, so the run controls were dead for the
    rest of the session.
    """
    bar.set_connected(True)
    bar.set_status(running=True, paused=False)
    bar.set_handed_over(True)
    bar.set_handed_over(False)
    assert bar._pause.isEnabled(), "Pause never came back after a handover"
    assert bar._stop.isEnabled(), "Stop never came back after a handover"


def test_passing_back_to_an_idle_bot_offers_start(bar):
    bar.set_status(running=False, paused=False)
    bar.set_handed_over(True)
    bar.set_handed_over(False)
    assert bar._start.isEnabled()
    assert not bar._pause.isEnabled()


def test_the_label_says_which_way_the_button_goes(bar):
    assert bar._handover.text() == TAKE_OVER_TEXT
    bar.set_handed_over(True)
    assert bar._handover.text() == PASS_BACK_TEXT


def test_clicking_asks_and_does_not_decide(bar):
    """The window moves the button only once the command actually went out."""
    asked = []
    bar.handover_clicked.connect(asked.append)
    bar._toggle_handover()
    assert asked == [True]
    assert bar._handover.text() == TAKE_OVER_TEXT, "the button moved on its own"


def test_losing_the_connection_does_not_give_the_bot_the_keyboard_back(bar):
    """Start must stay dead while the owner is the one playing."""
    bar.set_handed_over(True)
    bar.set_connected(False)
    assert not bar._start.isEnabled()
    bar.set_connected(True)
    assert not bar._start.isEnabled()
