"""The compass and the map pin. See world/bearings for what each signal may claim."""
from __future__ import annotations

import pytest

from hivemind.vision import landmarks as lm
from hivemind.world.bearings import Bearings, FLOOR, TAPS_PER_FULL_TURN

TABLE = lm.Table({
    "hive": {"kind": "hive", "router_node": "hive", "prompts": [
        {"text": "make honey", "mine": True}, {"text": "claim hive", "mine": False}]},
    "red_cannon": {"kind": "transport", "router_node": "red_cannon",
                   "prompts": ["fire the red cannon"]},
})


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def tick(self, seconds):
        self.t += seconds


class Reading:
    def __init__(self, value, ok=True):
        self.value, self.ok = value, ok


class Fix:
    def __init__(self, field, at):
        self.field, self.at = field, at


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def b(clock):
    return Bearings(TABLE, clock=clock)


# ---------------------------------------------------------------- nothing --
def test_it_starts_knowing_nothing(b):
    assert b.where() is None
    assert b.at("hive") is None
    assert b.in_field() is None
    assert b.shift_lock is None
    assert "nowhere I can confirm" in b.describe()


# ------------------------------------------------------------------ panel --
def test_the_panel_is_an_instant_certain_fix(b):
    b.saw_panel("Make Honey")
    assert b.at("hive") is True
    assert b.on_my_pad() is True
    assert b.in_field() is False
    assert b.where().source == "panel"


def test_a_free_pad_is_the_hive_but_not_our_pad(b):
    b.saw_panel("Claim Hive")
    assert b.at("hive") is True
    assert b.on_my_pad() is False


def test_an_absent_panel_means_not_at_a_landmark(b):
    """MEASURED: the prompt vanishes the moment the character steps off."""
    b.saw_panel("Make Honey")
    b.saw_panel("")
    assert b.at("hive") is False
    assert b.on_my_pad() is False
    assert b.at("red_cannon") is False


def test_could_not_look_says_nothing(b):
    b.saw_panel("Make Honey")
    b.saw_panel(None)
    assert b.at("hive") is True


def test_a_panel_fix_dies_quickly_when_not_refreshed(b, clock):
    b.saw_panel("Make Honey")
    clock.tick(30)
    assert b.where() is None
    assert b.at("hive") is None


def test_a_notification_on_the_panel_is_not_a_place(b):
    b.saw_panel("Make Honey")
    b.saw_panel("You've made 5 Honey")
    # The text was not a prompt, so we are no longer at the landmark it named.
    assert b.at("hive") is not True


def test_the_cannon_is_a_landmark_too(b):
    mark = b.saw_panel("Fire the Red Cannon")
    assert mark is not None and mark.place == "red_cannon"
    assert b.at("red_cannon") is True
    assert b.at("hive") is False


# ------------------------------------------------------------------- feed --
def test_the_feed_names_the_field(b, clock):
    b.saw_feed(Fix("pumpkin", clock()))
    assert b.in_field() == "pumpkin"
    assert b.at("pumpkin") is True
    assert b.at("hive") is False
    assert b.where().source == "feed"


def test_a_feed_fix_goes_stale_after_a_walk_s_worth_of_time(b, clock):
    b.saw_feed(Fix("pumpkin", clock()))
    clock.tick(120)
    assert b.in_field() is None
    assert b.where() is None


def test_the_feed_beats_a_stale_spawn_belief(b, clock):
    b.spawned()
    b.saw_feed(Fix("pineapple", clock()))
    assert b.where().name == "pineapple"
    assert b.at("hive") is False


# ----------------------------------------------------------------- pollen --
def test_a_rising_counter_means_some_field(b, clock):
    assert b.saw_pollen(Reading(1000)) is None       # nothing to compare yet
    clock.tick(3)
    assert b.saw_pollen(Reading(1500)) is True
    assert b.in_field() is True
    assert b.where().name == "a field"


def test_a_flat_counter_proves_nothing(b, clock):
    b.saw_pollen(Reading(1000))
    clock.tick(3)
    assert b.saw_pollen(Reading(1000)) is False
    assert b.in_field() is None


def test_an_unreadable_counter_is_ignored(b):
    assert b.saw_pollen(Reading(None, ok=False)) is None
    assert b.saw_pollen(None) is None


def test_the_panel_overrides_a_rising_counter(b, clock):
    """Standing on a pad is standing on a pad, whatever the last pickup did."""
    b.saw_pollen(Reading(1000)); clock.tick(2); b.saw_pollen(Reading(2000))
    b.saw_panel("Make Honey")
    assert b.in_field() is False


# ------------------------------------------------------------------ heard --
def test_the_model_is_believed_weakly_and_only_coarsely(b):
    b.heard("The player character is inside a hive, as indicated by the "
            "hexagonal walls.")
    place = b.where()
    assert place is not None and place.name == "hive"
    assert place.confidence < 0.5          # never strong enough alone to say False
    assert b.at("pumpkin") is None


def test_the_model_loses_to_the_panel(b):
    b.heard("the player is in a field surrounded by flowers")
    b.saw_panel("Make Honey")
    assert b.where().source == "panel"
    assert b.in_field() is False


def test_the_model_saying_nothing_useful_changes_nothing(b):
    b.heard("a screenshot from a video game")
    b.heard(None)
    assert b.where() is None


