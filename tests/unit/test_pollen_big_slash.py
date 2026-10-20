"""The pollen pill in its BIGGER font (data/templates/digits slash_big*).

MEASURED 2026-10-02: a short pollen text, "225/2,587,500", is drawn bigger
than a long one -- digits 12-13 px tall against 11, the slash 16-18 px -- and
none of the slash templates scored over 0.48 on it, so 322 saved frames read
"225?2,587,500". Three slashes, one of each height, cut from frames read by
eye, read them; old against new templates on 10,242 saved frames: no read that
worked changed, 257 more read, no honey read holds a slash. A big-font "5"
template ALONE was refused: it read the big "3" as a "5" ("53/3,622,500" as
5,622,500). With a big "3" beside it, both cut from that one pill: 103 more
pollen reads and 1 honey, none that worked changed, 20 of them checked by eye
-- every 3 and 5 right.
"""
from __future__ import annotations

import pathlib

import cv2
import pytest

from hivemind.vision import digits
from hivemind.vision import screenstate as ss

PILLS = (pathlib.Path(__file__).resolve().parents[1]
         / "fixtures" / "screens" / "pollen_pill")
TEMPLATES = (pathlib.Path(__file__).resolve().parents[2]
             / "data" / "templates" / "digits")


@pytest.fixture(scope="module")
def templates():
    return ss.load_templates(TEMPLATES)


def read(templates, name):
    pill = cv2.imread(str(PILLS / name))
    assert pill is not None, name
    text, _score = digits.read(pill, templates)
    return digits.parse_fraction(text)


@pytest.mark.parametrize("name, want", [
    ("big-225-2587500.png", (225, 2_587_500)),
    ("big-1708-2975625.png", (1_708, 2_975_625)),
    ("big-882-3784219.png", (882, 3_784_219)),
    ("big-17-2898000.png", (17, 2_898_000)),
])
def test_the_big_slash_reads(templates, name, want):
    assert read(templates, name) == want


@pytest.mark.parametrize("name, truth", [
    ("big-34-2587500-big-fives.png", (34, 2_587_500)),
    ("big-53-3622500-big-threes.png", (53, 3_622_500)),
])
def test_the_big_threes_and_fives_read_and_are_never_swapped(templates, name, truth):
    assert read(templates, name) == truth
