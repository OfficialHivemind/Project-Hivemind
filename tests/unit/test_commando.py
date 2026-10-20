"""The Commando Chick (act/commando, G3): the Wealth Clock's walk cut where
Natro's Commando walk leaves it, Natro's obby to the stair, captures counted
only on the feed's word, every loss backed off, and a capture priced against
gathering (brain/value)."""
from __future__ import annotations

import yaml

from hivemind.act import commando
from hivemind.brain import blenderplan
from hivemind.datapaths import data


def test_the_way_is_the_clock_walk_to_natros_ladder_and_rotleft_then_its_own_legs():
    edges = yaml.safe_load(data("world", "natro_paths.yaml").read_text())["edges"]
    clock = next(e for e in edges if e["name"] == commando.VIA)
    cut = clock["steps"][:commando.VIA_UPTO + 1]
    # gtc-clock's "ladder 2" (nm_Walk(22.5, LeftKey)) and RotLeft 2: the same
    # last legs as gtq-brown's opening, which Natro's Commando walk shares
    assert cut[-3] == {"op": "walk", "keys": "a", "studs": 90.0}
    assert cut[-2:] == [{"op": "camera", "direction": "left"}] * 2
    # the clock goes on with Natro's 40 tiles forward; the chick's walk with 27
    assert clock["steps"][commando.VIA_UPTO + 1]["studs"] == 160.0
    assert commando.START[0] == {"op": "walk", "keys": "w", "studs": 108.0}


def test_the_obby_is_natros_and_it_ends_in_and_back_out_onto_the_stair():
    start, enter = commando.START, commando.ENTER
    assert start[-len(enter):] == enter
    assert [s["studs"] for s in enter if s["op"] == "walk"] == [20.0, 36.0, 2.0]
    jumps = [i for i, s in enumerate(start) if s["op"] == "jump"]
    assert len(jumps) == 6                       # five in the obby, ENTER's hop
    # each obby jump is taken walking forward (Natro's Space then nm_Walk Fwd)
    assert all(start[i + 1]["keys"] == "w" for i in jumps[:5])
    # 464: Natro's 480 less 4 tiles off the walk to the pit's edge (2026-10-13)
    assert sum(s.get("studs", 0) for s in start if s["op"] == "walk") == 464.0


def test_only_the_feeds_capture_is_counted_and_a_lost_bar_is_scheduled_like_one():
    t = 1_791_800_000.0
    got = commando.record({}, "killed", t, took=88.0)
    assert got["captures"] == 1 and got["tries"][-1]["took"] == 88.0
    assert not commando.due(got, t + commando.COOLDOWN_S - 1)
    assert commando.due(got, t + commando.COOLDOWN_S)
    gone = commando.record(got, "gone", t + 2000)
    assert gone["captures"] == 1 and gone["next_at"] == t + 2000 + commando.COOLDOWN_S


def test_every_loss_doubles_the_wait_absent_too_and_a_capture_resets_it():
    # the chick is always there unless just captured: no bar is a miss
    t = 1_791_800_000.0
    state = {}
    for k, result in enumerate(("absent", "fled", "died", "time", "walk")):
        state = commando.record(state, result, t)
        assert state["next_at"] == t + commando.LOST_RETRY_S * 2 ** k
    for _ in range(20):
        state = commando.record(state, "died", t)
    assert state["next_at"] == t + commando.LOST_RETRY_MAX_S
    assert commando.record(commando.record(state, "killed", t), "died", t)["next_at"] == \
        t + commando.LOST_RETRY_S


def test_the_feed_words():
    assert commando.defeated("Defeated Commando Chick!")
    assert commando.defeated("Captured Commando Chick! (25)")
    assert commando.defeated("defeatedcommandochick")          # tesseract runs words together
    assert commando.fled("Commando Chick fled! (HP Saved)")
    assert commando.fled("Commando Chick got away!")
    assert not commando.defeated("Commando Chick fled! (HP Saved)")
    assert not commando.defeated("Defeated Mondo Chick!")         # the other chick
    assert not commando.defeated("+250 Bond (from Commander Bee)")
    assert not commando.fled("Defeated Rhino Beetle! (+1 Battle Point)")
    # the whole feed is one line: a Clover Field kill beside the flee is no capture
    both = "Defeated Rhino Beetle! (+1 Battle Point) +205 Bond Commando Chick fled! (HP Saved)"
    assert commando.fled(both) and not commando.defeated(both)
    assert commando.defeated("Commando Chick has been captured!")


