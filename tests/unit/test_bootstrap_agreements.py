"""Roblox's "Updated Agreements" box is recognised, never answered (act/bootstrap)."""
from __future__ import annotations

import glob
import shutil
from pathlib import Path

import cv2
import pytest

from hivemind.act import bootstrap

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None,
                                     reason="tesseract is not installed")


@needs_tesseract
def test_the_box_of_2026_10_02_is_recognised():
    frame = cv2.imread(str(FIXTURES / "bootstrap" / "updated-agreements.jpg"))
    assert bootstrap.agreements_waiting(frame)


@needs_tesseract
@pytest.mark.parametrize("name", ["in_game.png", "app_home.png"])
def test_the_game_and_the_plain_app_home_are_not_the_box(name):
    frame = cv2.imread(str(FIXTURES / "screens" / name))
    assert frame is not None
    assert not bootstrap.agreements_waiting(frame)


def test_the_reason_says_it_is_the_owners_and_nothing_presses_it():
    assert "owner" in bootstrap.NEEDS_THE_OWNER
    assert "never the bot's" in bootstrap.NEEDS_THE_OWNER
    src = Path(bootstrap.__file__).read_text()
    # nothing in the bootstrap clicks or presses on an "agree"
    assert "click" not in src.split("def agreements_waiting")[1].split("CAPTURE_TRIES")[0]
