"""The seek's face turn (act/planter.face_the_bar): a tap that loses the bar is
undone, on the bars measured 2026-10-13 (var/planters/seek-20261013-*)."""
from hivemind.act.planter import face_the_bar

W = 1920


def run(bar, seen):
    """face_the_bar with a camera whose looks after each tap are `seen`."""
    taps, looks = [], iter(seen)
    out = face_the_bar(bar, W, taps.append, lambda: next(looks))
    return out, taps


def test_a_tap_that_loses_the_bar_is_undone():
    # Bamboo 07:01: x 325, one tap left saw it at 530, the second lost it
    (bar, turned), taps = run(325, [530, None])
    assert (bar, turned) == (530, -1)
    assert taps == [-1, -1, 1]


def test_a_bar_found_after_the_tap_is_followed():
    # Pine Tree 05:42: x 159, one tap left saw it at 666
    (bar, turned), taps = run(159, [666])
    assert (bar, turned) == (666, -1) and taps == [-1]


def test_a_bar_near_the_middle_takes_no_tap():
    (bar, turned), taps = run(1162, [])
    assert (bar, turned) == (1162, 0) and taps == []


def test_lost_on_the_first_tap_ends_where_it_began():
    # Pine Tree 02:28: x 377, the tap left lost it
    (bar, turned), taps = run(377, [None])
    assert (bar, turned) == (377, 0) and taps == [-1, 1]
