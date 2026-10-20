"""Choosing a field, and being able to say why. See brain/decide.py."""
from __future__ import annotations

import pathlib

import pytest

from hivemind.brain.decide import (WORTH_PROTECTING, Planner, Situation,
                                   load_fields)
from hivemind.brain.fieldnotes import FieldNotes, Note

ROOT = pathlib.Path(__file__).resolve().parents[2]

FIELDS = {
    "sunflower":  {"bees_required": 0,  "flowers": 660, "mobs": [], "safe": True},
    "pine_tree":  {"bees_required": 15, "flowers": 713, "safe": False,
                   "mobs": ["mantis", "mantis", "werewolf"]},
    "pineapple":  {"bees_required": 10, "flowers": 759, "safe": False,
                   "mobs": ["mantis"]},
    "pepper":     {"bees_required": 35, "flowers": 567, "mobs": [], "safe": True},
}
REACH = {"sunflower", "pine_tree", "pineapple", "pepper"}


def planner(notes=None, reachable=REACH, **kw):
    return Planner(FIELDS, notes, reachable=reachable, **kw)


def proven(*fields):
    notes = FieldNotes()
    for name in fields:
        notes.notes[name] = Note(field=name, proven=True, visits=1)
    return notes


# ---- progression, derived from evidence ----------------------------------
def test_nothing_gathered_proves_no_bees():
    assert planner(FieldNotes()).bees_at_least() == 0


def test_gathering_somewhere_proves_its_bee_requirement():
    """The owner asked for a bot that works out its own progress. Earning in
    a field that needs 15 bees IS the proof of 15 bees."""
    assert planner(proven("pine_tree")).bees_at_least() == 15


def test_the_proof_is_the_highest_requirement_reached():
    assert planner(proven("pineapple", "pine_tree")).bees_at_least() == 15


def test_a_measured_rate_also_proves_it():
    notes = FieldNotes()
    notes.notes["pine_tree"] = Note(field="pine_tree", pollen=500, seconds=10.0, paid_pollen=500, paid_seconds=10.0)
    assert planner(notes).bees_at_least() == 15


# ---- the rule that cost 361,439 pollen -----------------------------------
def test_a_loaded_backpack_is_banked_before_a_guarded_trip():
    """THE FIX FOR 2026-09-20. The bot carried the owner's own 362,208 pollen
    to a field with two mantises in it and lost all of it."""
    p = planner(proven("pine_tree"), reachable={"pine_tree", "pineapple"})
    decision = p.decide(Situation(pollen=362_208, capacity=957_375))
    assert decision.action == "convert"
    assert "362,208" in decision.why


def test_an_empty_backpack_will_risk_a_guarded_field():
    """With nothing to lose the flowers are worth the mobs."""
    p = planner(proven("pine_tree"), reachable={"pine_tree", "pineapple"})
    decision = p.decide(Situation(pollen=0, capacity=957_375))
    assert decision.action == "gather"
    assert decision.field in {"pine_tree", "pineapple"}


def test_a_safe_field_is_taken_even_with_a_full_load():
    p = planner(proven("pine_tree"))
    decision = p.decide(Situation(pollen=362_208, capacity=957_375))
    assert decision.action == "gather" and decision.field == "sunflower"


def test_a_full_backpack_always_converts():
    p = planner(proven("pine_tree"))
    decision = p.decide(Situation(pollen=900_000, capacity=957_375))
    assert decision.action == "convert" and "full" in decision.why


def test_the_threshold_is_where_the_behaviour_changes():
    p = planner(proven("pine_tree"), reachable={"pine_tree"})
    under = p.decide(Situation(pollen=WORTH_PROTECTING - 1, capacity=900_000))
    over = p.decide(Situation(pollen=WORTH_PROTECTING, capacity=900_000))
    assert under.action == "gather"
    assert over.action == "convert"


# ---- not choosing places it cannot reach ---------------------------------
def test_a_field_with_no_route_is_never_chosen():
    """REGRESSION. The planner first chose the Sunflower Field -- safe, 660
    flowers, no bees needed, and NO RECORDED ROUTE FROM THE HIVE."""
    p = planner(proven("pine_tree"), reachable={"pine_tree", "pineapple"})
    decision = p.decide(Situation(pollen=0, capacity=900_000))
    assert decision.field != "sunflower"
    sun = next(s for s in decision.alternatives if s.field == "sunflower")
    assert sun.score == 0 and "no recorded route" in sun.why


def test_a_field_beyond_our_bees_is_never_chosen():
    p = planner(proven("pineapple"))
    decision = p.decide(Situation(pollen=0, capacity=900_000))
    assert decision.field != "pepper"
    pepper = next(s for s in decision.alternatives if s.field == "pepper")
    assert "35" in pepper.why


def test_nowhere_to_go_and_pollen_in_hand_means_convert():
    p = planner(proven("pine_tree"), reachable=set())
    decision = p.decide(Situation(pollen=5_000, capacity=900_000))
    assert decision.action == "convert"


def test_nowhere_to_go_and_nothing_in_hand_means_wait():
    p = planner(proven("pine_tree"), reachable=set())
    assert p.decide(Situation(pollen=0, capacity=900_000)).action == "wait"


# ---- measured beats presumed ---------------------------------------------
def test_a_guess_is_on_the_same_scale_as_a_measurement():
    """THE SCALE BUG, kept honest under exploration. A guess used to be
    `flowers * 0.5` -- hundreds -- against a rate in pollen/s, so measuring a
    field demoted it. Now an unmeasured field may win ONE exploratory trip,
    but its score is bounded by the best measured rate, never by a flower
    count pretending to be one."""
    from hivemind.brain.decide import EXPLORE_OPTIMISM
    notes = proven("pine_tree")
    notes.notes["pine_tree"] = Note(field="pine_tree", pollen=100_000,
                                    seconds=400.0, proven=True, paid_pollen=100_000, paid_seconds=400.0)          # 250/s
    p = planner(notes, reachable={"pine_tree", "pineapple"})
    ranked = p.rank(Situation(pollen=0, capacity=900_000))
    guess = next(r for r in ranked if r.field == "pineapple")
    assert guess.rate is None
    assert guess.score <= 250 * EXPLORE_OPTIMISM, "a guess outran the best measurement"
    assert "measured" in next(r for r in ranked if r.field == "pine_tree").why


def test_an_unmeasured_field_never_claims_a_rate():
    ranked = planner(FieldNotes()).rank(Situation(pollen=0, capacity=900_000))
    for score in ranked:
        if score.rate is None:
            assert "pollen/s" not in score.why


# ---- it can explain itself ------------------------------------------------
def test_every_decision_carries_its_reasoning():
    p = planner(proven("pine_tree"))
    decision = p.decide(Situation(pollen=0, capacity=900_000))
    assert decision.why and decision.alternatives
    assert all(s.why for s in decision.alternatives)


def test_explain_reads_like_a_person_wrote_it():
    p = planner(proven("pine_tree"))
    text = p.explain(Situation(pollen=362_208, capacity=957_375))
    assert "decision:" in text and "proved at least 15 bees" in text


def test_unknown_pollen_is_not_treated_as_empty():
    """An unreadable HUD must never look like an empty backpack."""
    p = planner(proven("pine_tree"), reachable={"pine_tree"})
    decision = p.decide(Situation(pollen=None, capacity=957_375))
    assert decision.action in {"gather", "convert", "wait"}


# ---- against the real shipped data ---------------------------------------
def test_the_real_knowledge_base_loads_and_ranks():
    fields = load_fields(ROOT / "data/knowledge/world.yaml")
    assert len(fields) == 17
    p = Planner(fields, proven("mountain_top"),
                reachable={"pine_tree", "pineapple", "pumpkin", "strawberry"})
    assert p.bees_at_least() == 25
    decision = p.decide(Situation(pollen=362_208, capacity=957_375))
    assert decision.action == "convert", \
        "with a loaded backpack and only guarded fields reachable, bank it"


# ---- learning which fields actually kill this character -------------------
# The wiki's mob list is the same for everyone. The death rate is ours, and it
# is the number that matters: one death costs the entire backpack, measured at
# 445,029 pollen on a single trip.
class _Note:
    def __init__(self, pollen=0, seconds=0.0, deaths=0, proven=True):
        self.pollen = pollen
        self.seconds = seconds
        self.deaths = deaths
        self.proven = proven

    @property
    def rate(self):
        return self.pollen / self.seconds if self.seconds else 0.0

    @property
    def pays(self):
        return self.pollen > 0

    @property
    def been_here(self):
        return self.proven or self.pays

    def survival_over(self, seconds):
        import math
        rate = self.deaths / self.seconds if self.seconds else 0.0
        return 1.0 if rate <= 0 or seconds <= 0 else math.exp(-rate * seconds)


