"""WALK-SPD and WALK-RETIME: the other speed buffs (vision/buffs SPEED_BUFFS)
and a mid-hold speed change believed only once RETIME_READS reads agree
(act/routes FactorConfirm), dated back to its first read.

The bar strips are tests/fixtures/haste and tests/fixtures/bearmorph (saved
frames' buff bars, see their own tests)."""
from __future__ import annotations

import pathlib

import cv2
import numpy as np
import pytest

from hivemind.act import routes as R
from hivemind.act.routes import FactorConfirm, RouteRunner
from hivemind.nav.router import Router
from hivemind.vision import buffs

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
STRIPS = sorted((FIX / "haste").glob("*.png")) + sorted((FIX / "bearmorph").glob("*.png"))


def frame(path):
    out = np.full((1080, 1920, 3), (150, 120, 90), np.uint8)
    strip = cv2.imread(str(path))
    out[buffs.BAR_TOP:buffs.BAR_BOTTOM, :strip.shape[1]] = strip
    return out


# ---- the buffs ------------------------------------------------------------------

@pytest.mark.parametrize("path", STRIPS, ids=lambda p: p.name)
def test_no_saved_bar_reads_another_speed_buff(path):
    """None of these buffs was ever on this account's bar (SPEED_BUFFS)."""
    assert buffs.speed_buffs(frame(path)) == []


def test_a_second_haste_icon_is_the_coconut_surge_and_the_count_stays_read():
    f = frame(FIX / "haste/x10-190458-line18.png")      # Haste x10 in slot 5
    bar = buffs.BAR_TOP, buffs.BAR_BOTTOM
    x5, x9 = 5 * buffs.ICON, 9 * buffs.ICON
    # a full Haste icon with no count, as the surge is drawn, in slot 9
    full = cv2.cvtColor(buffs._template("haste"), cv2.COLOR_GRAY2BGR)
    f[bar[0]:bar[1], x9:x9 + buffs.ICON] = full
    assert buffs.speed_buffs(f) == []              # no boots owned: never the surge
    got = buffs.speed_buffs(f, owned={"coconut_clogs", "porcelain_dipper"})
    assert [b.name for b in got] == ["coconut_haste"]
    assert got[0].factor(28.0) == pytest.approx(38.0 / 28.0)
    assert got[0].remaining_s == pytest.approx(2.0)
    h = buffs.haste(f)
    assert h.stacks == 10 and buffs.find_all(f, "haste")[0].slot == 5, h
    assert x5 < x9


class _Bar:
    """vision/bufficons.Bar's one method speed_buffs uses."""
    def __init__(self, *names):
        self._names = list(names)

    def names(self):
        return self._names


def test_the_network_must_name_both_haste_icons_while_it_is_on():
    f = frame(FIX / "haste/x10-190458-line18.png")
    x9 = 9 * buffs.ICON
    f[buffs.BAR_TOP:buffs.BAR_BOTTOM, x9:x9 + buffs.ICON] = cv2.cvtColor(
        buffs._template("haste"), cv2.COLOR_GRAY2BGR)
    boots = buffs.COCONUT_HASTE_GEAR[1:]
    assert buffs.speed_buffs(f, owned=boots, bar=_Bar("melody", "haste")) == []
    assert [b.name for b in buffs.speed_buffs(f, owned=boots, bar=_Bar("haste", "haste"))] \
        == ["coconut_haste"]


def test_a_field_boost_beside_haste_is_not_the_surge_even_with_the_boots():
    """MEASURED (incident 2026-10-22 05:16:31, frame 060): a Cactus field boost
    scores 0.755 on the Haste template beside a real Haste x6 (0.817), which
    the old rule read as Coconut Haste; it shows none of Haste's light square."""
    f = frame(FIX / "haste/boost-cactus-051631.png")
    assert [h.slot for h in buffs.find_all(f, "haste")] == [6, 7]
    assert buffs.speed_buffs(f, owned=buffs.COCONUT_HASTE_GEAR) == []
    assert buffs.haste(f).stacks == 6


def test_a_pale_streak_of_scenery_is_not_the_surge_either():
    """MEASURED (incident 2026-10-09 04:21:42, frame 048): slot 10 is dark
    scenery with a white streak at its foot, 0.91 on the template and 11 light
    rows, beside a real Haste x2; it shows none of the running figure."""
    f = frame(FIX / "haste/scenery-pale-042142.png")
    assert [h.slot for h in buffs.find_all(f, "haste")] == [3, 10]
    assert buffs.speed_buffs(f, owned=buffs.COCONUT_HASTE_GEAR) == []
    assert buffs.haste(f).stacks == 2


