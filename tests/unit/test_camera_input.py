"""Camera control, and the guarantees around pressing keys.

The camera is not cosmetic. Every movement key is relative to where it points,
so turning it redefines what "forward" means -- which is how the bot escapes
the spot it spawns in, wedged against the hive wall with `w` blocked (measured
in game: forward 0.22 px/frame against 10.88 for strafing). 24 of the
transpiled routes also contain camera steps and cannot run without them.

The key bindings are Roblox's own and are not guessed: BeeTuxMacro's utils.sh
drives `comma` / `period` for yaw and `Prior` / `Next` for zoom.
"""
import pytest

from hivemind.platform.input import VirtualInput
from hivemind.platform.wl.vkeyboard import KEYS


class FakeKeyboard:
    """Records what reached the compositor, in order."""

    def __init__(self, fail_on: str | None = None):
        self.events: list[tuple[str, str]] = []
        self.held: set[str] = set()
        self._fail_on = fail_on

    def press(self, name: str) -> None:
        if name not in KEYS:
            raise KeyError(f"unknown key {name!r}")
        if name == self._fail_on:
            raise OSError("compositor went away")
        self.held.add(name)
        self.events.append(("press", name))

    def release(self, name: str) -> None:
        self.held.discard(name)
        self.events.append(("release", name))

    def release_all(self) -> None:
        for name in list(self.held):
            self.release(name)


class FakeMouse:
    def release_all(self) -> None:
        pass


@pytest.fixture
def vin():
    inp = VirtualInput.__new__(VirtualInput)
    inp.kb = FakeKeyboard()
    inp.mouse = FakeMouse()
    return inp


def taps(inp) -> list[str]:
    return [name for action, name in inp.kb.events if action == "press"]


# ---- the bindings ---------------------------------------------------------

def test_the_camera_keys_exist_in_the_keymap():
    for name in ("comma", "period", "pageup", "pagedown"):
        assert name in KEYS, f"{name} is not mapped; camera control cannot work"


def test_turning_taps_the_roblox_camera_keys(vin):
    vin.camera_left()
    vin.camera_right()
    assert taps(vin) == ["comma", "period"]


def test_zooming_taps_page_up_and_down(vin):
    vin.camera_up()
    vin.camera_down()
    assert taps(vin) == ["pageup", "pagedown"]


def test_multiple_taps_are_sent_separately(vin):
    """A held key does not turn further; Roblox steps per press."""
    vin.camera_right(3, gap=0.0)
    assert taps(vin) == ["period"] * 3


def test_every_camera_tap_is_released(vin):
    vin.camera_right(3, gap=0.0)
    vin.camera_left(2, gap=0.0)
    assert vin.kb.held == set(), "a camera tap left a key down"


# ---- the press guarantees, which the camera relies on ---------------------

def test_a_partial_multi_key_press_leaves_nothing_down():
    """`press('w', 'shfit')` used to put W down and strand it on the typo."""
    inp = VirtualInput.__new__(VirtualInput)
    inp.kb = FakeKeyboard()
    inp.mouse = FakeMouse()
    with pytest.raises(KeyError):
        inp.press("w", "shfit")
    assert inp.kb.held == set(), "the first key stayed down"


def test_held_releases_even_when_the_press_itself_fails():
    """The press is inside the try, so the finally is always armed."""
    inp = VirtualInput.__new__(VirtualInput)
    inp.kb = FakeKeyboard(fail_on="d")
    inp.mouse = FakeMouse()
    with pytest.raises(OSError):
        with inp.held("a", "d"):
            pass
    assert inp.kb.held == set()


def test_release_continues_past_a_failure():
    """One key failing to release must not strand the others."""
    class Awkward(FakeKeyboard):
        def release(self, name):
            if name == "a":
                raise OSError("no")
            super().release(name)

    inp = VirtualInput.__new__(VirtualInput)
    inp.kb = Awkward()
    inp.mouse = FakeMouse()
    inp.press("a", "d")
    with pytest.raises(OSError):
        inp.release("a", "d")
    assert "d" not in inp.kb.held, "the second key was stranded by the first"
