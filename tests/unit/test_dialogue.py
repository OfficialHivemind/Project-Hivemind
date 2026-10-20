"""The NPC dialogue box: finding it, and turning its pages with a click.

EVERY NUMBER HERE COMES OFF TWO FRAMES, `var/bears/black_bear-dialogue-032911
.jpg` and `var/bears/black_bear-after-leaving-032930.jpg`, saved nineteen
seconds apart on 2026-09-23 with `natro_back_black_bear` run in between. The
three facts they establish are the reason this module exists:

  * the box's body is blue HSV ~(108, 205, 168) and fills a rectangle;
  * that rectangle was x=716 y=763 w=489 h=117 in BOTH frames, to the pixel,
    so it is a screen-fixed UI overlay;
  * the character did not move between them, so an open dialogue swallows the
    movement keys and cannot be walked out of. The box itself says what does
    work: "Click to continue".
"""
from __future__ import annotations

import pathlib

import cv2
import numpy as np
import pytest

from hivemind.act import dialogue as D

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRAMES = ROOT / "var" / "bears"
OPEN_FRAMES = ("black_bear-dialogue-032911.jpg",
               "black_bear-after-leaving-032930.jpg")
SHUT_FRAMES = ("black_bear-021910.jpg", "black_bear-234012.jpg")


def _frame(name):
    path = FRAMES / name
    if not path.exists():
        pytest.skip(f"{name} is not in the repo")
    img = cv2.imread(str(path))
    if img is None:
        pytest.skip(f"{name} could not be read")
    return img


def _painted(rect=D.EXPECTED, hsv=(108, 205, 168), size=(1080, 1920)):
    """A frame with one filled rectangle of the box's own blue."""
    frame = np.zeros((size[0], size[1], 3), np.uint8)
    x, y, w, h = rect
    patch = np.full((h, w, 3), hsv, np.uint8)
    frame[y:y + h, x:x + w] = cv2.cvtColor(patch, cv2.COLOR_HSV2BGR)
    return frame


# ---- finding it ------------------------------------------------------------
@pytest.mark.parametrize("name", OPEN_FRAMES)
def test_it_finds_the_box_on_the_frames_it_was_measured_from(name):
    box = D.find(_frame(name))
    assert box is not None, "the box it was calibrated on was not found"
    assert (box.x, box.y, box.w, box.h) == D.EXPECTED


@pytest.mark.parametrize("name", SHUT_FRAMES)
def test_it_finds_nothing_when_no_dialogue_is_open(name):
    assert D.find(_frame(name)) is None


def test_the_hive_pad_is_not_a_dialogue_box():
    """Both open frames also show the hive pad's blue mat, which is bigger
    than the box. If the pad were matching, the shut frames -- same pad, same
    camera -- would match too. This states it as its own claim."""
    for name in SHUT_FRAMES:
        frame = _frame(name)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        blue = cv2.inRange(hsv, np.array(D.BOX_HSV[0]), np.array(D.BOX_HSV[1]))
        assert blue.any(), f"{name} has no blue at all, so it proves nothing"
        assert D.find(frame) is None


def test_no_frame_is_not_a_box():
    assert D.find(None) is None


def test_a_ragged_patch_of_blue_is_not_a_box():
    frame = _painted()
    # knock holes in it until it is no longer a filled rectangle
    rng = np.random.default_rng(3)
    x, y, w, h = D.EXPECTED
    for _ in range(4_000):
        cx, cy = rng.integers(x, x + w), rng.integers(y, y + h)
        frame[cy:cy + 6, cx:cx + 6] = 0
    box = D.find(frame)
    assert box is None or box.fill >= D.MIN_FILL


def test_a_box_too_small_to_hold_a_sentence_is_not_one():
    assert D.find(_painted(rect=(716, 763, 120, 40))) is None


def test_the_click_goes_to_the_middle_of_the_box():
    box = D.find(_frame(OPEN_FRAMES[0]))
    x, y = box.centre
    ex, ey, ew, eh = D.EXPECTED
    assert x == ex + ew // 2 and y == ey + eh // 2
    assert ex < x < ex + ew and ey < y < ey + eh


# ---- turning the pages -----------------------------------------------------
class Clicks:
    def __init__(self):
        self.at = []

    def __call__(self, x, y):
        self.at.append((x, y))


def test_it_reads_every_page_and_stops_when_the_box_closes():
    open_frame, shut_frame = _painted(), np.zeros((1080, 1920, 3), np.uint8)
    pages = iter(["Black Bear Hello there. Click to continue",
                  "Black Bear Bring me 500,000 pollen. Click to continue"])
    # shut twice: CLOSED ONLY AFTER A SECOND LOOK (act/dialogue.advance)
    seen = iter([open_frame, open_frame, shut_frame, shut_frame])
    clicks = Clicks()
    out = D.advance(frames=lambda: next(seen), click=clicks,
                    transcribe=lambda f: next(pages), sleep=lambda s: None)
    assert out.pages == ["Black Bear Hello there. Click to continue",
                         "Black Bear Bring me 500,000 pollen. Click to continue"]
    assert out.clicks == 2 and out.closed
    assert clicks.at == [D.find(open_frame).centre] * 2


def test_it_presses_nothing_when_there_is_no_box():
    clicks = Clicks()
    out = D.advance(frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
                    click=clicks, transcribe=lambda f: "anything",
                    sleep=lambda s: None)
    assert clicks.at == [] and out.pages == [] and not out.closed
    assert "no box" in out.reason


