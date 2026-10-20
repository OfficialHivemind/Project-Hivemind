"""The HUD with a long pollen counter (vision/screenstate.hud_present). MEASURED
2026-10-21 22:45: "15,068,506/10,560,237" is drawn small, every glyph 8 px high
with the slash, so the taller-slash test failed with the HUD in view and the
bot looped stop -> rejoin (runs 1168-1170). The fixture is that frame's top bar."""
from __future__ import annotations

import pathlib

import cv2
import numpy as np

import hivemind
from hivemind.vision import screenstate as ss

FIX = pathlib.Path(hivemind.__file__).resolve().parents[2] / "tests/fixtures/screens/hud_long_counter_top.png"


def test_a_long_counter_with_no_taller_slash_is_still_the_hud():
    top = cv2.imread(str(FIX))
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[:top.shape[0]] = top
    assert ss.hud_present(frame)
