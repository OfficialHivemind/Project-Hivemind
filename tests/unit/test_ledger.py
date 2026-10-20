"""The record of what the bot did, which has to survive the bot."""
from __future__ import annotations

import json

import pytest

from hivemind.brain.farm import Cycle
from hivemind.brain.ledger import Ledger


@pytest.fixture
def ledger(tmp_path):
    ticks = iter(range(1_000, 2_000))
    return Ledger(tmp_path / "trips.jsonl", clock=lambda: float(next(ticks)))


def trip(**kw) -> Cycle:
    base = dict(number=1, seconds=300.0, gather_seconds=240.0,
                pattern_passes=20, pollen_gathered=100_000,
                honey_earned=30_000)
    base.update(kw)
    return Cycle(**base)


def test_a_trip_survives_the_process_that_measured_it(ledger, tmp_path):
    """The whole reason this is a file: the night restarted 134 times."""
    ledger.record(trip(), aimed_at="Sunflower", credited="Sunflower")

    reread = Ledger(tmp_path / "trips.jsonl")
    assert [t["honey"] for t in reread.trips()] == [30_000]


def test_where_it_aimed_and_where_it_was_paid_are_both_kept(ledger):
    """MEASURED 2026-09-22: aimed Sunflower, credited Dandelion, 378,000/hr.

    Recording only the intention would have named the wrong field; recording
    only the credit would have hidden that the routes land a field over. Both
    are true and they are different facts.
    """
    ledger.record(trip(), aimed_at="Sunflower", credited="Dandelion")

    row = ledger.trips()[0]
    assert row["aimed_at"] == "Sunflower"
    assert row["credited"] == "Dandelion"
    # the honey is credited to where the game actually paid it
    assert ledger.best_fields() == [("Dandelion", 30_000)]


def test_an_unmeasured_trip_is_not_a_zero(ledger):
    """A tidy total that silently understates the night is worse than a gap."""
    ledger.record(trip(honey_earned=None, pollen_gathered=None),
                  aimed_at="Pine Tree")

    totals = ledger.totals()
    assert totals.trips == 1
    assert totals.unmeasured == 1
    assert totals.honey == 0
    assert totals.honey_per_hour is None, "unknown rate must not read as zero"
    assert "not measured" in totals.describe()
    assert ledger.best_fields() == [], "nothing was measured to credit"


def test_the_rate_is_measured_honey_over_the_time_it_took(ledger):
    ledger.record(trip(seconds=1800.0, honey_earned=50_000), credited="Rose")

    assert ledger.totals().honey_per_hour == pytest.approx(100_000.0)


def test_a_half_written_last_line_costs_one_trip_not_the_file(ledger):
    """The OOM killer has ended runs here twice, mid-append."""
    ledger.record(trip(number=1), credited="Rose")
    ledger.record(trip(number=2), credited="Rose")
    with ledger.path.open("a", encoding="utf-8") as fh:
        fh.write('{"cycle": 3, "honey": 99')      # killed mid-write

    rows = ledger.trips()
    assert [r["cycle"] for r in rows] == [1, 2]
    assert ledger.totals().honey == 60_000


def test_a_field_this_reader_has_never_heard_of_is_kept(ledger):
    """The same lesson as telemetry.from_json, which dropped whole events.

    A newer run writing a key an older reader does not know must not cost the
    trip -- the reader defaults what is missing and keeps what it cannot use.
    """
    ledger.append({"at": 1.0, "cycle": 7, "honey": 10, "beequips_found": 3})

    row = ledger.trips()[0]
    assert row["beequips_found"] == 3
    assert ledger.totals().honey == 10
    assert ledger.totals().passes == 0, "a missing key defaults, it does not raise"


def test_only_trips_since_a_moment_are_counted(ledger):
    ledger.record(trip(honey_earned=1), credited="Rose")      # at 1000
    ledger.record(trip(honey_earned=2), credited="Rose")      # at 1001

    assert ledger.totals(since=1001).honey == 2


def test_honey_per_field_is_ordered_best_first(ledger):
    ledger.record(trip(honey_earned=5_000), credited="Sunflower")
    ledger.record(trip(honey_earned=90_000), credited="Dandelion")
    ledger.record(trip(honey_earned=1_000), credited="Sunflower")

    assert ledger.best_fields() == [("Dandelion", 90_000), ("Sunflower", 6_000)]


