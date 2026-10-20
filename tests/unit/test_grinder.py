"""ROADMAP H16: the gifted Basic Bee grinder (brain/grinder)."""
import importlib.util
import re
from pathlib import Path

import hivemind
from hivemind.brain import grinder as g
from hivemind.world.settings import BOUNDS, READ_AT_EVERY_USE, SECTIONS

ROOT = Path(hivemind.__file__).resolve().parents[2]
SCHEMA = {e[0]: e for _, entries in SECTIONS for e in entries}
TYPES = {"basic": {"label": "Basic Bee", "rarity": "common"},
         "rad": {"label": "Rad Bee", "rarity": "rare"},
         "tadpole": {"label": "Tadpole Bee", "rarity": "mythic"},
         "cobalt": {"label": "Cobalt Bee", "rarity": "event"}}
M = 10_000_000


def step(**kw):
    args = dict(on=True, slot=9, max_honey=5 * M, max_jellies=3, state={}, session="s1",
                read={}, read_gifted=(), read_at=0.0, owned=9, bees=8,
                have={"basic": 0, "rad": 3}, types=TYPES, stale="", eggs_held=1,
                jelly_spare=5, honey=50 * M, egg_price=M, may_buy=True, replace_live=False)
    args.update(kw)
    return g.next_step(**args)


def mine(bee, gifted=False, **kw):
    return dict(slot=9, bee=bee, gifted=gifted, at=100.0, **kw)


def test_off_by_default_and_without_a_slot():
    assert SCHEMA[g.ON][3] is False
    assert SCHEMA[g.SLOT][3] == 0 and BOUNDS[g.SLOT][:2] == (0, 50)
    assert all(k in READ_AT_EVERY_USE for k in (g.ON, g.SLOT, g.MAX_HONEY, g.MAX_JELLIES))
    assert step(on=False).do == "off"
    assert step(slot=0).do == "off"


def test_the_one_empty_slot_is_hatched_live_any_other_only_said():
    s = step()
    assert (s.do, s.live) == ("hatch", True)
    # two empty slots: the hatch would need aiming (H13d, look-only)
    s = step(owned=10, read={i: "rad" for i in range(1, 9)}, read_at=5.0)
    assert (s.do, s.live) == ("hatch", False) and "HATCH_AIM_LIVE" in s.why
    assert "would" in s.said(9)


def test_an_egg_is_bought_only_for_a_live_step_and_in_budget():
    s = step(eggs_held=0)
    assert (s.do, s.live) == ("buy_egg", True)
    assert not step(eggs_held=0, owned=10, read={i: "rad" for i in range(1, 9)},
                    read_at=5.0).live
    assert step(eggs_held=0, may_buy=False).do == "wait"
    assert step(eggs_held=0, egg_price=None).do == "wait"
    assert step(eggs_held=0, honey=M - 1).do == "wait"
    spent = {"session": {"id": "s1", "honey": 5 * M}}
    assert step(eggs_held=0, state=spent).do == "stop"
    # a new session starts the budget again
    assert step(eggs_held=0, state=spent, session="s2").live


def test_the_basic_bee_is_jellied_live_only_when_it_is_the_only_one():
    s = step(owned=9, bees=9, state=mine("basic"), have={"basic": 1})
    assert (s.do, s.live) == ("jelly", True)
    s = step(owned=9, bees=9, state=mine("basic"), have={"basic": 3})
    assert (s.do, s.live) == ("jelly", False)
    s = step(owned=9, bees=9, state={**mine("basic"), "session": {"id": "s1", "jellies": 3}},
             have={"basic": 1})
    assert s.do == "stop" and "budget" in s.why
    assert step(owned=9, bees=9, state=mine("basic"), have={"basic": 1},
                jelly_spare=0).do == "wait"


def test_an_egg_on_a_full_slot_is_look_only_until_measured():
    s = step(owned=9, bees=9, state=mine("rad"), have={"rad": 1})
    assert (s.do, s.live) == ("replace", False) and "not measured" in s.why
    s = step(owned=9, bees=9, state=mine("rad"), have={"rad": 1}, replace_live=True)
    assert (s.do, s.live) == ("replace", True)
    # and no egg is bought for a step that only says "would"
    s = step(owned=9, bees=9, state=mine("rad"), have={"rad": 1}, eggs_held=0)
    assert (s.do, s.live) == ("buy_egg", False)


def test_any_gifted_or_mythic_stops_and_is_kept():
    assert step(owned=9, bees=9, state=mine("basic", gifted=True)).why.startswith("DONE")
    assert step(owned=9, bees=9, state=mine("rad", gifted=True)).do == "stop"
    assert step(owned=9, bees=9, state=mine("tadpole")).do == "stop"
    assert step(owned=9, bees=9, state=mine("cobalt")).do == "stop"
    # a per-slot read showing a gifted bee there stops it too
    assert step(owned=9, bees=9, read={9: "rad"}, read_gifted={9}, read_at=5.0).do == "stop"
    # a kept stop for this slot stands until the owner re-arms it
    assert step(state={"slot": 9, "done": "DONE: x"}).do == "stop"
    assert step(state={"slot": 3, "done": "DONE: x"}).do == "hatch"


def test_seen_keeps_the_card_and_says_when_to_stop():
    st = {}
    assert g.seen(st, 9, "basic", False, "common", 1.0) == ""
    assert st["bee"] == "basic" and "done" not in st
    assert g.seen(st, 9, "basic", True, "common", 2.0).startswith("DONE")
    assert "kept" in g.seen({}, 9, "rad", True, "rare", 1.0)
    assert "Mythic" in g.seen({}, 9, "tadpole", False, "mythic", 1.0)
    assert g.seen({}, 9, None, False, "", 1.0)            # an unread card stops


def test_unknown_or_stale_waits():
    assert step(stale="the bee menu changed").do == "wait"
    assert step(owned=9, bees=9).do == "wait"              # full slot, nobody saw it
    assert step(slot=12).do == "wait"                      # not bought


def test_spend_is_per_session():
    st = g.add_spend({}, "a", honey=M, eggs=1)
    g.add_spend(st, "a", jellies=1)
    assert g.spent(st, "a") == {"honey": M, "jellies": 1, "eggs": 1}
    assert g.spent(st, "b") == {"honey": 0, "jellies": 0, "eggs": 0}


def test_run_farm_wires_it_look_only_where_unmeasured():
    farm = (ROOT / "scripts" / "run_farm.py").read_text()
    assert re.search(r"^GRIND_REPLACE_LIVE = False$", farm, re.M)
    assert re.search(r'^GRIND_REPLACE_QUESTION = ""$', farm, re.M)
    for name in ("grind_at_the_pad()", "grind_step()", "not grind_claims(slot)",
                 "on_card=lambda card: grind_saw("):
        assert name in farm


def test_the_stop_alerts_and_pings(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "telegram_alerts_grind", ROOT / "scripts" / "telegram_alerts.py")
    tg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tg)
    line = "12:00:01  " + g.STOPPED + "DONE: a GIFTED BASIC BEE in slot 9"
    on = tmp_path / "settings.yaml"
    on.write_text("telegram.alerts: true\n")          # the master ships off (U15b)
    kind, photo, msg = tg.triage(line, {}, 0.0, settings=on)
    assert kind == "telegram.alerts" and photo and "GIFTED BASIC BEE in slot 9" in msg
    assert tg.PING_IF.search(msg)
    assert tg.triage("12:00:01  " + g.LINE + " would: hatch", {}, 0.0, settings=on) is None
