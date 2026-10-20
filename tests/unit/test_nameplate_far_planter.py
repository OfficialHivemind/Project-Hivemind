"""vision/nameplate.find_planter_bars: a planter's bar from afar, not a mob's."""
from pathlib import Path

import cv2

from hivemind.vision import nameplate

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "planters"


def test_the_blue_clay_planter_is_found_from_afar():
    # MEASURED 2026-10-10 22:52: "Blue Clay Planter (100.0%)", 104x14, dark text
    bars = nameplate.find_planter_bars(cv2.imread(str(FIX / "blue-clay-far.jpg")))
    assert any(abs(x - 684) < 10 and abs(y - 118) < 10 for x, y, _w, _h in bars)


def test_a_spiders_bar_is_not_a_planter():
    # "Spider (Lvl 4)" over "HP: 100" -- its label above rules it out
    frame = cv2.imread(str(FIX / "spider-bar-not-a-planter.jpg"))
    assert not [b for b in nameplate.find_planter_bars(frame)
                if abs(b[0] - 550) < 20 and abs(b[1] - 235) < 20]
