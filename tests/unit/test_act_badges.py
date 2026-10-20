"""The badge look: off until switched on, one measured button, no keys, and
nothing believed until the page reads like the badge menu (act/badges)."""
from __future__ import annotations

import pytest

import numpy as np

from hivemind.act import badges
from hivemind.vision import questmenu


@pytest.fixture(autouse=True)
def _buttons_show(monkeypatch):
    """These drawn frames carry no HUD icons; whether a button shows is
    test_roblox_overlay's subject (vision/questmenu.button_check, A18)."""
    monkeypatch.setattr(questmenu, "button_check", lambda frame, name, template=None: (True, 1.0, 0.0))


def blank(value=0):
    return np.full((1080, 1920, 3), value, np.uint8)


def panel(value=0, fraction=0.5):
    frame = blank(value)
    frame[:int(1080 * fraction), :, :] = 200
    return frame


class FakeInput:
    def __init__(self):
        self.clicks = []
        self.wheel = []

    def click(self, x=None, y=None):
        self.clicks.append((x, y))

    # the pointer over the list and its wheel: no keys (the list's pages)
    def move_mouse(self, x, y):
        self.wheel.append(("over", x, y))

    def scroll(self, steps=1, horizontal=False):
        self.wheel.append(("scroll", steps))

    def __getattr__(self, name):
        raise AssertionError(f"act/badges must not use {name!r}")


class Settings:
    def __init__(self, on):
        self.on = on

    def bool(self, key):
        assert key == "badges.look"
        return self.on


def player(frames):
    seen = list(frames)

    def next_frame():
        return seen.pop(0) if len(seen) > 1 else seen[0]
    return next_frame


ROSETTE = questmenu.button_at(questmenu.BUTTONS.index("badges"))
PAGE = "Badges\nSunflower Badge - Cadet\nCollect 50,000 pollen from the Sunflower Field\nClaim"


def test_off_means_no_click():
    vin = FakeInput()
    for settings in (None, Settings(False)):
        look = badges.look(vin, player([blank()]), lambda f: PAGE, settings=settings,
                           sleep=lambda s: None)
        assert not look.ok and vin.clicks == []


def test_it_is_the_rosette_and_never_the_robux_shop():
    assert ROSETTE == (195, 128)
    assert ROSETTE != questmenu.button_at(questmenu.BUTTONS.index("robux_shop"))


def test_a_badge_page_is_kept_and_closed_with_the_same_button(tmp_path):
    vin = FakeInput()
    look = badges.look(vin, player([blank(), panel(), blank(), blank()]), lambda f: PAGE,
                       settings=Settings(True), sleep=lambda s: None, keep_dir=tmp_path,
                       stamp="s1")
    assert look.ok and look.claimable and not look.menu_open, look.describe()
    assert vin.clicks == [ROSETTE, ROSETTE], "open, then close, with the same button"
    assert (tmp_path / "s1" / "page.jpg").exists() and "Sunflower" in (tmp_path / "s1" / "page.txt").read_text()


def test_nothing_opening_is_one_click_and_no_more(tmp_path):
    vin = FakeInput()
    look = badges.look(vin, player([blank()]), lambda f: PAGE, settings=Settings(True),
                       sleep=lambda s: None, keep_dir=tmp_path)
    assert not look.ok and "nothing opened" in look.reason
    assert vin.clicks == [ROSETTE]


def test_a_page_that_is_not_the_badge_menu_is_backed_out_of(tmp_path):
    vin = FakeInput()
    look = badges.look(vin, player([blank(), panel(), blank(), blank()]),
                       lambda f: "Settings\nMusic volume\nCamera sensitivity",
                       settings=Settings(True), sleep=lambda s: None, keep_dir=tmp_path)
    assert not look.ok and "does not read like the badge menu" in look.reason
    assert vin.clicks == [ROSETTE, ROSETTE] and not look.menu_open


