"""The subscriber goal: YouTube's own count, the next round number, and a
thank-you only for a count above the best already seen (stream/subs).

The owner, 2026-09-28: the stream should win subscribers.
"""
from __future__ import annotations

import io
import json
import random
import urllib.parse

import pytest

from hivemind.stream import chat, subs
from hivemind.stream.voice import Announcer


# ---- the goal ---------------------------------------------------------------------
@pytest.mark.parametrize("count,goal", [(0, 10), (9, 10), (10, 25), (96, 100), (99, 100),
                                        (100, 150), (749, 750), (4999, 5000),
                                        (5000, 10000), (12345, 15000)])
def test_the_goal_is_the_next_round_number(count, goal):
    assert subs.goal_for(count) == goal


def test_the_bar_runs_from_the_last_round_number_to_the_next():
    assert subs.progress(96) == pytest.approx((96 - 50) / 50)
    assert subs.progress(100) == 0.0
    assert subs.progress(0) == 0.0
    assert 0.0 <= subs.progress(12345) <= 1.0


# ---- what is news -------------------------------------------------------------------
def test_the_first_count_is_not_a_new_subscriber():
    t = subs.Tracker()
    assert t.seen(96) is None
    assert t.count == 96 and t.goal == 100


def test_one_more_is_thanked_and_a_dip_and_back_is_not():
    t = subs.Tracker()
    t.seen(96)
    change = t.seen(97)
    assert change is not None and change.new == 1 and change.goal == 100 and not change.reached
    assert t.seen(96) is None, "a dip is not news"
    assert t.seen(97) is None, "coming back from a dip is not a new subscriber"
    assert t.seen(99).new == 2


def test_passing_a_round_number_says_so():
    t = subs.Tracker()
    t.seen(99)
    change = t.seen(101)
    assert change.reached == 100 and change.goal == 150


# ---- YouTube's answer ------------------------------------------------------------------
def test_the_count_is_read_from_youtubes_answer():
    answer = {"items": [{"id": "UC" + "a" * 22,
                         "statistics": {"subscriberCount": "96", "hiddenSubscriberCount": False}}]}
    assert chat.subscriber_count(answer) == 96
    hidden = {"items": [{"statistics": {"subscriberCount": "96", "hiddenSubscriberCount": True}}]}
    assert chat.subscriber_count(hidden) is None, "a hidden count stays hidden"
    for junk in ({}, {"items": []}, {"items": [{}]}, [],
                 {"items": [{"statistics": {"subscriberCount": "-3"}}]},
                 {"items": [{"statistics": {"subscriberCount": "lots"}}]}):
        assert chat.subscriber_count(junk) is None, junk


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _YouTube:
    """Answers the reader's requests the way the Data API does, and keeps
    what was asked. `subs_fail` makes the statistics read time out."""

    def __init__(self, count=96, subs_fail=False):
        self.count = count
        self.subs_fail = subs_fail
        self.asked: list = []

    def open(self, request, timeout=None):
        url = urllib.parse.urlsplit(request.full_url)
        query = urllib.parse.parse_qs(url.query)
        method = url.path.rsplit("/", 1)[-1]
        self.asked.append((method, query.get("part", [""])[0]))
        assert request.get_header("X-goog-api-key"), "the key goes in the header"
        assert "key=" not in request.full_url, "never in the URL"
        if method == "channels" and query.get("part") == ["statistics"]:
            if self.subs_fail:
                raise TimeoutError("timed out")
            body = {"items": [{"id": query["id"][0],
                               "statistics": {"subscriberCount": str(self.count)}}]}
        else:
            body = {"items": []}
        return _Answer(json.dumps(body).encode())


CHANNEL = "UC" + "b" * 22
KEY = "A" * 39


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_the_reader_hands_over_the_count_on_its_own_schedule():
    yt, clock, got = _YouTube(count=96), Clock(), []
    reader = chat.YouTubeReader(KEY, CHANNEL, on_line=lambda m: None, opener=yt,
                                clock=clock, on_subs=got.append)
    reader.step()
    assert got == [96] and reader.subscribers == 96
    reads = [a for a in yt.asked if a == ("channels", "statistics")]
    reader.step()
    assert [a for a in yt.asked if a == ("channels", "statistics")] == reads, \
        "not again before YT_SUBS_EVERY"
    yt.count = 97
    clock.t += chat.YT_SUBS_EVERY
    reader.step()
    assert got == [96, 97]


def test_a_lost_count_read_leaves_the_chat_alone():
    yt, states = _YouTube(subs_fail=True), []
    reader = chat.YouTubeReader(KEY, CHANNEL, on_line=lambda m: None, opener=yt,
                                clock=Clock(), on_subs=lambda n: None,
                                on_state=states.append)
    reader.step()
    assert reader.subscribers is None
    assert not any("timed out" in s for s in states), states


def test_without_a_listener_nothing_extra_is_asked():
    yt = _YouTube()
    reader = chat.YouTubeReader(KEY, CHANNEL, on_line=lambda m: None, opener=yt, clock=Clock())
    reader.step()
    assert ("channels", "statistics") not in yt.asked


# ---- the voice ---------------------------------------------------------------------------
def _announcer():
    settings = {"stream.voice_room": True}
    return Announcer(get=settings.get, clock=Clock(), rng=random.Random(4))


def test_a_new_subscriber_is_thanked_with_the_real_numbers():
    a = _announcer()
    t = subs.Tracker()
    t.seen(96)
    a.subscribers(t.count, t.goal, t.seen(97))
    said = a.next_line()
    assert said and "97" in said and ("3" in said or "100" in said), said


def test_the_first_count_says_nothing_but_the_room_line_uses_it():
    a = _announcer()
    a.subscribers(96, 100, None)
    assert not a.waiting
    a.room_next = [k for k, _, _ in __import__("hivemind.stream.voice", fromlist=["x"]).ROOM_LINES
                   ].index("subscribe")
    line = a._room(a.opened + 10_000)
    assert line is not None and "96 subscribers" in line.text and "100" in line.text
