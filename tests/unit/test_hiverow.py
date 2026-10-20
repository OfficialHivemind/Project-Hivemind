"""Finding our pad along the hive row: Natro's nm_findHiveSlot, in our terms.

The prompt is the stop signal and the key comes up the moment it shows.
Every hold is bounded, every branch releases what it pressed, and a search
that does not find the prompt says so rather than pressing anything.
"""
from hivemind.act import hiverow


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Vin:
    """Records holds as (key, seconds down) using the fake clock."""

    def __init__(self, clock):
        self.clock = clock
        self.holds: list[tuple[str, float]] = []
        self.down: list[str] = []

    class _Held:
        def __init__(self, vin, key):
            self.vin, self.key = vin, key

        def __enter__(self):
            self.vin.down.append(self.key)
            self.began = self.vin.clock()
            return self

        def __exit__(self, *exc):
            self.vin.down.remove(self.key)
            self.vin.holds.append((self.key, round(self.vin.clock() - self.began, 3)))

    def held(self, *keys):
        assert len(keys) == 1
        return Vin._Held(self, keys[0])


def search(prompt_at, *, clock=None, **kw):
    """`prompt_at(clock_now, key_down) -> bool` scripts when the prompt shows."""
    clock = clock or Clock()
    vin = Vin(clock)

    def at_hive(frame):
        return prompt_at(clock.now, vin.down[0] if vin.down else None)

    out = hiverow.find_along_row(vin, lambda: object(), at_hive, walkspeed=28.0,
                                 clock=clock, sleep=clock.sleep, **kw)
    return out, vin, clock


def test_already_on_the_pad_moves_nothing():
    out, vin, _ = search(lambda now, key: True)
    assert out.ok and out.already
    assert vin.holds == []
    assert "already" in out.describe()


def test_the_key_comes_up_the_moment_the_prompt_shows():
    # the prompt appears 2.0 s into the leftward hold and stays: we are on the pad
    out, vin, _ = search(lambda now, key: now >= 2.0)
    assert out.ok and out.direction == "left"
    assert 2.0 <= out.seen_after <= 2.2, out.seen_after
    assert vin.holds[0][0] == "a" and vin.holds[0][1] <= 2.2, vin.holds
    assert out.corrections == 0
    assert vin.down == [], "a key was left down"


def test_the_left_hold_is_bounded_and_the_right_hold_follows():
    # never on the left; shows 5 s into the rightward hold
    seen = {"right_began": None, "shown": False}

    def prompt(now, key):
        if key == "d":
            if seen["right_began"] is None:
                seen["right_began"] = now
            seen["shown"] = seen["shown"] or now - seen["right_began"] >= 5.0
        return seen["shown"]            # and it stays: we are on the pad
    out, vin, _ = search(prompt)
    assert out.ok and out.direction == "right"
    assert vin.holds[0] == ("a", hiverow.HOLD_SECONDS), vin.holds
    assert vin.holds[1][0] == "d" and 5.0 <= vin.holds[1][1] <= 5.2, vin.holds


def test_never_seeing_the_prompt_is_said_and_nothing_stays_down():
    out, vin, _ = search(lambda now, key: False)
    assert not out.ok
    assert [h[0] for h in vin.holds] == ["a", "d"]
    assert vin.holds[0][1] == hiverow.HOLD_SECONDS
    assert vin.holds[1][1] == hiverow.BACK_HOLD_SECONDS
    assert "without the prompt" in out.reason
    assert vin.down == []


def test_an_overrun_is_walked_back_a_tile_and_a_half_at_a_time():
    """The prompt shows while holding left, is gone at the first look after
    (the character slid past), and is back after one step right."""
    clock = Clock()
    vin = Vin(clock)
    state = {"seen": False}

    def steps_back() -> int:
        return sum(1 for key, _ in vin.holds if key == "d")

    def prompt(frame) -> bool:
        key = vin.down[0] if vin.down else None
        if key == "a" and clock.now >= 1.0:
            state["seen"] = True
            return True
        if key is not None:
            return False                      # mid-step, never
        return state["seen"] and steps_back() >= 1

    out = hiverow.find_along_row(vin, lambda: object(), prompt, walkspeed=28.0,
                                 clock=clock, sleep=clock.sleep)
    assert out.ok and out.corrections == 1, (out, vin.holds)
    # 1.5 tiles at 4 studs a tile, at 28 studs/s
    step = [h for h in vin.holds if h[0] == "d"][0]
    assert abs(step[1] - (1.5 * 4.0 / 28.0)) < 1e-3, step   # the fake rounds to ms
    assert "1 step(s) back" in out.describe()
    assert vin.down == []


def test_an_overrun_that_never_recovers_is_said_after_ten_steps():
    clock = Clock()
    vin = Vin(clock)

    def prompt(frame) -> bool:
        key = vin.down[0] if vin.down else None
        return key == "a" and clock.now >= 1.0       # only ever while sliding past

    out = hiverow.find_along_row(vin, lambda: object(), prompt, walkspeed=28.0,
                                 clock=clock, sleep=clock.sleep)
    assert not out.ok and out.corrections == hiverow.CONFIRM_TRIES
    assert "gone again after 10 step(s)" in out.reason
    assert vin.down == []


