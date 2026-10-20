"""Arrival by sight: it must not fire on the prompt we set off from.

THE RUN THIS FILE EXISTS FOR. 2026-09-21, var/gui-run.log 21:07:36, a trip to
the Pumpkin Patch by way of the red cannon:

    to pumpkin: left the hive, arrival unconfirmed — nowhere I can confirm
    (from_hive_to_pumpkin_with_red_cannon: w: stopped early — the target is
    in view; from_hive_to_pumpkin_with_red_cannon: d for 161 studs: pushed
    against something for 1.5 of 5.8s)

`w` is the FIRST step of that route and the character was standing on its own
hive pad, whose "Make Honey" prompt was on screen. Arrival fired on the first
watch tick, the remaining 259 studs of the approach were skipped as "already
arrived", E was pressed at the hive, and the route's post-cannon legs ran from
the hive. The owner watched where that ends up: it tried the cannon to Pumpkin,
missed it, walked past and ended at Black Bear.
"""
from __future__ import annotations

import numpy as np
import pytest

from hivemind.nav.arrival import Arrival


class Screen:
    """A scripted sequence of "is the panel box showing" answers."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.i = 0

    def frame(self):
        return np.zeros((4, 4, 3), np.uint8)

    def present(self, _frame):
        value = self.answers[min(self.i, len(self.answers) - 1)]
        self.i += 1
        if isinstance(value, Exception):
            raise value
        return value


def watcher(*answers, **kw):
    screen = Screen(*answers)
    return Arrival(screen.frame, screen.present, **kw), screen


# ---- the bug --------------------------------------------------------------
def test_a_prompt_already_showing_when_armed_never_fires():
    """Standing on the hive pad. The pad's own prompt is not the target."""
    arrival, _ = watcher(True)
    arrival.arm("red_cannon")
    assert [arrival() for _ in range(6)] == [False] * 6
    assert arrival.held_back == 6 and arrival.fired == 0


def test_it_fires_once_the_start_prompt_has_gone_and_another_appears():
    """The honest sequence: on the pad, off the pad, at the cannon."""
    arrival, _ = watcher(True,          # arm: the hive prompt
                         True,          # still on the pad
                         False,         # stepped off it
                         False,
                         True)          # something new is in view
    arrival.arm("red_cannon")
    assert arrival() is False
    assert arrival() is False
    assert arrival() is False
    assert arrival() is True
    assert arrival.fired == 1


def test_an_empty_screen_at_arming_makes_arrival_live_at_once():
    """A route that does not start at a landmark has nothing to step off."""
    arrival, _ = watcher(False, True)
    arrival.arm("ticket_shop")
    assert arrival() is True


def test_it_keeps_firing_while_the_prompt_stays_up():
    """The runner latches on the first True; this must not go quiet after it."""
    arrival, _ = watcher(False, True)
    arrival.arm("red_cannon")
    assert [arrival() for _ in range(3)] == [True, True, True]


def test_a_prompt_that_comes_back_after_clearing_still_fires():
    """`arm` consumes the first look, so these are arm, off-the-pad, at-it."""
    arrival, _ = watcher(True, False, True)
    arrival.arm("red_cannon")
    assert arrival() is False       # stepped off the pad
    assert arrival() is True        # somewhere new


# ---- arming and disarming -------------------------------------------------
def test_an_unarmed_watcher_never_fires():
    """It is installed for the routes that end in a press and nothing else."""
    arrival, screen = watcher(True)
    assert arrival() is False
    assert screen.i == 0, "it looked at the screen with nothing armed"


def test_disarm_stops_it():
    arrival, _ = watcher(False, True)
    arrival.arm("red_cannon")
    arrival.disarm()
    assert arrival() is False


def test_re_arming_forgets_the_last_journey():
    """Otherwise the SECOND route out of the hive fires on the pad again."""
    arrival, _ = watcher(False, True, True, True)
    arrival.arm("red_cannon")
    assert arrival() is True
    arrival.arm("red_cannon")           # armed while a prompt is showing
    assert arrival() is False


# ---- it must not break a walk ---------------------------------------------
def test_a_frame_it_cannot_grab_is_not_an_arrival():
    def boom():
        raise RuntimeError("the compositor went away")
    arrival = Arrival(boom, lambda f: True)
    arrival.arm("red_cannon")
    assert arrival() is False


def test_no_frame_is_not_an_arrival():
    arrival = Arrival(lambda: None, lambda f: True)
    arrival.arm("red_cannon")
    assert arrival() is False


def test_a_detector_that_throws_is_not_an_arrival():
    arrival, _ = watcher(RuntimeError("bad frame"))
    arrival.arm("red_cannon")
    assert arrival() is False


def test_arming_when_the_screen_cannot_be_read_leaves_arrival_LIVE():
    """The permissive choice, deliberately: a pessimistic one would disarm
    arrival for the whole route on a single failed grab, and then every walk
    runs on its timer -- the failure arrival exists to stop."""
    arrival = Arrival(lambda: None, lambda f: True)
    arrival.arm("red_cannon")
    arrival.frames = lambda: np.zeros((4, 4, 3), np.uint8)
    arrival.panel_present = lambda f: True
    assert arrival() is True


# ---- it says what it is doing ---------------------------------------------
def test_it_explains_why_it_is_holding_back():
    said = []
    arrival, _ = watcher(True, True, False,
                         emit=lambda event: said.append(event.text))
    arrival.arm("red_cannon")
    arrival()
    arrival()
    joined = " ".join(said)
    assert "already showing" in joined
    assert "red cannon" in joined
    assert "stepped off" in joined


def test_the_destination_is_named_in_plain_words():
    said = []
    arrival, _ = watcher(True, emit=lambda e: said.append(e.text))
    arrival.arm("honey_dispenser")
    assert "honey dispenser" in " ".join(said)


def test_a_broken_emit_does_not_break_the_watcher():
    def bad(_event):
        raise RuntimeError("the bus is down")
    arrival, _ = watcher(False, True, emit=bad)
    arrival.arm("red_cannon")
    assert arrival() is True
