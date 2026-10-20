"""The Stump Snail (act/stumpsnail): its HP read off the bar's own text (two
scales that must agree), the rate as a median slope, the price against
gathering that picks a full session or a re-measure, the waits after each
outcome, and the switch -- off unless the owner turns it on."""
from __future__ import annotations

import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from hivemind.act import stumpsnail as snail
from hivemind.world.settings import defaults, describe, wired


def test_the_hp_text_is_read_whole_or_not_at_all():
    # tesseract's own outputs on the 2026-10-06 bars (act/stumpsnail HP_SCALES)
    assert snail.parse_hp("HP:29,880,096\n") == 29_880_096
    assert snail.parse_hp("HP: 512") == 512
    assert snail.parse_hp("HP:29,14,018") is None        # a lost digit
    assert snail.parse_hp("P:29,724,036") is None        # no "HP"
    assert snail.parse_hp("HP:29880,096") is None        # a lost comma
    assert snail.parse_hp("HP:31,000,000") is None       # more than it has
    assert snail.parse_hp("0 / 12,300") is None          # a Bloom's bar


def _bar_frame(text_cols: int = 18):
    """A frame with one nameplate-green bar at the snail's height (110 x 16,
    white text over 8 x `text_cols` of it: 0.08 at 18, the snail's measured
    0.046-0.103) and one bright leaf-green box with none."""
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[90:106, 1000:1110] = (68, 231, 31)          # BGR of nameplate's (64, 220, 232) HSV mode
    frame[94:102, 1030:1030 + text_cols] = (255, 255, 255)
    frame[500:510, 300:390] = (68, 231, 31)           # a leaf: green, no text
    return frame


class _Tesseract:
    """A stand-in for tesseract that answers by the page's width (the scale)."""

    def __init__(self, by_scale):
        self.by_scale, self.calls = by_scale, 0

    def __call__(self, cmd, input, capture_output, timeout):
        self.calls += 1
        page = cv2.imdecode(np.frombuffer(input, np.uint8), cv2.IMREAD_GRAYSCALE)
        scale = round((page.shape[1] - 2 * snail.HP_PAD) / 110)
        return type("Out", (), {"stdout": self.by_scale.get(scale, "").encode()})()


def test_the_hp_counts_only_when_both_scales_read_the_same():
    frame = _bar_frame()
    assert snail.hp_boxes(frame) == [(1000, 90, 110, 16)]       # the leaf is not read
    agree = _Tesseract({4: "HP:29,879,792", 3: "HP: 29,879,792"})
    assert snail.read_hp(frame, run=agree) == 29_879_792
    assert agree.calls == 2
    # MEASURED: alone, a scale reads a 7 as a 1 (600 or 60,000 HP low)
    assert snail.read_hp(frame, run=_Tesseract({4: "HP:29,879,792", 3: "HP:29,879,192"})) is None
    assert snail.read_hp(frame, run=_Tesseract({4: "HP:29,879,792"})) is None
    assert snail.hp_boxes(_bar_frame(text_cols=0)) == []        # no text: not a nameplate


def test_the_rate_is_the_median_slope_and_one_misread_does_not_move_it():
    start = [(0.0, 29_879_800), (1.0, 29_879_700), (2.0, 29_879_600)]
    end = [(900.0, 29_805_100), (901.0, 29_805_000), (902.0, 29_804_900)]
    assert snail.dps(start + end) == pytest.approx(83.0, abs=0.5)
    # one end reading 600,000 low, the misread the two scales exist for
    bad = start + end[:2] + [(902.0, 29_204_900)]
    assert snail.dps(bad) == pytest.approx(83.0, abs=1.0)
    assert snail.dps(start) is None                             # under MIN_SPAN_S
    assert snail.dps([(0.0, 100), (60.0, 200)]) == 0.0          # never below nothing
    assert snail.hp_left(start + end) == 29_805_000


def test_a_full_session_goes_only_when_it_beats_gathering():
    # MEASURED: 83 HP/s (2026-10-06) against the planner's 3,747/s (2026-10-12)
    assert snail.session_q(83.0, snail.SESSION_S, 3_747.0, p=0.9) < 0
    assert snail.session_seconds({"dps": 83.0}, 3_747.0, 0.9) == snail.PROBE_S
    assert snail.session_seconds({}, 3_747.0, 0.9) == snail.PROBE_S          # never measured
    assert snail.session_seconds({"dps": 5_000.0}, None, 0.9) == snail.PROBE_S  # no rho
    # the break-even, a walk that always lands: rho * (S + walk) / S
    even = 3_747.0 * (snail.SESSION_S + snail.WALK_S) / snail.SESSION_S
    assert snail.session_seconds({"dps": even * 1.01}, 3_747.0, 1.0) == snail.SESSION_S
    assert snail.session_seconds({"dps": even * 0.99}, 3_747.0, 1.0) == snail.PROBE_S


