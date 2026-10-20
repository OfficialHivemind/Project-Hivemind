"""Claiming a hive after joining, without ever claiming one we cannot see.

The owner's correction is the premise: you do not own a hive until you claim an
empty one, so there is no fixed slot to walk to and the slot number every
recorded route depends on is an OUTPUT of this module, not an input.

That makes the negative tests the important ones. Pressing the interact key at
a hive that is not empty does nothing in game, so a wrong press is cheap -- but
a wrong ANSWER is not, because the slot number it returns is what every route
out of the hive is measured from. The detector for the hive prompt does not
exist yet (no captured frame contains one; a real run of
`scripts/learn_hive_prompt.py` saw no prompt at any of the six positions), so
these tests pin down that the module refuses and explains rather than pressing
the key hopefully, and that a claim is only ever reported after the prompt was
seen to change.
"""
import pathlib

import numpy as np
import pytest

from hivemind.act import routes
from hivemind.act.hive import (CLAIM_KEY, SLOT_COUNT, TOP_SLOT, ClaimResult,
                               HiveClaimer, SlotState, claim_hive,
                               hive_bearing, prompt_unavailable,
                               sweep_and_claim, template_reader)
from hivemind.act.routes import RouteResult


class FakeInput:
    """Records keys, and notices any that are left down.

    Same shape as `tests/unit/test_routes.py`'s double, because the safety
    property being checked is the same one: no key may outlive the block that
    pressed it.
    """

    def __init__(self):
        self.events: list[tuple[str, object]] = []
        self.held_keys: set[str] = set()
        self.released_all = 0

    def press(self, *keys):
        for k in keys:
            self.held_keys.add(k)
            self.events.append(("press", k))

    def release(self, *keys):
        for k in keys:
            self.held_keys.discard(k)
            self.events.append(("release", k))

    def release_all(self):
        self.released_all += 1
        self.held_keys.clear()
        self.events.append(("release_all", None))

    def tap(self, key, ms=40):
        # a tap really does put the key down, so a crash mid-tap would strand
        # it -- model that rather than recording a bare event
        self.press(key)
        self.release(key)
        self.events.append(("tap", key))


class HiveInput(FakeInput):
    """A keyboard wired into a fake hive row: keys actually do something.

    Two jumps carry the character one slot sideways (BeeTuxMacro's hop), and
    the claim key claims the slot it is standing at -- but only when that slot
    is empty, which is the game's behaviour and the reason a blind press is
    cheap while a blind CLAIM is not.
    """

    def __init__(self, world):
        super().__init__()
        self.world = world
        self.jumps = 0
        self.claim_key = CLAIM_KEY

    def tap(self, key, ms=40):
        super().tap(key, ms)
        if key == "space":
            self.jumps += 1
            if self.jumps % 2 == 0:
                self.world.position = min(self.world.position + 1,
                                          len(self.world.states) - 1)
        elif key == self.claim_key:
            self.world.claim()


class FakeHive:
    """A row of six slots, and a character standing at one of them.

    `states` is indexed by hop count, matching the game's own addressing:
    `slot = 5 - hops` from the left corner. `claim_works=False` is the hive
    that looked empty and was not -- the case where the claim key does nothing
    and the prompt never changes.
    """

    def __init__(self, states, claim_works=True):
        self.states = [SlotState(s) for s in states]
        self.claim_works = claim_works
        self.position = 0
        self.vin = HiveInput(self)
        self.reads = 0

    def claim(self) -> None:
        if self.claim_works and self.states[self.position] is SlotState.EMPTY:
            self.states[self.position] = SlotState.MINE

    def frames(self):
        return np.zeros((8, 8, 4), np.uint8)

    def detector(self):
        """A screen test that can actually read this fake world."""
        def read(_frame):
            self.reads += 1
            return self.states[self.position]
        read.detector_built = True
        return read


def run(world, **kwargs):
    # zero waits: the real ones are for the game, not for the logic
    kwargs.setdefault("read_prompt", world.detector())
    return claim_hive(world.vin, world.frames, hop_rise=0.0, hop_settle=0.0,
                      confirm_interval=0.0, **kwargs)


def taps(inp) -> list[str]:
    return [key for action, key in inp.events if action == "tap"]


# ---- the key that gets pressed ---------------------------------------------

def test_the_claim_key_is_the_one_the_macro_presses_at_a_hive():
    """The only constant in this module that presses something.

    An earlier version used "c", reading the register's probe NAMES
    ("claim-hive C", "make-honey H") as key bindings. They are the letters
    those white pixels sit on. Every place BeeTuxMacro actually acts at a hive
    it presses `e`: find_hive claims with `e` the moment either probe reads
    white (stuff/utils.sh:140-141), `e()` is `wtype -P E -p E`
    (stuff/utils.sh:578-580), and convert() presses `e` at the owned hive
    before sleeping CONVERT_TIME (stuff/utils.sh:28,39). `RouteRunner`'s
    transpiled `interact` op is the same key, and this test pins the two
    together so they cannot drift apart silently."""
    assert CLAIM_KEY == "e"

    src = pathlib.Path(routes.__file__).read_text()
    # the press goes through `_held_back` (the owner's Pause or Take Over
    # can hold a key back), but the key is still "e"
    assert 'elif op == "interact":\n            self._held_back(self.vin.tap("e")' in src


