"""The token detour: bounded, closed-loop, and it always comes back.

See act/chase. The thing these tests exist to stop is a detour that walks off
and does not return -- the field patterns are loops of blind timed holds, so a
character left thirty studs from where the pattern expects it is a character
that will be inside a wall in ten minutes.
"""
from __future__ import annotations

import contextlib

import numpy as np
import pytest

from hivemind.act import chase
from hivemind.vision import tokens


class FakeInput:
    """Records every hold, and notices a key left down."""

    def __init__(self):
        self.legs: list[str] = []
        self.down: set[str] = set()
        self.released = 0

    @contextlib.contextmanager
    def held(self, *keys):
        self.legs.append("".join(keys))
        self.down.update(keys)
        try:
            yield
        finally:
            self.down.difference_update(keys)

    def release_all(self):
        self.down.clear()
        self.released += 1


def _frame():
    return np.zeros((1080, 1920, 3), np.uint8)


def _frames_from(sequence):
    """A frame source that also works once the sequence runs out."""
    box = list(sequence)

    def take():
        return box.pop(0) if box else _frame()
    return take


def _sighting(x, y, confidence=0.9):
    return tokens.Sighting(x=x, y=y, confidence=confidence)


@pytest.fixture
def patched(monkeypatch):
    """Drive the loop with a scripted list of what the detector 'sees'."""
    def install(script):
        calls = {"n": 0}

        def fake_detect(frame, limit=40):
            i = min(calls["n"], len(script) - 1)
            calls["n"] += 1
            return script[i]
        monkeypatch.setattr(tokens, "detect", fake_detect)
        return calls
    return install


# ---------------------------------------------------------------- refusals --
def test_no_frame_is_not_a_crash():
    out = chase.chase(lambda: None, vin=FakeInput())
    assert not out.walked and "no frame" in out.reason


def test_nothing_confident_enough_means_no_walk(patched):
    patched([[_sighting(400, 400, confidence=0.1)]])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()]), vin=vin)
    assert not out.walked
    assert vin.legs == []
    assert "confidence" in out.reason


def test_a_token_already_underfoot_is_not_chased(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 10, ay + 10)]])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()]), vin=vin)
    assert not out.walked and vin.legs == []


def test_switched_off_by_default_when_settings_are_unreadable():
    assert chase.wanted(None) == (False, 45.0)

    class Broken:
        def bool(self, key): raise RuntimeError("no file")
        def int(self, key): raise RuntimeError("no file")
    assert chase.wanted(Broken())[0] is False


# ------------------------------------------------------------- the walking --
def test_it_walks_towards_a_token_and_back(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    far = _sighting(ax + 400, ay - 400)
    patched([[far]] * 3 + [[]])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 8), vin=vin, sleep=lambda s: None)
    assert out.walked and out.steps >= 1
    # every outward leg has a mirrored leg after it
    outward = out.steps
    assert len(vin.legs) == outward * 2, vin.legs
    assert vin.legs[:outward] == [chase._reverse(k) for k in vin.legs[outward:][::-1]]


def test_the_return_undoes_each_leg_in_reverse(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 400, ay - 400)],
             [_sighting(ax - 400, ay - 400)],
             []])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 8), vin=vin, sleep=lambda s: None)
    out_legs = vin.legs[:out.steps]
    back_legs = vin.legs[out.steps:]
    assert back_legs == [chase._reverse(k) for k in reversed(out_legs)]


def test_a_token_that_vanishes_counts_as_collected(patched):
    """Within one step of arriving (ARRIVED_PIXELS + a step's travel)."""
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 150, ay - 150)], []])
    out = chase.chase(_frames_from([_frame()] * 6), vin=FakeInput(),
                      sleep=lambda s: None)
    assert out.arrived and out.walked


def test_it_aims_by_looking_again_not_by_dead_reckoning(patched):
    """The token drifts on screen between steps; the keys must follow it.

    CHANGED 2026-09-22. This used to jump the token from +500 to -500 px in
    one step and expect the walk to lunge after it. A token a thousand pixels
    from where it was a third of a second ago is not the same token moving --
    it is a different sighting -- and following it is the re-aim-at-nearest
    behaviour that walks past the token that matters
    (DESIGN 8y). The walk now keeps ITS target: it re-finds the sighting
    nearest the target's last position, so a realistic per-step drift is
    followed and a leap to the other side of the screen is not.
    """
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 500, ay)],      # to the right
             [_sighting(ax + 440, ay + 40)], # a step later: drifted, still right
             [_sighting(ax + 380, ay + 70)],
             []])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 8), vin=vin, sleep=lambda s: None)
    outward = vin.legs[:out.steps]
    assert out.steps >= 2, outward
    assert all("d" in leg for leg in outward), outward