class _Notes:
    def __init__(self, mapping):
        self.notes = mapping

    def known(self, field):
        return self.notes.get(field)


def _two_field_planner(deaths_in_deadly):
    from hivemind.brain.decide import Planner
    fields = {
        "safe_field": {"flowers": 700, "safe": False, "mobs": ["ladybug"],
                       "bees_required": 0},
        "deadly": {"flowers": 700, "safe": False, "mobs": ["mantis"],
                   "bees_required": 0},
    }
    notes = _Notes({
        "safe_field": _Note(pollen=100_000, seconds=1000.0, deaths=0),
        "deadly": _Note(pollen=100_000, seconds=1000.0,
                        deaths=deaths_in_deadly),
    })
    return Planner(fields, notes, trip_seconds=420.0)


def test_two_equal_fields_rank_equally_when_neither_has_killed_us():
    planner = _two_field_planner(0)
    scored = {s.field: s.score for s in planner.rank(Situation(pollen=0))}
    assert scored["safe_field"] == scored["deadly"]


def test_a_field_that_has_killed_us_is_worth_less_than_an_identical_one():
    planner = _two_field_planner(2)
    scored = {s.field: s.score for s in planner.rank(Situation(pollen=0))}
    assert scored["deadly"] < scored["safe_field"]


def test_the_ranking_says_out_loud_that_it_died_there():
    planner = _two_field_planner(2)
    deadly = [s for s in planner.rank(Situation(pollen=0))
              if s.field == "deadly"][0]
    assert "died here 2 times" in deadly.why


def test_carrying_a_lot_refuses_a_field_that_has_already_killed_us():
    planner = _two_field_planner(1)
    deadly = [s for s in planner.rank(Situation(pollen=500_000))
              if s.field == "deadly"][0]
    assert deadly.score == 0.0
    assert "not worth it" in deadly.why


# ---- how long to stay in a field -----------------------------------------
# Replaces BeeTuxMacro's FARM_SECONDS=420, which MEASURED was ending trips at
# 47% of a backpack while paying the full round trip every time.
def test_a_field_that_has_never_killed_us_is_farmed_until_the_backpack_is_full():
    from hivemind.brain.decide import best_trip_seconds
    assert best_trip_seconds(overhead_seconds=108, death_rate=0.0,
                             fill_seconds=820) == 820


def test_with_no_deaths_and_no_fill_estimate_it_stops_at_the_hard_ceiling():
    from hivemind.brain.decide import LONGEST_TRIP_SECONDS, best_trip_seconds
    assert best_trip_seconds(108, 0.0, None) == LONGEST_TRIP_SECONDS


def test_a_deadly_field_earns_a_short_raid_not_a_long_trip():
    from hivemind.brain.decide import best_trip_seconds
    safe = best_trip_seconds(108, 0.0, 820)
    risky = best_trip_seconds(108, 1 / 500, 820)
    lethal = best_trip_seconds(108, 1 / 100, 820)
    assert lethal < risky < safe


def test_the_deadlier_the_field_the_shorter_the_trip():
    from hivemind.brain.decide import best_trip_seconds
    lengths = [best_trip_seconds(108, rate, 2000)
               for rate in (1 / 2000, 1 / 1000, 1 / 500, 1 / 200)]
    assert lengths == sorted(lengths, reverse=True)


def test_a_trip_is_never_shorter_than_a_minute():
    from hivemind.brain.decide import best_trip_seconds
    # Even somewhere appalling, a trip that cannot outlast its own travel time
    # is not a plan -- the caller should be choosing a different field, and
    # that is the planner's job, not this function's.
    assert best_trip_seconds(108, 1.0, 820) >= 60.0


def test_a_bigger_round_trip_justifies_a_longer_stay():
    from hivemind.brain.decide import best_trip_seconds
    near = best_trip_seconds(60, 1 / 500, 2000)
    far = best_trip_seconds(240, 1 / 500, 2000)
    assert far > near


# ---- quests changing where it stands -------------------------------------
# The owner asked for quests to work. Two of their three quests want a
# specific colour of pollen; where the bot stands is how they get done.
class _ColourNote(_Note):
    def __init__(self, petals=None, **kw):
        super().__init__(**kw)
        self.petals = dict(petals or {})

    @property
    def looked_at_flowers(self):
        return sum(self.petals.values()) > 0

    def colour_share(self, colour):
        total = sum(self.petals.values())
        return None if total <= 0 else self.petals.get(colour, 0) / total


def _quest_planner(needs, blue_petals, red_petals, unmeasured=False):
    from hivemind.brain.decide import Planner
    fields = {
        "bluish": {"flowers": 700, "safe": True, "bees_required": 0},
        "reddish": {"flowers": 700, "safe": True, "bees_required": 0},
    }
    notes = _Notes({
        "bluish": _ColourNote(pollen=100_000, seconds=1000.0,
                              petals={} if unmeasured else blue_petals),
        "reddish": _ColourNote(pollen=100_000, seconds=1000.0,
                               petals={} if unmeasured else red_petals),
    })
    return Planner(fields, notes, quest_needs=needs)


def _needs(**remaining):
    from hivemind.brain.questneeds import Need, Needs
    got = Needs()
    for colour, owed in remaining.items():
        got.pollen[colour] = Need(colour=colour, target=owed, done=0)
    return got


def test_a_quest_for_blue_pollen_favours_the_field_with_blue_flowers():
    planner = _quest_planner(_needs(blue=500_000),
                             {"blue": 80, "white": 20},
                             {"red": 80, "white": 20})
    scored = {s.field: s.score for s in planner.rank(Situation(pollen=0))}
    assert scored["bluish"] > scored["reddish"]


def test_the_ranking_says_why_a_quest_moved_it():
    planner = _quest_planner(_needs(blue=500_000),
                             {"blue": 80, "white": 20},
                             {"red": 80, "white": 20})
    bluish = [s for s in planner.rank(Situation(pollen=0))
              if s.field == "bluish"][0]
    assert "quests still want" in bluish.why


def test_a_field_nobody_has_looked_at_gets_no_credit_and_no_penalty():
    planner = _quest_planner(_needs(blue=500_000), {}, {}, unmeasured=True)
    scored = {s.field: s.score for s in planner.rank(Situation(pollen=0))}
    assert scored["bluish"] == scored["reddish"]


def test_with_no_quests_read_nothing_changes():
    """THE TWO FIELDS SHARE A COLOUR MIX ON PURPOSE. Since the owner's note
    of 2026-09-23 the colour of a field's petals moves its score on its own
    (COLOUR_WORTH), so giving these two different mixes would make them
    differ for a reason that has nothing to do with quests, which is what
    this test is about."""
    planner = _quest_planner(None, {"blue": 80}, {"blue": 80})
    scored = {s.field: s.score for s in planner.rank(Situation(pollen=0))}
    assert scored["bluish"] == scored["reddish"]


def test_a_completed_quest_stops_tilting_the_ranking():
    """Same colour mix on both, for the reason in the test above: the petals
    move a score on their own now, and this is about the quest."""
    planner = _quest_planner(_needs(), {"blue": 80}, {"blue": 80})
    scored = {s.field: s.score for s in planner.rank(Situation(pollen=0))}
    assert scored["bluish"] == scored["reddish"]


def test_a_quest_tilts_but_never_overrides_a_real_rate_difference():
    from hivemind.brain.decide import Planner
    fields = {"fast_wrong_colour": {"flowers": 700, "safe": True,
                                    "bees_required": 0},
              "slow_right_colour": {"flowers": 700, "safe": True,
                                    "bees_required": 0}}
    notes = _Notes({
        # Three times the rate, entirely the wrong colour.
        "fast_wrong_colour": _ColourNote(pollen=300_000, seconds=1000.0,
                                         petals={"white": 100}),
        "slow_right_colour": _ColourNote(pollen=100_000, seconds=1000.0,
                                         petals={"blue": 100}),
    })
    planner = Planner(fields, notes, quest_needs=_needs(blue=900_000))
    best = planner.rank(Situation(pollen=0))[0]
    assert best.field == "fast_wrong_colour"


