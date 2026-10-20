"""Facts about a field, filed under a name the game said. See brain/fieldnotes."""
from __future__ import annotations

import pathlib

import pytest

from hivemind.brain.fieldnotes import IMPLAUSIBLE_JUMP, FieldNotes, Note


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def tick(self, seconds=1.0):
        self.t += seconds
        return self.t


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def notes(clock):
    return FieldNotes(clock=clock)


def walk(notes, clock, field, pollen, seconds=1.0):
    notes.note(field, pollen)
    clock.tick(seconds)


def test_nothing_is_known_at_the_start(notes):
    assert notes.best() == []
    assert "no fields recorded" in notes.describe()


def test_pollen_is_credited_to_the_field_it_was_gathered_in(notes, clock):
    walk(notes, clock, "pumpkin", 100)
    walk(notes, clock, "pumpkin", 200)
    notes.note("pumpkin", 300)
    note = notes.known("pumpkin")
    assert note.pollen == 200
    assert note.seconds == pytest.approx(2.0)
    assert note.rate == pytest.approx(100.0)


def test_a_sample_with_no_fix_is_thrown_away(notes, clock):
    """THE WHOLE POINT. The old map credited pollen to wherever it last thought
    it was, and smeared a million pollen over thirteen imaginary places."""
    walk(notes, clock, "pumpkin", 100)
    walk(notes, clock, None, 5000)
    notes.note(None, 9000)
    assert notes.unattributed == 2
    assert notes.known("pumpkin").pollen == 0


def test_a_gap_with_no_fix_does_not_bridge_two_fields(notes, clock):
    """Time must not be credited across a stretch where we were lost."""
    walk(notes, clock, "pumpkin", 100)
    walk(notes, clock, None, 100, seconds=30.0)
    walk(notes, clock, "cactus", 100)
    notes.note("cactus", 150)
    assert notes.known("pumpkin").seconds == pytest.approx(0.0)
    assert notes.known("cactus").seconds == pytest.approx(1.0)
    assert notes.known("cactus").pollen == 50


def test_moving_between_fields_does_not_credit_the_new_one(notes, clock):
    """The first sample in a field describes the walk in, not the field."""
    walk(notes, clock, "pumpkin", 100)
    notes.note("cactus", 900)
    assert notes.known("cactus").pollen == 0
    assert notes.known("cactus").visits == 1


def test_returning_to_a_field_counts_a_second_visit(notes, clock):
    walk(notes, clock, "pumpkin", 10)
    walk(notes, clock, "cactus", 20)
    notes.note("pumpkin", 30)
    assert notes.known("pumpkin").visits == 2


def test_an_impossible_jump_is_not_gathering(notes, clock):
    """A conversion empties the backpack and a quest reward arrives at once.
    Neither came out of the ground."""
    walk(notes, clock, "pumpkin", 1_000)
    notes.note("pumpkin", 1_000 + IMPLAUSIBLE_JUMP + 1)
    assert notes.known("pumpkin").pollen == 0


def test_pollen_going_down_is_never_negative_earnings(notes, clock):
    walk(notes, clock, "pumpkin", 500_000)
    notes.note("pumpkin", 0)                # converted at the hive
    assert notes.known("pumpkin").pollen == 0


def test_fields_are_ranked_by_rate_not_by_total(notes, clock):
    """An hour in a poor field must not outrank a minute in a rich one."""
    for _ in range(10):
        walk(notes, clock, "clover", 0)
    notes.note("clover", 100)
    walk(notes, clock, "pumpkin", 0)
    notes.note("pumpkin", 500)
    best = notes.best()
    assert [n.field for n in best] == ["pumpkin", "clover"]


def test_a_field_that_never_paid_is_not_in_best(notes, clock):
    walk(notes, clock, "stump", 0)
    notes.note("stump", 0)
    assert notes.best() == []
    assert notes.known("stump") is not None


def test_sentences_about_a_field_are_kept_once(notes):
    notes.saw("pumpkin", "orange pumpkins and blue flowers")
    notes.saw("pumpkin", "orange pumpkins and blue flowers")
    notes.saw("pumpkin", "a mantis is here")
    assert len(notes.known("pumpkin").saw) == 2


def test_it_survives_being_saved_and_read_back(notes, clock, tmp_path):
    walk(notes, clock, "pumpkin", 100)
    notes.note("pumpkin", 400)
    notes.saw("pumpkin", "orange pumpkins")
    path = notes.save(tmp_path / "fields.json")

    fresh = FieldNotes()
    assert fresh.load(path) == 1
    note = fresh.known("pumpkin")
    assert note.pollen == 300 and note.saw == ["orange pumpkins"]


def test_loading_adds_to_what_is_already_known(notes, clock, tmp_path):
    walk(notes, clock, "pumpkin", 0)
    notes.note("pumpkin", 100)
    path = notes.save(tmp_path / "a.json")
    notes.load(path)
    assert notes.known("pumpkin").pollen == 200, "a second session should add"


