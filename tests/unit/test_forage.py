"""Farming by consequence rather than by map.

The route-driven loop could not work: every movement key is camera-relative,
the camera's rotation survives a reset, and eight headings were tried live
without one of them reaching the cannon. This loop navigates by what the HUD
says instead, so the tests that matter are the ones about EVIDENCE — that it
never counts a cycle it cannot prove, and never turns an unreadable counter
into a number.
"""
import threading

import pytest

from hivemind.brain.forage import Forager, Phase


class Reading:
    def __init__(self, value=None, capacity=None, ok=True):
        self.value, self.capacity = value, capacity
        self.ok = ok and value is not None

    def describe(self):
        return f"{self.value}/{self.capacity}"


class FakeHud:
    """A HUD the test drives directly."""

    def __init__(self):
        self.carried, self.capacity, self.honey_value = 0, 660_000, 1_000
        self.readable = True

    def pollen(self):
        if not self.readable:
            return Reading(ok=False)
        return Reading(self.carried, self.capacity)

    def honey(self):
        if not self.readable:
            return Reading(ok=False)
        return Reading(self.honey_value)


class FakeInput:
    def __init__(self):
        self.held_keys, self.events = set(), []

    def press(self, *keys):
        self.held_keys.update(keys)
        self.events += [("press", k) for k in keys]

    def release(self, *keys):
        self.held_keys.difference_update(keys)
        self.events += [("release", k) for k in keys]

    def release_all(self):
        self.held_keys.clear()
        self.events.append(("release_all", None))

    def tap(self, key, ms=40):
        self.events.append(("tap", key))

    def camera_right(self, taps=1, gap=0.0):
        self.events.append(("camera_right", taps))

    class _Held:
        def __init__(self, inp, keys):
            self.inp, self.keys = inp, keys

        def __enter__(self):
            self.inp.press(*self.keys)
            return self.inp

        def __exit__(self, *exc):
            self.inp.release(*self.keys)

    def held(self, *keys):
        return FakeInput._Held(self, keys)


class FakeRoutes:
    """Stands in for RouteRunner. `pollen_per_pass` simulates a field."""

    def __init__(self, hud, vin, pollen_per_pass=0, reset_ok=True):
        self.hud, self.vin = hud, vin
        self.pollen_per_pass = pollen_per_pass
        self.reset_ok = reset_ok
        self.resets, self.passes = 0, 0

    def run(self, name):
        self.passes += 1
        self.hud.carried = min(self.hud.capacity,
                               self.hud.carried + self.pollen_per_pass)
        return None

    def _run_step(self, step, result, depth):
        if step.get("op") == "reset":
            self.resets += 1
            if not self.reset_ok:
                result.ok = False
                result.reason = "the respawn dialog did not appear"
        return None