def test_the_waits_after_each_outcome():
    t = 1_791_800_000.0
    poor = snail.record({}, "fought", t, rate=83.0, hp=29_500_000, q=-3.4e6)
    assert poor["next_at"] == t + snail.PROBE_EVERY_S
    assert poor["dps"] == 83.0 and poor["hp"] == 29_500_000
    paying = snail.record(poor, "fought", t, rate=5_000.0, q=1.0e6)
    assert paying["next_at"] == t + snail.AGAIN_S and paying["dps"] == 5_000.0
    assert snail.record({}, "absent", t)["next_at"] == t + snail.ABSENT_OPEN_S
    killed = snail.record(paying, "killed", t)
    assert killed["next_at"] == t + snail.COOLDOWN_S and killed["hp"] == snail.SNAIL_HP
    assert not snail.due(killed, t + snail.COOLDOWN_S - 1) and snail.due(killed, t + snail.COOLDOWN_S)
    # losses in a row double the wait, a session that ran resets the count
    one = snail.record(poor, "died", t)
    two = snail.record(one, "walk", t)
    three = snail.record(two, "unread", t)
    assert [s["next_at"] - t for s in (one, two, three)] == [
        snail.LOST_RETRY_S, 2 * snail.LOST_RETRY_S, 4 * snail.LOST_RETRY_S]
    assert snail.record(snail.record(three, "fought", t, q=-1.0), "died", t)["next_at"] == t + snail.LOST_RETRY_S
    many = {}
    for _ in range(12):
        many = snail.record(many, "died", t)
    assert many["next_at"] == t + snail.LOST_RETRY_MAX_S
    assert len(many["tries"]) == 12


def test_the_state_round_trips(tmp_path):
    path = tmp_path / "stumpsnail.json"
    assert snail.load(path) == {}
    snail.save(path, snail.record({}, "fought", 7.0, rate=83.0, q=-1.0))
    assert snail.load(path)["dps"] == 83.0


def test_the_switch_is_off_by_default_and_read():
    assert defaults()["combat.stump_snail"] is False
    assert wired("combat.stump_snail")
    assert len(describe("combat.stump_snail")) > 30


def test_the_feed_word_is_the_snails_own():
    assert snail.defeated("Defeated Stump Snail!")
    assert not snail.defeated("Defeated Rhino Beetle! (+1 Battle Point)")


# THE READER ON THE REAL BARS, where they are still on this machine: the
# twenty frames of 2026-10-06 with the bar on screen, read by eye.
FRAMES = Path.home() / "Hivemind" / "var" / "routes" / "attempt-676"
TRUTH = {
    "063714-natro_out_stump-21": 29_880_100, "063714-natro_out_stump-22": 29_880_100,
    "063717-natro_start_stump": 29_880_096, "063718-natro_start_stump": 29_880_056,
    "063720-natro_pattern_stump": 29_879_792,
    "070143-natro_out_stump-21": 29_774_044, "070143-natro_out_stump-22": 29_774_044,
    "070147-natro_start_stump": 29_774_018, "070148-natro_start_stump": 29_773_976,
    "070149-natro_pattern_stump": 29_773_800,
    "071646-natro_out_stump-21": 29_720_538, "071646-natro_out_stump-22": 29_720_538,
    "071649-natro_start_stump": 29_720_512, "071650-natro_start_stump": 29_720_292,
    "071652-natro_pattern_stump": 29_720_036,
    "073744-natro_out_stump-21": 29_635_580, "073744-natro_out_stump-22": 29_635_580,
    "073748-natro_start_stump": 29_635_540, "073749-natro_start_stump": 29_635_356,
    "073751-natro_pattern_stump": 29_635_176,
}


def test_the_real_bars_read_right_or_not_at_all():
    if shutil.which(snail.TESSERACT) is None or not FRAMES.is_dir():
        pytest.skip("tesseract or the 2026-10-06 frames are not on this machine")
    exact = 0
    for stem, hp in TRUTH.items():
        path = next(iter(sorted(FRAMES.glob(stem + "*.jpg"))), None)
        if path is None:
            pytest.skip(f"{stem} is gone")
        got = snail.read_hp(cv2.imread(str(path)))
        assert got in (None, hp), f"{path.name}: read {got}, the bar says {hp}"
        exact += got == hp
    assert exact >= 10                       # MEASURED 12 of 20