def test_a_quest_naming_a_field_counts_without_any_flower_measurement():
    """"Collect 150,000 Pollen from the Strawberry Field" is satisfied by
    standing there, whatever colour its flowers are -- and the bot may never
    have looked at them."""
    from hivemind.brain.decide import Planner
    from hivemind.brain.questneeds import Need, Needs
    needs = Needs()
    needs.fields["strawberry"] = Need(colour="strawberry", target=150_000)
    fields = {"strawberry": {"flowers": 700, "safe": True, "bees_required": 0},
              "other": {"flowers": 700, "safe": True, "bees_required": 0}}
    notes = _Notes({"strawberry": _ColourNote(pollen=100_000, seconds=1000.0),
                    "other": _ColourNote(pollen=100_000, seconds=1000.0)})
    planner = Planner(fields, notes, quest_needs=needs)
    scored = {s.field: s.score for s in planner.rank(Situation(pollen=0))}
    assert scored["strawberry"] > scored["other"]
    row = [s for s in planner.rank(Situation(pollen=0))
           if s.field == "strawberry"][0]
    assert "from here specifically" in row.why


# ---- exploration: the bug that farmed one field all night -----------------
def _measured(name, rate, seconds):
    n = Note(field=name, seconds=seconds, pollen=int(rate * seconds), visits=1,
             proven=True, paid_pollen=int(rate * seconds), paid_seconds=seconds)
    return n


def _night_of_0920():
    """The exact shape of 2026-09-20: pineapple measured, strawberry not."""
    fields = {
        "pineapple":  {"bees_required": 0, "flowers": 759, "safe": False,
                       "mobs": ["mantis", "rhino_beetle"]},
        "strawberry": {"bees_required": 0,  "flowers": 572, "safe": False,
                       "mobs": ["ladybug", "ladybug"]},
    }
    notes = FieldNotes()
    notes.notes["pineapple"] = _measured("pineapple", 252.0, 22_772.0)
    return fields, notes


def test_an_unmeasured_reachable_field_wins_one_trip():
    """REGRESSION. 42 trips to pineapple, 0 anywhere else, while a quest
    wanted 150,000 pollen from a strawberry field it could reach."""
    fields, notes = _night_of_0920()
    p = Planner(fields, notes, reachable={"pineapple", "strawberry"})
    ranked = p.rank(Situation(pollen=0, capacity=948_750))
    assert ranked[0].field == "strawberry", [(r.field, round(r.score)) for r in ranked]
    assert "assumed as good as our best" in ranked[0].why


def test_after_one_proper_trip_the_field_stands_on_its_measurement():
    fields, notes = _night_of_0920()
    # strawberry measured for a full trip at a WORSE rate than pineapple
    notes.notes["strawberry"] = _measured("strawberry", 150.0, 400.0)
    p = Planner(fields, notes, reachable={"pineapple", "strawberry"})
    ranked = p.rank(Situation(pollen=0, capacity=948_750))
    assert ranked[0].field == "pineapple"
    assert "assumed as good as" not in ranked[1].why
    assert "worth finishing" not in ranked[1].why


def test_a_half_measured_field_is_worth_finishing_only_if_it_looks_worse():
    fields, notes = _night_of_0920()
    # 150 s at a poor rate: optimism (252 * 1.1 * 0.5 = 138.6) beats the
    # measured 100, so it is still worth finishing the measurement
    notes.notes["strawberry"] = _measured("strawberry", 100.0, 150.0)
    p = Planner(fields, notes, reachable={"pineapple", "strawberry"})
    s = next(r for r in p.rank(Situation(pollen=0)) if r.field == "strawberry")
    assert "worth finishing" in s.why
    assert 100 < s.score < 110            # 138.6 * DANGER_DISCOUNT 0.75
    # ...but a half-measured field that already looks GOOD needs no optimism
    notes.notes["strawberry"] = _measured("strawberry", 300.0, 150.0)
    s = next(r for r in p.rank(Situation(pollen=0)) if r.field == "strawberry")
    assert "worth finishing" not in s.why


def test_with_nothing_measured_anywhere_guesses_rank_by_flowers():
    """No best field means no optimism -- the old behaviour, unchanged."""
    fields, _ = _night_of_0920()
    p = Planner(fields, FieldNotes(), reachable={"pineapple", "strawberry"})
    ranked = p.rank(Situation(pollen=0))
    assert ranked[0].field == "pineapple"          # 759 flowers > 572
    assert all("assumed as good as" not in r.why for r in ranked)


def test_curiosity_never_overrides_the_backpack_rule():
    """Carrying a lot into a guarded field is still refused, bonus or not."""
    fields, notes = _night_of_0920()
    p = Planner(fields, notes, reachable={"pineapple", "strawberry"})
    ranked = p.rank(Situation(pollen=WORTH_PROTECTING * 4, capacity=948_750))
    s = next(r for r in ranked if r.field == "strawberry")
    assert s.score == 0.0 and "not worth the risk" in s.why


def test_curiosity_does_not_reach_a_field_with_no_route():
    fields, notes = _night_of_0920()
    p = Planner(fields, notes, reachable={"pineapple"})
    s = next(r for r in p.rank(Situation(pollen=0)) if r.field == "strawberry")
    assert s.score == 0.0 and "no recorded route" in s.why


def test_the_real_knowledge_base_no_longer_farms_one_field_forever():
    """Replay through the REAL fields file, with the real measured rate.

    It takes pineapple's actual numbers out of `var/field_notes.json` and
    leaves the rest of that file alone. That is deliberate: the file also
    carries how many trips failed to ARRIVE at each field, the bot rewrites it
    every run, and a field it has given up reaching is scored zero on purpose
    -- so reading the whole file would make this test assert last night's
    travel luck instead of the ranking rule. `test_a_field_that_cannot_be
    _reached_stops_winning` covers that half separately.

    The rule here: a field nobody has measured outranks the one with 22,772
    seconds in it, so the bot cannot settle on its first success for ever.
    MEASURED 2026-09-20, this was backwards -- it farmed the Pineapple Patch,
    recorded 170 pollen/s, and promptly ranked it below the Pine Tree Forest
    on a score of 334 that was never a rate at all.
    """
    import json
    fields = load_fields(ROOT / "data/knowledge/world.yaml")
    live = ROOT / "var/field_notes.json"
    if not live.exists():
        pytest.skip("the night's field notes are not in the repo")
    body = (json.loads(live.read_text()).get("fields") or {}).get("pineapple")
    if not body or not body.get("seconds"):
        pytest.skip("pineapple has no measured rate in the notes yet")

    notes = FieldNotes()
    notes.notes["pineapple"] = Note(field="pineapple",
                                    pollen=int(body["pollen"]),
                                    seconds=float(body["seconds"]),
                                    visits=int(body.get("visits", 1)),
                                    proven=True, paid_pollen=int(body["pollen"]), paid_seconds=float(body["seconds"]))
    reach = {"pineapple", "strawberry", "pine_tree", "pumpkin", "rose_field"}
    ranked = Planner(fields, notes, reachable=reach).rank(
        Situation(pollen=0, capacity=948_750))

    pineapple = next(r for r in ranked if r.field == "pineapple")
    assert pineapple.score > 0 and pineapple.rate is not None
    assert ranked[0].field != "pineapple", (
        f"the field with {body['seconds']:,.0f} measured seconds must not win "
        f"every trip; got {ranked[0].field}")
    assert ranked[0].rate is None and "assumed as good as" in ranked[0].why
    # ...and the first exploratory trip goes to the least-guarded candidate
    tied = [r for r in ranked if r.score == ranked[0].score]
    assert len(ranked[0].mobs) == min(len(r.mobs) for r in tied)



def test_exploration_only_ever_spends_an_empty_backpack():
    """Carrying pollen, every guarded field -- measured or not -- is refused,
    so curiosity can never be what carries a full bag past a mantis. All five
    reachable fields are guarded, so the answer is to convert."""
    fields = load_fields(ROOT / "data/knowledge/world.yaml")
    notes = FieldNotes()
    if not (ROOT / "var/field_notes.json").exists():
        pytest.skip("the night's field notes are not in the repo")
    notes.load(ROOT / "var/field_notes.json")
    reach = {"pineapple", "strawberry", "pine_tree", "pumpkin", "rose_field"}
    p = Planner(fields, notes, reachable=reach)
    situation = Situation(pollen=WORTH_PROTECTING * 3, capacity=948_750)
    ranked = p.rank(situation)
    assert all(r.score == 0 for r in ranked if not r.safe), \
        [(r.field, r.score) for r in ranked if r.score]
    assert p.decide(situation).action == "convert"