def test_the_claim_key_can_be_overridden_without_editing_the_module():
    """It is cited, not measured: the prompt's own bracketed letter has never
    been read off a real frame. Whoever captures the prompt must be able to
    correct the key from the call site, and the override has to be the key that
    is really sent -- a parameter that is stored and ignored is worse than none
    at all."""
    world = FakeHive(["empty"] + ["taken"] * 5)
    world.vin.claim_key = "k"          # the fake hive answers to this instead
    result = run(world, claim_key="k")
    assert result.ok and result.newly_claimed
    assert taps(world.vin).count("k") == 1
    assert CLAIM_KEY not in taps(world.vin)


def test_the_claim_key_cannot_be_overridden_into_return_or_escape():
    """Making the key overridable must not become a back door to the two keys
    this project refuses to press blind: Escape opens the in-game menu that
    carries **Leave**, and Return activates whatever that menu has selected.
    The respawn confirmation is a different screen and only
    `RouteRunner._reset`, behind `reset_dialog_present`, may press Return."""
    for key in ("enter", "Return", " escape "):
        with pytest.raises(ValueError, match="not a key this module will press"):
            HiveClaimer(FakeInput(), lambda: None, claim_key=key)


# ---- the addressing the rest of the code already uses ----------------------

def test_the_row_is_six_slots_addressed_as_five_minus_hops():
    """`RouteRunner._hop_to_slot` hops `from_slot - hive_slot` times from slot
    5, and scripts/diag_hive_slot.py photographs six positions. A claimer that
    numbered them differently would hand back a slot that sends every recorded
    route to the wrong place."""
    assert (SLOT_COUNT, TOP_SLOT) == (6, 5)
    world = FakeHive(["taken"] * 6)
    result = run(world)
    assert [r.slot for r in result.readings] == [5, 4, 3, 2, 1, 0]
    assert [r.hops for r in result.readings] == [0, 1, 2, 3, 4, 5]


# ---- the happy path --------------------------------------------------------

def test_an_empty_slot_is_found_and_claimed():
    world = FakeHive(["taken", "taken", "empty", "taken", "taken", "taken"])
    result = run(world)
    assert result.ok
    assert (result.slot, result.hops) == (3, 2)
    assert result.newly_claimed
    assert taps(world.vin).count(CLAIM_KEY) == 1


def test_a_claim_is_only_reported_after_the_prompt_changes():
    """The whole point: `confirmed_by` must name what was seen, not what was
    pressed."""
    world = FakeHive(["empty"] + ["taken"] * 5)
    result = run(world)
    assert result.ok and "Make Honey" in result.confirmed_by


def test_it_hops_twice_per_slot_and_stops_at_the_empty_one():
    """Two jumps per hop is BeeTuxMacro's sequence; hopping past the claim
    would leave the character standing at the wrong hive."""
    world = FakeHive(["taken", "empty", "taken", "taken", "taken", "taken"])
    run(world)
    assert taps(world.vin).count("space") == 2, "did not hop exactly once"


def test_a_hive_that_is_already_ours_ends_the_search_without_claiming():
    """Rejoining a server we already have a hive in. There is nothing to
    claim, and the claim key is not one to press speculatively at our own hive
    -- at an owned hive that same key starts a ~100 s honey conversion."""
    world = FakeHive(["mine"] + ["empty"] * 5)
    result = run(world)
    assert result.ok and result.slot == 5
    assert not result.newly_claimed
    assert CLAIM_KEY not in taps(world.vin)
    assert taps(world.vin) == [], "moved when it was already standing at ours"


def test_it_never_hops_past_the_last_slot():
    world = FakeHive(["taken"] * 6)
    run(world)
    assert taps(world.vin).count("space") == 2 * (SLOT_COUNT - 1)


# ---- refusing, which is most of the value ----------------------------------

def test_the_default_detector_refuses_and_never_presses_anything():
    """There is no captured template for either prompt, so the shipped default
    cannot tell an empty hive from someone else's. It must refuse BEFORE
    moving: a blind sweep that ends in a claim press reports a slot number
    nothing verified."""
    inp = FakeInput()
    result = claim_hive(inp, lambda: np.zeros((8, 8, 4), np.uint8))
    assert not result.ok
    assert taps(inp) == [], "moved or pressed a key with no way to look"
    assert "never been captured" in result.reason
    assert "learn_hive_prompt" in result.reason, "did not say how to fix it"


def test_the_default_detector_reports_unknown_not_a_guess():
    assert prompt_unavailable(np.zeros((8, 8, 4), np.uint8)) is SlotState.UNKNOWN
    assert prompt_unavailable.detector_built is False


def test_a_detector_that_cannot_read_the_screen_does_not_claim():
    """A real detector can still fail to read -- a dark frame, a dialog over
    the prompt. Unreadable must not decay into 'empty'."""
    world = FakeHive(["unknown"] * 6)
    result = run(world)
    assert not result.ok
    assert CLAIM_KEY not in taps(world.vin)
    assert "could not be read" in result.reason


def test_unreadable_slots_are_not_reported_as_a_full_row():
    """'every hive is taken' and 'I could not see four of them' lead to
    different decisions: the first says change servers, the second says fix the
    camera. Collapsing them hides a fixable fault."""
    world = FakeHive(["taken", "unknown", "unknown", "taken", "taken", "taken"])
    result = run(world)
    assert not result.ok
    assert "could not be read" in result.reason
    assert "slots 4, 3" in result.reason