def test_a_missing_or_broken_file_is_not_fatal(tmp_path):
    assert FieldNotes().load(tmp_path / "nope.json") == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert FieldNotes().load(bad) == 0


def test_it_says_how_much_it_threw_away(notes, clock):
    walk(notes, clock, "pumpkin", 0)
    notes.note("pumpkin", 10)
    for _ in range(5):
        notes.note(None, 10)
    assert "discarded" in notes.describe()


def test_a_note_describes_itself_in_english():
    note = Note(field="mountain_top", pollen=1234, seconds=10.0, visits=1)
    text = note.describe()
    assert "mountain top" in text and "1,234" in text and "visit" in text


# ---- how dangerous is a field, and how sure are we? -----------------------
# Zero deaths in a few minutes is not evidence of safety. The raw ratio says
# it is -- exactly 0.0, whether we watched for ten seconds or ten hours -- and
# used to choose a trip length that answer is "stay forever", which costs a
# full backpack the first time a mantis lands.
def test_no_deaths_in_a_short_watch_is_not_treated_as_safe():
    from hivemind.brain.fieldnotes import Note
    brief = Note(field="x", seconds=120.0, deaths=0)
    long = Note(field="x", seconds=7200.0, deaths=0)
    assert brief.likely_death_rate > long.likely_death_rate > 0


def test_evidence_of_safety_accumulates_towards_zero():
    from hivemind.brain.fieldnotes import Note
    rates = [Note(field="x", seconds=s, deaths=0).likely_death_rate
             for s in (60, 600, 6000, 60000)]
    assert rates == sorted(rates, reverse=True)
    assert rates[-1] < 1e-4


def test_a_real_death_raises_the_rate_sharply():
    from hivemind.brain.fieldnotes import Note
    clean = Note(field="x", seconds=880.0, deaths=0)
    killed = Note(field="x", seconds=880.0, deaths=1)
    assert killed.likely_death_rate > 2 * clean.likely_death_rate


def test_a_field_never_gathered_in_borrows_the_pooled_rate():
    from hivemind.brain.fieldnotes import FieldNotes, Note
    notes = FieldNotes()
    notes.notes["known"] = Note(field="known", seconds=1000.0, deaths=2)
    pooled = notes.pooled_death_rate()
    assert notes.danger_of("somewhere_new") == pooled
    assert pooled > 0


def test_a_field_with_its_own_record_uses_it_not_the_pool():
    from hivemind.brain.fieldnotes import FieldNotes, Note
    notes = FieldNotes()
    notes.notes["deadly"] = Note(field="deadly", seconds=100.0, deaths=5)
    notes.notes["calm"] = Note(field="calm", seconds=10_000.0, deaths=0)
    assert notes.danger_of("deadly") > notes.danger_of("calm")


def test_with_no_records_at_all_nothing_is_claimed():
    from hivemind.brain.fieldnotes import FieldNotes
    assert FieldNotes().pooled_death_rate() == 0.0


def test_deaths_are_remembered_across_a_save_and_load(tmp_path):
    from hivemind.brain.fieldnotes import FieldNotes, Note
    notes = FieldNotes()
    notes.notes["pineapple"] = Note(field="pineapple", seconds=500.0,
                                    pollen=1000, deaths=2)
    path = notes.save(tmp_path / "notes.json")
    again = FieldNotes()
    again.load(path)
    assert again.notes["pineapple"].deaths == 2


def test_a_death_is_credited_to_the_field_the_game_last_named():
    from hivemind.brain.fieldnotes import FieldNotes
    notes = FieldNotes()
    notes.note("pineapple", 1000)
    notes.note("pineapple", 2000)
    hit = notes.died()
    assert hit is not None and hit.field == "pineapple"
    assert notes.notes["pineapple"].deaths == 1


def test_a_death_with_no_idea_where_we_were_is_not_invented():
    from hivemind.brain.fieldnotes import FieldNotes
    notes = FieldNotes()
    assert notes.died() is None


# ---- a death is credited even when the feed has gone quiet ----------------
# REGRESSION for 2026-09-21. A real death in the Pineapple Patch recorded
# `deaths: 0`, because the sample immediately before it was unattributed --
# which is exactly what a death looks like from the reward feed, since the
# character is dying and respawning and the game has nothing to credit. The
# danger-learning that death was supposed to feed was therefore inert.
def test_a_death_is_credited_even_after_an_unattributed_sample():
    from hivemind.brain.fieldnotes import FieldNotes
    notes = FieldNotes()
    notes.note("pineapple", 1000)
    notes.note("pineapple", 2000)
    notes.note(None, None)          # the feed goes quiet, as it does on death
    hit = notes.died()
    assert hit is not None and hit.field == "pineapple"
    assert notes.notes["pineapple"].deaths == 1


def test_two_deaths_in_a_row_land_on_the_same_field():
    from hivemind.brain.fieldnotes import FieldNotes
    notes = FieldNotes()
    notes.note("pineapple", 1000)
    notes.died()
    notes.note(None, None)
    notes.died()
    assert notes.notes["pineapple"].deaths == 2


