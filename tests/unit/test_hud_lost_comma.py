"""Commas the HUD reader lost or failed (vision/digits, 2026-10-22).

MEASURED on recorded frames (routes attempts 1150-1174, var/planters, 200
incidents of 21-22 Oct): at the 12 px 10-digit honey font a comma fell under
the size filter, the 9 px hole it left beat VALUE_GAP and the value was cut
there -- 1,108,639,179 read as 1,108,639, a confident honey 1000x low. And a
comma on the edge of the pollen fill scored 0.49 and failed the whole read.
The pills are crops of the bot's own frames (paths in each test id).
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


@pytest.mark.parametrize("name, value", [
    # routes/attempt-1154/104826-natro_home_pine_tree-02-walk-d300.jpg, was "1,108,639"
    ("lost-comma-1108639179.png", 1_108_639_179),
    # planters/seek-20261013-093245-push0.jpg, was "2,006"
    ("lost-comma-2006168984.png", 2_006_168_984),
])
def test_a_lost_comma_no_longer_cuts_the_honey(templates, name, value):
    text, score = digits.read(cv2.imread(str(SCREENS / "honey_pill" / name)), templates)
    assert digits.to_int(text) == value, (text, score)


@pytest.mark.parametrize("name, value", [
    # incidents/224713-mob-sighting/048_t+04.2s.jpg, was "279?630/1130512"
    ("weak-comma-279630-1130512.png", (279_630, 1_130_512)),
    # incidents/235405-token/144_t+07.4s.jpg: the slash's foot is not a comma
    ("slash-foot-327605-955877.png", (327_605, 955_877)),
    # incidents/20260928-205316-hud-hold/000_t+00.0s.jpg: the 15 px font, its
    # rate suffix only 12 px after the value; a 0.9-height cut read it
    # "0/2,962,170??18/????"
    ("rate-suffix-15px-0-2962170.png", (0, 2_962_170)),
])
def test_pollen_commas_by_shape(templates, name, value):
    text, score = digits.read(cv2.imread(str(SCREENS / "pollen_pill" / name)), templates)
    assert digits.parse_fraction(text) == value, (text, score)


@pytest.mark.parametrize("text", ["1,193,", "1,191746", "1518,356", "1,108639179"])
def test_misgrouped_commas_are_not_a_number(text):
    # all four were accepted before; honey was 1.19-1.52 billion
    assert digits.to_int(text) is None


def test_plain_and_grouped_numbers_still_parse():
    assert digits.to_int("1,108,639,179") == 1_108_639_179
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
