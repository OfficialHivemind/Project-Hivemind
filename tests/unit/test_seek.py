"""Walk until the panel names the place. See act/seek."""
from __future__ import annotations

import contextlib

from hivemind.act import seek as S
from hivemind.vision import landmarks as lm

TABLE = lm.Table({
    "hive": {"kind": "hive", "prompts": [{"text": "make honey", "mine": True}]},
    "red_cannon": {"kind": "transport", "prompts": ["fire the red cannon"]},
    "ticket_shop": {"kind": "shop", "prompts": ["open shop"]},
})


class Vin:
    def __init__(self):
        self.taps, self.holds, self.released = [], [], 0

    @contextlib.contextmanager
    def held(self, *keys):
        self.holds.append("".join(keys))
        yield

    def tap(self, key, ms=40):
        self.taps.append(key)

    def release_all(self):
        self.released += 1


def panel(*reads):
    """Panel text per look, in order; the last repeats."""
    box = list(reads)

    def read(frame):
        return box.pop(0) if len(box) > 1 else (box[0] if box else "")
    return read


def run(reads, place="red_cannon", **kw):
    vin = Vin()
    out = S.seek(vin, lambda: object(), panel(*reads), TABLE, place,
                 sleep=lambda s: None, **kw)
    return vin, out


def test_already_there_costs_nothing():
    vin, out = run(["Fire the Red Cannon"])
    assert out.found and out.steps == 0 and vin.holds == []


def test_it_walks_until_the_panel_names_the_place():
    vin, out = run(["", "", "Fire the Red Cannon"])
    assert out.found and out.steps == 2
    assert vin.holds == ["w", "w"]
    assert out.prompt == "Fire the Red Cannon"


def test_the_wrong_landmark_does_not_end_the_search_but_is_remembered():
    vin, out = run(["", "Open Shop", "Fire the Red Cannon"])
    assert out.found and out.steps == 2
    assert "Open Shop" in out.seen


def test_it_turns_a_quarter_after_each_leg_and_counts_the_taps():
    vin, out = run([""], legs=2, first_leg=1)
    assert not out.found
    assert out.steps == 1 + 2
    assert out.taps == 4 and vin.taps.count("period") == 4


def test_it_never_presses_e():
    vin, out = run(["", "", "Fire the Red Cannon"])
    assert "e" not in vin.taps
    vin, out = run([""], legs=2)
    assert "e" not in vin.taps


def test_a_stop_request_ends_it():
    vin, out = run([""], stopped=lambda: True)
    assert not out.found and out.reason == "stop requested"
    assert vin.holds == []


def test_an_unreadable_panel_is_not_a_match():
    vin, out = run([None], legs=1)
    assert not out.found and out.seen == []


def test_the_search_is_bounded():
    vin, out = run([""], legs=S.LEGS, first_leg=S.FIRST_LEG)
    assert out.steps == sum(S.FIRST_LEG + i for i in range(S.LEGS))
    assert "without the panel ever naming it" in out.reason


def test_keys_are_released_however_it_ends():
    vin, out = run([""], legs=1)
    assert vin.released >= 1


def test_describe_says_what_it_saw():
    vin, out = run(["", "Make Honey"], legs=1, first_leg=1)
    assert "did not find the red cannon" in out.describe()
    assert "'Make Honey'" in out.describe()
    vin, out = run(["Fire the Red Cannon"])
    assert "found the red cannon" in out.describe()