def test_an_explicit_field_still_wins_over_the_remembered_one():
    from hivemind.brain.fieldnotes import FieldNotes
    notes = FieldNotes()
    notes.note("pineapple", 1000)
    notes.died("pine_tree")
    assert notes.notes["pine_tree"].deaths == 1
    assert notes.notes.get("pineapple") is None or \
        notes.notes["pineapple"].deaths == 0


def test_a_death_before_the_game_ever_named_a_field_is_not_invented():
    from hivemind.brain.fieldnotes import FieldNotes
    assert FieldNotes().died() is None


# ------------------- which field the game credited DURING this trip ---------
# MEASURED 2026-09-22 03:05: the convert asked `credited_field`, got "nothing",
# and the pose search kept a wrong hive slot because nothing contradicted it --
# while `Note.last_seen` for the Dandelion Field had been stamped during that
# very trip. `credited_field` reads the last reward-feed FIX, and a fix costs a
# vision-model call, so it is stale or absent whenever the model has been
# unloaded under memory pressure.

def test_the_field_credited_since_a_moment_is_the_most_recent_one():
    clock = [1000.0]
    notes = FieldNotes(clock=lambda: clock[0])
    notes.note("dandelion", 100)
    clock[0] = 1010.0
    notes.note("sunflower", 200)
    assert notes.field_since(1005.0) == "sunflower"
    assert notes.field_since(999.0) == "sunflower"


def test_nothing_credited_in_the_window_is_a_real_answer():
    clock = [1000.0]
    notes = FieldNotes(clock=lambda: clock[0])
    notes.note("dandelion", 100)
    assert notes.field_since(2000.0) is None


def test_it_does_not_depend_on_the_last_fix_surviving():
    """The whole point: `credited_field` can be None while a field was
    certainly credited a moment ago."""
    clock = [1000.0]
    notes = FieldNotes(clock=lambda: clock[0])
    notes.note("dandelion", 100)
    notes._seen_field = None            # the model was unloaded; the fix is gone
    notes._last_field = None
    assert notes.credited_field is None
    assert notes.field_since(999.0) == "dandelion"


def test_an_empty_set_of_notes_credits_nothing():
    assert FieldNotes().field_since(0.0) is None


def test_the_window_must_be_measured_on_the_notes_own_clock():
    """THE BUG THIS COST A NIGHT OF MEASUREMENTS. The notes run on
    `time.monotonic` -- seconds since boot -- and `Note.last_seen` is stamped
    from it, so a caller passing a Unix timestamp (about 1.79e9) makes this
    return None for ever. It did exactly that on its first live outing:
    "the trip aimed at sunflower and the game credited no field while it was
    out", while the same run's report said Dandelion had gained 102,328 pollen
    over 305 seconds.
    """
    import time as _time
    notes = FieldNotes()
    began = notes.clock()
    notes.note("dandelion", 100)
    assert notes.field_since(began) == "dandelion"
    assert notes.field_since(_time.time()) is None, (
        "a wall-clock window must not silently match nothing -- callers pass "
        "notes.clock()")


# --- the death rate a trip is planned around ------------------------------
# MEASURED 2026-09-22 04:56: `danger_of` switched to the field's own Jeffreys
# rate the moment a field had one second of history, so the LEAST watched
# field got the SHORTEST trip. Rose pays 927 pollen/s -- the best rate this
# account has ever recorded -- and had been watched for 9 s, so it asked for a
# 60-second trip against a 108-second round trip. Zero deaths anywhere, all
# night. See FieldNotes.danger_of.

def test_a_field_watched_briefly_keeps_the_characters_own_rate():
    notes = FieldNotes()
    notes.notes["pineapple"] = Note(field="pineapple", seconds=24_000.0,
                                    pollen=1, deaths=0)
    notes.notes["rose"] = Note(field="rose", seconds=9.0, pollen=8_434,
                               deaths=0)

    pooled = notes.pooled_death_rate()

    # 9 seconds of evidence must not overturn 24,000 seconds of survival
    assert notes.danger_of("rose") == pytest.approx(pooled, rel=0.05)
    # and it is nowhere near what the field's own sample alone would say
    assert notes.danger_of("rose") < notes.notes["rose"].likely_death_rate / 100


def test_nothing_observed_is_exactly_the_pooled_rate():
    """Unchanged behaviour at the extreme: this was already right."""
    notes = FieldNotes()
    notes.notes["pineapple"] = Note(field="pineapple", seconds=24_000.0,
                                    pollen=1, deaths=0)

    assert notes.danger_of("never_been") == notes.pooled_death_rate()


def test_a_long_record_converges_on_its_own_deaths_per_second():
    """The prior must fade, or a field that really is lethal never shows it."""
    notes = FieldNotes()
    notes.notes["safe"] = Note(field="safe", seconds=100_000.0, pollen=1,
                               deaths=0)
    notes.notes["pine"] = Note(field="pine", seconds=100_000.0, pollen=1,
                               deaths=50)

    assert notes.danger_of("pine") == pytest.approx(50 / 100_000.0, rel=0.02)


