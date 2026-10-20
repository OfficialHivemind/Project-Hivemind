"""Honey beside a SHORT rate (vision/digits.segment).

MEASURED 2026-10-02: the honey rate the HUD appends renders in a bigger font
when it is short -- "(+6,285/sec)" beside "(+297,385/sec)" -- and its
parentheses (11 and 13 px tall beside the value's 15) pulled the pill's median
glyph height off the digits. Every 10 px digit was then cut in four and Honey
read as forty "?": in the field before every Micro-Converter of the night, and
on the hive pad before a convert whenever the honey rate was low. These are
the honey pills of the bot's own kept frames (var/hotbar, 00:40 and 05:02).
"""
from __future__ import annotations

import pathlib

import cv2
import pytest

from hivemind.vision import digits
from hivemind.vision import screenstate as ss

PILLS = (pathlib.Path(__file__).resolve().parents[1]
         / "fixtures" / "screens" / "honey_pill")
TEMPLATES = (pathlib.Path(__file__).resolve().parents[2]
             / "data" / "templates" / "digits")


@pytest.fixture(scope="module")
def templates():
    return ss.load_templates(TEMPLATES)


@pytest.mark.parametrize("name, value", [
    ("short-rate-311529970.png", 311_529_970),     # "(+6,285/sec)"
    ("short-rate-151641110.png", 151_641_110),     # "(+4,274/sec)"
    ("long-rate-155432337.png", 155_432_337),      # "(+297,385/sec)", read before too
])
def test_honey_reads_beside_a_short_or_long_rate(templates, name, value):
    pill = cv2.imread(str(PILLS / name))
    assert pill is not None, name
    text, score = digits.read(pill, templates)
    assert digits.to_int(text) == value, (text, score)


def test_the_value_sets_the_glyph_size_not_the_rate(templates):
    pill = cv2.imread(str(PILLS / "short-rate-311529970.png"))
    glyphs = digits.leading_run(digits.segment(pill))
    # nine digits and two commas, none of them sliced
    assert len(glyphs) == 11
    assert sorted({g.w for g in glyphs if g.h >= 12}) == [9, 10]
