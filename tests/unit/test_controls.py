"""The buttons have to actually do something. See brain/controls.py."""
from __future__ import annotations

import threading
import time

import pytest

from hivemind.brain.controls import Controls, HandedOver, Stopped
from hivemind.telemetry.events import Action, Command, StatusUpdate


class FakeInput:
    def __init__(self, fail: bool = False):
        self.releases = 0
        self.fail = fail

    def release_all(self):
        self.releases += 1
        if self.fail:
            raise RuntimeError("virtual keyboard is gone")


def press(controls, action):
    controls.handle(Command(action=action))


def test_it_ignores_events_that_are_not_commands():
    c = Controls()
    c.handle(StatusUpdate(running=True))
    assert c.commands == 0


def test_start_then_pause_then_resume():
    c = Controls()
    press(c, Action.START)
    assert c.report().running is True
    press(c, Action.PAUSE)
    assert c.paused is True
    press(c, Action.RESUME)
    assert c.paused is False
    c.check()                       # must not block


def test_stop_raises_out_of_check():
    c = Controls()
    press(c, Action.START)
    press(c, Action.STOP)
    with pytest.raises(Stopped):
        c.check()


def test_pause_blocks_check_until_resumed():
    c = Controls()
    press(c, Action.START)
    press(c, Action.PAUSE)
    freed = threading.Event()

    def loop():
        c.check()
        freed.set()

    threading.Thread(target=loop, daemon=True).start()
    assert not freed.wait(0.2), "check() returned while paused"
    press(c, Action.RESUME)
    assert freed.wait(2.0), "check() did not return after resume"


def test_take_over_releases_every_key_immediately():
    """The owner's hands are on the keyboard; ours must not be."""
    vin = FakeInput()
    c = Controls(vin=vin)
    press(c, Action.START)
    press(c, Action.TAKE_OVER)
    assert vin.releases == 1
    assert c.handed_over is True


def test_the_bot_may_not_press_keys_while_handed_over():
    c = Controls(vin=FakeInput())
    press(c, Action.TAKE_OVER)
    assert c.may_press() is False
    with pytest.raises(HandedOver):
        c.guard()
    press(c, Action.PASS_BACK)
    assert c.may_press() is True
    c.guard()


def test_a_handover_blocks_the_loop_and_pass_back_resumes_it():
    c = Controls(vin=FakeInput())
    press(c, Action.START)
    press(c, Action.TAKE_OVER)
    freed = threading.Event()
    threading.Thread(target=lambda: (c.check(), freed.set()), daemon=True).start()
    assert not freed.wait(0.2), "the bot kept running while handed over"
    press(c, Action.PASS_BACK)
    assert freed.wait(2.0), "pass back did not resume the loop"


def test_pass_back_does_not_unpause_a_paused_bot():
    """Two separate reasons to be stopped; clearing one must not clear both."""
    c = Controls(vin=FakeInput())
    press(c, Action.START)
    press(c, Action.PAUSE)
    press(c, Action.TAKE_OVER)
    press(c, Action.PASS_BACK)
    assert c.paused is True
    freed = threading.Event()
    threading.Thread(target=lambda: (c.check(), freed.set()), daemon=True).start()
    assert not freed.wait(0.2), "pass back resumed a bot that was paused"


def test_stop_also_releases_the_keys():
    vin = FakeInput()
    c = Controls(vin=vin)
    press(c, Action.START)
    press(c, Action.STOP)
    assert vin.releases == 1


def test_a_failed_release_still_changes_state_and_is_reported():
    """An input error must not leave the owner fighting the bot silently."""
    seen = []
    c = Controls(vin=FakeInput(fail=True), emit=seen.append)
    press(c, Action.TAKE_OVER)
    assert c.handed_over is True
    assert any("could not release keys" in getattr(e, "note", "") for e in seen)


def test_every_command_reports_back_to_the_gui():
    seen = []
    c = Controls(vin=FakeInput(), emit=seen.append)
    for action in (Action.START, Action.PAUSE, Action.RESUME,
                   Action.TAKE_OVER, Action.PASS_BACK, Action.STOP):
        press(c, action)
    assert len(seen) == 6
    assert all(isinstance(e, StatusUpdate) for e in seen)


def test_the_gui_is_told_who_is_driving():
    c = Controls(vin=FakeInput())
    press(c, Action.TAKE_OVER)
    first = c.report()
    # DESIGN 8du: "handing over" until the loop reaches a step boundary --
    # never "handed over" while a step may still be pressing keys
    assert first.handing_over is True and first.handed_over is False
    assert first.paused is True, "a handover must read as not-running to the GUI"
    c.check(timeout=0.01)          # the loop blocks there: the acknowledgement
    update = c.report()
    assert update.handed_over is True and update.paused is True
