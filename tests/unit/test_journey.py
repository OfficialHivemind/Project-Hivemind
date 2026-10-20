"""Travel that checks its own work. See nav/journey for the run behind it."""
from __future__ import annotations

import pytest

from hivemind.nav import journey as J
from hivemind.vision import landmarks as lm
from hivemind.world.bearings import Bearings

TABLE = lm.Table({
    "hive": {"kind": "hive", "router_node": "hive", "prompts": [
        {"text": "make honey", "mine": True}, {"text": "claim hive", "mine": False}]},
    "red_cannon": {"kind": "transport", "router_node": "red_cannon",
                   "prompts": ["fire the red cannon"]},
})

# THE POSE SEARCH WITH NO SLOT TRUSTED: what these tests always meant by
# calling `_poses` with no journey, before it learned to start from a
# measured slot (`slot_trusted`, DESIGN 8w).
from types import SimpleNamespace as _NS
_NO_SLOT = _NS(slot_trusted=False, hive_slot=None)


class Vin:
    def __init__(self):
        self.taps: list[str] = []
        self.released = 0

    def tap(self, key, ms=40):
        self.taps.append(key)

    def release_all(self):
        self.released += 1


class Result:
    def __init__(self, ok=True, reason=""):
        self.ok, self.reason = ok, reason