def test_a_leap_across_the_screen_is_a_different_token_not_a_new_aim(patched):
    """The other half of the change above."""
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 500, ay)],
             [_sighting(ax - 500, ay)],      # nothing near where the target was
             []])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 6), vin=vin, sleep=lambda s: None)
    # one step, then STEPS_ON_PREDICTION toward where it should be
    assert out.steps == 1 + chase.STEPS_ON_PREDICTION, vin.legs
    assert out.steps_on_prediction == chase.STEPS_ON_PREDICTION
    # gone 500 px out after one step: lost, not collected (audit 2026-09-25)
    # -- and not re-aimed at the other token either
    assert not out.arrived and "lost sight" in out.reason
    assert not any("a" in leg for leg in vin.legs[:out.steps]), vin.legs


# ----------------------------------------------------------------- bounds --
def test_the_radius_setting_really_shortens_the_walk():
    assert chase.step_budget(10, 28) < chase.step_budget(45, 28)
    assert chase.step_budget(100000, 28) == chase.MAX_STEPS
    assert chase.step_budget(0, 28) >= 1


def test_it_never_walks_further_than_the_budget(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 900, ay - 900)]] * 50)
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 80), vin=vin,
                      sleep=lambda s: None, radius_studs=1e9)
    assert out.steps <= chase.MAX_STEPS
    assert len(vin.legs) <= chase.MAX_STEPS * 2


def test_a_stop_request_ends_it(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 900, ay - 900)]] * 20)
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 40), vin=vin,
                      sleep=lambda s: None, stopped=lambda: True)
    assert out.steps == 0


def test_no_key_is_left_held_even_when_it_throws(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 400, ay - 400)]] * 5)
    vin = FakeInput()

    def boom(_):
        raise RuntimeError("panic mid-walk")
    with pytest.raises(RuntimeError):
        chase.chase(_frames_from([_frame()] * 6), vin=vin, sleep=boom)
    assert vin.down == set()
    assert vin.released >= 1


def test_it_presses_only_movement_keys(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 400, ay - 400)]] * 4 + [[]])
    vin = FakeInput()
    chase.chase(_frames_from([_frame()] * 10), vin=vin, sleep=lambda s: None)
    assert set("".join(vin.legs)) <= set("wasd"), vin.legs


# ---------------------------------------------------------------- steering --
def test_keys_towards_reads_the_screen_the_right_way_up():
    """Higher up the screen is further away, so that is forward."""
    assert chase.keys_towards(0, -300) == "w"
    assert chase.keys_towards(0, 300) == "s"
    assert chase.keys_towards(300, 0) == "d"
    assert chase.keys_towards(-300, 0) == "a"
    assert set(chase.keys_towards(300, -300)) == set("wd")


def test_a_token_dead_ahead_does_not_also_strafe():
    assert chase.keys_towards(5, -300) == "w"


# --- how sure before a walk -------------------------------------------------
# The owner, 2026-09-22, watching a live run: it chased bees as if they
# were tokens. The detector looks for a white glyph on a flat cube face, and a
# Roblox bee IS one, so the gate is the lever -- and it is a setting, because
# the right value can only be found against the honey rate, not argued about.

def test_the_gate_is_a_parameter_and_the_default_is_stricter_than_the_detectors(patched):
    patched([[_sighting(400, 400, confidence=0.6)]])

    loose = chase.chase(_frames_from([_frame()]), vin=FakeInput(),
                        min_confidence=0.5)
    strict = chase.chase(_frames_from([_frame()]), vin=FakeInput(),
                         min_confidence=0.7)

    assert loose.walked or loose.reason == "", loose.reason
    assert not strict.walked
    assert "0.70" in strict.reason, "the reason must name the gate actually used"