def test_one_real_death_shortens_the_trip_sharply():
    """Relaxing on no evidence must not mean ignoring evidence.

    A single death in a twenty-minute record takes the planned trip from the
    1,200 s cap to about 383 s -- because one death costs the whole backpack.
    """
    from hivemind.brain.decide import best_trip_seconds

    notes = FieldNotes()
    notes.notes["safe"] = Note(field="safe", seconds=24_000.0, pollen=1,
                               deaths=0)
    notes.notes["pine"] = Note(field="pine", seconds=1_200.0, pollen=1,
                               deaths=0)
    clean = best_trip_seconds(108.0, notes.danger_of("pine"),
                              fill_seconds=48_000)

    notes.notes["pine"].deaths = 1
    killed = best_trip_seconds(108.0, notes.danger_of("pine"),
                               fill_seconds=48_000)

    assert clean == pytest.approx(1_200.0)
    assert killed < clean / 2, (clean, killed)


def test_the_least_watched_field_no_longer_gets_the_shortest_trip():
    """The exact perversity that was costing the night, as a property."""
    from hivemind.brain.decide import best_trip_seconds

    notes = FieldNotes()
    notes.notes["pineapple"] = Note(field="pineapple", seconds=22_772.0,
                                    pollen=1, deaths=0)
    for name, seconds in (("rose", 9.0), ("sunflower", 74.0),
                          ("pumpkin", 160.0), ("dandelion", 2_490.0)):
        notes.notes[name] = Note(field=name, seconds=seconds, pollen=1,
                                 deaths=0)

    trips = {name: best_trip_seconds(108.0, notes.danger_of(name),
                                     fill_seconds=48_000)
             for name in ("rose", "sunflower", "pumpkin", "dandelion")}

    # none of them is cut short merely for being new, and in particular none
    # asks for a trip shorter than the round trip that pays for it
    assert all(t > 108.0 for t in trips.values()), trips
    assert trips["rose"] > 600.0, trips


# --- did the trip actually get there --------------------------------------

def test_the_feed_naming_a_field_settles_it():
    from hivemind.brain.fieldnotes import trip_arrived
    assert trip_arrived(0, "dandelion", 50) is True


def test_pollen_going_up_settles_it_even_unnamed():
    """A field has no prompt and the feed needs a pickup plus a model call,
    so an unnamed field is still a field if the counter rose."""
    from hivemind.brain.fieldnotes import trip_arrived
    assert trip_arrived(120_000, None, 40) is True


def test_a_walked_pattern_that_gathered_nothing_did_not_arrive():
    """MEASURED 2026-09-22 05:07: 'to sunflower: left the hive, arrival
    unconfirmed', then 'I am nowhere I can confirm' with the backpack flat at
    5%. You cannot walk a gathering pattern in a flower field and collect
    nothing."""
    from hivemind.brain.fieldnotes import trip_arrived
    assert trip_arrived(0, None, 7) is False


def test_an_unreadable_counter_concludes_nothing():
    """A guess recorded as a failure would ban a field that may be fine."""
    from hivemind.brain.fieldnotes import trip_arrived
    assert trip_arrived(None, None, 7) is None


def test_a_trip_that_never_gathered_concludes_nothing():
    from hivemind.brain.fieldnotes import trip_arrived
    assert trip_arrived(0, None, 0) is None


# --- what a trip proves about the route it walked -------------------------

def test_reaching_no_field_blames_the_route():
    from hivemind.brain.fieldnotes import verdict_for_aim
    assert verdict_for_aim("sunflower", None, 0, 7) == "failed"


def test_reaching_the_field_it_aimed_at_forgives_the_route():
    from hivemind.brain.fieldnotes import verdict_for_aim
    assert verdict_for_aim("dandelion", "dandelion", 200_000, 40) == "arrived"


def test_landing_a_field_over_is_not_this_functions_call():
    """REGRESSION, and it would have cancelled the other half of the system.

    `nav.journey.wrong_place` already rules on a trip credited elsewhere, and
    it has a veto: a trip that PAID is not a failure, which is what saved
    378,000 honey an hour once. Returning "arrived" here would reset the
    failure wrong_place had just recorded; "failed" would double-count it.
    """
    from hivemind.brain.fieldnotes import verdict_for_aim
    assert verdict_for_aim("sunflower", "dandelion", 460_000, 86) is None


def test_a_route_that_comes_back_full_is_worth_walking_again(): 
    """CHANGED ON MEASUREMENT. This asserted None, which would have banned a
    route that works.

    MEASURED 2026-09-22 05:33: the route named for Sunflower delivered
    442,156 pollen over 76 passes with the reward feed silent throughout.
    `travel_failures` counts trips that got NOWHERE in a row, so leaving the
    counter untouched on a route's good trips while its bad ones kept
    incrementing it would ban a route that works half the time.
    """
    from hivemind.brain.fieldnotes import verdict_for_aim
    assert verdict_for_aim("sunflower", None, 442_156, 76) == "arrived"


