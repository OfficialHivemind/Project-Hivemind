"""Counting the consumables a player decides about from the inventory's pages
(act/inventory.count_pages `extras`), and the count/cap lines (vision/inventory)."""
from pathlib import Path

import pytest

from hivemind.act import inventory as act_inv
from hivemind.vision import inventory as inv

SAVED = Path(Path.home() / "Hivemind/var/inventory/20261001-192542")


def test_a_count_over_a_cap_is_read():
    text = "Coconut: 7/500\nMicro-Converter: 15/15\nWhirligig: 8/100\nStinger: 70"
    labels = {"coconut": "Coconut", "micro_converter": "Micro-Converter",
              "whirligig": "Whirligig", "stinger": "Stinger"}
    assert inv.counts_in(text, labels) == {"coconut": 7, "micro_converter": 15,
                                          "whirligig": 8, "stinger": 70}
    assert inv.caps_in(text, labels) == {"coconut": 500, "micro_converter": 15,
                                         "whirligig": 100}


def test_two_pages_agreeing_count_an_extra_without_a_question():
    asked = []
    pages = [(None, "Whirligig: 8/100\nField Dice: 3"), (None, "Whirligig: 8\nField Dice: 3")]
    result = act_inv.InventoryRead()
    act_inv.count_pages(pages, {}, {"whirligig": "Whirligig", "field_dice": "Field Dice"},
                        lambda image, q: asked.append(q) or "none", lambda t: None, result)
    assert result.counts == {"whirligig": 8, "field_dice": 3}
    assert result.caps == {"whirligig": 100}
    assert asked == []


def test_one_page_is_asked_once_and_counted_when_the_answer_agrees():
    pages = [(None, "Micro-Converter: 15/15")]
    result = act_inv.InventoryRead()
    act_inv.count_pages(pages, {}, {"micro_converter": "Micro-Converter"},
                        lambda image, q: "15", lambda t: None, result)
    assert result.counts == {"micro_converter": 15}
    result = act_inv.InventoryRead()
    act_inv.count_pages(pages, {}, {"micro_converter": "Micro-Converter"},
                        lambda image, q: "13", lambda t: None, result)
    assert "micro_converter" not in result.counts and "micro_converter" in result.unsure


@pytest.mark.skipif(not SAVED.exists(), reason="no saved read here")
def test_the_saved_2026_10_01_read_counts_the_jelly_and_the_time_savers():
    pages = [(None, (SAVED / f"page-0{i}.txt").read_text()) for i in range(6)]
    extras = {"royal_jelly": "Royal Jelly", "blueberry": "Blueberry",
              "whirligig": "Whirligig", "jelly_beans": "Jelly Beans",
              "micro_converter": "Micro-Converter"}
    truth = {"Royal Jelly": "33", "Blueberry": "3816", "Whirligig": "8",
             "Jelly Beans": "18", "Micro-Converter": "15"}

    def ask(image, question):          # the model, answering what the page shows
        return next((v for k, v in truth.items() if f"called {k} " in question), "none")

    result = act_inv.InventoryRead()
    act_inv.count_pages(pages, {}, extras, ask, lambda t: None, result)
    assert result.counts["royal_jelly"] == 33
    assert result.counts["blueberry"] == 3816
    assert result.counts["whirligig"] == 8
    assert result.counts["jelly_beans"] == 18
    assert result.counts["micro_converter"] == 15
    assert result.caps["whirligig"] == 100 and result.caps["micro_converter"] == 15


def test_a_count_that_moved_by_one_while_read_is_counted_not_unknown():
    # MEASURED 2026-10-06 22:17: "Treat: x30019" then "Treat: 30020" (a treat came
    # in between pages) left 30,019 Treats unknown and the quest's feed unfed
    pages = [(None, "Treat: 30019"), (None, "Treat: 30020")]
    answers = iter(["30019", "30020"])
    result = act_inv.InventoryRead()
    act_inv.count_pages(pages, {"treats": "Treat"}, {}, lambda image, q: next(answers),
                        lambda t: None, result)
    assert result.counts == {"treats": 30019} and "treats" not in result.unsure


def test_counts_far_apart_stay_unsure():
    pages = [(None, "Treat: 30019"), (None, "Treat: 3002")]
    answers = iter(["30019", "3002"])
    result = act_inv.InventoryRead()
    act_inv.count_pages(pages, {"treats": "Treat"}, {}, lambda image, q: next(answers),
                        lambda t: None, result)
    assert "treats" not in result.counts and "treats" in result.unsure


def test_an_extra_that_moved_by_one_is_counted():
    pages = [(None, "Gumdrops: 203"), (None, "Gumdrops: 204")]
    result = act_inv.InventoryRead()
    act_inv.count_pages(pages, {}, {"gumdrops": "Gumdrops"}, lambda image, q: "none",
                        lambda t: None, result)
    assert result.counts == {"gumdrops": 203}