def test_a_disk_that_will_not_take_the_line_does_not_end_the_night(tmp_path):
    """A trip that earned honey and failed to write it down still earned it."""
    blocked = Ledger(tmp_path / "a-file" / "trips.jsonl")
    (tmp_path / "a-file").write_text("not a directory")

    blocked.record(trip())          # must not raise
    assert blocked.trips() == []


def test_what_stopped_a_trip_early_is_written_down(ledger):
    """`recovered 2x (jump, go_home)` is how the 200x honey gap was found."""
    ledger.record(trip(recoveries=["jump", "go_home"], unreadable_pollen=7,
                       gather_ended="stalled"), credited="Rose")

    row = ledger.trips()[0]
    assert row["recoveries"] == ["jump", "go_home"]
    assert row["unreadable_pollen"] == 7
    assert row["gather_ended"] == "stalled"


def test_every_line_is_one_json_object(ledger):
    """So `tail -f` and `jq` work on it, and a reader needs no state."""
    ledger.record(trip(number=1), credited="Rose")
    ledger.record(trip(number=2), credited="Rose")

    lines = ledger.path.read_text().splitlines()
    assert len(lines) == 2
    assert all(isinstance(json.loads(line), dict) for line in lines)


# --- one sitting, not one process -----------------------------------------

def test_a_long_quiet_gap_ends_a_session(ledger):
    """MEASURED 2026-09-21: the morning report added last night's honey to
    tonight's and claimed 2,051,028 when the night earned 124,538. The bot
    restarts constantly, so a session cannot mean a process."""
    from hivemind.brain.ledger import latest_session, sessions

    rows = [{"at": 0.0, "honey": 1}, {"at": 60.0, "honey": 2},
            {"at": 60.0 + 4 * 3600, "honey": 40}, {"at": 60.0 + 4 * 3600 + 30,
                                                   "honey": 50}]

    assert [len(s) for s in sessions(rows)] == [2, 2]
    assert ledger.totals(rows=latest_session(rows)).honey == 90


def test_restarting_twenty_seconds_later_is_the_same_session(ledger):
    """scripts/overnight.sh waits GAP=20 s between attempts, and did so 134
    times in one night. Every one of those is the same sitting."""
    from hivemind.brain.ledger import sessions

    rows = [{"at": float(i * 20), "honey": 1} for i in range(134)]

    assert len(sessions(rows)) == 1


def test_no_trips_at_all_is_an_empty_session_not_a_crash(ledger):
    from hivemind.brain.ledger import latest_session

    assert latest_session([]) == []


# --- honey banked in the wrong seconds ------------------------------------

def test_a_bank_with_no_gathering_is_not_income_at_that_rate(ledger):
    """MEASURED 2026-09-22 04:51. The trip before it gathered 965,753 pollen
    and failed to walk home; the rejoin kept the backpack and the next cycle
    converted it on arrival in 59 seconds, 0 passes:

        cycle 1: pollen not measured, +1,019,114 honey, 0s over 0 passes

    The honey is real and belongs in the total. Dividing it by 59 seconds is
    not a rate -- it read 12,606,955 honey/hr.
    """
    ledger.record(trip(seconds=59.0, gather_seconds=0.0, pattern_passes=0,
                       pollen_gathered=None, honey_earned=1_019_114))
    ledger.record(trip(seconds=600.0, gather_seconds=540.0, pattern_passes=40,
                       honey_earned=60_000), credited="Rose")

    totals = ledger.totals()

    assert totals.honey == 1_079_114, "the banked honey is real"
    assert totals.carried_in == 1_019_114
    assert totals.earned_here == 60_000
    # 60,000 over the 600 s that actually gathered it
    assert totals.honey_per_hour == pytest.approx(360_000.0)
    assert "earlier trip's backpack" in totals.describe()


def test_a_carry_in_bank_credits_no_field(ledger):
    """Its pollen came from somewhere else, so naming a field would be a lie."""
    ledger.record(trip(seconds=59.0, gather_seconds=0.0, pattern_passes=0,
                       honey_earned=900_000), credited="Dandelion")

    assert ledger.best_fields() == []
    assert ledger.totals().honey == 900_000


def test_nothing_but_carry_in_has_no_rate(ledger):
    ledger.record(trip(seconds=59.0, gather_seconds=0.0, pattern_passes=0,
                       honey_earned=500_000))

    assert ledger.totals().honey_per_hour is None