def test_a_good_trip_clears_the_failures_a_bad_one_recorded():
    """The counter means "in a row", which is the whole point of resetting."""
    from hivemind.brain.fieldnotes import verdict_for_aim

    notes = FieldNotes()
    notes.travel_failed("sunflower")
    assert notes.known("sunflower").travel_failures == 1

    assert verdict_for_aim("sunflower", None, 442_156, 76) == "arrived"
    notes.arrived("sunflower")

    assert notes.known("sunflower").travel_failures == 0


def test_an_unreadable_counter_proves_nothing_about_this_route():
    from hivemind.brain.fieldnotes import verdict_for_aim
    assert verdict_for_aim("sunflower", None, None, 40) is None


def test_a_trip_with_no_aim_recorded_says_nothing():
    """A convert-only cycle never travelled."""
    from hivemind.brain.fieldnotes import verdict_for_aim
    assert verdict_for_aim(None, None, None, 0) is None


def test_enough_dead_trips_in_a_row_reach_the_give_up_threshold():
    """Dead trips accumulate until `decide.TRAVEL_FAILURES_TO_GIVE_UP`.

    The threshold itself is read rather than hardcoded here: it was raised
    from 2 to 4 on 2026-09-22 after two-in-a-row banned Dandelion thirteen
    minutes after that same route delivered 418,434 pollen, leaving the bot
    with no field it could reach.
    """
    from hivemind.brain.decide import TRAVEL_FAILURES_TO_GIVE_UP
    from hivemind.brain.fieldnotes import verdict_for_aim

    notes = FieldNotes()
    for _ in range(TRAVEL_FAILURES_TO_GIVE_UP):
        assert verdict_for_aim("sunflower", None, 0, 7) == "failed"
        notes.travel_failed("sunflower")

    assert notes.known("sunflower").travel_failures >= TRAVEL_FAILURES_TO_GIVE_UP


def test_one_good_trip_short_of_the_threshold_clears_it():
    """The ban is one-way once it lands -- a banned field is never chosen, so
    it can never earn the success that would clear it. That asymmetry is why
    the threshold is generous, and why a success before it must reset fully.
    """
    from hivemind.brain.decide import TRAVEL_FAILURES_TO_GIVE_UP
    from hivemind.brain.fieldnotes import verdict_for_aim

    notes = FieldNotes()
    for _ in range(TRAVEL_FAILURES_TO_GIVE_UP - 1):
        notes.travel_failed("dandelion")

    assert verdict_for_aim("dandelion", None, 418_434, 88) == "arrived"
    notes.arrived("dandelion")

    assert notes.known("dandelion").travel_failures == 0


# --- the walk home is a separate record from the walk out -----------------
# MEASURED 2026-09-22 over runs 120-169: the walk home succeeded 0 times out
# of 52, at about a minute a failure. Ten of the seventeen return paths had
# never been tried (skipped for branching per hive slot until that morning),
# so the attempt is counted per field rather than abandoned wholesale.

def test_the_way_back_is_counted_separately_from_the_way_there():
    """A route out that works says nothing about the route back, and on this
    account the two have completely different records."""
    notes = FieldNotes()

    notes.home_failed("dandelion")
    notes.arrived("dandelion")          # the way THERE is fine

    assert notes.known("dandelion").home_failures == 1, \
        "arriving at a field forgave the walk home, which it knows nothing about"
    assert notes.known("dandelion").travel_failures == 0


def test_a_walk_home_that_lands_forgives_the_failures():
    notes = FieldNotes()
    for _ in range(3):
        notes.home_failed("rose")

    notes.walked_home("rose")

    assert notes.known("rose").home_failures == 0


def test_home_failures_survive_a_restart():
    """The bot restarts every cycle; a count that resets each time can never
    reach the threshold. Same lesson as the heading search."""
    import json, tempfile, pathlib
    notes = FieldNotes()
    notes.home_failed("pine_tree")
    notes.home_failed("pine_tree")
    path = pathlib.Path(tempfile.mkdtemp()) / "notes.json"
    notes.save(path)

    after = FieldNotes()
    after.load(path)

    assert after.known("pine_tree").home_failures == 2


def test_an_unnamed_field_records_nothing():
    """Same rule as everywhere else here: never file under a placeholder."""
    notes = FieldNotes()

    assert notes.home_failed(None) is None
    assert notes.walked_home("") is None
    assert notes.notes == {}


# ---- the sight homing's own record ------------------------------------------------

def test_sight_failures_are_counted_apart_from_the_routes_and_forgiven_on_success(tmp_path):
    """MEASURED 2026-09-22: homing by sight landed once in nine attempts and
    each failure costs ~40 s of looking. It gets its own count so a field
    where it never works can skip straight to the rejoin."""
    notes = FieldNotes()
    notes.home_failed("dandelion")
    notes.sight_failed("dandelion")
    notes.sight_failed("dandelion")
    note = notes.known("dandelion")
    assert (note.home_failures, note.sight_failures) == (1, 2)

    notes.sighted_home("dandelion")
    assert notes.known("dandelion").sight_failures == 0
    assert notes.known("dandelion").home_failures == 1, "the route's record is its own"

    notes.sight_failed("dandelion")
    path = notes.save(tmp_path / "notes.json")
    again = FieldNotes()
    again.load(path)
    assert again.known("dandelion").sight_failures == 1


