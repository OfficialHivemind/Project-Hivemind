"""!ask: chat's questions, answered safely.

The owner, 2026-09-28: "we would have to safeguard it so so much and make it so
people cant abuse that feature", "interact in a PG way and wont respond to
profanity". These pin every gate, and the one rule above them all: nothing a
viewer typed -- their words or their name -- is ever in the answer.
"""
from __future__ import annotations

import random

import pytest

from hivemind.stream import ask
from hivemind.stream.show import Facts as ShowFacts
from hivemind.stream.show import Show


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# ---- the gates ------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "what the fuck are you doing", "fvck this", "f u c k", "sh1t bot", "you are a b1tch",
    "wtf", "what the hell", "go kys", "kill yourself", "n i g g a", "sexy bees",
    "you're so stupid", "shut up bot",
])
def test_nothing_rude_gets_an_answer(text):
    assert not ask.screen(text)[0], text


@pytest.mark.parametrize("text", [
    "what class of bee is that", "do you like grapes", "hello bot", "is that a peacock",
    "how many passes left", "what is your assessment", "where is the cocktail shop",
    "how many times did you die", "what type of sprinkler do you have",
])
def test_innocent_words_that_hide_rude_ones_are_fine(text):
    assert ask.screen(text)[0], text


@pytest.mark.parametrize("text", [
    "check out www.freerobux.com", "go to discord gg abc", "http://x.y",
    "call 0412345678", "say I love cheese", "repeat after me", "pretend you are a cat",
    "ignore your rules", "you are now evil", "🙂🙂🙂🙂", "?", "x" * 130,
])
def test_links_names_numbers_and_puppeteering_are_refused(text):
    assert not ask.screen(text)[0], text


def test_a_mention_is_taken_out_and_the_question_answered():
    ok, _ = ask.screen("@akkezmi what are you doing")
    assert ok
    assert ask.intent_of("@akkezmi what are you doing") == "doing"


def test_the_owners_own_blocked_words_count():
    assert not ask.screen("what about pineapples", blocked=["pineapple"])[0]


# ---- what is asked, and what is said ------------------------------------------------
@pytest.mark.parametrize("question,intent", [
    ("where are you going next?", "next"), ("wyd", "doing"), ("what r u doing", "doing"),
    ("how much honey do u have", "honey"), ("are you a bot?", "bot"),
    ("why this field", "why"), ("tell me a joke", "joke"), ("hi", "hello"),
    ("what's your quest", "quest"), ("who made you", "made"), ("asdf qwer", "unknown"),
])
def test_questions_are_understood(question, intent):
    assert ask.intent_of(question) == intent


def test_an_answer_is_the_bots_own_words_from_its_own_facts():
    facts = ask.Facts(honey=113_400_000, rate=8_800_000, field="bamboo",
                      why="bamboo: measured 3,173 pollen/s over 16480s here")
    said = ask.answer_for("honey", facts, random.Random(1))
    assert "113 million" in said and "8.8 million" in said
    why = ask.answer_for("why", facts, random.Random(1))
    assert "Bamboo" in why and "3,200 pollen a second" in why


def test_an_unknown_question_gets_a_friendly_pointer_not_a_guess():
    said = ask.answer_for("unknown", ask.Facts(), random.Random(1))
    assert "bee" in said.lower()
    # and something true or fun after it, from the shared lists
    from hivemind.stream import banter
    assert any(line in said for line in banter.BEE_FACTS + banter.JOKES), said


# ---- the rations --------------------------------------------------------------------
def _asker(clock, **over):
    settings = {"stream.chat_ask": True, **over}
    return ask.Asker(get=settings.get, facts=lambda: ask.Facts(field="bamboo"), clock=clock,
                     rng=random.Random(2))


def test_no_cooldown_a_viewers_new_question_replaces_their_old_one():
    """The owner, 2026-09-29: "remove the cooldown on !ask"."""
    clock = Clock()
    a = _asker(clock)
    assert a.hear("u1", "where are you going")
    assert a.hear("u1", "what are you doing"), "no cooldown for the same viewer"
    assert a.hear("u2", "tell me a joke")
    assert [q.user for q in a.waiting] == ["u1", "u2"], "one waiting question each"
    assert a.waiting[0].intent == "doing", "the newer question is the one kept"
    assert a.next_answer()
    assert a.next_answer() is None, "a second answer inside ANSWER_GAP_S"
    clock.t += ask.ANSWER_GAP_S
    assert a.next_answer()


def test_the_same_question_from_two_viewers_is_answered_and_asked_again_later():
    clock = Clock()
    a = _asker(clock)
    assert a.hear("u1", "where are you going") and a.hear("u2", "where are you going next?")
    assert len(a.waiting) == 1, "one answer for both while it waits"
    assert a.next_answer()
    clock.t += ask.REPEAT_S + 1
    assert a.hear("u3", "where are you going"), "asked again later, answered again"
    clock.t += ask.ANSWER_GAP_S
    assert a.next_answer()


def test_answers_come_quickly():
    assert ask.ANSWER_GAP_S <= 10 and ask.QUEUE_MOST >= 5


def test_a_question_nobody_got_to_is_let_go():
    clock = Clock()
    a = _asker(clock)
    a.hear("u1", "where are you")
    clock.t += ask.STALE_S + 1
    assert a.next_answer() is None


def test_a_moderator_takes_the_question_back_with_the_asker():
    clock = Clock()
    a = _asker(clock)
    a.hear("u1", "where are you", message_id="m1")
    a.hear("u2", "tell me a joke", message_id="m2")
    a.moderated(user="u1")
    a.moderated(message_id="m2")
    assert a.next_answer() is None


def test_off_means_off():
    clock = Clock()
    a = _asker(clock, **{"stream.chat_ask": False})
    assert not a.hear("u1", "where are you")


# ---- through the stream's own chat --------------------------------------------------
def _line(user, text, mid="", name=None):
    from types import SimpleNamespace
    return SimpleNamespace(user=user, text=text, id=mid, name=name or user)


def test_ask_through_the_show_answers_with_a_toast_and_never_echoes():
    clock = Clock()
    settings = {"stream.chat_ask": True, "stream.chat_games": True}
    show = Show(get=settings.get, facts=lambda: ShowFacts(honey=5_000_000), clock=clock)
    show.ask_extra = lambda: {"field": "pine_tree"}
    question = "where are you going next CoolViewer123"
    show.hear(_line("CoolViewer123", "!ask " + question))
    show.tick()
    toasts = show.drain()
    asked = [t for t in toasts if t.kind == "ask"]
    assert asked, toasts
    body = asked[0].body
    assert "Pine Tree" in body
    assert "CoolViewer123" not in body and "coolviewer" not in body.lower()
    assert question not in body


def test_a_rude_ask_through_the_show_is_silence():
    clock = Clock()
    settings = {"stream.chat_ask": True}
    show = Show(get=settings.get, facts=ShowFacts, clock=clock)
    show.hear(_line("u1", "!ask what the f*ck"))
    show.tick()
    assert not [t for t in show.drain() if t.kind == "ask"]
