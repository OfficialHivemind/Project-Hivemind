"""A drag goes through the owner's buttons like a click (brain/controls)."""
from __future__ import annotations

from hivemind.brain.controls import Controls, GuardedInput
from hivemind.telemetry.events import Action, Command


class RawInput:
    def __init__(self):
        self.drags = []

    def release_all(self):
        pass

    def drag(self, *args, **kwargs):
        self.drags.append((args, kwargs))


def test_a_drag_passes_when_nothing_holds_it():
    raw = RawInput()
    c = Controls(vin=raw)
    c.handle(Command(action=Action.START))
    vin = GuardedInput(raw, c)
    assert vin.drag(10, 20, 300, 400) is True
    assert raw.drags == [((10, 20, 300, 400), {})]


def test_a_drag_after_a_handover_is_dropped():
    raw = RawInput()
    c = Controls(vin=raw)
    c.handle(Command(action=Action.START))
    vin = GuardedInput(raw, c, poll=0.01)
    c.handle(Command(action=Action.TAKE_OVER))
    c.handle(Command(action=Action.PASS_BACK))
    # the loop has not started a fresh cycle since: what it decided is stale
    assert vin.drag(10, 20, 300, 400) is False
    assert raw.drags == []


def test_the_real_input_lets_the_button_go_even_when_a_move_fails():
    from hivemind.platform import input as inp

    class Pointer:
        def __init__(self):
            self.events, self.moves = [], 0

        def move_to(self, x, y):
            self.moves += 1
            if self.moves == 3:
                raise RuntimeError("the compositor went away")

        def button(self, btn, state):
            self.events.append(state)

    real = inp.VirtualInput.__new__(inp.VirtualInput)
    real.mouse = Pointer()
    try:
        real.drag(0, 0, 100, 100, steps=4, hold_s=0.0)
    except RuntimeError:
        pass
    assert real.mouse.events == [1, 0]


def test_a_drag_whose_check_says_no_lets_go_where_it_began():
    # an egg must never be let go over a cell the check did not pass: it is
    # carried back over the list it came from, where a drop does nothing
    from hivemind.platform import input as inp

    class Pointer:
        def __init__(self):
            self.at, self.events = None, []

        def move_to(self, x, y):
            self.at = (round(x), round(y))

        def button(self, btn, state):
            self.events.append((state, self.at))

    real = inp.VirtualInput.__new__(inp.VirtualInput)
    real.mouse = Pointer()
    assert real.drag(10, 20, 300, 400, steps=4, hold_s=0.0, check=lambda: False) is False
    assert real.mouse.events == [(1, (10, 20)), (0, (10, 20))]
    real.mouse = Pointer()
    assert real.drag(10, 20, 300, 400, steps=4, hold_s=0.0, check=lambda: True) is True
    assert real.mouse.events == [(1, (10, 20)), (0, (300, 400))]

    def broken():
        raise RuntimeError("no frame")
    real.mouse = Pointer()
    assert real.drag(10, 20, 300, 400, steps=4, hold_s=0.0, check=broken) is False
    assert real.mouse.events[-1] == (0, (10, 20))


def test_drag_seek_lets_go_only_where_find_and_check_say():
    from hivemind.platform import input as inp

    class Pointer:
        def __init__(self):
            self.at, self.events = None, []

        def move_to(self, x, y):
            self.at = (round(x), round(y))

        def button(self, btn, state):
            self.events.append((state, self.at))

    real = inp.VirtualInput.__new__(inp.VirtualInput)
    real.mouse = Pointer()
    assert real.drag_seek(10, 20, 500, 300, lambda: None, steps=3, hold_s=0.0) is None
    assert real.mouse.events == [(1, (10, 20)), (0, (10, 20))]           # carried home
    real.mouse = Pointer()
    got = real.drag_seek(10, 20, 500, 300, lambda: (600, 250), steps=3, hold_s=0.0)
    assert got == (600.0, 250.0) and real.mouse.events[-1] == (0, (600, 250))
    real.mouse = Pointer()
    assert real.drag_seek(10, 20, 500, 300, lambda: (600, 250), check=lambda: False,
                          steps=3, hold_s=0.0) is None
    assert real.mouse.events[-1] == (0, (10, 20))


def test_a_held_back_drag_seek_is_none():
    raw = RawInput()
    raw.drag_seek = lambda *a, **k: (1, 2)
    c = Controls(vin=raw)
    c.handle(Command(action=Action.START))
    vin = GuardedInput(raw, c, poll=0.01)
    c.handle(Command(action=Action.TAKE_OVER))
    c.handle(Command(action=Action.PASS_BACK))
    assert vin.drag_seek(10, 20, 300, 400, lambda: None) is None
