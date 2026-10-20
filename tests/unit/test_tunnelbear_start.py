"""The Tunnel Bear's start (audit 2026-10-13 #5): its full bar is seen at the
screen's top edge, where `find` never looked, on the real frames of the 5 tries
of 2026-10-12/13 (var/tunnelbear/<stamp>/); and the fight is held after
act/tunnelbear.HOLD_DEATHS deaths, until the fight changes or the hive grows."""
from pathlib import Path

import cv2
import pytest

from hivemind.act import tunnelbear as tb
from hivemind.vision import nameplate

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "tunnelbear"
BAR = sorted(p.name for p in FIX.glob("bar-*.jpg"))
NONE = sorted(p.name for p in FIX.glob("none-*.jpg"))


@pytest.mark.parametrize("name", BAR)
def test_its_bar_at_the_top_edge_is_seen(name):
    frame = cv2.imread(str(FIX / name))
    assert nameplate.find(frame) == [] and nameplate.hurt_bars(frame) == []   # the old miss
    assert tb.bar_at_top(frame) and tb.seen(frame)


@pytest.mark.parametrize("name", NONE)
def test_no_bar_on_arrival_or_with_the_bear_over_the_character(name):
    assert not tb.seen(cv2.imread(str(FIX / name)))


def test_the_looks_dodge_back():
    assert [s["keys"] for s in tb.DODGE] == ["s"] and tb.DODGE[0]["studs"] > 0


def test_three_deaths_hold_it_until_the_hive_grows_or_the_fight_changes():
    now = 1_000_000.0
    state = {"tries": [{"at": 0, "result": "died"}] * 4}      # the old fight's: not counted
    for result in ("died", "absent", "died"):
        state = tb.record(state, result, now, bees=41)
    assert not tb.held(state, 41) and tb.deaths(state) == 2
    state = tb.record(state, "died", now, bees=41)
    assert tb.held(state, 41) and tb.held(state) and not tb.due(state, now + 30 * 86400, 41)
    assert tb.due(state, now + tb.LOST_RETRY_MAX_S + 1, 42)   # one more bee
    assert not tb.held(dict(state, held=dict(state["held"], fight="older")), 41)
    assert tb.deaths(tb.record(state, "killed", now, 41)) == 0
