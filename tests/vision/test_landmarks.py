"""Panel text becomes a place, and only recorded text does. See vision/landmarks."""
from __future__ import annotations

import pathlib

import pytest

from hivemind.vision import landmarks as lm

ROOT = pathlib.Path(__file__).resolve().parents[2]

TABLE = {
    "hive": {"kind": "hive", "router_node": "hive", "prompts": [
        {"text": "make honey", "mine": True},
        {"text": "claim hive", "mine": False},
        {"text": "claim this hive", "mine": False}]},
    "red_cannon": {"kind": "transport", "router_node": "red_cannon",
                   "prompts": [{"text": "fire the red cannon"}]},
    "ticket_shop": {"kind": "shop", "router_node": None, "near": "red_cannon",
                    "prompts": ["open shop"]},
}
NOT = ["you've made", "you have made"]


@pytest.fixture
def table():
    return lm.Table(TABLE, NOT)


def test_normalise_strips_case_punctuation_and_spacing():
    assert lm.normalise("  Fire the  Red Cannon! ") == "fire the red cannon"
    assert lm.normalise("You’ve made") == "you've made"
    assert lm.normalise(None) == ""


def test_each_recorded_prompt_is_found(table):
    assert table.match("Make Honey").place == "hive"
    assert table.match("Fire the Red Cannon").place == "red_cannon"
    assert table.match("Open Shop").place == "ticket_shop"


def test_the_model_s_capitalisation_does_not_matter(table):
    assert table.match("MAKE HONEY").place == "hive"
    assert table.match("claim HIVE").place == "hive"


def test_our_pad_and_a_free_pad_are_told_apart(table):
    assert table.match("Make Honey").mine is True
    assert table.match("Claim Hive").mine is False


def test_the_longer_phrase_wins(table):
    assert table.match("Claim This Hive").prompt == "claim this hive"


def test_a_notification_is_not_a_place(table):
    """"You've made 73,013,670 Honey" shares the panel and means an event."""
    assert table.match("You've made 73,013,670 Honey") is None
    assert table.match("You have made 5 Honey") is None


def test_free_text_is_never_a_landmark(table):
    """The model has been measured inventing "claim hive" on an empty crop;
    the only defence is refusing anything but the recorded words."""
    assert table.match("a beautiful garden with flowers") is None
    assert table.match("the player is at the hive") is None


def test_empty_and_none_are_not_matches(table):
    assert table.match("") is None
    assert table.match(None) is None
    assert table.is_prompt("") is False


def test_recognising_is_not_reaching(table):
    assert table.match("Fire the Red Cannon").reachable is True
    shop = table.match("Open Shop")
    assert shop.reachable is False and shop.near == "red_cannon"


def test_describe_reads_as_a_sentence(table):
    assert "our own hive pad" in table.match("Make Honey").describe()
    assert "free hive pad" in table.match("Claim Hive").describe()
    assert "red cannon" in table.match("Fire the Red Cannon").describe()


def test_places_are_listed_once_each(table):
    assert table.places() == ["hive", "red_cannon", "ticket_shop"]


def test_the_real_table_loads_and_knows_the_hive():
    real = lm.load(ROOT / "data/knowledge/landmarks.yaml")
    assert len(real) >= 5
    assert real.match("Make Honey").place == "hive"
    assert real.match("Talk to Black Bear").place == "black_bear"


def test_a_missing_file_is_an_empty_table_not_an_error(tmp_path):
    assert len(lm.load(tmp_path / "nope.yaml")) == 0


def test_a_broken_file_is_an_empty_table_not_an_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("landmarks: [unclosed")
    assert len(lm.load(bad)) == 0
