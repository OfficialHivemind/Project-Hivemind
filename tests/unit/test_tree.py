"""The behaviour tree.

The property the whole architecture rests on is REACTIVITY: a higher-priority
condition becoming true must interrupt lower-priority work with no transition
declared anywhere. That is what a state machine cannot do without an edge
between every pair of states, and it is why this is a tree.

The mirror property is RESUMPTION: a multi-step routine must survive being
ticked repeatedly without restarting from step one.
"""
from hivemind.behave.tree import (Action, BehaviourTree, Condition, Cooldown,
                                  Invert, Parallel, ReactiveSequence,
                                  Retry, Selector, Sequence, Status, Succeed,
                                  Tick, Timeout)


def const(status, name="const"):
    return Action(lambda t: status, name=name)


def counter(statuses, name="counter"):
    """Returns each status in turn, then repeats the last."""
    box = {"i": 0}

    def run(tick):
        i = min(box["i"], len(statuses) - 1)
        box["i"] += 1
        return statuses[i]
    node = Action(run, name=name)
    node.calls = box
    return node


def tick_of(now=0.0, **bb):
    return Tick(now=now, blackboard=dict(bb))


# ---- sequence ------------------------------------------------------------

def test_sequence_succeeds_when_all_children_do():
    s = Sequence(const(Status.SUCCESS), const(Status.SUCCESS))
    assert s.tick(tick_of()) is Status.SUCCESS


def test_sequence_fails_on_the_first_failure():
    ran = []
    s = Sequence(Action(lambda t: (ran.append("a"), Status.FAILURE)[1]),
                 Action(lambda t: (ran.append("b"), Status.SUCCESS)[1]))
    assert s.tick(tick_of()) is Status.FAILURE
    assert ran == ["a"]


def test_sequence_remembers_where_it_was():
    """A walk that runs for many ticks must not restart the steps before it."""
    first_calls = []
    walk = counter([Status.RUNNING, Status.RUNNING, Status.SUCCESS], "walk")
    s = Sequence(Action(lambda t: (first_calls.append(1), Status.SUCCESS)[1],
                        name="step1"),
                 walk)
    assert s.tick(tick_of()) is Status.RUNNING
    assert s.tick(tick_of()) is Status.RUNNING
    assert s.tick(tick_of()) is Status.SUCCESS
    assert first_calls == [1], "step1 must run once, not on every tick"


def test_sequence_restarts_after_completing():
    s = Sequence(const(Status.SUCCESS), const(Status.SUCCESS))
    assert s.tick(tick_of()) is Status.SUCCESS
    assert s.tick(tick_of()) is Status.SUCCESS


# ---- selector: the reactive part ----------------------------------------

def test_selector_takes_the_first_success():
    s = Selector(const(Status.FAILURE, "a"), const(Status.SUCCESS, "b"),
                 const(Status.SUCCESS, "c"))
    t = tick_of()
    assert s.tick(t) is Status.SUCCESS
    assert [n for n, _ in t.trace] == ["Selector", "a", "b"][1:] + ["Selector"]


def test_selector_fails_only_when_everything_does():
    assert Selector(const(Status.FAILURE), const(Status.FAILURE)).tick(
        tick_of()) is Status.FAILURE


def test_a_higher_priority_condition_interrupts_running_work():
    """THE property. No transition is declared; priority alone preempts."""
    boss = {"spawned": False}
    gather_ticks = []

    urgent = ReactiveSequence(Condition(lambda t: boss["spawned"], name="boss?"),
                              const(Status.RUNNING, "fight"), name="urgent")
    gather = Action(lambda t: (gather_ticks.append(1), Status.RUNNING)[1],
                    name="gather")
    tree = BehaviourTree(Selector(urgent, gather, name="root"),
                         clock=lambda: 0.0)

    tree.tick()
    assert gather_ticks == [1]
    boss["spawned"] = True
    tree.tick()
    assert gather_ticks == [1], "gather must not be ticked once the boss is up"
    assert "fight" in tree.last_path


