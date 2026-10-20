"""Every GUI tab gets real data, or an honest reason. See brain/dashboard."""
from __future__ import annotations

import pathlib

import pytest

from hivemind.datapaths import config_dir

from hivemind.brain.dashboard import GAPS, Dashboard

ROOT = pathlib.Path(__file__).resolve().parents[2]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Score:
    def __init__(self, field, score, mobs=(), why=""):
        self.field, self.score, self.mobs, self.why = field, score, mobs, why


class Note:
    last_seen = 1234.0     # monotonic, this process only
    last_wall = 1234.0     # the wall clock, which is what the dashboard shows


class Notes:
    def known(self, name):
        return Note() if name == "pineapple" else None


class Standing:
    honey, bees, tool, colour = 29_868_790, 26, "golden_rake", "blue"
    fields_proven = ("pineapple", "pine_tree")


def dash(**kw):
    got = []
    clock = Clock()
    d = Dashboard(got.append, clock=clock, wall=lambda: 1e9, **kw)
    return d, got, clock


def kinds(events, name):
    return [e for e in events if type(e).__name__ == name]


# ------------------------------------------------------------------ pacing --
def test_it_only_publishes_on_its_own_schedule():
    d, got, clock = dash()
    assert d.refresh(force=True) is True
    got.clear()
    assert d.refresh() is False and got == []
    clock.t = d.every + 1
    assert d.refresh() is True


def test_nothing_it_does_can_end_a_run():
    """Every publisher is wrapped: a broken one becomes a Log, not a crash."""
    class Exploding:
        def items(self): raise RuntimeError("bad yaml")
        def progression(self): raise RuntimeError("bad yaml")
        def account(self): raise RuntimeError("bad yaml")
    d, got, _ = dash(knowledge=Exploding())
    assert d.refresh(force=True) is True
    assert kinds(got, "ShadowPrice"), "it carried on past the failure"


# ------------------------------------------------------------------ timers --
def test_the_timers_tab_gets_every_deadline_the_game_has():
    d, got, _ = dash()
    d.refresh(force=True)
    timers = kinds(got, "Timer")
    assert len(timers) >= 8
    names = {t.name for t in timers}
    assert {"Stump Snail", "Coconut Crab", "Wealth Clock"} <= names


def test_a_timer_nobody_has_used_offers_no_deadline():
    """ready_at of 0 renders as "—" in the panel, not as "ready"."""
    d, got, _ = dash()
    d.refresh(force=True)
    for t in kinds(got, "Timer"):
        assert t.ready_at == 0.0
        assert "never seen used" in t.note


def test_the_two_opposite_boss_rules_survive_to_the_panel():
    """Stump Snail saves damage and the Coconut Crab resets. These get
    OPPOSITE scheduling, so the flag has to arrive intact."""
    d, got, _ = dash()
    d.refresh(force=True)
    by = {t.name: t for t in kinds(got, "Timer")}
    assert by["Stump Snail"].persistent_hp is True
    assert by["Coconut Crab"].persistent_hp is False


def test_an_unverified_cooldown_says_so():
    d, got, _ = dash()
    d.refresh(force=True)
    assert any("unverified" in t.note for t in kinds(got, "Timer"))


# ------------------------------------------------------------------ prices --
def test_a_ticket_is_priced_through_the_jelly_dispenser():
    """THE NUMBER NO PLAYER HAS. 6 tickets buy a Royal Jelly at the dispenser
    and a jelly costs 250,000 honey at the shop, so a ticket is worth about
    41,667 honey. Derived from two cited observations, not asserted."""
    from hivemind.brain import knowledge
    d, got, _ = dash(knowledge=knowledge)
    d.refresh(honey_per_hour=2_854_895, force=True)
    ticket = next(p for p in kinds(got, "ShadowPrice") if p.resource == "Ticket")
    assert ticket.known
    assert 35_000 < ticket.honey_value < 50_000, ticket.honey_value
    assert "Royal Jelly" in ticket.basis