def test_a_genuinely_full_row_says_so():
    world = FakeHive(["taken"] * 6)
    result = run(world)
    assert not result.ok
    assert "no free hive" in result.reason
    assert len(result.readings) == SLOT_COUNT


def test_a_claim_the_screen_never_confirms_is_not_reported_as_success():
    """The dangerous case. The detector said empty, the key was pressed, and the
    prompt never changed -- so the hive was not ours after all, or the read was
    wrong. Either way the slot number would be fiction."""
    world = FakeHive(["empty"] + ["taken"] * 5, claim_works=False)
    result = run(world, confirm_polls=3)
    assert not result.ok
    assert result.slot is None
    assert "never became Make Honey" in result.reason
    assert "last read: empty" in result.reason


def test_an_unrecognised_detector_answer_reads_as_unknown():
    """A detector returning something this module does not know must never
    fall through to the one state that presses a key."""
    def confused(_frame):
        return "probably empty?"
    confused.detector_built = True

    world = FakeHive(["empty"] * 6)
    result = run(world, read_prompt=confused)
    assert not result.ok
    assert CLAIM_KEY not in taps(world.vin)
    assert "could not be read" in result.reason


def test_a_missing_frame_reads_as_unknown_rather_than_empty():
    inp = FakeInput()
    detector = FakeHive(["empty"] * 6).detector()
    result = claim_hive(inp, lambda: None, read_prompt=detector,
                        hop_rise=0.0, hop_settle=0.0, confirm_interval=0.0)
    assert not result.ok and CLAIM_KEY not in taps(inp)


# ---- keys -------------------------------------------------------------------

def test_only_space_and_the_claim_key_are_ever_sent():
    """Return in particular: the in-game menu carries Leave, and nothing in a
    hive sweep has any business pressing it."""
    world = FakeHive(["taken", "taken", "empty", "taken", "taken", "taken"])
    run(world)
    assert set(taps(world.vin)) <= {"space", CLAIM_KEY}
    assert "enter" not in taps(world.vin)


def test_no_key_is_left_held_by_a_sweep():
    world = FakeHive(["taken"] * 6)
    run(world)
    assert world.vin.held_keys == set()


def test_a_detector_that_raises_still_releases_every_key():
    """A capture failure mid-hop must not leave the character jumping into the
    honeycomb until someone notices."""
    def exploding(_frame):
        raise RuntimeError("capture died")
    exploding.detector_built = True

    world = FakeHive(["taken"] * 6)
    with pytest.raises(RuntimeError):
        run(world, read_prompt=exploding)
    assert world.vin.held_keys == set()
    assert world.vin.released_all >= 1


def test_a_finished_sweep_ends_with_everything_released():
    world = FakeHive(["empty"] * 6)
    run(world)
    assert world.vin.released_all >= 1


# ---- the approach ----------------------------------------------------------

def test_the_approach_runs_before_anything_is_read():
    world = FakeHive(["empty"] * 6)
    order = []
    run(world, approach=lambda: order.append("approach") or None,
        on_reading=lambda r: order.append("read"))
    assert order[0] == "approach"


def test_a_failed_approach_refuses_the_sweep():
    """Reading six slots from an unknown position would claim the wrong one."""
    world = FakeHive(["empty"] * 6)
    result = run(world, approach=lambda: False)
    assert not result.ok
    assert CLAIM_KEY not in taps(world.vin)
    assert "walk to the first hive slot failed" in result.reason


def test_an_approach_that_reports_failure_by_result_refuses_the_sweep():
    """The obvious thing to pass as `approach` is `RouteRunner.run(...)`, and a
    `RouteResult` is truthy whether or not the route ran -- `ok=False` with a
    reason is how it reports a walk that stopped early. Testing only `is False`
    let a failed approach through, and the sweep then read six slots from
    wherever the character actually was."""
    world = FakeHive(["empty"] * 6)
    result = run(world, approach=lambda: RouteResult("to_corner", ok=False,
                                                     reason="no route"))
    assert not result.ok
    assert CLAIM_KEY not in taps(world.vin)
    assert taps(world.vin) == [], "swept the row after the walk failed"
    assert "walk to the first hive slot failed" in result.reason


def test_an_approach_reporting_success_by_result_runs_the_sweep():
    """The other half: a route that ran must not read as a failure."""
    world = FakeHive(["empty"] * 6)
    assert run(world, approach=lambda: RouteResult("to_corner")).ok


def test_an_approach_returning_none_is_not_treated_as_failure():
    world = FakeHive(["empty"] * 6)
    assert run(world, approach=lambda: None).ok


# ---- reporting -------------------------------------------------------------

def test_every_slot_inspected_is_reported():
    world = FakeHive(["taken", "taken", "empty", "taken", "taken", "taken"])
    result = run(world)
    assert [r.state for r in result.readings] == [
        SlotState.TAKEN, SlotState.TAKEN, SlotState.EMPTY]
    assert result.readings[0].describe() == "slot 5 (after 0 hops): taken"


def test_a_refusal_describes_itself_without_naming_a_slot():
    result = ClaimResult(reason="nothing readable")
    assert "no hive claimed" in result.describe()
    assert result.describe().endswith("nothing readable")


def test_a_success_describes_how_it_was_confirmed():
    world = FakeHive(["taken", "empty", "taken", "taken", "taken", "taken"])
    text = run(world).describe()
    assert "slot 4" in text and "confirmed by" in text


