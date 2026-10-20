"""Start, Pause and Stop have to actually reach the bot.

All three were declared as signals, emitted by their buttons, and connected to
nothing at all -- while set_status kept enabling and disabling them, so they
looked live. Clicking Stop on a running bot did nothing and the bot kept
playing. That is the worst possible failure for a run control, so it is tested
end to end: click the button, check a Command left through the bridge.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication                      # noqa: E402

from hivemind.gui.window import MainWindow                      # noqa: E402
from hivemind.telemetry.events import (Action, Command,         # noqa: E402
                                       StatusUpdate, from_json)


class FakeBridge:
    """Stands in for EventBridge, recording what the window tries to send."""

    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class Signals(QObject):
            event_received = Signal(object)
            connection_changed = Signal(bool)

        self._signals = Signals()
        self.event_received = self._signals.event_received
        self.connection_changed = self._signals.connection_changed
        self.sent: list = []
        self.connected = True

    def send(self, event) -> bool:
        if not self.connected:
            return False
        self.sent.append(event)
        return True


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeBot:
    """The bot as a process, faked. A test must never start a real one."""

    def __init__(self, alive=False):
        self.alive = alive
        self.starts = 0
        self.stops = 0
        self.log_path = "/tmp/fake.log"

    def running(self):
        return self.alive

    def describe_state(self):
        # The launcher's own words (gui/launcher.BotProcess.describe_state).
        return ("the watchdog started from here is running (pid 1234) — the "
                "bot is joining, or between attempts"
                if self.alive else
                "not connected — nothing is running; Start launches the bot")

    def exit_code(self):
        return None if self.alive else 0

    @property
    def pid(self):
        return 1234 if self.alive else None

    process = None

    def start(self):
        from hivemind.gui.launcher import Launch
        self.starts += 1
        self.alive = True
        return Launch(ok=True, pid=1234, log=self.log_path)

    def stop(self, **kw):
        self.stops += 1
        self.alive = False
        return "the bot stopped cleanly"


@pytest.fixture
def window(app):
    bridge = FakeBridge()
    bot = FakeBot()
    win = MainWindow(bridge, bot=bot)
    win._connected = bridge.connected      # the real one learns this by signal
    return win, bridge


def test_start_resumes_a_bot_that_is_already_connected(window):
    win, bridge = window
    win.status._start.click()
    assert [e.action for e in bridge.sent if isinstance(e, Command)] == [Action.START]
    assert win.bot.starts == 0, "it launched a second bot instead of resuming"


def test_start_LAUNCHES_the_bot_when_there_is_none(window):
    """THE OWNER'S BUG: the Play button did nothing. It sent START to a socket with nothing on the other end."""
    win, bridge = window
    win._connected = False
    bridge.connected = False
    win.status._start.click()
    assert win.bot.starts == 1
    assert bridge.sent == [], "it tried to talk to a bot that was not running"
    # It starts the WATCHDOG now (gui/launcher, 2026-09-23): a bare run_farm
    # died at its first rejoin, and the owner wants a press to run the
    # current bot until Stop.
    assert "started the watchdog" in win.status._state.text()


def test_start_does_not_launch_twice_while_the_bot_is_booting(window):
    win, bridge = window
    win._connected = False
    bridge.connected = False
    win.bot.alive = True                  # launched, not yet connected
    win.status._start.click()
    assert win.bot.starts == 0
    assert "joining" in win.status._state.text()


def test_stop_sends_a_stop_command(window):
    win, bridge = window
    win.status.set_status(running=True, paused=False)
    win.status._stop.click()
    assert [e.action for e in bridge.sent if isinstance(e, Command)] == [Action.STOP]


def test_pause_and_resume_are_distinguished(window):
    """The same button means two different things, so it must say which."""
    win, bridge = window
    win.status.set_connected(True)    # Pause is live only with a bot to hear it
    win.status.set_status(running=True, paused=False)
    win.status._pause.click()
    win.status.set_status(running=True, paused=True)
    win.status._pause.click()
    assert [e.action for e in bridge.sent if isinstance(e, Command)] == [
        Action.PAUSE, Action.RESUME]


def test_a_command_that_cannot_be_sent_is_reported(window):
    """A button that silently does nothing is worse than a disabled one: the
    user believes the bot stopped while it is still playing."""
    win, bridge = window
    # the button was live (connected) and the link went down before the click
    win.status.set_connected(True)
    win.status.set_status(running=True, paused=False)
    bridge.connected = False
    win.status._pause.click()
    assert bridge.sent == []
    assert "could not send" in win.status._state.text()


def test_stopping_with_no_bot_anywhere_says_so(window):
    win, bridge = window
    bridge.connected = False
    win.status.set_status(running=True, paused=False)
    win.status._stop.click()
    assert win.bot.stops == 0
    assert "nothing to stop" in win.status._state.text()


