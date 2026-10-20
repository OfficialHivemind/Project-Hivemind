"""A quest field step that stops moving loses its tilt for a while, and a read
short of the list's end keeps the quests it did not reach (brain/questneeds
StepStalls, keep_unlisted). MEASURED cases: run-1018 15 Oct (Bamboo goo
unmoved, 212 min gathered there), run-1184 23 Oct (12 quests, then 4 for 10 h)."""
from __future__ import annotations

from hivemind.brain import questneeds as qn

BAMBOO = "Collect 5,750,000 Goo from the Bamboo Field. {}/5,750,000"
PEPPER = "Collect 400,000,000 Pollen from the Pepper Patch. 55,209,579/400,000,000"


def _needs(done):
    return qn.from_lines([BAMBOO.format(f"{done:,}"), PEPPER])


def test_an_unmoved_step_cools_after_enough_gathering_and_a_move_restores_it():
    s = qn.StepStalls()
    assert s.observe(_needs(366660), 0.0) == []
    s.gathered("bamboo", 20 * 60)
    assert s.observe(_needs(366660), 1200.0) == []            # not enough gathered yet
    s.gathered("bamboo", 15 * 60)
    s.gathered("pepper", 60 * 60)
    said = s.observe(_needs(366660), 2400.0)
    assert any(line.startswith("bamboo: its quest step still owes 5,383,340") for line in said)
    assert s.cooled(2401.0) == {"bamboo", "pepper"}
    assert _needs(366660).fields_dropped(s.cooled(2401.0)).field_remaining("bamboo") == 0
    said = s.observe(_needs(400000), 3000.0)                    # it moved
    assert any("bamboo: its quest step moved" in line for line in said)
    assert s.cooled(3001.0) == {"pepper"}
    assert s.cooled(2400.0 + qn.STALL_COOLDOWN_S + 1) == set()  # the cooldown is over


def test_no_gathering_there_is_no_stall_and_the_state_round_trips():
    s = qn.StepStalls()
    s.observe(_needs(1), 0.0)
    assert s.observe(_needs(1), 10 * 3600.0) == []              # never went there
    again = qn.StepStalls(s.state)
    again.gathered("bamboo", qn.STALL_GATHER_S)
    assert again.observe(_needs(1), 11 * 3600.0)
    assert "bamboo" in qn.StepStalls(again.state).cooled(11 * 3600.0 + 1)


def test_a_short_read_forgets_no_step_it_did_not_reach():
    s = qn.StepStalls()
    s.observe(_needs(1), 0.0)
    s.gathered("bamboo", qn.STALL_GATHER_S)
    s.observe(qn.from_lines([PEPPER]), 60.0, whole=False)        # the first page only
    assert "bamboo" in s.steps
    assert s.observe(_needs(1), 120.0)                          # still unmoved: cooled
    s.observe(qn.from_lines([PEPPER]), 180.0, whole=True)        # a whole read: gone
    assert "bamboo" not in s.steps and "bamboo" not in s.cooled(181.0)


WAS = {"read_at": 1000.0, "quests": [
    {"giver": "", "name": "Weed Wacker 3", "requirements": [PEPPER]},
    {"giver": "", "name": "Bucko Bee: Medley", "requirements": [BAMBOO.format("1")]}]}
NOW = [{"giver": "", "name": "Weed Wacker 3", "requirements": [PEPPER]}]


def test_a_read_short_of_the_end_keeps_the_quests_it_did_not_reach():
    out, notes = qn.keep_unlisted(WAS, NOW, False, 2000.0)
    assert [q["name"] for q in out] == ["Weed Wacker 3", "Bucko Bee: Medley"]
    assert out[1]["seen_at"] == 1000.0 and "seen_at" not in out[0]
    assert notes and "Bucko Bee: Medley" in notes[0]
    # kept again by the next short read, dated by its last sighting, until the cap
    again, _ = qn.keep_unlisted({"read_at": 2000.0, "quests": out}, NOW, False, 3000.0)
    assert again[1]["seen_at"] == 1000.0
    late, _ = qn.keep_unlisted({"read_at": 2000.0, "quests": out}, NOW, False,
                               1000.0 + qn.KEEP_UNLISTED_S + 1)
    assert [q["name"] for q in late] == ["Weed Wacker 3"]


def test_a_whole_or_unknown_read_replaces_the_list():
    for whole in (True, None):
        out, notes = qn.keep_unlisted(WAS, NOW, whole, 2000.0)
        assert [q["name"] for q in out] == ["Weed Wacker 3"] and notes == []
    # and the kept quests are needs like any other
    out, _ = qn.keep_unlisted(WAS, NOW, False, 2000.0)
    path_needs = qn.from_lines([r for q in out for r in q["requirements"]])
    assert path_needs.field_remaining("bamboo") == 5_749_999


def test_a_finished_quest_is_never_kept_so_its_giver_is_not_queued_again():
    # run-1185, 23 Oct: handed in at 11:14, not listed by the short read at 11:26
    done = {"giver": "", "name": "Defeat 4 Mantises.", "requirements": [
        "Defeat 4 Scorpions. Complete! Talk to Polar Bear.",
        "Defeat 4 Mantises. Complete! Talk to Polar Bear."]}
    was = dict(WAS, quests=WAS["quests"] + [done])
    out, notes = qn.keep_unlisted(was, NOW, False, 2000.0)
    assert [q["name"] for q in out] == ["Weed Wacker 3", "Bucko Bee: Medley"]
    assert "Mantises" not in notes[0]
    lines = [r for q in out for r in q["requirements"]]
    assert qn.from_lines(lines).ready_to_hand_in == ()