# ---- the detector you get once the prompts are captured --------------------

def _frame_with(patch, at=(100, 300)):
    """A dark frame with one bright patch pasted into it."""
    frame = np.zeros((720, 1280, 3), np.uint8)
    y, x = at
    frame[y:y + patch.shape[0], x:x + patch.shape[1]] = patch
    return frame


@pytest.fixture
def prompts():
    rng = np.random.default_rng(7)
    claim = rng.integers(0, 255, (24, 120, 3), dtype=np.uint8)
    honey = rng.integers(0, 255, (24, 120, 3), dtype=np.uint8)
    return claim, honey


def test_the_template_reader_tells_the_two_prompts_apart(prompts):
    claim, honey = prompts
    read = template_reader(claim, honey)
    assert read(_frame_with(claim)) is SlotState.EMPTY
    assert read(_frame_with(honey)) is SlotState.MINE


def test_the_template_reader_reports_unknown_when_neither_prompt_is_there(prompts):
    """No prompt means 'no prompt'. It covers another player's hive AND
    standing too far away, and reporting TAKEN would assert the first without
    being able to rule out the second."""
    claim, honey = prompts
    read = template_reader(claim, honey)
    assert read(np.zeros((720, 1280, 3), np.uint8)) is SlotState.UNKNOWN


def test_the_template_reader_prefers_mine_when_both_match(prompts):
    """If both somehow match, the safe reading is the one that claims
    nothing."""
    claim, honey = prompts
    frame = _frame_with(claim)
    frame[500:524, 100:220] = honey
    assert template_reader(claim, honey)(frame) is SlotState.MINE


def test_the_template_reader_honours_its_search_region(prompts):
    claim, honey = prompts
    read = template_reader(claim, honey, region=(0, 0, 640, 200))
    assert read(_frame_with(claim, at=(300, 100))) is SlotState.UNKNOWN
    assert read(_frame_with(claim, at=(20, 100))) is SlotState.EMPTY


def test_the_template_reader_counts_as_a_built_detector(prompts):
    """It is what lifts the refusal, so the flag has to be on it."""
    claim, honey = prompts
    read = template_reader(claim, honey)
    assert read.detector_built is True

    inp = FakeInput()
    result = claim_hive(inp, lambda: _frame_with(claim), read_prompt=read,
                        hop_rise=0.0, hop_settle=0.0, confirm_interval=0.0,
                        confirm_polls=2)
    # the frame never changes, so the claim is correctly NOT confirmed --
    # what matters here is that it got as far as trying
    assert CLAIM_KEY in taps(inp)
    assert not result.ok


def test_the_threshold_is_what_decides_a_degraded_match(prompts):
    """The register records the 'Servers' label needing 0.90 instead of 0.75
    because a tight crop matched the PREFIX of a different row at 0.877. The
    same correction has to be reachable here, so the threshold must really be
    the deciding line rather than decoration.

    The match score is MEASURED from the frame rather than assumed: a
    half-brightness copy of the template still scores ~1.0, because
    TM_CCOEFF_NORMED subtracts the mean and normalises, so a test that assumed
    dimming weakens a match would pass for the wrong reason."""
    from hivemind.vision import templates as tmod
    claim, honey = prompts
    rng = np.random.default_rng(11)
    noisy = ((claim.astype(np.int16) + rng.integers(-110, 110, claim.shape))
             .clip(0, 255).astype(np.uint8))
    frame = _frame_with(noisy)

    score = tmod.find(frame, claim, threshold=0.0).score
    assert 0.1 < score < 0.95, f"degradation did not land in a useful band: {score}"
    assert template_reader(claim, honey,
                           threshold=score + 0.01)(frame) is SlotState.UNKNOWN
    assert template_reader(claim, honey,
                           threshold=score - 0.01)(frame) is SlotState.EMPTY


def test_a_mistyped_hive_claimer_argument_is_rejected():
    """`claim_hive` forwards **kwargs; a typo there would otherwise be silently
    ignored and the caller would think it had set a timing."""
    with pytest.raises(TypeError):
        HiveClaimer(FakeInput(), lambda: None, hop_rize=0.0)


# --------------------- the sweep must not pretend it measured a direction ---
class SweepInput:
    """Everything `sweep_and_claim` presses: taps, held walks, and the key."""

    def __init__(self):
        self.taps: list[str] = []
        self.holds: list[str] = []

    def tap(self, key, ms=40):
        self.taps.append(key)

    def held(self, *keys):
        import contextlib
        self.holds.append("".join(keys))
        return contextlib.nullcontext()

    def release_all(self):
        pass


def test_the_sweep_says_when_no_bearing_hint_was_wired_in():
    """IT PRINTED A FICTION for a whole night. With no hint `look()` returns
    (0, 0) every time, so `best` stays at step 0 and the note read "strongest
    bearing at 0° (0 px)" in every log -- which looks like a measurement of an
    empty screen and is actually "nothing was measured". `w` is
    camera-relative, so with no hint the sweep walks whichever way the camera
    already points, and that is why some claims walked fourteen steps without
    a pad ever appearing."""
    said = []
    vin = SweepInput()
    sweep_and_claim(vin, lambda: np.zeros((8, 8, 4), np.uint8),
                    lambda f: "", sleep=lambda s: None,
                    on_note=said.append, max_walk_steps=1)
    joined = " ".join(said)
    assert "no bearing hint wired in" in joined
    assert "strongest bearing" not in joined