def test_a_walk_home_that_lands_forgives_both_counts(tmp_path):
    notes = FieldNotes()
    notes.home_failed("cactus")
    notes.sight_failed("cactus")
    notes.walked_home("cactus")
    notes.sighted_home("cactus")
    note = notes.known("cactus")
    assert (note.home_failures, note.sight_failures) == (0, 0)


def test_neither_counter_needs_a_field(tmp_path):
    notes = FieldNotes()
    assert notes.sight_failed(None) is None and notes.sighted_home("") is None


# ---- a field is priced over the seconds its pollen was measured in ----------
# MEASURED 2026-09-23 02:45: the Rose trip gathered 986,128 pollen in 968 s --
# 1,019/s, the best this account has recorded -- and the notes called Rose a
# 398 pollen/s field. `note()` credited every sampled second but could only
# credit a pollen GAIN when both ends of the interval were legible, and the
# counter is illegible above a million.

def test_seconds_with_an_unreadable_counter_do_not_dilute_the_rate():
    """Forty legible ten-second intervals at 1,000/s, then a long illegible
    stretch. The rate is 1,000/s, not the 500/s the whole clock would say.

    THE LEGIBLE RUN IS 400 s ON PURPOSE -- past `PAID_ENOUGH_SECONDS`. Below
    that the paid pair is not used at all, because a pair resting on a few
    intervals can hold a whole token pickup, or one hot stint, and price a
    field far above anything real. The same 2026-09-23 measurements that
    justify not diluting (Rose, 1,019/s read as 398) also justify the floor
    (Cactus at 1,875/s from 3 s; Pine Tree at 1,491/s from 76 s). Both facts
    are real, and this is the scale at which the first one can be trusted.
    """
    ticks = iter([float(t) for t in range(0, 1_000, 10)])
    notes = FieldNotes(clock=lambda: next(ticks))
    for i in range(41):                       # t=0..400, +10,000 per 10 s
        notes.note("rose", i * 10_000)
    for _ in range(40):                       # t=410..800, unreadable
        notes.note("rose", None)
    note = notes.known("rose")
    assert note.pollen == 400_000
    assert note.paid_pollen == 400_000
    assert note.seconds == pytest.approx(800.0), "every second here still counts for deaths"
    assert note.paid_seconds == pytest.approx(400.0)
    assert note.rate == pytest.approx(1_000.0), "not 500/s"


def test_a_few_paid_seconds_cannot_price_a_field():
    """MEASURED 2026-09-23 03:05: a three-second visit to Cactus recorded
    5,625 pollen -- one token pickup inside one interval -- and priced the
    field at 1,875 pollen/s, seven times the best rate this account has ever
    recorded. Under the floor the field is priced over its whole time
    instead, which is a number no single pickup can run away with."""
    ticks = iter([0.0, 1.5, 3.0, 100.0])
    notes = FieldNotes(clock=lambda: next(ticks))
    notes.note("cactus", 0)
    notes.note("cactus", 5_625)       # one interval, one pickup
    notes.note("cactus", 5_625)
    note = notes.known("cactus")
    assert note.paid_pollen == 5_625 and note.paid_seconds == pytest.approx(3.0)
    assert note.rate == pytest.approx(note.pollen / note.seconds)
    assert note.rate < 2_000, f"one pickup priced the field at {note.rate:.0f}/s"


def test_paid_seconds_written_without_paid_pollen_are_not_trusted(tmp_path):
    """MEASURED 2026-09-23 03:20, from the live var/field_notes.json: the
    Dandelion note held 5,212,881 pollen against 1,005 paid seconds and so
    priced itself at 5,186 pollen/s, because `paid_seconds` had shipped on
    its own and was being divided into a numerator covering 23,482 seconds.
    A file like that cannot say which pollen those seconds bought, so it is
    read as having no paid measurement at all."""
    import json
    body = {"fields": {"dandelion": {"field": "dandelion", "pollen": 5_212_881,
                                     "seconds": 23_482.0, "paid_seconds": 1_005.0,
                                     "visits": 60, "proven": True}}}
    path = tmp_path / "field_notes.json"
    path.write_text(json.dumps(body))
    notes = FieldNotes()
    notes.load(path)
    note = notes.known("dandelion")
    assert note.paid_seconds == 0.0 and note.paid_pollen == 0
    assert note.rate == pytest.approx(5_212_881 / 23_482.0)
    assert note.rate < 300, f"priced at {note.rate:.0f}/s, the old bug said 5,186"


def test_the_death_rate_still_uses_every_second_spent_there():
    ticks = iter([0.0, 10.0, 20.0, 30.0])
    notes = FieldNotes(clock=lambda: next(ticks))
    notes.note("rose", 0)
    notes.note("rose", None)
    notes.note("rose", None)
    notes.died("rose")
    note = notes.known("rose")
    assert note.seconds == pytest.approx(20.0)
    assert note.death_rate == pytest.approx(1 / 20.0)