def test_a_command_survives_the_wire():
    """It travels as JSON over the socket, so it has to round-trip."""
    restored = from_json(Command(action=Action.STOP).to_json())
    assert isinstance(restored, Command)
    assert restored.action == Action.STOP


# --- the header must not contradict itself ---------------------------------

def test_connecting_updates_the_text_not_just_the_dot(app):
    """A bot that connects but has not yet reported leaves the header green
    beside "not connected — is the bot running?" forever."""
    from hivemind.gui.panels.status import StatusBar
    bar = StatusBar()
    bar.set_connected(False)
    assert "not connected" in bar._state.text()
    bar.set_connected(True)
    assert "not connected" not in bar._state.text()


def test_a_status_update_still_wins_over_the_placeholder(app):
    from hivemind.gui.panels.status import StatusBar
    bar = StatusBar()
    bar.set_connected(True)
    bar.set_status(running=True, paused=False, note="gathering")
    assert bar._state.text() == "running — gathering"


def test_the_window_tracks_paused_from_the_bot(window):
    win, _ = window
    win.handle(StatusUpdate(running=True, paused=True))
    assert win.status.paused is True
    win.handle(StatusUpdate(running=True, paused=False))
    assert win.status.paused is False


# --- a replay must never be mistakable for the live account ----------------
# The owner caught this themselves: they looked at the GUI and asked where the stats
# came from, because the game was not even open. Honey 10.2M, 446K pollen, 25
# bees, five planters, a Royal Jelly question and the picture in the live view
# were ALL from data/demo/session.jsonl, not their account.

def test_a_live_window_carries_no_banner(window):
    win, _ = window
    # isHidden(), not isVisible(): an offscreen parent is never "visible",
    # so isVisible() would pass whether or not the banner was shown.
    assert win._replay_banner.isHidden()
    assert "DEMO" not in win.windowTitle()


def test_a_replay_says_so_in_the_window_and_the_title(window):
    win, _ = window
    win.set_replay_banner("session.jsonl")
    assert not win._replay_banner.isHidden()
    text = win._replay_banner.text()
    assert "DEMO" in text
    assert "NOT your account" in text
    assert "session.jsonl" in text
    assert "DEMO" in win.windowTitle()


# ---- input feedback: the owner could not tell a press had registered ------
def test_every_button_state_is_styled():
    """THEIR REPORT: no button had a click or hover animation, so they could not
    tell whether an input had gone through.

    The primary button was the worst of the three: `#Primary` sets
    `border: none` and the only hover rule in the stylesheet changed
    `border-color`, so Start -- the button pressed most -- had no hover state
    at all, and nothing anywhere had a `:pressed` state.
    """
    from hivemind.gui import theme
    sheet = theme.STYLESHEET
    for selector in ("QPushButton:hover", "QPushButton:pressed",
                     "QPushButton:focus", "QPushButton:disabled",
                     "QPushButton#Primary:hover", "QPushButton#Primary:pressed",
                     "QPushButton#Danger:hover", "QPushButton#Danger:pressed",
                     "QTabBar::tab:hover", "QComboBox:hover"):
        assert selector in sheet, f"{selector} has no styling"


def test_pressed_moves_the_button_not_only_its_colour():
    """A 1px shift is what makes a click feel registered at a glance."""
    from hivemind.gui import theme
    pressed = theme.STYLESHEET.split("QPushButton:pressed")[1].split("}")[0]
    assert "padding-top" in pressed and "padding-bottom" in pressed


def test_hover_and_pressed_are_different_colours():
    from hivemind.gui import theme
    assert theme.BG_RAISED_HOVER != theme.BG_RAISED
    assert theme.BG_RAISED_PRESSED != theme.BG_RAISED
    assert theme.BG_RAISED_HOVER != theme.BG_RAISED_PRESSED
    assert theme.ACCENT_HOVER != theme.ACCENT != theme.ACCENT_PRESSED


def test_the_handover_button_is_restyled_when_its_name_changes(window):
    """Qt resolves stylesheet selectors at polish time and does not redo it on
    setObjectName, so this button never went yellow on take-over."""
    win, _ = window
    win.status.set_handed_over(True)
    assert win.status._handover.objectName() == "Primary"
    win.status.set_handed_over(False)
    assert win.status._handover.objectName() == ""


def test_start_in_a_demo_replay_launches_nothing(window):
    """2026-10-22: Start during a replay launched the real bot; the UI preview
    build is a replay only, so Play there must start nothing."""
    win, bridge = window
    win._connected = False
    bridge.connected = False
    win.set_replay_banner("session.jsonl")
    win.status._start.click()
    assert win.bot.starts == 0 and bridge.sent == []


def test_pause_and_stop_in_a_demo_say_so_plainly(window):
    """The Windows Claude's release check, 2026-10-22: a demo said "could not
    send pause -- not connected to the bot"."""
    win, bridge = window
    win.set_replay_banner("session.jsonl")
    win._command(Action.PAUSE)
    assert bridge.sent == []
    assert "demo" in win.status._state.text().lower()