def test_a_bearing_hint_is_used_and_reported():
    said = []
    vin = SweepInput()
    looks = {"n": 0}

    def hint(frame):
        looks["n"] += 1
        # the third look is the yellowest
        return (0, 900 if looks["n"] == 3 else 10)

    sweep_and_claim(vin, lambda: np.zeros((8, 8, 4), np.uint8),
                    lambda f: "", bearing_hint=hint, sleep=lambda s: None,
                    on_note=said.append, max_walk_steps=1)
    joined = " ".join(said)
    assert "strongest bearing at 90° (900 px)" in joined
    assert "no bearing hint" not in joined


def test_the_real_yellow_bearing_separates_the_hive_from_a_field():
    """The measurement that makes it usable as a hint, from
    vision/notice.HIVE_YELLOW: 88,331-522,511 honeycomb-yellow pixels at the
    hive against 8,837-11,840 in a field."""
    import glob
    import cv2
    root = pathlib.Path(__file__).resolve().parents[2]
    at_hive = sorted(glob.glob(str(root / "tests/fixtures/screens/**/at_own_hive.png"),
                               recursive=True))
    if not at_hive:
        pytest.skip("the hive frame is not in the repo")
    frame = cv2.imread(at_hive[0])
    _, strength = hive_bearing(frame)
    assert strength > 40_000, f"only {strength} yellow pixels at the hive"


# ---- the claim sweep turns round when it finds nothing ---------------------
# `w` is camera-relative, so when the hive wall is not in view the sweep walks
# whichever way the camera happens to face. If the pads are behind the
# character it walks AWAY from them and reports there are none. MEASURED
# 2026-09-23: 4 of runs 250-309 died this way, each after 42 seconds, and a
# failed claim ends the whole attempt because without a hive there are no bees
# and nothing would be collected. The successful claims find the pad at step 2.

class _Row:
    """Pads along a line. The character starts at 0, each forward step moves
    one place in `facing`, and four camera taps reverse it."""

    def __init__(self, pads):
        self.pads, self.at, self.facing = dict(pads), 0, +1
        self.taps, self.claimed = [], False

    def panel(self, frame=None):
        if self.claimed and self.at in self.pads:
            return "Make Honey"
        return self.pads.get(self.at, "")

    def vin(self):
        row = self

        class Held:
            def __enter__(self):
                row.at += row.facing
                return self

            def __exit__(self, *exc):
                return False

        class Vin:
            def held(self, key):
                assert key == "w", key
                return Held()

            def tap(self, key):
                row.taps.append(key)
                if key == "e":
                    row.claimed = True
                elif key == "period" and row.taps.count("period") % 4 == 0:
                    row.facing = -row.facing

            def release_all(self):
                pass

        return Vin()


def _blank_frame():
    import numpy as np
    return np.zeros((240, 320, 3), np.uint8)


def test_it_turns_round_and_finds_a_pad_behind_it():
    from hivemind.act.hive import sweep_and_claim
    row = _Row({-3: "Claim Hive"})          # the only pad is BEHIND the start
    result = sweep_and_claim(row.vin(), _blank_frame, row.panel,
                             max_walk_steps=4, walk_step_seconds=0.0,
                             sleep=lambda s: None, look_steps=1)
    assert result.ok, result.reason
    assert result.newly_claimed
    assert "e" in row.taps, "it never pressed to claim"


def test_it_says_both_passes_in_the_reason_when_it_finds_nothing():
    from hivemind.act.hive import sweep_and_claim
    row = _Row({})
    result = sweep_and_claim(row.vin(), _blank_frame, row.panel,
                             max_walk_steps=3, walk_step_seconds=0.0,
                             sleep=lambda s: None, look_steps=1)
    assert not result.ok
    assert "3 steps one way and 6 back" in result.reason, result.reason


def test_a_pad_in_front_is_still_found_on_the_first_pass():
    from hivemind.act.hive import sweep_and_claim
    row = _Row({2: "Make Honey"})
    result = sweep_and_claim(row.vin(), _blank_frame, row.panel,
                             max_walk_steps=5, walk_step_seconds=0.0,
                             sleep=lambda s: None, look_steps=1)
    assert result.ok and result.hops == 2, (result.hops, result.reason)
    assert "e" not in row.taps, "it pressed at a pad that was already ours"


# ---------------------------------------------------------------------------
# A missed claim: a different line next time, and a box (act/hive
# retry_start_taps, CLAIM_RETRY_LIVE). MEASURED 2026-10-22: runs 1189-1200
# looped on the claim, each retry walking the same line from the same spawn.

