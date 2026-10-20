"""A bee's card read (act/beecard): measured on the Festive Bee's card."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "tests/fixtures/hive/new-type-card.jpg"


def labels():
    types = yaml.safe_load((ROOT / "data/knowledge/bee_types.yaml").read_text())["types"]
    return {slug: body["label"] for slug, body in types.items()}


def test_the_festive_card_reads_as_the_festive_bee_red_event():
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is not installed")
    from hivemind.act import beecard, shoplook
    from hivemind.vision import hivecell
    frame = cv2.imread(str(CARD))
    card = beecard.read_card(frame, hivecell.new_type_card_close(frame), shoplook._ocr_line)
    assert "hatched" in card["bar"].lower()
    assert beecard.bee_of(card["name"], labels()) == "festive"
    assert beecard.rarity_of(card["rarity"]) == ("red", "event")
    assert not beecard.gifted(card)


def test_a_name_one_letter_from_two_types_is_no_name():
    from hivemind.act import beecard
    names = labels()
    assert beecard.bee_of("FestiveBeel!", names) == "festive"
    assert beecard.bee_of("DemonBee!!!", names) == "demon"
    assert beecard.bee_of("DemoBee!!", names) == "demo"
    assert beecard.bee_of("DemaBee!!", names) == "demo"       # one from Demo, two from Demon
    assert beecard.bee_of("DemnBee!!", names) is None         # one from Demo AND from Demon
    assert beecard.bee_of("Festive!!!", names) is None        # no "bee": not a name line
    assert beecard.bee_of("XyzzyBee!", names) is None
    assert beecard.rarity_of("Blue Legendary") == ("blue", "legendary")
    assert beecard.gifted({"name": "Gifted Rad Bee!"})


def test_the_click_cards_name_is_found_as_whole_words():
    # MEASURED 2026-10-04: a click on the Demon's face read like this
    from hivemind.act import beecard
    names = labels()
    text = "am ,m Demon Bee (Lvl 8) . : M p Bond:| 2ssmslereeeo H Energy | rg ] Speed: EE"
    assert beecard.names_in(text, names) == ["demon"]          # not "demo" as well
    assert beecard.names_in("Demo Bee (Lvl 9)", names) == ["demo"]
    assert beecard.names_in("Bond: 120 Energy", names) == []


ROLL = Path(__file__).resolve().parents[1] / "fixtures/hive/jelly-roll-commander.jpg"


def test_a_rarity_read_one_letter_off_still_counts():
    # MEASURED 2026-10-05 22:55: the roll card's "Epic" read "' Epie |"
    from hivemind.act.beecard import rarity_of
    assert rarity_of("' Epie |") == (None, "epic")
    assert rarity_of("Mythie") == (None, "mythic")           # must still stop a roll
    assert rarity_of("Red Legendarv") == ("red", "legendary")
    assert rarity_of("nothing") == (None, None)


def test_the_roll_card_names_the_bee_and_offers_use_another():
    import shutil
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is not installed")
    import cv2
    from hivemind.act import beecard, shoplook
    from hivemind.vision import hivecell
    frame = cv2.imread(str(ROLL))
    at = hivecell.new_type_card_close(frame)
    assert at == (827, 292)
    card = beecard.read_card(frame, at, shoplook._ocr_line)
    assert beecard.bee_of(card["name"], {"commander": "Commander Bee", "demo": "Demo Bee"}) == "commander"
    assert beecard.use_another_at(frame, at, shoplook._ocr_line) == (964, 682)
    assert beecard.use_another_at(frame, (at[0], at[1] + 200), shoplook._ocr_line) is None


def test_a_roll_card_with_its_name_unread_names_what_the_bee_became():
    # MEASURED 2026-10-07 10:22 (var/jelly.json): the name line read 'ETe Bee!',
    # and the bar's "Your Honey Bee transformed into a..." was taken as the
    # result -- the card's own words said Rad Bee ("Beel": its "!" read as "l")
    from hivemind.act import beecard
    card = {"name": "ETe Bee!", "bar": "Your Honey Bee transformed into a...",
            "whole": "ASRA S sR - I Rad Beel | Red Rare A stylish bee with a taste "
                     "[E for red flowers. Everyone [ wants to be this bee. i"}
    names = {"honey": "Honey Bee", "rad": "Rad Bee", "cool": "Cool Bee"}
    assert beecard.bee_of(card["name"], names) is None
    assert beecard.rolled_into(card, names) == ["rad"]
    # a card whose OCR kept the bar names only what the bee became
    card["whole"] = "Your Cool Bee transformed into a... Honey Beel! Epic A satisfied bee"
    assert beecard.rolled_into(card, names) == ["honey"]


def test_a_bees_info_card_left_up_over_the_world_has_the_same_red_x():
    # MEASURED 2026-10-07 21:04 (run-735): a Bubble Bee's card up mid-screen
    # while it gathered, its Energy bar taken for a mob's health bar; the live
    # view's frame, boxes and all (run_farm STRAY_CARD_EVERY_S)
    import cv2

    from hivemind.vision import hivecell
    frame = cv2.imread(str(ROOT / "tests/fixtures/hive/bee-info-card.jpg"))
    x, y = hivecell.new_type_card_close(frame)
    assert abs(x - 827) <= 3 and abs(y - 296) <= 3
