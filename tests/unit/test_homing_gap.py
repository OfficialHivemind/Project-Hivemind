"""The sight homing's gap back-out (act/homing GAP_BACK_OUT): a dark look right
after a step at the hive undoes the step and runs the row search, as attempt
948 05:50 needed (307,489 px, then 0); and the give-up line's "most was" is the
whole homing's best, not the last circle's."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np

from hivemind.act import homing


class _Keys:
    def __init__(self):
        self.walked, self.taps = [], []

    @contextmanager
    def held(self, *keys):
        self.walked.append("".join(keys))
        yield

    def tap(self, key):
        self.taps.append(key)


def _run(monkeypatch, readings, switch):
    """Home through `readings` ((bearing, yellow) per look) with GAP_BACK_OUT=`switch`."""
    looks = iter(readings + [(0, 0)] * 40)
    monkeypatch.setattr(homing, "hive_bearing", lambda frame: next(looks))
    monkeypatch.setattr(homing, "GAP_BACK_OUT", switch)
    keys, searches = _Keys(), []

    def row_search():
        searches.append(True)
        return SimpleNamespace(ok=True, describe=lambda: "landed")

    found = homing.home_by_sight(keys, lambda: np.zeros((4, 4, 3), np.uint8),
                                 lambda frame: "", sleep=lambda s: None,
                                 row_search=row_search)
    return found, keys, searches


def test_948_a_step_at_the_hive_then_a_dark_look_backs_out_and_searches_the_row(monkeypatch):
    # look 6: bracketed at -602 px, walked left-forward at 307,489; look 7: 0
    found, keys, searches = _run(monkeypatch, [(-602, 105_808), (-602, 307_489), (0, 0)], "on")
    assert keys.walked == ["wa", "sd"]           # the step, then the same step undone
    assert searches == [True] and found.ok


def test_off_scans_as_before_and_says_the_best_of_the_whole_homing(monkeypatch):
    found, keys, searches = _run(monkeypatch, [(0, 307_489), (0, 7_760)], "off")
    assert not searches and not found.ok and keys.taps[:8] == ["period"] * 8
    assert "most was 307,489 px over all" in found.reason
    assert "7,760 in this last circle" in found.reason
    assert "in view earlier and was lost" in found.reason


def test_not_after_a_flat_wall_step_nor_a_tap(monkeypatch):
    found, _, searches = _run(monkeypatch, [(0, 807_648), (0, 0)], "on")    # attempt 875
    assert not searches and not found.ok
    found, _, searches = _run(monkeypatch, [(700, 300_000), (0, 0)], "on")  # a tap lost it
    assert not searches


def test_ab_is_hour_pairs_so_each_arm_has_even_and_odd_hours(monkeypatch):
    monkeypatch.setattr(homing, "GAP_BACK_OUT", "ab")
    on = [h for h in range(24) if homing.gap_back_out_on(h)]
    assert on == [0, 1, 4, 5, 8, 9, 12, 13, 16, 17, 20, 21]
