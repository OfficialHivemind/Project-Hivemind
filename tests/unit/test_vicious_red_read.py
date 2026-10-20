"""The Vicious Bee's red attack message (2026-10-23, Clover): the grey
read lost it; the red channel + tolerant words catch it."""
from pathlib import Path

import pytest

from hivemind.act import vicious

FRAME = Path.home() / "Hivemind/var/vicious/20261023-204232/0032.1-check.jpg"


@pytest.mark.parametrize("line,want", [
    ("A Vicmus Bee is aftackmg Pl4yerOne n the Clover Feld A", "found"),   # MEASURED misread
    ("A Vcious Bee is attarking P1ayer0ne n the Clover Field A", "found"),  # MEASURED 15 Oct
    ("A Vicus Bee is atecking PlayerOne n te Spider Fitd A.", "found"),     # MEASURED 13 Oct
    ("A Vecrous Bee is attackng PIayerOne n the C lover Fieid A", "found"),
    ("Vicious Bee is attacking someone in the Rose Field!", "found"),
    ("Vicious Bee has been defeated!", "killed"),
    ("Vicious Bee left the field", "left"),
])
def test_tolerant_words(line, want):
    assert vicious.heard([line]) == want


@pytest.mark.parametrize("line", ["Defeated Ladybug!", "+10 Honey", "Bee Bear is here",
                                  "Honey Bee attack boost", ""])
def test_no_false_bee(line):
    assert vicious.heard([line]) == ""


def test_the_23_oct_frame_is_heard_through_the_red_channel():
    if not FRAME.exists():
        pytest.skip("the owner's saved hunt frame is not on this machine")
    import cv2
    from hivemind.vision import amulet, notices
    frame = cv2.imread(str(FRAME))
    grey = vicious.heard(vicious.rows(amulet.read_words(frame, region=vicious.MESSAGE_REGION)))
    assert grey == ""                                   # the old read: missed
    assert vicious.heard(notices.read_red(frame)) == "found"
