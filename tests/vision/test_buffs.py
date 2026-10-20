"""The buff bar reader, against the recorded bars it was built from.

The strips in tests/fixtures/buffs are the bar rows (58..96) of three real
frames, with the counts read by eye in labels.json; the templates in
data/templates/buffs were cut from the same frames by
scripts/build_buff_templates.py. So these tests prove the reader against its
own provenance -- and `test_a_bar_it_was_not_built_from` keeps one frame back.
"""
from __future__ import annotations

import json
import pathlib

import cv2
import numpy as np
import pytest

from hivemind.vision import buffs

FIX = pathlib.Path(__file__).resolve().parents[2] / "tests/fixtures/buffs"


def _frame_with(strip: np.ndarray) -> np.ndarray:
    """A 1080p frame that is sky everywhere except the bar rows."""
    frame = np.full((1080, 1920, 3), (150, 120, 90), np.uint8)
    frame[buffs.BAR_TOP:buffs.BAR_BOTTOM, :strip.shape[1]] = strip
    return frame


def _bars():
    labels = json.loads((FIX / "labels.json").read_text())
    for name, per_slot in labels.items():
        strip = cv2.imread(str(FIX / name))
        assert strip is not None, name
        yield name, _frame_with(strip), {int(k): v for k, v in per_slot.items()}


def test_every_labelled_stack_count_reads_back():
    checked = 0
    for name, frame, per_slot in _bars():
        icons = buffs.slots(frame)
        for slot, text in per_slot.items():
            if not text or "." in text:            # no count, or the small multiplier font
                continue
            assert buffs.stacks(icons[slot]) == int(text[1:]), (name, slot, text)
            checked += 1
    assert checked >= 10


def test_an_icon_with_no_count_reads_none_not_zero():
    for name, frame, per_slot in _bars():
        icons = buffs.slots(frame)
        for slot, text in per_slot.items():
            if text == "":
                assert buffs.stacks(icons[slot]) is None, (name, slot)


def test_the_small_multiplier_font_is_not_mistaken_for_a_count():
    """"x1.22" and "x1.20" are 6-8 px glyphs; the count font is 12 px."""
    for name, frame, per_slot in _bars():
        icons = buffs.slots(frame)
        for slot, text in per_slot.items():
            if "." in text:
                assert buffs.stacks(icons[slot]) is None, (name, slot, text)


def test_haste_is_found_where_it_is_and_nowhere_else():
    bars = dict((n, (f, p)) for n, f, p in _bars())
    # bar0: Haste at slot 3 with x3; bar1: Haste at slot 5 with no count; bar2: none
    h0 = buffs.haste(bars["bar0.png"][0])
    assert h0.present and h0.stacks == 3 and h0.factor == pytest.approx(1.3)
    assert buffs.find(bars["bar0.png"][0], "haste").slot == 3
    h1 = buffs.haste(bars["bar1.png"][0])
    assert h1.present and h1.stacks is None and h1.factor == pytest.approx(1.1)
    assert buffs.find(bars["bar1.png"][0], "haste").slot == 5
    h2 = buffs.haste(bars["bar2.png"][0])
    assert not h2.present and h2.factor == 1.0


def test_melody_is_not_haste_though_both_sit_on_a_light_square():
    bars = dict((n, (f, p)) for n, f, p in _bars())
    frame = bars["bar0.png"][0]
    assert buffs.find(frame, "melody").slot == 5
    assert buffs.find(frame, "haste").slot == 3


def test_no_frame_means_no_haste():
    h = buffs.haste(None)
    assert not h.present and h.factor == 1.0


def test_describe_says_what_was_read():
    assert "no haste" in buffs.Haste(False, None).describe()
    assert "x4" in buffs.Haste(True, 4, 0.9).describe() and "1.4x" in buffs.Haste(True, 4, 0.9).describe()
    # a count the reader could not make out, against an icon with no digit
    # on it at all -- a single stack (`Haste.counted`)
    assert "unreadable" in buffs.Haste(True, None, 0.9, counted=True).describe()
    assert "no count on the icon" in buffs.Haste(True, None, 0.9).describe()


def test_a_present_reading_is_held_through_the_icons_fade():
    """MEASURED 2026-09-22 22:24: the icon's score dipped under the threshold
    for about a second mid-buff (0.80 -> 0.74 -> 0.66); one read flickered."""
    calls = {"n": 0}
    readings = [buffs.Haste(True, 3, 0.9), buffs.Haste(False, None), buffs.Haste(False, None),
                buffs.Haste(False, None)]

    class T(buffs.HasteTracker):
        pass
    tracker = T(hold_seconds=2.5)
    import hivemind.vision.buffs as B
    real = B.haste
    try:
        B.haste = lambda frame: readings[min(calls.__setitem__("n", calls["n"] + 1) or calls["n"] - 1, 3)]
        assert tracker.read(None, now=0.0).stacks == 3
        assert tracker.read(None, now=1.0).stacks == 3, "held through the dip"
        assert tracker.read(None, now=2.0).present
        assert not tracker.read(None, now=3.0).present, "a genuine end is seen once the hold expires"
    finally:
        B.haste = real