def test_the_default_gate_is_above_the_detectors_own_cut():
    assert chase.DEFAULT_CHASE_CONFIDENCE > tokens.CHASE_CONFIDENCE


def test_the_setting_is_a_percent_and_is_clamped():
    class S:
        def __init__(self, v): self.v = v
        def int(self, key): return self.v

    assert chase.chase_confidence_from(S(70)) == pytest.approx(0.70)
    assert chase.chase_confidence_from(S(50)) == pytest.approx(0.50)
    assert chase.chase_confidence_from(S(5)) == pytest.approx(0.30), "clamped low"
    assert chase.chase_confidence_from(S(100)) == pytest.approx(0.95), "clamped high"
    assert chase.chase_confidence_from(S(0)) == pytest.approx(0.70), "0 means default"
    assert chase.chase_confidence_from(S("nonsense")) == pytest.approx(0.70)


# --- the brain chooses, the chase walks (DESIGN 8y) ----------------------------

def test_a_picker_chooses_the_target_instead_of_the_nearest(patched):
    near = _sighting(1000, 700, confidence=0.9)     # nearest to the character
    far = _sighting(1500, 400, confidence=0.9)
    patched([[near, far], [], []])
    chosen = []

    def pick(seen, w, h):
        chosen.append(len(seen))
        return next(s for s in seen if s.x == 1500)

    vin = FakeInput()
    out = chase.chase(_frames_from([_frame(), _frame(), _frame()]), vin=vin, pick=pick)

    assert chosen == [2], "the picker must see every sighting once"
    assert out.walked
    # the first leg heads toward (1500, 400): right and up, so 'w' and 'd'
    assert "d" in vin.legs[0] and "w" in vin.legs[0], vin.legs


def test_a_picker_that_chooses_nothing_means_no_walk(patched):
    patched([[_sighting(1000, 700, confidence=0.9)]])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()]), vin=vin, pick=lambda s, w, h: None)
    assert not out.walked
    assert vin.legs == []
    assert "brain chose none" in out.reason


def test_a_picker_that_chooses_nothing_gets_one_more_look(patched):
    """The detector flickers: a target missing from the first frame is looked
    for once more before the chase says none (MEASURED 2026-10-01, 13 of 86)."""
    target = _sighting(1500, 400, confidence=0.9)
    patched([[], [target], [], []])
    looks = []

    def pick(seen, w, h):
        looks.append(len(seen))
        return seen[0] if seen else None

    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 4), vin=vin, pick=pick)
    assert looks == [0, 1]
    assert out.walked
    assert "d" in vin.legs[0] and "w" in vin.legs[0], vin.legs


def test_none_on_both_looks_says_both(patched):
    patched([[_sighting(1000, 700, confidence=0.9)], [], []])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 3), vin=vin, pick=lambda s, w, h: None)
    assert not out.walked and vin.legs == []
    assert out.reason == "1 candidate(s), then 0 on a second look; the brain chose none"


def test_a_picker_that_raises_does_not_walk_on_a_guess(patched):
    patched([[_sighting(1000, 700, confidence=0.9)]])
    vin = FakeInput()

    def broken(seen, w, h):
        raise RuntimeError("no brain today")

    out = chase.chase(_frames_from([_frame()]), vin=vin, pick=broken)
    assert not out.walked
    assert "picker failed" in out.reason


def test_the_walk_keeps_its_target_when_another_token_drifts_nearer(patched):
    """Mid-chase re-acquisition used to take the sighting nearest the
    CHARACTER, so one step toward a token could hand the walk to a different
    token. Now it re-finds the sighting nearest the target's last position."""
    target = _sighting(1400, 400, confidence=0.9)
    # after one step: the target has drifted a little; a rival now sits right
    # by the character
    step1 = [_sighting(1360, 430, confidence=0.9), _sighting(980, 690, confidence=0.9)]
    patched([[target], step1, step1, step1, step1])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 6), vin=vin,
                      pick=lambda seen, w, h: seen[0])

    assert out.walked
    # every leg keeps heading right-and-up toward the original target, never
    # toward the rival beside the character
    assert all("d" in leg for leg in vin.legs[:len(vin.legs) // 2]), vin.legs


def test_a_target_that_vanishes_mid_walk_counts_as_collected(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 150, ay - 100, confidence=0.9)], []])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame(), _frame()]), vin=vin,
                      pick=lambda seen, w, h: seen[0])
    assert out.arrived