# ------------------- a field whose route does not work stops being chosen ----
# MEASURED 2026-09-21: five consecutive cycles all chose the Strawberry Field,
# every one failed to leave the hive row, and the Rose Field -- measured the
# same night at 930 pollen/s, the best rate this account has recorded -- was
# never chosen again. The curiosity bonus rates an unmeasured field as good as
# the best measured one, and a field that cannot be reached stays unmeasured,
# so it wins for ever.
#
# Here `pineapple` stands for the measured field and `pepper` for the one whose
# route does not work; `pepper` needs 35 bees, so `pineapple` is farmed first
# to prove enough of them.

def _both_reachable():
    # The watched seconds are over YARDSTICK_ENOUGH_SECONDS on purpose: these
    # two are meant to be MEASURED fields (a good one at 900/s and a dud), and
    # the good one has to be solid enough to BE the yardstick, or nothing gets
    # a curiosity bonus and the fixture never starts with an unmeasured field
    # winning. A rate from a ten-second visit is not a measurement -- see
    # `_measured_rate` and the two fields that proved it, Cactus at 3 s and
    # Spider at 86 s.
    notes = FieldNotes()
    notes.notes["pineapple"] = Note(field="pineapple", pollen=360_000,
                                    seconds=400.0, visits=10, proven=True, paid_pollen=360_000, paid_seconds=400.0)
    notes.notes["pine_tree"] = Note(field="pine_tree", pollen=400,
                                    seconds=400.0, visits=10, proven=True, paid_pollen=400, paid_seconds=400.0)
    return notes


def _ranked(notes):
    situation = Situation(pollen=0, capacity=1_000_000)
    return [o.field for o in planner(notes).decide(situation).alternatives]


def test_a_field_that_cannot_be_reached_stops_winning():
    from hivemind.brain import decide as D
    notes = _both_reachable()
    first = _ranked(notes)[0]
    assert first != "pineapple", (
        "the fixture must start with an unmeasured field winning, "
        f"not {first}")
    for _ in range(D.TRAVEL_FAILURES_TO_GIVE_UP):
        notes.travel_failed(first)
    assert _ranked(notes)[0] != first, "it kept choosing what it cannot reach"


def test_one_failed_trip_is_forgiven():
    """A journey already retries three times inside itself: one bad trip is
    bad luck, two is the route."""
    notes = _both_reachable()
    first = _ranked(notes)[0]
    notes.travel_failed(first)
    assert _ranked(notes)[0] == first


def test_arriving_forgives_every_earlier_failure():
    from hivemind.brain import decide as D
    notes = _both_reachable()
    first = _ranked(notes)[0]
    for _ in range(D.TRAVEL_FAILURES_TO_GIVE_UP + 3):
        notes.travel_failed(first)
    assert _ranked(notes)[0] != first
    notes.arrived(first)
    assert _ranked(notes)[0] == first


def test_the_reason_says_it_is_the_route_and_not_the_field():
    from hivemind.brain import decide as D
    notes = _both_reachable()
    first = _ranked(notes)[0]
    for _ in range(D.TRAVEL_FAILURES_TO_GIVE_UP):
        notes.travel_failed(first)
    ranked = planner(notes).decide(Situation(pollen=0,
                                             capacity=1_000_000)).alternatives
    blocked = next(o for o in ranked if o.field == first)
    assert blocked.score == 0.0
    assert "failed to arrive" in blocked.why


def test_the_failure_count_is_not_added_up_across_sessions(tmp_path):
    """A new session relaunched the game and re-claimed the hive; the route
    may well work this time, so a saved count is a ceiling, not a running
    total."""
    notes = FieldNotes()
    notes.travel_failed("pepper")
    notes.travel_failed("pepper")
    path = notes.save(tmp_path / "notes.json")

    again = FieldNotes()
    again.travel_failed("pepper")
    again.load(path)
    assert again.notes["pepper"].travel_failures == 2


def test_giving_up_on_EVERY_field_is_not_allowed():
    """THE SAFETY VALVE. Giving up on a field whose route does not work is
    right; giving up on all of them leaves the planner with nothing to choose
    and the bot standing at the hive doing nothing. A failed trip costs one
    cycle; standing still costs the night."""
    from hivemind.brain import decide as D
    notes = _both_reachable()
    for name in FIELDS:
        for _ in range(D.TRAVEL_FAILURES_TO_GIVE_UP + 1):
            notes.travel_failed(name)
    decision = planner(notes).decide(Situation(pollen=0, capacity=1_000_000))
    assert decision.action == "gather", decision.why
    assert decision.field
    assert "so has every other route" in decision.why


def test_the_valve_stays_shut_while_anything_is_still_reachable():
    from hivemind.brain import decide as D
    notes = _both_reachable()
    for name in ("pepper", "pine_tree", "pineapple"):
        for _ in range(D.TRAVEL_FAILURES_TO_GIVE_UP + 1):
            notes.travel_failed(name)
    decision = planner(notes).decide(Situation(pollen=0, capacity=1_000_000))
    assert decision.field == "sunflower", decision.why
    assert "so has every other route" not in decision.why


def test_a_field_beyond_our_bees_does_not_hold_the_valve_shut():
    """`pepper` needs 35 bees. With none proved it is not a live option, so it
    must not count as "something still reachable"."""
    from hivemind.brain import decide as D
    notes = FieldNotes()
    for name in ("sunflower", "pine_tree", "pineapple"):
        for _ in range(D.TRAVEL_FAILURES_TO_GIVE_UP + 1):
            notes.travel_failed(name)
    decision = planner(notes).decide(Situation(pollen=0, capacity=1_000_000))
    assert decision.action == "gather"
    assert "so has every other route" in decision.why


def test_forgiveness_never_overrides_the_danger_rules():
    """THE BUG THE SAFETY VALVE INTRODUCED, caught by an existing test.

    The "trying is worth more than standing still" note was written as an
    `elif` in the scoring chain, so a forgiven field skipped every rule below
    it -- the bee requirement and, worse, the danger rules. A guarded field
    scored full marks with a full backpack, which is the exact mistake that
    cost 361,439 pollen on 2026-09-20.

    Forgiveness is about whether a route is worth trying again. It has nothing
    to say about mantises.
    """
    from hivemind.brain import decide as D
    notes = FieldNotes()
    for name in FIELDS:
        for _ in range(D.TRAVEL_FAILURES_TO_GIVE_UP + 1):
            notes.travel_failed(name)
    p = planner(notes)
    loaded = p.rank(Situation(pollen=WORTH_PROTECTING * 3, capacity=948_750))
    guarded = [r for r in loaded if not r.safe]
    assert guarded, "the fixture must contain a guarded field"
    assert all(r.score == 0 for r in guarded), \
        [(r.field, r.score) for r in guarded if r.score]
    # ...and with an empty bag the forgiveness is still offered and explained
    empty = p.rank(Situation(pollen=0, capacity=948_750))
    live = [r for r in empty if r.score > 0]
    assert live and any("so has every other route" in r.why for r in live)


def test_forgiveness_does_not_override_the_bee_requirement():
    from hivemind.brain import decide as D
    notes = FieldNotes()
    for name in FIELDS:
        for _ in range(D.TRAVEL_FAILURES_TO_GIVE_UP + 1):
            notes.travel_failed(name)
    ranked = planner(notes).rank(Situation(pollen=0, capacity=948_750))
    pepper = next(r for r in ranked if r.field == "pepper")   # needs 35 bees
    assert pepper.score == 0 and "bees" in pepper.why


# --- the owner's knowledge of which fields are worst --------------------------
# 2026-09-22, after watching the bot farm the starter fields all day: the Blue
# Flower Field and Dandelion pay the least honey, as they give the least
# pollen. A flower count cannot say this -- Blue
# Flower has the MOST flowers in the starter zone -- so it is a separate fact
# (`yield: lowest` in world.yaml) and the planner's GUESS honours it.

def test_a_field_the_owner_calls_worst_ranks_below_an_identical_unmeasured_one():
    fields = {
        "plain":  {"bees_required": 0, "flowers": 700, "mobs": [], "safe": True},
        "worst":  {"bees_required": 0, "flowers": 700, "mobs": [], "safe": True,
                   "yield": "lowest"},
    }
    p = Planner(fields, FieldNotes(), reachable={"plain", "worst"})

    ranked = p.rank(Situation(pollen=0, capacity=1_000_000))
    by = {r.field: r for r in ranked}

    assert by["worst"].score < by["plain"].score
    assert "lowest-yield" in by["worst"].why
    assert "lowest-yield" not in by["plain"].why


