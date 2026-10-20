"""The voice says what the bot is thinking: its own lines, plainer (stream/thinking).

The owner, 2026-09-29: it should be smart and talk about what it is thinking,
what it wants to do and what it is doing. Every line below is a real one from
the bot's run logs.
"""
from __future__ import annotations

import random

import pytest

from hivemind.stream import thinking, voice
from hivemind.telemetry.events import Log, TaskUpdate

REAL = {
    "goal": "goals: next is the Honey Mask — 6,108,098 honey short, about 19 min of farming at "
            "19,377,652/h; also needs Oil 44/50; honey 93,891,902 (the HUD, 29 Sep 00:00)",
    "goal_hours": "goals: next is the Honey Mask — 43,318,106 honey short, about 2.3 h of farming at "
                  "18,691,143/h; also needs Oil 44/50; honey 56,681,894 (the HUD, 28 Sep 22:52)",
    "goal_ready": "goals: the honey for the Honey Mask is there (100,000,000); still needed: "
                  "Oil 44/50; honey 276,079,967 (the HUD, 29 Sep 07:40)",
    "bug_run": "the backpack is empty and we are on our own pad — a bug run: Werewolf due in pumpkin "
               "— drops worth about 55,000 honey (wiki honey and tickets at 100,000), 25 battle "
               "point(s), a run of at most 127s.",
    "booster_go": "the backpack is empty and we are on our own pad — going to the blue field booster "
                  "to use it (every 0.75h), about 52s there, for a field boost for 15 minutes to one "
                  "blue field, picked at random",
    "handin": "a finished quest is waiting to be handed in at brown bear, panda bear — going there "
              "before the shorter walks",
    "fly_quarantined": "flying to pine tree: the red cannon approach missed its last 1 try, but the walk "
                       "is quarantined, so the flight is tried again (3 misses in a row ground it); the "
                       "walk landed 0 of its last 10 (P 0.08, quarantined), 16,526 stud-equivalents; the "
                       "flight landed 10 of its last 10 (P 0.92), 622 stud-equivalents",
    "walk_draw": "walking to bamboo: the walk landed 10 of its last 10 (P 0.92), 937 stud-equivalents; "
                 "the flight landed 6 of its last 10 (P 0.58), 1,017 stud-equivalents — the bag is "
                 "empty, so the choice is a draw from each route's record: this one wins 60% of draws",
    "fly_new": "flying to clover: the walk landed 0 of its last 1 (P 0.33), 2,766 stud-equivalents; the "
               "flight never judged yet (even odds), 734 stud-equivalents — the bag is empty, so the "
               "choice is a draw from each route's record",
    "walk_new": "walking to clover: the walk never judged yet (even odds), 1,514 stud-equivalents; the "
                "flight never judged yet (even odds), 734 stud-equivalents — the bag is empty",
    "booster_yes": "booster: the next trip goes to bamboo and the blue field booster boosts it — 1 in 4 "
                   "that it picks bamboo, +100% for about 356s of the trip, when the boosted bag is full: "
                   "worth 89s of gathering against a 61s detour, so using it",
    "booster_no": "booster: the next trip goes to pineapple and the white field booster boosts it — 1 in "
                  "7 that it picks pineapple, +200% for about 217s of the trip, when the boosted bag is "
                  "full: worth 62s of gathering against a 119s detour, so not worth the walk",
    "buff": "waiting out a brown bear morph and Haste (about 3s) before the walk home — its glide "
            "lands short under a speed buff (0 of 3 tonight, against 7 of 7 without)",
    "bug_empty": "bug run done in 54s (walked) — pumpkin: no mob health bar and no hit on us in 35 "
                 "look(s) over 4 heading(s), 10.4s; the feed named Werewolf here",
    "respawn": "respawning to get home after the errand (the counter reads 0) — Natro's way back, and "
               "it keeps the server session",
}


def say(key):
    t = thinking.think(REAL[key], random.Random(1))
    assert t is not None, key
    return t


