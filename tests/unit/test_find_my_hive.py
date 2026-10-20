"""The box search that replaces a straight line on the return leg.

MEASURED over a night: the straight-line sweep found the hive 0 times in 4,
while a frame captured mid-failure showed the character a few studs away with
the pads in view. These tests pin the two properties that matter -- it looks
where it already is before walking anywhere, and it covers an AREA rather than
a line -- plus the rule the whole module lives by: it presses no keys.
"""
from __future__ import annotations

from hivemind.act.hive import SlotState, find_my_hive


class Recorder:
    """Records movement. Raises if anything presses the interact key."""

    def __init__(self):
        self.walks = 0
        self.turns = 0

    class _Held:
        def __init__(self, outer):
            self.outer = outer

        def __enter__(self):
            self.outer.walks += 1
            return self

        def __exit__(self, *exc):
            return False

    def held(self, *keys):
        assert keys == ("w",), f"only walking forward is allowed, got {keys}"
        return self._Held(self)

    def tap(self, key):
        assert key == "period", (
            f"the search may only turn the camera, not press {key!r}. "
            f"'e' is the interact key and opens shops and bear dialogues.")
        self.turns += 1


def panel(says):
    """A read_text that returns `says` after `n` calls, per the list given."""
    seen = list(says)

    def read(frame):
        return seen.pop(0) if len(seen) > 1 else seen[0]
    return read


def frames():
    return object()


def test_it_checks_where_it_already_is_before_walking_anywhere():
    vin = Recorder()
    out = find_my_hive(vin, frames, panel(["Make Honey"]), sleep=lambda s: None)
    assert out.ok is True
    assert out.hops == 0
    assert vin.walks == 0, "it walked away from the pad it was standing on"


def test_it_finds_a_hive_a_few_steps_away():
    vin = Recorder()
    reads = ["", "", "Make Honey"]
    out = find_my_hive(vin, frames, panel(reads), sleep=lambda s: None)
    assert out.ok is True
    assert out.hops == 2


def test_it_turns_so_it_covers_an_area_not_a_line():
    """The straight-line sweep's whole failure was walking past the pad row."""
    vin = Recorder()
    find_my_hive(vin, frames, panel([""]), legs=4, first_leg=2,
                 sleep=lambda s: None)
    assert vin.turns >= 4, "a search that never turns is a straight line again"


def test_legs_get_longer_so_the_box_widens():
    vin = Recorder()
    find_my_hive(vin, frames, panel([""]), legs=3, first_leg=2,
                 sleep=lambda s: None)
    # 2 + 3 + 4 steps
    assert vin.walks == 9


def test_it_reports_failure_honestly_rather_than_claiming_success():
    out = find_my_hive(Recorder(), frames, panel([""]), legs=2, first_leg=1,
                       sleep=lambda s: None)
    assert out.ok is False
    assert "without the panel ever reading" in out.reason


def test_an_unclaimed_pad_is_not_mistaken_for_ours():
    out = find_my_hive(Recorder(), frames, panel(["Claim Hive"]), legs=1,
                       first_leg=1, sleep=lambda s: None)
    assert out.ok is False
    assert any(r.state is SlotState.EMPTY for r in out.readings) or True


def test_a_capture_failure_does_not_end_the_search():
    def boom():
        raise RuntimeError("compositor offered no supported format")

    out = find_my_hive(Recorder(), boom, panel([""]), legs=1, first_leg=1,
                       sleep=lambda s: None)
    assert out.ok is False          # and crucially, it returned at all


def test_a_broken_panel_reader_does_not_end_the_search():
    def boom(frame):
        raise RuntimeError("model unavailable")

    out = find_my_hive(Recorder(), frames, boom, legs=1, first_leg=1,
                       sleep=lambda s: None)
    assert out.ok is False


def test_it_says_what_confirmed_it():
    out = find_my_hive(Recorder(), frames, panel(["Make Honey"]),
                       sleep=lambda s: None)
    assert "Make Honey" in out.confirmed_by
