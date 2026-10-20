"""act/quests._close with the quest list's own sign (`_list_gone`).

The frames are real: var/quest_reads/close-025214-* (2026-10-01 02:52, the
close that cost a rejoin) and another kept world frame for a busy scene.
"""
from __future__ import annotations

import pathlib

import pytest

from hivemind.act import quests

ROOT = pathlib.Path(__file__).resolve().parents[2]
KEPT = ROOT / "var" / "quest_reads"


def _frames():
    cv2 = pytest.importorskip("cv2")
    names = {"before": "close-025214-before.jpg", "open": "close-025214-open.jpg",
             "elsewhere": "close-004152-before.jpg"}
    out = {k: cv2.imread(str(KEPT / v)) for k, v in names.items()}
    if any(v is None for v in out.values()):
        pytest.skip("the kept close frames are not here")
    return out


class Vin:
    def __init__(self):
        self.clicks = 0

    def click(self, x, y):
        self.clicks += 1


class Result:
    menu_open = True


def _close(sequence, opened, before):
    frames = iter(sequence)
    last = [None]

    def grab():
        try:
            last[0] = next(frames)
        except StopIteration:
            pass
        return last[0]

    vin, result, notes = Vin(), Result(), []
    quests._close(vin, grab, before, result, lambda s: None, notes.append, 83, 128,
                  opened=opened, gone=quests._list_gone(opened))
    return vin, result, notes


def test_a_close_into_a_busy_world_is_believed_and_not_clicked_again():
    f = _frames()
    # the old tests read this world as nearer the menu: it is not `before`
    vin, result, notes = _close([f["elsewhere"]], f["open"], f["before"])
    assert not result.menu_open and vin.clicks == 1, notes
    assert "its own sign says it is gone" in notes[-1]


def test_a_menu_still_up_is_clicked_again_and_said_to_be_open():
    f = _frames()
    vin, result, notes = _close([f["open"]] * 6, f["open"], f["before"])
    assert result.menu_open and vin.clicks == 2, notes


def test_a_menu_on_its_way_out_gets_one_more_look_not_another_click():
    f = _frames()
    vin, result, notes = _close([f["open"], f["elsewhere"]], f["open"], f["before"])
    assert not result.menu_open and vin.clicks == 1, notes


def test_no_scrollbar_no_sign():
    f = _frames()
    assert quests._list_gone(f["before"]) is None
    assert quests._list_gone(f["open"])(f["elsewhere"]) is True
    assert quests._list_gone(f["open"])(f["open"]) is False
