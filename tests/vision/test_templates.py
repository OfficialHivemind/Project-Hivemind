"""UI landmark matching.

The case that motivated all of this: on the Bee Swarm game page the rows read

    Server Size      6
    ...
    Servers      View >

A tight crop of the word "Servers" matches the *prefix* of "Server Size" at
0.877. The exploration run took that as its target, stopped scrolling and
clicked the wrong row -- landing on "Server Size", which does nothing. Widening
the template past the word (blank space after "Servers", the word "Size" after
"Server") drops that false match to 0.695 while true matches stay at 1.000.

These tests pin both halves: that the right row is found, and that the decoy is
not.
"""
import pathlib

import cv2
import pytest

from hivemind.vision.templates import find, find_all, load

SCREENS = pathlib.Path(__file__).resolve().parents[1] / "fixtures/screens"
UI = pathlib.Path(__file__).resolve().parents[2] / "data" / "templates" / "ui"

THRESHOLD = 0.90          # sits in the measured gap between 0.695 and 1.000


@pytest.fixture(scope="module")
def servers_label():
    path = UI / "servers_label.png"
    if not path.exists():
        pytest.skip("servers_label.png not extracted yet")
    return load(path)


def frame(name: str):
    path = SCREENS / f"{name}.png"
    if not path.exists():
        pytest.skip(f"fixture {name}.png not captured")
    return cv2.imread(str(path))


def test_finds_the_servers_row(servers_label):
    hit = find(frame("game_page_servers_row"), servers_label, threshold=THRESHOLD)
    assert hit is not None
    assert hit.score >= 0.99
    assert hit.cy == 543          # MEASURED on this capture


def test_does_not_match_server_size_row(servers_label):
    """The decoy. 'Servers' is a prefix of 'Server Size'."""
    scored = find(frame("game_page_top"), servers_label, threshold=0.0)
    assert scored.score < THRESHOLD


def test_absent_on_the_home_page(servers_label):
    assert find(frame("app_home"), servers_label, threshold=THRESHOLD) is None


def test_absent_in_game(servers_label):
    assert find(frame("in_game"), servers_label, threshold=THRESHOLD) is None


def test_exactly_one_match_on_the_game_page(servers_label):
    """One row, one hit -- not a cluster of near-duplicate offsets."""
    hits = find_all(frame("game_page_servers_row"), servers_label,
                    threshold=THRESHOLD)
    assert len(hits) == 1


def test_region_restricts_the_search(servers_label):
    img = frame("game_page_servers_row")
    assert find(img, servers_label, threshold=THRESHOLD,
                region=(0, 0, 1920, 400)) is None
    assert find(img, servers_label, threshold=THRESHOLD,
                region=(0, 400, 1920, 400)) is not None


def test_match_centre_is_inside_the_match(servers_label):
    hit = find(frame("game_page_servers_row"), servers_label, threshold=THRESHOLD)
    cx, cy = hit.centre
    assert hit.x <= cx <= hit.x + hit.w
    assert hit.y <= cy <= hit.y + hit.h


def test_oversized_template_returns_none(servers_label):
    small = frame("game_page_servers_row")[:10, :10]
    assert find(small, servers_label, threshold=0.0) is None
