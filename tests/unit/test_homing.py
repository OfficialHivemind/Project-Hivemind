"""Walking to your own hive by looking, not by timing.

MEASURED 2026-09-22: the recorded walk home reached the hive 0 times in 52
attempts. The owner: the AI has to keep looking and lining the player up.
These tests drive `home_by_sight` with a scripted world and check that it
looks before every step, turns toward the yellow, uses the name to pick the
pad, and ends only on the panel's word.
"""
from __future__ import annotations

import numpy as np
import pytest

from hivemind.act import homing
from hivemind.act.homing import _direction, home_by_sight


# --- the one-word answer parser -------------------------------------------

@pytest.mark.parametrize("said, want", [
    ("LEFT", "LEFT"),
    ("right", "RIGHT"),
    ("Centre", "CENTRE"),
    ("center", "CENTRE"),
    ("It is in the middle of the image.", "CENTRE"),
    ("NO", "NO"),
    ("No, the name is not visible.", "NO"),
    # THE ONE THAT BITES: a chatty model that mentions a side while denying.
    ("I do not see the name on the left side of the image.", "NO"),
    ("The name is not visible anywhere.", "NO"),
    # earliest side word wins, so this is RIGHT and not CENTRE
    ("right of centre", "RIGHT"),
    ("", None),
    (None, None),
    ("a honeycomb wall", None),
])
def test_the_answer_parses_without_guessing(said, want):
    assert _direction(said) == want


# --- a scripted world ------------------------------------------------------

class World:
    """Where the character is, in a one-dimensional row facing the hive.

    `facing` is camera taps off the hive (0 = facing it). `dist` is steps
    from the row (0 = at it). `x` is position along the row; the owner's pad
    is at `pad`. The panel reads "Make Honey" only at dist 0 and x == pad.
    """

    def __init__(self, facing=0, dist=3, x=0, pad=0):
        self.facing, self.dist, self.x, self.pad = facing, dist, x, pad
        self.frames = 0

    def frame(self):
        self.frames += 1
        return np.zeros((1080, 1920, 3), dtype=np.uint8)

    def panel(self, frame):
        # At the row every pad shows a prompt: ours "Make Honey", the rest
        # "Claim Hive" (taken pads show none; `Taken` below models those).
        if self.dist != 0:
            return ""
        return "Make Honey" if self.x == self.pad else "Claim Hive"

    def bearing(self, frame):
        if abs(self.facing) >= 2:            # 90 degrees or more: not in view
            return (0, 1_000)
        px = 500 * self.facing
        # hive_bearing's re-measured figures: 167,686 on a pad, 82,941 one
        # step off, 22,000-54,000 from the field, under 15,000 with no hive
        yellow = {0: 167_000, 1: 83_000, 2: 54_000, 3: 30_000}.get(self.dist,
                                                                  8_000)
        return (px, yellow)

    def ask(self, png, question):
        class A:
            def __init__(self, t): self.text = t
        if self.dist > 0:
            return A("NO")
        if self.x == self.pad:
            return A("CENTRE")
        return A("LEFT" if self.pad < self.x else "RIGHT")

    def available(self):
        return True


class Vin:
    def __init__(self, world):
        self.w = world
        self.taps: list[str] = []
        self.holds: list[str] = []
        self.moving = ""                 # the key down right now, for Ground

    def tap(self, key):
        self.taps.append(key)
        # `facing` is how many taps the hive sits to the RIGHT of centre, so a
        # right tap ("period", CAMERA_KEYS) brings it TOWARD zero. The first
        # draft of this fake had the sign backwards and turned away from the
        # hive on every correction.
        self.w.facing += -1 if key == "period" else 1

    class _Held:
        def __init__(self, vin, key):
            self.vin, self.key = vin, key

        def __enter__(self):
            self.vin.holds.append(self.key)
            self.vin.moving = self.key
            w = self.vin.w
            if any(k in getattr(w, "walls", ()) for k in self.key):
                return self                  # a wall: the keys move nothing
            if "w" in self.key and w.facing == 0:
                w.dist = max(0, w.dist - 1)
            if "a" in self.key:
                w.x -= 1
            if "d" in self.key:
                w.x += 1
            return self

        def __exit__(self, *exc):
            self.vin.moving = ""
            return False

    def held(self, *keys):
        return Vin._Held(self, "".join(keys))


