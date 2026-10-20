"""A growing planter is booked by the growth its own bar reads (act/planter
.read_growth, regrown), wherever the bar is on screen. MEASURED 2026-10-13: the
Blue Clay in Spider was booked 54 min on at 20:20:06 with no growth read, and
was back at 21:29 to a bar reading 81.4%."""
import shutil
from pathlib import Path

import cv2
import pytest

from hivemind.act import planter as P
from hivemind.vision.beemenu import TESSERACT

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "planter"


@pytest.mark.skipif(shutil.which(TESSERACT) is None, reason="no tesseract")
def test_its_bar_reads_81_4_and_books_it_67_min_on():
    frame = cv2.imread(str(FIX / "growing-blue-clay-81pct.png"))
    growth = P.read_growth(frame, "Blue Clay Planter")
    assert growth == pytest.approx(0.814)
    assert P.read_growth(frame, "Paper Planter") is None      # another planter's name
    st = P.placed({}, "blue_clay_planter", "spider", 0.0)      # 6 h in Spider
    now = 10 * 3600.0
    due, early = P.due_at(P.regrown(st, "blue_clay_planter", now, growth), "blue_clay_planter", {})
    assert not early and (due - now) / 60 == pytest.approx(0.186 * 360, abs=0.5)   # 67 min
