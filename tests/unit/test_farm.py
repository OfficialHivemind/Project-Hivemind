"""The farm loop, and the ways an overnight run goes wrong quietly.

The happy path here is three lines long. Everything else in this file is about
the failures that do not announce themselves: a counter that cannot be read
being treated as an empty backpack, a character grinding into a wall while the
loop reports "gathering", a convert that pressed E next to somebody else's hive
and slept a hundred seconds, and a stop request that arrives while a key is
down.

The two rules being enforced throughout:

  * every number the loop reports was READ. There is no fallback value, so an
    unmeasured cycle reports None and the totals simply do not include it
  * no key is ever left held, on any exit path, including the error one
"""
import threading
from types import SimpleNamespace

import cv2
import pytest

from hivemind.act.routes import RouteRunner
from hivemind.brain import farm
from hivemind.brain.farm import FarmLoop, HudReader, Read, Reading, Rung
from hivemind.datapaths import data
from hivemind.nav.router import Edge, Router, Routine
from hivemind.telemetry.events import Level, Log, Metric, TaskUpdate
from hivemind.vision import digits

FIXTURES = __import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures/screens"
CAPACITY = 660_000          # the Pollen capacity in every captured frame


# --- fakes ------------------------------------------------------------------

class FakeInput:
    """Same shape as the one in test_routes.py, and it tracks what is held."""

    def __init__(self):
        self.events: list[tuple[str, object]] = []
        self.held_keys: set[str] = set()

    def press(self, *keys):
        for k in keys:
            self.held_keys.add(k)
            self.events.append(("press", k))

    def release(self, *keys):
        for k in keys:
            self.held_keys.discard(k)
            self.events.append(("release", k))

    def release_all(self):
        self.events.append(("release_all", None))
        self.held_keys.clear()

    def tap(self, key, ms=40):
        self.events.append(("tap", key))

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


def taps(inp) -> list[str]:
    return [key for action, key in inp.events if action == "tap"]


