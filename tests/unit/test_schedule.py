"""B15 schedules: `schedule.pause` parsed and checked against the clock
(world/settings schedule_windows / schedule_paused; run_farm schedule_guard)."""
from __future__ import annotations

from datetime import datetime

from hivemind.world.settings import defaults, schedule_paused, schedule_windows

# 2026-11-02 is a Monday
MON = datetime(2026, 11, 2)


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return MON.replace(day=2 + day, hour=hh, minute=mm)


def test_off_by_default():
    assert defaults()["schedule.pause"] == ""
    assert schedule_windows("") == ([], [])
    assert not schedule_paused([], at(0, 12))


def test_work_hours_on_weekdays_only():
    windows, problems = schedule_windows("Mon-Fri 09:00-17:00")
    assert not problems
    assert schedule_paused(windows, at(0, 9))
    assert schedule_paused(windows, at(4, 16, 59))
    assert not schedule_paused(windows, at(4, 17))       # the end is open
    assert not schedule_paused(windows, at(0, 8, 59))
    assert not schedule_paused(windows, at(5, 12))       # Saturday


def test_quiet_hours_past_midnight_belong_to_the_day_they_start():
    windows, _ = schedule_windows("Fri 23:00-07:00")
    assert schedule_paused(windows, at(4, 23, 30))
    assert schedule_paused(windows, at(5, 6, 59))        # Saturday morning
    assert not schedule_paused(windows, at(4, 6))        # Friday morning
    every, _ = schedule_windows("23:00-07:00")
    assert schedule_paused(every, at(0, 2)) and not schedule_paused(every, at(0, 12))


def test_a_wrapping_day_range_and_several_windows():
    windows, problems = schedule_windows("Sat-Sun 10:00-12:00, wed 20:00-21:30")
    assert not problems
    assert schedule_paused(windows, at(6, 11)) and schedule_paused(windows, at(2, 21, 15))
    assert not schedule_paused(windows, at(2, 11))
    fri_to_mon, _ = schedule_windows("Fri-Mon 01:00-02:00")
    assert [schedule_paused(fri_to_mon, at(d, 1)) for d in range(7)] == \
        [True, False, False, False, True, True, True]


def test_a_bad_window_is_left_out_and_said():
    windows, problems = schedule_windows("Mon 09:00-17:00, Funday 1:00-2:00, 25:00-01:00, "
                                         "10:00-10:00, lunch")
    assert len(windows) == 1 and len(problems) == 4
    assert all(p.startswith("schedule.pause") and p.endswith("left out") for p in problems)
