"""The pollen bar, read without digits.

MEASURED 2026-09-22 23:37 to 2026-09-23 00:22: with the backpack full the
pill reads "1,208,419/1,205,886" and the digit reader returns
"11?0?46/111???0" at 0.49 confidence -- seven digits either side of the slash
defeat it. The planner therefore saw no backpack, never chose to convert, and
six attempts in a row gathered into a full bag while the honey stayed at
7,256,845. The bar needs no OCR; these are the frames it was measured on.
"""
from __future__ import annotations

import glob
import pathlib

import cv2
import numpy as np
import pytest

from hivemind.vision import screenstate as ss

ROOT = pathlib.Path(__file__).resolve().parents[2]

# (frame, the fill its own legible numbers give). The live full-bag frame is
# not in the repo; the fixtures and route frames are.
KNOWN = [
    ("tests/fixtures/screens/hive/at_own_hive.png", 627_840 / 660_000),
    ("var/routes/attempt-254/*hive_offset*.jpg", None),          # any, just must read
]


def _frame(pattern: str):
    hits = sorted(glob.glob(str(ROOT / pattern)))
    if not hits:
        pytest.skip(f"no frame matching {pattern}")
    frame = cv2.imread(hits[0])
    if frame is None:
        pytest.skip(f"could not read {hits[0]}")
    return frame


def test_a_legible_bar_agrees_with_its_own_numbers():
    frame = _frame("tests/fixtures/screens/hive/at_own_hive.png")
    fill = ss.pollen_bar_fill(frame)
    assert fill is not None
    assert fill == pytest.approx(627_840 / 660_000, abs=0.02)


def test_a_full_bar_reads_full():
    """A pill filled end to end, drawn as the game draws it: red on the track."""
    frame = np.zeros((1080, 1920, 3), np.uint8)
    rx, ry, rw, rh = ss.POLLEN_REGION
    left, right, top, bottom = ss.POLLEN_BAR
    frame[ry:ry + rh, rx:rx + rw] = (210, 210, 210)              # the pill
    frame[ry + 3:ry + rh - 3, rx + left:rx + right] = (40, 40, 220)   # red fill
    assert ss.pollen_bar_fill(frame) == pytest.approx(1.0, abs=0.02)


def test_an_empty_bar_reads_empty_and_is_not_none():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    rx, ry, rw, rh = ss.POLLEN_REGION
    left, right, top, bottom = ss.POLLEN_BAR
    frame[ry:ry + rh, rx:rx + rw] = (210, 210, 210)
    frame[ry + 3:ry + rh - 3, rx + left:rx + right] = (130, 130, 130)  # grey track
    fill = ss.pollen_bar_fill(frame)
    assert fill == pytest.approx(0.0, abs=0.02), "an empty bar is 0%, not unknown"


def test_a_half_bar_reads_half():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    rx, ry, rw, rh = ss.POLLEN_REGION
    left, right, top, bottom = ss.POLLEN_BAR
    frame[ry:ry + rh, rx:rx + rw] = (210, 210, 210)
    frame[ry + 3:ry + rh - 3, rx + left:rx + right] = (130, 130, 130)
    middle = left + (right - left) // 2
    frame[ry + 3:ry + rh - 3, rx + left:rx + middle] = (60, 200, 60)   # green fill
    assert ss.pollen_bar_fill(frame) == pytest.approx(0.5, abs=0.03)


def test_no_pill_means_no_reading():
    """The app home has no HUD; a number there would be an invention."""
    frame = _frame("tests/fixtures/screens/app_home.png")
    assert ss.pollen_bar_fill(frame) is None


def test_a_missing_or_empty_frame_is_not_a_reading():
    assert ss.pollen_bar_fill(None) is None
    assert ss.pollen_bar_fill(np.zeros((0, 0, 3), np.uint8)) is None


def test_the_reading_carries_the_bar_even_when_the_digits_fail():
    from hivemind.brain.farm import HudReader
    frame = _frame("tests/fixtures/screens/hive/at_own_hive.png")
    hud = HudReader(lambda: frame, ss.load_templates(ROOT / "data/templates/digits"))
    reading = hud.pollen()
    assert reading.bar_fill is not None
    assert reading.fill is not None
    # this frame's digits ARE legible, so the counter wins
    assert reading.fill_measured_by == "the counter"


def test_fill_falls_back_to_the_bar_and_says_so():
    from hivemind.brain.farm import Read, Reading
    from_bar = Reading(Read.UNREADABLE, text="11?0?46/111???0", score=0.49, bar_fill=1.0)
    assert from_bar.fill == 1.0 and from_bar.fill_measured_by == "the bar"
    assert "the bar looks 100% full" in from_bar.describe()
    nothing = Reading(Read.UNREADABLE, text="???", score=0.1)
    assert nothing.fill is None and nothing.fill_measured_by == "nothing"