class FakeClock:
    """Simulated monotonic time. `sleep` advances it instead of blocking."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, float(seconds))

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeRoutes:
    """Stands in for RouteRunner, including the two behaviours that matter.

    It calls `on_step` BEFORE each step, the way RouteRunner does -- that is
    what lets a stop request abort a route in progress -- and it holds a key
    through `vin.held()` while "walking", so a test can prove nothing is left
    down when the abort unwinds through it.
    """

    def __init__(self, vin, clock=None, steps: int = 3, studs: float = 100.0,
                 seconds: float = 0.0, missing: tuple[str, ...] = (),
                 raise_on: str | None = None, on_run=None):
        self.vin = vin
        self.on_step = lambda op, step: None
        self.clock = clock
        self.steps = steps
        self.studs = studs
        self.seconds = seconds
        self.missing = set(missing)
        self.raise_on = raise_on
        self.on_run = on_run
        self.ran: list[str] = []
        self.steps_run = 0

    def run(self, name: str):
        from hivemind.act.routes import RouteResult
        self.ran.append(name)
        if self.on_run is not None:
            self.on_run(name, len(self.ran))
        if name in self.missing:
            return RouteResult(name, ok=False, reason=f"no route named {name!r}")
        if name == self.raise_on:
            raise RuntimeError("the compositor went away")
        for _ in range(self.steps):
            self.on_step("walk", {"op": "walk", "keys": "w"})
            with self.vin.held("w"):
                self.steps_run += 1
                if self.clock is not None and self.steps:
                    self.clock.advance(self.seconds / self.steps)
        return RouteResult(name, steps_run=self.steps, studs=self.studs, ok=True)


def pollen(value, capacity=CAPACITY) -> Reading:
    return Reading(Read.OK, value, capacity, f"{value:,}/{capacity:,}", 1.0)


def honey(value) -> Reading:
    return Reading(Read.OK, value, None, f"{value:,}", 1.0)


UNREADABLE = Reading(Read.UNREADABLE, text="44?,372/660,000", score=0.41)


def unreadable(bar_fill=None) -> Reading:
    """A counter the reader could not parse, with what the BAR showed --
    which is what a full backpack looks like (its seven digits either side of
    the slash defeat the digit reader)."""
    return Reading(Read.UNREADABLE, text="11?0?46/111???0", score=0.49,
                   bar_fill=bar_fill)
NO_HUD = Reading(Read.NO_HUD)


class FakeHud:
    """Scripted readings. Each read advances the clock, so time passes."""

    def __init__(self, clock, pollen_script, honey_script=None, tick=3.0,
                 honey_after_e=False):
        self.clock = clock
        self.pollen_script = list(pollen_script)
        self.honey_script = list(honey_script or [honey(1_000_000)])
        self.tick = tick
        self.pollen_reads = 0
        self.honey_reads = 0
        # THE COUNTER RISES WHEN E IS PRESSED, as the game's does: with
        # `honey_after_e` a two-entry script is "before the convert, after
        # it" -- the loop reads honey for other reasons on the way (the
        # micro-converter, the goals), and a script that advanced per read
        # spent its rise before the press. `build` hands over the input.
        self.honey_after_e = honey_after_e
        self.inp = None

    def _next(self, script, index):
        # The last entry repeats, so a script describes a state the world then
        # stays in rather than running out mid-test.
        return script[min(index, len(script) - 1)]

    def pollen(self) -> Reading:
        reading = self._next(self.pollen_script, self.pollen_reads)
        self.pollen_reads += 1
        self.clock.advance(self.tick)
        return reading

    def honey(self) -> Reading:
        if self.honey_after_e and self.inp is not None:
            pressed = "e" in taps(self.inp)
            reading = self.honey_script[-1 if pressed else 0]
        else:
            reading = self._next(self.honey_script, self.honey_reads)
        self.honey_reads += 1
        self.clock.advance(self.tick)
        return reading


@pytest.fixture
def clock():
    return FakeClock()


def build(clock, hud, routes=None, inp=None, **kwargs):
    inp = inp or FakeInput()
    routes = routes or FakeRoutes(inp, clock)
    events: list = []
    loop = FarmLoop(routes, hud, vin=inp, clock=clock, sleep=clock.sleep,
                    emit=events.append, **kwargs)
    if getattr(hud, "honey_after_e", False):
        hud.inp = inp
    return loop, inp, routes, events


def real_runner(inp):
    """A REAL RouteRunner over a graph shaped like the shipped one."""
    router = Router(path="/nonexistent", measurements=None)
    router.add(Edge("from_hive_to_pine_tree_with_red_cannon", "hive", "pine_tree",
                    346.0, steps=[{"op": "walk", "keys": "w", "studs": 346.0},
                                  {"op": "camera", "direction": "right"},
                                  {"op": "jump"}]))
    router.add(Edge("from_pine_tree_to_hive", "pine_tree", "hive", 1068.4,
                    steps=[{"op": "walk", "keys": "a", "studs": 1068.4}]))
    router.routines["collect_around"] = Routine(
        "collect_around", [{"op": "walk", "keys": "w", "studs": 8.1},
                           {"op": "walk", "keys": "d", "studs": 8.1}], 80.7, False)
    return RouteRunner(inp, router, walkspeed=1_000_000.0)   # instant, for tests


# --- the HUD reader, against REAL captures ---------------------------------
# These are the only tests here that touch pixels, and they are the reason the
# rest may use scripted Readings: the seam is exercised against the same frames
# the digit templates were learned from.

@pytest.fixture(scope="module")
def templates():
    return digits.TemplateSet.load(data("templates", "digits"))


def frame(name):
    image = cv2.imread(str(FIXTURES / f"{name}.png"))
    assert image is not None, f"missing fixture {name}.png"
    return image


def test_the_hud_reader_reads_a_real_in_game_frame(templates):
    """The values in tests/fixtures/screens/in_game.png, measured from it."""
    reader = HudReader(lambda: frame("in_game"), templates)
    backpack = reader.pollen()
    assert backpack.state is Read.OK
    assert (backpack.value, backpack.capacity) == (445_372, CAPACITY)
    assert backpack.fill == pytest.approx(445_372 / CAPACITY)
    assert reader.honey().value == 10_216_184


def test_the_pollen_pill_must_be_parsed_as_a_fraction(templates):
    """`to_int` drops the slash, so 445,372/660,000 reads as 445,372,660,000.

    That is a number 1,000,000x too large that carries no sign of being wrong,
    and it would make every backpack look 0% full forever.
    """
    x, y, w, h = farm.ss.POLLEN_REGION
    text, _ = digits.read(frame("in_game")[y:y + h, x:x + w], templates)
    # The trap used to be 445,372,660,000. Since 2026-10-22 `to_int` refuses
    # commas that are not thousands groups ("372/660" is not one), so a
    # fraction handed to it fails instead of reading a million times too big.
    assert digits.to_int(text) is None
    assert int("".join(c for c in text if c.isdigit())) == 445_372_660_000  # the trap
    assert HudReader(lambda: frame("in_game"), templates).pollen().value == 445_372


@pytest.mark.parametrize("name", ["app_home", "escape_menu", "reset_dialog"])
def test_a_screen_without_the_hud_is_not_an_empty_backpack(templates, name):
    """The conflation that would make the bot convert nothing all night."""
    reading = HudReader(lambda: frame(name), templates).pollen()
    assert reading.state is Read.NO_HUD
    assert reading.value is None


def test_missing_templates_are_their_own_state(templates):
    reading = HudReader(lambda: frame("in_game"), None).pollen()
    assert reading.state is Read.NO_TEMPLATES
    assert reading.value is None
    assert "templates" in reading.describe()


def test_a_capture_failure_is_counted_not_guessed():
    def broken():
        raise TimeoutError("capture deadline exceeded")

    reader = HudReader(broken, None)
    reading = reader.pollen()
    assert reading.state is Read.NO_FRAME and reading.value is None
    assert reader.frame_errors == 1 and "TimeoutError" in reader.last_error


# --- a full cycle, through the real route runner ---------------------------

def test_a_full_cycle_travels_gathers_returns_and_converts(clock):
    """Out, pattern, home, E, and honey counted from two real readings."""
    inp = FakeInput()
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(640_000),
                          pollen(640_000), pollen(0)],
                  honey_script=[honey(10_000_000), honey(10_450_000)], honey_after_e=True)
    loop, _, routes, events = build(clock, hud, routes=real_runner(inp), inp=inp)

    report = loop.run(cycles=1)

    assert report.cycles_done == 1
    cycle = report.cycles[0]
    assert cycle.ok, cycle.reason
    assert cycle.pattern_passes >= 1
    assert cycle.converted, cycle.convert_note
    assert cycle.honey_earned == 450_000
    assert report.honey_earned == 450_000
    assert "e" in taps(inp), "never pressed E to convert"
    assert inp.held_keys == set(), "a key survived the cycle"
    names = [e.name for e in events if isinstance(e, TaskUpdate)]
    assert "travel to the field" in names and "gather" in names
    assert "return to the hive" in names and "convert" in names


def test_the_backpack_filling_ends_the_gather_at_the_configured_percent(clock):
    hud = FakeHud(clock, [pollen(0), pollen(100_000), pollen(500_000),
                          pollen(0)], honey_script=[honey(1), honey(2)])
    loop, _, routes, _ = build(clock, hud, full_at=0.70)

    report = loop.run(cycles=1)
    cycle = report.cycles[0]

    assert "500,000/660,000 (76%)" in cycle.gather_ended
    # 400,000, not 500,000: the baseline is the counter as the gather STARTS.
    # The backpack arrived holding 100,000, and claiming that as gathered would
    # credit this cycle with pollen a previous one collected.
    assert cycle.pollen_gathered == 400_000
    assert routes.ran.count("collect_around") == 1, routes.ran


def test_arriving_with_a_full_backpack_turns_straight_round(clock):
    """A cycle whose convert failed leaves a full backpack behind.

    Gathering into a full backpack collects nothing, so a loop that does not
    check on arrival wastes the whole 420 s cap before noticing.
    """
    hud = FakeHud(clock, [pollen(650_000)], honey_script=[honey(5), honey(5)])
    loop, _, routes, _ = build(clock, hud, full_at=0.90)

    cycle = loop.run(cycles=1).cycles[0]

    assert cycle.pattern_passes == 0
    assert "arrived with the backpack already" in cycle.gather_ended
    assert "collect_around" not in routes.ran


# --- unreadable is not empty ------------------------------------------------

def test_an_unreadable_counter_never_becomes_a_number(clock):
    """The whole honesty rule, end to end.

    With the counter unreadable the loop must fall back to BeeTuxMacro's farm
    cap, claim no pollen and no honey, and SAY the reads failed -- not report a
    tidy zero that looks like a measurement of an empty field.
    """
    hud = FakeHud(clock, [UNREADABLE], honey_script=[UNREADABLE])
    loop, _, _, _ = build(clock, hud, stall_after=1e9, farm_seconds=60.0)

    report = loop.run(cycles=1)
    cycle = report.cycles[0]

    assert cycle.pollen_gathered is None, "claimed pollen it never read"
    assert cycle.honey_earned is None, "claimed honey it never read"
    assert report.honey_earned == 0 and report.cycles_measured == 0
    assert report.honey_per_hour is None, "invented a rate from nothing"
    assert "farm cap" in cycle.gather_ended
    assert report.reads[Read.UNREADABLE] > 0
    assert "unreadable" in report.describe()
    assert "unknown" in cycle.convert_note


def test_an_empty_backpack_is_a_different_state_from_an_unreadable_one(clock):
    """0/660,000 is a reading. It skips the dwell instead of sleeping 100 s."""
    hud = FakeHud(clock, [pollen(0)], honey_script=[honey(7), honey(7)])
    loop, inp, _, _ = build(clock, hud, stall_after=1e9, farm_seconds=12.0)

    cycle = loop.run(cycles=1).cycles[0]

    assert "nothing to convert" in cycle.convert_note
    assert "EMPTY" in cycle.convert_note
    assert "e" not in taps(inp), "pressed E with an empty backpack"
    assert cycle.honey_earned == 0, "honey was readable, so 0 is a measurement"


def test_the_report_separates_no_hud_from_unreadable(clock):
    """Two different problems with two different fixes; one counter each."""
    hud = FakeHud(clock, [UNREADABLE, UNREADABLE, NO_HUD])
    loop, _, _, _ = build(clock, hud, hud_wait_seconds=10.0)

    report = loop.run(cycles=1)

    assert report.reads[Read.UNREADABLE] == 2
    assert report.reads[Read.NO_HUD] >= 1


# --- stalling, and the recovery ladder -------------------------------------

def test_a_flat_pollen_counter_escalates_instead_of_farming_into_a_wall(clock):
    """MEASURED precedent: the bot can spawn wedged with `w` blocked by the
    hive wall, and a blocked `w` still changes 70% of the frame. Only the
    counter says whether gathering is actually happening."""
    hud = FakeHud(clock, [pollen(120_000)], honey_script=[honey(3), honey(3)])
    loop, inp, _, _ = build(clock, hud, stall_after=10.0)

    cycle = loop.run(cycles=1).cycles[0]

    assert cycle.recoveries == ["jump", "turn", "go_home"], cycle.recoveries
    assert taps(inp)[:2] == ["space", "period"], taps(inp)
    assert "going home rather than gathering into a wall" in cycle.gather_ended


def test_recovery_escalates_rather_than_repeating(clock):
    """Retrying the rung that just failed is how a bot spends an hour jumping."""
    hud = FakeHud(clock, [pollen(1_000)], honey_script=[honey(0), honey(0)])
    loop, inp, _, _ = build(clock, hud, stall_after=10.0)
    loop.run(cycles=1)
    assert taps(inp).count("space") == 1
    assert taps(inp).count("period") == 1


def test_the_ladder_resets_once_pollen_rises_again(clock):
    """The next obstacle is a different obstacle; it gets the cheap rung first."""
    script = [pollen(0), pollen(0), pollen(0), pollen(50_000),
              pollen(50_000), pollen(50_000), pollen(50_000)]
    hud = FakeHud(clock, script, honey_script=[honey(0), honey(0)])
    loop, inp, _, _ = build(clock, hud, stall_after=6.0)

    loop.run(cycles=1)

    assert taps(inp).count("space") == 2, "did not go back to the cheap rung"


def test_a_ladder_that_cannot_go_home_still_ends_the_gather(clock):
    hud = FakeHud(clock, [pollen(400)], honey_script=[honey(0), honey(0)])
    loop, _, _, _ = build(clock, hud, stall_after=8.0, ladder=(Rung.JUMP,))

    cycle = loop.run(cycles=1).cycles[0]

    assert "every recovery step has been tried" in cycle.gather_ended
    assert cycle.recoveries == ["jump"]


def test_an_unreadable_counter_after_a_rise_does_NOT_walk_out(clock):
    """CHANGED ON MEASUREMENT, TWICE, and it used to assert the opposite.

    "I cannot see it" and "it is not rising" need different words -- the cycle
    line says how often the counter was unreadable -- but they must not have
    the same CONSEQUENCE. An unreadable counter left the stall clock running,
    the ladder climbed to its last rung, `go_home`, and the trip ended.

    MEASURED 2026-09-22: the one trip whose counter read cleanly ran the full
    1,208 s, gathered 476,000 pollen over 90 passes and earned 156,189 honey.
    Every trip whose counter read "212?1,072,500 at confidence 0.19" ended at
    about 237 s over 18 passes for roughly 800 honey, with "recovered 2x
    (jump, go_home)" in the cycle line -- the ladder walking out of a field it
    could not see. Two hundred times the honey, decided by a digit read.

    THE FORGIVENESS IS CONDITIONAL, which the first version of this fix got
    wrong; see the test below. Once pollen has risen we know the trip is
    gathering, so an illegible counter is a reading problem and is tolerated
    for the rest of the trip. The trip still ends on `farm_seconds`, which the
    planner computes from the field's measured rate.
    """
    # PADDED ON PURPOSE: reads before the gather loop (the arrival check and
    # the convert's own before/after) consume the front of this script, so a
    # single rising entry never reaches the loop. The repeats make the rise
    # land wherever the loop's first read happens to fall.
    hud = FakeHud(clock, [pollen(0)] * 6 + [pollen(90_000)] * 6 + [UNREADABLE],
                  honey_script=[honey(0), honey(0)])
    loop, _, _, _ = build(clock, hud, stall_after=8.0, farm_seconds=200.0)

    cycle = loop.run(cycles=1).cycles[0]

    assert "farm cap" in cycle.gather_ended, cycle.gather_ended
    # It may well have jumped BEFORE the rise, while the counter was readable
    # and genuinely flat -- that is the ladder working. What it must not do is
    # reach the last rung and leave a field it simply could not see.
    assert "go_home" not in cycle.recoveries, cycle.recoveries
    assert cycle.pollen_gathered == 90_000
    assert cycle.unreadable_pollen > 0
    assert "unreadable" in cycle.describe()


def test_an_unreadable_counter_with_nothing_gathered_DOES_go_home(clock):
    """The other half: forgiveness has to be earned.

    NOT FROM A MEASUREMENT. The first version of this docstring claimed a live
    trip on 2026-09-22 05:15 had sat at 53,656 pollen for eight minutes while
    the ladder stayed silent. That was my misreading: "carrying N pollen" in
    the log is the PLANNER's figure, captured when it picks a field and
    reprinted each time it explains itself, not the live backpack. That trip
    in fact gathered 442,156 pollen over 1,030 s and 76 passes -- about 429
    pollen/s, one of the best of the night -- and the ladder was silent
    because pollen was rising, exactly as intended.

    The gate stands on reasoning instead. Suppressing the stall ladder on an
    unreadable counter is a claim that the trip is fine really; that claim
    needs some evidence, and a trip whose counter has never once been read
    high enough to show a rise has none at all. Until pollen has gone up, an
    unreadable counter is treated exactly as a flat one was before -- which
    only restores the old behaviour, in the one case where there is nothing
    to go on. After a rise, the forgiveness in the test above applies.
    """
    hud = FakeHud(clock, [UNREADABLE], honey_script=[honey(0), honey(0)])
    loop, _, _, _ = build(clock, hud, stall_after=8.0)

    cycle = loop.run(cycles=1).cycles[0]

    assert "go_home" in cycle.recoveries, cycle.recoveries
    assert "unreadable" in cycle.gather_ended, cycle.gather_ended
    assert cycle.unreadable_pollen > 0

def test_a_hive_that_does_not_convert_is_reported_not_slept_through(clock):
    """BeeTuxMacro presses E and sleeps 100 s. Unattended, that cannot tell
    converting from standing next to somebody else's hive -- and the owner's
    correction is that there is no fixed slot to walk to at all."""
    hud = FakeHud(clock, [pollen(600_000)], honey_script=[honey(9), honey(9)])
    loop, inp, _, _ = build(clock, hud, stall_after=1e9, farm_seconds=10.0,
                            convert_confirm_seconds=10.0, convert_seconds=300.0)

    cycle = loop.run(cycles=1).cycles[0]

    assert not cycle.converted
    assert "not a hive we own" in cycle.convert_note
    assert taps(inp).count("e") == 2, "should press E once more before giving up"
    assert clock.now < 300.0, "sat out the whole dwell instead of concluding"


def test_the_convert_waits_while_the_counter_is_falling(clock):
    hud = FakeHud(clock, [pollen(600_000), pollen(600_000), pollen(300_000),
                          pollen(0)], honey_script=[honey(0), honey(600_000)], honey_after_e=True)
    loop, inp, _, _ = build(clock, hud, full_at=0.5, stall_after=1e9)

    cycle = loop.run(cycles=1).cycles[0]

    assert cycle.converted and cycle.honey_earned == 600_000
    assert taps(inp).count("e") == 1, "prompted again while it was working"


def test_honey_that_cannot_be_read_is_not_counted_as_zero(clock):
    hud = FakeHud(clock, [pollen(600_000), pollen(600_000), pollen(0)],
                  honey_script=[UNREADABLE])
    loop, _, _, _ = build(clock, hud, full_at=0.5, stall_after=1e9)

    report = loop.run(cycles=1)

    assert report.cycles[0].honey_earned is None
    assert "honey not measured" in report.cycles[0].honey_note
    assert report.honey_per_hour is None


# --- stopping ---------------------------------------------------------------

def test_stop_requested_mid_gather_ends_the_loop_promptly(clock):
    stop = threading.Event()
    inp = FakeInput()
    routes = FakeRoutes(inp, clock, on_run=lambda name, n: stop.set()
                        if name == "collect_around" and n >= 3 else None)
    hud = FakeHud(clock, [pollen(1_000), pollen(2_000), pollen(3_000)])
    loop, _, _, _ = build(clock, hud, routes=routes, inp=inp, stop=stop)

    report = loop.run()

    assert report.stopped_because == "stop requested"
    assert "from_pine_tree_to_hive" not in routes.ran, "walked home after stop"
    assert inp.held_keys == set()


def test_stop_aborts_a_route_between_steps(clock):
    """The return leg is 1,068 studs -- 38 s -- so waiting for it to finish is
    not "stopping promptly", and a stop usually means something is wrong."""
    stop = threading.Event()
    inp = FakeInput()
    routes = FakeRoutes(inp, clock, steps=50,
                        on_run=lambda name, n: stop.set())
    hud = FakeHud(clock, [pollen(0)])
    loop, _, _, _ = build(clock, hud, routes=routes, inp=inp, stop=stop)

    loop.run()

    assert routes.steps_run == 0, "ran steps after the stop was requested"
    assert inp.held_keys == set()


def test_the_runners_own_step_hook_is_restored(clock):
    """The loop borrows `on_step`; a caller's telemetry hook must survive."""
    inp = FakeInput()
    routes = FakeRoutes(inp, clock)
    seen: list[str] = []
    routes.on_step = lambda op, step: seen.append(op)
    hud = FakeHud(clock, [pollen(0), pollen(650_000), pollen(0)],
                  honey_script=[honey(0), honey(1)])
    loop, _, _, _ = build(clock, hud, routes=routes, inp=inp)

    loop.run(cycles=1)

    assert seen, "the caller's hook stopped being called"
    assert routes.on_step is not None


