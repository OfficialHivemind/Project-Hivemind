"""Recurring deadlines and boss preemption semantics.

The rule worth testing hardest: an UNVERIFIED persistent-HP flag must make the
boss non-preemptable. Treating a persistent boss as resetting forgoes an
optimisation; treating a resetting boss as persistent wastes whole fights, so
the two errors are not symmetric and the default must favour the cheap one.
"""
import pytest

from hivemind.world.timers import (MIN_OBSERVATIONS, TimerBook, TimerKind,
                                   TimerState, load_kinds)

HOUR = 3600.0


def state(persistent=True, verified=True, cooldown=HOUR):
    return TimerState(TimerKind(id="b", name="Boss", category="boss",
                                cooldown_s=cooldown, persistent_hp=persistent,
                                verified=verified))


def test_loads_the_shipped_file():
    kinds = load_kinds()
    assert "stump_snail" in kinds and "coconut_crab" in kinds


def test_nothing_shipped_is_verified_yet():
    assert not any(k.verified for k in load_kinds().values())


def test_no_shipped_boss_is_preemptable_while_unverified():
    """The safety rule, applied to the real data file."""
    book = TimerBook()
    assert book.preemptable() == []


def test_a_verified_persistent_boss_is_preemptable():
    assert state(persistent=True, verified=True).preemptable() is True


def test_an_unverified_persistent_boss_is_not_preemptable():
    s = state(persistent=True, verified=False)
    assert s.preemptable() is False
    assert "nobody has checked" in s.explain_preemption()   # plain words (UI panel 2026-10-22)


def test_a_resetting_boss_is_never_preemptable():
    s = state(persistent=False, verified=True)
    assert s.preemptable() is False
    assert "resets" in s.explain_preemption()


def test_an_unobserved_timer_has_no_deadline():
    """Honest gap rather than an invented time."""
    s = state()
    assert s.ready_at() is None
    assert s.remaining() is None
    assert s.ready(now=1e9) is False


def test_using_it_starts_the_cooldown():
    s = state(cooldown=HOUR)
    s.observe_used(at=0.0)
    assert s.ready_at() == pytest.approx(HOUR)
    assert not s.ready(now=HOUR - 1)
    assert s.ready(now=HOUR + 1)


def test_remaining_never_goes_negative():
    s = state(cooldown=HOUR)
    s.observe_used(at=0.0)
    assert s.remaining(now=10 * HOUR) == 0.0


def test_a_zero_cooldown_thing_is_ready_once_seen():
    s = state(cooldown=0)
    assert s.ready_at() is None
    s.observe_ready(at=100.0)
    assert s.ready(now=101.0)


def test_observed_cooldown_overrides_the_file_once_there_is_enough():
    """The period is learned from USE -> next sighting, not sighting -> sighting."""
    s = state(cooldown=HOUR)          # file says 1h
    for i in range(MIN_OBSERVATIONS + 1):
        s.observe_used(at=i * 3 * HOUR)
        s.observe_absent(at=i * 3 * HOUR + 2 * HOUR)    # still gone at +2h
        s.observe_ready(at=i * 3 * HOUR + 2 * HOUR)     # and there at +2h
    assert s.cooldown_is_measured
    assert s.cooldown == pytest.approx(2 * HOUR)


def test_one_observation_is_not_enough_to_override():
    s = state(cooldown=HOUR)
    s.observe_used(at=0.0)
    s.observe_ready(at=2 * HOUR)
    assert not s.cooldown_is_measured
    assert s.cooldown == pytest.approx(HOUR)


def test_repeated_sightings_of_one_window_are_not_counted_as_a_period():
    """Seeing it available repeatedly is ONE window, not a series of periods.

    This is the bug that made the estimator learn its own polling cadence: a
    window stays open until the thing is collected, so re-checking an
    uncollected Wealth Clock every five minutes taught a five-minute cooldown
    for an hourly machine -- and cooldown_is_measured then reported True.
    """
    s = state(cooldown=HOUR)
    s.observe_used(at=0.0)
    for t in (300.0, 600.0, 900.0, 1200.0, 1500.0):
        s.observe_ready(at=t)          # the same open window, seen five times
    assert len(s.observations) == 1, "one window is one measurement"
    assert not s.cooldown_is_measured
    assert s.cooldown == pytest.approx(HOUR), "the file's figure must stand"


def test_a_sighting_after_a_use_beats_the_files_guess():
    """Looking straight at it outranks arithmetic from an unverified cooldown."""
    s = state(cooldown=2 * 24 * HOUR)        # file guesses two days
    s.observe_used(at=0.0)
    assert not s.ready(now=3600.0)           # nothing seen yet: trust the guess
    s.observe_ready(at=3600.0)               # the bot SEES it available
    assert s.ready(now=3700.0), "observed availability was thrown away"
    assert s.remaining(now=3700.0) == 0.0


def test_a_use_after_a_sighting_starts_the_cooldown_again():
    """The sighting must not pin it ready forever once it has been consumed."""
    s = state(cooldown=HOUR)
    s.observe_used(at=0.0)
    s.observe_ready(at=100.0)
    assert s.ready(now=110.0)
    s.observe_used(at=110.0)
    assert not s.ready(now=120.0)
    assert s.remaining(now=120.0) == pytest.approx(HOUR - 10)


def test_the_bracket_records_how_uncertain_the_measurement_is():
    """An upper bound alone over-estimates; the lower bound bounds the error."""
    s = state(cooldown=HOUR)
    s.observe_used(at=0.0)
    s.observe_absent(at=1000.0)        # not there yet at t=1000
    s.observe_ready(at=1600.0)         # there by t=1600
    obs = s.observations[0]
    assert obs.lower == pytest.approx(1000.0)
    assert obs.upper == pytest.approx(1600.0)
    assert obs.estimate == pytest.approx(1300.0)
    assert obs.uncertainty == pytest.approx(600.0)


def test_upcoming_is_sorted_and_excludes_the_unknown():
    book = TimerBook()
    book.states["wealth_clock"].observe_used(at=0.0)
    book.states["coconut_crab"].observe_used(at=0.0)
    upcoming = book.upcoming(now=0.0)
    assert [s.kind.id for s in upcoming] == ["wealth_clock", "coconut_crab"]
    assert len(book.unknown()) == len(book) - 2


def test_a_malformed_row_does_not_lose_the_file(tmp_path):
    path = tmp_path / "t.yaml"
    path.write_text("timers:\n"
                    "  - {id: good, name: Good, cooldown_s: 60}\n"
                    "  - {id: bad}\n")
    kinds = load_kinds(path)
    assert "good" in kinds and "bad" not in kinds