def test_a_capture_priced_and_its_milestones_agree_with_the_drops():
    # to the Gold Egg: honey 463,400 + 9 tickets (none at the 5th), a Stinger
    # (10 tickets), Glue and 2 Red Extract (10 Royal Jelly each), the egg
    # (100 tickets at the Ticket Tent)
    v, unpriced = commando.worth(1, 10)
    assert v == 463_400 + 900_000 + 1_000_000 + 2_500_000 + 5_000_000 + 10_000_000
    assert unpriced == []
    assert commando.worth(11, 15)[1] == ["star_jelly"]
    assert commando.worth(50, 50)[1] == ["mythic_egg"]
    for m in (k for k in blenderplan.COMMANDO_MILESTONES if k <= len(commando.HONEY)):
        assert set(commando.drops(m)) - {"honey", "ticket"} or commando.drops(m)["ticket"] == 100, m


def test_the_plan_line_says_how_far_and_prices_a_timed_visit():
    words = commando.outlook({}, 3747.0)
    assert words.startswith("Commando Chick 0 captured: Glue at 5, Gold Egg at 10, Star Jelly at 15")
    assert "no visit timed yet" in words
    t = 1_791_800_000.0
    state = {"captures": 9, "tries": [{"at": t, "result": "killed", "took": 120.0}]}
    words = commando.outlook(state, 3747.0)
    assert "Gold Egg at 10" in words and "captures 10-10" in words and "Q +" in words
    assert "SAVE" not in words                    # the plan line keeps the egg's name only


def test_the_switch_is_wired_and_ships_off():
    """Off as shipped (U15b); the owner's own file turns it on."""
    from hivemind.world.settings import defaults, wired
    assert wired("combat.commando") and defaults()["combat.commando"] is False


def test_two_obby_deaths_in_a_row_hold_the_fight_until_cleared_or_the_legs_change():
    # 2026-10-13 03:58 and 05:11: both tries died in the lava before the stair;
    # 23:05: one death after 4 crossings in 5 is a slip, not a hold
    t = 1_791_800_000.0
    assert commando.START == commando.OBBY + commando.ENTER
    slip = commando.record({}, "obby", t)
    assert not commando.held(slip) and commando.due(slip, t + commando.LOST_RETRY_S)
    assert not commando.held(commando.record(commando.record(slip, "killed", t), "obby", t))
    stuck = commando.record(slip, "obby", t)
    assert commando.held(stuck) and not commando.due(stuck, t + commando.LOST_RETRY_MAX_S)
    assert not commando.held(commando.record({}, "died", t))      # the chick's grenades: backed off only
    cleared = {k: v for k, v in stuck.items() if k != "held"}       # a person deletes "held"
    assert commando.due(cleared, t + 2 * commando.LOST_RETRY_S)
    fixed = dict(stuck, held={"at": t, "obby": "legs before a fix"})
    assert not commando.held(fixed) and commando.due(fixed, t + 2 * commando.LOST_RETRY_S)


def test_the_walk_waits_out_a_strong_haste_at_the_hedge_before_the_obbys_forward_legs():
    # act/commando.CALM_AT: the d7 after the a30 into the hedge (its last wall),
    # so the d7 and the a90 -- the obby's forward axis after RotLeft 2 -- are
    # walked at a factor the bar reads true, not x10's 2.0 (~1.68 really)
    edges = yaml.safe_load(data("world", "natro_paths.yaml").read_text())["edges"]
    clock = next(e for e in edges if e["name"] == commando.VIA)
    via = commando.via(clock["steps"])
    assert len(via) == commando.VIA_UPTO + 1
    assert [s for s in via if s.get("calm")] == [{"op": "walk", "keys": "d", "studs": 7.0,
                                                  "calm": "always"}]
    assert via[commando.CALM_AT - 2] == {"op": "walk", "keys": "a", "studs": 30.0}
    assert via[commando.CALM_AT + 2] == {"op": "walk", "keys": "a", "studs": 90.0}
    assert "calm" not in clock["steps"][commando.CALM_AT]      # a copy: the clock walk unchanged
