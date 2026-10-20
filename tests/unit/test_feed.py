"""Feeding the bees for a quest step (act/feed): the step read off the quest
menu, what is typed for it, and the Feed box filled in -- on the measured box
(2026-10-05 22:38) and on drawn ones laid out like it."""
from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

# var/quests.json, read 2026-10-05: the progress on the line under the step
TRANSCRIPT = ("Search For Sunflower Seeds\nRaise 6 Bees to Level 6.\nComplete!\n\n"
              "Feed 100 Treats to your Bees.\n0/100\n\n"
              "Feed 25 Sunflower Seeds to your Bees.\n0/25\nObtain 1 Red Drive.\n0/1")
LABELS = {"treats": "Treat", "sunflower_seed": "Sunflower Seed", "strawberry": "Strawberry",
          "blueberry": "Blueberry", "royal_jelly": "Royal Jelly"}


def test_a_feed_step_is_read_off_the_menu():
    from hivemind.brain.questneeds import from_lines
    needs = from_lines(TRANSCRIPT.splitlines())
    owed = {n.item: n.remaining for n in needs.feeds}
    assert owed == {"treats": 100, "sunflower seeds": 25}
    assert not any("Feed" in line for line in needs.unread)
    done = from_lines(["Feed 100 Treats to your Bees.", "Complete!"])
    assert [n.remaining for n in done.feeds] == [0]
    # two reads of one menu: the further one stands
    merged = from_lines(["Feed 25 Sunflower Seeds to your Bees. 0/25"]).merged_with(
        from_lines(["Feed 25 Sunflower Seeds to your Bees. 10/25"]))
    assert [(n.item, n.remaining) for n in merged.feeds] == [("sunflower seeds", 15)]


def test_only_hundreds_and_tens_are_typed():
    from hivemind.act import feed
    assert feed.chunks(100) == [100]
    assert feed.chunks(25) == [10, 10, 10]
    assert feed.chunks(250) == [100, 100, 100]
    assert feed.chunks(5000, most=2) == [100, 100]
    assert feed.chunks(0) == []


def test_the_step_names_its_row_by_the_rows_own_title():
    from hivemind.act import feed
    assert feed.item_of("treats", LABELS) == "treats"
    assert feed.item_of("sunflower seeds", LABELS) == "sunflower_seed"
    assert feed.item_of("Strawberries", LABELS) == "strawberry"
    assert feed.item_of("moon charms", LABELS) is None


def test_what_was_fed_since_the_read_is_not_fed_again():
    from hivemind.act import feed
    from hivemind.brain.questneeds import from_lines
    needs = from_lines(TRANSCRIPT.splitlines())
    # 30 seeds fed since the read cover the 25; the treats were fed before it
    fed = {"sunflower seeds": [[50.0, 10], [150.0, 10], [160.0, 10], [170.0, 10]],
           "treats": [[90.0, 100]]}
    assert feed.owed(needs.feeds, fed, read_at=100.0) == [("treats", 100)]
    assert feed.owed(needs.feeds, {"sunflower seeds": [[150.0, 10]]}, 100.0) == [
        ("treats", 100), ("sunflower seeds", 15)]


def test_the_cell_is_let_go_on_its_glow_or_after_the_dwell():
    from hivemind.act import feed
    now = [0.0]
    check = feed.lit_or_dwelt(lambda f: False, dwell=1.0, clock=lambda: now[0])
    assert not check("frame")
    now[0] = 0.5
    assert not check("frame")
    now[0] = 1.0
    assert check("frame")
    assert feed.lit_or_dwelt(lambda f: True)("frame")


# MEASURED 2026-10-05 22:38 (tests/fixtures/inventory/feed-box-sunflower.jpg)
FEED_BOX = (832, 474, 122, 48)      # x, y, w, h -- green "Feed:"
CANCEL_BOX = (832, 536, 121, 49)    # red
ALL_BOX = (968, 536, 122, 50)       # green "All (404)" -- never pressed
FIELD_BOX = (964, 474, 263, 48)     # right of Feed, blue with a white number


