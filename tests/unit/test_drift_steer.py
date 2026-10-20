"""ROADMAP A21: a gather that drifted off its field with no flowers in view.

Live 2026-10-15 04:33-04:44 (run-1013): Blue Flower walked onto the red
cannon's platform, the bed steer had nothing to aim at, and the pollen sat
flat for 11 min under a jump every ~110 s. Two fixes, both tested here on
synthetic inputs: walk back the ground's measured drift since the last good
bed (act/drift `steer_by_drift`), and end the gather when it stays off the
flowers and flat (brain/farm `stuck_off_the_flowers`, STUCK_FLAT_S).
"""
from types import SimpleNamespace

from hivemind.act import drift, motion
from hivemind.brain import farm
from hivemind.brain.farm import FLAT_COUNTER, Rung, stuck_off_the_flowers
from tests.unit.test_farm import FakeHud, FakeInput, build, clock, pollen, honey  # noqa: F401

BACK_AT = 0.105


def bed(share):
    return SimpleNamespace(share=share, informative=True, towards=(0.0, 0.0))


class Odometer:
    """Each hold moves the ground by `px` (scene px, x right, y down) for
    whichever keys were held, the way walking does: `w` slides the ground
    down, `a` slides it right."""

    def __init__(self, inp, px=300.0, measured=True):
        self.inp, self.px, self.measured = inp, px, measured
        self.samples, self.dx, self.dy, self.travel = 0, 0.0, 0.0, 0.0

    def update(self, frame):
        if not self.measured:
            return
        held = self.inp.held_keys
        step = self.px / max(1, round(drift.STEP_SECONDS / motion.SAMPLE_SECONDS))
        self.dy += step * (("w" in held) - ("s" in held))
        self.dx += step * (("a" in held) - ("d" in held))
        self.samples += 1
        self.travel += step


def walk(share, owed, measured=True, max_steps=drift.DRIFT_STEPS):
    """A walk where the bed reads `share` at every look."""
    inp = FakeInput()
    out = drift.steer_by_drift(lambda: "frame", lambda _f: bed(share), vin=inp,
                               owed=owed, back_at=BACK_AT,
                               odometer=Odometer(inp, measured=measured),
                               sleep=lambda _s: None, max_steps=max_steps)
    return out, inp


def test_the_steer_walks_back_against_the_recorded_drift_and_stops_in_the_bed():
    """The ground moved (-1322, +1031) px: left and down, so the character
    went right and forward. Back is left and backward: `s` and `a`."""
    inp = FakeInput()
    odo = Odometer(inp)
    shares = iter([0.0, 0.0, 0.0, 0.3])
    current = {"s": next(shares)}
    steps = {"n": 0}

    def bed_of(_frame):
        return bed(current["s"])

    def sleep(_s):
        pass

    def frames():
        return "frame"

    real_hold = drift.motion.hold_measuring

    def hold(vin, keys, seconds, sleep_, frames_, odometer):
        got = real_hold(vin, keys, seconds, sleep_, frames_, odometer)
        steps["n"] += 1
        current["s"] = next(shares, current["s"])
        return got

    drift.motion.hold_measuring, keep = hold, drift.motion.hold_measuring
    try:
        out = drift.steer_by_drift(frames, bed_of, vin=inp, owed=(-1322, +1031),
                                   back_at=BACK_AT, odometer=odo, sleep=sleep)
    finally:
        drift.motion.hold_measuring = keep
    assert out.keys[0] == "sa", out.keys
    assert out.back and out.steps == 3, out.describe()
    # each step paid 300 px of the debt on each axis it walked
    assert out.owed_after == (-1322 + 900, 1031 - 900)
    assert "steered back along the drift" in out.describe()
    assert not inp.held_keys


def test_the_steer_ends_when_the_drift_is_paid_and_no_bed_came_back():
    out, inp = walk(0.0, owed=(0.0, 600.0))
    assert out.steps == 2 and not out.back, out.describe()
    assert "walked back and still no flower bed" in out.reason
    assert not inp.held_keys


def test_the_steer_is_bounded():
    out, _ = walk(0.0, owed=(0.0, 1e6), max_steps=4)
    assert out.steps == 4 and not out.back
    assert "walked the 4 steps" in out.reason


def test_unmeasured_steps_end_it_rather_than_walking_on_a_guess():
    out, _ = walk(0.0, owed=(0.0, 1e6), measured=False)
    assert out.steps == drift.DRIFT_BLIND_STEPS and not out.back
    assert "could not measure" in out.reason


def test_a_bed_already_back_walks_nothing():
    out, inp = walk(0.4, owed=(500.0, 500.0))
    assert out.steps == 0 and out.back
    assert not [e for e in inp.events if e[0] == "press"]


def test_good_bed_needs_an_informative_look_at_back_at():
    look = lambda s, inf=True: SimpleNamespace(informative=inf, bed=bed(s))  # noqa: E731
    assert drift.good_bed([look(0.0), look(0.2)], BACK_AT)
    assert not drift.good_bed([look(0.05), look(0.5, inf=False)], BACK_AT)


# --- the stuck rule ---------------------------------------------------------

def test_the_stuck_rule_jumps_once_then_goes_home():
    assert stuck_off_the_flowers(True, 10.0, jumped=False) is None
    assert stuck_off_the_flowers(True, farm.STUCK_JUMP_S, jumped=False) is Rung.JUMP
    assert stuck_off_the_flowers(True, farm.STUCK_JUMP_S + 5, jumped=True) is None
    assert stuck_off_the_flowers(True, farm.STUCK_FLAT_S, jumped=True) is Rung.GO_HOME


def test_the_stuck_rule_never_fires_on_the_flowers():
    assert stuck_off_the_flowers(False, 10_000.0, jumped=False) is None


def test_a_gather_off_the_flowers_and_flat_goes_home_before_the_ladder(clock):
    hud = FakeHud(clock, [pollen(120_000)], honey_script=[honey(3), honey(3)])
    off = drift.Steer(reason="no flowers in view to walk towards")
    loop, inp, _, events = build(clock, hud, stay_in_field=lambda: off)
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.recoveries == ["jump", "go_home"], cycle.recoveries
    assert cycle.gather_ended.startswith(FLAT_COUNTER), cycle.gather_ended
    assert "STUCK_FLAT_S" in cycle.gather_ended
    assert cycle.gather_seconds < farm.STALL_SECONDS
    assert not inp.held_keys


def test_a_flat_gather_on_the_flowers_keeps_the_ladder(clock):
    hud = FakeHud(clock, [pollen(120_000)], honey_script=[honey(3), honey(3)])
    on = drift.Steer(back=True)
    loop, _, _, _ = build(clock, hud, stall_after=10.0, stay_in_field=lambda: on)
    cycle = loop.run(cycles=1).cycles[0]
    assert cycle.recoveries == ["jump", "turn", "go_home"], cycle.recoveries
    assert "STUCK_FLAT_S" not in cycle.gather_ended


def test_rising_pollen_off_the_bed_reading_is_not_stuck(clock):
    script = [pollen(10_000 * i) for i in range(1, 80)]     # to a full bag
    hud = FakeHud(clock, script, honey_script=[honey(3), honey(3)])
    off = drift.Steer(reason="no flowers in view to walk towards")
    loop, _, _, _ = build(clock, hud, stay_in_field=lambda: off)
    cycle = loop.run(cycles=1).cycles[0]
    assert "go_home" not in cycle.recoveries, cycle.recoveries
    assert "STUCK_FLAT_S" not in (cycle.gather_ended or "")