def test_a_target_lost_far_out_is_not_a_collection(patched):
    """MEASURED (audit 2026-09-25): 714 of 977 chases starting 270-359 px out
    ended "1 step(s), walked onto it", which one step cannot cover -- and
    each taught the school "reached it, nothing moved"."""
    patched([[_sighting(1400, 400, confidence=0.9)], []])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame(), _frame()]), vin=vin,
                      pick=lambda seen, w, h: seen[0])
    assert not out.arrived and "lost sight" in out.reason
    # the step's row says what it aimed at and that nothing was re-found
    assert out.trail and out.trail[0]["aim"] == [1400, 400] and out.trail[0]["found"] is None
    assert out.anchor is not None


# --- the detour comes home by looking (DESIGN 8z addendum) ---------------------

class FakeOdometer:
    """A `vision.flow.Odometer` stand-in: `dx`/`dy` are the SCENE's motion,
    `displacement()` the character's, and `update()` only sees motion while
    the fake input has a key down."""

    def __init__(self, broken=False, blind=False, px_per_update=20.0):
        self.dx = self.dy = 0.0
        self.travel = 0.0
        self.samples = 0
        self.broken = broken          # update() raises
        self.blind = blind            # the ground is featureless: nothing accepted
        self.px = px_per_update
        self.resets = 0
        self.updates = 0
        self.moving = ""              # keys currently held, set by the fake input

    def reset(self):
        self.resets += 1
        self.dx = self.dy = self.travel = 0.0
        self.samples = 0

    def update(self, frame):
        if self.broken:
            raise RuntimeError("odometer broke")
        self.updates += 1
        if self.blind or not self.moving:
            return None
        k = self.moving
        # the character walks right -> the ground slides LEFT (scene dx < 0)
        self.dx -= self.px * ((1 if "d" in k else 0) - (1 if "a" in k else 0))
        # forward carries the ground DOWN the screen (scene dy > 0)
        self.dy += self.px * ((1 if "w" in k else 0) - (1 if "s" in k else 0))
        self.travel += self.px
        self.samples += 1
        return object()

    def displacement(self):
        return None if self.samples == 0 else (-self.dx, -self.dy)


def _odometer_vin(odo):
    """A FakeInput that tells the odometer which keys are down."""
    vin = FakeInput()
    real_held = vin.held

    @contextlib.contextmanager
    def held(*keys):
        with real_held(*keys):
            odo.moving = "".join(keys)
            try:
                yield
            finally:
                odo.moving = ""
    vin.held = held
    return vin


def test_the_detour_comes_home_by_the_odometer_not_by_reversing_legs(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    # a token 480 px to the right; walk to it, then come home
    patched([[_sighting(ax + 480, ay)]] * 3 + [[]] * 200)
    odo = FakeOdometer()
    vin = _odometer_vin(odo)

    out = chase.chase(_frames_from([_frame()] * 400), vin=vin, odometer=odo,
                      pick=lambda seen, w, h: seen[0], sleep=lambda s: None)

    assert out.walked
    assert out.returned_by == "looking", out.returned_by
    assert odo.resets == 1, "the odometer is zeroed where the detour begins"
    disp = odo.displacement()
    assert abs(disp[0]) <= chase.ARRIVED_PIXELS and abs(disp[1]) <= chase.ARRIVED_PIXELS, disp
    # the legs after the outward ones must be corrections, not a mirror image
    outward = out.steps
    homeward = vin.legs[outward:]
    assert homeward, vin.legs
    assert all("a" in leg for leg in homeward), homeward


def test_the_ground_is_sampled_during_the_hold_not_around_it(patched):
    """The flow needs consecutive frames a few px apart: one frame before a
    step and one after would be a 90 px jump it cannot track."""
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 480, ay)]] * 3 + [[]] * 200)
    odo = FakeOdometer()
    vin = _odometer_vin(odo)

    out = chase.chase(_frames_from([_frame()] * 400), vin=vin, odometer=odo,
                      pick=lambda seen, w, h: seen[0], sleep=lambda s: None)

    per_hold = max(1, round(chase.STEP_SECONDS / chase.SAMPLE_SECONDS))
    assert per_hold >= 4, per_hold
    assert odo.samples >= per_hold * out.steps, (odo.samples, out.steps)