# --- never getting permanently stuck ---------------------------------------

def test_a_missing_route_stops_the_loop_instead_of_spinning(clock):
    inp = FakeInput()
    routes = FakeRoutes(inp, clock, missing=("collect_around",))
    hud = FakeHud(clock, [pollen(0)])
    loop, _, _, _ = build(clock, hud, routes=routes, inp=inp)

    report = loop.run()

    assert "no route named" in report.stopped_because
    assert report.cycles_done == 1, "kept trying a route that does not exist"


def test_cycles_that_measure_nothing_stop_the_loop(clock):
    """Four brakes exist; this is the one that catches "everything works and
    nothing happens" -- the failure that otherwise runs until morning."""
    hud = FakeHud(clock, [pollen(0)], honey_script=[honey(500), honey(500)])
    loop, _, _, events = build(clock, hud, stall_after=1e9, farm_seconds=9.0,
                               max_barren_cycles=2)

    report = loop.run()

    assert report.cycles_done == 2
    assert "needs a human" in report.stopped_because
    assert any(isinstance(e, Log) and e.level is Level.WARN for e in events)


def test_a_hud_that_never_appears_stops_the_loop_and_presses_nothing(clock):
    """There is no key that fixes "not in the game": Escape opens the menu
    carrying Leave, and Return on it is the keystroke this project is most
    careful about."""
    inp = FakeInput()
    routes = FakeRoutes(inp, clock)
    hud = FakeHud(clock, [NO_HUD])
    loop, _, _, _ = build(clock, hud, routes=routes, inp=inp,
                          hud_wait_seconds=20.0)

    report = loop.run()

    assert "HUD did not appear" in report.stopped_because
    assert routes.ran == [], "walked while not in the world"
    assert taps(inp) == []


