"""The Blender makes several a visit (act/blender choose_n, set_quantity): how
many from the goal's shortfall, the held ingredients and MAX_PER_VISIT; the
"+" and the quantity box on the measured row (MEASURED 2026-10-13 22:32:21,
var/shoplook/20261013-223221-blend-make-1.jpg = fixtures/blender/qty-row.jpg)."""
from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

FIX = Path(__file__).resolve().parents[1] / "fixtures/blender"
LABELS = {"sunflower_seed": "Sunflower Seed", "royal_jelly": "Royal Jelly",
          "pineapple": "Pineapple", "oil": "Oil", "enzymes": "Enzymes"}
PLUS = (861, 650, 80, 50)                # the button finder's box on qty-row.jpg


def _item_of(words, labels):
    from hivemind.act.feed import item_of
    return item_of(words, labels)


def _need(material, label, gives, need, have):
    return NS(material=material, label=label, need=need, have=have,
              sources=[{"kind": "blender", "gives": gives}])


def _belt(enz_have=5, oil_have=7):
    enz = _need("enzymes", "Enzymes", "50 Pineapples + 10 Royal Jelly", 50, enz_have)
    oil = _need("oil", "Oil", "50 Sunflower Seeds + 10 Royal Jelly", 25, oil_have)
    return [NS(label="Honeycomb Belt", state="honey ready", missing=[enz, oil])]


def test_how_many_is_the_least_of_the_shortfall_the_ingredients_and_the_cap():
    from hivemind.act import blender
    enz = {"pineapple": 50, "royal_jelly": 10}
    lots = {"pineapple": 5000, "sunflower_seed": 5000, "royal_jelly": 1000}
    # the cap: 45 short, 100 in hand
    assert blender.choose_n(_belt(), lots, LABELS, _item_of) == ("enzymes", "Enzymes", enz, 10)
    assert blender.MAX_PER_VISIT == 10
    # the shortfall: 3 short
    assert blender.choose_n(_belt(enz_have=47), lots, LABELS, _item_of)[3] == 3
    # the ingredients: 54 jelly make 5, less 20 kept 3; 160 pineapples 3
    assert blender.choose_n(_belt(), dict(lots, royal_jelly=54), LABELS, _item_of)[3] == 5
    assert blender.choose_n(_belt(), dict(lots, royal_jelly=54), LABELS, _item_of,
                            keep={"royal_jelly": 20})[3] == 3
    assert blender.choose_n(_belt(), dict(lots, pineapple=160), LABELS, _item_of)[3] == 3
    # not one in hand: the Oil instead, and nothing when neither
    assert blender.choose_n(_belt(), dict(lots, pineapple=49), LABELS, _item_of)[:2] == ("oil", "Oil")
    assert blender.choose_n(_belt(), dict(lots, royal_jelly=9), LABELS, _item_of) is None
    # what the Blender holds uncollected is not made again: 3 short, 3 done
    assert blender.choose_n(_belt(enz_have=47), lots, LABELS, _item_of,
                            making={"enzymes": 3})[:2] == ("oil", "Oil")
    assert blender.choose_n(_belt(enz_have=40), lots, LABELS, _item_of,
                            making={"enzymes": 4})[3] == 6
    # choose keeps its shape
    assert blender.choose(_belt(), lots, LABELS, _item_of) == ("enzymes", "Enzymes", enz)


def test_the_quantity_read():
    from hivemind.act.blender import count_of
    assert [count_of(t) for t in ("1", "10", "1.", "lO", "I0", " 7 ")] == [1, 10, 1, 10, 10, 7]
    assert [count_of(t) for t in ("", None, "e", "1 0", "-")] == [None] * 5


def _tesseract():
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is not installed")


def test_the_plus_and_the_box_reading_one_on_the_measured_row():
    _tesseract()
    from hivemind.act import blender, shoplook
    row = cv2.imread(str(FIX / "qty-row.jpg"))
    found = blender.bar_buttons(row)
    confirm = next(b for w, b, c in found if w == "confirm" and c == "green")
    plus = blender.plus_button(found, confirm)
    assert plus == PLUS
    assert blender.quantity_box(plus) == (767, 650, 860, 700)
    said = shoplook._ocr_line(row, blender.quantity_box(plus), psm=7)
    assert blender.count_of(said) == 1, said
    # the "-" left of the box is teal, the "+" is not
    minus = (767 - blender.MINUS_W, 650, 767, 700)
    assert blender._green(row, minus, blender.TEAL) >= blender.MAKE_GREEN_MIN
    assert blender._green(row, (861, 650, 941, 700), blender.TEAL) < 0.1


