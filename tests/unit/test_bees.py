"""The swarm model: the thing that explains a night of farming nothing."""
from __future__ import annotations

from hivemind.brain.bees import Swarm


def test_with_no_hive_claimed_it_refuses_and_says_why():
    """Bees only exist once a hive is claimed. This is THE root cause."""
    swarm = Swarm()
    ready, why = swarm.can_gather(now=100.0)
    assert ready is False
    assert "no hive" in why.lower()
    assert "bees only exist" in why.lower()


def test_a_claimed_hive_with_no_death_is_ready():
    swarm = Swarm()
    swarm.claimed(now=0.0)
    ready, _ = swarm.can_gather(now=1.0)
    assert ready is True


def test_a_death_sends_the_bees_home_for_the_recovery_window():
    swarm = Swarm()
    swarm.claimed(now=0.0)
    swarm.died("reset", now=10.0)
    ready, why = swarm.can_gather(now=20.0)          # 10 s into a 30 s wait
    assert ready is False
    assert "come back" in why or "need about" in why
    assert swarm.resting_for(now=20.0) == 20.0
    assert swarm.can_gather(now=41.0)[0] is True     # past the window


def test_seeing_pollen_rise_outranks_the_clock():
    """A measured fact beats a sourced estimate.

    RECOVERY_SECONDS comes from a wiki that contradicts itself. If the pollen
    counter is observed rising, the bees are demonstrably working and there is
    nothing left to wait for, whatever the clock says.
    """
    swarm = Swarm()
    swarm.claimed(now=0.0)
    swarm.died("reset", now=10.0)
    assert swarm.can_gather(now=15.0)[0] is False
    swarm.saw_pollen_rise(now=15.0)
    assert swarm.resting_for(now=15.0) == 0.0
    assert swarm.can_gather(now=15.0)[0] is True


def test_proof_from_before_the_death_does_not_count():
    """Bees seen working, THEN a reset, is not evidence they are working now."""
    swarm = Swarm()
    swarm.claimed(now=0.0)
    swarm.saw_pollen_rise(now=5.0)
    swarm.died("reset", now=10.0)
    assert swarm.can_gather(now=12.0)[0] is False


def test_it_explains_a_zero_reading_instead_of_blaming_the_field():
    """The loop that blamed geography for its own resets.

    `explains_zero` returns a reason when the bot itself is why nothing is
    being collected, and None when a zero really is about the field.
    """
    swarm = Swarm()
    assert swarm.explains_zero(now=1.0) is not None      # no hive
    swarm.claimed(now=0.0)
    assert swarm.explains_zero(now=1.0) is None          # a real barren field
    swarm.died("reset", now=2.0)
    assert swarm.explains_zero(now=3.0) is not None      # our own fault


def test_deaths_are_counted_and_described():
    swarm = Swarm()
    swarm.claimed(now=0.0)
    for i in range(3):
        swarm.died("reset", now=float(i))
    assert swarm.deaths == 3
    assert "3 death" in swarm.can_gather(now=1.0)[1]
    assert "no hive" in Swarm().describe()