def test_a_field_with_no_measured_interval_falls_back_to_its_whole_time():
    """Better a diluted rate than none: a field whose counter was never
    legible still ranks on something rather than reading as zero."""
    ticks = iter([0.0, 10.0, 20.0])
    notes = FieldNotes(clock=lambda: next(ticks))
    notes.note("rose", 5_000)
    notes.note("rose", None)
    note = notes.known("rose")
    assert note.paid_seconds == 0.0 and note.seconds > 0
    assert note.rate == 0.0, "no gain was ever measured, so there is no rate to claim"


def test_paid_seconds_survive_a_restart(tmp_path):
    ticks = iter([0.0, 10.0, 20.0])
    notes = FieldNotes(clock=lambda: next(ticks))
    notes.note("rose", 0)
    notes.note("rose", 10_000)
    path = notes.save(tmp_path / "notes.json")
    again = FieldNotes()
    again.load(path)
    assert again.known("rose").paid_seconds == pytest.approx(10.0)
    assert again.known("rose").rate == pytest.approx(1_000.0)


# ---- the notes survive a crash mid-write -----------------------------------
# `var/night/MORNING.md`, 2026-09-23: 249 runs started, 12 ended in a
# traceback. A direct write truncates first and fills second, so a kill in
# between leaves half a JSON file -- and `load` catching the parse error makes
# that loss look exactly like a fresh account.

def test_a_failed_write_leaves_the_old_notes_intact(tmp_path, monkeypatch):
    path = tmp_path / "field_notes.json"
    first = FieldNotes()
    first.notes["rose"] = Note(field="rose", pollen=500_000, seconds=1_000.0,
                               visits=3, proven=True)
    first.save(path)
    before = path.read_text()

    second = FieldNotes()
    second.notes["rose"] = Note(field="rose", pollen=999, seconds=1.0)
    real_replace = pathlib.Path.replace

    def die(self, target):
        raise OSError("killed between the write and the rename")

    monkeypatch.setattr(pathlib.Path, "replace", die)
    with pytest.raises(OSError):
        second.save(path)
    monkeypatch.setattr(pathlib.Path, "replace", real_replace)

    assert path.read_text() == before, "the old notes were damaged"
    back = FieldNotes()
    back.load(path)
    assert back.known("rose").pollen == 500_000