def test_the_session_limit_is_honoured(clock):
    hud = FakeHud(clock, [pollen(0), pollen(650_000), pollen(0)],
                  honey_script=[honey(0), honey(1_000)])
    loop, _, _, _ = build(clock, hud, stall_after=1e9)

    report = loop.run(max_seconds=5.0)

    assert "session limit" in report.stopped_because


# --- nothing is left held, on any path -------------------------------------

def test_an_exception_is_recorded_rather_than_hidden(clock):
    inp = FakeInput()
    routes = FakeRoutes(inp, clock, raise_on="collect_around")
    hud = FakeHud(clock, [pollen(0)])
    loop, _, _, events = build(clock, hud, routes=routes, inp=inp)

    report = loop.run()

    assert "RuntimeError" in report.error
    assert "compositor went away" in report.stopped_because
    assert any(isinstance(e, Log) and e.level is Level.ERROR for e in events)
    assert inp.held_keys == set()


@pytest.mark.parametrize("scenario", ["clean", "stopped", "crash", "stall"])
def test_no_key_is_left_held_on_any_exit_path(clock, scenario):
    """A stuck key is the worst failure this program has: the character runs
    into a wall forever. Four layers guard it; this checks the loop's own."""
    inp = FakeInput()
    stop = threading.Event()
    routes = FakeRoutes(inp, clock)
    hud = FakeHud(clock, [pollen(0), pollen(650_000), pollen(0)],
                  honey_script=[honey(0), honey(1)])
    kwargs = {}
    if scenario == "stopped":
        routes.on_run = lambda name, n: stop.set()
    elif scenario == "crash":
        routes.raise_on = "collect_around"
    elif scenario == "stall":
        hud = FakeHud(clock, [pollen(5)], honey_script=[honey(0), honey(0)])
        kwargs["stall_after"] = 8.0

    loop, _, _, _ = build(clock, hud, routes=routes, inp=inp,
                          stop=stop if scenario == "stopped" else None, **kwargs)
    loop.run(cycles=1)

    assert inp.held_keys == set(), f"{scenario}: a key was left down"
    assert ("release_all", None) in inp.events


def test_the_loop_never_presses_escape_or_return(clock):
    """Escape opens the in-game menu that carries Leave, and the respawn
    confirmation is a DIFFERENT screen. Resetting is RouteRunner's job, where
    it is gated on seeing the confirmation. This loop has no business there."""
    inp = FakeInput()
    hud = FakeHud(clock, [pollen(0), pollen(650_000), pollen(0)],
                  honey_script=[honey(0), honey(1)])
    loop, _, _, _ = build(clock, hud, routes=real_runner(inp), inp=inp)

    loop.run(cycles=2)

    assert set(taps(inp)) <= {"e", "space", "period", "shift", "comma",
                              "pageup", "pagedown", "o"}, taps(inp)
    assert "enter" not in taps(inp) and "escape" not in taps(inp)


# --- telemetry --------------------------------------------------------------

def test_it_says_what_it_is_doing(clock):
    # the full bag held for the reads the loop makes on the way home
    hud = FakeHud(clock, [pollen(0), pollen(650_000), pollen(650_000),
                          pollen(650_000), pollen(0)],
                  honey_script=[honey(100), honey(700)], honey_after_e=True)
    loop, _, _, events = build(clock, hud)

    loop.run(cycles=1)

    metrics = {e.name: e.value for e in events if isinstance(e, Metric)}
    assert metrics["honey_earned"] == 600
    assert metrics["cycles"] == 1
    assert "backpack_fill" in metrics
    statuses = [e for e in events if getattr(e, "kind", "") == "status"]
    assert statuses[0].running and not statuses[-1].running


def test_progress_is_indeterminate_rather_than_zero_when_unreadable(clock):
    """0.0 on a progress bar reads as "empty backpack"; -1 means "unknown",
    which is what the event protocol reserves a negative for."""
    hud = FakeHud(clock, [UNREADABLE], honey_script=[honey(0), honey(0)])
    loop, _, _, events = build(clock, hud, stall_after=1e9, farm_seconds=9.0)

    loop.run(cycles=1)

    gather = [e for e in events if isinstance(e, TaskUpdate)
              and e.name == "gather" and e.status == "running"]
    assert gather and all(e.progress < 0 for e in gather[1:])


def test_a_broken_telemetry_link_does_not_end_the_night(clock):
    def broken(_event):
        raise BrokenPipeError("the GUI went away")

    hud = FakeHud(clock, [pollen(0), pollen(650_000), pollen(0)],
                  honey_script=[honey(0), honey(1)])
    inp = FakeInput()
    loop = FarmLoop(FakeRoutes(inp, clock), hud, vin=inp, clock=clock,
                    sleep=clock.sleep, emit=broken)

    report = loop.run(cycles=1)

    assert report.cycles_done == 1 and not report.error
    assert loop.telemetry_errors > 0, "swallowed the failure without counting it"


def test_it_refuses_to_run_without_an_input_client(clock):
    hud = FakeHud(clock, [pollen(0)])
    with pytest.raises(ValueError, match="input client"):
        FarmLoop(object(), hud, clock=clock, sleep=clock.sleep)


# --- the numbers themselves -------------------------------------------------

def test_every_constant_traces_back_to_a_source():
    """Guards the rule, not the values: these came out of BeeTuxMacro's config
    and the shipped route graph, and a silent edit to a round number is exactly
    what the rule exists to catch."""
    assert farm.CONVERT_SECONDS == 100.0            # config.sh:66 CONVERT_TIME
    assert farm.FARM_CAP_SECONDS == 420.0           # config.sh:64 FARM_SECONDS
    assert farm.FULL_AT == 0.90                     # settings.py convert-at %
    assert farm.STALL_SECONDS == farm.FARM_CAP_SECONDS / 4
    assert farm.CONVERT_CONFIRM_SECONDS == farm.CONVERT_SECONDS * 0.15
    assert farm.OUT_ROUTES == ("from_hive_to_pine_tree_with_red_cannon",)
    assert farm.HOME_ROUTES == ("from_pine_tree_to_hive",)


def test_the_default_routes_exist_in_the_shipped_graph():
    """A default that names a route nobody transpiled stops the loop on cycle
    one, at night, with the owner asleep."""
    router = Router()
    names = {e.name for e in router.edges} | set(router.routines)
    for name in farm.OUT_ROUTES + farm.HOME_ROUTES + (farm.PATTERN,):
        assert name in names, f"{name} is not in data/world/paths.yaml"


# --- losing the world mid-trip ---------------------------------------------

def test_the_hud_vanishing_mid_gather_abandons_the_trip_quietly(clock):
    """A disconnect dialog, a respawn or the app UI all read as "no HUD", and
    none of them is a screen to press keys at. The ladder is the wrong answer:
    jumping and turning cannot bring the world back."""
    inp = FakeInput()
    routes = FakeRoutes(inp, clock)
    hud = FakeHud(clock, [pollen(10_000), NO_HUD], honey_script=[honey(5)])
    loop, _, _, _ = build(clock, hud, routes=routes, inp=inp, stall_after=1e9,
                          hud_wait_seconds=12.0)

    report = loop.run()

    assert report.cycles[0].lost_hud
    assert "off screen" in report.cycles[0].gather_ended
    assert "from_pine_tree_to_hive" not in routes.ran, "walked home blind"
    assert taps(inp) == [], "pressed a key at a screen it could not see"
    assert "HUD did not appear" in report.stopped_because