class Ground:
    """A `vision.flow.Odometer` stand-in: the ground moves while a key is down
    unless the world says that key is against a wall."""

    def __init__(self, vin, px=15.0):
        self.vin, self.px = vin, px
        self.dx = self.dy = self.travel = 0.0
        self.samples = 0

    def reset(self):
        self.dx = self.dy = self.travel = 0.0
        self.samples = 0

    def update(self, frame):
        key = self.vin.moving
        if not key:
            return None
        self.samples += 1
        if not any(k in getattr(self.vin.w, "walls", ()) for k in key):
            self.travel += self.px
        return object()

    def displacement(self):
        return None if self.samples == 0 else (-self.dx, -self.dy)


def drive(world, username="ExamplePlayer", model=None, ground=False, **kw):
    vin = Vin(world)
    m = model if model is not None else world
    monkey_bearing(world)
    if ground:
        kw["odometer"] = Ground(vin)
    result = home_by_sight(vin, world.frame, world.panel, m, username,
                           sleep=lambda s: None, **kw)
    return result, vin


def monkey_bearing(world):
    homing.hive_bearing = world.bearing


@pytest.fixture(autouse=True)
def _restore_bearing():
    real = homing.hive_bearing
    yield
    homing.hive_bearing = real


# --- what it does ----------------------------------------------------------

def test_it_ends_only_when_the_panel_says_so():
    world = World(facing=0, dist=2, x=0, pad=0)

    result, vin = drive(world)

    assert result.ok
    assert "Make Honey" in result.confirmed_by
    assert world.dist == 0 and world.x == world.pad


def test_it_looks_before_every_single_step():
    """The closed loop: never more than one step without a frame."""
    world = World(facing=0, dist=3, x=0, pad=0)

    result, vin = drive(world)

    moves = len(vin.holds) + len(vin.taps)
    assert world.frames >= moves, (world.frames, moves)


def test_it_turns_toward_the_yellow_before_walking():
    world = World(facing=1, dist=2, x=0, pad=0)     # hive 45 degrees right

    result, vin = drive(world)

    assert result.ok
    assert vin.taps and vin.taps[0] == "period", vin.taps
    assert result.taps == 1, "the compass must be told about the turn"


def test_it_scans_a_full_circle_when_the_hive_is_out_of_view():
    world = World(facing=3, dist=2, x=0, pad=0)     # 135 degrees off

    result, vin = drive(world)

    assert result.ok
    assert vin.taps.count("period") >= 1


def test_it_gives_up_honestly_where_there_is_no_hive():
    class Nowhere(World):
        def bearing(self, frame):
            return (0, 12_000)               # field yellow only, never the hive

    result, vin = drive(Nowhere(facing=0, dist=2))

    assert not result.ok
    assert "never saw the hive" in result.reason
    assert "12,000" in result.reason, "it must say how much yellow it did see"
    assert "20,000+" in result.reason, "and what the hive would have read"
    assert vin.holds == [], "it must not walk when it cannot see the hive"
    assert len(vin.taps) <= homing.TAPS_PER_FULL_TURN + 1, \
        "one full turn is the whole budget; the rejoin is faster than looking longer"


def test_the_name_picks_the_pad_along_the_row():
    """Six pads, ours is two to the right. The yellow alone cannot tell them
    apart; the owner's name can. The row itself is recognised by the panel
    showing a hive prompt on the pad it lands on."""
    world = World(facing=0, dist=1, x=0, pad=2)

    result, vin = drive(world)

    assert result.ok
    assert vin.holds.count("d") >= 2, vin.holds
    assert "a" not in vin.holds, "it walked the wrong way along the row"