def test_with_no_odometer_reading_it_reverses_the_legs_and_says_so(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 480, ay)]] * 3 + [[]] * 10)
    odo = FakeOdometer(blind=True)
    vin = _odometer_vin(odo)

    out = chase.chase(_frames_from([_frame()] * 200), vin=vin, odometer=odo,
                      pick=lambda seen, w, h: seen[0], sleep=lambda s: None)

    assert out.walked
    assert out.returned_by == "reversing the legs"


def test_a_broken_odometer_falls_back_rather_than_ending_the_detour(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 480, ay)]] * 3 + [[]] * 10)
    odo = FakeOdometer(broken=True)
    vin = _odometer_vin(odo)

    out = chase.chase(_frames_from([_frame()] * 200), vin=vin, odometer=odo,
                      pick=lambda seen, w, h: seen[0], sleep=lambda s: None)

    assert out.walked
    assert out.returned_by == "reversing the legs"
    assert not vin.down, "no key left down"


def test_the_tracker_is_told_how_far_the_ground_moved(patched):
    """The token memory is carried with the ground, not un-matched by it."""
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 480, ay)]] * 3 + [[]] * 200)
    odo = FakeOdometer()
    vin = _odometer_vin(odo)
    shifts = []

    class Memory:
        def observe(self, seen, now, scene_shift=None):
            shifts.append(scene_shift)
            return []

    chase.chase(_frames_from([_frame()] * 400), vin=vin, odometer=odo, tracker=Memory(),
                pick=lambda seen, w, h: seen[0], sleep=lambda s: None)

    assert shifts and shifts[0] is None, "the first look has nothing to shift by"
    moved = [sh for sh in shifts[1:] if sh is not None]
    assert moved, shifts
    # walking right slides the ground left
    assert all(sh[0] < 0 for sh in moved[:1]), moved


def test_without_an_odometer_the_old_reversal_is_unchanged(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 480, ay)]] * 3 + [[]] * 10)
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 20), vin=vin,
                      pick=lambda seen, w, h: seen[0], sleep=lambda s: None)
    assert out.returned_by == "reversing the legs"


# --- what stays put while the ground moves is not in the world ------------------
def test_a_target_that_stays_put_while_the_ground_moves_is_the_characters_gear(patched):
    """MEASURED 2026-10-03: 128 of the school's last 400 lessons were one
    olive-yellow thing left of the character, bobbing too far for
    vision/pinned to pin it, chased and never reached."""
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax - 500, ay - 200)],          # chosen
             [_sighting(ax - 490, ay - 210)]])         # after a step: still there
    odo = FakeOdometer(px_per_update=40.0)
    vin = _odometer_vin(odo)
    vetoed = []
    out = chase.chase(_frames_from([_frame()] * 12), vin=vin, sleep=lambda s: None,
                      odometer=odo, on_attached=lambda x, y: vetoed.append((x, y)))
    assert out.attached == (ax - 500, ay - 200), out
    assert vetoed == [(ax - 500, ay - 200)]
    assert not out.arrived and "not in the world" in out.reason


def test_a_target_lost_without_ground_motion_is_not_called_gear(patched):
    """No odometer reading, no claim: a step that did not move proves nothing."""
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax - 500, ay - 200)], [_sighting(ax - 490, ay - 210)]])
    out = chase.chase(_frames_from([_frame()] * 12), vin=FakeInput(),
                      sleep=lambda s: None, on_attached=lambda x, y: None)
    assert out.attached is None


def test_a_vetoed_spot_is_skipped_within_its_radius():
    from hivemind.vision import pinned
    p = pinned.Pinned()
    assert not p.is_pinned(455, 455)
    p.veto(455, 455)
    assert p.is_pinned(455 + pinned.VETO_RADIUS, 455 - 20)
    assert not p.is_pinned(455 + pinned.VETO_RADIUS + 5, 455)


# --- a far token slides with the ground beside it, not the ground's median ----

