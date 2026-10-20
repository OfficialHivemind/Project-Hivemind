"""act/stickerstack: Yes only to a question naming a sticker the stack may take."""
from hivemind.act import stickerstack as ss

TABLE = {"keep_from": 4, "stickers": {
    "Young Elf": {"rarity": 1}, "Diamond Egg": {"rarity": 6}, "Elf": {"rarity": 2}}}


def test_the_longest_named_sticker_is_the_one_asked_about():
    assert ss.sticker_named("Donate Young Elf to the Sticker Stack?", TABLE) == "Young Elf"
    assert ss.sticker_named("add a sticker?", TABLE) is None


class FakeInput:
    def __init__(self):
        self.clicks = []

    def click(self, x, y):
        self.clicks.append((x, y))


def run(questions, stacked=()):
    """Every icon opens the next question; returns (result, clicks)."""
    import numpy as np
    from hivemind.act import inventory
    state = {"open": False, "n": 0}
    vin = FakeInput()
    orig = (inventory.dialog_open, inventory.dialog_question, inventory.answer, ss.menu_open)
    inventory.dialog_open = lambda f: state["open"]
    inventory.dialog_question = lambda f, ocr: questions[state["n"] - 1]

    def answer(v, f, yes):
        state["open"] = False
        v.clicks.append(("yes" if yes else "no",))
    inventory.answer = answer
    ss.menu_open = lambda f, ocr: True
    real_click = vin.click

    def click(x, y):
        real_click(x, y)
        state["n"] += 1
        state["open"] = state["n"] <= len(questions)
    vin.click = click
    try:
        got = ss.donate_one(vin, lambda: np.zeros((1080, 1920, 3), np.uint8), None, TABLE,
                            list(stacked), sleep=lambda s: None)
    finally:
        inventory.dialog_open, inventory.dialog_question, inventory.answer, ss.menu_open = orig
    return got, vin.clicks


def test_a_rare_sticker_is_refused_and_the_next_common_one_given():
    got, clicks = run(["Donate Diamond Egg?", "Donate Young Elf?"])
    assert got.name == "Young Elf"
    assert [c for c in clicks if len(c) == 1] == [("no",), ("yes",)]


def test_one_stacked_before_is_refused():
    got, _ = run(["Donate Young Elf?"], stacked=["Young Elf"])
    assert not got.ok


def test_a_click_that_opens_no_question_ends_the_visit():
    got, clicks = run([])
    assert not got.ok and "opened no question" in got.reason
    assert len(clicks) == 1
