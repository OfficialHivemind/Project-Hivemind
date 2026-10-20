"""The red attack disc. See vision/hurt for the measurements these pin."""
from __future__ import annotations

import glob
import pathlib

import cv2
import numpy as np
import pytest

from hivemind.vision import hurt

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _last(window):
    f = sorted(glob.glob(str(ROOT / f"var/incidents/{window}/*.jpg")))
    if not f:
        pytest.skip(f"{window} is not in the repo")
    return cv2.imread(f[-1])


@pytest.mark.parametrize("window", ["051548-mob-sighting", "023452-mob-sighting",
                                    "223853-mob-sighting"])
def test_an_attacked_frame_shows_the_disc(window):
    found = hurt.find(_last(window))
    assert found is not None, window
    assert found.fraction >= hurt.MIN_DISC_FRACTION


@pytest.mark.parametrize("window", ["000336-mob-sighting", "234344-token",
                                    "234323-token"])
def test_a_normal_field_frame_does_not(window):
    assert hurt.find(_last(window)) is None, window


def test_a_red_thing_off_to_the_side_is_not_the_disc():
    img = np.full((1080, 1920, 3), (60, 140, 60), np.uint8)
    cv2.rectangle(img, (1500, 300), (1900, 900), (30, 30, 220), -1)   # big, but not on us
    assert hurt.find(img) is None


def test_a_disc_over_the_player_is():
    img = np.full((1080, 1920, 3), (60, 140, 60), np.uint8)
    cv2.circle(img, (960, 600), 350, (40, 40, 230), -1)
    found = hurt.find(img)
    assert found is not None and "attack disc" in found.describe()


def test_many_small_red_flowers_are_not_an_attack():
    """The Rose Field is red: many small blobs, none of them the disc."""
    img = np.full((1080, 1920, 3), (60, 140, 60), np.uint8)
    for x in range(200, 1800, 70):
        for y in range(300, 950, 70):
            cv2.circle(img, (x, y), 18, (40, 40, 230), -1)
    assert hurt.find(img) is None


def test_empty_and_missing_frames_are_not_errors():
    assert hurt.find(None) is None
    assert hurt.find(np.zeros((0, 0, 3), np.uint8)) is None
    assert hurt.attacked(np.zeros((1080, 1920, 3), np.uint8)) is False