def test_the_row_is_recognised_by_the_panel_not_by_a_yellow_count():
    """MEASURED 2026-09-22: our own pad reads 167,686 and the corner of Hive 1
    and the ramp 158,597 -- no count separates them. A pad's prompt does."""
    world = World(facing=0, dist=1, x=0, pad=1)
    said = []

    result, vin = drive(world, on_note=said.append)

    assert result.ok
    assert any("on a pad, so this is the row" in t for t in said), said


def test_taken_pads_show_no_prompt_so_the_wall_is_found_by_stalling():
    """Next to a hive that is not ours there is no prompt at all. Forward
    steps then stop raising the count -- and that, with a high count, is the
    row."""
    class Taken(World):
        def panel(self, frame):
            return "Make Honey" if self.dist == 0 and self.x == self.pad else ""

    world = Taken(facing=0, dist=1, x=0, pad=2)
    said = []

    result, vin = drive(world, on_note=said.append)

    assert result.ok, result.reason
    assert any("this is the row" in t for t in said), said
    assert vin.holds.count("d") >= 2


def test_without_a_name_it_walks_the_row_until_the_panel_speaks():
    """Homing on the yellow alone finds the ROW; the panel still finds the pad."""
    world = World(facing=0, dist=1, x=0, pad=3)

    result, vin = drive(world, username="", model=None)

    assert result.ok
    assert world.x == 3


def test_a_stop_request_ends_it_at_once():
    world = World(facing=0, dist=3)

    result, vin = drive(world, stopped=lambda: True)

    assert not result.ok
    assert result.reason == "stop requested"
    assert vin.holds == [] and vin.taps == []


def test_it_presses_only_movement_and_camera_keys():
    """No interact key, no Enter, no clicks — the username is READ, never typed."""
    world = World(facing=2, dist=3, x=0, pad=2)

    result, vin = drive(world)

    assert set(vin.taps) <= {"period", "comma"}, vin.taps
    assert set(vin.holds) <= {"w", "a", "s", "d"}, vin.holds


def test_it_is_bounded():
    class Stuck(World):
        def panel(self, frame):
            return ""                        # never on the pad

    result, vin = drive(Stuck(facing=0, dist=0, x=0, pad=99), max_looks=6)

    assert not result.ok
    assert result.hops == 6
    assert "6 times" in result.reason


def test_a_tap_that_overshoots_is_not_answered_with_another_tap():
    """MEASURED 2026-09-22 18:38 on the first live run: one camera tap swings
    the yellow's centroid about 800 px, so with a 240 px deadband it went
    +481 -> -315 -> +484 -> -378 for twenty looks beside the hive wall and
    never stepped forward. A sign flip after a tap means the hive is
    bracketed; the answer is to walk, not to turn back."""
    class Swing(World):
        # the hive sits 400 px right; each tap swings the view 800 px
        def __init__(self):
            super().__init__(facing=0, dist=1, x=0, pad=0)
            self.offset = 400

        def bearing(self, frame):
            yellow = 83_000 if self.dist == 1 else 167_000
            return (self.offset, yellow)

    world = Swing()
    vin = Vin(world)
    real_tap = vin.tap

    def tap(key):
        real_tap(key)
        world.offset += -800 if key == "period" else 800
        world.facing = 0                 # keep the fake's walk working
    vin.tap = tap
    homing.hive_bearing = world.bearing

    result = home_by_sight(vin, world.frame, world.panel, world, "ExamplePlayer",
                           sleep=lambda s: None)

    assert result.ok, result.reason
    assert len(vin.taps) <= 2, f"it kept turning: {vin.taps}"
    assert "w" in vin.holds



def test_field_yellow_is_not_mistaken_for_the_hive():
    """MEASURED 2026-09-22 18:49: the field read 8,837-11,840 yellow px under
    the old compass and the loop walked twenty steps toward 11,272 of them.
    Under the re-measured compass fields read up to 15,000 and the wall
    22,000+. Nothing under IN_VIEW_YELLOW may start a walk."""
    class Flowers(World):
        def bearing(self, frame):
            return (300, 15_000)             # the worst field reading measured; under the wall's 20,000

    result, vin = drive(Flowers(facing=0, dist=3))

    assert not result.ok
    assert "w" not in vin.holds, f"it walked at flowers: {vin.holds}"


