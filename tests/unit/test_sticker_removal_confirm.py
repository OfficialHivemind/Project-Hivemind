"""The second question after a donation (2026-10-20 07:39, run-1103)."""
from hivemind.act import stickerstack


TABLE = {"stickers": {"Blowing Leaf": {"rarity": 1}, "Cyan Decorative Border": {"rarity": 1}}}


class Vin:
    def __init__(self):
        self.answers = []


def run(question, monkeypatch, name="Blowing Leaf"):
    vin = Vin()
    monkeypatch.setattr(stickerstack.inventory, "dialog_open", lambda f: True)
    monkeypatch.setattr(stickerstack.inventory, "dialog_question", lambda f, o: question)
    monkeypatch.setattr(stickerstack, "question_text", lambda f, o: question)
    monkeypatch.setattr(stickerstack.inventory, "answer",
                        lambda v, f, yes: v.answers.append(yes) or True)
    out = stickerstack.Donated()
    out.name = name
    t = iter(range(100))
    stickerstack._confirm_removal(vin, lambda: "frame", None, TABLE, name, out,
                                  lambda f, tag: None, lambda s: None, lambda: next(t) * 0.1)
    return vin, out


def test_the_removal_question_for_the_same_sticker_gets_yes(monkeypatch):
    vin, out = run("The Blowing Leaf Sticker will be permanently removed from your "
                   "inventory. Continue?", monkeypatch)
    assert vin.answers == [True] and out.name == "Blowing Leaf"


def test_any_other_second_box_gets_no(monkeypatch):
    vin, out = run("The Cyan Decorative Border Sticker will be permanently removed from "
                   "your inventory. Continue?", monkeypatch)
    assert vin.answers == [False] and out.name is None
    vin, out = run("Buy a Royal Jelly for 250,000 honey?", monkeypatch)
    assert vin.answers == [False] and out.name is None