def test_the_goal_is_said_with_the_real_numbers():
    t = say("goal")
    assert "Honey Mask" in t.text and "6.1 million" in t.text and "19 minutes" in t.text
    assert "Oil, 44 of 50" in t.text and t.decision


def test_a_goal_hours_away_is_said_in_hours():
    t = say("goal_hours")
    assert "43.3 million" in t.text and "2.3 hours" in t.text


def test_the_honey_for_a_goal_being_there_is_said():
    assert "Honey Mask" in say("goal_ready").text and "Oil, 44 of 50" in say("goal_ready").text


def test_an_errand_says_what_it_is_for():
    assert "Werewolf" in say("bug_run").text and "Pumpkin" in say("bug_run").text
    t = say("booster_go").text
    assert "Blue Field Booster" in t and "field boost for 15 minutes" in t and "picked" not in t


def test_a_hand_in_names_both_bears_and_does_not_claim_a_walk():
    t = say("handin").text
    assert "Brown Bear and Panda Bear" in t
    assert "off to" not in t and "Heading" not in t, "the queue is not the walk"


def test_a_route_is_explained_by_its_record():
    t = say("fly_quarantined").text
    assert "cannon" in t and "0 of its last 10" in t and "10 of its last 10" in t
    t = say("walk_draw").text
    assert t.startswith("Walking to Bamboo") and "track record" in t


def test_a_route_never_tried_says_so():
    assert "first time" in say("fly_new").text and "cannon" in say("fly_new").text
    assert "first time" in say("walk_new").text and "walk" in say("walk_new").text


def test_a_booster_is_used_or_skipped_and_says_why():
    assert "worth about 89 seconds" in say("booster_yes").text
    assert "isn't worth" in say("booster_no").text


def test_details_are_said_too():
    assert "brown bear morph and Haste" in say("buff").text
    assert "Pumpkin" in say("bug_empty").text
    assert "costs me nothing" in say("respawn").text
    for key in ("buff", "bug_empty", "respawn"):
        assert not say(key).decision


@pytest.mark.parametrize("text", ["the world is back", "slot 1 (sprinkler): pressed, 3% changed",
                                  "chasing a token at (1,2)", "", "goals: something new entirely"])
def test_anything_else_is_not_a_thought(text):
    assert thinking.think(text) is None


@pytest.mark.parametrize("n,words", [("6,108,098", "6.1 million"), ("55,000", "55 thousand"),
                                     ("900", "900"), ("100,000,000", "100 million")])
def test_amounts(n, words):
    assert thinking.amount(n) == words


# ---- in the voice ---------------------------------------------------------------------
class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def announcer(clock, **over):
    got = {"stream.voice": True, "stream.voice_room": False, "stream.voice_banter": True,
           "gather.convert_at": 90, **over}
    return voice.Announcer(get=got.get, clock=clock, rng=random.Random(3),
                           chat_live=lambda: False, playing=lambda: True)


def test_the_bots_reasoning_is_said_and_not_twice_too_soon():
    clock = Clock()
    a = announcer(clock)
    a.hear(Log(message=REAL["goal"]))
    a.hear(Log(message=REAL["goal"]))
    assert [ln.kind for ln in a.waiting] == ["thought"]
    assert "Honey Mask" in a.next_line()


def test_a_quiet_stretch_says_what_the_bot_is_doing_before_any_joke():
    clock = Clock()
    a = announcer(clock)
    a._field = "pine_tree"
    a.hear(TaskUpdate(name="gather", status="running", progress=0.62))
    a.hear(Log(message=REAL["goal"]))
    said = []
    end = clock.t + voice.FIRST_BANTER_S - 1
    while clock.t < end:
        line = a.next_line()
        if line:
            said.append(line)
        clock.t += 1
    assert any("gathering in Pine Tree" in s and "62%" in s and "90%" in s for s in said), said
    assert any("working towards the Honey Mask" in s for s in said), said
    from hivemind.stream import banter
    assert not any(s in banter.JOKES for s in said), "no joke before FIRST_BANTER_S"