def test_a_tap_that_swings_the_hive_out_of_view_is_undone_not_scanned():
    """MEASURED 2026-09-22 18:55 (run 224): the hive read -730 px, a left tap
    swung it clean out of the frame, the scan tapped right and found it at
    -730 again -- eighteen looks of that. Two in-view bearings never had
    opposite signs, so the sign-flip rule never fired. The overshoot is the
    disappearance itself: undo the tap and walk."""
    class EdgeOfView(World):
        # the hive sits far left; a left tap loses it entirely, a right tap
        # brings it back to the same spot
        def __init__(self):
            super().__init__(facing=0, dist=2, x=0, pad=0)
            self.visible = True

        def bearing(self, frame):
            if not self.visible:
                return (0, 5_000)
            yellow = {2: 54_000, 1: 83_000, 0: 167_000}.get(self.dist, 167_000)
            return (-730, yellow)

    world = EdgeOfView()
    vin = Vin(world)

    def tap(key):
        vin.taps.append(key)
        world.visible = key == "period"      # left loses it, right restores it
    vin.tap = tap
    homing.hive_bearing = world.bearing

    result = home_by_sight(vin, world.frame, world.panel, world, "ExamplePlayer",
                           sleep=lambda s: None)

    assert result.ok, result.reason
    assert vin.taps.count("comma") <= 2, f"it kept turning left: {vin.taps}"
    assert sum(1 for h in vin.holds if "w" in h) >= 2, "it never walked while the hive was off-centre"


def test_never_two_correcting_taps_without_a_step_between():
    """The rule that ends both spins. A tap, then a step, whatever the next
    look says short of losing the hive."""
    class Stubborn(World):
        # always reads well off-centre on the same side while approaching
        def bearing(self, frame):
            yellow = {3: 30_000, 2: 54_000, 1: 83_000, 0: 167_000}.get(self.dist, 167_000)
            return (-600 if self.dist > 0 else 0, yellow)

    world = Stubborn(facing=0, dist=3, x=0, pad=0)
    vin = Vin(world)
    vin.tap = lambda key: vin.taps.append(key)   # taps change nothing here
    homing.hive_bearing = world.bearing

    result = home_by_sight(vin, world.frame, world.panel, world, "ExamplePlayer",
                           sleep=lambda s: None)

    assert result.ok, result.reason
    # the order of taps and holds is not recorded; the ratio is the contract
    assert vin.taps.count("comma") <= sum(1 for h in vin.holds if "w" in h), (vin.taps, vin.holds)


def test_stalling_against_a_high_count_means_the_row_not_a_blockage():
    """MEASURED 2026-09-22 19:46 (run 237): 88,338 -> 144,603 -> then twenty-two
    forward steps between 146,056 and 151,645 yellow px, wedged against Hive
    1. Under the re-measured compass that corner reads 158,597 and our own
    pad 167,686 -- so a stall at a high count means the wall is reached and
    the row is to be walked, never twenty more steps into it."""
    class Wedged(World):
        def bearing(self, frame):
            return (-150, {3: 30_000, 2: 158_000}.get(self.dist, 158_000))

        def panel(self, frame):
            return ""                        # no pad here: a wall

    world = Wedged(facing=0, dist=3, x=0, pad=0)
    world.walls = ()
    vin = Vin(world)

    class _Held(Vin._Held):
        def __enter__(self):
            self.vin.holds.append(self.key)
            self.vin.moving = self.key
            if "w" in self.key:
                self.vin.w.dist = max(2, self.vin.w.dist - 1)   # the wall
            return self
    vin.held = lambda *keys: _Held(vin, "".join(keys))
    homing.hive_bearing = world.bearing
    said = []

    result = home_by_sight(vin, world.frame, world.panel, world, "ExamplePlayer",
                           sleep=lambda s: None, on_note=said.append, max_looks=12)

    assert not result.ok
    assert vin.holds.count("w") == 1 + homing.STALLED_STEPS, vin.holds
    assert any("this is the row" in t for t in said), said
    assert {"a", "d"} & set(vin.holds), "it never walked the row"