class _Grid:
    """Pads on a grid. Eight camera taps are a full turn (45 degrees each)
    and every forward step moves one square the way the camera faces."""
    DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]

    def __init__(self, pads):
        self.pads, self.at, self.heading = dict(pads), (0, 0), 0
        self.taps, self.claimed, self.walked = [], False, []

    def panel(self, frame=None):
        if self.claimed and self.at in self.pads:
            return "Make Honey"
        return self.pads.get(self.at, "")

    def vin(self):
        grid = self

        class Held:
            def __init__(self, key):
                self.key = key

            def __enter__(self):
                # `a` and `d` strafe: a quarter turn either side of the facing
                turn = {"w": 0, "d": 2, "a": -2}[self.key]
                dx, dy = grid.DIRS[(grid.heading + turn) % 8]
                grid.at = (grid.at[0] + dx, grid.at[1] + dy)
                grid.walked.append(self.key)
                return self

            def __exit__(self, *exc):
                return False

        class Vin:
            def held(self, key):
                assert key in ("w", "a", "d"), key
                return Held(key)

            def tap(self, key):
                grid.taps.append(key)
                if key == "e":
                    grid.claimed = True
                elif key == "period":
                    grid.heading = (grid.heading + 1) % 8

            def release_all(self):
                pass

        return Vin()


def _grid_sweep(grid, **kwargs):
    from hivemind.act.hive import sweep_and_claim
    return sweep_and_claim(grid.vin(), _blank_frame, grid.panel,
                           max_walk_steps=3, walk_step_seconds=0.0,
                           sleep=lambda s: None, look_steps=8, **kwargs)


def test_a_pad_beside_the_line_is_missed_without_the_box_and_found_with_it():
    result = _grid_sweep(_Grid({(0, 2): "Claim Hive"}))
    assert not result.ok
    grid = _Grid({(0, 2): "Claim Hive"})
    result = _grid_sweep(grid, box_legs=6)
    assert result.ok and result.newly_claimed, result.reason
    assert grid.taps.count("e") == 1


def test_a_box_that_finds_nothing_says_so():
    result = _grid_sweep(_Grid({}), box_legs=2)
    assert not result.ok
    assert "3 steps one way and 6 back and a 2-leg box" in result.reason, result.reason


def test_a_retry_turned_a_quarter_walks_the_other_line():
    grid = _Grid({(0, 2): "Claim Hive"})
    result = _grid_sweep(grid, start_taps=2)
    assert result.ok and result.hops == 2, (result.hops, result.reason)


def test_the_retry_line_follows_the_misses_in_a_row():
    from hivemind.act.hive import RETRY_WINDOW_S, retry_start_taps
    now = 10_000.0
    miss = lambda at: {"at": at, "ok": False, "start_taps": 0}
    assert retry_start_taps([], now) == 0
    assert retry_start_taps([miss(now - 60)], now) == 2
    assert retry_start_taps([miss(now - 90), miss(now - 60)], now) == 1
    assert retry_start_taps([miss(now - 120), miss(now - 90), miss(now - 60)], now) == 3
    assert retry_start_taps([miss(now - 150 + i) for i in range(4)], now) == 0
    # a claim that worked ends the run of misses; so does an old one
    assert retry_start_taps([miss(now - 90), {"at": now - 60, "ok": True}], now) == 0
    assert retry_start_taps([miss(now - RETRY_WINDOW_S - 1)], now) == 0
    assert retry_start_taps([{"bad": 1}, miss(now - 60)], now) == 2


def test_the_claim_history_keeps_the_newest_and_survives_a_broken_file(tmp_path):
    from hivemind.act.hive import (CLAIM_HISTORY_KEEP, load_claim_history,
                                   record_claim)
    path = tmp_path / "claim" / "history.json"
    assert load_claim_history(path) == []
    for i in range(CLAIM_HISTORY_KEEP + 5):
        record_claim(path, i % 2 == 0, 2, 1000.0 + i)
    rows = load_claim_history(path)
    assert len(rows) == CLAIM_HISTORY_KEEP and rows[-1]["at"] == 1000.0 + CLAIM_HISTORY_KEEP + 4
    path.write_text("{not json", encoding="utf-8")
    assert load_claim_history(path) == []
    record_claim(path, False, 0, 5.0)
    assert load_claim_history(path) == [{"at": 5.0, "ok": False, "start_taps": 0}]


def test_the_retry_ships_look_only_and_the_runner_says_what_it_would_do():
    from hivemind.act import hive
    import hivemind
    assert hive.CLAIM_RETRY_LIVE is False
    src = (pathlib.Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py"
           ).read_text(encoding="utf-8")
    assert "hive_mod.claim_retry_would(start, hive_mod.CLAIM_BOX_LEGS)" in src
    assert "start_taps=start if live else 0" in src
    assert "box_legs=hive_mod.CLAIM_BOX_LEGS if live else 0" in src
    assert "hive_mod.record_claim(CLAIM_HISTORY_FILE" in src


def test_the_claim_retry_line_has_both_clauses():
    # MEASURED run-1250.log:90 printed "claim retry would: and walk a 6-leg
    # box if both passes miss" -- the turn clause vanished for start 0.
    from hivemind.act.hive import claim_retry_would
    assert claim_retry_would(0, 6) == ("claim retry would: start facing the usual way "
                                       "(no turn), and walk a 6-leg box if both passes miss")
    assert claim_retry_would(2, 6) == ("claim retry would: start 90° round (the last "
                                       "claim missed), and walk a 6-leg box if both passes miss")


# ---------------------------------------------------------------------------
# ROADMAP A7: runs 1189-1200 (2026-10-22 20:03-20:35) read "Send Trade Request
# to <player>" where the free pad's 'Claim Hive' is, and rejoined twelve times.