# ---- what it learns, and chat asking what it thinks ---------------------------------------
LEARNED = ("skills: natro_out_pine_tree_via_red_cannon landed — now landed 10 of its last 10 (P 0.92); "
           "natro_home_pine_tree landed — now landed 10 of its last 10 (P 0.92)")
MISSED = "skills: natro_out_bamboo_via_red_cannon elsewhere — now landed 3 of its last 9 (P 0.36)"


def test_what_a_route_taught_it_is_said():
    t = thinking.think(LEARNED, random.Random(1))
    assert t is not None and "cannon" in t.text and "Pine Tree" in t.text and "10" in t.text
    t = thinking.think(MISSED, random.Random(1))
    assert "didn't get me there" in t.text and "3 of its last 9" in t.text
    assert thinking.think("skills: 58 route(s) measured; quarantined, 95% sure each lands") is None


def test_chat_can_ask_what_it_is_thinking():
    from hivemind.stream import ask
    assert ask.intent_of("what are you thinking?") == "thinking"
    assert ask.intent_of("whats your plan") == "thinking"
    said = ask.answer_for("thinking", ask.Facts(thought="My next goal is the Honey Mask."),
                          random.Random(1))
    assert "Honey Mask" in said
    assert ask.answer_for("thinking", ask.Facts(field="bamboo"), random.Random(1))


def test_the_voice_keeps_its_latest_thought_for_chat():
    clock = Clock()
    a = announcer(clock)
    a.hear(Log(message=REAL["booster_yes"]))
    assert "Blue Field Booster" in a.last_thought


# ---- the half hour, looked back on --------------------------------------------------------
def test_every_half_hour_it_looks_back_on_what_it_did():
    from types import SimpleNamespace
    clock = Clock()
    a = announcer(clock)
    for head in ("Converted +3.6M", "Big convert +4.1M"):
        a.toasted(SimpleNamespace(kind="convert", title=head, body=""))
    for _ in range(3):
        a.hear(Log(message="reward feed: a Rhino Beetle was defeated (+1 battle point)"))
    a.hear(Log(message="chasing a honey token at (1110, 335), confidence 0.93, up to 4 step(s)"))
    a.waiting.clear()
    clock.t += voice.SUMMARY_EVERY_S + 1
    said = a.next_line()
    assert said and "7.7 million honey from 2 trips" in said, said
    assert "beat 3 bugs" in said and "chased 1 token" in said
    clock.t += voice.SUMMARY_EVERY_S + 1
    assert a._summary(clock.t) is None, "no trip banked, nothing to look back on"


def test_buying_hatching_and_fights_get_their_own_rows_and_the_pose_lines_none():
    # the owner, 2026-10-05: show it thinking about purchases too
    from hivemind.stream.show import category_of
    from hivemind.telemetry.events import Log
    cat = lambda text, source="farm": category_of(Log(message=text, source=source))  # noqa: E731
    assert cat("buying 1: Hive Slot (bee 37) at the Mountain Top Shop for 380,891,931 honey") == "shop"
    assert cat("goals: next is the Hive Slot (bee 37) — 120,834,850 honey short", "goals") == "shop"
    assert cat("buying a Basic Egg: bought it — 'Basic Egg | 10.000.000 Honey | Buy'", "items") == "shop"
    assert cat("egg hatch: answered Yes to 'hatch basic egg'", "items") == "hive"
    assert cat("reward feed: the Mantis dropped 410 honey", "combat") == "fight"
    assert cat("items: using Glue in the bamboo — Glue 1", "goals") == "item"
    assert cat("I am in the pine tree field (95% sure, feed, 0s ago)") is None
    assert cat("buff bar: haste x2 (icon score 0.97)") is None
    assert cat("died: a mantis knocked the character out") == "death"