class FarOdometer(FakeOdometer):
    """The median slides `px` an update, but the ground beside the followed
    spot only `share` of it -- a token far up the screen, under perspective."""

    def __init__(self, share=0.25, **kw):
        super().__init__(**kw)
        self.share = share
        self.point = None

    def follow(self, x, y):
        self.point = (float(x), float(y))

    def update(self, frame):
        before = (self.dx, self.dy)
        got = super().update(frame)
        if got is not None and self.point is not None:
            self.point = (self.point[0] + self.share * (self.dx - before[0]),
                          self.point[1] + self.share * (self.dy - before[1]))
        return got


def test_a_far_token_is_found_where_the_ground_beside_it_carried_it(patched):
    # MEASURED 2026-10-03 04:34: four loot chases after a Mantis lost tokens
    # 606-727 px out after one step -- looked for at the median's slide,
    # which a far token does not make (vision/flow.FOLLOW_NEAREST)
    ax, ay = chase.anchor_of(1920, 1080)
    far = (ax - 650, ay - 300)
    odo = FarOdometer()
    vin = _odometer_vin(odo)
    steps = round(chase.STEP_SECONDS / chase.SAMPLE_SECONDS)
    slid = (far[0] + 0.25 * odo.px * steps, far[1] + 0.25 * odo.px * steps)
    patched([[_sighting(*far)]] + [[_sighting(*slid)]] * 400)
    out = chase.chase(_frames_from([_frame()] * 400), vin=vin, odometer=odo,
                      sleep=lambda s: None, radius_studs=45.0)
    assert out.steps >= 2 and "lost sight" not in out.reason, out.reason
    assert out.attached is None, "a far token sliding little is no gear"
    assert out.looks and len(out.looks) <= chase.LOOKS_KEPT


def test_carried_moves_a_point_with_the_tracked_ground_nearest_it():
    from hivemind.vision import flow
    near = [[[x, 800.0], [x + 60.0, 800.0]] for x in range(400, 1600, 60)]   # 20 near points
    far = [[[x, 420.0], [x + 12.0, 420.0]] for x in range(400, 1000, 50)]    # 12 far points
    sample = flow.FlowSample(60.0, 0.0, 32, 0.0, True, np.array(near + far, np.float64))
    x, y = flow.carried((300.0, 400.0), sample)
    assert abs(x - 312.0) < 1e-6 and y == 400.0
    x, _ = flow.carried((900.0, 790.0), sample)
    assert abs(x - 960.0) < 1e-6
    bare = flow.FlowSample(5.0, -3.0, 0, 0.0, True, None)
    assert flow.carried((10.0, 10.0), bare) == (15.0, 7.0)


def test_a_far_token_is_re_found_part_way_to_where_the_ground_would_carry_it():
    # MEASURED 2026-10-03 11:16:39: the target 676 px out at (366, 346); after
    # one step the ground's carry put it hundreds of px on, and it was seen at
    # (443, 373) -- 81 px from where it was, in the ground's direction
    from types import SimpleNamespace as S

    from hivemind.act import chase
    target = S(x=366, y=346, confidence=1.0)
    carried = (366 + 250, 346 + 300)
    seen = [S(x=443, y=373, confidence=1.0), S(x=233, y=350, confidence=1.0)]
    far_y = 670 - chase.FAR_ABOVE_PX                    # the anchor at 1080 px
    found = chase._same_token(seen, target, 0.5, near=carried, far_y=far_y)
    assert found is not None and (found.x, found.y) == (443, 373)
    # what hangs within STUCK_PX of where it was after a long carry is the
    # gear's, and stays `_stuck`'s to say
    gear = [S(x=380, y=360, confidence=1.0)]
    assert chase._same_token(gear, target, 0.5, near=carried, far_y=far_y) is None
    assert chase._stuck(gear, target, 0.5, None, near=carried) is not None
    # and a sighting that moved against the ground's way is not the target
    back = [S(x=300, y=290, confidence=1.0)]
    assert chase._same_token(back, target, 0.5, near=carried, far_y=far_y) is None
    # THE GEAR'S OWN ROW IS NOT FAR: the 04:34:27 miss's "token" at (391, 461),
    # in the measured gear zone, re-seen 49 px on -- not taken for a far token
    low = S(x=391, y=461, confidence=1.0)
    assert chase._same_token([S(x=426, y=496, confidence=1.0)], low, 0.5,
                             near=(391 + 280, 461 + 100), far_y=far_y) is None


