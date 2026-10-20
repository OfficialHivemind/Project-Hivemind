"""A borrowed route (run_farm GIVER_ROUTE_OVERRIDE) is scored on its own place.

The `said` strings are the Honey Bee hand-ins' own reasons, 2026-10-13
(var/night/run-949.log 06:07:38 landed at the stack; run-954.log 08:24:21 a
real miss, cut by a mob into the Strawberry field).
"""
from hivemind.act import errands
from hivemind.act.errands import borrowed_route_landed, borrowed_verdict_on, route_place

HUNT = ("the search did not find the Honey Bee — held toward a quest marker: no quest "
        "marker on screen, spiral forward 0.2s, forward 6.0s, left 6.0s, right 12.0s "
        "without a panel that names it")
AT_STACK = HUNT + " (walked past 'Add a Sticker to the Sticker Stack')"
REASON = ("looked 11 times and the panel never said 'Talk to Honey Bee' (last read '') "
          "— either the walk did not arrive or the honey bee is not there")


def test_route_place():
    assert route_place("natro_out_sticker_stack") == "sticker_stack"
    assert route_place("natro_out_sticker_stack_via_red_cannon") == "sticker_stack"


def test_landed_at_its_own_place():
    assert borrowed_route_landed("natro_out_sticker_stack", False, f"{AT_STACK} {REASON}")


def test_real_miss_stays_a_miss():
    assert not borrowed_route_landed("natro_out_sticker_stack", False, f"{HUNT} {REASON}")


def test_pressed_is_landed():
    assert borrowed_route_landed("natro_out_sticker_stack", True, "")


def test_ab_split_is_four_hour_blocks(monkeypatch):
    monkeypatch.setattr(errands, "BORROWED_ROUTE_VERDICT", "ab")
    on = [h for h in range(24) if borrowed_verdict_on(h)]
    assert on == [0, 1, 2, 3, 8, 9, 10, 11, 16, 17, 18, 19]
    # half of each even/odd and hour-pair group, so it confounds neither
    assert sum(h % 2 == 0 for h in on) == 6
    assert sum((h // 2) % 2 == 0 for h in on) == 6
    monkeypatch.setattr(errands, "BORROWED_ROUTE_VERDICT", "off")
    assert not borrowed_verdict_on(0)
