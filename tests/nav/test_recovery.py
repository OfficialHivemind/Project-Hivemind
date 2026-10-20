"""Getting unstuck.

Two failure modes to avoid, in opposite directions: grinding against a rock for
an hour, and resetting to spawn over a pebble. The ladder exists to sit between
them, and the tests are mostly about it escalating and de-escalating correctly.

The one with real consequences is the reset rung: a character reset teleports to
spawn, so every position-derived belief becomes false. A bot that keeps
navigating from a stale position after a reset walks confidently the wrong way.
"""
import pytest

from hivemind.nav.recovery import LADDER, POSITION_BELIEFS, Recovery, Rung
from hivemind.world.beliefs import BeliefStore


class FakeInput:
    def __init__(self):
        self.events = []
        self.held = set()

    def press(self, *keys):
        for k in keys:
            self.held.add(k)
            self.events.append(("press", k))

    def release(self, *keys):
        for k in keys:
            self.held.discard(k)
            self.events.append(("release", k))

    def tap(self, key, ms=40):
        self.events.append(("tap", key))


@pytest.fixture
def inp():
    return FakeInput()


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """The rungs genuinely sleep, which would add 15s to the suite.

    Patched out rather than shortened, so the test is about the LOGIC of the
    ladder. The one test that needs sleep to raise patches it itself.
    """
    import hivemind.nav.recovery as mod
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)


def test_the_ladder_is_ordered_cheapest_first():
    costs = [cost for _, cost in LADDER]
    assert costs == sorted(costs), "a dearer rung must never precede a cheaper one"


def test_reset_is_the_last_resort():
    assert LADDER[-1][0] is Rung.RESET


def test_it_starts_with_the_cheapest_rung(inp):
    r = Recovery(inp)
    assert r.next_rung() is Rung.JUMP
    assert r.attempt() is Rung.JUMP


def test_a_failure_escalates_rather_than_repeating(inp):
    """Retrying a jump that just failed is how a bot spends an hour jumping."""
    r = Recovery(inp)
    r.attempt(); r.failed()
    assert r.next_rung() is Rung.SIDESTEP
    r.attempt(); r.failed()
    assert r.next_rung() is Rung.BACK_OFF


def test_success_returns_to_the_cheapest_rung(inp):
    """The next obstacle is a different obstacle."""
    r = Recovery(inp)
    r.attempt(); r.failed()
    r.attempt(); r.succeeded()
    assert r.next_rung() is Rung.JUMP


def test_the_ladder_is_exhausted_after_every_rung(inp):
    r = Recovery(inp)
    for _ in LADDER:
        assert r.attempt() is not None
        r.failed()
    assert r.exhausted
    assert r.attempt() is None
    assert "human" in r.describe()


def test_cost_accumulates_as_it_escalates(inp):
    r = Recovery(inp)
    assert r.cost_so_far() == 0
    r.attempt(); r.failed()
    assert r.cost_so_far() == pytest.approx(LADDER[0][1])


# ---- key safety ----------------------------------------------------------

@pytest.mark.parametrize("rung_index", range(len(LADDER)))
def test_no_rung_ever_leaves_a_key_held(inp, rung_index):
    """The worst failure in this project."""
    r = Recovery(inp)
    for _ in range(rung_index):
        r.attempt(); r.failed()
    r.attempt()
    assert inp.held == set(), f"{LADDER[rung_index][0]} left {inp.held} held"


def test_a_key_is_released_even_if_the_hold_raises(monkeypatch, inp):
    import hivemind.nav.recovery as mod

    def boom(_seconds):
        raise KeyboardInterrupt
    monkeypatch.setattr(mod.time, "sleep", boom)   # overrides the autouse stub
    r = Recovery(inp)
    r._step = 1                              # sidestep, which holds a key
    with pytest.raises(KeyboardInterrupt):
        r.attempt()
    assert inp.held == set()


# ---- the reset rung ------------------------------------------------------

def test_reset_invalidates_every_position_belief(inp):
    store = BeliefStore()
    for name in POSITION_BELIEFS:
        store.observe(name, "somewhere")
    store.observe("bees", 25)

    r = Recovery(inp, beliefs=store)
    r._step = len(LADDER) - 1
    assert r.attempt() is Rung.RESET

    for name in POSITION_BELIEFS:
        assert store.get(name) is None, f"{name} survived a reset"
    assert store.get("bees") == 25, "a reset does not change how many bees you own"


def test_reset_calls_the_hook(inp):
    fired = []
    r = Recovery(inp, on_reset=lambda: fired.append(1))
    r._step = len(LADDER) - 1
    r.attempt()
    assert fired == [1]


def test_reset_works_without_a_belief_store(inp):
    r = Recovery(inp)
    r._step = len(LADDER) - 1
    assert r.attempt() is Rung.RESET


def test_a_broken_belief_store_does_not_stop_the_reset(inp):
    class Broken:
        def invalidate(self, name):
            raise RuntimeError("store is wedged")
    fired = []
    r = Recovery(inp, beliefs=Broken(), on_reset=lambda: fired.append(1))
    r._step = len(LADDER) - 1
    assert r.attempt() is Rung.RESET
    assert fired == [1], "the reset must still happen"


def test_resets_are_counted(inp):
    r = Recovery(inp)
    assert r.resets == 0
    r._step = len(LADDER) - 1
    r.attempt()
    assert r.resets == 1


# ---- direction handling --------------------------------------------------

@pytest.mark.parametrize("heading,expected", [
    ("w", "s"), ("s", "w"), ("a", "d"), ("d", "a"), ("wa", "sd"), ("wd", "sa"),
])
def test_backing_off_reverses_the_heading(heading, expected):
    assert Recovery._opposite(heading) == expected


def test_sidestep_alternates_direction(inp):
    """Strafing the same way twice just walks further into the same corner."""
    r = Recovery(inp)
    r._step = 1
    r.attempt()
    first = [k for op, k in inp.events if op == "press"]
    inp.events.clear()
    r._step = 1
    r.attempt()
    second = [k for op, k in inp.events if op == "press"]
    assert first != second


def test_describe_reports_the_rung_and_the_cost(inp):
    r = Recovery(inp)
    text = r.describe()
    assert "jump" in text and "1 of 5" in text