class Clock:
    """A clock the test advances, so nothing sleeps for real."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(seconds, 0.05)


def build(pollen_per_pass=0, reset_ok=True, **kwargs):
    hud, vin = FakeHud(), FakeInput()
    routes = FakeRoutes(hud, vin, pollen_per_pass, reset_ok)
    clock = Clock()

    # capture the bound method BEFORE reassigning, or `run` calls itself
    underlying = routes.run

    def run(name):
        clock.now += 1.0
        return underlying(name)

    routes.run = run
    forager = Forager(routes, hud, vin=vin, clock=clock, sleep=clock.sleep,
                      frames=kwargs.pop("frames", None),
                      tracker_factory=kwargs.pop("tracker_factory", None),
                      probe_seconds=kwargs.pop("probe_seconds", 10.0),
                      gather_seconds=kwargs.pop("gather_seconds", 60.0),
                      walk_seconds=kwargs.pop("walk_seconds", 1.0),
                      convert_seconds=kwargs.pop("convert_seconds", 20.0),
                      **kwargs)
    return forager, hud, vin, routes, clock


# ---- the anchor ------------------------------------------------------------

def test_a_cycle_resets_out_but_not_back_with_a_full_backpack():
    """The rule this loop was built on turned out to have a price.

    It used to reset at both ends of a cycle, because a reset is the only
    move that cannot land somewhere wrong -- exact position, no drift. What
    nobody had established was that a reset is a DEATH, and a death empties
    the backpack. The owner found it by watching: "when i die i loose all
    pollen and go back to hive".

    So the reset on the way OUT stands -- the backpack is empty, there is
    nothing to lose, and the exactness is free. The one on the way BACK is
    refused, because by then the cycle is carrying everything it gathered.
    """
    forager, hud, vin, routes, _ = build(pollen_per_pass=500)
    forager.run(cycles=1)
    assert routes.resets == 1, (
        f"{routes.resets} resets: the return leg must not reset while "
        f"carrying pollen")


def test_a_refused_reset_stops_rather_than_wandering():
    """If the respawn dialog is not confirmed, position is unknown."""
    forager, _, _, routes, _ = build(pollen_per_pass=500, reset_ok=False)
    session = forager.run(cycles=3)
    assert len(session.cycles) == 1
    assert "reset" in session.cycles[0].note


# ---- it only counts what it can prove --------------------------------------

def test_a_barren_search_is_not_a_cycle():
    """No pollen means no field, and no field means nothing to report."""
    forager, _, _, _, _ = build(pollen_per_pass=0)
    session = forager.run(cycles=1)
    assert session.cycles[0].found_field is False
    assert session.complete_cycles == 0
    assert session.honey_made == 0


def test_finding_pollen_makes_it_stay():
    forager, _, _, _, _ = build(pollen_per_pass=500)
    session = forager.run(cycles=1)
    assert session.cycles[0].found_field
    assert session.cycles[0].search_probes == 1


def test_a_barren_probe_makes_it_search_further_out():
    """A fixed radius can only ever search one ring.

    MEASURED: ten probes at ~70 studs apiece returned 0 pollen every time,
    because 70 studs only circles the hive platform. The nearest fields are
    300-600 studs out, so each barren probe has to reach further than the last.
    """
    said = []
    forager, hud, vin, routes, _ = build(pollen_per_pass=0, max_probes=4,
                                         emit=lambda e: said.append(e.text))
    forager.run(cycles=1)
    walks = [line for line in said if line.startswith("walking ")]
    assert len(walks) >= 2, f"expected several walks, got {said}"
    distances = [float(line.split()[1].rstrip("s")) for line in walks]
    assert distances == sorted(distances), f"did not spiral out: {distances}"
    assert distances[-1] > distances[0], "never reached further than the first"


def test_the_camera_only_turns_when_every_direction_is_blocked():
    """Turning the camera is the LAST resort; picking an open key comes first,
    because at the hive only `d` moved while w/a/s were all under 0.4 px."""
    forager, hud, vin, routes, _ = build(pollen_per_pass=500)
    forager.run(cycles=1)
    assert not [e for e in vin.events if e[0] == "camera_right"], (
        "turned the camera although a direction was open")


def test_an_unreadable_counter_is_never_treated_as_zero():
    forager, hud, _, _, _ = build(pollen_per_pass=500)
    hud.readable = False
    session = forager.run(cycles=1)
    # it may stop before the gather: a reset needs the bag read empty first
    # (act/respawn.bag_is_empty_enough), and an unreadable one is not
    assert (session.unreadable_reads > 0
            or "could not reset" in session.stopped_because), session.stopped_because
    assert session.cycles[0].found_field is False, (
        "an unreadable HUD must not read as a barren field or a full one")


def test_a_complete_cycle_needs_both_a_field_and_honey():
    forager, hud, _, _, _ = build(pollen_per_pass=500)
    session = forager.run(cycles=1)
    # honey never moved in this fake, so the cycle is not complete
    assert session.cycles[0].found_field
    assert session.complete_cycles == 0, "counted a cycle that made no honey"


# ---- stopping and safety ---------------------------------------------------

def test_it_stops_when_asked():
    stop = threading.Event()
    forager, _, _, routes, _ = build(pollen_per_pass=500, stop=stop)
    original = routes.run

    def run_and_stop(name):
        stop.set()
        return original(name)

    routes.run = run_and_stop
    session = forager.run(cycles=10)
    assert session.stopped_because == "stop requested"
    assert len(session.cycles) == 1


def test_no_key_is_left_held_on_any_exit():
    stop = threading.Event()
    stop.set()
    forager, _, vin, _, _ = build(pollen_per_pass=500, stop=stop)
    forager.run(cycles=1)
    assert vin.held_keys == set()


def test_no_key_is_left_held_after_a_normal_run():
    forager, _, vin, _, _ = build(pollen_per_pass=500)
    forager.run(cycles=2)
    assert vin.held_keys == set()


def test_the_backpack_filling_ends_the_gather():
    forager, hud, _, _, _ = build(pollen_per_pass=100_000,
                                  gather_seconds=10_000.0)
    session = forager.run(cycles=1)
    cycle = session.cycles[0]
    # this fake has no way home, so the note is the walk home's; the gather
    # itself ended on the full bag, long before its 10,000 s
    assert cycle.seconds < 100 and cycle.pollen_gathered >= 0.8 * hud.capacity, cycle


def test_it_reports_honestly_when_nothing_was_found():
    forager, _, _, _, _ = build(pollen_per_pass=0, max_probes=2)
    session = forager.run(cycles=1)
    text = session.cycles[0].describe()
    assert "no field found" in text
    assert "0 complete" in session.describe()


# --- absence of features is not absence of motion --------------------------
# MEASURED: wedged inside the white fence by the hive, with a flower field
# visible beyond it, flow read 0.0 px in all four directions — because the
# visible scene was flat white wall and flat green floor with no corners to
# track. The search called that "every direction blocked" twelve times while
# the pollen counter climbed to 1,084.

class BlankTracker:
    """A tracker that can see nothing — too few points to mean anything."""

    def __init__(self, points=2):
        self.points = points
        self._first = True

    def update(self, _frame):
        if self._first:
            self._first = False
            return None
        import numpy as np
        return type("S", (), {"pairs": np.zeros((self.points, 2, 2))})()


def test_a_featureless_screen_reports_unknown_not_blocked():
    import numpy as np
    forager, hud, vin, routes, _ = build(
        pollen_per_pass=500,
        frames=lambda: np.zeros((8, 8, 4), np.uint8),
        tracker_factory=lambda: BlankTracker(points=2))
    flow = forager._flow_while("w", 0.2)
    assert flow is None, (
        "a screen with nothing to track must not read as a wall")


def test_plenty_of_points_that_do_not_move_is_genuinely_blocked():
    import numpy as np
    forager, hud, vin, routes, _ = build(
        pollen_per_pass=500,
        frames=lambda: np.zeros((8, 8, 4), np.uint8),
        tracker_factory=lambda: BlankTracker(points=40))
    flow = forager._flow_while("w", 0.2)
    assert flow == 0.0, "40 tracked points that did not move IS blocked"


def test_walking_out_jumps_to_clear_fences():
    """The recorded routes contain 54 jumps; scenery catches a walker."""
    import numpy as np
    forager, hud, vin, routes, clock = build(
        pollen_per_pass=500,
        frames=lambda: np.zeros((8, 8, 4), np.uint8),
        tracker_factory=lambda: BlankTracker(points=40))
    forager._flow_while("w", 6.0, jump=True)
    assert [e for e in vin.events if e == ("tap", "space")], "never jumped"


def test_a_short_direction_probe_does_not_jump():
    """Jumping during a 1s probe would measure the jump, not the walk."""
    import numpy as np
    forager, hud, vin, routes, _ = build(
        pollen_per_pass=500,
        frames=lambda: np.zeros((8, 8, 4), np.uint8),
        tracker_factory=lambda: BlankTracker(points=40))
    vin.events.clear()
    forager._flow_while("w", 6.0, jump=False)
    assert not [e for e in vin.events if e == ("tap", "space")]


# ---------------------------------------------------------------------------
# A reset is a death
# ---------------------------------------------------------------------------
def test_it_refuses_to_reset_while_carrying_pollen():
    """MEASURED: a run reset on its first move and destroyed 115,831 pollen.

    The owner named the mechanic while watching: "when i die i loose all
    pollen and go back to hive". A reset is exact -- it lands at the hive
    with no drift -- and that exactness was worth having right up until the
    price was understood.
    """
    forager, hud, vin, routes, clock = build()
    hud.carried = 115_831
    before = routes.resets
    assert forager.go_home() is False
    assert routes.resets == before, \
        "it reset anyway and threw the backpack away"


def test_an_empty_backpack_may_still_reset():
    """Nothing to lose is the one case where the exactness is free."""
    forager, hud, vin, routes, clock = build()
    hud.carried = 0
    assert forager.go_home() is True
    assert routes.resets == 1


def test_a_caller_can_insist_but_has_to_say_so():
    forager, hud, vin, routes, clock = build()
    hud.carried = 500_000
    assert forager.go_home(allow_loss=True) is True
    assert routes.resets == 1


def test_it_does_not_reset_when_it_is_already_at_the_hive():
    """A reset here is pure cost: a death, an empty backpack, thirty seconds
    of resting bees, and a chance of failing outright.

    MEASURED: a run claimed a hive -- which leaves the character standing on
    it -- then immediately tried to reset back to it. The reset was refused
    because the respawn dialog never appeared and the cycle ended two seconds
    in having done nothing.
    """
    forager, hud, vin, routes, _ = build(at_home=lambda: True)
    hud.carried = 0
    assert forager.go_home() is True
    assert routes.resets == 0, "it reset while already standing at the hive"


def test_it_still_resets_when_it_is_not_home():
    forager, hud, vin, routes, _ = build(at_home=lambda: False)
    hud.carried = 0
    assert forager.go_home() is True
    assert routes.resets == 1


def test_an_unanswerable_home_check_does_not_block_the_reset():
    def boom():
        raise RuntimeError("cannot see")
    forager, hud, vin, routes, _ = build(at_home=boom)
    hud.carried = 0
    assert forager.go_home() is True
    assert routes.resets == 1