# ------------------------------------------------------------------ spawn --
def test_a_spawn_resets_everything_to_known(b, clock):
    b.turned(5); b.toggled_shift_lock()
    b.saw_feed(Fix("pumpkin", clock()))
    b.spawned()
    assert b.heading_taps == 0
    assert b.shift_lock is False
    assert b.at("hive") is True
    assert b.in_field() is False
    assert b.where().source == "spawn"


def test_moving_kills_landmark_fixes_but_not_a_field_fix(b, clock):
    b.saw_panel("Make Honey")
    b.moved("route")
    assert b.at("hive") is None
    b.saw_feed(Fix("pumpkin", clock()))
    b.moved("pattern pass")
    assert b.in_field() == "pumpkin"


# ---------------------------------------------------------------- heading --
def test_heading_wraps_at_one_full_turn(b):
    b.turned(TAPS_PER_FULL_TURN)
    assert b.heading_taps == 0 and b.taps_to_square() == 0
    b.turned(3)
    assert b.heading_degrees == 135.0


def test_squaring_up_goes_the_short_way_round(b):
    b.turned(3)
    assert b.taps_to_square() == -3           # three left
    b.turned(3)                               # now 6
    assert b.taps_to_square() == 2            # two right, not six left
    b.turned(-6)
    assert b.taps_to_square() == 0


def test_left_taps_are_negative(b):
    b.turned(-1)
    assert b.heading_taps == TAPS_PER_FULL_TURN - 1
    assert b.taps_to_square() == 1


def test_shift_lock_is_a_parity(b):
    b.spawned()
    b.toggled_shift_lock(); assert b.shift_lock is True
    b.toggled_shift_lock(); assert b.shift_lock is False


def test_shift_lock_stays_unknown_until_a_spawn_says(b):
    b.toggled_shift_lock()
    assert b.shift_lock is None


def test_a_claim_records_where_the_pad_is(b):
    b.spawned()
    b.claimed(steps_forward=2, at_taps=3)
    assert b.pad_offset == (2, 3)
    assert b.on_my_pad() is True


# -------------------------------------------------------------- reporting --
def test_describe_names_the_source_and_the_heading(b, clock):
    b.spawned(); b.turned(2); b.saw_panel("Make Honey")
    text = b.describe()
    assert "our own hive pad" in text and "panel" in text
    assert "90° right of spawn heading" in text
    assert "shift lock off" in text


def test_changes_are_announced_once_each():
    said = []
    b = Bearings(TABLE, clock=lambda: 0.0, emit=said.append)
    b.saw_panel("Make Honey")
    b.saw_panel("Make Honey")
    thoughts = [e for e in said if getattr(e, "kind", "") == "thought"]
    assert len(thoughts) == 1
    assert "our own hive pad" in thoughts[0].text


def test_the_floor_is_where_a_fresh_fix_has_halved():
    assert 0.4 < FLOOR < 0.5


# ----------------------------------------------------------------- threats --
def test_a_threat_is_remembered_briefly_and_said(b, clock):
    b.spawned()
    b.saw_threat("mob health bar 376x56 at (1392, 244)")
    assert "THREAT: mob health bar" in b.describe()
    clock.tick(4)
    assert b.threat() is not None
    clock.tick(4)
    assert b.threat() is None
    assert "THREAT" not in b.describe()


def test_a_spawn_forgets_the_threat(b):
    b.saw_threat("a red attack disc")
    b.spawned()
    assert b.threat() is None


def test_an_empty_report_is_ignored(b):
    b.saw_threat("")
    assert b.threat() is None and b.threats_seen == 0


def test_a_successful_claim_applies_its_camera_taps_to_the_heading():
    """IT DID NOT, and that was silent.

    `claimed()` stored the sweep's taps in `pad_offset` and stopped, so after a
    successful claim the compass believed the camera was still at spawn
    heading. `journey.square_up` then had nothing to undo and the route ran
    however far round the sweep had left it. The caller's `else` branch already
    called `turned()` when the claim FAILED, which is the wrong way round.

    `sweep_and_claim` taps a whole turn before picking a bearing, so its
    total is 8 + the bearing, and 8 taps modulo a full turn is zero -- which
    is why every live run so far got away with it: all of them picked bearing
    0 ("strongest bearing at 0° (0 px)").
    """
    from hivemind.world.bearings import Bearings
    from hivemind.vision import landmarks as lm
    table = lm.Table({"hive": {"kind": "hive", "router_node": "hive",
                               "prompts": [{"text": "make honey", "mine": True}]}})

    b = Bearings(table, clock=lambda: 0.0)
    b.spawned()
    b.claimed(2, 8)                      # a full turn: back where it was
    assert b.heading_taps == 0
    assert b.taps_to_square() == 0

    b = Bearings(table, clock=lambda: 0.0)
    b.spawned()
    b.claimed(2, 8 + 3)                  # a full turn, then three more
    assert b.heading_taps == 3, "the sweep's real turn was not recorded"
    assert b.taps_to_square() == -3, "squaring up would not have undone it"


def test_a_claim_still_reports_where_the_pad_is():
    from hivemind.world.bearings import Bearings
    from hivemind.vision import landmarks as lm
    table = lm.Table({"hive": {"kind": "hive", "router_node": "hive",
                               "prompts": [{"text": "make honey", "mine": True}]}})
    b = Bearings(table, clock=lambda: 0.0)
    b.spawned()
    b.claimed(2, 11)
    assert b.pad_offset == (2, 3)
    assert b.on_my_pad() is True