def test_the_world_coming_back_resumes_farming(clock):
    """The abandoned trip must not end the night: Roblox reconnects."""
    inp = FakeInput()
    hud = FakeHud(clock, [pollen(10_000), NO_HUD, NO_HUD, NO_HUD, NO_HUD,
                          pollen(600_000), pollen(600_000), pollen(600_000),
                          pollen(0)],
                  honey_script=[honey(0), honey(80_000)], honey_after_e=True)
    loop, _, routes, _ = build(clock, hud, routes=FakeRoutes(inp, clock),
                               inp=inp, stall_after=1e9, hud_wait_seconds=60.0)

    report = loop.run(cycles=2)

    assert report.cycles[0].lost_hud and not report.cycles[1].lost_hud
    assert report.cycles[1].converted
    assert report.honey_earned == 80_000


def test_no_e_is_pressed_at_a_hive_it_cannot_see(clock):
    inp = FakeInput()
    hud = FakeHud(clock, [pollen(650_000), pollen(650_000), NO_HUD],
                  honey_script=[honey(1), honey(1)])
    loop, _, _, _ = build(clock, hud, routes=FakeRoutes(inp, clock), inp=inp,
                          full_at=0.5, stall_after=1e9, hud_wait_seconds=8.0)

    report = loop.run(cycles=1)

    assert "pressing nothing" in report.cycles[0].convert_note
    assert "e" not in taps(inp)


# --- handing every completed trip to whoever is keeping the record ---------

def test_every_completed_trip_is_handed_to_on_cycle(clock):
    """The ledger's only source. A trip the hook never sees is a trip that
    vanishes when the run restarts, and the night restarted 134 times."""
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(640_000),
                          pollen(0), pollen(200_000), pollen(640_000),
                          pollen(0)],
                  honey_script=[honey(0), honey(500), honey(500), honey(900)])
    seen: list = []
    loop, _, _, _ = build(clock, hud, on_cycle=seen.append)

    report = loop.run(cycles=2)

    assert [c.number for c in seen] == [1, 2]
    assert seen == report.cycles, "the hook must get the same objects reported"


def test_a_hook_that_raises_costs_the_record_not_the_honey(clock):
    """Bookkeeping that ends the night is worse than no bookkeeping."""
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(640_000),
                          pollen(0)], honey_script=[honey(0), honey(500)])

    def explode(cycle):
        raise OSError("disk full")

    loop, _, _, events = build(clock, hud, on_cycle=explode)

    report = loop.run(cycles=1)

    assert report.cycles_done == 1
    assert not report.error, "the trip still happened"
    assert any("could not record the trip" in getattr(e, "message", "")
               for e in events), "and it says so, rather than failing quietly"


class FakeJourney:
    """Just enough journey for `_travel` to reach `_told_travel`.

    Without one, `_travel` returns at its first line -- `if self.journey is
    None` -- and the two tests below pass without exercising anything, which
    is how the first draft of them was written.
    """

    def __init__(self, ok: bool = False, reason: str = "did not arrive"):
        self.ok, self.reason = ok, reason

    def go(self, destination, routes):
        from hivemind.nav.journey import Outcome
        return Outcome(destination=destination, ok=self.ok,
                       reason="" if self.ok else self.reason)

    def home(self, routes, find=None):
        from hivemind.nav.journey import Outcome
        return Outcome(destination="hive", ok=True)


def test_a_trip_with_no_field_name_records_nothing(clock):
    """REGRESSION, and it was an infinite loop.

    `_travel` falls back to the display label -- `destination = self.field or
    "the field"` -- so the log reads well when the plan named no field.
    Passing that label on wrote a FIELD called "the field" into the notes,
    where it absorbed the failures belonging to the field actually being
    attempted. MEASURED 2026-09-22 06:33: `the field  failures=3` while the
    real field sat at zero, so it never reached
    `decide.TRAVEL_FAILURES_TO_GIVE_UP` and was chosen again every cycle.
    Runs 149, 150 and 151 each did "cycle 1: 0s gathering over 0 passes".
    """
    told: list = []
    hud = FakeHud(clock, [pollen(0)], honey_script=[honey(0), honey(0)])
    loop, _, _, _ = build(clock, hud, on_travel=lambda f, a: told.append(f),
                          journey=FakeJourney(ok=False))
    loop.field = None

    loop.run(cycles=1)

    assert told == [], f"recorded a note under a placeholder: {told}"


def test_a_trip_with_a_field_name_still_reports_it(clock):
    """The other half: the real name must still get through."""
    told: list = []
    hud = FakeHud(clock, [pollen(0)], honey_script=[honey(0), honey(0)])
    loop, _, _, _ = build(clock, hud, on_travel=lambda f, a: told.append(f),
                          journey=FakeJourney(ok=False))
    loop.field = "dandelion"

    loop.run(cycles=1)

    assert told == ["dandelion"], told


def test_a_route_refused_for_a_stop_is_no_verdict_on_the_field(clock):
    """2026-10-20 20:17: a deploy's stop refused the walk out to Pumpkin, and
    that was booked as a travel failure toward Pumpkin's ban."""
    told: list = []
    hud = FakeHud(clock, [pollen(0)], honey_script=[honey(0), honey(0)])
    loop, _, _, _ = build(clock, hud, on_travel=lambda f, a: told.append(f),
                          journey=FakeJourney(ok=False, reason=(
                              "natro_out_pumpkin_via_red_cannon: not walked — stop requested")))
    loop.field = "pumpkin"

    loop.run(cycles=1)

    assert told == [], told


# ---- the gather camera tilt -----------------------------------------------------

def test_the_gather_tilt_is_applied_for_the_gather_and_undone_before_the_walk_home(clock):
    """The common blue-hive gather view: PageUp once for a blue hive. It is
    for the gather only -- the hive compass was measured at tilt 0, so the
    tilt comes off before anything walks home."""
    inp = FakeInput()
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(640_000),
                          pollen(640_000), pollen(0)],
                  honey_script=[honey(10_000_000), honey(10_450_000)], honey_after_e=True)
    loop, _, routes, events = build(clock, hud, routes=real_runner(inp), inp=inp,
                                    gather_tilt=1)

    report = loop.run(cycles=1)

    assert report.cycles_done == 1 and report.cycles[0].ok
    t = taps(inp)
    assert t.count("pageup") == 1 and t.count("pagedown") == 1, t
    assert t.index("pageup") < t.index("pagedown")
    # undone before the return leg's first key, and before the convert press
    assert t.index("pagedown") < t.index("e"), t
    said = [getattr(e, "message", "") for e in events]
    assert any("camera tilted 1 PageUp" in m for m in said), said


def test_no_tilt_means_no_camera_keys_at_all(clock):
    inp = FakeInput()
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(640_000),
                          pollen(640_000), pollen(0)],
                  honey_script=[honey(10_000_000), honey(10_450_000)], honey_after_e=True)
    loop, _, routes, events = build(clock, hud, routes=real_runner(inp), inp=inp)
    loop.run(cycles=1)
    t = taps(inp)
    assert "pageup" not in t and "pagedown" not in t
    assert "o" not in t and "i" not in t


def test_the_gather_zoom_is_applied_for_the_gather_and_undone_before_the_walk_home(clock):
    """Natro's gather view: zoomed out (five O taps after every reset). For
    the gather only, like the tilt -- every O gets its I before anything
    walks home or presses E on the pad."""
    inp = FakeInput()
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(640_000),
                          pollen(640_000), pollen(0)],
                  honey_script=[honey(10_000_000), honey(10_450_000)], honey_after_e=True)
    loop, _, routes, events = build(clock, hud, routes=real_runner(inp), inp=inp,
                                    gather_zoom=3)

    report = loop.run(cycles=1)

    assert report.cycles_done == 1 and report.cycles[0].ok
    t = taps(inp)
    assert t.count("o") == 3 and t.count("i") == 3, t
    assert max(k for k, key in enumerate(t) if key == "o") < t.index("i"), t
    assert max(k for k, key in enumerate(t) if key == "i") < t.index("e"), t
    said = [getattr(e, "message", "") for e in events]
    assert any("camera zoomed out 3 tap(s)" in m for m in said), said


def test_the_gather_zoom_is_held_to_natros_most():
    from hivemind.brain.farm import GATHER_ZOOM_MOST, gather_zoom_from

    class Settings:
        def __init__(self, value):
            self.value = value

        def int(self, key):
            assert key == "gather.camera_zoom_out"
            return self.value

    assert gather_zoom_from(Settings(5)) == 5
    assert gather_zoom_from(Settings(50)) == GATHER_ZOOM_MOST == 8
    assert gather_zoom_from(Settings(-2)) == 0
    assert gather_zoom_from(object()) == 0