def test_a_near_token_is_re_found_past_where_the_ground_would_carry_it():
    # MEASURED 2026-10-07, var/loot_misses/20261004-011933: the honey target at
    # (432, 432), carried to (575, 554), was in the next look at (660, 660),
    # confidence 1.0 -- 1.7x as far along the line, 136 px from the prediction
    from types import SimpleNamespace as S

    from hivemind.act import chase
    far_y = 670 - chase.FAR_ABOVE_PX
    target = S(x=432, y=432, confidence=1.0)
    found = chase._same_token([S(x=660, y=660, confidence=1.0)], target, 0.5,
                              near=(575, 554), far_y=far_y)
    assert found is not None and (found.x, found.y) == (660, 660)
    # 20261003-222952: the helmet, 137 px off the line, is not the target
    target = S(x=590, y=428, confidence=1.0)
    assert chase._same_token([S(x=812, y=475, confidence=0.63)], target, 0.5,
                             near=(704, 559), far_y=far_y) is None


def test_two_start_looks_that_miss_walk_on_the_deciding_look_when_given_it(patched):
    """A coin edge-on in both start looks is still there: the brain's own
    look, a moment old, is the target (MEASURED 2026-10-07, 33 of 107)."""
    patched([[], [], []])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 4), vin=vin, pick=lambda s, w, h: None,
                      fallback=_sighting(1500, 400))
    assert out.walked and "d" in vin.legs[0] and "w" in vin.legs[0], vin.legs


def test_a_target_missed_after_a_step_is_walked_on_and_found_again(patched):
    """MEASURED 2026-10-07 (run-737): 9 of 30 chases lost sight after their
    first step, a step or two short; one step on the prediction, then the
    looks again (STEPS_ON_PREDICTION)."""
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 500, ay)],
             [], [],                              # both looks after step 1 miss it
             [_sighting(ax + 480, ay)],           # there again after the step on
             []])
    vin = FakeInput()
    out = chase.chase(_frames_from([_frame()] * 8), vin=vin, sleep=lambda s: None)
    assert out.trail[0]["found"] is None                    # lost after step 1
    assert out.trail[1]["found"] == [ax + 480, ay]          # found after the step on
    assert all("d" in leg for leg in vin.legs[:out.steps]), vin.legs


def test_a_walk_home_aims_past_its_start_by_what_earlier_ones_left(patched):
    """act/chase CARRY: the leftovers of earlier walks home are carried, so the
    gather does not drift by one leftover a chase (MEASURED 2026-10-08)."""
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 480, ay)]] * 3 + [[]] * 200)
    odo = FakeOdometer()
    vin = _odometer_vin(odo)
    carry = [150.0, 0.0]     # earlier chases left the character 150 px right of the gather

    out = chase.chase(_frames_from([_frame()] * 400), vin=vin, odometer=odo,
                      pick=lambda seen, w, h: seen[0], sleep=lambda s: None,
                      carry=carry)

    assert out.returned_by == "looking", out.returned_by
    x, y = odo.displacement()
    assert x < 0, "it walked back past this detour's start"
    assert abs(x + 150) <= chase.ARRIVED_PIXELS and abs(y) <= chase.ARRIVED_PIXELS
    assert carry == [x + 150, y], carry      # the new leftover, against the gather


def test_no_carry_is_the_old_walk_home(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 480, ay)]] * 3 + [[]] * 200)
    odo = FakeOdometer()
    out = chase.chase(_frames_from([_frame()] * 400), vin=_odometer_vin(odo), odometer=odo,
                      pick=lambda seen, w, h: seen[0], sleep=lambda s: None, carry=None)
    x, y = odo.displacement()
    assert out.returned_by == "looking" and abs(x) <= chase.ARRIVED_PIXELS


def test_no_step_on_a_prediction_when_told_none(patched):
    """run_farm LEDGE_FIELDS: a token lost after a step is not walked after."""
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 600, ay)]] * 2 + [[]] * 200)
    odo = FakeOdometer()
    out = chase.chase(_frames_from([_frame()] * 400), vin=_odometer_vin(odo), odometer=odo,
                      pick=lambda seen, w, h: seen[0], sleep=lambda s: None,
                      predict_steps=0)
    assert out.steps_on_prediction == 0, out
    assert "lost sight" in out.reason, out.reason