def test_stalling_at_a_low_count_is_a_blockage_and_ends_fast():
    """The same stall far from the hive -- a fence, a tree -- is not the row.
    Say so at once; the rejoin is cheaper than the look budget."""
    class Fenced(World):
        def bearing(self, frame):
            return (-150, 30_000)            # in view, far away, never rising

    world = Fenced(facing=0, dist=5, x=0, pad=0)
    vin = Vin(world)

    class _Held(Vin._Held):
        def __enter__(self):
            self.vin.holds.append(self.key)
            return self                      # nothing moves
    vin.held = lambda *keys: _Held(vin, "".join(keys))
    homing.hive_bearing = world.bearing

    result = home_by_sight(vin, world.frame, world.panel, world, "ExamplePlayer",
                           sleep=lambda s: None)

    assert not result.ok
    assert "blocked" in result.reason and "30,000" in result.reason, result.reason
    # the count never rose, so every step after the first was a flat one
    assert vin.holds.count("w") == homing.STALLED_STEPS, vin.holds


def test_a_step_the_ground_says_moved_nothing_stalls_at_once():
    """With the ground odometer, a wall is known on the first step against it,
    not after three flat counts."""
    class Wall(World):
        walls = ("w",)

        def bearing(self, frame):
            return (0, 30_000)

    result, vin = drive(Wall(facing=0, dist=5), ground=True)

    assert not result.ok
    assert "blocked" in result.reason
    assert vin.holds.count("w") <= 2, vin.holds


def test_a_blocked_sidestep_turns_the_row_walk_round():
    """At the row, walking right into the ramp's side: the ground says the
    sidestep moved nothing, so the walk goes left instead and finds the pad."""
    class RampSide(World):
        walls = ("d",)

        def ask(self, png, question):
            class A:
                text = "NO"
            return A()

    world = RampSide(facing=0, dist=0, x=0, pad=-2)
    said = []

    result, vin = drive(world, ground=True, on_note=said.append)

    assert result.ok, result.reason
    # right once, back out, right once more, then turn round
    assert vin.holds.count("d") == 2 and "s" in vin.holds, vin.holds
    assert vin.holds.count("a") >= 2
    assert any("still blocked to the right" in t for t in said), said


def test_blocked_both_ways_along_the_row_gives_up_with_the_reason():
    class Boxed(World):
        walls = ("a", "d")

        def ask(self, png, question):
            class A:
                text = "NO"
            return A()

    result, vin = drive(Boxed(facing=0, dist=0, x=0, pad=5), ground=True)

    assert not result.ok
    assert "blocked both ways along the hive row" in result.reason, result.reason


def test_slow_real_progress_is_not_called_blocked():
    """A 5% rise per step is a slow approach, not a wall."""
    class Slow(World):
        def __init__(self):
            super().__init__(facing=0, dist=8, x=0, pad=0)

        def bearing(self, frame):
            if self.dist == 0:
                return (0, 167_000)
            return (0, int(30_000 * (1.05 ** (8 - self.dist))))

    result, vin = drive(Slow())

    assert result.ok, result.reason
    assert "blocked" not in (result.reason or "")


def test_every_look_is_kept_as_a_named_frame(tmp_path):
    """The record that turned run 237's numbers into a picture of a corner."""
    world = World(facing=1, dist=2, x=0, pad=0)

    result, vin = drive(world, save_dir=tmp_path)

    assert result.ok
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == result.hops, names
    assert names[0].startswith("look00-turn-right-y") and names[0].endswith(".jpg")
    assert any("-step-" in n for n in names)
    assert names[-1].startswith(f"look{result.hops - 1:02d}-on-our-pad")