def test_a_measured_rate_is_never_touched_by_the_yield_tag():
    """Once a field is farmed, the measurement speaks for itself."""
    fields = {
        "worst":  {"bees_required": 0, "flowers": 700, "mobs": [], "safe": True,
                   "yield": "lowest"},
    }
    notes = FieldNotes()
    notes.notes["worst"] = Note(field="worst", proven=True, visits=3,
                                seconds=600.0, pollen=120_000, paid_pollen=120_000, paid_seconds=600.0)
    with_tag = Planner(fields, notes, reachable={"worst"}).rank(
        Situation(pollen=0, capacity=1_000_000))[0]
    fields["worst"].pop("yield")
    without = Planner(fields, notes, reachable={"worst"}).rank(
        Situation(pollen=0, capacity=1_000_000))[0]

    assert with_tag.score == pytest.approx(without.score)


# ------------------- the unmeasured fields keep their own order --------------
# MEASURED 2026-09-23 01:05: with an empty backpack the ranking read
# `stump 764.6, cactus 764.6, mountain_top 764.6, spider 764.6, bamboo 764.6`
# -- nine fields on one number, because the curiosity bonus REPLACED the score
# that carried the flower count and the quest bonus. The order among them was
# whatever the dictionary gave, and Clover -- 754 flowers, the most of any
# field, with a quest asking for 3,000,000 pollen from it specifically -- had
# never been farmed once all night.

def test_unmeasured_fields_are_ordered_by_flowers_and_by_what_the_quests_want():
    fields = {
        "few_flowers": {"flowers": 400, "bees_required": 0},
        "many_flowers": {"flowers": 754, "bees_required": 0},
        "measured": {"flowers": 500, "bees_required": 0},
    }
    notes = FieldNotes()
    notes.notes["measured"] = Note(field="measured", pollen=100_000,
                                   seconds=1_000.0, visits=3, proven=True, paid_pollen=100_000, paid_seconds=1_000.0)
    ranked = Planner(fields, notes).rank(Situation(pollen=0, capacity=1_000_000))
    by = {r.field: r.score for r in ranked}
    assert by["many_flowers"] > by["few_flowers"], by
    # and both still outrank the measured field, so exploring still happens
    assert by["few_flowers"] > by["measured"], by


def test_the_tie_break_never_costs_an_unmeasured_field_its_turn():
    """The floor is arithmetic: a guarded unmeasured field scores
    best x EXPLORE_OPTIMISM x DANGER_DISCOUNT before the share, and that must
    stay above a measured guarded field's rate x DANGER_DISCOUNT."""
    from hivemind.brain.decide import DANGER_DISCOUNT, EXPLORE_OPTIMISM, EXPLORE_TIE_FLOOR
    assert EXPLORE_TIE_FLOOR * EXPLORE_OPTIMISM > 1.0 / DANGER_DISCOUNT * DANGER_DISCOUNT
    assert EXPLORE_TIE_FLOOR >= 0.92, "below this, exploration ranks under a measured field"


def test_one_lucky_sample_cannot_become_the_yardstick():
    """MEASURED 2026-09-23 03:05: a three-second visit to Cactus recorded
    5,625 pollen -- 1,875 pollen/s, seven times anything real -- because a
    single token pickup lands inside one sample. Every unmeasured field's
    curiosity bonus is a multiple of the best measured rate, so a noisy
    sample would raise all of them."""
    from hivemind.brain.decide import MEASURED_ENOUGH_SECONDS
    fields = {"lucky": {"flowers": 500, "bees_required": 0},
              "real": {"flowers": 500, "bees_required": 0}}
    notes = FieldNotes()
    notes.notes["lucky"] = Note(field="lucky", pollen=5_625, seconds=3.0,
                                paid_seconds=3.0, paid_pollen=5_625, visits=1, proven=True)
    notes.notes["real"] = Note(field="real", pollen=200_000, seconds=1_000.0,
                               paid_seconds=1_000.0, paid_pollen=200_000, visits=3, proven=True)
    planner = Planner(fields, notes)
    assert notes.known("lucky").rate == pytest.approx(1875.0)
    assert planner._best_measured() == pytest.approx(200.0), "the 3-second sample is not evidence"
    assert MEASURED_ENOUGH_SECONDS >= 30.0


def test_a_well_watched_field_is_still_the_yardstick():
    fields = {"good": {"flowers": 500, "bees_required": 0}}
    notes = FieldNotes()
    notes.notes["good"] = Note(field="good", pollen=986_128, seconds=968.0,
                               paid_seconds=968.0, paid_pollen=986_128, visits=1, proven=True)
    assert Planner(fields, notes)._best_measured() == pytest.approx(1018.7, abs=0.2)


# ------------- a rate from a handful of seconds is not a rate ----------------
# MEASURED 2026-09-23 03:05: `cactus` held 5,437 pollen over 3 seconds -- one
# token pickup inside one sampling interval -- and priced itself at 1,875
# pollen/s, seven times the best rate this account has ever recorded. The
# planner's own score for a field came straight off that number, so the
# thinnest measurement on the board outranked Pineapple's 22,772 seconds.

def _thin_and_thick():
    """`sunflower` stands for Cactus -- the thin three-second sample -- and
    `pineapple` for a field watched for a thousand seconds."""
    notes = FieldNotes()
    notes.notes["sunflower"] = Note(field="sunflower", pollen=5_437,
                                    seconds=3.0, visits=2, proven=True, paid_pollen=5_437, paid_seconds=3.0)
    notes.notes["pineapple"] = Note(field="pineapple", pollen=600_000,
                                    seconds=1_000.0, visits=10, proven=True, paid_pollen=600_000, paid_seconds=1_000.0)
    return notes


def test_a_three_second_sample_does_not_outrank_a_watched_field():
    notes = _thin_and_thick()
    ranked = planner(notes).rank(Situation(pollen=0, capacity=1_000_000))
    scores = {r.field: r.score for r in ranked}
    assert scores["sunflower"] < 1_875, (
        f"it scored {scores['sunflower']:.0f} off a three-second sample")


def test_the_thin_field_is_described_as_unfarmed_not_as_fast():
    notes = _thin_and_thick()
    ranked = planner(notes).rank(Situation(pollen=0, capacity=1_000_000))
    why = next(r.why for r in ranked if r.field == "sunflower")
    assert "1,875" not in why, why
    assert "never farmed here" in why, why


# ---------- a loaded bag deletes the good fields, silently -------------------
# MEASURED 2026-09-23 03:25 against the live var/field_notes.json, carrying
# 626,837 of a 1,113,750 backpack:
#
#     loaded   dandelion 219   -- and every other field scored 0, vetoed
#     empty    spider 862, bamboo 831, mountain_top 795, cactus 703
#
# The existing rule only converts when the BEST field is guarded. Here the
# guarded ones had already been struck off inside `rank`, so the best field
# was a safe one, the decision looked reasonable, and nothing said that the
# bag had cut the board down to the owner's own worst field.

def _one_safe_dud_and_one_guarded_prize():
    """`sunflower` is the safe dud (it is the only `safe: True` field in
    FIELDS with no mobs); `pineapple` is the guarded field worth having."""
    notes = FieldNotes()
    notes.notes["sunflower"] = Note(field="sunflower", pollen=20_000,
                                    seconds=100.0, visits=5, proven=True, paid_pollen=20_000, paid_seconds=100.0)
    notes.notes["pineapple"] = Note(field="pineapple", pollen=400_000,
                                    seconds=400.0, visits=5, proven=True, paid_pollen=400_000, paid_seconds=400.0)
    return notes


def test_a_bag_that_costs_us_the_board_is_banked_first():
    from hivemind.brain import decide as D
    notes = _one_safe_dud_and_one_guarded_prize()
    p = planner(notes)
    loaded = p.decide(Situation(pollen=D.WORTH_PROTECTING + 1,
                                capacity=1_113_750))
    assert loaded.action == "convert", loaded.describe()
    assert "strikes every guarded field off the board" in loaded.why


def test_an_empty_bag_goes_straight_to_the_best_field():
    notes = _one_safe_dud_and_one_guarded_prize()
    decision = planner(notes).decide(Situation(pollen=0, capacity=1_113_750))
    assert decision.action == "gather"
    assert decision.field == "pineapple", decision.describe()