def test_the_whole_list_is_read_with_the_pointer_over_it_then_once_in_six_hours(tmp_path):
    # MEASURED 2026-10-07 03:22: the field badges are below the first page
    vin = FakeInput()
    pages = [blank(), panel(), panel(90, 0.7), panel(30, 0.4), panel(30, 0.4), blank(), blank()]
    look = badges.look(vin, player(pages), lambda f: PAGE, settings=Settings(True),
                       sleep=lambda s: None, keep_dir=tmp_path, stamp="s1")
    assert look.ok and look.pages == 3, look.describe()
    # to the list's top first (the menu opens where it was left), then down
    assert vin.wheel[:4] == [("over", *badges.LIST_POINT),
                             ("scroll", -badges.PAGE_NOTCHES * badges.PAGES_MOST),
                             ("over", *badges.LIST_POINT), ("scroll", badges.PAGE_NOTCHES)]
    assert (tmp_path / "s1" / "page-top.jpg").exists() and (tmp_path / "s1" / "page-01.jpg").exists()
    assert vin.clicks == [ROSETTE, ROSETTE]
    again = FakeInput()
    look = badges.look(again, player([blank(), panel(), blank()]), lambda f: PAGE,
                       settings=Settings(True), sleep=lambda s: None, keep_dir=tmp_path,
                       stamp="s2")
    assert look.ok and look.pages == 1 and not [w for w in again.wheel if w[0] == "scroll"]


def test_a_page_that_reads_wrong_is_tried_again_next_run(tmp_path):
    # MEASURED 2026-10-07 03:48: page 1 read as the Cub Buddy's notification;
    # the list was not read to its end, so the next run tries it again
    vin = FakeInput()
    texts = iter([PAGE, "Buddy made some gifts!\n+1 Treat (from Cub Buddy)"])
    look = badges.look(vin, player([blank(), panel(), panel(90, 0.7), blank(), blank()]),
                       lambda f: next(texts, PAGE), settings=Settings(True),
                       sleep=lambda s: None, keep_dir=tmp_path, stamp="s1")
    assert look.ok and look.pages == 1
    assert badges._all_due(tmp_path)


def _bar(frame, y0, y1, upto=1.0):
    """A progress bar in the list: the badge menu's green (H 58 S 157 V 249,
    measured 04:02) to `upto` of its width, its red after."""
    import cv2
    green = cv2.cvtColor(np.uint8([[[58, 157, 249]]]), cv2.COLOR_HSV2BGR)[0, 0]
    red = cv2.cvtColor(np.uint8([[[3, 158, 240]]]), cv2.COLOR_HSV2BGR)[0, 0]
    split = 10 + int(287 * upto)
    frame[y0:y1, 10:split] = green
    frame[y0:y1, split:297] = red
    return frame


def test_a_complete_badge_is_pressed_once_and_counted_when_its_bar_empties(tmp_path):
    # MEASURED 2026-10-07 04:02: the Blue Flower Badge's bar all green,
    # "Complete! Press To Collect."; Pine Tree's at 79% and Mountain Top's at
    # 95% are green to x 230 and red under the ticket -- not complete
    [(x, y)] = badges.full_bars(_bar(panel(), 400, 440))
    assert x == 153 and abs(y - 420) <= 2
    assert badges.full_bars(_bar(panel(), 400, 440, upto=0.95)) == []
    vin = FakeInput()
    opened, collected = _bar(panel(), 400, 440), _bar(panel(), 400, 440, upto=0.1)
    look = badges.look(vin, player([blank(), opened, collected, blank(), blank()]),
                       lambda f: PAGE, settings=Settings(True), sleep=lambda s: None,
                       keep_dir=tmp_path, stamp="s1")
    assert look.collected == 1, look.describe()
    assert vin.clicks[0] == ROSETTE and vin.clicks[1][0] == 153 and abs(vin.clicks[1][1] - 420) <= 2