def test_a_resource_with_no_path_to_honey_is_reported_unknown_not_zero():
    from hivemind.brain import knowledge
    d, got, _ = dash(knowledge=knowledge)
    d.refresh(force=True)
    glitter = next(p for p in kinds(got, "ShadowPrice") if p.resource == "Glitter")
    assert glitter.known is False
    assert "no observed path" in glitter.basis


def test_pollen_is_priced_only_from_a_measured_convert():
    from hivemind.brain import knowledge
    d, got, _ = dash(knowledge=knowledge)
    d.refresh(force=True)                       # nothing measured yet
    pollen = next(p for p in kinds(got, "ShadowPrice") if p.resource == "Pollen")
    assert pollen.known is False

    d2, got2, _ = dash(knowledge=knowledge)
    d2.refresh(pollen_per_honey=0.9, force=True)
    pollen = next(p for p in kinds(got2, "ShadowPrice") if p.resource == "Pollen")
    assert pollen.known and 0.5 < pollen.honey_value < 1.5


def test_an_hour_is_priced_from_the_measured_rate():
    d, got, _ = dash()
    d.refresh(honey_per_hour=2_854_895, force=True)
    hour = next(m for m in kinds(got, "Metric") if m.name == "price_of_an_hour")
    assert abs(hour.value - 2_854_895) < 1


def test_without_a_measured_rate_time_has_no_price():
    d, got, _ = dash()
    d.refresh(force=True)
    assert not [m for m in kinds(got, "Metric") if m.name == "price_of_an_hour"]


# ------------------------------------------------------------------ fields --
def test_every_ranked_field_reaches_the_fields_tab():
    d, got, _ = dash()
    ranked = [Score("pineapple", 189.0, ("mantis", "rhino"), "measured 252/s"),
              Score("strawberry", 106.8, ("ladybug",), "never farmed"),
              Score("bamboo", 0.0, (), "no recorded route")]
    d.refresh(ranked=ranked, notes=Notes(), force=True)
    fields = kinds(got, "FieldStatus")
    assert {f.name for f in fields} == {"pineapple", "strawberry", "bamboo"}
    assert sum(f.recommended for f in fields) == 1
    assert next(f for f in fields if f.recommended).name == "pineapple"


def test_a_field_with_no_route_is_shown_rather_than_hidden():
    d, got, _ = dash()
    d.refresh(ranked=[Score("bamboo", 0.0, (), "no recorded route from the hive")],
              force=True)
    bamboo = next(f for f in kinds(got, "FieldStatus") if f.name == "bamboo")
    assert bamboo.recommended is False
    assert "no recorded route" in bamboo.note


def test_the_mob_count_and_last_visit_come_through():
    d, got, _ = dash()
    d.refresh(ranked=[Score("pineapple", 1.0, ("mantis", "rhino"))],
              notes=Notes(), force=True)
    f = kinds(got, "FieldStatus")[0]
    assert f.mobs == 2 and f.last_visited == 1234.0


# ----------------------------------------------------------------- account --
def test_the_account_tab_separates_measurement_from_testimony():
    from hivemind.brain import knowledge
    if not (config_dir() / knowledge.ACCOUNT_FILE).exists():   # the blank template: needs the owner's own file
        pytest.skip("reads the owner's own account.yaml (config dir); this install has the blank template")
    d, got, _ = dash(knowledge=knowledge)
    d.refresh(standing=Standing(), force=True)
    by = {b.name: b for b in kinds(got, "Belief")}
    assert by["honey"].source == "read from the HUD"
    assert by["honey"].confidence == 1.0
    # the hive's count is the bot's own read now (act/beemenu, 2026-10-01):
    # a measurement, dated by its own time; the inventory rows are still the
    # owner's screenshot, and say so
    assert by["bee types discovered"].source.startswith("measured")
    assert by["bee types discovered"].confidence == 1.0
    assert "screenshot" in by["tickets"].source
    assert by["tickets"].confidence < 1.0


def test_fields_gathered_in_are_reported_as_proof():
    d, got, _ = dash()
    d.refresh(standing=Standing(), force=True)
    proven = next(b for b in kinds(got, "Belief") if b.name == "fields gathered in")
    assert "proved by earning" in proven.source
    assert "pineapple" in str(proven.value)