def test_a_failed_save_costs_nothing():
    world = World(facing=0, dist=1, x=0, pad=0)

    result, vin = drive(world, save_dir="/proc/nowhere/homing")

    assert result.ok


def test_a_hive_beside_us_is_approached_diagonally_not_straight():
    """MEASURED 2026-09-22 20:27 (run 244): the hive read -578 px, a left tap
    lost it, the tap back found it at -578, a straight step left it at -578
    -- twelve looks. Walking straight never changes a bearing to something
    beside you; the step after a tap-back goes toward the hive's side."""
    class Beside(World):
        def __init__(self):
            super().__init__(facing=0, dist=3, x=0, pad=0)
            self.visible = True
            self.offset = -578

        def bearing(self, frame):
            if not self.visible:
                return (0, 0)
            return (self.offset, 62_000)

    world = Beside()
    vin = Vin(world)

    def tap(key):
        vin.taps.append(key)
        world.visible = key == "period"          # a left tap loses it, right restores
    vin.tap = tap
    homing.hive_bearing = world.bearing

    home_by_sight(vin, world.frame, world.panel, world, "ExamplePlayer",
                  sleep=lambda s: None, max_looks=6)

    assert "wa" in vin.holds, f"never walked toward the hive's side: {vin.holds}"
    assert "w" not in vin.holds[:4], f"walked straight while the hive was beside us: {vin.holds}"


def test_a_row_end_landmark_prompt_means_walk_the_row():
    """MEASURED 2026-09-22 20:27 (run 244): "E Open Beequip Storage" on the
    panel, the pads in view to the right, and eighteen looks spent turning
    toward the storage's wall. The storage is at the row's end."""
    class ByTheStorage(World):
        def panel(self, frame):
            if self.dist == 0 and self.x == self.pad:
                return "Make Honey"
            return "Open Beequip Storage" if self.x == 0 else ""

        def bearing(self, frame):
            return (-676, 413_760)               # the storage's wall, huge and left

    world = ByTheStorage(facing=0, dist=0, x=0, pad=3)
    said = []

    result, vin = drive(world, on_note=said.append)

    assert result.ok, result.reason
    assert any("end of the hive row" in t for t in said), said
    assert vin.taps == [], f"it turned toward the wall: {vin.taps}"
    assert vin.holds.count("d") >= 3


def test_a_measured_no_motion_step_is_acted_on_before_any_turn():
    """Run 244 again: 'that step moved nothing' at 88,789 px, then a tap, a
    tap back, a tap... The verdict comes first now."""
    class Wall(World):
        walls = ("w",)

        def bearing(self, frame):
            return (-578, 88_789)                # off-centre enough to want a tap

        def panel(self, frame):
            return "Make Honey" if self.x == self.pad else ""

    world = Wall(facing=0, dist=0, x=0, pad=-2)     # at the row, pad two to the left
    said = []

    result, vin = drive(world, ground=True, on_note=said.append)

    assert result.ok, result.reason
    first_w = next(i for i, h in enumerate(vin.holds) if "w" in h)
    after = vin.holds[first_w + 1:]
    assert after and after[0] in ("a", "d"), f"it turned instead of walking the row: {vin.holds} {vin.taps}"
    assert any("this is the row" in t for t in said), said


def test_a_camera_tap_is_not_mistaken_for_progress_or_for_a_stall():
    """A tap swings the count without moving the character; the step after it
    starts a fresh comparison rather than being judged against a view that
    no longer exists. Here the hive reads off to alternate sides after every
    tap while the walk genuinely closes on it."""
    class Swinging(World):
        def bearing(self, frame):
            side = 600 if len(self.vinref.taps) % 2 == 0 else -600
            yellow = {5: 30_000, 4: 45_000, 3: 60_000, 2: 83_000,
                      1: 120_000}.get(self.dist, 167_000)
            return (side, yellow)

    world = Swinging(facing=0, dist=5, x=0, pad=0)
    vin = Vin(world)
    world.vinref = vin
    vin.tap = lambda key: vin.taps.append(key)      # taps turn the camera, not the walk
    homing.hive_bearing = world.bearing
    result = home_by_sight(vin, world.frame, world.panel, world, "ExamplePlayer",
                           sleep=lambda s: None)
    assert result.ok, result.reason
    assert "blocked" not in (result.reason or ""), result.reason


