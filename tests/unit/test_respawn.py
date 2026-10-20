"""Respawning home after an errand: only ever with an empty bag, read off the HUD.

A reset is a death and death empties the backpack, so the one question this
module answers is "is there anything in the bag to lose?" -- from the pollen
counter, never from the sequence of events that should have emptied it.
"""
from types import SimpleNamespace as R

from hivemind.act import respawn


def test_a_counter_reading_zero_is_empty():
    v = respawn.bag_is_empty_enough(R(value=0, capacity=1_113_750, bar_fill=0.0))
    assert v.ok and "reads 0" in v.reason


def test_a_stray_token_s_worth_is_allowed_and_said():
    # the Bucko Bee recon arrived holding 1,958 of a 1,113,750 bag
    v = respawn.bag_is_empty_enough(R(value=1_958, capacity=1_113_750, bar_fill=0.0))
    assert v.ok and "1,958" in v.reason and "1%" in v.reason


def test_more_than_the_share_is_refused():
    v = respawn.bag_is_empty_enough(R(value=20_000, capacity=1_113_750, bar_fill=0.02))
    assert not v.ok and "lose it" in v.reason
    assert respawn.MAX_BAG_SHARE == 0.01


def test_digits_without_a_bag_size_are_not_enough():
    v = respawn.bag_is_empty_enough(R(value=500, capacity=None, bar_fill=None))
    assert not v.ok and "unknown" in v.reason


def test_the_bar_decides_only_when_the_digits_cannot():
    empty = respawn.bag_is_empty_enough(R(value=None, capacity=None, bar_fill=0.0))
    assert empty.ok and "illegible" in empty.reason
    full = respawn.bag_is_empty_enough(R(value=None, capacity=None, bar_fill=0.4))
    assert not full.ok and "not empty" in full.reason
    # legible digits win over a bar that disagrees
    digits = respawn.bag_is_empty_enough(R(value=300_000, capacity=1_000_000, bar_fill=0.0))
    assert not digits.ok


def test_no_reading_at_all_is_a_refusal():
    v = respawn.bag_is_empty_enough(R(value=None, capacity=None, bar_fill=None))
    assert not v.ok and "guessing" in v.reason



# ---- where a respawn lands, decided from the screen ---------------------------
# MEASURED 2026-09-23 19:49:52: the spawn point in front of the hive row, the
# pad a few tiles ahead, 85,197 honeycomb pixels. The prompt is the exception.

def test_the_pads_prompt_is_the_strongest_evidence():
    out = respawn.landed(True, 0)
    assert out.ok and out.where == "pad"


def test_the_hive_row_in_view_means_the_spawn_point():
    out = respawn.landed(False, 85_197)
    assert out.ok and out.where == "spawn" and "85,197" in out.reason


def test_a_field_reading_is_not_a_landing():
    out = respawn.landed(False, 11_879)            # a leg of the walk home, in the field
    assert not out.ok and out.where == "unknown" and "11,879" in out.reason


def test_the_threshold_is_the_homing_modules_own():
    from hivemind.act.homing import NEAR_YELLOW
    assert respawn.ROW_IN_VIEW_YELLOW == NEAR_YELLOW == 50_000
    assert respawn.landed(False, NEAR_YELLOW).ok
    assert not respawn.landed(False, NEAR_YELLOW - 1).ok