def test_it_does_not_bank_when_banking_buys_nothing():
    """If the safe field is the best field anyway, the dwell is pure loss."""
    notes = FieldNotes()
    notes.notes["sunflower"] = Note(field="sunflower", pollen=900_000,
                                    seconds=900.0, visits=5, proven=True, paid_pollen=900_000, paid_seconds=900.0)
    notes.notes["pineapple"] = Note(field="pineapple", pollen=10_000,
                                    seconds=900.0, visits=5, proven=True, paid_pollen=10_000, paid_seconds=900.0)
    from hivemind.brain import decide as D
    decision = planner(notes).decide(
        Situation(pollen=D.WORTH_PROTECTING + 1, capacity=1_113_750))
    assert decision.action == "gather" and decision.field == "sunflower", \
        decision.describe()


def test_the_dwell_is_priced_not_assumed():
    """A gain smaller than the dwell it costs is not a gain. With a trip only
    a little longer than the dwell, a 1% better field must not win."""
    from hivemind.brain import decide as D
    notes = _one_safe_dud_and_one_guarded_prize()
    carrying = 1_000_000
    dwell = D.CONVERT_FIXED_SECONDS + carrying / D.CONVERT_POLLEN_PER_SECOND
    p = planner(notes, trip_seconds=dwell * 1.01)
    decision = p.decide(Situation(pollen=carrying, capacity=1_113_750))
    assert decision.action == "gather", (
        f"a {dwell:.0f}s dwell was taken out of a {dwell * 1.01:.0f}s trip: "
        f"{decision.describe()}")


# ------------- the planner must survive the real world file -----------------
# MEASURED 2026-09-23 03:20, var/night/run-289.log line 43:
#
#     the planner failed ('Planner' object has no attribute
#     'farm_seconds_for') — using the configured route
#
# An attribute that does not exist, on a branch every loaded backpack takes.
# `_choose` catches any planner exception and falls back to the configured
# route so that a broken brain cannot stop the loop earning -- which is right,
# and which means a crash here costs a whole attempt in silence. pyflakes
# cannot see an attribute typo, so the guard has to be a real call: the real
# field table, the real notes if they are in the repo, and every bag size.

def test_the_planner_decides_against_the_real_world_file():
    from hivemind.brain.decide import load_fields
    world = ROOT / "data/knowledge/world.yaml"
    if not world.exists():
        pytest.skip("the knowledge base is not in the repo")
    fields = load_fields(world)
    assert fields, "no fields loaded from the knowledge base"
    notes = FieldNotes()
    if (ROOT / "var/field_notes.json").exists():
        notes.load(ROOT / "var/field_notes.json")
    p = Planner(fields, notes)
    capacity = 1_113_750
    for carrying in (0, 1, 523, 3_735, 107_427, 626_837, 1_000_000, capacity):
        decision = p.decide(Situation(pollen=carrying, capacity=capacity))
        assert decision.action in ("gather", "convert", "wait"), decision
        assert decision.why, f"no reason given at {carrying:,}"
        p.explain(Situation(pollen=carrying, capacity=capacity))
    for pollen in (None, 0, capacity):
        p.decide(Situation(pollen=pollen, capacity=None))
        p.decide(Situation(pollen=pollen, capacity=capacity))


# ------ curiosity shrinks as the route to a place keeps failing -------------
# MEASURED over the night's 140 recorded trips (var/trips.jsonl): nine earned
# exactly zero pollen between them over 2,219 seconds -- sunflower 2, clover
# 4, mountain_top 1, spider 1, pine_tree 1 -- while the fields that pay sat
# measured and ranked below them. `left` shrinks the bonus as seconds are
# SPENT IN a field, and a trip that never arrives spends none there, so an
# unreachable field kept full curiosity right up to the give-up bar.

def _measured_plus_two_unmeasured():
    """`pineapple` is the measured field; `sunflower` (0 bees) and
    `pine_tree` (15, proved by a visit) are the two unmeasured ones that are
    actually available to choose. `pepper` needs 35 and stays barred, which
    is why it cannot be used for this."""
    notes = FieldNotes()
    notes.notes["pineapple"] = Note(field="pineapple", pollen=400_000,
                                    seconds=1_000.0, visits=5, proven=True, paid_pollen=400_000, paid_seconds=1_000.0)
    notes.notes["pine_tree"] = Note(field="pine_tree", proven=True, visits=1)
    return notes


def _scores(notes):
    return {o.field: o.score for o in planner(notes).rank(
        Situation(pollen=0, capacity=1_000_000))}


def test_a_route_that_has_failed_once_is_worth_less_than_one_that_has_not():
    notes = _measured_plus_two_unmeasured()
    before = _scores(notes)
    assert before["sunflower"] > 0 and before["pine_tree"] > 0, before
    notes.travel_failed("sunflower")
    after = _scores(notes)
    assert after["sunflower"] < before["sunflower"], (
        f"{before['sunflower']:.0f} -> {after['sunflower']:.0f}")
    assert after["pine_tree"] == pytest.approx(before["pine_tree"]), \
        "a field whose route has not failed must not be discounted"


def test_the_discount_runs_down_to_the_bar_it_already_has():
    from hivemind.brain import decide as D
    notes = _measured_plus_two_unmeasured()
    scores = []
    for _ in range(D.TRAVEL_FAILURES_TO_GIVE_UP):
        scores.append(_scores(notes)["sunflower"])
        notes.travel_failed("sunflower")
    assert scores == sorted(scores, reverse=True), scores
    assert scores[-1] < scores[0], scores
    assert _scores(notes)["sunflower"] == 0.0, "the existing bar no longer fires"


def test_a_proven_field_overtakes_a_doubtful_route_before_the_bar():
    """The point of the discount: the fields that pay must win back the
    ranking while the bad route still has tries left, not only after it is
    barred outright."""
    from hivemind.brain import decide as D
    notes = _measured_plus_two_unmeasured()
    order = [o.field for o in planner(notes).rank(
        Situation(pollen=0, capacity=1_000_000))]
    assert order.index("sunflower") < order.index("pineapple"), \
        f"the fixture must start with the unmeasured field winning: {order}"
    for _ in range(D.TRAVEL_FAILURES_TO_GIVE_UP - 1):
        notes.travel_failed("sunflower")
    order = [o.field for o in planner(notes).rank(
        Situation(pollen=0, capacity=1_000_000))]
    assert order.index("pineapple") < order.index("sunflower"), order


# ---- the guess for an unfarmed field is scaled off a REAL rate -------------
# MEASURED 2026-09-23 03:56 against the live notes: `_yardstick` returned
# (1874.8, 594) -- Cactus's three-second sample -- so every unfarmed field's
# guess was scaled off a rate five times anything the account has recorded,
# and four places nobody had ever farmed outranked every field that pays:
#
#   spider 862, mountain_top 795, cactus 703, strawberry 677
#   blue_flower 326, rose 298, dandelion 219
#
# `_yardstick` was the third reader of "our best measured rate" and the last
# to get the MEASURED_ENOUGH_SECONDS floor.

def test_the_yardstick_ignores_a_rate_from_three_seconds():
    notes = FieldNotes()
    notes.notes["sunflower"] = Note(field="sunflower", pollen=5_625,
                                    seconds=3.0, visits=2, proven=True, paid_pollen=5_625, paid_seconds=3.0)
    notes.notes["pineapple"] = Note(field="pineapple", pollen=400_000,
                                    seconds=1_000.0, visits=5, proven=True, paid_pollen=400_000, paid_seconds=1_000.0)
    rate, flowers = planner(notes)._yardstick()
    assert rate == pytest.approx(400.0), f"the yardstick is {rate:.0f}/s"
    assert flowers == FIELDS["pineapple"]["flowers"]


def test_a_thin_sample_does_not_lift_every_unfarmed_field():
    thin = FieldNotes()
    thin.notes["sunflower"] = Note(field="sunflower", pollen=5_625,
                                   seconds=3.0, visits=2, proven=True, paid_pollen=5_625, paid_seconds=3.0)
    thin.notes["pineapple"] = Note(field="pineapple", pollen=400_000,
                                   seconds=1_000.0, visits=5, proven=True, paid_pollen=400_000, paid_seconds=1_000.0)
    scores = {o.field: o.score for o in planner(thin).rank(
        Situation(pollen=0, capacity=1_000_000))}
    # pine_tree has never been farmed at all; its score must not exceed the
    # one field here that has been measured for a thousand seconds.
    assert scores["pine_tree"] <= scores["pineapple"] * 1.2, scores