def test_the_abandoned_branch_is_reset_not_left_mid_step():
    """Otherwise it resumes halfway through when control returns."""
    switch = {"urgent": False}
    steps = []
    routine = Sequence(
        Action(lambda t: (steps.append("open"), Status.SUCCESS)[1], name="open"),
        const(Status.RUNNING, "read"), name="routine")
    tree = BehaviourTree(
        Selector(ReactiveSequence(Condition(lambda t: switch["urgent"],
                                            name="urgent?"),
                                  const(Status.RUNNING, "urgent")),
                 routine, name="root"),
        clock=lambda: 0.0)

    tree.tick()                      # routine starts, "open" runs
    assert steps == ["open"]
    switch["urgent"] = True
    tree.tick()                      # urgent takes over, routine abandoned
    switch["urgent"] = False
    tree.tick()                      # routine restarts from the top
    assert steps == ["open", "open"]


# ---- parallel ------------------------------------------------------------

def test_parallel_needs_every_child_by_default():
    p = Parallel(const(Status.SUCCESS), const(Status.RUNNING))
    assert p.tick(tick_of()) is Status.RUNNING


def test_parallel_threshold():
    p = Parallel(const(Status.SUCCESS), const(Status.RUNNING), threshold=1)
    assert p.tick(tick_of()) is Status.SUCCESS


def test_parallel_fails_once_the_threshold_is_unreachable():
    p = Parallel(const(Status.FAILURE), const(Status.FAILURE),
                 const(Status.RUNNING), threshold=2)
    assert p.tick(tick_of()) is Status.FAILURE


def test_parallel_ticks_every_child_each_time():
    calls = []
    p = Parallel(Action(lambda t: (calls.append("a"), Status.RUNNING)[1]),
                 Action(lambda t: (calls.append("b"), Status.RUNNING)[1]))
    p.tick(tick_of())
    assert calls == ["a", "b"]


# ---- decorators ----------------------------------------------------------

def test_invert():
    assert Invert(const(Status.SUCCESS)).tick(tick_of()) is Status.FAILURE
    assert Invert(const(Status.FAILURE)).tick(tick_of()) is Status.SUCCESS
    assert Invert(const(Status.RUNNING)).tick(tick_of()) is Status.RUNNING


def test_retry_gives_up_after_the_limit():
    r = Retry(const(Status.FAILURE), times=3)
    assert r.tick(tick_of()) is Status.RUNNING
    assert r.tick(tick_of()) is Status.RUNNING
    assert r.tick(tick_of()) is Status.FAILURE


def test_retry_resets_its_count_on_success():
    node = counter([Status.FAILURE, Status.SUCCESS, Status.FAILURE])
    r = Retry(node, times=2)
    assert r.tick(tick_of()) is Status.RUNNING
    assert r.tick(tick_of()) is Status.SUCCESS
    assert r.tick(tick_of()) is Status.RUNNING, "count should have reset"


def test_cooldown_blocks_until_the_window_passes():
    c = Cooldown(const(Status.SUCCESS), seconds=60)
    assert c.tick(tick_of(now=0)) is Status.SUCCESS
    assert c.tick(tick_of(now=30)) is Status.FAILURE
    assert c.tick(tick_of(now=61)) is Status.SUCCESS


def test_cooldown_does_not_start_on_failure():
    c = Cooldown(const(Status.FAILURE), seconds=60)
    assert c.tick(tick_of(now=0)) is Status.FAILURE
    assert c.last_success is None


def test_timeout_fails_a_child_that_runs_too_long():
    """A stuck leaf must be distinguishable from a slow one."""
    t = Timeout(const(Status.RUNNING), seconds=10)
    assert t.tick(tick_of(now=0)) is Status.RUNNING
    assert t.tick(tick_of(now=5)) is Status.RUNNING
    assert t.tick(tick_of(now=11)) is Status.FAILURE


