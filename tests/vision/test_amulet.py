"""The Ant Amulet table: "Keep Old" found on its own red button, or nothing.

run-529 (2026-09-28 20:55): the table stood in plain view for the whole 30 s
the bot looked, and the reading over the middle of the screen found neither
button; the owner watched the bot farm the Dandelion Field behind it. The
frames of that table are var/amulet/ (the machine's own; skipped without).
"""
from __future__ import annotations

import pathlib
import types

import cv2
import numpy as np
import pytest

from hivemind.vision import amulet

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRAMES = ROOT / "var" / "amulet"


def _frame(name):
    path = FRAMES / name
    if not path.exists():
        pytest.skip(f"no {path}")
    return cv2.imread(str(path))


@pytest.mark.parametrize("name", ["table-hive-205556.jpg", "table-field-205738.jpg"])
def test_the_table_the_old_reading_missed_is_read(name):
    choice = amulet.read_choice(_frame(name))
    assert choice.is_amulet_table, choice.describe()
    x, y = choice.keep_old
    assert 829 <= x <= 988 and 598 <= y <= 646, "the click is inside the red button"


def test_no_table_no_click():
    frame = _frame("no-table-arena.jpg")
    assert amulet.find_buttons(frame) is None
    assert amulet.read_buttons(frame) is None


def _drawn(red=True, green=True, gap=20):
    """A frame with the table's two buttons drawn where the game puts them."""
    frame = np.full((1080, 1920, 3), (60, 140, 60), np.uint8)
    if red:
        cv2.rectangle(frame, (829, 598), (829 + 158, 598 + 47), (33, 41, 194), -1)
    if green:
        left = 829 + 159 + gap
        cv2.rectangle(frame, (left, 598), (left + 159, 598 + 45), (39, 117, 33), -1)
    return frame


def _tesseract(say):
    """A stand-in for tesseract that reads `say(n)` for the n-th button."""
    calls = []

    def run(argv, input=None, capture_output=True, timeout=None):
        calls.append(argv)
        return types.SimpleNamespace(stdout=say(len(calls)).encode())
    return run, calls


def test_a_pair_is_the_table_only_when_its_words_are_exactly_right():
    frame = _drawn()
    assert amulet.find_buttons(frame) is not None
    run, _ = _tesseract(lambda n: "Keep Old" if n == 1 else "Replace")
    assert amulet.read_buttons(frame, run=run).is_amulet_table
    for wrong in (["Buy", "Replace"], ["Keep Old", "Purchase"], ["Keep", "Replace"], ["", ""]):
        run, _ = _tesseract(lambda n, w=wrong: w[n - 1])
        assert amulet.read_buttons(frame, run=run) is None, wrong


def test_one_button_alone_or_two_far_apart_is_not_the_table():
    assert amulet.find_buttons(_drawn(green=False)) is None
    assert amulet.find_buttons(_drawn(red=False)) is None
    assert amulet.find_buttons(_drawn(gap=200)) is None
