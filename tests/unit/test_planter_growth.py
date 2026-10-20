"""A planter grows only while the game is played: the measured Paper in Stump,
2026-10-12/13, replayed (act/planter game_closed/game_opened, still_growing,
bar_growth, regrown)."""
from hivemind.act import planter as P

HOUR = 3600.0
PLACED = 22 * HOUR + 23 * 60 + 42          # 22:23:42, the Paper into Stump
CLOSED = 22 * HOUR + 37 * 60               # 22:37:00, run-921 shut the game
JOINED = 23 * HOUR + 18 * 60 + 45          # 23:18:45, run-936's fresh join


def _paper():
    return P.placed({}, "paper_planter", "stump", PLACED)


def _growth(state, now):
    body = state["out"]["paper_planter"]
    return (now - body["at"]) / P.planter_grow_s(state, "paper_planter")


def test_the_paper_is_still_one_hour():
    assert P.grow_s("paper_planter", "stump") == HOUR


def test_a_shut_game_moves_the_planter_on_and_matches_its_bar():
    st = P.game_opened(P.game_closed(_paper(), CLOSED), JOINED)
    assert "closed_at" not in st
    # its bar read 51.3% at 23:35:57 and 88.2% at 23:58:07
    assert abs(_growth(st, 23 * HOUR + 35 * 60 + 57) - 0.513) < 0.01
    assert abs(_growth(st, 23 * HOUR + 58 * 60 + 7) - 0.882) < 0.01
    # not due at the wall-clock hour any more: due at 00:05:27
    due, early = P.due_at(st, "paper_planter", {})
    assert not early and abs(due - (PLACED + HOUR + (JOINED - CLOSED))) < 1e-6
    _step = P.next_step(st, "stump", (), PLACED + HOUR + 60)
    assert _step is None


def test_no_close_mark_or_an_old_one_moves_nothing():
    st = _paper()
    assert P.game_opened(st, JOINED)["out"] == st["out"]
    late = P.game_closed(st, JOINED + 10)            # closed after this join
    assert P.game_opened(late, JOINED)["out"] == st["out"]


def test_still_growing_prompt():
    assert P.still_growing("E Harvest the Paper Planter (lt's still. growing)")
    assert P.still_growing("E | Harvest the Paper | Planter (It's still growing)")
    assert not P.still_growing("E Harvest the Ticket Planter")
    assert not P.still_growing("")


def test_bar_growth():
    assert P.bar_growth("Paper Planter (51.3%)", "Paper Planter") == 0.513
    assert P.bar_growth("Blue Clay Planter (0.0%)", "Blue Clay Planter") == 0.0
    assert P.bar_growth("Ticket Planter (100.0%)", "Ticket Planter") == 1.0
    assert P.bar_growth("Paper Planter (51.3%)", "Ticket Planter") is None
    assert P.bar_growth("Paper Planter", "Paper Planter") is None
    assert P.bar_growth("", "Paper Planter") is None


def test_regrown_books_it_by_its_bar_and_is_no_miss():
    now = 23 * HOUR + 35 * 60 + 57
    st = P.missed(_paper(), "paper_planter", now - 60)
    st = P.regrown(st, "paper_planter", now, 0.513)
    assert st["out"]["paper_planter"]["misses"] == 0
    due, _ = P.due_at(st, "paper_planter", {})
    assert abs(due - (now + 0.487 * HOUR)) < 1e-6
    # no bar read: looked at again after GROWING_RETRY of its grow time
    st = P.regrown(_paper(), "paper_planter", now, None)
    due, _ = P.due_at(st, "paper_planter", {})
    assert abs(due - (now + P.GROWING_RETRY * HOUR)) < 1e-6
    # a planter not out: nothing changes
    assert P.regrown({}, "paper_planter", now, 0.5) == {}