class _Row:
    """A drawn Make page, then the measured quantity row behind a fake game:
    each "+" adds one (the first `drop` are lost), each "-" takes one off down
    to 1, and the box reads `box(count, pressed)`."""

    def __init__(self, drop=0, box=None):
        self.row = cv2.imread(str(FIX / "qty-row.jpg"))
        self.stage, self.count, self.drop, self.pressed = "page", 1, drop, False
        self.box = box or (lambda count, pressed: str(count))
        self.clicks = []

    def frame(self):
        if self.stage != "page":
            return self.row
        f = np.zeros_like(self.row)
        f[309:708, 683:1235] = (160, 80, 20)
        f[633:685, 793:1124] = (40, 190, 40)                      # Make
        return f

    def ocr(self, frame, box):
        from hivemind.act import blender
        if box == blender.MAKE_BOX:
            return "Make Enzymes" if self.stage == "page" else ""
        if box == blender.quantity_box(PLUS):
            return self.box(self.count, self.pressed)
        return ""

    def read(self, frame, box):
        return {973: "Confirm", 1106: "Cancel"}.get(box[0], "e")

    def words_of(self, frame, region):
        return [NS(text="Crafting", conf=100.0)] if self.stage == "crafting" else []

    def click(self, x, y):
        if self.stage == "page":
            what, self.stage = "make", "amount"
        else:
            what = next(name for name, (x0, x1) in (("-", (693, 767)), ("+", (861, 941)),
                                                   ("confirm", (973, 1086)),
                                                   ("cancel", (1106, 1226)))
                        if x0 <= x <= x1)
        if what == "+":
            self.pressed = True
            self.drop, self.count = self.drop - 1, self.count + (self.drop <= 0)
        elif what == "-":
            self.pressed, self.count = True, max(1, self.count - 1)
        elif what == "confirm":
            self.stage, self.confirmed = "crafting", self.count
        elif what == "cancel":
            self.stage = "cancelled"
        self.clicks.append(what)
        return True

    def make(self, n):
        from hivemind.act import blender
        return blender.make_one(self, self.frame, self.ocr, "Enzymes", self.frame(), n=n,
                                read=self.read, words_of=self.words_of, sleep=lambda s: None)


def test_four_are_set_by_the_plus_and_read_back_before_confirm():
    g = _Row()
    made, why, reads = g.make(4)
    assert made == 4 and why == "4 Enzymes crafting", (why, reads)
    assert g.clicks == ["make", "+", "+", "+", "confirm"] and g.confirmed == 4


def test_one_presses_no_plus_and_reads_nothing():
    g = _Row(box=lambda count, pressed: pytest.fail("one reads no box"))
    made, _why, _reads = g.make(1)
    assert made == 1 and g.clicks == ["make", "confirm"]


def test_a_box_that_does_not_read_one_first_makes_one_as_before(monkeypatch):
    from hivemind.act import blender
    monkeypatch.setattr(blender, "_digits", lambda *a, **k: None)   # neither read gets a number
    g = _Row(box=lambda count, pressed: "")
    made, _why, reads = g.make(10)
    assert made == 1 and g.clicks == ["make", "confirm"], reads


def test_lost_presses_go_back_to_a_box_reading_one():
    g = _Row(drop=2)
    made, _why, reads = g.make(5)
    assert made == 1 and g.confirmed == 1, reads
    assert g.clicks == ["make"] + ["+"] * 4 + ["-"] * 4 + ["confirm"]


def test_an_unverified_number_is_never_confirmed():
    g = _Row(box=lambda count, pressed: "8" if pressed else "1")
    made, why, reads = g.make(5)
    assert made == 0 and "confirm" not in g.clicks and g.clicks[-1] == "cancel", (why, reads)
    assert "Cancel pressed" in why