def test_a_players_trade_prompt_is_named_in_the_miss_and_never_pressed():
    from hivemind.act.hive import sweep_and_claim
    row = _Row({2: "Send Trade Request to somebody"})
    result = sweep_and_claim(row.vin(), _blank_frame, row.panel,
                             max_walk_steps=3, walk_step_seconds=0.0,
                             sleep=lambda s: None, look_steps=1)
    assert not result.ok and "e" not in row.taps
    assert result.player_at == "step 2"
    assert "another player's trade prompt was read at step 2" in result.reason


def test_claim_misses_in_a_row_end_at_a_success_or_a_long_gap():
    from hivemind.act.hive import misses_in_a_row
    now, gap = 10_000.0, 3600.0
    miss = lambda at: {"at": at, "ok": False}
    assert misses_in_a_row([], now, gap) == 0
    # twelve misses ~2.7 min apart, as 20:03-20:35 that night
    assert misses_in_a_row([miss(now - 160 * i) for i in range(11, -1, -1)], now, gap) == 12
    assert misses_in_a_row([miss(now - 300), {"at": now - 200, "ok": True},
                            miss(now - 100)], now, gap) == 1
    assert misses_in_a_row([miss(now - 2 * gap - 10), miss(now - gap)], now, gap) == 1
    assert misses_in_a_row([miss(now - gap - 1)], now, gap) == 0
    assert misses_in_a_row([{"bad": 1}, miss(now - 60)], now, gap) == 1


def test_the_runner_spaces_a_missed_claims_rejoin_out():
    import hivemind
    src = (pathlib.Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py"
           ).read_text(encoding="utf-8")
    assert '"could not claim a hive" in (report.stopped_because' in src
    assert "wait = startfails.backoff_s(misses)" in src


# Runs 1189-1200 replayed (act/hive CLAIM_ROW_LIVE). MEASURED 2026-10-22: one
# private server, 12 fresh joins, every one read "Send Trade Request to <a
# player>" at step 2 -- another player at the pad straight ahead, theirs -- and
# walked 14 steps out and 28 back without another panel. The spawn frame
# (var/badges/20261022-200419) shows a free pad either side of theirs.
# ponytail: a grid square is one step forward and one slot sideways; the real
# spacing is the live check's to confirm.

TRADE = "Send Trade Request to someplayer"     # a player's name, not kept here


def _server_1189():
    return _Grid({(2, 0): TRADE, (2, 1): "Claim Hive", (2, -1): "Claim Hive",
                  (2, 2): "", (2, -2): ""})


def _join(grid, notes=None, **kwargs):
    from hivemind.act.hive import sweep_and_claim
    return sweep_and_claim(grid.vin(), _blank_frame, grid.panel,
                           max_walk_steps=14, walk_step_seconds=0.0,
                           sleep=lambda s: None, look_steps=8,
                           on_note=(notes.append if notes is not None else None),
                           **kwargs)


def test_runs_1189_to_1200_loop_and_the_turned_retry_and_box_do_not_break_it():
    from hivemind.act.hive import CLAIM_BOX_LEGS, retry_start_taps
    history, now = [], 10_000.0
    for _run in range(12):
        start = retry_start_taps(history, now)
        grid = _server_1189()
        result = _join(grid, start_taps=start, box_legs=CLAIM_BOX_LEGS)
        assert not result.ok and "e" not in grid.taps, (start, result.describe())
        history.append({"at": now, "ok": False, "start_taps": start})
        now += 180


# The row at step 2 as a line in studs, for the edge-counting row search
# (act/hive `strafe`). MEASURED inputs: the prompt shows only a few studs
# either side of a pad's middle (hiverow lost it after the stop on 140 of 791
# holds onto our pad, var/night/run-*.log), and a timed walk scatters 15%
# (785 of them from the spawn point: 1.8 s mean, sd 0.27). The default 3.25
# studs either side and 0.12 s from key to motion reproduce that 17.7% on
# this model (docs/pending/claimedge.md). ASSUMED: Natro's 36.8-stud slot,
# and no prompt at a taken pad whose owner is away.
class _Strip:
    def __init__(self, pads, speed=32.2, spacing=36.8, half=3.25, lag=0.12, x0=0.0):
        self.pads, self.speed, self.spacing = dict(pads), speed, spacing
        self.half, self.lag, self.x0 = half, lag, x0
        self.t, self.depth, self.moves = 0.0, 0, []
        self.taps, self.walked, self.claimed, self.e_on = [], [], None, []

    def sleep(self, s):
        if s > 0:
            self.t += max(s, 1e-6)     # a crumb of time below the float's step would stall it

    def clock(self):
        return self.t

    def x(self):
        x = self.x0
        for on, off, way in self.moves:
            a = on + self.lag
            b = min(self.t, (off + self.lag) if off is not None else self.t)
            if b > a:
                x += way * self.speed * (b - a)
        return x

    def pad(self):
        if self.depth != ROW_DEPTH:
            return None
        k = round(self.x() / self.spacing)
        return k if abs(self.x() - k * self.spacing) <= self.half else None

    def panel(self, frame=None):
        k = self.pad()
        if k is not None and k == self.claimed:
            return "Make Honey"
        return self.pads.get(k, "") if k is not None else ""

    def vin(self):
        strip = self

        class Held:
            def __init__(self, key):
                self.key = key

            def __enter__(self):
                strip.walked.append(self.key)
                if self.key == "w":
                    back = strip.taps.count("period") % 8 == 4
                    strip.depth += -1 if back else 1
                else:
                    strip.moves.append([strip.t, None, {"a": -1, "d": 1}[self.key]])
                return self

            def __exit__(self, *exc):
                if self.key != "w":
                    strip.moves[-1][1] = strip.t
                return False

        class Vin:
            def held(self, key):
                assert key in ("w", "a", "d"), key
                return Held(key)

            def tap(self, key):
                strip.taps.append(key)
                if key == "e":
                    strip.e_on.append(strip.panel())
                    if strip.panel() == "Claim Hive":
                        strip.claimed = strip.pad()

            def release_all(self):
                pass

        return Vin()


