"""The HUD reader, against the first frame the bot ever earned anything in.

WHY THIS FIXTURE MATTERS. `field_earning.png` is a real 1920x1080 capture from
2026-09-20 taken in the Pine Tree field, moments after the bot claimed a hive
and rode the red cannon out. Its HUD reads

    Honey   16,201,128        (+83/sec)
    Pollen  103,439/688,050   (+780/sec)

and BOTH pills were unreadable when it was taken. That is the point of keeping
it: two separate defects in the reader were invisible for the entire life of
the project because they can only appear once the numbers are non-zero and
moving.

  * the pollen bar draws a bright GREEN fill under the leading digits, which
    passed a plain brightness threshold and swallowed the "1" of 103,439
  * both pills append a RATE -- "(+780/sec)" -- whose parentheses are not in
    the template set, so it read as "??780/5???" and was concatenated onto the
    value

A reader that only ever saw `0/660,000` could not have caught either.
"""
from __future__ import annotations

import pathlib

import cv2
import pytest

from hivemind.brain.farm import HudReader
from hivemind.vision import digits
from hivemind.vision import screenstate as ss

FRAME = (pathlib.Path(__file__).resolve().parents[1]
         / "fixtures" / "screens" / "field_earning.png")
TEMPLATES = (pathlib.Path(__file__).resolve().parents[2]
             / "data" / "templates" / "digits")


@pytest.fixture(scope="module")
def hud():
    if not FRAME.exists():
        pytest.skip("the earning frame is not in the repo")
    frame = cv2.imread(str(FRAME))
    return HudReader(lambda: frame, ss.load_templates(TEMPLATES))


def test_pollen_reads_through_the_green_fill_bar(hud):
    reading = hud.pollen()
    assert reading.ok, f"pollen unreadable: {reading.describe()}"
    assert reading.value == 103_439, (
        "the leading 1 sits on the bar's green fill; losing it reads 103,439 "
        "as 3,439")
    assert reading.capacity == 688_050


def test_honey_reads_with_a_rate_suffix_beside_it(hud):
    reading = hud.honey()
    assert reading.ok, f"honey unreadable: {reading.describe()}"
    assert reading.value == 16_201_128


def test_the_rate_suffix_is_cut_geometrically_not_by_guessing():
    """The suffix is separated by a wide gap; the value's glyphs are not.

    An earlier fix cut the string with a regex and turned "16?201?128" into
    16 when a comma failed to match. Splitting on the gap cannot shrink a
    number: an unreadable glyph stays inside the run and the reading fails
    honestly instead.
    """
    frame = cv2.imread(str(FRAME))
    glyphs = digits.segment(frame[22:58, 660:954])
    run = digits.leading_run(glyphs)
    assert len(run) == 10, "16,201,128 is ten glyphs"
    assert len(glyphs) > len(run), "the rate suffix should have been cut"
    gaps = [b.x - (a.x + a.w) for a, b in zip(run, run[1:])]
    assert max(gaps) <= digits.VALUE_GAP, (
        "a gap inside the value is as wide as the one before the suffix — "
        "the geometric split no longer separates them")


def test_an_unreadable_glyph_fails_rather_than_truncating():
    """Guard the regression the regex trim introduced."""
    assert digits.to_int("16?201?128") is None
    assert digits.to_int("16,201,128") == 16_201_128
