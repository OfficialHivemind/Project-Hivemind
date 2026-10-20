"""The reward feed read by tesseract (vision/feed.read_text), and the source
parser that takes its "rom ...)" (vision/whereami.FROM)."""
from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from hivemind.vision import feed, whereami

KNOWN = {"pine tree": "pine_tree", "pumpkin": "pumpkin", "mountain top": "mountain_top"}


def pill(text="+5,431 Honey (from Pine Tree Forest)", w=560):
    img = np.zeros((40, w, 3), np.uint8)
    img[:] = (235, 120, 30)                       # BGR: the pill's blue, hue ~104
    cv2.putText(img, text, (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2,
                cv2.LINE_AA)
    return img


class Script:
    """A fake `run` handing tesseract's answers back in turn."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    def __call__(self, argv, input=None, capture_output=True, timeout=None):
        self.calls += 1
        assert argv[:3] == ["tesseract", "stdin", "stdout"] and "afr" in argv
        return SimpleNamespace(stdout=self.answers.pop(0).encode())


def test_the_grey_read_is_kept_when_it_names_a_source():
    run = Script("+5,431 Honey (from Pine Tree Forest)")
    assert feed.read_text(pill(), run=run) == "+5,431 Honey (from Pine Tree Forest)"
    assert run.calls == 1


def test_the_white_pass_is_read_when_the_grey_one_names_no_source():
    run = Script("+1,463 Honey Pumpkin Patch", "+1,463 Honey (from Pumpkin Patch)")
    assert feed.read_text(pill(), run=run) == "+1,463 Honey (from Pumpkin Patch)"
    assert run.calls == 2


def test_neither_naming_a_source_keeps_the_grey_words_and_never_joins_them():
    run = Script("Defeated Mantis! (+5 Battle Points)", "Defeated Mantis! (+5 Battle Points)")
    text = feed.read_text(pill(), run=run)
    assert text == "Defeated Mantis! (+5 Battle Points)"   # one kill line, not two


def test_no_tesseract_or_no_strip_is_no_text():
    def broken(*a, **k):
        raise OSError("no tesseract")
    assert feed.read_text(pill(), run=broken) == ""
    assert feed.read_text(None) == ""
    assert feed.read_text(np.zeros((0, 0, 3), np.uint8)) == ""


def test_a_credit_that_lost_its_f_still_names_the_field():
    """3 of tesseract's 4 misses against the model read "rom ...)"."""
    assert whereami.field_in("t1 Blueberry rom Pine Tree Forest)", KNOWN) == "pine_tree"
    assert whereami.field_in("+1,463 Honey (from Pumpkin Patch)", KNOWN) == "pumpkin"
    assert whereami.field_in("+217 Honey (from Mantis)", KNOWN) is None
    assert whereami.field_in("Prom Night Forest)", KNOWN) is None


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="no tesseract here")
def test_real_tesseract_reads_a_drawn_credit():
    text = feed.read_text(pill())
    assert whereami.field_in(text, KNOWN) == "pine_tree", text