def test_a_stop_request_releases_the_key_and_ends_the_search():
    clock = Clock()
    asked = {"stop": False}

    def stopped():
        return asked["stop"]

    def prompt(now, key):
        if now >= 1.0:
            asked["stop"] = True
        return False
    out, vin, _ = search(prompt, clock=clock, stopped=stopped)
    assert not out.ok and "stop" in out.reason
    assert vin.holds[0][0] == "a" and vin.holds[0][1] < hiverow.HOLD_SECONDS
    assert vin.down == []


def test_natros_numbers_are_cited_not_invented():
    assert hiverow.HOLD_SECONDS == 15.0          # 150,000,000 x 100 ns
    assert hiverow.SETTLE_SECONDS == 0.5         # Sleep 500
    assert hiverow.OVERRUN_TILES == 1.5          # nm_Walk(1.5, RightKey)
    assert hiverow.CONFIRM_TRIES == 10           # Loop 10


def test_a_forward_hold_walks_onto_the_pad_and_backs_off_with_s():
    """From the spawn point the pad is straight ahead (act/respawn). The same
    loop, one hold: forward until the prompt, back with S for an overrun."""
    clock = Clock()
    vin = Vin(clock)
    state = {"seen": False}

    def prompt(frame) -> bool:
        key = vin.down[0] if vin.down else None
        if key == "w" and clock.now >= 1.5:
            state["seen"] = True
            return True
        if key is not None:
            return False
        return state["seen"] and any(k == "s" for k, _ in vin.holds)

    out = hiverow.walk_onto_pad(vin, lambda: object(), prompt, walkspeed=28.0,
                                clock=clock, sleep=clock.sleep)
    assert out.ok and out.direction == "forward" and out.key == "w"
    assert vin.holds[0][0] == "w" and vin.holds[0][1] <= 1.7, vin.holds
    assert [k for k, _ in vin.holds][1:] == ["s"], vin.holds
    assert out.corrections == 1
    assert vin.down == []


def test_the_forward_hold_is_bounded_and_says_so():
    clock = Clock()
    vin = Vin(clock)
    out = hiverow.walk_onto_pad(vin, lambda: object(), lambda f: False, walkspeed=28.0,
                                clock=clock, sleep=clock.sleep)
    assert not out.ok
    assert vin.holds == [("w", hiverow.PAD_AHEAD_SECONDS)]
    assert "held forward 8s" in out.reason


# --- a hold of two keys at once: pressing into a wall while sliding along it ----

class VinMany(Vin):
    """Records each hold's keys as a tuple."""

    def held(self, *keys):
        return Vin._Held(self, tuple(keys))


def test_a_hold_may_press_two_keys_together_and_walks_back_with_both_opposites():
    clock = Clock()
    vin = VinMany(clock)
    shown = {"ever": False}

    def at_hive(frame):
        # the prompt shows 1 s into the diagonal hold; the slide carries the
        # character past it once the keys come up (the overrun), and the walk
        # back with both opposite keys brings it back, where it stays
        if shown.get("back"):
            return True
        if vin.down and vin.down[0] == ("w", "a") and clock.now >= 1.0:
            shown["ever"] = True
            return True
        if vin.down and vin.down[0] == ("s", "d"):
            shown["back"] = True
            return True
        return False

    out = hiverow.find_along_row(
        vin, lambda: object(), at_hive, walkspeed=28.0, clock=clock, sleep=clock.sleep,
        holds=((("w", "a"), "forward and left along the wall", 5.0),), overrun="hold")
    assert shown["ever"]
    assert vin.holds[0][0] == ("w", "a")
    assert ("s", "d") in [k for k, _ in vin.holds]          # the walk back, both keys
    assert out.ok and out.key == ("w", "a")


def test_the_walk_back_of_a_two_key_hold_is_named_in_words():
    assert hiverow._name(("s", "d")) == "back and right"
    assert hiverow._opposite(("w", "a")) == ("s", "d")
    assert hiverow._opposite("a") == "d"
    assert hiverow._keys("w") == ("w",) and hiverow._keys(("w", "a")) == ("w", "a")


def test_from_the_face_two_narrow_passes_a_tile_apart():
    # W2, MEASURED: every find from the face came within ~5 s; the misses
    # walked Natro's 15 s + 30 s off the hives. No prompt at all here: the
    # search stays within a side's reach and tries one tile nearer.
    class MovingClock(Clock):          # a real clock never stands still on a 1e-17 s sleep
        def sleep(self, seconds):
            self.now += max(seconds, 1e-3)

    clock = MovingClock()
    vin = Vin(clock)
    out = hiverow.search_from_the_face(vin, lambda: object(), lambda frame: False,
                                       walkspeed=28.0, clock=clock, sleep=clock.sleep)
    assert not out.ok
    assert [k for k, _ in vin.holds] == ["w", "s", "a", "d", "a", "w", "a", "d"]
    assert max(sec for k, sec in vin.holds if k in "ad") <= 2 * hiverow.ROW_SIDE_SECONDS + 0.5
