"""What each kill drops, measured from the reward feed (act/bugrun.FeedDrops)."""
from __future__ import annotations

import pathlib

from hivemind.act import bugrun

MOBS = pathlib.Path(__file__).resolve().parents[2] / "data" / "knowledge" / "mobs.yaml"


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def drops():
    clock = Clock()
    return bugrun.FeedDrops(bugrun.load(MOBS), clock=clock), clock


def test_the_1710_ladybugs_drops_are_read_and_fields_are_not_drops():
    feed, _ = drops()
    # the feed of var/routes/attempt-595/171027-bugrun-strawberry-gone.jpg
    text = ("Defeated Ladybug! (+1 Battle Point) +170 Bond (from Ladybug) "
            "Defeated Ladybug! (+1 Battle Point) +170 Bond (from Ladybug) "
            "+1 Honeysuckle (from Ladybug) +587 Honey (from Pine Tree Forest)")
    got = feed.seen(text)
    assert sorted(got) == [("ladybug", "bond", 170), ("ladybug", "bond", 170),
                           ("ladybug", "honeysuckle", 1)]


def test_a_line_read_again_within_its_life_is_one_drop():
    feed, clock = drops()
    line = "+1 Oil (from Werewolf)"
    assert feed.seen(line) == [("werewolf", "oil", 1)]
    clock.t += 3
    assert feed.seen(line) == []                      # the same line, read again
    clock.t += bugrun.FEED_LINE_SECONDS + 1
    assert feed.seen(line) == [("werewolf", "oil", 1)]   # a new one, later


def test_amounts_with_commas_and_unknown_mobs():
    feed, _ = drops()
    assert feed.seen("+5,000 Honey (from Werewolf)") == [("werewolf", "honey", 5000)]
    assert feed.seen("+1 Glitter (from Puffshroom)") == []    # not in the book


# ---- loot by sight ----------------------------------------------------------

class Chase:
    def __init__(self, walked=True, arrived=True):
        self.walked, self.arrived = walked, arrived

    def describe(self):
        return "chased a token"


def run(results, **kw):
    it = iter(results)
    clock = Clock()

    def one():
        clock.t += 2.0
        return next(it)
    return bugrun.loot_by_sight(one, clock=clock, **kw)


def test_it_chases_until_nothing_is_seen_twice():
    got = run([Chase(), Chase(arrived=False), Chase(False, False), Chase(False, False),
               Chase()])
    assert got.chases == 4 and got.walked == 2 and got.arrived == 1
    assert "twice in a row" in got.reason


def test_it_stops_at_its_time_or_its_count():
    got = run([Chase()] * 20)
    assert got.chases <= bugrun.LOOT_SIGHT_CHASES
    got = run([Chase()] * 20, seconds=5.0)
    assert got.chases == 3 and "time" in got.reason       # 2 s a chase


def test_a_stop_or_a_failing_chase_ends_it():
    got = bugrun.loot_by_sight(lambda: Chase(), stopped=lambda: True)
    assert got.chases == 0 and got.reason == "stopped"

    def broken():
        raise RuntimeError("no frame")
    got = bugrun.loot_by_sight(broken)
    assert got.chases == 0 and "failed" in got.reason