# ------------------------------------------------- the look after arriving --
def test_a_token_gone_after_arriving_is_seen_gone(patched):
    """act/chase SIGHT_CHECK: one look SIGHT_SETTLE_S after arriving, for the
    school; nothing in view where the walk stopped is "gone"."""
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 150, ay - 150)], []])
    slept = []
    out = chase.chase(_frames_from([_frame()] * 6), vin=FakeInput(),
                      sleep=slept.append)
    assert out.arrived
    assert out.sight["verdict"] == "gone", out.sight
    assert chase.SIGHT_SETTLE_S in slept


def test_a_token_still_there_after_arriving_is_seen_still_there(patched):
    ax, ay = chase.anchor_of(1920, 1080)
    patched([[_sighting(ax + 150, ay)], [_sighting(ax + 100, ay)], [_sighting(ax + 100, ay)]])
    out = chase.chase(_frames_from([_frame()] * 6), vin=FakeInput(), sleep=lambda s: None)
    assert out.arrived
    assert out.sight["verdict"] == "still there" and out.sight["underfoot"], out.sight


def test_the_look_after_arriving_presses_nothing(patched, monkeypatch):
    ax, ay = chase.anchor_of(1920, 1080)
    legs = {}
    for on in (True, False):
        monkeypatch.setattr(chase, "SIGHT_CHECK", on)
        patched([[_sighting(ax + 150, ay - 150)], []])
        vin = FakeInput()
        out = chase.chase(_frames_from([_frame()] * 6), vin=vin, sleep=lambda s: None)
        legs[on] = list(vin.legs)
        assert (out.sight is not None) is on
    assert legs[True] == legs[False]


def test_no_look_after_a_chase_that_did_not_arrive(patched):
    patched([[_sighting(1400, 400, confidence=0.9)], []])
    out = chase.chase(_frames_from([_frame(), _frame()]), vin=FakeInput(),
                      sleep=lambda s: None, predict_steps=0)
    assert not out.arrived and out.sight is None


def test_chain_target_is_the_nearest_confirmed_token_just_seen_within_chain_px():
    from hivemind.vision.tracks import Track

    def t(i, dx, matches=2, last=10.0):
        return Track(id=i, x=960 + dx, y=669, matches=matches, first_seen=0.0, last_seen=last)

    class Mem:
        def __init__(self, ts): self.ts = ts
        def confirmed(self, now): return [x for x in self.ts if x.confirmed]

    clock = lambda: 10.0
    pick = lambda ts: chase._chain_target(Mem(ts), 960, 669, clock)
    assert pick([t(1, 50), t(2, 240), t(3, 180)]).id == 3      # the one under us is skipped
    assert pick([t(1, 300)]) is None                           # past CHAIN_PX
    assert pick([t(1, 180, matches=1)]) is None                # seen once
    assert pick([t(1, 180, last=8.0)]) is None                 # not in the latest look
    assert chase._chain_target(None, 960, 669, clock) is None


def test_a_pickup_with_a_token_close_by_says_it_would_chain_and_presses_the_same(patched):
    # reviewer 2026-10-21: the call site in chase() had no test; CHAIN_LIVE is
    # not built, so the note is all that may change
    from hivemind.vision.tracks import Track
    ax, ay = chase.anchor_of(1920, 1080)

    class Mem:
        def observe(self, *a, **k): pass
        def confirmed(self, now):
            return [Track(id=7, x=ax + 180, y=ay, kind="honey", matches=2,
                          first_seen=0.0, last_seen=now)]

    legs, notes = {}, {}
    for name, tracker in (("chain", Mem()), ("none", None)):
        patched([[_sighting(ax + 150, ay - 150)], []])
        vin, said = FakeInput(), []
        out = chase.chase(_frames_from([_frame()] * 6), vin=vin, sleep=lambda s: None,
                          tracker=tracker, on_note=said.append, clock=lambda: 10.0)
        assert out.arrived
        legs[name], notes[name] = list(vin.legs), said
    assert any(m.startswith("chase would: chain to honey#7 180 px on") for m in notes["chain"])
    assert not any("chain to" in m for m in notes["none"])
    assert legs["chain"] == legs["none"]
