"""vision/nectar: the nectar levels off the buff bar (Natro's fill-height read)."""
from pathlib import Path

import cv2

from hivemind.vision import nectar

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "nectar"


def test_the_comforting_icon_reads_its_fill():
    # MEASURED 2026-10-11 00:14, after one Blue Clay harvest: 8-9 of 38 rows
    got = nectar.read(cv2.imread(str(FIX / "comforting-21.jpg")))
    assert 15 <= got["comforting"] <= 28
    assert got["refreshing"] == 0.0 and got["invigorating"] == 0.0       # no icon, no nectar


def test_no_frame_is_no_reading():
    assert all(v is None for v in nectar.read(None).values())
