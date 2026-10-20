"""Which red notice the game showed, read (vision/notices.read_newest, kind_of).

The sprinkler's refusals come in the same red: "You must be standing in a field
to build a Sprinkler." and, since the Pine Tree flight lands on the flowers
where the last trip's sprinkler still stands, "Cannot place sprinklers this
close to eachother." (var/hotbar, 2026-10-01 12:04). The second is no reason to
step back.
"""
from __future__ import annotations

import shutil

import cv2
import numpy as np
import pytest

from hivemind.vision import notices


def frame_with_notices(*texts):
    """A frame whose notice column holds these notices, oldest first, drawn as
    the game draws them: white words on a red bar, the newest lowest."""
    img = np.full((1080, 1920, 3), (60, 140, 60), np.uint8)
    y = 1033 - 30 * (len(texts) - 1)
    for text in texts:
        cv2.rectangle(img, (1566, y), (1903, y + 20), (40, 40, 210), -1)
        cv2.putText(img, text, (1572, y + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                    (255, 255, 255), 1, cv2.LINE_AA)
        y += 30
    return img


@pytest.mark.parametrize("text, kind", [
    ("Cannot place sprinklers this close to eachother.", "too_close"),
    ("Cannot place sprinklers this close to eachofher.", "too_close"),   # read so, live
    ("Cannot place sprinklers tnis close to eachofher.", "too_close"),
    ("You must be standing in a field to build a Sprinkler.", "not_in_field"),
    ("You must be standlnq in a field to build a Sprlnkler.", "not_in_field"),
    ("", "unknown"),
    ("Your bag is full", "unknown"),
])
def test_the_two_refusals_are_told_apart(text, kind):
    assert notices.kind_of(text) == kind


def test_the_newest_notice_is_the_lowest():
    img = frame_with_notices("older one", "newer one")
    box = notices.newest_box(img)
    assert box is not None
    x0, y0, x1, y1 = box
    assert 1030 <= y0 <= 1036 and 1050 <= y1 <= 1056          # the bottom bar, not the one above
    assert x0 <= 1570 and x1 >= 1900


def test_no_notice_reads_nothing():
    img = np.full((1080, 1920, 3), (60, 140, 60), np.uint8)
    assert notices.newest_box(img) is None
    assert notices.read_newest(img) == ""


def test_the_newest_notice_is_what_is_read():
    """Only the newest bar is given to tesseract (stood in for here: its TSV)."""
    img = frame_with_notices("You must be standing in a field", "Cannot place")
    asked = {}

    class Out:
        stdout = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                  "left\ttop\twidth\theight\tconf\ttext\n"
                  "5\t1\t1\t1\t1\t1\t10\t5\t60\t20\t95\tCannot\n"
                  "5\t1\t1\t1\t1\t2\t80\t5\t60\t20\t95\tclose\n").encode()

    def run(cmd, input=None, **kw):
        crop = cv2.imdecode(np.frombuffer(input, np.uint8), cv2.IMREAD_GRAYSCALE)
        asked["height"] = crop.shape[0]
        return Out()

    said = notices.read_newest(img, run=run)
    assert said == "Cannot close"
    assert notices.kind_of(said) == "too_close"
    assert asked["height"] < 70            # one bar (upscaled x2), not the column


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="no tesseract here")
def test_tesseract_reads_a_drawn_notice():
    said = notices.read_newest(frame_with_notices("Cannot place sprinklers this close to eachother."))
    assert notices.kind_of(said) == "too_close", said


def test_red_flowers_are_no_notice():
    """A red field across the column (Mountain Top, golden 2026-10-26) has no
    bar's wall-to-wall rows, or too many of them to be a bar's edge."""
    img = np.full((1080, 1920, 3), (60, 140, 60), np.uint8)
    for x in range(1480, 1915, 40):                       # patchy flowers
        cv2.circle(img, (x, 1000), 14, (40, 40, 210), -1)
    assert notices.newest_box(img) is None
    img[950:1075, 1480:1915] = (40, 40, 210)               # red wall to wall
    assert notices.newest_box(img) is None