def test_with_nothing_measured_the_flower_count_still_orders_the_board():
    """The fallback must survive: a fresh account has no yardstick at all and
    still has to pick somewhere."""
    scores = {o.field: o.score for o in planner(FieldNotes()).rank(
        Situation(pollen=0, capacity=1_000_000))}
    order = sorted(scores, key=lambda f: -scores[f])
    by_flowers = sorted((f for f in FIELDS if scores.get(f, 0) > 0),
                        key=lambda f: -FIELDS[f]["flowers"])
    assert order[0] == by_flowers[0], (order, by_flowers)


# ---- what share of a field's pollen this hive can actually use -------------
# THE OWNER, 2026-09-23: white pollen, like Spider's white flowers, gives
# their hive little, because their bees are good at blue and a little at red.
# The bot's petal counts agree about the
# field -- Spider measures 18% blue, 5% red, 76% white, the most white on the
# board -- and the colour preference was reading none of that. It read a
# single `colour:` label from the knowledge base, which is None for most
# fields, and it only applied to fields that had never been farmed.

def test_the_colour_worth_comes_from_the_measured_petals():
    from hivemind.brain.decide import colour_worth, COLOUR_WORTH
    spider = {"blue": 18, "red": 5, "white": 76}
    bamboo = {"blue": 80, "red": 4, "white": 17}
    assert colour_worth(spider) < colour_worth(bamboo)
    assert colour_worth({"blue": 100}) == pytest.approx(COLOUR_WORTH["blue"])
    assert colour_worth({"white": 100}) == pytest.approx(COLOUR_WORTH["white"])


def test_a_field_whose_petals_were_never_counted_has_no_opinion():
    """None, not zero. A field nobody has looked at must not be scored as if
    it were all white."""
    from hivemind.brain.decide import colour_worth
    assert colour_worth(None) is None
    assert colour_worth({}) is None
    assert colour_worth({"blue": 0, "white": 0}) is None


def test_blue_is_worth_more_than_red_which_is_worth_more_than_white():
    """Straight from the owner's sentence: good at blue, a little at red."""
    from hivemind.brain.decide import COLOUR_WORTH
    assert COLOUR_WORTH["blue"] > COLOUR_WORTH["red"] > COLOUR_WORTH["white"]
    assert COLOUR_WORTH["blue"] == 1.0


def _two_fields(sunflower_petals, pineapple_petals):
    notes = FieldNotes()
    notes.notes["sunflower"] = Note(field="sunflower", pollen=400_000,
                                    seconds=1_000.0, visits=5, proven=True,
                                    petals=dict(sunflower_petals), paid_pollen=400_000, paid_seconds=1_000.0)
    notes.notes["pineapple"] = Note(field="pineapple", pollen=400_000,
                                    seconds=1_000.0, visits=5, proven=True,
                                    petals=dict(pineapple_petals), paid_pollen=400_000, paid_seconds=1_000.0)
    return notes


def test_two_fields_at_the_same_rate_are_split_by_their_colour():
    notes = _two_fields({"white": 90, "blue": 10}, {"blue": 90, "white": 10})
    scored = {o.field: o.score for o in planner(notes).rank(
        Situation(pollen=0, capacity=1_000_000))}
    assert scored["pineapple"] > scored["sunflower"], scored


def test_a_measured_field_is_adjusted_too_not_only_an_unfarmed_one():
    """The old bonus sat in the `else` branch, so a field the bot had
    actually farmed got no colour consideration at all."""
    white = _two_fields({"white": 100}, {"blue": 100})
    scores = {o.field: o.score for o in planner(white).rank(
        Situation(pollen=0, capacity=1_000_000))}
    for name in ("sunflower", "pineapple"):
        why = next(o.why for o in planner(white).rank(
            Situation(pollen=0, capacity=1_000_000)) if o.field == name)
        assert "colour these bees are good at" in why, why
    assert scores["pineapple"] > scores["sunflower"]


def test_the_reason_says_the_share_so_the_trade_is_visible():
    notes = _two_fields({"white": 76, "blue": 18, "red": 6}, {"blue": 100})
    why = next(o.why for o in planner(notes).rank(
        Situation(pollen=0, capacity=1_000_000)) if o.field == "sunflower")
    assert "% of its pollen is a colour these bees are good at" in why, why


def test_a_field_of_pure_usable_pollen_keeps_its_whole_rate():
    """The weight only ever takes away, so a perfect field is not inflated."""
    from hivemind.brain.decide import COLOUR_WEIGHT, colour_worth
    keep = (1.0 - COLOUR_WEIGHT) + COLOUR_WEIGHT * colour_worth({"blue": 1})
    assert keep == pytest.approx(1.0)


# ---- a field with no walk home pays for its rejoin ------------------------
# Seven fields lost their transpiled walk home on 2026-09-23 (the Natro paths
# glide or press the portal, and a route with its jump missing is a different
# route). A trip there still earns; it just ends in a ~100 s rejoin, and the
# planner charges the time share -- and only the time share, because the
# Wealth Clock streak the rejoin also costs has no measured honey value yet.

def _two_equal_fields():
    from hivemind.brain.fieldnotes import FieldNotes, Note
    notes = FieldNotes()
    for name in ("strawberry", "blue_flower"):
        notes.notes[name] = Note(field=name, proven=True, visits=3,
                                 seconds=900.0, pollen=300_000,
                                 paid_seconds=900.0, paid_pollen=300_000)
    fields = {"strawberry": {"flowers": 400, "mobs": []},
              "blue_flower": {"flowers": 400, "mobs": []}}
    return fields, notes


def test_a_field_without_a_walk_home_is_discounted_by_the_rejoins_time_share():
    from hivemind.brain.decide import REJOIN_SECONDS, Planner, Situation
    fields, notes = _two_equal_fields()
    p = Planner(fields, notes, reachable={"strawberry", "blue_flower"},
                walk_home={"strawberry"}, trip_seconds=1000.0)
    ranked = {s.field: s for s in p.rank(Situation(pollen=0, capacity=1_000_000))}
    assert ranked["strawberry"].score > ranked["blue_flower"].score
    assert abs(ranked["blue_flower"].score / ranked["strawberry"].score
               - 1000.0 / (1000.0 + REJOIN_SECONDS)) < 1e-6
    assert "ends in a rejoin" in ranked["blue_flower"].why
    assert "rejoin" not in ranked["strawberry"].why


def test_with_no_knowledge_of_walks_home_every_field_is_priced_the_same():
    from hivemind.brain.decide import Planner, Situation
    fields, notes = _two_equal_fields()
    p = Planner(fields, notes, reachable={"strawberry", "blue_flower"},
                trip_seconds=1000.0)
    ranked = {s.field: s for s in p.rank(Situation(pollen=0, capacity=1_000_000))}
    assert ranked["strawberry"].score == ranked["blue_flower"].score


def test_the_rejoin_is_a_price_not_a_ban():
    """A field that pays much more is still chosen; it just pays its way."""
    from hivemind.brain.decide import Planner, Situation
    from hivemind.brain.fieldnotes import FieldNotes, Note
    notes = FieldNotes()
    notes.notes["spider"] = Note(field="spider", proven=True, visits=3, seconds=900.0,
                                 pollen=900_000, paid_seconds=900.0, paid_pollen=900_000)
    notes.notes["dandelion"] = Note(field="dandelion", proven=True, visits=3,
                                    seconds=900.0, pollen=200_000,
                                    paid_seconds=900.0, paid_pollen=200_000)
    fields = {"spider": {"flowers": 400, "mobs": []},
              "dandelion": {"flowers": 400, "mobs": []}}
    p = Planner(fields, notes, reachable={"spider", "dandelion"},
                walk_home={"dandelion"}, trip_seconds=1000.0)
    assert p.decide(Situation(pollen=0, capacity=1_000_000)).field == "spider"


# ---- a wanted fight tilts toward the mob's field, and never overrides danger --