# --- never turn "we do not know where" into "this field pays" -------------

def test_honey_from_an_unnamed_field_is_not_credited_to_the_aim(ledger):
    """REGRESSION. `by_field` read `credited or aimed_at`, so on 2026-09-22
    the morning report announced

        Honey by the field the game actually paid it in: sunflower 1,498

    for five trips whose "paid in" column was an em dash -- trips that had
    reached nowhere at all and gathered nothing. Falling back to the aim turns
    "we do not know" into a claim that a field pays, which is the one thing
    the reward feed exists to avoid guessing.
    """
    ledger.record(trip(honey_earned=637), aimed_at="Sunflower", credited=None)

    totals = ledger.totals()
    assert ledger.best_fields() == []
    assert totals.unattributed == 637
    assert totals.honey == 637, "the honey itself is still real"


def test_a_named_field_is_credited_normally(ledger):
    ledger.record(trip(honey_earned=90_000), aimed_at="Sunflower",
                  credited="Dandelion")

    assert ledger.best_fields() == [("Dandelion", 90_000)]
    assert ledger.totals().unattributed == 0


def test_a_carry_in_bank_is_neither_credited_nor_unattributed(ledger):
    """Its pollen came from an earlier trip, which is already counted."""
    ledger.record(trip(seconds=59.0, gather_seconds=0.0, pattern_passes=0,
                       honey_earned=1_019_114), credited="Dandelion")

    totals = ledger.totals()
    assert ledger.best_fields() == []
    assert totals.unattributed == 0
    assert totals.carried_in == 1_019_114


def test_how_each_trip_got_home_is_counted(ledger):
    """Gathered and converted: walked home. Gathered and never converted: the
    rejoin followed. A carry-in bank (no passes) is neither."""
    ledger.record(trip(converted=True), aimed_at="dandelion", credited="dandelion", attempt=1)
    ledger.record(trip(converted=False, number=2), aimed_at="dandelion", credited="dandelion", attempt=1)
    ledger.record(trip(converted=True, number=3, pattern_passes=0, gather_seconds=0.0,
                       pollen_gathered=0), aimed_at=None, credited=None, attempt=2)
    t = ledger.totals()
    assert (t.walked_home, t.not_home) == (1, 1)
    rows = ledger.trips()
    assert "convert_note" in rows[0], "the convert step's own words are kept"


def test_pollen_per_second_is_compared_by_pattern(ledger):
    """The measurement that decides whether Natro's patterns beat farm_snake."""
    ledger.record(trip(pollen_gathered=100_000, gather_seconds=500.0, pattern="farm_snake"),
                  aimed_at="dandelion", credited="dandelion", attempt=1)
    ledger.record(trip(number=2, pollen_gathered=300_000, gather_seconds=500.0,
                       pattern="natro_pattern_dandelion"),
                  aimed_at="dandelion", credited="dandelion", attempt=1)
    ledger.record(trip(number=3, pollen_gathered=None, gather_seconds=500.0,
                       pattern="natro_pattern_dandelion"),
                  aimed_at="dandelion", credited="dandelion", attempt=1)
    by = ledger.by_pattern()
    assert by["farm_snake"]["per_second"] == 200.0
    assert by["natro_pattern_dandelion"]["per_second"] == 600.0
    assert by["natro_pattern_dandelion"]["trips"] == 1, "an unreadable trip is not a zero"


def test_pollen_is_attributed_to_the_field_the_game_named(ledger):
    """Honey is banked a cycle later than the pollen that made it, so honey by
    field attributes the money to the wrong trip. Pollen has no such lag."""
    ledger.record(trip(pollen_gathered=986_128, gather_seconds=968.0),
                  aimed_at="rose", credited="rose", attempt=1)
    ledger.record(trip(number=2, pollen_gathered=100_000, gather_seconds=500.0),
                  aimed_at="dandelion", credited="dandelion", attempt=1)
    ledger.record(trip(number=3, pollen_gathered=0, gather_seconds=0.0,
                       honey_earned=1_141_497), aimed_at=None, credited=None, attempt=2)
    where = ledger.pollen_by_field()
    assert where["rose"]["pollen"] == 986_128
    assert where["rose"]["per_second"] == pytest.approx(1018.7, abs=0.2)
    assert where["dandelion"]["per_second"] == 200.0
    assert None not in where and len(where) == 2, where