# ---- a full backpack whose counter cannot be read -------------------------------

def test_a_bar_only_fill_still_reaches_the_planner(clock):
    """MEASURED 2026-09-22 23:37 to 2026-09-23 00:22: with the bag full the
    counter read "11?0?46/111???0" at 0.49, `value` was None, the planner saw
    no backpack at all, never chose to convert, and six attempts in a row
    gathered into a full bag with the honey stuck at 7,256,845."""
    seen = []

    def plan(pollen_value, capacity):
        seen.append((pollen_value, capacity))
        return {"action": "convert", "why": "the bag is full"}

    # a legible read first (so the capacity is learned), then a counter that
    # cannot be parsed with the bar HALF full -- not full enough to decide on
    # its own, so the planner must still be given a number to weigh
    hud = FakeHud(clock, [pollen(200_000, capacity=1_000_000)])
    loop, _, routes, events = build(clock, hud, plan=plan)

    cycle = farm.Cycle(number=1, started_at=clock())
    assert loop._choose(cycle) is False          # the planner said convert
    hud.pollen_script = [unreadable(bar_fill=0.5)]
    hud.pollen_reads = 0
    assert loop._choose(cycle) is False

    assert seen[0] == (200_000, 1_000_000)
    assert seen[1] == (500_000, 1_000_000), seen
    said = [getattr(e, "message", "") for e in events]
    assert any("the bar looks 50% full" in m for m in said), said


def test_without_a_capacity_a_bar_only_fill_is_not_invented(clock):
    """No legible counter has been read this session, so there is no capacity
    to multiply the bar by, and nothing is guessed."""
    seen = []

    def plan(pollen_value, capacity):
        seen.append((pollen_value, capacity))
        return {"action": "convert", "why": "nothing to go on"}

    hud = FakeHud(clock, [unreadable(bar_fill=0.4)])      # not full: the planner decides
    loop, _, routes, events = build(clock, hud, plan=plan)
    loop._choose(farm.Cycle(number=1, started_at=clock()))
    assert seen and seen[0] == (None, None)


def test_a_full_bar_with_no_number_at_all_still_converts_instead_of_travelling(clock):
    """MEASURED 2026-09-23 00:32: the counter read "1?0?419/111???0", the bar
    said 100%, no legible capacity had been read this session, so the planner
    got nothing, travelled to Stump by cannon and turned straight round."""
    asked = []

    def plan(pollen_value, capacity):
        asked.append((pollen_value, capacity))
        return {"action": "gather", "field": "stump", "out": ["out"], "home": ["home"],
                "why": "off we go"}

    hud = FakeHud(clock, [unreadable(bar_fill=1.0)])
    loop, _, routes, events = build(clock, hud, plan=plan)
    cycle = farm.Cycle(number=1, started_at=clock())

    assert loop._choose(cycle) is False, "it must not travel with a full bag"
    assert asked == [], "the planner was not even asked"
    assert "the bar looks 100% full" in cycle.reason


def test_the_after_convert_errand_runs_only_on_a_confirmed_convert(clock):
    """The one cheap moment: bag empty, standing on our own pad, the honey
    counter settled. MEASURED 2026-09-22 23:38: running it at session start
    instead cost attempt 256 its whole session."""
    ran = []
    inp = FakeInput()
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(640_000),
                          pollen(640_000), pollen(0), pollen(0)],
                  honey_script=[honey(10_000_000), honey(10_450_000),
                                honey(10_450_000)])
    loop, _, routes, events = build(clock, hud, routes=real_runner(inp), inp=inp,
                                    after_convert=lambda cycle: ran.append(cycle.number))

    report = loop.run(cycles=1)

    assert report.cycles[0].converted, report.cycles[0].convert_note
    assert ran == [1], ran


def test_a_failed_convert_runs_no_errand(clock):
    ran = []
    hud = FakeHud(clock, [pollen(200_000)], honey_script=[honey(1_000_000)])
    loop, _, routes, events = build(clock, hud,
                                    after_convert=lambda cycle: ran.append(1),
                                    confirm_hive=lambda: False)
    loop.run(cycles=1)
    assert ran == []


def test_an_errand_that_raises_does_not_end_the_night(clock):
    inp = FakeInput()
    hud = FakeHud(clock, [pollen(0), pollen(200_000), pollen(640_000),
                          pollen(640_000), pollen(0), pollen(0)],
                  honey_script=[honey(10_000_000), honey(10_450_000),
                                honey(10_450_000)])

    def boom(cycle):
        raise RuntimeError("the bear was out")

    loop, _, routes, events = build(clock, hud, routes=real_runner(inp), inp=inp,
                                    after_convert=boom)
    report = loop.run(cycles=1)
    assert report.cycles[0].converted
    said = [getattr(e, "message", "") for e in events]
    assert any("after-convert errand failed" in m for m in said), said


def test_a_bar_only_full_reading_must_say_it_twice_before_ending_a_trip(clock):
    """MEASURED 2026-09-23 02:28 (attempt 283): a cannon flight landed and the
    trip ended with "0s gathering over 0 passes". One frame of a moving
    character is not worth a 1,200-second trip."""
    inp = FakeInput()
    hud = FakeHud(clock, [pollen(0)])
    loop, _, routes, events = build(clock, hud, routes=real_runner(inp), inp=inp)
    loop.farm_seconds = 40.0
    # the gather's own reads: bar says full, a second look says it is not,
    # then a real figure, then full for real so the loop ends
    hud.pollen_script = [unreadable(bar_fill=1.0), unreadable(bar_fill=0.1),
                         pollen(50_000), pollen(1_100_000)]
    hud.pollen_reads = 0
    cycle = farm.Cycle(number=1, started_at=clock())
    report = farm.Report()
    loop._gather(cycle, report)

    assert cycle.pattern_passes >= 1, cycle.gather_ended
    said = [getattr(e, "message", "") for e in events]
    assert any("a second look said" in m for m in said), said


def test_a_counter_measured_full_backpack_still_turns_straight_round(clock):
    hud = FakeHud(clock, [pollen(1_100_000), pollen(1_100_000), pollen(1_100_000)],
                  honey_script=[honey(1_000_000), honey(2_000_000)])
    loop, _, routes, events = build(clock, hud)
    report = loop.run(cycles=1)
    cycle = report.cycles[0]
    assert cycle.pattern_passes == 0
    assert "already" in cycle.gather_ended and "turning straight round" in cycle.gather_ended


def test_a_gather_that_walked_nothing_says_why(clock):
    hud = FakeHud(clock, [pollen(1_100_000)], honey_script=[honey(1_000_000), honey(2_000_000)])
    loop, _, routes, events = build(clock, hud)
    cycle = loop.run(cycles=1).cycles[0]
    assert "gathered nothing:" in cycle.describe(), cycle.describe()

# ---- the errand's premise has to be true, not inferred ---------------------
# MEASURED 2026-09-23 04:04 (attempt 292): the walk home failed, the convert
# correctly REFUSED to press E because nothing confirmed a hive in front of
# the character -- and the after-convert errand ran anyway, announcing "the
# backpack is empty and we are on our own pad" while its own saved frame
# shows the HUD reading 1,092,706/1,113,750 (98%) and the character wedged
# against a fence. The condition had been `converted or honey_earned > 0`,
# and honey rises on its own from the hive's trickle.

def test_a_honey_trickle_is_not_a_convert():
    from hivemind.brain.farm import Cycle, errand_is_safe
    cycle = Cycle(number=1)
    cycle.converted = False
    cycle.honey_earned = 873
    assert not errand_is_safe(cycle)


def test_a_confirmed_convert_is():
    from hivemind.brain.farm import Cycle, errand_is_safe
    cycle = Cycle(number=1)
    cycle.converted = True
    assert errand_is_safe(cycle)


def test_a_cycle_that_says_nothing_is_not_safe():
    from hivemind.brain.farm import Cycle, errand_is_safe
    assert not errand_is_safe(Cycle(number=1))


# ---- the bar watches the convert when the digits cannot --------------------
# MEASURED 2026-09-23 05:19 (attempt 297): the convert fired on the BAR ("the
# bar looks 93% full"), pressed E, banked 1,117,190 honey, and then reported
# "the convert dwell elapsed without a single readable pollen counter, so
# whether it converted is unknown". `cycle.converted` stayed False, so every
# errand gated on a confirmed convert was skipped -- including the two quest
# hand-ins that were waiting. The digits are illegible at seven figures, which
# is exactly when a convert happens, because the backpack is full.