GOLDEN = sorted((FIX / "golden").glob("*.jpg"))


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.name)
def test_no_golden_frame_reads_a_surge_even_with_the_boots(path):
    """No surge has ever been on this account's bar (tests/unit/test_golden's
    frames; private, so a checkout without them collects none)."""
    assert buffs.speed_buffs(cv2.imread(str(path)), owned=buffs.COCONUT_HASTE_GEAR) == []


def test_the_wiki_factors_and_how_they_end():
    oil = buffs.SpeedBuff("oil", remaining_s=600.0)
    plus = buffs.SpeedBuff("haste_plus", remaining_s=60.0)
    assert oil.factor(28.0) == 1.2 and plus.factor(28.0) == 2.0
    h = buffs.Haste(present=True, stacks=3, remaining_s=10.0)
    no_bear = buffs.Bear(present=False)
    changes = buffs.speed_changes(h, no_bear, 28.0, [oil, plus])
    assert [at for at, _ in changes] == [10.0, 60.0, 600.0]
    assert changes[0][1] == pytest.approx(1.2 * 2.0)
    assert changes[-1][1] == pytest.approx(1.0)
    assert buffs.speed_changes(h, no_bear, 28.0) == [(10.0, 1.0)]


# ---- believing a change ---------------------------------------------------------

def test_a_flicker_is_dropped_and_a_change_is_believed_after_four_reads():
    c = FactorConfirm(1.0, reads=4)
    assert c.feed(1.6, 0.0, 0.0) == (1.0, None, None)
    assert c.feed(1.6, 0.1, 0.0)[1] is None          # the same read again: not counted
    assert c.feed(1.0, 0.25, 0.25) == (1.0, None, (1.6, 0.25))
    for k, t in enumerate((1.0, 1.25, 1.5)):
        assert c.feed(1.3, t, t)[1] is None, k
    factor, back, dropped = c.feed(1.3, 1.75, 1.75)
    assert (factor, dropped) == (1.3, None) and back == pytest.approx(0.75)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def hold(monkeypatch, reads, live):
    """Walk 200 studs at 32.2 through `reads` (one per 0.25 s, the factor the
    bar shows); -> (studs counted, notes)."""
    clock = Clock()
    monkeypatch.setattr(R.time, "monotonic", clock)
    monkeypatch.setattr(R, "RETIME_CONFIRM_LIVE", live)
    seq = iter(reads)
    value = {"now": next(seq)}
    runner = RouteRunner(object(), Router(path="/nonexistent", measurements=None),
                         walkspeed=32.2, movespeed_factor=lambda: value["now"])
    start = runner._speed_factor()
    runner._odo = [200.0, 0.0, clock.t, start, FactorConfirm(start)]
    for v in seq:
        clock.t += 0.25
        value["now"] = v
        runner._odometer_deadline(clock.t + 10)
    clock.t += 0.25
    runner._odometer_deadline(clock.t + 10)
    return runner._odo[1], runner._retime_notes


def test_live_a_one_read_flicker_is_not_walked(monkeypatch):
    reads = [1.0] * 4 + [1.6] + [1.0] * 6
    truth = 32.2 * 0.25 * len(reads)
    before, _ = hold(monkeypatch, reads, live=False)
    after, _ = hold(monkeypatch, reads, live=True)
    assert before == pytest.approx(truth + 32.2 * 0.6 * 0.25)
    assert after == pytest.approx(truth)


def test_live_a_real_change_is_walked_as_before_once_believed(monkeypatch):
    reads = [1.0] * 4 + [1.5] * 8
    before, _ = hold(monkeypatch, reads, live=False)
    after, _ = hold(monkeypatch, reads, live=True)
    assert after == pytest.approx(before)


def test_look_only_walks_as_before_and_says_what_it_would_skip(monkeypatch):
    reads = [1.0] * 4 + [1.6] + [1.0] * 6
    before, notes = hold(monkeypatch, reads, live=False)
    assert before == pytest.approx(32.2 * 0.25 * len(reads) + 32.2 * 0.6 * 0.25)
    assert len(notes) == 1 and notes[0].startswith("retime would: not walk the 1.60x"), notes
    assert R.RETIME_CONFIRM_LIVE is False and buffs.SPEED_BUFFS_LIVE is False


def test_a_flicker_replaced_by_another_says_what_came_next(monkeypatch):
    """x1 -> x1.6 for one read -> x1.3 that stays: the note names 1.30x, not
    a return to 1.00x it never made."""
    _, notes = hold(monkeypatch, [1.0] * 4 + [1.6] + [1.3] * 6, live=False)
    assert len(notes) == 1 and "then 1.30x read" in notes[0], notes