class Runner:
    """Replays scripted steps through on_step, the way RouteRunner does."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.vin = Vin()
        self.on_step = None
        self.ran: list[str] = []

    def run(self, name):
        self.ran.append(name)
        for step in self.routes.get(name, []):
            if callable(self.on_step):
                self.on_step(step["op"], step)
        return Result()


class Panel:
    """What the panel reads, per look, in order. Repeats the last."""

    def __init__(self, *reads):
        self.reads = list(reads)
        self.looks = 0

    def __call__(self, frame=None):
        self.looks += 1
        if not self.reads:
            return ""
        return self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]


def make(routes, panel, retries=1, said=None):
    runner = Runner(routes)
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, panel, frames=lambda: object(),
                  emit=said.append if said is not None else None,
                  sleep=lambda s: None, retries=retries)
    return runner, b, j


WALK = [{"op": "walk", "keys": "w", "studs": 10}]
CANNON = [{"op": "walk", "keys": "w", "studs": 10},
          {"op": "interact"},
          {"op": "pause", "seconds": 8}]


# --------------------------------------------------------------- square up --
def test_a_turned_camera_is_squared_up_before_any_route():
    runner, b, j = make({"out": WALK}, Panel(""))
    b.turned(3)
    j.go("pumpkin", ["out"])
    assert runner.vin.taps[:3] == ["comma"] * 3
    assert b.heading_taps == 0


def test_squaring_up_goes_the_short_way():
    runner, b, j = make({"out": WALK}, Panel(""))
    b.turned(6)
    j.go("pumpkin", ["out"])
    assert runner.vin.taps[:2] == ["period"] * 2


def test_shift_lock_left_on_is_turned_off_first():
    runner, b, j = make({"out": WALK}, Panel(""))
    b.toggled_shift_lock()
    out = j.go("pumpkin", ["out"])
    assert "shift" in runner.vin.taps and out.shift_reset
    assert b.shift_lock is False


def test_nothing_to_square_means_no_taps():
    runner, b, j = make({"out": WALK}, Panel(""))
    j.go("pumpkin", ["out"])
    assert runner.vin.taps == []


# ------------------------------------------------------------- the guard ---
def test_camera_steps_in_a_route_are_counted():
    route = [{"op": "camera", "direction": "right"}] * 3 + \
            [{"op": "camera", "direction": "left"}]
    runner, b, j = make({"out": route}, Panel(""))
    j.go("pumpkin", ["out"])
    assert b.heading_taps == 2


def test_shift_lock_steps_in_a_route_are_counted():
    runner, b, j = make({"out": [{"op": "shift_lock"}]}, Panel(""))
    j.go("pumpkin", ["out"])
    assert b.shift_lock is True


def test_interact_is_refused_at_a_blank_panel():
    """THE CANNON. The route pressed E at nothing and waited eight seconds."""
    said = []
    runner, b, j = make({"out": CANNON}, Panel(""), said=said)
    out = j.go("pine_tree", ["out"])
    assert j.refusals >= 1
    assert "wanted to press E" in out.refused and "no panel" in out.refused
    assert runner.vin.released >= 1


def test_interact_is_allowed_when_the_panel_names_a_landmark():
    runner, b, j = make({"out": CANNON}, Panel("Fire the Red Cannon", ""))
    j.go("pine_tree", ["out"])
    assert j.refusals == 0


def test_interact_is_refused_when_the_panel_is_unreadable():
    runner, b, j = make({"out": CANNON}, Panel(None))
    out = j.go("pine_tree", ["out"])
    assert "could not read" in out.refused


def test_a_stop_request_aborts_mid_route():
    runner = Runner({"out": WALK * 3})
    b = Bearings(TABLE, clock=lambda: 0.0); b.spawned()
    j = J.Journey(runner, b, Panel(""), frames=lambda: object(),
                  sleep=lambda s: None, stopped=lambda: True)
    out = j.go("pumpkin", ["out"])
    assert not out.ok and "stop" in out.reason


# ------------------------------------------------------------ verification --
def test_still_at_the_hive_after_the_routes_is_a_failure():
    """The whole point. 27 passes and 0 pollen on the hive pads."""
    runner, b, j = make({"out": WALK}, Panel("Make Honey"))
    out = j.go("pumpkin", ["out"])
    assert out.ok is False and out.confirmed is False
    assert "STILL AT THE HIVE" in out.reason


def test_it_retries_once_squared_up_then_gives_up():
    runner, b, j = make({"out": WALK}, Panel("Make Honey"), retries=1)
    out = j.go("pumpkin", ["out"])
    assert out.attempts == 2
    assert runner.ran == ["out", "out"]


def test_leaving_the_hive_is_ok_but_unconfirmed_for_a_field():
    runner, b, j = make({"out": WALK}, Panel(""))
    out = j.go("pumpkin", ["out"])
    assert out.ok is True and out.confirmed is False
    assert "unconfirmed" in out.describe()


def test_a_landmark_destination_is_confirmed_by_its_prompt():
    runner, b, j = make({"out": WALK}, Panel("Fire the Red Cannon"))
    out = j.go("red_cannon", ["out"])
    assert out.ok and out.confirmed
    assert "arrived" in out.describe()


def test_a_landmark_destination_is_not_confirmed_by_a_different_prompt():
    runner, b, j = make({"out": WALK}, Panel("Make Honey"))
    out = j.go("red_cannon", ["out"])
    assert not out.ok
    assert "does not say we are at the red_cannon" in out.reason


def test_a_refused_route_is_reported_not_retried_into_success():
    runner, b, j = make({"out": CANNON}, Panel(""), retries=1)
    out = j.go("pine_tree", ["out"])
    assert out.attempts == 2                # it did try again, squared up
    assert not out.ok or out.refused        # and still says what happened


def test_a_route_that_fails_is_a_failure():
    class Failing(Runner):
        def run(self, name):
            self.ran.append(name)
            return Result(ok=False, reason="no route named 'out'")
    runner = Failing({})
    b = Bearings(TABLE, clock=lambda: 0.0); b.spawned()
    j = J.Journey(runner, b, Panel(""), frames=lambda: object(),
                  sleep=lambda s: None, retries=0)
    out = j.go("pumpkin", ["out"])
    assert not out.ok and "no route named" in out.reason


def test_the_supervisor_is_consulted_and_heard():
    class Sup:
        def diagnose_lost(self, detail):
            return "The player character is inside a hive."
    runner = Runner({"out": WALK})
    b = Bearings(TABLE, clock=lambda: 0.0); b.spawned()
    j = J.Journey(runner, b, Panel(None), frames=lambda: object(),
                  sleep=lambda s: None, supervisor=Sup(), retries=0)
    j.go("pumpkin", ["out"])
    assert b.where() is not None and b.where().source == "heard"


def test_the_previous_on_step_hook_still_runs():
    seen = []
    runner, b, j = make({"out": WALK}, Panel(""))
    runner.on_step = lambda op, step: seen.append(op)
    j.go("pumpkin", ["out"])
    assert seen == ["walk"]
    assert runner.on_step is not None and seen  # restored afterwards


# ------------------------------------------------------------------- home --
def test_already_on_the_pad_is_home_without_moving():
    runner, b, j = make({}, Panel("Make Honey"))
    b.saw_panel("Make Honey")
    out = j.home([], find=lambda: (_ for _ in ()).throw(AssertionError("moved")))
    assert out.ok and out.confirmed and "already" in out.reason
    assert runner.ran == []


def test_the_search_is_used_when_nothing_lands_and_its_taps_are_counted():
    class Found:
        ok, hops, taps, reason = True, 5, 12, ""
    runner, b, j = make({}, Panel(""))
    out = j.home([], find=lambda: Found())
    assert out.ok and out.confirmed and "searching" in out.reason
    assert b.heading_taps == 12 % 8
    assert b.on_my_pad() is True


def test_a_failed_search_says_so_and_squares_nothing_up_falsely():
    class Lost:
        ok, hops, taps, reason = False, 27, 12, "walked a box and never saw it"
    runner, b, j = make({}, Panel(""))
    out = j.home([], find=lambda: Lost())
    assert not out.ok and "never saw it" in out.reason
    assert b.heading_taps == 12 % 8


def test_home_does_not_square_up_before_a_recorded_route():
    """The routes are a chain: the route home undoes the taps the route out
    made. Squaring up first would undo them twice."""
    runner, b, j = make({"home": WALK}, Panel("Make Honey"))
    b.turned(2)
    out = j.home(["home"])
    assert "comma" not in runner.vin.taps and "period" not in runner.vin.taps
    assert out.ok


def test_home_still_turns_shift_lock_off():
    runner, b, j = make({"home": WALK}, Panel("Make Honey"))
    b.toggled_shift_lock()
    out = j.home(["home"])
    assert "shift" in runner.vin.taps and out.shift_reset


# ------------------------------------------------------------------- seek --
def _cannon_table():
    return lm.Table({
        "hive": {"kind": "hive", "router_node": "hive",
                 "prompts": [{"text": "make honey", "mine": True}]},
        "red_cannon": {"kind": "transport", "router_node": "red_cannon",
                       "prompts": ["fire the red cannon"]},
        "ticket_shop": {"kind": "shop", "router_node": None,
                        "prompts": ["open shop"]},
    })


class Found:
    def __init__(self, prompt="Fire the Red Cannon", taps=4):
        self.found, self.prompt, self.taps, self.steps = True, prompt, taps, 3

    def describe(self):
        return "found it"


class NotFound:
    found, prompt, taps, steps = False, "", 8, 10

    def describe(self):
        return "did not find it"


def _with_seek(panel, seeker, routes=None):
    runner = Runner(routes or {"from_hive_to_pine_tree_with_red_cannon": CANNON})
    b = Bearings(_cannon_table(), clock=lambda: 0.0)
    b.spawned()
    asked = []

    def seek(place):
        asked.append(place)
        return seeker

    j = J.Journey(runner, b, panel, frames=lambda: object(),
                  sleep=lambda s: None, retries=0, seek=seek)
    return runner, b, j, asked


def test_a_near_miss_is_closed_by_searching_for_the_route_s_landmark():
    runner, b, j, asked = _with_seek(Panel("", ""), Found())
    out = j.go("pine_tree", ["from_hive_to_pine_tree_with_red_cannon"])
    assert asked == ["red_cannon"], "it searched for the landmark named in the route"
    assert j.refusals == 0 and j.seeks == 1
    assert b.heading_taps == 4 % 8, "the search's taps were counted"


def test_a_failed_search_still_refuses_and_says_so():
    runner, b, j, asked = _with_seek(Panel(""), NotFound())
    out = j.go("pine_tree", ["from_hive_to_pine_tree_with_red_cannon"])
    assert asked == ["red_cannon"]
    assert j.refusals == 1
    assert "wanted to press E" in out.refused
    assert b.heading_taps == 0, "eight taps is a full turn"


def test_no_landmark_in_the_route_name_means_no_search():
    runner, b, j, asked = _with_seek(Panel(""), Found(),
                                     routes={"from_hive_to_somewhere": CANNON})
    out = j.go("somewhere", ["from_hive_to_somewhere"])
    assert asked == [] and j.refusals == 1


def test_the_hive_is_never_what_a_route_s_interact_is_for():
    runner, b, j, asked = _with_seek(Panel(""), Found("Make Honey"),
                                     routes={"from_hive_to_red_cannon": CANNON})
    j.go("red_cannon", ["from_hive_to_red_cannon"])
    assert asked == ["red_cannon"]


def test_a_visible_prompt_needs_no_search():
    runner, b, j, asked = _with_seek(Panel("Fire the Red Cannon"), Found())
    j.go("pine_tree", ["from_hive_to_pine_tree_with_red_cannon"])
    assert asked == [] and j.seeks == 0


# ------------------------------------------- the panel has to be the RIGHT one
# 2026-09-21, var/gui-run.log 21:07:36. Arrival-by-sight fired on the hive
# pad's own "Make Honey" on the first watch tick of the first walk, every
# remaining approach walk was skipped as "already arrived", and THIS GUARD
# then looked at "Make Honey", matched it, and pressed E -- at the hive, for a
# route whose press boards the red cannon. The route's post-cannon legs ran
# from the hive and the character ended up at Black Bear. The owner: it tried
# the cannon to Pumpkin, missed it, walked past and ended at Black Bear.

def test_interact_is_refused_when_the_panel_names_the_WRONG_landmark():
    said = []
    runner = Runner({"from_hive_to_red_cannon": CANNON})
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel("Make Honey"), frames=lambda: object(),
                  emit=said.append, sleep=lambda s: None, retries=0)
    out = j.go("red_cannon", ["from_hive_to_red_cannon"])
    assert j.refusals == 1, "it pressed E at the hive for a cannon route"
    assert "not at the place this press is for" in out.refused
    assert "hive" in out.refused and "red cannon" in out.refused
    assert runner.vin.released >= 1


def test_the_wrong_landmark_is_searched_past_before_being_refused():
    """A prompt for somewhere else is a near miss like any other, so the
    search runs -- and if it finds the real one, the press goes ahead."""
    runner, b, j, asked = _with_seek(Panel("Open Shop"), Found())
    j.go("pine_tree", ["from_hive_to_pine_tree_with_red_cannon"])
    assert asked == ["red_cannon"] and j.seeks == 1
    assert j.refusals == 0


def test_a_search_that_finds_the_wrong_landmark_is_still_refused():
    """Strengthened: the search reporting success is not the same as the
    search finding the thing the press is for."""
    runner, b, j, asked = _with_seek(Panel(""), Found("Make Honey"),
                                     routes={"from_hive_to_red_cannon": CANNON})
    out = j.go("red_cannon", ["from_hive_to_red_cannon"])
    assert asked == ["red_cannon"]
    assert j.refusals == 1
    assert "not at the place this press is for" in out.refused


def test_any_landmark_still_passes_when_the_route_names_none():
    """The honest fallback. Nothing to check against, so nothing is checked --
    unchanged behaviour, kept on purpose."""
    runner = Runner({"from_hive_to_somewhere": CANNON})
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel("Make Honey"), frames=lambda: object(),
                  sleep=lambda s: None, retries=0)
    j.go("somewhere", ["from_hive_to_somewhere"])
    assert j.refusals == 0


# -------------------------------------------------- arming arrival by sight --
class Watcher:
    """An Arrival stand-in that records how it was armed."""

    def __init__(self):
        self.armed: list[str] = []
        self.disarms = 0

    def arm(self, destination=""):
        self.armed.append(destination)

    def disarm(self):
        self.disarms += 1

    def __call__(self):
        return False


class MeasuringRunner(Runner):
    """A Runner that also records the approach the journey gave it."""

    def __init__(self, routes, total=323.5):
        super().__init__(routes)
        self.total = total
        self.approaches: list[float | None] = []
        self.ends = 0

    def approach_studs(self, names):
        return self.total

    def begin_approach(self, total):
        self.approaches.append(total)

    def end_approach(self):
        self.ends += 1


def _journey_with(runner, panel, **kw):
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    return b, J.Journey(runner, b, panel, frames=lambda: object(),
                        sleep=lambda s: None, retries=0, **kw)


def test_the_arrival_watcher_is_told_which_landmark_the_press_is_for():
    """Without this it cannot tell the hive's prompt from the cannon's, and
    without the arm() call it cannot tell EITHER from the one already on
    screen when the walk starts."""
    watcher = Watcher()
    runner = MeasuringRunner({"from_hive_to_red_cannon": CANNON})
    b, j = _journey_with(runner, Panel("Fire the Red Cannon"),
                         target_in_view=watcher)
    j.go("red_cannon", ["from_hive_to_red_cannon"])
    assert watcher.armed == ["red_cannon"]
    assert watcher.disarms == 1


def test_the_runner_is_given_the_whole_journey_s_approach_length():
    """A journey can be a LIST of routes and only the journey knows where the
    approach ends, so the gate cannot be set inside one route."""
    watcher = Watcher()
    runner = MeasuringRunner({"from_hive_to_red_cannon": CANNON})
    b, j = _journey_with(runner, Panel("Fire the Red Cannon"),
                         target_in_view=watcher)
    j.go("red_cannon", ["from_hive_to_red_cannon"])
    assert runner.approaches == [323.5]
    assert runner.ends == 1


def test_nothing_is_armed_for_a_route_that_names_no_landmark():
    watcher = Watcher()
    runner = MeasuringRunner({"from_hive_to_somewhere": WALK})
    b, j = _journey_with(runner, Panel(""), target_in_view=watcher)
    j.go("somewhere", ["from_hive_to_somewhere"])
    assert watcher.armed == [] and runner.approaches == []


def test_a_watcher_that_throws_while_arming_does_not_stop_the_journey():
    class Bad(Watcher):
        def arm(self, destination=""):
            raise RuntimeError("no frame")

    runner = MeasuringRunner({"from_hive_to_red_cannon": CANNON})
    b, j = _journey_with(runner, Panel("Fire the Red Cannon"),
                         target_in_view=Bad())
    out = j.go("red_cannon", ["from_hive_to_red_cannon"])
    assert out.confirmed


# ------------------------------ a route only works from where it was recorded
# MEASURED live 2026-09-21 23:31:46, the trip to the Rose Field:
#
#     from_hive_to_rose_field: w for 64 studs: pushed against something for
#       1.9 of 2.3s
#     from_hive_to_rose_field: d for 212 studs: pushed against something for
#       5.1 of 7.6s
#
# Seven of the first ten seconds of walking moved nothing. The previous
# cycle's box search had left the character beside the red cannon instead of
# on its hive pad, and from there the route's first two legs walk into the
# cannon's own body. `var/incidents/233113-refused/000_t+00.0s.jpg` is the
# character on sand at the foot of the cannon as the route begins.
#
# The owner: the bot still did not know where it was going, and each try to
# work it out only got it more lost.

class Home:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, 0

    def __call__(self):
        self.calls += 1
        return self


def _wandered(panel, home, routes=None, retries=0):
    """A journey whose compass can PROVE we are not at the hive."""
    runner = Runner(routes or {"from_hive_to_rose_field": CANNON})
    runner.route_start = lambda names: "hive"
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    b.saw_panel("")                      # looked, no panel: not at the hive
    j = J.Journey(runner, b, panel, frames=lambda: object(),
                  sleep=lambda s: None, retries=retries, go_home=home)
    return runner, b, j


def test_a_hive_route_is_not_run_from_somewhere_else():
    home = Home(ok=True)
    runner, b, j = _wandered(Panel("Fire the Red Cannon"), home)
    # `at("hive")` is TRUE here, from the spawn belief -- which is exactly the
    # trap: the whole hive AREA is not a hive PAD. Only the panel says which.
    assert b.at("hive") is True
    assert b.on_my_pad() is False, "the fixture must prove we are off the pad"
    out = j.go("rose", ["from_hive_to_rose_field"])
    assert home.calls == 1, "it ran the route without going back first"
    assert out.went_home


def test_the_route_still_runs_after_getting_back():
    home = Home(ok=True)
    runner, b, j = _wandered(Panel("Fire the Red Cannon"), home)
    j.go("rose", ["from_hive_to_rose_field"])
    assert runner.ran == ["from_hive_to_rose_field"]


def test_a_failed_walk_home_refuses_the_route_rather_than_running_it_wrong():
    home = Home(ok=False)
    runner, b, j = _wandered(Panel(""), home)
    out = j.go("rose", ["from_hive_to_rose_field"])
    assert runner.ran == [], "it walked a hive route from the wrong place"
    assert not out.ok
    assert "wrong place" in out.reason


def test_being_at_the_hive_needs_no_detour():
    home = Home()
    runner = Runner({"from_hive_to_rose_field": CANNON})
    runner.route_start = lambda names: "hive"
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    b.saw_panel("Make Honey")            # standing on the pad
    j = J.Journey(runner, b, Panel("Fire the Red Cannon"),
                  frames=lambda: object(), sleep=lambda s: None,
                  retries=0, go_home=home)
    out = j.go("rose", ["from_hive_to_rose_field"])
    assert home.calls == 0 and not out.went_home
    assert runner.ran == ["from_hive_to_rose_field"]


def test_an_unsure_compass_does_not_ground_the_bot():
    """`None` is "the panel could not say", not "we are elsewhere". Refusing
    to travel whenever the compass is unsure would stop the night. An unsure
    compass LOOKS first (attempt 481, journey `_start_is_wrong`); a look that
    cannot be taken -- no frame -- changes nothing, and the route runs."""
    home = Home()
    runner = Runner({"from_hive_to_rose_field": CANNON})
    runner.route_start = lambda names: "hive"
    b = Bearings(TABLE, clock=lambda: 0.0)
    j = J.Journey(runner, b, Panel("Fire the Red Cannon"),
                  frames=lambda: None, sleep=lambda s: None,
                  retries=0, go_home=home)
    assert b.on_my_pad() is None
    j.go("rose", ["from_hive_to_rose_field"])
    assert home.calls == 0
    assert runner.ran == ["from_hive_to_rose_field"]


def test_a_route_that_does_not_start_at_the_hive_is_left_alone():
    home = Home()
    runner, b, j = _wandered(Panel("Fire the Red Cannon"), home)
    j.starts_at = lambda names: "rose_field"
    j.go("hive", ["from_rose_field_to_hive"])
    assert home.calls == 0


def test_without_a_way_home_it_still_tries():
    """No `go_home` wired means the old behaviour, not a refusal."""
    runner = Runner({"from_hive_to_rose_field": CANNON})
    runner.route_start = lambda names: "hive"
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    b.saw_panel("")
    j = J.Journey(runner, b, Panel("Fire the Red Cannon"),
                  frames=lambda: object(), sleep=lambda s: None, retries=0)
    j.go("rose", ["from_hive_to_rose_field"])
    assert runner.ran == ["from_hive_to_rose_field"]


def test_a_walk_home_that_throws_does_not_end_the_journey():
    def boom():
        raise RuntimeError("the compositor went away")
    runner, b, j = _wandered(Panel(""), boom)
    out = j.go("rose", ["from_hive_to_rose_field"])
    assert not out.ok and "wrong place" in out.reason


# ---- the landmark a route reaches through a `call` -------------------------
def test_a_landmark_reached_through_a_call_is_still_the_expected_one():
    """`from_hive_to_rose_field` boards the cannon via
    `{"op": "call", "route": "from_hive_to_red_cannon"}` and says nothing
    about it in its own name, so `expected` came out empty -- which turned off
    the nearby search AND let the guard accept any landmark at all. Watched
    live three attempts in a row on 2026-09-21."""
    runner, b, j, asked = _with_seek(
        Panel(""), Found(), routes={"from_hive_to_rose_field": CANNON})
    runner.route_names = lambda names: list(names) + ["from_hive_to_red_cannon"]
    j.go("rose", ["from_hive_to_rose_field"])
    assert asked == ["red_cannon"]
    assert j.refusals == 0



# -------------------- the bot searches for the pose the routes assume -------
# TWO MEASURED FACTS SHAPE THIS.
#
# 1. The routes did not work. Across a night, 31-83% of every walk was spent
#    pressed against a wall, in both directions, and the character finished
#    wedged between two hive bases.
# 2. The heading is not the cause. On 2026-09-22 at 01:33 the bot tried all
#    four quarter turns on a live account and arrived nowhere, and said so.
#
# What was left was the hive slot, and Natro Macro's paths name it: every one
# opens `nm_Walk(9.2*HiveSlot - 4, RightKey)`, so a slot is worth 36.8 studs
# of sideways walk and the whole difference between slots is one integer. The
# search tries the six of them first, then the other three quarter turns.

class BlockedResult:
    def __init__(self, blocked=2.0, planned=2.3):
        self.ok, self.reason = True, ""
        self.blocked_seconds = blocked
        self.notes = [f"w: pushed against something for {blocked} of {planned}s"]
        self.first_walk = (blocked, planned)

    @property
    def first_walk_blocked(self):
        blocked, planned = self.first_walk
        return blocked / planned if planned else 0.0


class WalledRunner(Runner):
    """Its first walk goes nowhere, every time."""

    def __init__(self, routes, blocked=2.0, planned=2.3):
        super().__init__(routes)
        self.blocked, self.planned = blocked, planned
        self.hive_slot = None

    def run(self, name):
        self.ran.append(name)
        for step in self.routes.get(name, []):
            if callable(self.on_step):
                self.on_step(step["op"], step)
        return BlockedResult(self.blocked, self.planned)


def _walled(panel, blocked=2.0, planned=2.3, said=None, retries=0):
    """`retries=0` is ONE attempt, which is what a one-step assertion needs:
    the pose advances on every failed attempt, so two attempts advance twice."""
    runner = WalledRunner({"out": WALK}, blocked, planned)
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, panel, frames=lambda: object(),
                  emit=said.append if said is not None else None,
                  sleep=lambda s: None, retries=retries)
    return runner, b, j


def test_the_six_hive_slots_are_tried_before_the_other_headings():
    """Slots first because that is where the evidence points: the headings
    were ruled out live, and Natro's paths show the slot is a real parameter
    worth 36.8 studs of sideways walk."""
    order = J.Journey._poses(_NO_SLOT)
    assert order[:J.HIVE_SLOTS] == [(0, s) for s in range(1, J.HIVE_SLOTS + 1)]
    assert all(h != 0 for h, _ in order[J.HIVE_SLOTS:])
    assert len(order) == J.HIVE_SLOTS + 3


def test_a_failed_trip_moves_the_search_on():
    said = []
    runner, b, j = _walled(Panel("Make Honey"), said=said)
    out = j.go("pumpkin", ["out"])
    assert out.turned_around
    assert (j.heading_offset, j.hive_slot) == (0, 1)
    assert "hive slot 1" in " ".join(t.text for t in said)


def test_the_slot_is_handed_to_the_route_runner():
    """`act.routes._hive_offset` turns it into the sideways walk.

    ONLY A TRUSTED SLOT -- one the owner configured or the ramp wall
    measured -- reaches the runner now. A slot the pose search merely "last
    arrived with" is a guess, and the runner walking its formula from the
    wrong pad is how every route out of the hive began in the wrong place
    (DESIGN 8k, 8w). The untrusted case is tested alongside the slot tests
    at the end of this file."""
    runner, b, j = _walled(Panel("Make Honey"), retries=0)
    j.hive_slot = 4
    j.slot_trusted = True
    j.go("pumpkin", ["out"])
    assert runner.hive_slot == 4


def test_the_pose_survives_the_next_square_up():
    runner, b, j = _walled(Panel("Make Honey"))
    j.go("pumpkin", ["out"])
    first = (j.heading_offset, j.hive_slot)
    assert first != (0, 0)
    j.go("pumpkin", ["out"])
    assert (j.heading_offset, j.hive_slot) != first, "the search stalled"


def test_every_starting_pose_tried_and_none_arriving_gives_up_on_the_pose():
    """Neither the slot nor the heading is then what is wrong, and carrying a
    random pose into the next cycle would only add a fault."""
    said = []
    poses = len(J.Journey._poses(_NO_SLOT))
    runner, b, j = _walled(Panel("Make Honey"), blocked=0.1, planned=2.3,
                           retries=poses, said=said)
    j.go("pumpkin", ["out"])
    assert (j.heading_offset, j.hive_slot) == (0, 0)
    assert j.poses_tried == set()
    assert "every starting pose has now been tried" in " ".join(
        t.text for t in said)


def test_a_pose_already_tried_is_not_offered_again():
    runner, b, j = _walled(Panel("Make Honey"), retries=0)
    j.poses_tried = {(0, 1)}
    j.go("pumpkin", ["out"])
    assert (j.heading_offset, j.hive_slot) not in ((0, 0), (0, 1))


def test_a_trip_that_arrives_keeps_the_pose_that_got_it_there():
    """A searched pose is kept only on a CONFIRMED arrival (journey.py,
    audit 2026-09-26 senses F3): here the panel names the landmark aimed at."""
    said = []
    runner = WalledRunner({"out": WALK}, 0.1, 2.3)
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel("Make Honey", "Fire the Red Cannon"),
                  frames=lambda: object(), emit=said.append,
                  sleep=lambda s: None, retries=0)
    j.go("pumpkin", ["out"])              # fails: the panel still says hive
    found = (j.heading_offset, j.hive_slot)
    assert found != (0, 0), "the search did not move"
    out = j.go("red_cannon", ["out"])     # the panel names it: arrived
    assert out.confirmed
    assert (j.heading_offset, j.hive_slot) == found
    assert j.poses_tried == set()
    assert "keeping it" in " ".join(t.text for t in said)


def test_an_unconfirmed_arrival_does_not_settle_a_searched_pose():
    """Leaving the hive for a field from a pose nobody has run is neither a
    win nor a failure: the next trip starts from it, and the search is not
    reset until an arrival is confirmed (F3)."""
    said = []
    runner = WalledRunner({"out": WALK}, 0.1, 2.3)
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel("Make Honey", ""), frames=lambda: object(),
                  emit=said.append, sleep=lambda s: None, retries=0)
    j.go("pumpkin", ["out"])
    found = (j.heading_offset, j.hive_slot)
    out = j.go("pumpkin", ["out"])        # the panel clears: it left the hive
    assert out.ok and not out.confirmed
    assert (j.heading_offset, j.hive_slot) == found
    assert j.poses_tried, "the search was reset without a confirmed arrival"
    assert "unconfirmed" in " ".join(t.text for t in said)


def test_a_successful_trip_is_never_turned_round():
    runner = WalledRunner({"out": WALK})
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel(""), frames=lambda: object(),
                  sleep=lambda s: None, retries=1)
    b.saw_panel("")                     # not at the hive: a field trip passes
    out = j.go("pumpkin", ["out"])
    assert out.ok and not out.turned_around


# ---- and it has to outlive the process --------------------------------------
def test_the_learned_pose_outlives_the_process():
    """A failed cycle ends in a rejoin, which is a whole new process, and the
    search gets one sample per cycle -- so without somewhere to write the
    answer it starts over for ever. MEASURED live 2026-09-22 00:49."""
    saved: list[tuple] = []
    runner, b, j = _walled(Panel("Make Honey"), blocked=0.1, planned=2.3,
                           retries=0)
    j.on_heading = lambda taps, tried=(), slot=0, poses=(): saved.append(
        (taps, list(tried), slot, list(poses)))
    j.go("pumpkin", ["out"])
    assert saved and saved[-1][3] == [(0, 0)], saved

    taps, tried, slot, poses = saved[-1]
    runner2 = WalledRunner({"out": WALK}, 0.1, 2.3)
    b2 = Bearings(TABLE, clock=lambda: 0.0)
    j3 = J.Journey(runner2, b2, Panel("Make Honey"), frames=lambda: object(),
                   sleep=lambda s: None, retries=0,
                   heading_offset=taps, heading_tried=tried,
                   hive_slot=slot, poses_tried=poses)
    assert j3.poses_tried == {(0, 0)}
    assert (j3.heading_offset, j3.hive_slot) == (taps, slot)


def test_a_saved_pose_is_kept_inside_its_range():
    runner = WalledRunner({"out": WALK})
    b = Bearings(TABLE, clock=lambda: 0.0)
    j = J.Journey(runner, b, Panel(""), frames=lambda: object(),
                  sleep=lambda s: None, heading_offset=11, hive_slot=99)
    assert j.heading_offset == 3
    assert j.hive_slot == J.HIVE_SLOTS


def test_a_caller_that_only_wants_the_heading_still_works():
    """The slot was added later; a two-argument callback must not break."""
    saved: list[int] = []
    runner, b, j = _walled(Panel("Make Honey"), retries=0)
    j.on_heading = lambda taps: saved.append(taps)
    j.go("pumpkin", ["out"])
    assert saved == [0], saved


def test_a_broken_pose_writer_does_not_end_the_journey():
    def boom(*_args, **_kw):
        raise RuntimeError("the disk is full")
    runner, b, j = _walled(Panel("Make Honey"), retries=0)
    j.on_heading = boom
    j.go("pumpkin", ["out"])
    assert (j.heading_offset, j.hive_slot) != (0, 0)


def test_a_candidate_pose_is_not_announced_as_one_that_worked():
    """It said "the correction that last arrived" whether or not anything had
    ever arrived. The search has not earned that claim until it succeeds."""
    said = []
    runner = WalledRunner({"out": WALK}, 0.1, 2.3)
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel("Make Honey"), frames=lambda: object(),
                  emit=said.append, sleep=lambda s: None, retries=0,
                  hive_slot=2, poses_tried=[(0, 1)])
    j.go("pumpkin", ["out"])
    joined = " ".join(t.text for t in said)
    assert "hive slot 2" in joined
    assert "the slot that last arrived" not in joined


def test_a_settled_pose_says_it_arrived():
    said = []
    runner = WalledRunner({"out": WALK}, 0.1, 2.3)
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel("Make Honey"), frames=lambda: object(),
                  emit=said.append, sleep=lambda s: None, retries=0,
                  hive_slot=2)                 # nothing left to try
    j.go("pumpkin", ["out"])
    assert "the slot that last arrived" in " ".join(t.text for t in said)


# ------------- the reward feed has the last word on whether it arrived ------
# MEASURED live 2026-09-22 02:06: a trip aimed at Sunflower reported "left the
# hive, arrival unconfirmed" and the game's reward feed credited DANDELION at
# 378 pollen/s. It farmed the wrong field happily and the pose search never
# advanced, because by `go`'s own honest standard nothing had failed -- a field
# has no prompt, so "left the hive" is the most it can ever claim.
#
# Landing one field over is the shape of a missing `hive_offset`: the sideways
# walk to the owned pad is skipped while the slot is unknown, worth 20 to 205
# studs.

def test_the_feed_naming_a_different_field_advances_the_search():
    said = []
    runner, b, j = _walled(Panel("Make Honey"), said=said, retries=0)
    before = (j.heading_offset, j.hive_slot)
    assert j.wrong_place("sunflower", "dandelion") is True
    assert (j.heading_offset, j.hive_slot) != before
    joined = " ".join(t.text for t in said)
    assert "one field over" in joined and "hive slot" in joined


def test_the_feed_naming_the_right_field_changes_nothing():
    runner, b, j = _walled(Panel("Make Honey"), retries=0)
    j.hive_slot = 3
    assert j.wrong_place("dandelion", "dandelion") is False
    assert j.hive_slot == 3


def test_no_verdict_at_all_changes_nothing():
    """The feed is quiet on a trip that gathered nothing, and silence is not
    evidence of being in the wrong place."""
    runner, b, j = _walled(Panel("Make Honey"), retries=0)
    j.hive_slot = 3
    assert j.wrong_place("dandelion", "") is False
    assert j.wrong_place("", "dandelion") is False
    assert j.hive_slot == 3


def test_running_out_of_poses_that_way_also_gives_up_honestly():
    said = []
    runner, b, j = _walled(Panel("Make Honey"), said=said, retries=0)
    j.poses_tried = set(J.Journey._poses(_NO_SLOT))
    assert j.wrong_place("sunflower", "dandelion") is False
    assert (j.heading_offset, j.hive_slot) == (0, 0)
    assert "the pose is not what is wrong" in " ".join(t.text for t in said)


def _shop_table():
    return lm.Table({
        "hive": {"kind": "hive", "router_node": "hive",
                 "prompts": [{"text": "make honey", "mine": True}]},
        "ticket_shop": {"kind": "shop", "router_node": None,
                        "prompts": ["open shop"]},
    })


def test_a_prompt_after_a_field_trip_moves_the_search_but_does_not_abort():
    """A CORRECTION TO MY OWN REASONING, made by the logs within the hour.

    This first abandoned the trip, on the argument that gathering at a shop
    counter earns nothing. MEASURED: trips that finished "at the ticket shop
    (98% sure, panel)" went on to earn 858, 801 and 985 honey, because the
    gathering pattern walks off the landmark into the field beside it. So the
    argument went and the observation stayed -- a prompt where a field was
    expected says the walk to the owned pad was wrong, and that is worth a
    step of the pose search and nothing more.
    """
    runner = Runner({"out": WALK})
    b = Bearings(_shop_table(), clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel("Open Shop"), frames=lambda: object(),
                  sleep=lambda s: None, retries=0)
    before = (j.heading_offset, j.hive_slot)
    out = j.go("sunflower", ["out"])
    assert out.ok, "the trip still earns; it must not be abandoned"
    assert out.landed_at == "ticket_shop"
    assert "ticket shop" in out.reason and "Gathering anyway" in out.reason
    assert (j.heading_offset, j.hive_slot) != before, "the search did not move"


def test_landing_wrong_gives_up_honestly_once_every_pose_is_spent():
    said = []
    runner = Runner({"out": WALK})
    b = Bearings(_shop_table(), clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel("Open Shop"), frames=lambda: object(),
                  emit=said.append, sleep=lambda s: None, retries=0)
    j.poses_tried = set(J.Journey._poses(_NO_SLOT))
    out = j.go("sunflower", ["out"])
    assert out.ok
    assert (j.heading_offset, j.hive_slot) == (0, 0)
    assert "the pose is not what is wrong" in " ".join(t.text for t in said)


def test_no_prompt_at_all_still_counts_as_having_left_the_hive():
    """A field really has no prompt, so silence is the expected good case."""
    runner = Runner({"out": WALK})
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel(""), frames=lambda: object(),
                  sleep=lambda s: None, retries=0)
    out = j.go("sunflower", ["out"])
    assert out.ok and "the field will confirm itself" in out.reason


def test_the_hive_is_still_reported_as_the_travel_doing_nothing():
    runner = Runner({"out": WALK})
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel("Make Honey"), frames=lambda: object(),
                  sleep=lambda s: None, retries=0)
    out = j.go("sunflower", ["out"])
    assert not out.ok and "STILL AT THE HIVE" in out.reason


def test_a_field_that_PAYS_is_not_the_wrong_field():
    """THIS COST 378,000 HONEY AN HOUR TO LEARN.

    MEASURED 2026-09-22: at hive slot 1 the bot aimed at the Sunflower Field,
    was credited the Dandelion Field, and earned 156,189 honey in 25 minutes
    on a twenty-minute trip that gathered 476,000 pollen over 90 passes. The
    search saw "wrong field" and moved to slot 2. The next cycles earned
    nothing at all.

    The goal is honey, not arriving at a named field.
    """
    said = []
    runner, b, j = _walled(Panel("Make Honey"), said=said, retries=0)
    j.hive_slot = 1
    j.poses_tried = {(0, 0)}
    moved = j.wrong_place("sunflower", "dandelion", earned=True)
    assert moved is False
    assert j.hive_slot == 1, "it abandoned a slot that was earning"
    assert j.poses_tried == set(), "the search should be settled, not paused"
    assert "a field that pays is not the wrong field" in " ".join(
        t.text for t in said).lower()


def test_a_trip_that_earned_NOTHING_still_moves_the_search():
    runner, b, j = _walled(Panel("Make Honey"), retries=0)
    before = (j.heading_offset, j.hive_slot)
    assert j.wrong_place("sunflower", "dandelion", earned=False) is True
    assert (j.heading_offset, j.hive_slot) != before


def test_earning_is_not_assumed_when_the_caller_says_nothing():
    """The default has to be the old behaviour, so a caller that has not been
    taught about earnings does not silently freeze the search."""
    runner, b, j = _walled(Panel("Make Honey"), retries=0)
    before = (j.heading_offset, j.hive_slot)
    assert j.wrong_place("sunflower", "dandelion") is True
    assert (j.heading_offset, j.hive_slot) != before


# ------------------------------------------------- the slot: fact or guess --
# The pose search hands the runner a "slot that last arrived", which is a
# guess, and Natro's sideways `hive_offset` walked from a guessed pad is how
# every route out of the hive began from the wrong place (DESIGN 8k). Now the
# runner is given a slot only when it is a FACT -- configured by the owner, or
# measured by feeling for the ramp wall -- and a measurement, once made, is
# adopted and no longer moved by the search.

class LearningRunner(Runner):
    """A runner whose first route reports the slot it measured at the ramp."""

    def __init__(self, routes, learned=None):
        super().__init__(routes)
        self.learned = learned
        self.hive_slot = None

    def run(self, name):
        out = super().run(name)
        out.learned_slot = self.learned
        self.learned = None                  # measured once, like the wall
        return out


def _journey(runner, panel, **kw):
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    said = []
    j = J.Journey(runner, b, panel, frames=lambda: object(),
                  emit=said.append, sleep=lambda s: None, retries=0, **kw)
    return j, said


def test_a_searched_slot_is_not_handed_to_the_runner():
    runner = LearningRunner({"out": WALK})
    j, _ = _journey(runner, Panel(""), hive_slot=1, slot_trusted=False)

    j.go("pumpkin", ["out"])

    assert runner.hive_slot is None, \
        "a guessed slot reached the runner; it would walk the sideways formula"


def test_a_configured_slot_is_handed_to_the_runner():
    runner = LearningRunner({"out": WALK})
    j, _ = _journey(runner, Panel(""), hive_slot=4, slot_trusted=True)

    j.go("pumpkin", ["out"])

    assert runner.hive_slot == 4


def test_one_ramp_reading_is_not_trusted():
    runner = LearningRunner({"out": WALK}, learned=2)
    told = []
    j, _ = _journey(runner, Panel(""), hive_slot=1, slot_trusted=False,
                    on_slot_learned=told.append)

    j.go("pumpkin", ["out"])

    assert j.slot_trusted is False and runner.hive_slot is None and told == []


def test_two_ramp_readings_are_averaged_and_rounded_up():
    # 08:28 and 08:50 on one pad: 3.2 and 2.8 -> 3, not "4 and 3 disagree"
    runner = LearningRunner({"out": WALK}, learned=4)
    j, _ = _journey(runner, Panel(""), hive_slot=1, slot_trusted=False)
    j.go("pumpkin", ["out"])
    runner.learned = 2
    j.go("pumpkin", ["out"])

    assert j.slot_trusted is True and runner.hive_slot == 3


def test_a_slot_measured_at_the_ramp_is_adopted_and_written_down():
    runner = LearningRunner({"out": WALK}, learned=3)
    told = []
    j, said = _journey(runner, Panel(""), hive_slot=1, slot_trusted=False,
                       on_slot_learned=told.append)

    j.go("pumpkin", ["out"])
    runner.learned = 3                       # the second walk reads it again
    j.go("pumpkin", ["out"])

    assert j.hive_slot == 3
    assert j.slot_trusted is True
    assert runner.hive_slot == 3
    assert told == [3], "the caller was not told, so a rejoin would forget it"
    assert any("measured the hive slot" in getattr(e, "text",
                                                    getattr(e, "message", ""))
               for e in said), [getattr(e, "text", e) for e in said]


def test_a_measured_slot_is_never_moved_by_the_pose_search():
    runner = LearningRunner({"out": WALK}, learned=3)
    j, _ = _journey(runner, Panel(""), hive_slot=1, slot_trusted=False)
    j.go("pumpkin", ["out"])                 # measures 3
    runner.learned = 3
    j.go("pumpkin", ["out"])                 # and again: trusted
    before = j.hive_slot

    # the search believes the trip landed in the wrong place and steps on
    j.wrong_place("pumpkin", "mushroom", earned=False)

    assert j.hive_slot == before == 3, \
        "the pose search moved a slot that was read off the ramp wall"


# ------------------------------------------------------- a held E is a press --
HELD_E = [{"op": "walk", "keys": "w", "studs": 10},
          {"op": "key_down", "keys": "e"},
          {"op": "pause", "seconds": 0.1},
          {"op": "key_up", "keys": "e"}]


def test_a_held_e_is_guarded_like_a_tapped_one():
    """Natro boards the cannon with E held for 100 ms. Same press, same guard:
    at a blank panel it is refused before anything goes down."""
    runner, b, j = make({"out": HELD_E}, Panel(""))
    out = j.go("pine_tree", ["out"])
    assert j.refusals >= 1
    assert "wanted to press E" in out.refused and "no panel" in out.refused


def test_a_held_e_at_the_cannons_prompt_is_allowed():
    runner, b, j = make({"out": HELD_E}, Panel("Fire the Red Cannon", ""))
    j.go("pine_tree", ["out"])
    assert j.refusals == 0


def test_holding_a_movement_key_is_not_a_press():
    runner, b, j = make({"out": [{"op": "key_down", "keys": "ds"}, {"op": "key_up", "keys": "ds"}]},
                        Panel(""))
    j.go("pine_tree", ["out"])
    assert j.refusals == 0


# ---- the hive slot, read in the library rather than in one script ----------
# It was read in `scripts/run_farm.py` and nowhere else, so by this project's
# own standard it was wired into one script rather than into the system, and
# it was still sitting in `world/settings.NOT_WIRED` under a note calling it
# "the biggest blocker in the project" -- which had been true and was not any
# more: the live logs say "running this as hive slot 3".

class _Slot:
    def __init__(self, value):
        self.value = value

    def int(self, key):
        assert key == "move.hive_slot", key
        return self.value


def test_the_owners_slot_is_read_from_the_settings():
    from hivemind.nav.journey import slot_from
    assert slot_from(_Slot(3)) == 3


def test_zero_means_not_set_rather_than_slot_zero():
    from hivemind.nav.journey import slot_from
    assert slot_from(_Slot(0)) == 0
    assert slot_from(_Slot(None)) == 0


def test_a_slot_off_the_end_of_the_row_is_refused():
    from hivemind.nav.journey import slot_from, HIVE_SLOTS
    assert slot_from(_Slot(HIVE_SLOTS)) == HIVE_SLOTS
    assert slot_from(_Slot(HIVE_SLOTS + 1)) == 0
    assert slot_from(_Slot(-2)) == 0


def test_rubbish_in_the_settings_is_not_a_slot():
    from hivemind.nav.journey import slot_from

    class Broken:
        def int(self, key):
            raise RuntimeError("no settings file")

    assert slot_from(Broken()) == 0
    assert slot_from(_Slot("three")) == 0


def test_it_is_no_longer_marked_unwired():
    from hivemind.world.settings import NOT_WIRED
    assert "move.hive_slot" not in NOT_WIRED


# --------------------------------------------------- the row search, home --
# After a recorded route home runs to its end and the prompt is not showing,
# Natro holds Left along the hive row until it is (nm_findHiveSlot). The
# journey runs that search -- and ONLY then: never with no route, because a
# character with no route home is in a field, and a bounded walk along the
# hive row is a search only when standing at the row.

class Row:
    def __init__(self, ok, text="found the pad holding left for 3.1s"):
        self.ok, self.text, self.calls = ok, text, 0

    def __call__(self):
        self.calls += 1
        return self

    def describe(self):
        return self.text


def test_the_row_search_runs_when_the_route_ran_and_the_prompt_is_missing():
    runner, b, j = make({"home": WALK}, Panel(""))
    row = Row(True)
    out = j.home(["home"], find=lambda: (_ for _ in ()).throw(AssertionError("searched by sight")),
                 search_row=row)
    assert row.calls == 1
    assert out.ok and out.confirmed
    assert "holding left for 3.1s" in out.reason
    assert b.on_my_pad() is True


def test_no_route_means_no_row_search():
    """With no route the character is wherever the gather left it."""
    class Found:
        ok, hops, taps, reason = True, 2, 0, ""
    runner, b, j = make({}, Panel(""))
    row = Row(True)
    out = j.home([], find=lambda: Found(), search_row=row)
    assert row.calls == 0
    assert out.ok and "searching" in out.reason


def test_a_route_that_failed_midway_does_not_hand_over_to_the_row_search():
    class FailingRunner(Runner):
        def run(self, name):
            self.ran.append(name)
            return Result(ok=False, reason="pushed against something for 9s")
    runner = FailingRunner({"home": WALK})
    b = Bearings(TABLE, clock=lambda: 0.0)
    b.spawned()
    j = J.Journey(runner, b, Panel(""), frames=lambda: object(),
                  sleep=lambda s: None, retries=0)
    row = Row(True)
    out = j.home(["home"], find=None, search_row=row)
    assert row.calls == 0
    assert not out.ok


def test_a_failed_row_search_is_noted_and_the_sight_search_still_runs():
    class Found:
        ok, hops, taps, reason = True, 4, 0, ""
    runner, b, j = make({"home": WALK}, Panel(""))
    row = Row(False, "did not find the pad along the row — held left 15s and right 30s")
    out = j.home(["home"], find=lambda: Found(), search_row=row)
    assert row.calls == 1
    assert out.ok and "searching" in out.reason
    assert any("row search" in n and "held left 15s" in n for n in out.notes), out.notes


def test_a_route_that_lands_needs_no_row_search():
    runner, b, j = make({"home": WALK}, Panel("Make Honey"))
    row = Row(True)
    out = j.home(["home"], search_row=row)
    assert row.calls == 0
    assert out.ok and "landed on the pad" in out.reason


def test_a_trusted_slot_starts_at_spawn_heading_and_a_wrong_landing_does_not_turn_it():
    # 2026-10-08 04:59: the search had ruled out 0 and started walks 90 degrees
    # round; Natro's paths assume the camera a respawn leaves.
    runner = LearningRunner({"out": WALK})
    j, _ = _journey(runner, Panel(""), hive_slot=3, slot_trusted=True,
                    heading_offset=2)
    assert j.heading_offset == 0
    j.landed_wrong("bamboo", "Open Shop")
    assert j.heading_offset == 0 and j.hive_slot == 3
