"""The 25-ticket boost when no sticker type is left (owner 2026-10-17: "sticker stack no work")."""
import shutil
from pathlib import Path

import cv2
import pytest
import hivemind
from hivemind.act import stickerstack

ROOT = Path(hivemind.__file__).resolve().parents[2]
MENU = ROOT / "tests/fixtures/stickerstack/menu_no_types.jpg"


def ocr_of(texts):
    return lambda frame, box: texts.get(box, "")


def test_boost_timer_is_read():
    o = ocr_of({stickerstack.BOOST_LINE: "Stack Boost (x47) (22:50)"})
    assert stickerstack.boost_left_s(None, o) == 22 * 60 + 50
    assert stickerstack.boost_left_s(None, ocr_of({})) is None


def test_no_types_is_seen():
    o = ocr_of({stickerstack.GRID_BOX: "(You have no types of Stickers that can be added to the Stack)"})
    assert stickerstack.no_stickers(None, o)
    assert not stickerstack.no_stickers(None, ocr_of({stickerstack.GRID_BOX: ""}))


def test_the_real_menu_shows_the_yellow_ticket_button():
    f = cv2.imread(str(MENU))
    assert f is not None and stickerstack._yellow(f, stickerstack.TICKET_BUTTON) >= 0.4


def test_no_tickets_while_the_boost_has_time_left():
    f = cv2.imread(str(MENU))
    clicks = []

    class Vin:
        def click(self, x, y):
            clicks.append((x, y))
    o = ocr_of({stickerstack.MENU_HEADER: "Choose a Sticker to Donate:",
                stickerstack.GRID_BOX: "You have no types of Stickers that can be added",
                stickerstack.BOOST_LINE: "Stack Boost (x47) (22:50)"})
    got = stickerstack.ticket_boost(Vin(), lambda: f, o, sleep=lambda s: None)
    assert not got.ok and clicks == [] and "22:50" in got.reason


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="reads through tesseract; none on PATH")
def test_the_question_is_read_line_by_line_even_when_the_name_wraps():
    """19 Oct: read whole, the 3-4 line box was gibberish and every sticker got No."""
    from hivemind.act import shoplook
    from hivemind.brain import stickers
    t = stickers.load()
    for name, want in (("asked_wrapped.jpg", "Purple Pointed Critter"),
                       ("asked_pink_chair.jpg", "Pink Chair")):
        f = cv2.imread(str(ROOT / "tests/fixtures/stickerstack" / name))
        q = stickerstack.question_text(f, shoplook._ocr_line)
        assert stickerstack.sticker_named(q, t) == want, q


def test_one_misread_letter_still_names_the_sticker():
    from hivemind.brain import stickers
    t = stickers.load()
    assert stickerstack.sticker_named('Add "Standina Caterpillar Sticker" to the Stack?', t) == "Standing Caterpillar"
    assert stickerstack.sticker_named('Add "Qwxyz Plorb Sticker" to the Stack?', t) is None
