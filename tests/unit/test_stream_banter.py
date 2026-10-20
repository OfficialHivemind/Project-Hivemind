"""The voice's fun: jokes, facts and quips in the quiet stretches, a quip for a
character pushing against a wall, and running counts -- all PG, all on cue.

The owner, 2026-09-28: "can u make the ai be entertaining and come up with
funy stuf to say".
"""
from __future__ import annotations

import random

import pytest

from hivemind.stream import ask, banter, voice
from hivemind.telemetry.events import Log, Thought


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


SETTINGS = {"stream.voice": True, "stream.voice_room": False, "stream.voice_banter": True}


def announcer(clock, playing=True, **over):
    got = dict(SETTINGS, **over)
    return voice.Announcer(get=got.get, clock=clock, rng=random.Random(7),
                           chat_live=lambda: False, playing=lambda: playing)


def drain(a, clock, seconds, step=1.0):
    said = []
    end = clock.t + seconds
    while clock.t < end:
        line = a.next_line()
        if line:
            said.append(line)
        clock.t += step
    return said


# ---- the lines ----------------------------------------------------------------------
@pytest.mark.parametrize("line", banter.JOKES + banter.QUIPS + banter.BEE_FACTS)
def test_every_line_is_pg(line):
    assert not ask.rude(line), line
    assert "http" not in line and "@" not in line


def test_chat_and_the_voice_share_the_jokes():
    assert ask.JOKES is banter.JOKES and ask.BEE_FACTS is banter.BEE_FACTS


def test_the_deck_takes_turns_and_repeats_nothing_until_all_are_said():
    deck = banter.Deck(["a1", "a2"], ["b1"], rng=random.Random(1))
    first = [deck.next() for _ in range(4)]
    assert first[0].startswith("a") and first[1] == "b1" and first[2].startswith("a")
    assert {first[0], first[2]} == {"a1", "a2"}, "both a's before either comes round"


# ---- when the banter comes ------------------------------------------------------------
def test_banter_fills_a_quiet_stretch_at_its_own_pace():
    clock = Clock()
    a = announcer(clock)
    assert drain(a, clock, voice.FIRST_BANTER_S - 1) == [], "nothing before FIRST_BANTER_S"
    said = drain(a, clock, 10 * voice.BANTER_EVERY_S)
    everything = set(banter.JOKES + banter.QUIPS + banter.BEE_FACTS)
    assert said and all(s in everything for s in said)
    assert len(said) <= 11, f"at most one per BANTER_EVERY_S: {len(said)}"
    assert len(set(said)) == len(said), "no repeats"


def test_no_banter_when_off_or_not_playing():
    for kwargs in ({"stream.voice_banter": False}, {}):
        clock = Clock()
        a = announcer(clock, playing=bool(kwargs), **kwargs)
        assert drain(a, clock, 600) == []


# ---- stuck --------------------------------------------------------------------------------
def _where(seconds=None):
    text = "I am in the bamboo field (90% sure, feed, 1s ago) · facing spawn heading"
    if seconds is not None:
        text += f" · pushing against something for {seconds}s"
    return Thought(topic="where", text=text)


def test_a_long_push_gets_a_quip_then_one_more_and_no_more():
    clock = Clock()
    a = announcer(clock, **{"stream.voice_banter": False})
    for s in (3, 10, 16, 30, 45):
        a.hear(_where(s))
    assert [ln.kind for ln in a.waiting] == ["stuck"]
    a.hear(_where(61))
    a.hear(_where(90))
    assert [ln.kind for ln in a.waiting] == ["stuck", "stuck_long"]


def test_a_new_push_soon_after_is_not_said_again():
    clock = Clock()
    a = announcer(clock, **{"stream.voice_banter": False})
    a.hear(_where(20))
    a.hear(_where())                      # free again
    clock.t += 30
    a.hear(_where(20))
    assert [ln.kind for ln in a.waiting] == ["stuck"]
    a.hear(_where())
    clock.t += voice.STUCK_EVERY_S
    a.hear(_where(20))
    assert [ln.kind for ln in a.waiting] == ["stuck", "stuck"]


# ---- counts ------------------------------------------------------------------------------
def test_the_third_spider_is_counted_out_loud():
    clock = Clock()
    a = announcer(clock, **{"stream.voice_banter": False})
    for _ in range(3):
        a.hear(Log(message="reward feed: a spider was defeated (+10 battle points)"))
    kinds = [ln.kind for ln in a.waiting]
    assert kinds[-1] == "kill_count" and "3 Spiders" in a.waiting[-1].text


def test_the_fifth_chase_is_counted():
    clock = Clock()
    a = announcer(clock, **{"stream.voice_banter": False})
    for _ in range(5):
        a.hear(Log(message="chasing a token at (768, 461), confidence 0.88, up to 4 step(s)"))
    assert a.waiting[-1].kind == "token_count" and "5" in a.waiting[-1].text


@pytest.mark.parametrize("name,many", [("Spider", "Spiders"), ("Werewolf", "Werewolves"),
                                       ("Mantis", "Mantises"), ("Rhino Beetle", "Rhino Beetles")])
def test_plurals(name, many):
    assert voice.plural(name) == many


# ---- chat's answers first ---------------------------------------------------------------
def test_an_answer_to_chat_is_said_before_the_bots_own_news_and_again_if_asked_again():
    from types import SimpleNamespace
    clock = Clock()
    a = announcer(clock, **{"stream.voice_banter": False})
    a._add("banked", voice.EVENT, amount="3.4 million")
    a.toasted(SimpleNamespace(kind="ask", title="Chat asked", body="I'm heading to Pine Tree next!"))
    assert a.next_line() == "I'm heading to Pine Tree next!"
    clock.t += voice.GAP_S + 1
    a.next_line()                                   # the honey line
    clock.t += voice.GAP_S + 1
    a.toasted(SimpleNamespace(kind="ask", title="Chat asked", body="I'm heading to Pine Tree next!"))
    assert a.next_line() == "I'm heading to Pine Tree next!", "the same answer to a new asker"