def test_writing_twice_leaves_no_litter(tmp_path):
    path = tmp_path / "field_notes.json"
    notes = FieldNotes()
    notes.notes["rose"] = Note(field="rose", pollen=1, seconds=1.0)
    notes.save(path)
    notes.save(path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["field_notes.json"]


# ---- a route that lands somewhere else left no trace -----------------------
# MEASURED 2026-09-23 over runs 280-309, nine trips aimed at the Spider Field:
# five were credited spider (935 pollen/s), two strawberry (337/s), one
# mushroom (377/s), one sunflower (255/s). Four in nine landed somewhere worth
# a third of the target, each costing about 670,000 pollen over a 1,050-second
# trip -- and nothing recorded it. `verdict_for_aim` returns None so it does
# not double-count, and `nav.journey.wrong_place` refuses to blame the pose
# because the trip earned. Between them the route kept a clean sheet.

def test_a_miss_is_recorded_against_the_field_it_aimed_at():
    notes = FieldNotes()
    notes.missed_it("spider")
    notes.missed_it("spider")
    assert notes.known("spider").missed == 2


def test_a_miss_is_not_a_travel_failure():
    """The field is fine; the ROUTE mis-delivers. A miss must never bar a
    field, or the best field on the board would be struck off for having a
    bad flight."""
    from hivemind.brain.decide import TRAVEL_FAILURES_TO_GIVE_UP
    notes = FieldNotes()
    for _ in range(TRAVEL_FAILURES_TO_GIVE_UP * 2):
        notes.missed_it("spider")
    assert notes.known("spider").travel_failures == 0


def test_a_miss_flips_the_route_the_next_trip_takes():
    """The whole point: Spider's cannon route mis-delivered four times in
    nine and `travel_failures` stayed 0, so the walking route was never
    tried."""
    from hivemind.nav.router import fly_this_time
    notes = FieldNotes()
    note = notes.notes.setdefault("spider", Note(field="spider"))
    before = fly_this_time(note.travel_failures + note.missed)
    notes.missed_it("spider")
    after = fly_this_time(note.travel_failures + note.missed)
    assert before != after, "a mis-delivery changed nothing"


def test_misses_survive_a_save_and_load(tmp_path):
    path = tmp_path / "field_notes.json"
    notes = FieldNotes()
    notes.missed_it("spider")
    notes.missed_it("spider")
    notes.missed_it("spider")
    notes.save(path)
    back = FieldNotes()
    back.load(path)
    assert back.known("spider").missed == 3


def test_missing_nothing_is_not_an_error():
    notes = FieldNotes()
    notes.missed_it("")
    notes.missed_it(None)
    assert not notes.notes


# --- strikes earned against old route data are not carried over --------------
# The walk-home counters stop a recorded route being run after three failures
# in a row. When the routes themselves change generation, the strikes were
# earned against something that no longer exists. See HOME_DATA_VERSION.

def test_home_strikes_from_an_older_route_generation_are_forgiven(tmp_path):
    import json
    from hivemind.brain.fieldnotes import FieldNotes
    old = {"fields": {"spider": {"seconds": 600.0, "pollen": 500000, "visits": 3,
                                 "samples": 30, "proven": True, "deaths": 1,
                                 "travel_failures": 2, "missed": 0,
                                 "home_failures": 3, "sight_failures": 3,
                                 "paid_seconds": 300.0, "paid_pollen": 250000,
                                 "petals": {}, "saw": []}},
           "unattributed": 0,
           # FALSE_DEATHS already given back, so the one death here is real
           "false_deaths_removed": sorted(__import__(
               "hivemind.brain.fieldnotes", fromlist=["FALSE_DEATHS"]).FALSE_DEATHS)}
    path = tmp_path / "old.json"
    path.write_text(json.dumps(old))
    notes = FieldNotes()
    assert notes.load(path) == 1
    note = notes.known("spider")
    assert note.home_failures == 0 and note.sight_failures == 0
    assert notes.forgave_home_failures == ["spider"]
    # everything else survived: the strikes were the only thing in question
    assert note.pollen == 500000 and note.deaths == 1 and note.travel_failures == 2


def test_home_strikes_from_the_current_generation_are_kept(tmp_path):
    from hivemind.brain.fieldnotes import FieldNotes
    notes = FieldNotes()
    notes.home_failed("spider")
    notes.home_failed("spider")
    notes.sight_failed("spider")
    path = notes.save(tmp_path / "current.json")
    fresh = FieldNotes()
    fresh.load(path)
    assert fresh.known("spider").home_failures == 2
    assert fresh.known("spider").sight_failures == 1
    assert fresh.forgave_home_failures == []


def test_the_saved_file_names_its_route_generation(tmp_path):
    import json
    from hivemind.brain.fieldnotes import HOME_DATA_VERSION, FieldNotes
    path = FieldNotes().save(tmp_path / "v.json")
    assert json.loads(path.read_text())["home_data_version"] == HOME_DATA_VERSION


# --- the HUD's own (+N/sec), kept as its own channel ---------------------------
# MEASURED 2026-09-23: it runs 8-30% below the counter's movement (tokens land
# in the counter as lumps), so it is a lower bound and never replaces a paid
# pair -- but it is exact where the counter is illegible, and it needs no
# pair of legible readings a known time apart.

def test_the_printed_rate_needs_enough_readings_before_it_is_a_number():
    from hivemind.brain.fieldnotes import PRINTED_ENOUGH_SAMPLES, FieldNotes
    notes = FieldNotes()
    for _ in range(PRINTED_ENOUGH_SAMPLES - 1):
        notes.saw_rate("spider", 740)
    assert notes.known("spider").printed_rate is None
    notes.saw_rate("spider", 760)
    assert abs(notes.known("spider").printed_rate - (740 * 59 + 760) / 60) < 1e-6


def test_a_printed_rate_is_only_ever_credited_with_a_fix():
    from hivemind.brain.fieldnotes import FieldNotes
    notes = FieldNotes()
    assert notes.saw_rate(None, 700) is None
    assert notes.saw_rate("spider", None) is None
    assert notes.saw_rate("spider", -5) is None
    assert notes.known("spider") is None


def test_the_printed_rate_survives_a_save_and_load(tmp_path):
    from hivemind.brain.fieldnotes import FieldNotes
    notes = FieldNotes()
    for _ in range(70):
        notes.saw_rate("spider", 750)
    path = notes.save(tmp_path / "n.json")
    fresh = FieldNotes()
    fresh.load(path)
    assert fresh.known("spider").printed_samples == 70
    assert abs(fresh.known("spider").printed_rate - 750) < 1e-6


def test_a_fixed_routes_trips_that_never_arrived_are_given_back_once(tmp_path):
    # Cactus's flight landed short of its ledge on every kept flight and the
    # planner gave it up at 4; its route was fixed (transpile_natro LANDINGS)
    import json as _json
    from hivemind.brain.fieldnotes import FieldNotes
    path = tmp_path / "field_notes.json"
    old = FieldNotes()
    for _ in range(4):
        old.travel_failed("cactus")
    old.save(path)
    body = _json.loads(path.read_text())
    body.pop("travel_failures_forgiven")          # written before the list existed
    path.write_text(_json.dumps(body))
    fresh = FieldNotes()
    fresh.load(path)
    assert fresh.known("cactus").travel_failures == 0
    assert fresh.forgave_travel and fresh.forgave_travel[0].startswith("cactus")
    for _ in range(4):                              # failing again after the fix stands
        fresh.travel_failed("cactus")
    fresh.save(path)
    again = FieldNotes()
    again.load(path)
    assert again.known("cactus").travel_failures == 4 and again.forgave_travel == []
