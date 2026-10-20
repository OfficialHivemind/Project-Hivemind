"""A quest-list read that stopped short of the list's end cannot take a
finished quest out of the hand-in queue by not listing it (brain/questneeds
carry_ready `whole`). MEASURED 2026-10-06 10:12 (run-680): the scroll stopped
after 4 pages, 7 of 10 quests were read, and "Fire Fighter" -- the Panda's,
finished since 06:58 -- was dropped."""
from __future__ import annotations

from hivemind.act.questscroll import FITS, ListPages
from hivemind.brain import questneeds

WAS = {"read_at": 100.0, "quests": [],
       "ready_since": {"panda_bear": {"quest": "Fire Fighter", "at": 100.0}}}
THIS_READ = ["Honey Bee's Honey Hunt\nCollect 6,500 Honey Tokens. 3,810/6,500"]


def _carry(whole):
    return questneeds.carry_ready(WAS, [], THIS_READ, {}, 200.0, whole=whole)


def test_a_read_short_of_the_end_keeps_what_it_did_not_list():
    out, notes = _carry(False)
    assert out["panda_bear"] == {"quest": "Fire Fighter", "at": 100.0}
    assert any("stopped short of the list's end" in n for n in notes), notes


def test_a_whole_read_still_drops_what_it_no_longer_lists():
    out, notes = _carry(True)
    assert "panda_bear" not in out
    assert any("no longer lists it" in n for n in notes), notes


def test_a_read_nobody_scrolled_is_as_before():
    out, _ = _carry(None)
    assert "panda_bear" not in out


def test_whole_means_the_end_was_reached_or_the_panel_showed_it_all():
    assert ListPages(complete=True).whole
    assert ListPages(reason=FITS).whole
    assert not ListPages(pages=[1, 2, 3, 4], reason="a page matched the one before it only 0.86").whole
    assert not ListPages(reason="no scrollbar on the list").whole