def test_a_wanted_mob_tilts_the_ranking_toward_its_field():
    from hivemind.brain.decide import QUEST_BONUS, Planner, Situation
    from hivemind.brain.fieldnotes import FieldNotes, Note
    from hivemind.brain.questneeds import Needs
    notes = FieldNotes()
    for name in ("spider", "mushroom"):
        notes.notes[name] = Note(field=name, proven=True, visits=3, seconds=900.0,
                                 pollen=300_000, paid_seconds=900.0, paid_pollen=300_000)
    fields = {"spider": {"flowers": 400, "mobs": ["spider"]},
              "mushroom": {"flowers": 400, "mobs": ["ladybug"]}}
    needs = Needs()
    needs.fights = ["Defeat 3 Spiders. 1/3"]
    p = Planner(fields, notes, quest_needs=needs)
    ranked = {s.field: s for s in p.rank(Situation(pollen=0, capacity=1_000_000))}
    assert ranked["spider"].score > ranked["mushroom"].score
    assert "2 more spiders defeated" in ranked["spider"].why
    assert "defeated" not in ranked["mushroom"].why
    # the tilt is the quest bonus, not an override
    assert abs(ranked["spider"].score / ranked["mushroom"].score - (1 + QUEST_BONUS)) < 1e-6


def test_a_wanted_fight_never_sends_a_loaded_bag_to_the_mob():
    from hivemind.brain.decide import Planner, Situation
    from hivemind.brain.fieldnotes import FieldNotes, Note
    from hivemind.brain.questneeds import Needs
    notes = FieldNotes()
    notes.notes["spider"] = Note(field="spider", proven=True, visits=3, seconds=900.0,
                                 pollen=300_000, paid_seconds=900.0, paid_pollen=300_000)
    fields = {"spider": {"flowers": 400, "mobs": ["spider"]}}
    needs = Needs()
    needs.fights = ["Defeat 3 Spiders. 1/3"]
    p = Planner(fields, notes, quest_needs=needs)
    loaded = p.rank(Situation(pollen=600_000, capacity=1_000_000))[0]
    assert loaded.score == 0.0 and "not worth the risk" in loaded.why


# ---- the HUD's printed rate stands in when the counter never gave a pair ----

def test_a_field_with_only_a_printed_rate_is_scored_on_it_and_says_so():
    from hivemind.brain.decide import Planner, Situation, _measured_rate
    from hivemind.brain.fieldnotes import PRINTED_ENOUGH_SAMPLES, FieldNotes
    notes = FieldNotes()
    for _ in range(PRINTED_ENOUGH_SAMPLES):
        notes.saw_rate("rose", 900)
    note = notes.known("rose")
    assert not note.pays and _measured_rate(note) == 900.0
    p = Planner({"rose": {"flowers": 400, "mobs": []}}, notes)
    scored = p.rank(Situation(pollen=0, capacity=1_000_000))[0]
    assert "HUD's own counter printed 900" in scored.why and "token lumps" in scored.why


def test_a_paid_pair_beats_the_printed_rate():
    from hivemind.brain.decide import _measured_rate
    from hivemind.brain.fieldnotes import PRINTED_ENOUGH_SAMPLES, Note
    note = Note(field="rose", proven=True, seconds=900.0, pollen=900_000,
                paid_seconds=900.0, paid_pollen=900_000,
                printed_sum=700.0 * PRINTED_ENOUGH_SAMPLES,
                printed_samples=PRINTED_ENOUGH_SAMPLES)
    assert _measured_rate(note) == 1000.0


def test_too_few_printed_readings_leave_the_field_unmeasured():
    from hivemind.brain.decide import _measured_rate
    from hivemind.brain.fieldnotes import Note
    assert _measured_rate(Note(field="rose", printed_sum=7000.0, printed_samples=10)) is None


def test_planner_v2_prices_the_whole_cycle_the_field_deaths_and_the_quest(tmp_path):
    """score_v2 (think-planner 2026-10-22): a guarded field with 10+ gather
    hours of its own and no deaths drops the x0.75; one with less keeps it;
    travel and the convert are priced; a quest's honey is a value, not a sort."""
    import json
    from hivemind.brain import decide as d
    rows = []
    for i in range(130):                                 # 130 x 300 s = 10.8 h
        rows.append({"credited": "pine_tree", "gather_seconds": 300, "seconds": 600,
                     "converted": True, "pollen": 1e7, "honey": 1.6e7, "deaths": 0,
                     "routes": [{"kind": "out", "target": "pine_tree", "seconds": 60}]})
    for i in range(5):
        rows.append({"credited": "pepper", "gather_seconds": 900, "seconds": 1200,
                     "converted": True, "pollen": 7e6, "honey": 1.12e7, "deaths": 0,
                     "routes": [{"kind": "out", "target": "pepper", "seconds": 60}]})
    path = tmp_path / "trips.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    stats = d.trip_stats(path)
    assert stats["_"]["convert_s"] == 240 and stats["pine_tree"]["travel_s"] == 60
    pine = d.FieldScore("pine_tree", 25_000, rate=40_000, safe=False, p_land=1.0)
    pepper = d.FieldScore("pepper", 6_000, rate=7_000, safe=True, p_land=1.0)
    mtop = d.FieldScore("mountain_top", 20_000, rate=40_000, safe=False, p_land=1.0)
    v, lived, quest, _ = d.score_v2(pine, stats)
    assert lived > 0.99 and abs(v - 40_000 * 300 * 1.6 * lived / 600) < 1
    assert d.score_v2(mtop, stats)[1] == d.DANGER_DISCOUNT    # unmeasured: floor
    # a big enough quest reward wins on value, a small one does not
    assert d.v2_rank([pine, pepper], stats, {"pepper": (2.55, 5e7)})[0][0] is pine
    assert d.v2_rank([pine, pepper], stats, {"pepper": (20.0, 5e7)})[0][0] is pepper
    assert d.score_v2(d.FieldScore("x", 0, rate=1), stats) is None
    assert d.v2_explore(d.v2_rank([pine, mtop], stats), stats, 0.05, 0) == []
    # the widened explore draws only around the planner's own pick: v2's best
    # being another field gives no draw (review fix 1, think-all 2026-10-22)
    clover = d.FieldScore("clover", 25_000, rate=40_000, safe=True, p_land=1.0)
    ranked = d.v2_rank([pine, clover], stats, None, 40_000 * 300)
    assert ranked[0][0] is pine and len(d.v2_explore(ranked, stats, 0.05, 0)) == 2
    assert len(d.v2_explore(ranked, stats, 0.05, 0, chosen="pine_tree")) == 2
    assert d.v2_explore(ranked, stats, 0.05, 0, chosen="clover") == []


def test_trip_stats_counts_an_uncredited_death_on_the_field_it_aimed_at(tmp_path):
    """MEASURED 2026-10-22: 3 of 25 death rows have credited None."""
    import json
    from hivemind.brain import decide as d
    path = tmp_path / "trips.jsonl"
    path.write_text(json.dumps({"credited": None, "aimed_at": "rose", "gather_seconds": 40,
                                "deaths": 1, "converted": True, "pollen": 0, "honey": None}))
    s = d.trip_stats(path)["rose"]
    assert s["deaths"] == 1 and s["seconds"] == 40 and s["gather_s"] is None


def test_leaks_reach_planner_v2_only_and_the_floor_holds():
    """reflect.field_minutes feeds v2's shadow (score_v2), never `rank`."""
    import hivemind.brain.decide as decide
    from hivemind.brain.decide import FieldScore, score_v2, v2_rank
    p = planner(proven("sunflower", "pine_tree"))
    before = {s.field: s.score for s in p.rank(Situation(pollen=0, capacity=900_000))}
    p.leak_minutes = {"pine_tree": 12.0}
    after = {s.field: s.score for s in p.rank(Situation(pollen=0, capacity=900_000))}
    assert after == before                                 # the live choice never moves
    alt = FieldScore("pine_tree", score=10.0, rate=3000.0, safe=True, reachable=True)
    stats = {"_": {"hpp": 1.5, "travel_s": 60.0, "convert_s": 190.0}}
    base = score_v2(alt, stats, capacity=900_000)
    hit = score_v2(alt, stats, capacity=900_000, leaks={"pine_tree": 12.0})
    assert hit[0] == pytest.approx(base[0] * 0.8) and "lost 12 min" in hit[3]
    worst = score_v2(alt, stats, capacity=900_000, leaks={"pine_tree": 600.0})
    assert worst[0] == pytest.approx(base[0] * decide.LEAK_FLOOR)
    other = FieldScore("sunflower", score=10.0, rate=2900.0, safe=True, reachable=True)
    ranked = v2_rank([alt, other], stats, capacity=900_000, leaks={"pine_tree": 30.0})
    assert ranked[0][0].field == "sunflower"               # the leak flips v2's pick