ROW_DEPTH = 2
SERVER_1189 = {0: TRADE, -1: "Claim Hive", 1: "Claim Hive"}   # 2+ pads out: taken, nobody there


def _strip_join(strip, notes=None, *, assumed_speed=32.2, **kwargs):
    from hivemind.act.hive import CLAIM_ROW_SLOTS, ROW_SLOT_STUDS
    kwargs.setdefault("row_slots", CLAIM_ROW_SLOTS)
    return sweep_and_claim(strip.vin(), _blank_frame, strip.panel,
                           max_walk_steps=14, walk_step_seconds=0.0,
                           look_steps=8, sleep=strip.sleep, clock=strip.clock,
                           row_step_seconds=ROW_SLOT_STUDS / assumed_speed,
                           on_note=(notes.append if notes is not None else None),
                           **kwargs)


@pytest.mark.parametrize("speed", [22.5, 27.4, 32.2, 37.0, 41.9])   # -30% .. +30%
def test_runs_1189_to_1200_the_row_counts_pads_and_claims_beside_the_taken_one(speed):
    strip, notes = _Strip(SERVER_1189, speed=speed), []
    result = _strip_join(strip, notes)
    assert result.ok and result.newly_claimed and result.hops == 2, result.describe()
    assert strip.claimed == -1 and strip.e_on == ["Claim Hive"], strip.e_on
    assert not any(n.startswith("row right") for n in notes), notes   # the first side had it
    assert any(n.startswith("row left pad 1 after") for n in notes), notes
    assert any("searching the hive row" in n and TRADE in n for n in notes), notes


def test_a_row_with_nothing_free_is_bounded_never_pressed_and_the_passes_go_on():
    strip = _Strip({0: TRADE, 1: TRADE.replace("someplayer", "another")})
    result = _strip_join(strip)
    assert not result.ok and "e" not in strip.taps
    assert strip.walked[:2] == ["w", "w"] and strip.walked[-40:] == ["w"] * 40
    assert {"a", "d"} <= set(strip.walked)
    passes = 8 * 0.35 + 42 * 0.4                    # the look round and the two passes
    assert strip.t - passes < 25, strip.t           # the three sides are bounded


@pytest.mark.parametrize("speed", [25.8, 32.2, 38.6])                # -20% .. +20%
def test_a_side_with_no_prompts_ends_and_the_other_side_walks_its_tail_back(speed):
    # the left side's pads are taken and nobody stands at them (no prompt,
    # ASSUMED); the free pad is two to the right, past another player's
    strip, notes = _Strip({0: TRADE, 1: TRADE + "2", 2: "Claim Hive"}, speed=speed), []
    result = _strip_join(strip, notes)
    assert result.ok and strip.claimed == 2 and strip.e_on == ["Claim Hive"], notes
    assert not any(n.startswith("row left pad") for n in notes), notes


def test_a_join_receipt_on_the_way_is_not_counted_as_a_pad():
    strip, notes = _Strip({0: TRADE, -1: "You've made 1,234 Honey today",
                           -2: "Claim Hive"}), []
    result = _strip_join(strip, notes, row_slots=2)
    assert result.ok and strip.claimed == -2, (result.describe(), notes)
    assert any(n.startswith("row left pad 1 after") for n in notes), notes


def test_the_row_search_ships_look_only_and_says_what_it_would_do():
    from hivemind.act import hive
    import hivemind
    assert hive.CLAIM_ROW_LIVE is False
    strip, notes = _Strip(SERVER_1189), []
    result = _strip_join(strip, notes, row_live=False)
    assert not result.ok and "e" not in strip.taps
    assert strip.walked == ["w"] * (14 + 28)          # exactly the old walk
    would = [n for n in notes if n.startswith("claim row would: ")]
    assert would == [
        "claim row would: search the hive row from step 2 — hold left past 3 "
        "pad(s), right past 6 and left past 3 back, counting a pad each time "
        "the panel goes and comes back, stopping on 'Claim Hive'; a side ends "
        f"2.9s after its last panel — the panel here read {TRADE!r}"], notes
    src = (pathlib.Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py"
           ).read_text(encoding="utf-8")
    assert "row_live=hive_mod.CLAIM_ROW_LIVE" in src
    assert "row_slots=hive_mod.CLAIM_ROW_SLOTS" in src
    assert "panel_seen=lambda frame: banner.find(frame) is not None" in src


def test_a_turned_retry_does_not_search_a_row_that_is_not_ahead():
    grid = _server_1189()
    _join(grid, start_taps=2, row_slots=3)
    assert "a" not in grid.walked and "d" not in grid.walked


def test_the_trade_prompt_split_over_two_lines_is_not_a_pad():
    from hivemind.act.hive import SlotState, _state_of
    assert _state_of("Send Trade Request to\nsomeplayer") is SlotState.UNKNOWN
