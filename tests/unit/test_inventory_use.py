"""Using an item from the inventory (act/inventory.use_item): its row found by
its own title, read exactly, on a real page of the list (2026-10-02 22:02)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")

PAGE = Path(__file__).resolve().parents[1] / "fixtures/inventory/page-20261002-220224-01.png"


@pytest.fixture
def page():
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is not installed")
    return cv2.imread(str(PAGE))


def test_the_rows_are_ninety_pixels_apart(page):
    from hivemind.act import inventory
    assert inventory.row_tops(page)[:4] == [12, 97, 187, 277]


def test_an_item_is_found_by_its_own_title_and_counted(page):
    from hivemind.act import inventory, shoplook
    ocr = shoplook._ocr_line
    assert inventory.find_row(page, "Glitter", ocr) == 637
    assert inventory.find_row(page, "Glue", ocr) == 727
    assert inventory.find_row(page, "glitter", ocr) == 637          # case is not a name
    assert inventory.find_row(page, "Moon Charm", ocr) is None       # not on this page
    assert inventory.find_row(page, "Glit", ocr) is None             # exact, never a prefix
    # the count's box holds the outlined "x18"
    patch = inventory._count_patch(page, 637)
    assert patch is not None and patch.std() > 20


DIALOG = Path(__file__).resolve().parents[1] / "fixtures/inventory/use-glitter-dialog.png"
NO_DIALOG = Path(__file__).resolve().parents[1] / "fixtures/inventory/no-dialog-window.png"


def test_the_use_question_is_read_and_answered_on_its_own_buttons():
    # MEASURED 2026-10-03 00:26: a click on Glitter's icon opens "Use Glitter?"
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is not installed")
    from hivemind.act import inventory, shoplook
    frame = cv2.imread(str(DIALOG))
    assert inventory.dialog_open(frame)
    assert inventory.dialog_question(frame, shoplook._ocr_line) == "use glitter"
    clicks = []

    class Vin:
        def click(self, x, y):
            clicks.append((x, y))
            return True
    assert inventory.answer(Vin(), frame, yes=True) and clicks == [((779 + 944) // 2, (564 + 613) // 2)]
    assert inventory.answer(Vin(), frame, yes=False) and clicks[-1] == ((977 + 1142) // 2, (564 + 613) // 2)
    other = cv2.imread(str(NO_DIALOG))
    assert not inventory.dialog_open(other)
    assert not inventory.answer(Vin(), other, yes=True) and len(clicks) == 2   # no green there


def test_every_count_on_the_measured_page_reads_right(page):
    # the largest of four readings: a reading only ever loses a digit (x1 -> x)
    from hivemind.act import inventory
    tops = inventory.row_tops(page)[:9]
    assert [inventory.row_count(page, t) for t in tops] == [1, 1, 4, 1, 21, 6, 54, 18, 9]


class _DragVin:
    """Records drags and clicks; a drag asks its check like platform/input."""

    def __init__(self):
        self.drags, self.clicks = [], []

    def drag(self, x0, y0, x1, y1, check=None):
        self.drags.append((x0, y0, x1, y1))
        return bool(check()) if check is not None else True

    def click(self, x, y):
        self.clicks.append((x, y))
        return True


def _hatch(monkeypatch, page, after, lit, accept):
    from hivemind.act import inventory, shoplook
    monkeypatch.setattr(inventory, "_read_menu",
                        lambda *a, on_page=None, **k: on_page(page))
    monkeypatch.setattr(inventory, "_crop_of", lambda frames, note: page)
    vin = _DragVin()
    # "Glitter" stands in for the egg: a row on the measured page
    out = inventory.hatch_egg(vin, lambda: after, "Glitter", (1200, 300), lit=lit,
                              accept=accept, ocr=shoplook._ocr_line, sleep=lambda s: None)
    return out, vin


def test_an_egg_is_never_let_go_where_the_cell_did_not_light(monkeypatch, page):
    out, vin = _hatch(monkeypatch, page, cv2.imread(str(NO_DIALOG)),
                      lit=lambda f: False, accept=lambda q: True)
    assert len(vin.drags) == 1 and vin.drags[0][2:] == (1200.0, 300.0)
    assert not out.dropped and not out.ok and "carried back" in out.reason
    assert vin.clicks == []


def test_a_question_it_was_not_told_to_accept_is_answered_no(monkeypatch, page):
    out, vin = _hatch(monkeypatch, page, cv2.imread(str(DIALOG)),
                      lit=lambda f: True, accept=lambda q: False)
    assert out.dropped and not out.ok and out.question == "use glitter"
    assert vin.clicks == [((977 + 1142) // 2, (564 + 613) // 2)]      # No, only


def test_the_egg_preview_never_lets_go_over_the_hive(monkeypatch, page):
    from hivemind.act import inventory, shoplook
    monkeypatch.setattr(inventory, "_read_menu",
                        lambda *a, on_page=None, **k: on_page(page))
    seen = []

    class Vin:
        def drag_seek(self, x0, y0, px, py, find, check=None):
            seen.append((x0, y0, px, py))
            return find()                      # what the real one lets go at
    out = inventory.preview_egg(Vin(), lambda: "frame", "Glitter", (1100, 300),
                                ocr=shoplook._ocr_line, sleep=lambda s: None)
    assert out.ok and not out.dropped and out.held == "frame"
    assert seen and seen[0][2:] == (1100.0, 300.0)


def test_a_title_one_letter_off_is_found_only_when_it_is_alone():
    # MEASURED 2026-10-03 06:39: the Magic Bean's row read "madic bean"
    from hivemind.act import inventory
    tops = [12, 97, 187]
    titles = {12 + inventory.ROW_TITLE[1]: "jelly beans", 97 + inventory.ROW_TITLE[1]: "madic bean",
              187 + inventory.ROW_TITLE[1]: "ant pass"}

    def ocr(page, box):
        return titles.get(box[1], "")
    import numpy as np
    page = np.zeros((400, 306, 3), np.uint8)
    import hivemind.act.inventory as mod
    orig = mod.row_tops
    try:
        mod.row_tops = lambda p: tops
        assert inventory.find_row(page, "Magic Bean", ocr) == 97
        titles[187 + inventory.ROW_TITLE[1]] = "magic beam"       # a second near one: neither
        assert inventory.find_row(page, "Magic Bean", ocr) is None
        assert inventory.find_row(page, "Glue", ocr) is None       # short names stay exact
    finally:
        mod.row_tops = orig


def _moving_world(page, opens: bool):
    """Full frames of a world that changes wholesale every look (the field
    under a running pattern); a click puts the measured list in its box."""
    import numpy as np
    rng = np.random.default_rng(1)
    state = {"open": False}

    def frames():
        f = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        if state["open"]:
            f[158:158 + 922, 0:306] = page
        return f

    class Vin:
        def click(self, x, y):
            if opens:
                state["open"] = not state["open"]
            return True

        def move_mouse(self, x, y):
            return True

        def scroll(self, *a, **k):
            return True
    return frames, Vin()


def test_a_moving_world_does_not_hide_the_open_list(page, tmp_path):
    # MEASURED 2026-10-03 07:22 and 10:43: Glue in a field while the pattern
    # ran, the world moving 98.9% and 77.2% by itself -- no list can beat that
    # by the margin, but Natro's marker on its edge is the list (rule 7)
    import time as _time
    from hivemind.act import inventory, shoplook

    def ask(image, question=None):      # as hatch_egg / use_item ask: the rows' titles
        return "\n".join(inventory._title(image, top, shoplook._ocr_line) + ": 1"
                         for top in inventory.row_tops(image))
    for opens in (True, False):
        frames, vin = _moving_world(page, opens)
        seen, result = [], inventory.InventoryRead()
        inventory._read_menu(vin, frames, ask, {}, lambda s: None,
                             lambda t: None, result, tmp_path, _time.time, None,
                             inventory.INVENTORY, lambda *a: None,
                             on_page=lambda p: seen.append(p) or True)
        if opens:
            assert seen and "nothing opened" not in result.reason, result.reason
        else:
            assert not seen and "marker did not show" in result.reason, result.reason