def test_a_blocked_sidestep_backs_out_of_a_gap_before_turning_round():
    """Runs 246/247: the name LEFT, every step left blocked -- the character
    stood in the gap between two hives. One step back, then left again."""
    class Gap(World):
        def __init__(self):
            super().__init__(facing=0, dist=0, x=0, pad=-2)
            self.depth = 1                          # one step into the gap

        def ask(self, png, question):
            class A:
                text = "LEFT"
            return A()

    world = Gap()
    vin = Vin(world)

    class _Held(Vin._Held):
        def __enter__(self):
            self.vin.holds.append(self.key)
            self.vin.moving = self.key
            w = self.vin.w
            if "s" in self.key:
                w.depth = max(0, w.depth - 1)       # backing out of the gap
            elif "a" in self.key and w.depth == 0:
                w.x -= 1                            # free to walk the row once out
            elif "d" in self.key and w.depth == 0:
                w.x += 1
            return self
    vin.held = lambda *keys: _Held(vin, "".join(keys))

    class Ground:
        def __init__(self):
            self.dx = self.dy = self.travel = 0.0; self.samples = 0
        def reset(self): pass
        def update(self, frame):
            key = vin.moving
            if not key: return None
            self.samples += 1
            moved = ("s" in key) or (world.depth == 0)
            if moved: self.travel += 15.0
            return object()
        def displacement(self): return None

    homing.hive_bearing = world.bearing
    said = []
    result = home_by_sight(vin, world.frame, world.panel, world, "ExamplePlayer",
                           sleep=lambda s: None, on_note=said.append, odometer=Ground())

    assert result.ok, result.reason
    assert "s" in vin.holds, "it never backed out"
    assert any("stepping back out" in t for t in said), said
    assert "d" not in vin.holds, f"it turned round instead of backing out: {vin.holds}"


def test_a_named_landmark_is_handed_to_the_caller_and_ends_the_walk():
    """MEASURED 2026-09-22 22:54 (attempt 253): while walking the row the
    panel said "at the honey dispenser" — 187 studs from the pad by Natro's
    own route — and the loop walked past it for another twelve looks."""
    class PastTheDispenser(World):
        def bearing(self, frame):
            return (0, 167_000)

        def panel(self, frame):
            return "Use the Honey Dispenser"

    world = PastTheDispenser(facing=0, dist=0, x=0, pad=9)
    offered = []

    def on_landmark(text):
        offered.append(text)
        return "honey dispenser" in text.lower()

    result, vin = drive(world, on_landmark=on_landmark)

    assert result.ok, result.reason
    assert "Honey Dispenser" in result.confirmed_by
    assert offered and "Honey Dispenser" in offered[0]
    assert vin.holds == [], "it should not have walked the row at all"


def test_a_rescue_that_does_not_land_leaves_the_walk_going():
    class PastTheDispenser(World):
        def bearing(self, frame):
            return (0, 167_000)

        def panel(self, frame):
            if self.x == self.pad:
                return "Make Honey"
            return "Use the Honey Dispenser"

    world = PastTheDispenser(facing=0, dist=0, x=0, pad=2)
    result, vin = drive(world, on_landmark=lambda text: False)

    assert result.ok, result.reason        # it found the pad by walking the row
    assert vin.holds, "the row walk must continue when the rescue fails"


def test_the_hive_prompt_is_never_offered_as_a_landmark():
    """"Make Honey" and "Claim Hive" are the loop's own business."""
    world = World(facing=0, dist=0, x=0, pad=0)
    offered = []
    result, vin = drive(world, on_landmark=lambda text: offered.append(text) or False)
    assert result.ok
    assert offered == [], offered
