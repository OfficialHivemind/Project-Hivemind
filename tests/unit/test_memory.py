"""Is there room to start something heavy?

The Linux OOM killer terminated the agent twice mid-run during live game tests.
This guard exists so a run refuses to start rather than being killed halfway --
halfway is the expensive outcome, because the game is left running and whatever
the run was measuring is lost.

The subtle part is NOT being too strict. Swap records pressure that has already
happened and only drains on reboot, so blocking on swap alone would refuse every
run for the rest of a session while 24 GB sat free.
"""
import os

import pytest

from hivemind.platform.memory import SAFE_TO_START_GB, SWAP_PRESSURE, Memory


def mem(available, swap_used=0.0, total=30.0, swap_total=4.0):
    return Memory(available_gb=available, total_gb=total,
                  swap_used_gb=swap_used, swap_total_gb=swap_total)


def test_plenty_of_memory_is_not_pressure():
    assert not mem(24.5).under_pressure


def test_too_little_memory_is_pressure():
    assert mem(SAFE_TO_START_GB - 0.1).under_pressure


def test_full_swap_alone_does_not_block_when_memory_is_ample():
    """The exact state after the OOM kills: 24.5 GB free, swap 72% full."""
    state = mem(24.5, swap_used=2.9)
    assert state.swap_fraction > SWAP_PRESSURE
    assert not state.under_pressure, (
        "blocked on stale swap while 24.5 GB was free")
    assert state.worth_mentioning, "should still be reported"
    assert "tight but workable" in state.describe()


def test_full_swap_does_block_when_memory_is_also_tight():
    """Swap full AND memory low means the next spike has nowhere to go."""
    assert mem(SAFE_TO_START_GB * 1.5, swap_used=3.5).under_pressure


def test_pressure_carries_advice_naming_the_biggest_win():
    state = mem(2.0, swap_used=3.9)
    assert state.under_pressure
    assert "vision model" in state.advice(), "should name the 6 GB first"


def test_a_healthy_machine_offers_no_advice():
    assert mem(24.0, swap_used=0.1).advice() == ""


def test_unreadable_meminfo_does_not_block(monkeypatch, tmp_path):
    """A guard that cannot read the system must not veto the run."""
    import hivemind.platform.memory as module
    monkeypatch.setattr(module, "MEMINFO", tmp_path / "nope")
    safe, note = module.check("the game")
    assert safe and "could not read" in note


@pytest.mark.skipif(os.name == "nt", reason="/proc/meminfo is Linux (win/memory has its own)")
def test_real_meminfo_parses():
    from hivemind.platform.memory import read
    state = read()
    assert state.total_gb > 0, "could not read this machine's memory"
    assert 0 <= state.available_gb <= state.total_gb


def test_attaching_to_a_kept_game_does_not_ask_for_the_game_twice():
    # MEASURED 2026-10-03 11:32-11:52: the kept game running, swap full,
    # 6.3-6.7 GB free -- three starts refused for want of the 6.5 a fresh
    # game needs; an attach needs that less the game's own share
    tight = Memory(available_gb=6.3, total_gb=30.0, swap_used_gb=4.0, swap_total_gb=4.0,
                   stall_pct=1.1)
    assert tight.short_for(kept=False) and tight.under_pressure
    assert not tight.short_for(kept=True)
    # the stall test and the floor stand for an attach too
    stalled = Memory(available_gb=6.3, total_gb=30.0, swap_used_gb=4.0, swap_total_gb=4.0,
                     stall_pct=9.0)
    assert stalled.short_for(kept=True)
    starved = Memory(available_gb=1.5, total_gb=30.0, swap_used_gb=0.0, swap_total_gb=4.0,
                     stall_pct=0.0)
    assert starved.short_for(kept=True)
    assert "kept game" in tight.describe(kept=True) and "UNDER PRESSURE" not in tight.describe(kept=True)
