"""The reporter must publish what was measured and nothing else.

These tests exist because the failure they guard against already happened: a
live run published 585 frames, 3 tasks and 3 metrics in thirty seconds, and
every panel the owner opened was empty. The two specific misses -- a metric
named `honey_earned` where the GUI reads `honey`, and no vitals at all -- are
both pinned here by name, because a rename would silently break the GUI again
and nothing else would notice.
"""
from __future__ import annotations

from hivemind.brain.report import Reporter
from hivemind.telemetry.events import (Belief, Considered, FieldStatus,
                                       Metric, StatusUpdate, Thought)


class Clock:
    def __init__(self, at=0.0):
        self.at = at

    def __call__(self):
        return self.at


def collect():
    events = []
    return events, Reporter(events.append, clock=Clock())


def kinds(events, cls):
    return [e for e in events if isinstance(e, cls)]


# ---- vitals ---------------------------------------------------------------
def test_vitals_use_the_names_the_gui_actually_reads():
    events, rep = collect()
    rep.vitals(pollen=1000, capacity=5000, honey=42, bees=25, rate=1234.0)
    names = {e.name for e in kinds(events, Metric)}
    # gui/window._metric maps exactly these, and refreshes the goal web on
    # `honey`. A rename here is a GUI regression.
    assert {"honey", "pollen", "bees", "honey_per_hour"} <= names


def test_an_unread_number_is_never_published_as_zero():
    events, rep = collect()
    rep.vitals(pollen=None, honey=None, bees=None)
    assert kinds(events, Metric) == []


def test_zero_is_published_when_zero_was_actually_read():
    events, rep = collect()
    rep.vitals(pollen=0, capacity=5000)
    assert [e.value for e in kinds(events, Metric) if e.name == "pollen"] == [0.0]


def test_an_unchanged_number_is_not_resent():
    events, rep = collect()
    rep.vitals(honey=42)
    rep.vitals(honey=42)
    rep.vitals(honey=43)
    assert [e.value for e in kinds(events, Metric) if e.name == "honey"] == [42.0, 43.0]


def test_backpack_fill_is_a_percentage_and_needs_a_capacity():
    events, rep = collect()
    rep.vitals(pollen=250, capacity=1000)
    fill = [e for e in kinds(events, Metric) if e.name == "backpack_fill"]
    assert [e.value for e in fill] == [25.0]

    events, rep = collect()
    rep.vitals(pollen=250, capacity=0)
    assert not [e for e in kinds(events, Metric) if e.name == "backpack_fill"]


# ---- the plan -------------------------------------------------------------
class FakeScore:
    def __init__(self, field, score, why="because", mobs=(), rate=None):
        self.field = field
        self.score = score
        self.why = why
        self.mobs = mobs
        self.rate = rate

    @property
    def pretty(self):
        return self.field.replace("_", " ")


class FakeDecision:
    def __init__(self, action="gather", field="pineapple", why="best rate"):
        self.action = action
        self.field = field
        self.why = why
        self.alternatives = []

    def describe(self):
        return f"{self.action} in {self.field} — {self.why}"


def test_the_plan_thought_uses_the_topic_the_goal_web_listens_for():
    events, rep = collect()
    rep.plan(FakeDecision(), [FakeScore("pineapple", 356.0)])
    thoughts = kinds(events, Thought)
    assert thoughts and thoughts[0].topic == "plan"


def test_the_same_decision_is_not_announced_twice():
    events, rep = collect()
    rep.plan(FakeDecision(), [FakeScore("pineapple", 356.0)])
    rep.plan(FakeDecision(), [FakeScore("pineapple", 356.0)])
    assert len(kinds(events, Thought)) == 1


def test_changing_field_announces_again():
    events, rep = collect()
    rep.plan(FakeDecision(field="pineapple"), [FakeScore("pineapple", 1.0)])
    rep.plan(FakeDecision(field="pine_tree"), [FakeScore("pine_tree", 1.0)])
    assert len(kinds(events, Thought)) == 2


def test_the_ranking_becomes_the_priority_list():
    events, rep = collect()
    ranked = [FakeScore("pineapple", 356.0), FakeScore("pine_tree", 334.0),
              FakeScore("rose", 232.0)]
    rep.plan(FakeDecision(), ranked)
    considered = kinds(events, Considered)
    assert len(considered) == 1
    assert [o.label for o in considered[0].options] == ["pineapple", "pine tree", "rose"]
    assert considered[0].chosen == "pineapple"


def test_the_ranking_is_offered_as_options_and_the_field_rows_are_left_to_the_dashboard():
    """NO FIELD ROWS FROM HERE (DESIGN 8du): they carried zeros over the
    measured rows Dashboard.publish_fields sends. The ranking goes out as the
    "Which field next?" options instead."""
    from hivemind.telemetry.events import Considered
    events, rep = collect()
    rep.plan(FakeDecision(), [FakeScore("pineapple", 1.0, mobs=("mantis",)),
                              FakeScore("rose", 0.5)])
    assert kinds(events, FieldStatus) == []
    asked = kinds(events, Considered)
    assert len(asked) == 1 and len(asked[0].options) == 2


def test_no_decision_publishes_nothing():
    events, rep = collect()
    rep.plan(None, [FakeScore("pineapple", 1.0)])
    assert events == []


def test_a_decision_with_no_ranking_still_announces_the_choice():
    events, rep = collect()
    rep.plan(FakeDecision(), [])
    assert len(kinds(events, Thought)) == 1
    assert kinds(events, Considered) == []


# ---- beliefs and status ---------------------------------------------------
def test_a_belief_carries_its_source():
    events, rep = collect()
    rep.belief("bees_at_least", 25, source="proved by gathering")
    held = kinds(events, Belief)
    assert held[0].name == "bees_at_least"
    assert held[0].value == 25
    assert held[0].source == "proved by gathering"


def test_an_unknown_belief_is_not_published():
    events, rep = collect()
    rep.belief("bees_at_least", None, source="unread")
    assert kinds(events, Belief) == []


def test_an_unchanged_belief_is_not_resent():
    events, rep = collect()
    rep.belief("where", "pineapple", source="feed")
    rep.belief("where", "pineapple", source="feed")
    assert len(kinds(events, Belief)) == 1


def test_status_reports_uptime_from_the_clock():
    events = []
    clock = Clock()
    rep = Reporter(events.append, clock=clock)
    clock.at = 30.0
    rep.status(running=True, note="farming")
    update = kinds(events, StatusUpdate)[0]
    assert update.running is True
    assert update.uptime_s == 30.0


# ---- the timer ------------------------------------------------------------
def test_the_first_push_is_always_due():
    # A `_last_full` starting at 0.0 with a clock that also starts at 0.0
    # makes the first check false, so the first push never happens. This has
    # been shipped twice in this project; it does not get shipped a third time.
    events = []
    rep = Reporter(events.append, clock=Clock(), every=5.0)
    assert rep.due() is True


def test_pushes_are_spaced_by_every():
    clock = Clock()
    rep = Reporter([].append, clock=clock, every=5.0)
    assert rep.due() is True
    clock.at = 4.9
    assert rep.due() is False
    clock.at = 5.0
    assert rep.due() is True
