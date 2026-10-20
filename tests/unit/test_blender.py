"""The Blender, driven (act/blender): recipes read off goals.yaml's sources,
the material chosen from the goals, and the window walked page by page --
on the measured window (2026-10-04 22:38) and on drawn ones."""
from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

FIX = Path(__file__).resolve().parents[1] / "fixtures/blender"
LABELS = {"sunflower_seed": "Sunflower Seed", "royal_jelly": "Royal Jelly", "pineapple": "Pineapple",
          "gumdrops": "Gumdrops", "moon_charm": "Moon Charm", "magic_bean": "Magic Bean",
          "strawberry": "Strawberry", "blueberry": "Blueberry", "oil": "Oil", "enzymes": "Enzymes"}


def _item_of(words, labels):
    from hivemind.act.feed import item_of
    return item_of(words, labels)


def test_a_recipe_is_read_off_the_goals_source():
    from hivemind.act.blender import recipe
    oil = "50 Sunflower Seeds + 10 Royal Jelly, 5 minutes -- the Blender's menu is not driven by this bot"
    assert recipe(oil, LABELS, _item_of) == {"sunflower_seed": 50, "royal_jelly": 10}
    assert recipe("25 Moon Charms + 1 Magic Bean", LABELS, _item_of) == {"moon_charm": 25, "magic_bean": 1}
    assert recipe("50 Blueberries + 10 Royal Jelly (the Blueberry Dispenser ...)", LABELS,
                  _item_of) == {"blueberry": 50, "royal_jelly": 10}
    assert recipe("5 Honeysuckle + 1 Oil", LABELS, _item_of) is None      # no Honeysuckle row
    assert recipe("", LABELS, _item_of) is None


def _row(label, state, missing):
    return NS(label=label, state=state, missing=missing)


def _need(material, label, gives, need=1, have=0):
    return NS(material=material, label=label, need=need, have=have,
              sources=[{"kind": "drop"}, {"kind": "blender", "gives": gives}])


def test_only_a_goal_the_blender_can_finish_is_blended_for():
    from hivemind.act.blender import choose
    oil = _need("oil", "Oil", "50 Sunflower Seeds + 10 Royal Jelly, 5 minutes", need=25, have=23)
    enz = _need("enzymes", "Enzymes", "50 Pineapples + 10 Royal Jelly", need=50, have=0)
    rows = [_row("Porcelain Dipper", "owned", []), _row("Hive Slot", "ready to buy", []),
            _row("Bubble Mask", "honey ready", [oil]), _row("Honeycomb Belt", "honey ready", [enz])]
    held = {"sunflower_seed": 371, "royal_jelly": 54, "pineapple": 4902}
    # 2 Oil: 100 seeds and 20 jelly, which are held
    assert choose(rows, held, LABELS, _item_of) == ("oil", "Oil", {"sunflower_seed": 50, "royal_jelly": 10})
    # the quest feeding's seeds kept back: 41 left, short of 100 -- and the
    # Honeycomb Belt behind it is not blended for instead
    assert choose(rows, held, LABELS, _item_of, keep={"sunflower_seed": 330}) is None
    # the Mask done: ONE Enzymes at a time since 2026-10-13 (the owner left
    # it to the bot): its jelly is bought for the goal and kept from the rolls
    rows[2] = _row("Bubble Mask", "ready to buy", [])
    assert choose(rows, held, LABELS, _item_of) == ("enzymes", "Enzymes", {"pineapple": 50, "royal_jelly": 10})


def test_a_goal_short_of_something_unblendable_still_gets_what_the_blender_makes():
    """Since 2026-10-13 one material at a time: the Stingers are a drop, the
    Blue Extract is made meanwhile; without its ingredients, nothing."""
    from hivemind.act.blender import choose
    sting = NS(material="stinger", label="Stingers", need=100, have=78, sources=[{"kind": "drop"}])
    ext = _need("blue_extract", "Blue Extract", "50 Blueberries + 10 Royal Jelly", need=1, have=0)
    rows = [_row("Cobalt Guard", "honey ready", [ext, sting])]
    assert choose(rows, {"blueberry": 9000, "royal_jelly": 54}, LABELS, _item_of) == (
        "blue_extract", "Blue Extract", {"blueberry": 50, "royal_jelly": 10})
    assert choose(rows, {"blueberry": 9000, "royal_jelly": 5}, LABELS, _item_of) is None


def test_the_measured_window_reads_exactly():
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is not installed")
    from hivemind.act import blender, shoplook
    window = cv2.imread(str(FIX / "window.jpg"))
    ocr = lambda f, box: shoplook._ocr_line(f, box, psm=7)  # noqa: E731
    assert blender.title_of(ocr(window, blender.TITLE_BOX)) == "red extract"
    assert blender.title_of(ocr(window, blender.MAKE_BOX)) == "make red extract"
    assert blender.panel_open(window)
    assert not blender.panel_open(cv2.imread(str(FIX / "closed.jpg")))


