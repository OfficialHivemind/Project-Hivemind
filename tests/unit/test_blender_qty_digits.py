"""The quantity box's digits-only fallback (act/blender._digits): MEASURED
2026-10-14 09:04:28 the line read missed a plain "6" and the visit was cancelled."""
import shutil
from pathlib import Path

import cv2
import pytest

from hivemind.act import blender

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "blender"
BOX = (767, 650, 860, 700)          # the box left of the "+" (qty-row.jpg)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="reads through tesseract; none on PATH")
def test_the_digits_read_reads_the_box_the_line_read_missed():
    assert blender._digits(cv2.imread(str(FIX / "qty-6.jpg")), BOX) == 6
    assert blender._digits(cv2.imread(str(FIX / "qty-5.jpg")), BOX) == 5
    assert blender._digits(cv2.imread(str(FIX / "qty-row.jpg")), BOX) == 1
