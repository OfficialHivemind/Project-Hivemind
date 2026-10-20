"""Digits on the pollen fill, one soft column off their template (vision/digits
SLACK, 2026-10-26). MEASURED: a 7-digit value under the fill failed as "?" when
one anti-aliased column shifted a glyph against its template; sliding the
template fixed it, but sliding freely read a slash+2 blob as a "7". The pills
are crops (958, 22, 300, 36) of the bot's own frames, named in each comment.
"""
from __future__ import annotations

import pathlib

import cv2
import pytest

import hivemind
from hivemind.vision import digits
from hivemind.vision import screenstate as ss

ROOT = pathlib.Path(hivemind.__file__).resolve().parents[2]
PILLS = ROOT / "tests" / "fixtures" / "screens" / "pollen_pill"


@pytest.fixture(scope="module")
def templates():
    return ss.load_templates(ROOT / "data" / "templates" / "digits")


def _read(templates, name):
    return digits.read(cv2.imread(str(PILLS / name)), templates)


@pytest.mark.parametrize("name, value", [
    # routes/attempt-1201/193119-*-jump_release-.jpg, was "?,168,197/..."
    ("green-fill-one-1168197-10560237.png", (1_168_197, 10_560_237)),
    # routes/attempt-1201/152001-*-walk-w120.jpg, was "7,338,21?/1?,298,413"
    ("olive-fill-zeros-7338210-10298413.png", (7_338_210, 10_298_413)),
])
def test_a_glyph_one_column_off_still_reads(templates, name, value):
    text, score = _read(templates, name)
    assert digits.parse_fraction(text) == value, (text, score)


def test_the_slide_never_reads_part_of_a_wide_blob(templates):
    # incidents/20260926-102314-mob-sighting/034_t+02.5s.jpg: the true pill is
    # 1,086,612/2,478,094; the "/2" blob must stay "?", never a confident 7
    text, score = _read(templates, "slash-two-blob-1086612-2478094.png")
    assert digits.parse_fraction(text) is None, (text, score)
    assert text.startswith("1,086,612/"), text