def _bar(fill, text="10??,?88/1,113,750"):
    """A pollen reading with no legible digits and a readable bar."""
    return Reading(Read.UNREADABLE, text=text, score=0.54, bar_fill=fill)


def test_a_convert_confirms_on_the_bar_when_the_digits_never_read(clock):
    hud = FakeHud(clock, [_bar(0.93), _bar(0.93), _bar(0.40), _bar(0.0)],
                  honey_script=[honey(17_523_581), honey(18_640_771)], honey_after_e=True)
    loop, inp, _, _ = build(clock, hud, full_at=0.5, stall_after=1e9)

    cycle = loop.run(cycles=1).cycles[0]

    assert cycle.converted, cycle.convert_note
    assert cycle.honey_earned == 1_117_190
    assert taps(inp).count("e") == 1


def test_a_bar_that_never_drains_is_not_a_convert(clock):
    hud = FakeHud(clock, [_bar(0.93)] * 6, honey_script=[honey(1), honey(1)])
    loop, _, _, _ = build(clock, hud, full_at=0.5, stall_after=1e9)

    cycle = loop.run(cycles=1).cycles[0]

    assert not cycle.converted, cycle.convert_note


def test_the_errand_runs_after_a_bar_confirmed_convert(clock):
    """The point of the fix: the hand-ins were being skipped."""
    from hivemind.brain.farm import errand_is_safe
    hud = FakeHud(clock, [_bar(0.93), _bar(0.93), _bar(0.0)],
                  honey_script=[honey(100), honey(1_100)])
    loop, _, _, _ = build(clock, hud, full_at=0.5, stall_after=1e9)

    cycle = loop.run(cycles=1).cycles[0]

    assert errand_is_safe(cycle), cycle.convert_note


def test_legible_digits_are_not_overruled_by_the_bar(clock):
    """The bar is the FALLBACK, not a replacement. Here the counter reads
    perfectly well and the bar is stuck at full -- which is the failure the
    bar itself has (a frame caught mid-flight, or the pill over a bright
    field, DESIGN 8as). The digits must decide."""
    def with_stuck_bar(value):
        return Reading(Read.OK, value, CAPACITY, f"{value:,}/{CAPACITY:,}",
                       1.0, bar_fill=1.0)

    hud = FakeHud(clock, [with_stuck_bar(600_000), with_stuck_bar(600_000),
                          with_stuck_bar(300_000), with_stuck_bar(0)],
                  honey_script=[honey(0), honey(600_000)], honey_after_e=True)
    loop, _, _, _ = build(clock, hud, full_at=0.5, stall_after=1e9)

    cycle = loop.run(cycles=1).cycles[0]

    assert cycle.converted, cycle.convert_note
    assert cycle.honey_earned == 600_000


# ---- one detour, more than one token ---------------------------------------
# THE OWNER, 2026-09-23, asked for a higher capture rate. MEASURED over 1,587 chases:
# the median frame has 16 tokens in view and the detour took exactly one
# before going back to the pattern. The chase itself lands 93% of the time
# (498 of 533 walked onto their token); it simply only ever got one turn.

def _bare_loop(chase):
    """A FarmLoop with nothing wired but the chase. `_chase_a_token` needs
    only `self.chase`, `self._stopped` and `self._emit`."""
    from hivemind.brain.farm import FarmLoop
    loop = FarmLoop.__new__(FarmLoop)
    loop.chase = chase
    loop.bearings = None
    loop.chase_tokens = True
    loop._stop = None
    loop.emit = None
    loop._stopped = lambda: False
    loop._emit = lambda event: None
    return loop


def _bare_cycle():
    from hivemind.brain.farm import Cycle
    return Cycle(number=1)


class _Chases:
    """A chase that succeeds `wins` times then declines, like the real one
    does when nothing is left worth walking to."""

    def __init__(self, wins):
        self.wins, self.calls = wins, 0

    def __call__(self):
        self.calls += 1
        walked = self.calls <= self.wins
        return SimpleNamespace(
            walked=walked, studs=10.0,
            describe=lambda: ("walked onto it" if walked else "held"))


def test_one_detour_takes_more_than_one_token():
    from hivemind.brain.farm import CHASE_CHAIN
    chase = _Chases(wins=99)
    loop = _bare_loop(chase=chase)
    cycle = _bare_cycle()
    loop._chase_a_token(cycle)
    assert chase.calls == CHASE_CHAIN, chase.calls
    assert cycle.tokens_chased == CHASE_CHAIN


def test_the_chain_stops_when_nothing_is_left_worth_taking():
    chase = _Chases(wins=1)
    loop = _bare_loop(chase=chase)
    cycle = _bare_cycle()
    loop._chase_a_token(cycle)
    assert cycle.tokens_chased == 1
    assert chase.calls == 2, "it did not try once more, or it kept going"


def test_a_detour_that_never_started_takes_nothing():
    chase = _Chases(wins=0)
    loop = _bare_loop(chase=chase)
    cycle = _bare_cycle()
    loop._chase_a_token(cycle)
    assert cycle.tokens_chased == 0 and chase.calls == 1


def test_a_chase_that_raises_ends_the_chain_without_ending_the_trip():
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        if calls["n"] == 1:
            return SimpleNamespace(walked=True, studs=1.0,
                                   describe=lambda: "walked onto it")
        raise RuntimeError("bad frame")

    loop = _bare_loop(chase=boom)
    cycle = _bare_cycle()
    loop._chase_a_token(cycle)          # must not raise
    assert cycle.tokens_chased == 1


# --- leaving at the empty bag (gather.leave_at_empty_bag) -----------------------------

def _rising_honey():
    return [honey(0), honey(100_000), honey(200_000), honey(300_000), honey(300_000)]


def _bag():
    return [pollen(600_000), pollen(600_000), pollen(300_000), pollen(0)]


def _converts(clock, leave, n):
    """`n` converts in one loop, each from a fresh scripted HUD."""
    hud = FakeHud(clock, _bag(), honey_script=_rising_honey())
    loop, inp, _, _ = build(clock, hud, full_at=0.5, stall_after=1e9, leave_at_empty=leave)
    cycles = []
    for _ in range(n):
        hud.pollen_reads = hud.honey_reads = 0
        cycles.append(loop.run(cycles=1).cycles[0])
    return cycles, inp


def test_the_first_convert_waits_and_measures_then_the_next_leave_at_the_empty_bag(clock):
    cycles, _ = _converts(clock, lambda: True, farm.LEAVE_CALIBRATE_EVERY + 1)
    first, *rest = cycles
    assert first.converted and not first.left_at_empty
    assert "honey settled at 300,000" in first.convert_note
    assert first.honey_earned and first.honey_earned > 0      # measured
    for c in rest[:farm.LEAVE_CALIBRATE_EVERY - 1]:
        assert c.converted and c.left_at_empty
        assert "left without waiting for the honey counter" in c.convert_note
        # and its honey read once it landed (ROADMAP P19), not while rolling
        assert c.honey_earned == first.honey_earned
        assert "honey settled at 300,000" in c.convert_note
        assert "read after leaving it" in c.convert_note
    # the next calibration convert waits again
    assert not cycles[farm.LEAVE_CALIBRATE_EVERY].left_at_empty
    assert (cycles[farm.LEAVE_CALIBRATE_EVERY].honey_earned or 0) > 0


def _left(clock, after_convert=None, honey_script=None):
    """One convert past the loop's first (calibrating) one, left at the empty
    bag: honey 1,000,000 before E and 1,300,000 once it lands."""
    hud = FakeHud(clock, _bag(), honey_after_e=True,
                  honey_script=honey_script or [honey(1_000_000), honey(1_300_000)])
    loop, inp, routes, events = build(clock, hud, full_at=0.5, stall_after=1e9,
                                      leave_at_empty=lambda: True,
                                      after_convert=after_convert)
    loop._dwells = 1
    return loop, hud, routes, events


