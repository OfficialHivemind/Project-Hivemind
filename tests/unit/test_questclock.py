"""When the quest menu is next worth reading (brain/questclock)."""
from __future__ import annotations

from hivemind.brain.questclock import QuestClock, next_interval

BASE, CAP = 20 * 60.0, 120 * 60.0
T0 = 1_790_000_000.0


def q(name, *reqs):
    return {"name": name, "requirements": list(reqs)}


def menu(tokens="880/5,000", ants="923,815/2,500,000", fire="Complete! Talk to Panda Bear."):
    return [q("Honey Bee's Honey Hunt", f"Collect 5,000 Honey Tokens. {tokens}"),
            q("Can't Without Ants", "Collect 50,000,000 Pollen. Complete!",
              f"Collect 2,500,000 Pollen from the Ant Field. {ants}"),
            q("Fire Fighter", f"Defeat 15 Fire Ants. {fire}"),
            q("Polar Bear: High Protein Bug Bar",
              "Collect 180,000 Pollen from the Sunflower Field. 49/180,000",
              "Defeat 4 Mantises. Complete!")]


def gap(previous, current, seconds=22 * 60.0):
    return next_interval(previous, T0, current, T0 + seconds, base=BASE, cap=CAP)


def test_nothing_moved_waits_the_cap():
    wait, why = gap(menu(), menu())
    assert wait == CAP and "nothing on the menu moved" in why


def test_a_slow_step_waits_the_cap_and_names_it():
    # 96 tokens in 22 minutes: 4,024 to go is about 15 hours
    wait, why = gap(menu(), menu(tokens="976/5,000"))
    assert wait == CAP
    assert "Honey Bee's Honey Hunt" in why and "976/5,000" in why and "15.4 h" in why


def test_a_step_due_to_finish_brings_the_read_to_it():
    # 1,000 tokens in 22 min, 2,000 to go: due in 44 min
    wait, why = gap(menu(tokens="2,000/5,000"), menu(tokens="3,000/5,000"))
    assert abs(wait - 44 * 60.0) < 1.0, wait
    assert "about 44 min away" in why


def test_never_sooner_than_the_base():
    # Bucko's blue pollen two minutes from done at 12:36 (run-555)
    was = [q("Bucko Bee: Pollen", "Collect 40,000,000 Blue Pollen. 36,000,000/40,000,000")]
    now = [q("Bucko Bee: Pollen", "Collect 40,000,000 Blue Pollen. 38,888,318/40,000,000")]
    wait, _ = gap(was, now)
    assert wait == BASE


def test_a_newly_complete_step_is_news():
    wait, why = gap(menu(fire="13/15"), menu())
    assert wait == BASE and "newly complete" in why and "Fire Fighter" in why


def test_a_complete_that_a_read_dropped_is_news_too():
    """A noisy read only brings the old pace back (act/quests.READS)."""
    wait, why = gap(menu(), menu(fire=""))
    assert wait == BASE and "no longer reads complete" in why


def test_a_quest_handed_in_and_its_successor_are_news():
    was = menu()
    now = [x for x in menu() if x["name"] != "Fire Fighter"] + [
        q("Panda Bear: Bamboo Bash", "Defeat 2 Rhino Beetles. 0/2")]
    wait, why = gap(was, now)
    assert wait == BASE
    assert "new: Panda Bear: Bamboo Bash" in why and "gone: Fire Fighter" in why


def test_a_step_that_reads_differently_is_news():
    was = menu()
    now = menu()
    now[3]["requirements"].append("Defeat 4 Scorpions. Complete!")
    wait, why = gap(was, now)
    assert wait == BASE and "steps read differently" in why


def test_an_empty_read_and_no_earlier_read_are_the_base():
    assert gap(menu(), [])[0] == BASE
    assert next_interval(None, 0.0, menu(), T0, base=BASE, cap=CAP)[0] == BASE
    assert next_interval(menu(), T0 + 5, menu(), T0, base=BASE, cap=CAP)[0] == BASE


def test_quest_objects_work_as_well_as_the_files_dicts():
    class Quest:
        def __init__(self, name, *reqs):
            self.name, self.requirements = name, tuple(reqs)

    was = [Quest(x["name"], *x["requirements"]) for x in menu()]
    assert gap(was, menu())[0] == CAP


# --- the clock ---------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


def test_the_clock_is_due_at_once_then_after_what_the_reads_say():
    c = Clock()
    qc = QuestClock(base=BASE, cap=CAP, clock=c)
    assert qc.due()
    assert qc.read(menu()) == BASE                   # nothing to compare with
    c.t += BASE
    assert qc.due()
    assert qc.read(menu()) == CAP
    c.t += BASE
    assert not qc.due()
    assert "nothing on the menu moved" in qc.describe()
    c.t += CAP - BASE
    assert qc.due()


def test_what_changes_quests_brings_the_read_back_to_the_base():
    c = Clock()
    qc = QuestClock(base=BASE, cap=CAP, clock=c)
    qc.read(menu())
    c.t += BASE
    qc.read(menu())                                  # due in the cap
    c.t += 5 * 60
    qc.soon("a bug run")
    assert not qc.due()                              # 25 min after the last read...
    c.t += 15 * 60
    assert qc.due()                                  # ...is past the base
    assert qc.why == "a bug run since the last read"


def test_soon_never_puts_a_read_later():
    c = Clock()
    qc = QuestClock(base=BASE, cap=CAP, clock=c)
    qc.at_next_convert("a quest step was gathered")
    qc.soon("a bug run")
    assert qc.due() and qc.why == "a quest step was gathered"


def test_a_file_from_an_earlier_process_is_compared_with():
    c = Clock()
    qc = QuestClock(base=BASE, cap=CAP, clock=c)
    qc.remember(menu(), T0 - 25 * 60)
    assert qc.read(menu()) == CAP


def test_a_skipped_start_up_read_waits_the_base_from_here():
    c = Clock()
    qc = QuestClock(base=BASE, cap=CAP, clock=c)
    qc.skipped()
    assert not qc.due()
    c.t += BASE
    assert qc.due()


def test_an_empty_read_is_not_remembered_as_the_last_one():
    c = Clock()
    qc = QuestClock(base=BASE, cap=CAP, clock=c)
    qc.read(menu())
    c.t += BASE
    assert qc.read([]) == BASE
    c.t += BASE
    assert qc.read(menu()) == CAP                    # compared with the good read


def test_a_last_read_older_than_the_cap_times_nothing():
    """var/quests.json from a process stopped hours ago: the time off is not farming."""
    wait, why = next_interval(menu(tokens="880/5,000"), T0, menu(tokens="2,000/5,000"),
                              T0 + CAP + 60, base=BASE, cap=CAP)
    assert wait == BASE and "too old" in why
