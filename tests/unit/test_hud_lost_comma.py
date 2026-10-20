"""Commas the HUD reader lost or failed (vision/digits, 2026-10-22).

MEASURED on recorded frames (route, planter and incident frames): at the 12 px 10-digit honey font a comma fell under
the size filter, the 9 px hole it left beat VALUE_GAP and the value was cut
there -- 1,234,567,890 read as 1,234,567, a confident honey 1000x low. And a
comma on the edge of the pollen fill scored 0.49 and failed the whole read.
The pills are crops of the bot's own frames.
"""
from __future__ import annotations

import pathlib

import cv2
import pytest

import hivemind
from hivemind.vision import digits
from hivemind.vision import screenstate as ss

ROOT = pathlib.Path(hivemind.__file__).resolve().parents[2]
SCREENS = ROOT / "tests" / "fixtures" / "screens"


@pytest.fixture(scope="module")
def templates():
    return ss.load_templates(ROOT / "data" / "templates" / "digits")


@pytest.mark.parametrize("name", [
    "lost-comma-a.png",     # a 10-digit honey once cut to 7 digits
    "lost-comma-b.png",     # a 10-digit honey once cut to 4 digits
])
def test_a_lost_comma_no_longer_cuts_the_honey(templates, name):
    path = SCREENS / "honey_pill" / name
    if not path.exists():
        pytest.skip("fixture frame not shipped")
    text, score = digits.read(cv2.imread(str(path)), templates)
    value = digits.to_int(text)
    assert value is not None and len(str(value)) == 10, (text, score)


@pytest.mark.parametrize("name, value", [
    # was "279?630/1130512"
    ("weak-comma-279630-1130512.png", (279_630, 1_130_512)),
    # the slash's foot is not a comma
    ("slash-foot-327605-955877.png", (327_605, 955_877)),
    # the 15 px font, its
    # rate suffix only 12 px after the value; a 0.9-height cut read it
    # "0/2,962,170??18/????"
    ("rate-suffix-15px-0-2962170.png", (0, 2_962_170)),
])
def test_pollen_commas_by_shape(templates, name, value):
    text, score = digits.read(cv2.imread(str(SCREENS / "pollen_pill" / name)), templates)
    assert digits.parse_fraction(text) == value, (text, score)


@pytest.mark.parametrize("text", ["1,193,", "1,191746", "1518,356", "1,234567890"])
def test_misgrouped_commas_are_not_a_number(text):
    # all four were accepted before; honey was in the billions
    assert digits.to_int(text) is None


def test_plain_and_grouped_numbers_still_parse():
    assert digits.to_int("1,234,567,890") == 1_234_567_890
    assert digits.to_int("72100") == 72_100
    assert digits.to_int("0") == 0


def test_a_capacity_with_a_lost_comma_matches_the_last_capacity():
    # review 2026-10-22: "5045,625" fails the group check, but its digits are
    # the capacity read in full before it; one "?" still matches, two do not
    from hivemind.brain.farm import HudReader
    reader = HudReader(lambda: None, None)
    reader._capacity = "5045625"
    assert reader._capacity_from("12/5045,625") == (12, 5_045_625)
    assert reader._capacity_from("12/5,04?,625") == (12, 5_045_625)
    assert reader._capacity_from("12/5045,626") is None
    assert reader._capacity_from("12/5,0??,625") is None
    assert reader._capacity_from("1?/5,045,625") is None