def _box_frame():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[369:598, 811:1248] = (240, 140, 60)                    # the panel's blue
    for (x, y, w, h), bgr in ((FEED_BOX, (40, 190, 40)), (CANCEL_BOX, (40, 40, 210)),
                              (ALL_BOX, (40, 190, 40)), (FIELD_BOX, (190, 90, 40))):
        frame[y:y + h, x:x + w] = bgr
    return frame


def _read(frame, box):
    """The button's own words, as vision/amulet.read_button would give them."""
    b, g, r = (int(v) for v in frame[box[1] + box[3] // 2, box[0] + 4])
    if g > 150 > r:
        return "Feed:" if box[1] < 520 else "All (404)"
    return "Cancel" if r > 150 > g else "?"


class _Game:
    """The box as the game is expected to keep it: the field cleared by the
    click that focuses it, digits added by each key, shut by Feed or Cancel."""

    def __init__(self, clears=True):
        self.open, self.clears, self.field = True, clears, "1"
        self.clicks, self.taps = [], []

    def click(self, x, y):
        self.clicks.append((x, y))
        fx, fy, fw, fh = FIELD_BOX
        if fx <= x <= fx + fw and fy <= y <= fy + fh and self.clears:
            self.field = ""
        ax, ay, aw, ah = ALL_BOX
        assert not (ax <= x <= ax + aw and ay <= y <= ay + ah), "All was pressed"
        for bx, by, bw, bh in (FEED_BOX, CANCEL_BOX):
            if bx <= x <= bx + bw and by <= y <= by + bh:
                self.open = False
        return True

    def tap(self, key):
        self.taps.append(key)
        if key.isdigit():
            self.field += key

    def frames(self):
        return _box_frame() if self.open else np.zeros((1080, 1920, 3), np.uint8)

    def ocr(self, frame, box):
        return self.field if self.open else ""


def _feed(game, amount):
    from hivemind.act import feed
    return feed.feed_box(game, game.frames, amount, ocr=game.ocr, read=_read,
                         words_of=lambda f, region: [], sleep=lambda s: None)


def test_the_box_is_filled_read_back_and_fed():
    game = _Game()
    ok, why = _feed(game, 100)
    assert ok, why
    assert game.taps == ["alt", "rightalt", "1", "0", "0"]
    fx, fy, fw, fh = FIELD_BOX
    assert fx <= game.clicks[0][0] <= fx + fw and fy <= game.clicks[0][1] <= fy + fh
    assert game.clicks[-1] == (FEED_BOX[0] + FEED_BOX[2] // 2, FEED_BOX[1] + FEED_BOX[3] // 2)


def test_a_field_that_does_not_read_back_is_cancelled():
    game = _Game(clears=False)                 # "1" left in it: "1100"
    ok, why = _feed(game, 100)
    assert not ok and "1100" in why and "Cancelled" in why
    assert game.clicks[-1] == (CANCEL_BOX[0] + CANCEL_BOX[2] // 2, CANCEL_BOX[1] + CANCEL_BOX[3] // 2)


def test_no_digit_but_one_and_zero_is_ever_typed():
    game = _Game()
    ok, why = _feed(game, 25)
    assert not ok and "1 and 0" in why
    assert game.taps == [] and game.clicks == []


def test_no_box_no_click():
    game = _Game()
    game.open = False
    ok, why = _feed(game, 100)
    assert not ok and "no box" in why
    assert game.clicks == [] and game.taps == []


class _DragVin(_Game):
    def drag(self, x0, y0, x1, y1, check=None):
        return bool(check()) if check is not None else True


def test_the_drop_hands_the_box_to_the_feeder(monkeypatch):
    from hivemind.act import feed, inventory
    page = np.zeros((900, 320, 3), np.uint8)
    monkeypatch.setattr(inventory, "_read_menu", lambda *a, on_page=None, **k: on_page(page))
    monkeypatch.setattr(inventory, "_crop_of", lambda frames, note: page)
    monkeypatch.setattr(inventory, "find_row", lambda page, name, ocr: 97 if name == "Treat" else None)
    monkeypatch.setattr(inventory, "row_count", lambda page, top: 21831)
    game = _DragVin()
    out = inventory.hatch_egg(
        game, game.frames, "Treat", (1117, 249), lit=lambda f: True,
        accept=lambda q: pytest.fail("the Yes/No question is not asked"),
        on_drop=lambda f: feed.feed_box(game, game.frames, 100, frame=f, ocr=game.ocr,
                                        read=_read, words_of=lambda f, r: [],
                                        sleep=lambda s: None),
        ocr=lambda f, box: "", sleep=lambda s: None)
    assert out.dropped and out.ok, out.reason
    assert game.taps == ["alt", "rightalt", "1", "0", "0"]


BOX = Path(__file__).resolve().parents[1] / "fixtures/inventory/feed-box-sunflower.jpg"


def test_the_measured_box_reads_its_buttons_field_and_question():
    import shutil
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is not installed")
    from hivemind.act import feed, shoplook
    from hivemind.vision import amulet
    frame = cv2.imread(str(BOX))
    found = feed.buttons(frame)
    assert found["feed"] == (832, 474, 122, 48) and found["cancel"] == (832, 536, 121, 49)
    x, y, box = feed.field_at(frame, found["feed"])
    assert box == (964, 474, 263, 48) and (x, y) == (1095, 498)
    assert amulet.read_button(frame, box) == "1"
    asked = shoplook._ocr_line(frame, (832, 474 - feed.TITLE_ABOVE[0], 832 + feed.TITLE_W,
                                       474 - feed.TITLE_ABOVE[1]), psm=6)
    assert "sunflower seed" in feed._singular(asked)


def test_a_box_asking_about_another_item_is_cancelled():
    game = _Game()
    from hivemind.act import feed
    ok, why = feed.feed_box(game, game.frames, 100, ocr=game.ocr, read=_read,
                            words_of=lambda f, region: [], item="treats",
                            title_ocr=lambda f, b: "How many Sunflower Seeds will you feed to Demon Bee?",
                            sleep=lambda s: None)
    assert not ok and "not about treats" in why and game.taps == []


def test_the_fields_ones_and_zeros_are_read_by_their_shape():
    # MEASURED 2026-10-06 02:43: the field showed "100" and the OCR read "160"
    from hivemind.act import feed
    box = FIELD_BOX
    shown = cv2.imread(str(BOX.parent / "feed-typed-100.jpg"))
    assert feed.glyphs(shown, box) == "100"
    # 23:08: "10" with the mouse's I-beam over the field -- one shape more, so a
    # read that can only fail toward Cancel
    beam = cv2.imread(str(BOX.parent / "feed-typed-10-ibeam.jpg"))
    assert feed.glyphs(beam, box) != "10" and len(feed.glyphs(beam, box)) == 3


def test_the_feed_box_question_names_an_ies_plural():
    # MEASURED 2026-10-06 16:36: "blueberry" is not a substring of "blueberries"
    from hivemind.act.feed import asks_about
    q = "how many blueberries will you feed to diamond bee"
    assert asks_about(q, "blueberries") and asks_about(q, "Blueberry")
    assert asks_about("how many strawberries will you feed to rad bee", "strawberries")
    assert asks_about("how many treats will you feed to basic bee", "treats")
    assert asks_about("how many sunflower seeds will you feed to the bee", "sunflower seeds")
    assert not asks_about(q, "strawberries")
    assert not asks_about(q, "treats")
    assert not asks_about("", "treats")


def test_a_drop_that_opened_no_box_rests_twenty_minutes_three_times_then_three_hours():
    # MEASURED 2026-10-06 17:25: the third Strawberry drop opened no box
    from hivemind.act.feed import rest_after
    soon, long = 1200, 10800
    drop = "the drop opened no box with a Feed button"
    assert rest_after({"reason": drop, "soon_fails": 1}, soon, long, 3) == soon
    assert rest_after({"reason": drop, "soon_fails": 3}, soon, long, 3) == soon
    assert rest_after({"reason": drop, "soon_fails": 4}, soon, long, 3) == long
    # a record written before the count existed: soon
    assert rest_after({"reason": drop}, soon, long, 3) == soon
    assert rest_after({"reason": "the click on Feed was held back", "soon_fails": 1}, soon, long, 3) == soon
    # what fails the same way again keeps the long rest
    assert rest_after({"reason": "the box asks 'x', not about treats", "soon_fails": 0}, soon, long, 3) == long
    assert rest_after({"reason": "the field read '160' after 100 was typed"}, soon, long, 3) == long
    assert rest_after({}, soon, long, 3) == long
