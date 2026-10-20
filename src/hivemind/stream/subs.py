"""The channel's subscriber goal: YouTube's own count and the round number
it is heading for.

THE OWNER, 2026-09-28: the stream "needs to ... keep them watching and make
them subscribe". A goal a viewer can see move is the ask that works, and a
new subscriber thanked on the spot is the reward for answering it.

THE COUNT IS YOUTUBE'S, never made up. The chat reader reads it with the
key it already has (stream/chat YouTubeReader: channels.list
part=statistics, 1 quota unit, every YT_SUBS_EVERY), and with no count --
no key, a hidden count, no network -- there is no goal on the stream and
nothing is said about one. YouTube gives the count "rounded down to three
significant figures" (the channels resource, statistics.subscriberCount),
which is exact below 1,000, where this channel is.

A DIP IS NOT AN UNSUBSCRIBE TO MOURN, AND COMING BACK FROM ONE IS NOT A NEW
SUBSCRIBER: counts from different Google frontends can disagree by one for
a while, so only a count above the best this window has seen is news.
"""
from __future__ import annotations

from dataclasses import dataclass

# The round numbers a goal is set at; past the last, every 5,000.
GOALS = (10, 25, 50, 100, 150, 200, 250, 300, 400, 500, 750, 1000, 1500,
         2000, 2500, 5000)
GOAL_STEP_PAST = 5000


def goal_for(count: int) -> int:
    """The next round number above `count`: 96 -> 100, 100 -> 150."""
    for goal in GOALS:
        if count < goal:
            return goal
    return (count // GOAL_STEP_PAST + 1) * GOAL_STEP_PAST


def floor_for(count: int) -> int:
    """The round number `count` last passed (0 below the first): where the
    bar towards `goal_for(count)` starts."""
    passed = [g for g in GOALS if g <= count]
    if count >= GOALS[-1]:
        passed.append(count // GOAL_STEP_PAST * GOAL_STEP_PAST)
    return max(passed, default=0)


def progress(count: int) -> float:
    """How far from the last round number to the next, 0 to 1."""
    low, high = floor_for(count), goal_for(count)
    return max(0.0, min(1.0, (count - low) / float(high - low)))


@dataclass
class Change:
    count: int          # YouTube's count now
    new: int            # how many above the best seen before
    goal: int           # the goal now
    reached: int        # a round number this change passed, or 0


class Tracker:
    """`seen(count)` for every count the reader hands over; a Change when
    there are subscribers to thank."""

    def __init__(self):
        self.count: int | None = None      # the last count YouTube said
        self.best: int | None = None       # the highest this window has seen

    @property
    def goal(self) -> int | None:
        return None if self.count is None else goal_for(self.count)

    def seen(self, count: int) -> Change | None:
        """None for the first count (the stream opening is not a subscribe),
        a dip, or no change."""
        count = int(count)
        self.count = count
        if self.best is None or count <= self.best:
            self.best = count if self.best is None else self.best
            return None
        before, self.best = self.best, count
        passed = [g for g in GOALS if before < g <= count]
        if count >= GOALS[-1]:
            step = count // GOAL_STEP_PAST * GOAL_STEP_PAST
            if before < step:
                passed.append(step)
        return Change(count=count, new=count - before, goal=goal_for(count),
                      reached=max(passed, default=0))