def test_a_left_converts_honey_is_read_before_the_errand_walks(clock):
    """ROADMAP P19: an errand that walks to a shop and spends is not in the
    trip's honey -- the landed balance is read at the errand's first step."""
    box = {}

    def errand(cycle):
        box["hud"].honey_script = [honey(1_300_000)]
        box["routes"].run("to_the_shop")
        box["hud"].honey_script = [honey(300_000)]        # bought something
    loop, hud, routes, _ = _left(clock, after_convert=errand)
    box.update(hud=hud, routes=routes)
    before = routes.on_step
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.left_at_empty and cycle.honey_earned == 300_000, cycle.honey_note
    assert "honey settled at 1,300,000 (+300,000)" in cycle.convert_note
    assert routes.on_step is before                       # the hook is put back
    assert loop._left_honey is None


def test_with_no_errand_the_left_honey_is_read_on_the_pad(clock):
    loop, hud, _, events = _left(clock)
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.left_at_empty and cycle.honey_earned == 300_000
    assert "+300,000 honey" in cycle.describe()
    assert any(isinstance(e, Metric) and e.name == "honey_earned" and e.value == 300_000
               for e in events)


def test_a_left_honey_that_never_reads_steady_is_not_claimed_and_does_not_hang(clock):
    loop, hud, _, _ = _left(clock)
    hud.honey_after_e = False                             # ever rising: never steady
    hud.honey_script = [honey(1_000_000 + 1_000 * i) for i in range(200)]
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.left_at_empty and cycle.honey_earned is None
    assert "never read steady after leaving" in cycle.honey_note
    assert "honey not measured (left at the empty bag)" in cycle.describe()
    assert hud.honey_reads < 30


class _ReplayHud:
    """The HUD of a REAL convert, replayed by the seconds since E: its
    'convert trail' line (s after E: bag / honey), the counters before E
    until the first entry, the last entry ever after."""

    def __init__(self, clock, before, trail):
        self.clock, self.before, self.trail = clock, before, trail
        self.e_at = None

    def _now(self):
        self.clock.advance(0.05)                  # a read takes a moment
        if self.e_at is None or self.clock() - self.e_at < self.trail[0][0]:
            return self.before
        return [entry for entry in self.trail if entry[0] <= self.clock() - self.e_at][-1]

    def pollen(self):
        return pollen(self._now()[1], capacity=10_000_000)

    def honey(self):
        return honey(self._now()[2])


def test_a_real_trail_left_at_the_empty_bag_measures_what_waiting_did(clock):
    """A convert trail shaped like one measured on the test account (the
    figures are made up): pressed E with 9,000,000 pollen and 1,000,000,000
    honey; that convert waited and banked +16,000,000. Replayed with the
    leave on, it leaves at the second empty read (8 s) and still books the
    same honey, read once it landed."""
    trail = [(2, 5_000_000, 1_004_000_000), (4, 800_000, 1_004_200_000),
             (6, 0, 1_007_000_000), (8, 0, 1_015_000_000),
             (10, 0, 1_016_000_000), (12, 0, 1_016_000_000)]
    hud = _ReplayHud(clock, (0, 9_000_000, 1_000_000_000), trail)
    inp = FakeInput()
    tap = inp.tap

    def stamped(key, ms=40):
        if key == "e" and hud.e_at is None:
            hud.e_at = clock()
        return tap(key, ms)
    inp.tap = stamped
    loop, _, _, _ = build(clock, hud, inp=inp, full_at=0.5, stall_after=1e9,
                          leave_at_empty=lambda: True)
    loop._dwells = 1
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.left_at_empty, cycle.convert_note
    assert "the backpack emptied 6s after the press" in cycle.convert_note
    assert cycle.honey_earned == 16_000_000, cycle.honey_note
    assert "honey settled at 1,016,000,000" in cycle.convert_note


def test_off_or_unreadable_every_convert_waits_for_the_honey_as_before(clock):
    def broken():
        raise RuntimeError("no settings")

    for leave in (None, lambda: False, broken):
        c = type(clock)()
        cycles, _ = _converts(c, leave, 3)
        for cycle in cycles:
            assert cycle.converted and not cycle.left_at_empty
            assert "honey settled at 300,000" in cycle.convert_note, cycle.convert_note


def test_the_leave_setting_is_read_at_every_convert_and_on_by_default():
    from hivemind.world import settings as st
    assert "gather.leave_at_empty_bag" in st.READ_AT_EVERY_USE
    assert st.defaults()["gather.leave_at_empty_bag"] is True


# --- the run's honey rate from the balance at each convert ----------------------------

def test_the_rate_is_the_balance_rise_between_the_first_and_last_convert():
    r = farm.Report(started_at=0.0, ended_at=3600.0)
    r.honey_marks = [(100.0, 10_000_000), (700.0, 14_800_000), (1300.0, 19_600_000)]
    # 9.6M over 1,200 s whatever the cycles measured
    assert r.honey_per_hour == pytest.approx(9_600_000 * 3.0)


def test_a_short_span_or_a_spend_falls_back_to_the_measured_cycles():
    r = farm.Report(started_at=0.0, ended_at=3600.0)
    r.cycles = [farm.Cycle(number=1, honey_earned=1_000_000)]
    r.honey_marks = [(100.0, 10_000_000), (300.0, 11_000_000)]          # 200 s apart
    assert r.honey_per_hour == pytest.approx(1_000_000.0)
    r.honey_marks = [(100.0, 10_000_000), (1300.0, 2_000_000)]          # honey spent
    assert r.honey_per_hour == pytest.approx(1_000_000.0)
    r.cycles, r.honey_marks = [], []
    assert r.honey_per_hour is None


def test_each_convert_marks_the_balance_at_its_press(clock):
    hud = FakeHud(clock, _bag(), honey_script=_rising_honey())
    loop, _, _, _ = build(clock, hud, full_at=0.5, stall_after=1e9)
    report = loop.run(cycles=1)
    cycle = report.cycles[0]
    assert len(report.honey_marks) == 1
    at, value = report.honey_marks[0]
    # stamped at the press, before the dwell ended, with the balance before
    # this convert's honey arrived
    assert cycle.started_at < at < cycle.started_at + cycle.seconds
    assert value + cycle.honey_earned == 300_000


def test_a_misread_mark_does_not_move_the_median_rate():
    marks = [(0.0, 100_000_000), (600.0, 104_800_000), (1200.0, 709_600_000),   # a 7 for a 1
             (1800.0, 114_400_000), (2400.0, 119_200_000)]
    assert farm._balance_rate(marks) == pytest.approx(4_800_000 * 6.0)


def test_a_convert_that_left_at_the_empty_bag_is_not_barren():
    c = farm.Cycle(number=1, left_at_empty=True)
    assert not c.measured_nothing
    assert farm.Cycle(number=2).measured_nothing


def test_one_empty_read_is_not_enough_to_leave(clock):
    """A false 0 between full reads (the dwell's own +0.6 s note) does not walk away."""
    # the gather takes two reads, the convert's start the third; then a false
    # 0, the bag still draining, and the two empty reads that end it
    # the honey still rolling throughout, as it does while the bag drains
    hud = FakeHud(clock, [pollen(600_000), pollen(600_000), pollen(600_000), pollen(0),
                          pollen(300_000), pollen(0), pollen(0)],
                  honey_script=[honey(100_000 * i) for i in range(30)])
    loop, _, _, _ = build(clock, hud, full_at=0.5, stall_after=1e9,
                          leave_at_empty=lambda: True)
    loop._dwells = 1                      # past the loop's first, calibrating convert
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.converted
    assert cycle.left_at_empty
    # it left only after the two empty reads at the end, not at the first 0
    assert hud.pollen_reads >= 7


def test_a_measuring_convert_whose_honey_never_read_leaves_and_hands_on(clock):
    """run-565 cycle 5 (22:52:20): the counter unreadable before the press and
    after it, the bag empty at 11 s -- and the dwell stood until 100 s, since
    the settle test had no start to compare with. It leaves at the empty bag
    now, and the next convert measures."""
    unread = Reading(Read.UNREADABLE, text="????,6?????,????0?", score=0.18)
    hud = FakeHud(clock, _bag(), honey_script=[unread] * 6 + [honey(300_000)] * 4)
    loop, _, _, _ = build(clock, hud, full_at=0.5, stall_after=1e9,
                          leave_at_empty=lambda: True)
    first = loop.run(cycles=1).cycles[0]
    assert first.converted and first.left_at_empty
    assert "the next one measures" in first.convert_note
    hud.pollen_reads = hud.honey_reads = 0
    hud.honey_script = _rising_honey()
    second = loop.run(cycles=1).cycles[0]
    assert second.converted and not second.left_at_empty, second.convert_note
    assert "honey settled at 300,000" in second.convert_note