def test_a_page_that_does_not_turn_is_not_clicked_again():
    """One click, the same words back. Clicking again at a screen that did
    not respond is clicking at a screen this does not understand."""
    clicks = Clicks()
    out = D.advance(frames=lambda: _painted(), click=clicks,
                    transcribe=lambda f: "Black Bear Hello. Click to continue",
                    sleep=lambda s: None)
    assert out.clicks == 1, f"clicked {out.clicks} times"
    assert len(out.pages) == 1
    assert "did not change" in out.reason


def test_it_stops_rather_than_clicking_for_ever():
    clicks, n = Clicks(), {"i": 0}

    def words(_frame):
        n["i"] += 1
        return f"page {n['i']}"

    out = D.advance(frames=lambda: _painted(), click=clicks,
                    transcribe=words, sleep=lambda s: None, max_pages=4)
    assert out.clicks == 4 and len(out.pages) == 4
    assert "stopped after 4 pages" in out.reason and not out.closed


def test_every_click_is_aimed_at_a_box_seen_on_that_very_frame():
    """The box could close between the look and the click, and a click into
    the world is a tool swing. So the position may never be remembered."""
    frames = [_painted(rect=(716, 763, 489, 117)),
              _painted(rect=(500, 900, 489, 117))]
    seen, clicks = iter(frames + [np.zeros((1080, 1920, 3), np.uint8)]), Clicks()
    pages = iter(["one", "two"])
    D.advance(frames=lambda: next(seen), click=clicks,
              transcribe=lambda f: next(pages), sleep=lambda s: None)
    assert clicks.at == [(716 + 244, 763 + 58), (500 + 244, 900 + 58)]


def test_a_click_that_fails_is_reported_not_retried():
    def boom(x, y):
        raise RuntimeError("no mouse")

    out = D.advance(frames=lambda: _painted(), click=boom,
                    transcribe=lambda f: "one", sleep=lambda s: None)
    assert out.clicks == 0 and "could not click" in out.reason


# ---- the night sky is the same blue ----------------------------------------
# Scanning the saved frames with the colour and fill tests alone found the two
# real boxes and one impostor: an 859x256 rectangle at (1061, 0), 80% filled,
# which is open night sky above the horizon. Without a position test it would
# have been clicked, and a click into the world is a tool swing.
SKY = ROOT / "var/homing/attempt-254/look18-row-no-d-y174218-b-0442.jpg"


def test_the_night_sky_is_not_a_dialogue_box():
    if not SKY.exists():
        pytest.skip("the night-sky frame is not in the repo")
    frame = cv2.imread(str(SKY))
    if frame is None:
        pytest.skip("the night-sky frame could not be read")
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.array(D.BOX_HSV[0]), np.array(D.BOX_HSV[1]))
    assert blue.sum() / 255 > 100_000, \
        "this frame no longer has a big blue expanse, so it proves nothing"
    assert D.find(frame) is None


def test_a_box_in_the_top_half_of_the_screen_is_not_one():
    assert D.find(_painted(rect=(716, 100, 489, 117))) is None


def test_a_box_wider_than_half_the_screen_is_not_one():
    assert D.find(_painted(rect=(200, 800, 1400, 117))) is None


def test_the_bounds_are_fractions_so_another_resolution_still_works():
    """The same layout at 720p must still be found -- a pixel rectangle would
    quietly match nothing there."""
    scale = 720 / 1080
    x, y, w, h = (int(v * scale) for v in D.EXPECTED)
    box = D.find(_painted(rect=(x, y, w, h), size=(720, 1280)))
    assert box is not None, "the same box at 720p was not found"


def test_none_on_a_frame_with_a_box_is_a_blank_read_not_a_page():
    """MEASURED 2026-10-03 02:41:57 at the Bucko Bee: 'NONE' read twice on a
    box between pages stopped the clicking as "the page did not change"."""
    open_frame, shut_frame = _painted(), np.zeros((1080, 1920, 3), np.uint8)
    pages = iter(["Gifted Bucko Bee Beautiful work! Click to continue", "NONE", "NONE",
                  "Gifted Bucko Bee Keep moving forward. Click to continue"])
    seen = iter([open_frame] * 4 + [shut_frame, shut_frame])
    clicks = Clicks()
    out = D.advance(frames=lambda: next(seen), click=clicks,
                    transcribe=lambda f: next(pages), sleep=lambda s: None)
    assert out.pages == ["Gifted Bucko Bee Beautiful work! Click to continue",
                         "Gifted Bucko Bee Keep moving forward. Click to continue"], out
    assert out.closed and out.blank_pages == 2


def test_a_line_said_again_later_is_a_new_page():
    """MEASURED 2026-10-07 18:29: the Spirit Bear says "Hmm..." at page 12 and
    again at page 24 -- the second is a page of its own, not one that failed
    to turn."""
    open_frame, shut_frame = _painted(), np.zeros((1080, 1920, 3), np.uint8)
    pages = iter(["Spirit Bear Hmm...", "Spirit Bear I planted the sunflowers.",
                  "Spirit Bear Hmm...", "Spirit Bear Will you help me?"])
    seen = iter([open_frame] * 4 + [shut_frame, shut_frame])
    out = D.advance(frames=lambda: next(seen), click=Clicks(),
                    transcribe=lambda f: next(pages), sleep=lambda s: None)
    assert len(out.pages) == 4 and out.closed, (out.pages, out.reason)
