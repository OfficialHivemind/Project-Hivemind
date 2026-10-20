"""A reactive behaviour tree.

Why a tree rather than a state machine. The bot's job is not a sequence -- it is
a set of things worth doing, ranked, where a higher-ranked one can become true at
any moment. A boss spawns while you are walking to a field; the backpack fills
while you are chasing a token; the game disconnects while you are in a dialog. A
state machine handles that with a transition from every state to every other
state, which is where macros go to die. A tree handles it by re-asking the
question from the top on every tick.

That "re-asking" is the load-bearing property, and it is what `Selector` does:
each tick it starts at its highest-priority child again rather than resuming
whichever child was running. So a condition becoming true INTERRUPTS lower
priority work automatically, with no transition written anywhere.

`Sequence` is the opposite and equally necessary: it remembers where it was, so a
multi-step routine (walk to hive, open it, read the bee count) survives being
ticked repeatedly without restarting from step one.

Nothing here knows what Bee Swarm is. Leaves are plain callables returning a
Status, which is what lets the whole planner be tested against the simulator with
no game, no compositor and no GPU.

Time is injected rather than read from the clock, so a decorator with a
five-minute cooldown can be tested in microseconds.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable


class Status(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"

    @property
    def done(self) -> bool:
        return self is not Status.RUNNING


Clock = Callable[[], float]


@dataclass
class Tick:
    """What a leaf is given: the world, and when it is."""
    now: float
    blackboard: dict
    trace: list[tuple[str, Status]] = field(default_factory=list)

    def record(self, name: str, status: Status) -> Status:
        self.trace.append((name, status))
        return status

    @property
    def path(self) -> str:
        """The branch that ran, which is the explanation of what it is doing."""
        return " > ".join(name for name, s in self.trace
                          if s is not Status.FAILURE)


class Node:
    """Base class. Subclasses implement `run`."""

    def __init__(self, name: str = ""):
        self.name = name or type(self).__name__

    def run(self, tick: Tick) -> Status:      # pragma: no cover - abstract
        raise NotImplementedError

    def tick(self, tick: Tick) -> Status:
        return tick.record(self.name, self.run(tick))

    def reset(self) -> None:
        """Forget any in-progress position. Called when a branch is abandoned."""

    def children(self) -> Iterable["Node"]:
        return ()

    def describe(self, indent: int = 0) -> str:
        lines = [f"{'  ' * indent}{self.name}"]
        for child in self.children():
            lines.append(child.describe(indent + 1))
        return "\n".join(lines)


# --- composites -----------------------------------------------------------

class Sequence(Node):
    """Run children in order until one fails. REMEMBERS its position.

    This is what lets a multi-step routine survive being ticked: a walk that
    returns RUNNING for thirty ticks does not restart the steps before it.
    """

    def __init__(self, *children: Node, name: str = ""):
        super().__init__(name or "Sequence")
        self._children = list(children)
        self._index = 0

    def children(self):
        return self._children

    def reset(self) -> None:
        self._index = 0
        for child in self._children:
            child.reset()

    def run(self, tick: Tick) -> Status:
        while self._index < len(self._children):
            status = self._children[self._index].tick(tick)
            if status is Status.RUNNING:
                return Status.RUNNING
            if status is Status.FAILURE:
                self.reset()
                return Status.FAILURE
            self._index += 1
        self.reset()
        return Status.SUCCESS


class ReactiveSequence(Node):
    """Run children in order, re-evaluating ALL of them every tick.

    This is where guards belong, and the distinction from `Sequence` is not a
    nicety -- it is a correctness bug waiting to happen.

    A plain Sequence remembers its position. Put a condition first and an action
    second, and once the action is RUNNING the sequence resumes AT the action:
    the condition is never checked again. A boss fight would carry on after the
    boss died; a "backpack is full" guard would keep converting an empty one.

    A ReactiveSequence re-ticks from the first child every time, so the guard is
    re-asked on every tick and a newly-false guard aborts the action. The cost is
    that children must be cheap and idempotent to re-tick, which conditions are.

    Rule of thumb used throughout this project:
        guard + action  -> ReactiveSequence
        step, step, step -> Sequence
    """

    def __init__(self, *children: Node, name: str = ""):
        super().__init__(name or "ReactiveSequence")
        self._children = list(children)
        self._running: Node | None = None

    def children(self):
        return self._children

    def reset(self) -> None:
        self._running = None
        for child in self._children:
            child.reset()

    def run(self, tick: Tick) -> Status:
        for child in self._children:
            status = child.tick(tick)
            if status is Status.FAILURE:
                # a guard went false, or a step failed: abandon anything that
                # was mid-flight so it does not resume later
                if self._running is not None:
                    self._running.reset()
                    self._running = None
                return Status.FAILURE
            if status is Status.RUNNING:
                self._running = child
                return Status.RUNNING
        self._running = None
        return Status.SUCCESS


class Selector(Node):
    """Try children in priority order until one succeeds. FORGETS its position.

    Restarting from the highest-priority child every tick is exactly what makes
    the tree reactive: a guard that becomes true preempts whatever lower-priority
    work was running, without any transition being declared.
    """

    def __init__(self, *children: Node, name: str = ""):
        super().__init__(name or "Selector")
        self._children = list(children)
        self._running: Node | None = None

    def children(self):
        return self._children

    def reset(self) -> None:
        self._running = None
        for child in self._children:
            child.reset()

    def run(self, tick: Tick) -> Status:
        for child in self._children:
            status = child.tick(tick)
            if status is Status.RUNNING:
                # a DIFFERENT child took over: abandon the old one cleanly so it
                # does not resume mid-step when control returns
                if self._running is not None and self._running is not child:
                    self._running.reset()
                self._running = child
                return Status.RUNNING
            if status is Status.SUCCESS:
                if self._running is not None and self._running is not child:
                    self._running.reset()
                self._running = None
                return Status.SUCCESS
        self._running = None
        return Status.FAILURE


class Parallel(Node):
    """Tick every child each time. Succeeds when `threshold` of them succeed."""

    def __init__(self, *children: Node, threshold: int | None = None,
                 name: str = ""):
        super().__init__(name or "Parallel")
        self._children = list(children)
        self.threshold = threshold if threshold is not None else len(children)

    def children(self):
        return self._children

    def reset(self) -> None:
        for child in self._children:
            child.reset()

    def run(self, tick: Tick) -> Status:
        results = [child.tick(tick) for child in self._children]
        if sum(r is Status.SUCCESS for r in results) >= self.threshold:
            self.reset()
            return Status.SUCCESS
        # impossible to still reach the threshold?
        possible = sum(r is not Status.FAILURE for r in results)
        if possible < self.threshold:
            self.reset()
            return Status.FAILURE
        return Status.RUNNING


# --- leaves ---------------------------------------------------------------

class Action(Node):
    """A leaf that does something. The callable returns a Status."""

    def __init__(self, fn: Callable[[Tick], Status], name: str = ""):
        super().__init__(name or getattr(fn, "__name__", "Action"))
        self.fn = fn

    def run(self, tick: Tick) -> Status:
        return self.fn(tick)


class Condition(Node):
    """A guard. True is SUCCESS, False is FAILURE, never RUNNING."""

    def __init__(self, fn: Callable[[Tick], bool], name: str = ""):
        super().__init__(name or getattr(fn, "__name__", "Condition"))
        self.fn = fn

    def run(self, tick: Tick) -> Status:
        return Status.SUCCESS if self.fn(tick) else Status.FAILURE


class Succeed(Node):
    """Always succeeds. Useful as a fallback tail on a Selector."""

    def run(self, tick: Tick) -> Status:
        return Status.SUCCESS


class Fail(Node):
    def run(self, tick: Tick) -> Status:
        return Status.FAILURE


# --- decorators -----------------------------------------------------------

class Decorator(Node):
    def __init__(self, child: Node, name: str = ""):
        super().__init__(name or type(self).__name__)
        self.child = child

    def children(self):
        return (self.child,)

    def reset(self) -> None:
        self.child.reset()


class Invert(Decorator):
    def run(self, tick: Tick) -> Status:
        status = self.child.tick(tick)
        if status is Status.SUCCESS:
            return Status.FAILURE
        if status is Status.FAILURE:
            return Status.SUCCESS
        return status


class Retry(Decorator):
    """Re-run a failing child up to `times`, then give up."""

    def __init__(self, child: Node, times: int = 3, name: str = ""):
        super().__init__(child, name or f"Retry({times})")
        self.times = times
        self._used = 0

    def reset(self) -> None:
        self._used = 0
        super().reset()

    def run(self, tick: Tick) -> Status:
        status = self.child.tick(tick)
        if status is Status.FAILURE:
            self._used += 1
            self.child.reset()
            if self._used >= self.times:
                self._used = 0
                return Status.FAILURE
            return Status.RUNNING
        if status is Status.SUCCESS:
            self._used = 0
        return status


class Cooldown(Decorator):
    """Refuse to run again until `seconds` have passed since the last SUCCESS.

    Keeps the tree from hammering something that only pays off periodically --
    re-opening the hive to count bees, for instance.
    """

    def __init__(self, child: Node, seconds: float, name: str = ""):
        super().__init__(child, name or f"Cooldown({seconds:g}s)")
        self.seconds = seconds
        self.last_success: float | None = None

    def run(self, tick: Tick) -> Status:
        if (self.last_success is not None
                and tick.now - self.last_success < self.seconds):
            return Status.FAILURE
        status = self.child.tick(tick)
        if status is Status.SUCCESS:
            self.last_success = tick.now
        return status


class Timeout(Decorator):
    """Fail a child that has been RUNNING for too long.

    Without this a stuck leaf is indistinguishable from a slow one, and the bot
    walks into a wall for eight hours.
    """

    def __init__(self, child: Node, seconds: float, name: str = ""):
        super().__init__(child, name or f"Timeout({seconds:g}s)")
        self.seconds = seconds
        self._started: float | None = None

    def reset(self) -> None:
        self._started = None
        super().reset()

    def run(self, tick: Tick) -> Status:
        if self._started is None:
            self._started = tick.now
        if tick.now - self._started > self.seconds:
            self.reset()
            return Status.FAILURE
        status = self.child.tick(tick)
        if status.done:
            self._started = None
        return status


# --- runner ---------------------------------------------------------------

class BehaviourTree:
    """Owns the root, the blackboard and the clock."""

    def __init__(self, root: Node, blackboard: dict | None = None,
                 clock: Clock = time.time):
        self.root = root
        self.blackboard = blackboard if blackboard is not None else {}
        self.clock = clock
        self.ticks = 0
        self.last_trace: list[tuple[str, Status]] = []
        self.last_path = ""

    def tick(self) -> Status:
        tick = Tick(now=self.clock(), blackboard=self.blackboard)
        status = self.root.tick(tick)
        self.ticks += 1
        self.last_trace = tick.trace
        self.last_path = tick.path
        return status

    def reset(self) -> None:
        self.root.reset()

    def describe(self) -> str:
        return self.root.describe()
