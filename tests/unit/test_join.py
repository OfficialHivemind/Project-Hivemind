"""Finding the private server's Join button.

The drawer shows several visually identical Join buttons. The one belonging to
YOUR private server is drawn in Roblox blue; every public-server Join is grey.
MEASURED in HSV at the same hue: private S=62, public S=7. Saturation is the
entire signal, which is why the band is wide in H and V and tight only where it
discriminates.

The negative cases matter as much as the positive one. Clicking the wrong Join
puts the bot in a stranger's public server, which is both useless and exactly
the kind of silent wrong-but-plausible outcome this project keeps guarding
against.
"""
import pathlib

import cv2
import pytest

from hivemind.act.join import PANEL_X, drawer_open, find_primary_button

SCREENS = pathlib.Path(__file__).resolve().parents[1] / "fixtures/screens"


def frame(name: str):
    path = SCREENS / f"{name}.png"
    if not path.exists():
        pytest.skip(f"fixture {name}.png not captured")
    return cv2.imread(str(path))


def test_finds_the_private_server_join_button():
    button = find_primary_button(frame("servers_drawer_private"))
    assert button is not None
    # MEASURED on the capture: (1841, 213) 63x32, centre (1872, 229)
    assert 1850 <= button.cx <= 1895
    assert 210 <= button.cy <= 250


def test_ignores_the_grey_public_server_joins():
    """The drawer scrolled past the private section shows only public servers."""
    assert find_primary_button(frame("servers_drawer_public")) is None


@pytest.mark.parametrize("name", ["game_page_servers_row", "app_home", "in_game"])
def test_no_false_positive_when_the_drawer_is_not_open(name):
    assert find_primary_button(frame(name)) is None


def test_search_is_confined_to_the_drawer():
    """Blue chrome on the app's left side must not be mistaken for the button."""
    img = frame("servers_drawer_private")
    # pushing the panel boundary past the button hides it entirely
    assert find_primary_button(img, panel_x=1900) is None
    assert find_primary_button(img, panel_x=PANEL_X) is not None


def test_a_tiny_blue_speck_is_not_a_button():
    assert find_primary_button(frame("servers_drawer_private"),
                               min_area=40_000) is None


def test_a_blue_game_thumbnail_is_not_a_button():
    """The regression. The app home yields blue blobs of 73x33 and 76x35 inside
    game thumbnails, against the real button's 63x32 -- genuinely the same shape,
    so no size or aspect rule separates them. The drawer gate does."""
    assert find_primary_button(frame("app_home")) is None
    # and confirm WHY: with the gate lifted, the decoys are indeed found
    assert find_primary_button(frame("app_home"), require_drawer=False) is not None


@pytest.mark.parametrize("name,expected", [
    ("servers_drawer_private", True), ("servers_drawer_public", True),
    ("app_home", False), ("in_game", False), ("game_page_servers_row", False)])
def test_drawer_detection(name, expected):
    assert drawer_open(frame(name)) is expected


def test_the_real_button_is_within_the_size_gate():
    button = find_primary_button(frame("servers_drawer_private"))
    assert 18 <= button.h <= 60 and button.w <= 220