def test_timeout_clock_restarts_after_completion():
    node = counter([Status.RUNNING, Status.SUCCESS, Status.RUNNING])
    t = Timeout(node, seconds=10)
    t.tick(tick_of(now=0))
    assert t.tick(tick_of(now=5)) is Status.SUCCESS
    assert t.tick(tick_of(now=100)) is Status.RUNNING, "should not be stale"


# ---- tree ----------------------------------------------------------------

def test_the_trace_explains_what_it_did():
    tree = BehaviourTree(Selector(const(Status.FAILURE, "quest"),
                                  const(Status.RUNNING, "gather"), name="root"),
                         clock=lambda: 0.0)
    tree.tick()
    assert "gather" in tree.last_path
    assert "quest" not in tree.last_path


def test_describe_renders_the_shape():
    tree = BehaviourTree(Sequence(const(Status.SUCCESS, "a"),
                                  Selector(const(Status.SUCCESS, "b"),
                                           name="pick"), name="top"))
    text = tree.describe()
    assert "top" in text and "pick" in text and "  " in text


def test_blackboard_is_shared_with_leaves():
    seen = []
    tree = BehaviourTree(Action(lambda t: (seen.append(t.blackboard["bees"]),
                                           Status.SUCCESS)[1]),
                         blackboard={"bees": 25}, clock=lambda: 0.0)
    tree.tick()
    assert seen == [25]


def test_tick_count_increments():
    tree = BehaviourTree(Succeed(), clock=lambda: 0.0)
    tree.tick(); tree.tick()
    assert tree.ticks == 2


def test_status_done_property():
    assert Status.SUCCESS.done and Status.FAILURE.done
    assert not Status.RUNNING.done


def test_an_empty_selector_fails_rather_than_hanging():
    assert Selector().tick(tick_of()) is Status.FAILURE


def test_an_empty_sequence_succeeds():
    assert Sequence().tick(tick_of()) is Status.SUCCESS


# ---- the guard-staleness bug -------------------------------------------

def test_a_plain_sequence_does_NOT_recheck_its_guard():
    """Documents the trap. A memory Sequence resumes AT the action."""
    alive = {"boss": True}
    s = Sequence(Condition(lambda t: alive["boss"], name="alive?"),
                 const(Status.RUNNING, "fight"))
    assert s.tick(tick_of()) is Status.RUNNING
    alive["boss"] = False
    assert s.tick(tick_of()) is Status.RUNNING, "guard is not re-checked"


def test_a_reactive_sequence_DOES_recheck_its_guard():
    """Which is why guards go here. A dead boss aborts the fight."""
    alive = {"boss": True}
    s = ReactiveSequence(Condition(lambda t: alive["boss"], name="alive?"),
                         const(Status.RUNNING, "fight"))
    assert s.tick(tick_of()) is Status.RUNNING
    alive["boss"] = False
    assert s.tick(tick_of()) is Status.FAILURE


def test_reactive_sequence_resets_a_running_child_when_a_guard_fails():
    alive = {"boss": True}
    steps = []
    fight = Sequence(Action(lambda t: (steps.append("approach"),
                                       Status.SUCCESS)[1], name="approach"),
                     const(Status.RUNNING, "swing"), name="fight")
    s = ReactiveSequence(Condition(lambda t: alive["boss"], name="alive?"), fight)
    s.tick(tick_of())
    assert steps == ["approach"]
    alive["boss"] = False
    assert s.tick(tick_of()) is Status.FAILURE
    alive["boss"] = True
    s.tick(tick_of())
    assert steps == ["approach", "approach"], "fight must restart, not resume"


def test_reactive_sequence_succeeds_when_all_children_do():
    s = ReactiveSequence(const(Status.SUCCESS), const(Status.SUCCESS))
    assert s.tick(tick_of()) is Status.SUCCESS