class _Window:
    """A drawn Blender: pages of titles, a green Make, then Confirm, then a
    red End Crafting -- each a button read by its colour."""

    def __init__(self, titles, confirm=True):
        self.titles, self.page, self.confirm = titles, 0, confirm
        self.stage, self.clicks = "page", []

    def frame(self):
        f = np.zeros((1080, 1920, 3), np.uint8)
        f[309:708, 683:1235] = (160, 80, 20)                         # the panel's blue
        if self.stage == "page":
            x0, y0, x1, y1 = (793, 633, 1124, 685)
            f[y0:y1, x0:x1] = (40, 190, 40)
        elif self.stage == "amount" and self.confirm:
            f[630:680, 980:1100] = (40, 190, 40)                     # Confirm
        elif self.stage == "crafting":
            f[630:680, 780:900] = (40, 40, 210)                      # End Crafting, red
        return f

    def ocr(self, frame, box):
        from hivemind.act import blender
        if box == blender.TITLE_BOX:
            return f"- {self.titles[self.page % len(self.titles)]} -"
        if box == blender.MAKE_BOX and self.stage == "page":
            return "Make " + self.titles[self.page % len(self.titles)]
        return ""

    def read(self, frame, box):
        x, y, w, h = box
        b, g, r = (int(v) for v in frame[y + h // 2, x + 3])
        if g > 150 > r:
            return "Confirm" if self.stage == "amount" else "Make"
        return "End Crafting" if r > 150 else ""

    def click(self, x, y):
        from hivemind.act import blender
        self.clicks.append((x, y))
        if (x, y) == blender.NEXT_ARROW:
            self.page += 1
        elif self.stage == "page" and 793 <= x <= 1124 and 633 <= y <= 685:
            self.stage = "amount"
        elif self.stage == "amount" and 980 <= x <= 1100 and 630 <= y <= 680:
            self.stage = "crafting"
        return True


def test_it_pages_to_the_recipe_and_makes_one():
    from hivemind.act import blender
    w = _Window(["Red Extract", "Blue Extract", "Oil", "Enzymes"])
    page, reads = blender.browse_to(w, w.frame, w.ocr, "Oil", sleep=lambda s: None)
    assert page is not None and reads == ["red extract", "blue extract", "oil"]
    ok, why, reads = blender.make_one(w, w.frame, w.ocr, "Oil", page, read=w.read,
                                      words_of=lambda f, r: [], sleep=lambda s: None)
    assert ok, (why, reads)
    assert w.stage == "crafting"


def test_a_recipe_that_is_not_there_comes_round_once():
    from hivemind.act import blender
    w = _Window(["Red Extract", "Blue Extract"])
    page, reads = blender.browse_to(w, w.frame, w.ocr, "Oil", sleep=lambda s: None)
    assert page is None and reads == ["red extract", "blue extract", "red extract"]


def test_no_confirm_no_craft():
    from hivemind.act import blender
    w = _Window(["Oil"], confirm=False)
    ok, why, _reads = blender.make_one(w, w.frame, w.ocr, "Oil", w.frame(), read=w.read,
                                       words_of=lambda f, r: [], sleep=lambda s: None)
    assert not ok and "Confirm" in why
    assert w.stage == "amount" and len(w.clicks) == 1        # Make only


def test_a_red_end_crafting_is_still_crafting_never_finished():
    from hivemind.act import blender
    w = _Window(["Oil"])
    w.stage = "crafting"
    f = w.frame()
    assert blender.still_crafting(f, read=w.read)
    assert blender.finished_button(f, read=w.read) is None


def test_a_material_the_last_read_missed_does_not_hold_the_blender_back():
    # MEASURED 2026-10-05 23:48: the read missed the Blueberry row
    from hivemind.act.blender import choose
    oil = _need("oil", "Oil", "50 Sunflower Seeds + 10 Royal Jelly", need=25, have=23)
    berries = NS(material="blueberry", label="Blueberry", need=500, have=None,
                 sources=[{"kind": "drop"}, {"kind": "dispenser"}])
    rows = [_row("Bubble Mask", "honey ready", [berries, oil])]
    held = {"sunflower_seed": 389, "royal_jelly": 58}
    assert choose(rows, held, LABELS, _item_of) == ("oil", "Oil", {"sunflower_seed": 50, "royal_jelly": 10})


def test_a_goal_short_only_of_unread_things_blends_nothing():
    from hivemind.act.blender import choose
    berries = NS(material="blueberry", label="Blueberry", need=500, have=None,
                 sources=[{"kind": "drop"}, {"kind": "dispenser"}])
    rows = [_row("Bubble Mask", "honey ready", [berries])]
    assert choose(rows, {"sunflower_seed": 389, "royal_jelly": 58}, LABELS, _item_of) is None


def test_the_measured_end_crafting_buttons_read_by_their_colour():
    # MEASURED 2026-10-06: a green End Crafting 246 x 85 when the Oil was done
    # (01:53, uncollected while the Feed box's size limits threw it away), a red
    # one 242 x 81 while it ran (00:13)
    from hivemind.act import blender
    done = cv2.imread(str(FIX / "finished.jpg"))
    running = cv2.imread(str(FIX / "crafting.jpg"))
    say = lambda f, box: "End Crafting"  # noqa: E731
    assert blender.finished_button(done, read=say) == (704, 608, 246, 82)
    assert not blender.still_crafting(done, read=say)
    assert blender.finished_button(running, read=say) is None
    assert blender.still_crafting(running, read=say)


def test_a_stray_letter_before_make_still_reads_the_button():
    # MEASURED 2026-10-06 13:33: "y make oil" turned a ready Oil craft away
    from hivemind.act import blender
    assert blender.reads_make("make oil", "Oil")
    assert blender.reads_make("y make oil", "Oil")
    assert blender.reads_make("y make red extract", "Red Extract")
    assert not blender.reads_make("make enzymes", "Oil")
    assert not blender.reads_make("make", "Oil")
    assert not blender.reads_make("glue make oil", "Oil")    # a word, not a stray letter
    assert not blender.reads_make("make oil", "Red Extract")
