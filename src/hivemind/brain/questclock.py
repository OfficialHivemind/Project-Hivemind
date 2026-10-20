"""When the quest menu is next worth reading (run_farm `one_errand`).

WHY. A read is 42-49 s on the pad with the bag empty, not gathering: MEASURED
over runs 555-557 (2026-10-01 12:13-16:29), eleven reads, one every 23
minutes on average -- about 3% of the session. And most found nothing to act
on: Pine Tree is pinned, so the Blue Flower, Bamboo and Sunflower steps do not
move, and the one that always does (the Honey Hunt's tokens, about 240 an hour
from 880 at 14:12 to 1,432 at 16:29) is about 15 hours from done. Replayed
over those reads (their logged steps), with the 14:44 Ant Challenge as the one
event, this schedule keeps the five up to 13:51 -- a step 2 minutes from
done, a "Complete!", a quest handed in and its successor, another "Complete!"
-- and then reads at 14:12 and once after the Ant Challenge: two reads where
there were six.

WHAT DECIDES IT, from two reads compared (`next_interval`):

  - a quest came or went, a step's "Complete!" came or went, a step changed
    shape, or the read parsed nothing: news, or a read not worth comparing,
    so the next read is `base` away, as every read was before;
  - otherwise each step whose count moved has a rate since the last read and
    so a time to finish at that rate, and the next read is due when the
    soonest of them would finish -- never sooner than `base`, never later
    than `cap`;
  - nothing moved: `cap`.

A noisy read (one that drops a "Complete!", or splits a step) looks like news
and only brings the old pace back. And what changes quests by itself -- a
hand-in or any talk at a giver, a bug run, the Ant Challenge, a trip to a
different field -- brings the next read back to `base` after the last one
(`soon`), or to the next convert (`at_next_convert`).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from . import questneeds

COMPLETE = re.compile(r"\s*complete!.*$", re.IGNORECASE)


def _pairs(quests) -> list[tuple[str, list]]:
    """(name, requirements) from Quest objects or var/quests.json's dicts."""
    out = []
    for q in quests or ():
        if isinstance(q, dict):
            name, reqs = q.get("name"), q.get("requirements")
        else:
            name, reqs = getattr(q, "name", None), getattr(q, "requirements", None)
        if name:
            out.append((str(name), list(reqs or ())))
    return out


def _steps(name: str, requirements) -> dict:
    """A quest's steps keyed by their words without the count or verdict."""
    steps = {}
    for step in questneeds.steps_of(name, requirements):
        key = COMPLETE.sub("", step.text).strip(" .").lower()
        steps[key] = step
    return steps


def _span(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 60:.0f} min"


def next_interval(previous, previous_at: float, current, now: float, *,
                  base: float, cap: float) -> tuple[float, str]:
    """Seconds from `now` until the menu is worth reading again, and why."""
    now_q = dict(_pairs(current))
    if not now_q:
        return base, "the read parsed no quests"
    was_q = dict(_pairs(previous))
    if not was_q or not previous_at or now <= previous_at:
        return base, "no earlier read to compare it with"
    if now - previous_at > cap:
        # THE BOT MAY HAVE BEEN STOPPED IN BETWEEN (var/quests.json from an
        # earlier process), so a pace over this span would count the time off
        # as farming and push the next read hours out.
        return base, "the last read is too old to time a step by"
    came, went = sorted(set(now_q) - set(was_q)), sorted(set(was_q) - set(now_q))
    if came or went:
        return base, ("a quest came or went since the last read ("
                      + ", ".join([f"new: {n}" for n in came] + [f"gone: {n}" for n in went])
                      + ")")
    elapsed = now - previous_at
    soonest = None
    for name, reqs in now_q.items():
        before, after = _steps(name, was_q[name]), _steps(name, reqs)
        if set(before) != set(after):
            return base, f"{name}: its steps read differently from the last read"
        for key, step in after.items():
            old = before[key]
            if bool(old.complete) != bool(step.complete):
                return base, (f"{name}: {step.text!r} "
                              + ("is newly complete" if step.complete else
                                 "no longer reads complete"))
            if step.complete or not step.total:
                continue
            moved = float(step.done) - float(old.done)
            if moved <= 0:
                continue
            left = max(0.0, float(step.total) - float(step.done))
            eta = left / (moved / elapsed)
            if soonest is None or eta < soonest[0]:
                soonest = (eta, name, step)
    if soonest is None:
        return cap, "nothing on the menu moved since the last read"
    eta, name, step = soonest
    wait = min(cap, max(base, eta))
    return wait, (f"the step nearest to done is {name}: "
                  f"{COMPLETE.sub('', step.text).strip()!r}, "
                  f"{int(step.done):,}/{int(step.total):,}, about {_span(eta)} "
                  f"away at its pace since the last read")


@dataclass
class QuestClock:
    """When the next read is due, from what the reads said and what happened."""
    base: float
    cap: float
    clock: object = time.time
    last_at: float = 0.0              # the last read (0: never, so due now)
    due_at: float = 0.0
    why: str = "none has been read yet"
    previous: list = field(default_factory=list)
    previous_at: float = 0.0

    def due(self, now: float | None = None) -> bool:
        return (self.clock() if now is None else now) >= self.due_at

    def remember(self, quests, read_at: float) -> None:
        """An earlier read to compare the next with (var/quests.json)."""
        if _pairs(quests) and read_at:
            self.previous, self.previous_at = list(quests), float(read_at)

    def read(self, quests, now: float | None = None) -> float:
        """A read just finished with these quests parsed (maybe none); the
        seconds until the next is due."""
        now = self.clock() if now is None else now
        wait, self.why = next_interval(self.previous, self.previous_at, quests, now,
                                       base=self.base, cap=self.cap)
        self.last_at, self.due_at = now, now + wait
        self.remember(quests, now)
        return wait

    def skipped(self, now: float | None = None) -> None:
        """The start-up read was skipped (a fresh file): `base` from here."""
        now = self.clock() if now is None else now
        self.last_at, self.due_at = now, now + self.base
        self.why = "the start-up read was skipped for a fresh file"

    def soon(self, what: str) -> None:
        """Something that changes quests happened: due `base` after the last read."""
        due = self.last_at + self.base
        if due < self.due_at:
            self.due_at, self.why = due, f"{what} since the last read"

    def at_next_convert(self, what: str) -> None:
        """Read at the very next convert."""
        self.due_at, self.why = 0.0, what

    def describe(self, now: float | None = None) -> str:
        now = self.clock() if now is None else now
        if self.due_at <= now:
            return f"due now — {self.why}"
        return (f"due at {time.strftime('%H:%M', time.localtime(self.due_at))}, "
                f"in {_span(self.due_at - now)} — {self.why}")
