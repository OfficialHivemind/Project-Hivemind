"""The top-centre notification panel, measured against real frames.

These are not synthetic. They are twelve 1920x1080 captures of the live game
taken during the hive-slot sweep (00:35) and the prompt run (00:58) on
2026-09-20, kept in `tests/fixtures/screens/hive` precisely so this detector
can be re-validated without the game running.
"""
from __future__ import annotations

import pathlib

import cv2
import pytest

from hivemind.vision import banner

HIVE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "screens" / "hive"
SCREENS = HIVE.parent

# MEASURED: these five carry the panel, the other seven do not, and every
# positive lands on the same pixels.
WITH_PANEL = ["slot_4_after_1_hops.png", "slot_3_after_2_hops.png",
              "slot_1_after_4_hops.png", "prompt_hop1.png", "prompt_hop4.png"]
WITHOUT_PANEL = ["slot_5_after_0_hops.png", "slot_2_after_3_hops.png",
                 "slot_0_after_5_hops.png", "prompt_hop0.png",
                 "prompt_hop2.png", "prompt_hop3.png", "prompt_hop5.png"]
PANEL_BOX = (784, 62, 352, 58)


def load(name: str):
    path = HIVE / name
    if not path.exists():
        pytest.skip(f"fixture {name} is not in the repo")
    return cv2.imread(str(path))


@pytest.mark.parametrize("name", WITH_PANEL)
def test_the_panel_is_found_where_it_really_is(name):
    panel = banner.find(load(name))
    assert panel is not None, f"{name} has a notification panel and it was missed"
    assert panel.box == PANEL_BOX, (
        f"{name}: the panel moved — every measured positive is at {PANEL_BOX}")


@pytest.mark.parametrize("name", WITHOUT_PANEL)
def test_no_panel_is_invented_where_there_is_none(name):
    assert banner.find(load(name)) is None, (
        f"{name} has no notification panel, so finding one is a false positive "
        f"— and a false positive here makes the hive reader transcribe scenery")


@pytest.mark.parametrize("name", ["in_game.png", "reset_dialog.png",
                                  "escape_menu.png", "app_home.png",
                                  "hive_short_pollen.png"])
def test_other_real_screens_do_not_trigger_it(name):
    path = SCREENS / name
    if not path.exists():
        pytest.skip(f"fixture {name} is not in the repo")
    assert banner.find(cv2.imread(str(path))) is None, (
        f"{name} is a real screen with no notification panel on it")


def test_the_sky_decoy_is_rejected_on_shape_not_colour():
    """The patch of blue sky is the same hue and a similar area.

    It is rejected because it is nearly square (aspect ~1.4 against the
    panel's 6.1) and sits far off-centre. Colour alone finds both, which is
    why neither test above would pass on colour alone.
    """
    frame = load("slot_5_after_0_hops.png")      # sky visible, no panel
    assert banner.find(frame) is None
    # and the colour really is present in that frame, so the rejection is
    # doing work rather than the mask being empty
    mask = banner.PANEL_BLUE.mask(frame[0:banner.SEARCH_HEIGHT, :, :3])
    assert mask.any(), "no blue at all — then this test proves nothing"


def test_a_missing_or_empty_frame_is_not_a_panel():
    import numpy as np
    assert banner.find(None) is None
    assert banner.find(np.zeros((0, 0, 3), np.uint8)) is None


# ---- the red cooldown panel ----------------------------------------------------
# MEASURED 2026-09-23 21:06:51: the wealth clock recon arrived and the panel
# read "Use the Wealth Clock (57:22)" in a RED box at the blue box's exact
# place -- and this detector returned None. Red is gated to the panel's
# measured geometry because, scanned over 4,584 frames, red flowers and attack
# discs also pass the shape rules; the true red panels never leave the box.

def test_the_red_cooldown_panel_is_found_at_the_panels_own_box():
    path = SCREENS / "wealth_clock_cooldown.png"
    if not path.exists():
        pytest.skip("fixture wealth_clock_cooldown.png is not in the repo")
    panel = banner.find(cv2.imread(str(path)))
    assert panel is not None
    assert (panel.x, panel.y, panel.w, panel.h) == (784, 62, 352, 58), panel


@pytest.mark.parametrize("name", ["red_flowers_not_a_panel.png", "attack_disc_not_a_panel.png"])
def test_red_things_that_are_not_the_panel_are_not_the_panel(name):
    """The strongest red false positives in the corpus: a Strawberry Field
    frame whose flowers form a (786, 58, 355x86) blob, and an attack disc
    filling the search band."""
    path = SCREENS / name
    if not path.exists():
        pytest.skip(f"fixture {name} is not in the repo")
    assert banner.find(cv2.imread(str(path))) is None


def test_the_red_gate_is_the_measured_box():
    assert banner.PANEL_AT == (784, 62) and banner.PANEL_SIZE == (352, 58)
    assert banner._is_the_panels_box(banner.Panel(784, 62, 352, 58))
    assert banner._is_the_panels_box(banner.Panel(790, 70, 340, 70))
    assert not banner._is_the_panels_box(banner.Panel(786, 58, 355, 86))     # the flowers
    assert not banner._is_the_panels_box(banner.Panel(0, 0, 1920, 220))       # the disc