def test_no_standing_means_no_invented_account_rows():
    d, got, _ = dash()
    d.refresh(force=True)
    assert not [b for b in kinds(got, "Belief") if b.name == "honey"]


# ------------------------------------------------------------------ vision --
def test_the_vision_tab_gets_what_each_detector_found():
    d, got, _ = dash()
    d.refresh(detections={"tokens": 30, "mob_bars": 1, "attack_disc": 0}, force=True)
    by = {m.name: m.value for m in kinds(got, "Metric")}
    assert by["seen_tokens"] == 30
    assert by["seen_mob_bars"] == 1
    assert by["seen_attack_disc"] == 0


# -------------------------------------------------------------------- gaps --
def test_the_panels_that_cannot_be_filled_say_why_once():
    d, got, _ = dash()
    d.refresh(force=True)
    gaps = [t for t in kinds(got, "Thought") if t.topic == "gap"]
    assert len(gaps) == len(GAPS) == 1
    text = " ".join(g.text for g in gaps)
    # the planters left the list 2026-10-21: publish_planters fills that panel
    assert "expiry sentinel" in text and "planter" not in text
    got.clear()
    d.refresh(force=True)
    assert not [t for t in kinds(got, "Thought") if t.topic == "gap"]


def test_every_gap_names_a_specific_blocker_and_what_would_fix_it():
    for gap in GAPS:
        assert len(gap.why) > 60, gap.panel
        assert "Show it" in gap.why, f"{gap.panel} does not say what would fix it"


def test_no_panel_is_ever_given_an_invented_row():
    """Planters and expiries cannot be read from the game, so nothing may
    publish one. This is the owner's rule: "dont add fake things for looks"."""
    from hivemind.brain import knowledge
    d, got, _ = dash(knowledge=knowledge)
    d.refresh(standing=Standing(), ranked=[Score("pineapple", 1.0)],
              notes=Notes(), honey_per_hour=1.0, detections={"tokens": 1},
              force=True)
    assert kinds(got, "Planter") == []
    assert kinds(got, "Expiry") == []


# ------------------------------------- the Fields tab was showing constants --
# THE OWNER: "the fields tab isnt linked". Two of the four things its own
# docstring promised were hardcoded: `health` defaulted to 1.0 and nothing ever
# set it, so every card drew a full green bar, and the token line read
# "0 tokens" for every field because the publisher passed a literal zero.
# Meanwhile the measured record sat in `brain.fieldnotes` and was never sent.

def _scored(field, why="", mobs=(), score=1.0):
    from types import SimpleNamespace
    return SimpleNamespace(field=field, score=score, mobs=tuple(mobs), why=why)


def test_a_field_carries_the_record_the_bot_actually_measured():
    from hivemind.brain.dashboard import Dashboard
    from hivemind.brain.fieldnotes import FieldNotes, Note
    sent = []
    notes = FieldNotes()
    notes.notes["rose"] = Note(field="rose", pollen=8_434, seconds=9.1,
                               visits=2, deaths=1, proven=True)
    Dashboard(sent.append).publish_fields(ranked=[_scored("rose")], notes=notes)
    field = next(e for e in sent if getattr(e, "name", "") == "rose")
    assert round(field.rate) == 927
    assert (field.pollen, field.visits, field.deaths) == (8_434, 2, 1)
    assert round(field.seconds, 1) == 9.1


def test_health_and_tokens_arrive_as_unknown_rather_than_as_good_news():
    """Field degradation is unverified and nothing counts tokens per field, so
    a confident 100% and a confident 0 are both inventions."""
    from hivemind.brain.dashboard import Dashboard
    sent = []
    Dashboard(sent.append).publish_fields(ranked=[_scored("rose")])
    field = next(e for e in sent if getattr(e, "name", "") == "rose")
    assert field.health < 0 and field.tokens < 0


def test_a_field_never_stood_in_reports_no_rate_rather_than_a_slow_one():
    from hivemind.brain.dashboard import Dashboard
    sent = []
    Dashboard(sent.append).publish_fields(ranked=[_scored("pepper")])
    field = next(e for e in sent if getattr(e, "name", "") == "pepper")
    assert field.rate == 0.0 and field.pollen == 0 and field.visits == 0
