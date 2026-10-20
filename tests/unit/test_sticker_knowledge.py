"""K10: Sticker Stack buff/badge and the Sticker Printer's Basic Egg odds."""
from hivemind.brain import stickers, value


def test_printer_odds_sum_to_one_print():
    t = stickers.load()
    assert abs(sum(p * len(n) for p, n in t["printer"]["basic"]) - 100) < 0.01


def test_printer_ticket_value_and_value_reads_it():
    t = stickers.load()
    assert round(stickers.printer_tickets(t), 2) == 1.93
    # a stacked type pays nothing: Simple Sun was 11.1486% x 5 tickets
    assert round(stickers.printer_tickets(t, ["Simple Sun"]), 4) == round(1.929796 - 0.55743, 4)
    assert value.PAYS["sticker_printer"](30)["ticket"] == stickers.printer_tickets(t)


def test_reward_tickets():
    t = stickers.load()
    assert stickers.reward_tickets("Pink Chair", t) == 10
    assert stickers.reward_tickets("Yellow Coffee Mug", t) == 0     # 1 Oil
    assert stickers.reward_tickets("No Such Sticker", t) == 0


def test_buff_and_badge():
    t = stickers.load()
    assert stickers.buff_seconds(0, t) == 900
    assert stickers.buff_seconds(47, t) == 1370
    assert stickers.buff_seconds(500, t) == 3600
    assert stickers.badge_pollen(24, t) == 0
    assert stickers.badge_pollen(25, t) == 5
    assert stickers.badge_pollen(260, t) == 20
