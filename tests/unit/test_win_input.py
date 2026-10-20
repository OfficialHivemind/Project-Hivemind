"""RL6 phase 3: win/input on a fake user32 (runs on Linux; nothing here has
touched a real Windows yet). What matters: the right scan codes and mouse
numbers go out, nothing goes out while another window has the foreground,
and a release always goes out."""
from __future__ import annotations

import ctypes

import pytest

from hivemind.platform import api
from hivemind.platform.win import _user32 as w
from hivemind.platform.win import input as wi

GAME, OTHER = 0x1001, 0x2002


class FakeUser32:
    def __init__(self):
        self.fg = GAME
        self.sent = []                      # decoded INPUTs
        self.origin = (100, 50)             # client area's screen position
        self.vscreen = (0, 0, 3840, 1080)   # two 1080p monitors side by side
        self.blocked = False

    def SendInput(self, n, arr, size):
        assert size == ctypes.sizeof(w.INPUT)
        for ev in arr[:n]:
            if ev.type == w.INPUT_KEYBOARD:
                self.sent.append(("key", ev.ki.wScan, ev.ki.dwFlags))
            else:
                data = ev.mi.mouseData
                data = data - (1 << 32) if data & 0x80000000 else data
                self.sent.append(("mouse", ev.mi.dwFlags, ev.mi.dx, ev.mi.dy, data))
        return 0 if self.blocked else n

    def GetForegroundWindow(self):
        return self.fg

    def SetForegroundWindow(self, hwnd):
        self.fg = hwnd
        return 1

    def GetWindowTextW(self, hwnd, buf, n):
        buf.value = "Discord" if hwnd == OTHER else "Roblox"
        return len(buf.value)

    def ClientToScreen(self, hwnd, ref):
        ref._obj.x += self.origin[0]
        ref._obj.y += self.origin[1]
        return 1

    def GetSystemMetrics(self, i):
        return self.vscreen[i - w.SM_XVIRTUALSCREEN]


@pytest.fixture
def made(monkeypatch):
    monkeypatch.setattr(wi.WinInput, "_install_safety", lambda self: None)
    monkeypatch.setattr(wi.time, "sleep", lambda s: None)
    u = FakeUser32()
    return wi.WinInput(window=lambda: GAME, user32=u), u


def keys(u):
    return [e for e in u.sent if e[0] == "key"]


def test_input_struct_has_the_windows_layout():
    # 64-bit Windows: sizeof(INPUT) == 40 (DWORD type + pad + the 32-byte union)
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(w.INPUT) == 40
    assert ctypes.sizeof(w.KEYBDINPUT) in (16, 24)


def test_same_key_names_as_linux_and_the_same_codes_where_not_extended():
    vk = pytest.importorskip("hivemind.platform.wl.vkeyboard")
    assert set(wi.SCANCODES) == set(vk.KEYS)
    for name, code in wi.SCANCODES.items():
        if not code & wi.EXTENDED:
            assert code == vk.KEYS[name], name
    assert wi._PLAIN == vk._PLAIN and wi._SHIFTED == vk._SHIFTED


def test_a_tap_is_a_scancode_down_then_up(made):
    vin, u = made
    vin.tap("w")
    assert keys(u) == [("key", 0x11, wi.KEYEVENTF_SCANCODE),
                       ("key", 0x11, wi.KEYEVENTF_SCANCODE | wi.KEYEVENTF_KEYUP)]
    assert vin.held_keys == set()


def test_extended_keys_carry_the_extended_flag(made):
    vin, u = made
    vin.camera_up()                         # pageup = E0 49
    down, up = keys(u)
    assert down[1] == 0x49 and down[2] & wi.KEYEVENTF_EXTENDEDKEY
    assert up[2] & wi.KEYEVENTF_KEYUP and up[2] & wi.KEYEVENTF_EXTENDEDKEY


def test_held_releases_on_an_exception(made):
    vin, u = made
    with pytest.raises(RuntimeError):
        with vin.held("w", "shift"):
            assert vin.held_keys == {"w", "shift"}
            raise RuntimeError("walker blew up")
    assert vin.held_keys == set()
    ups = [k for k in keys(u) if k[2] & wi.KEYEVENTF_KEYUP]
    assert {k[1] for k in ups} == {0x11, 0x2A}


def test_another_window_in_front_refuses_and_sends_nothing(made):
    vin, u = made
    u.fg = OTHER
    with pytest.raises(api.GameNotFocused, match="Discord"):
        vin.press("w")
    assert u.sent == [] and vin.held_keys == set()
    assert vin.guard.refusals == 1
    with pytest.raises(api.GameNotFocused):
        vin.click(10, 10)
    with pytest.raises(api.GameNotFocused):
        vin.scroll(1)
    assert u.sent == []


def test_no_game_window_refuses(made):
    vin, u = made
    vin.guard.window = lambda: None
    with pytest.raises(api.GameNotFocused, match="not found"):
        vin.tap("e")
    # held()'s finally still sends the key-up (harmless, as on Linux); no down
    assert all(k[2] & wi.KEYEVENTF_KEYUP for k in keys(u)) and len(u.sent) == 1


def test_losing_the_foreground_mid_hold_lets_everything_go(made):
    """The stuck-key lesson: a refused press releases what is held, and the
    releases go out although the game no longer has the foreground."""
    vin, u = made
    with pytest.raises(api.GameNotFocused):
        with vin.held("w"):
            u.fg = OTHER                    # the owner alt-tabs mid-walk
            vin.press("shift")
    assert vin.held_keys == set()
    assert keys(u)[-1] == ("key", 0x11, wi.KEYEVENTF_SCANCODE | wi.KEYEVENTF_KEYUP)


def test_release_all_goes_out_without_the_foreground(made):
    vin, u = made
    vin.press("a")
    vin.mouse.button(wi.BTN_LEFT, 1)
    u.fg = OTHER
    u.sent.clear()
    vin.release_all()
    assert ("key", 0x1E, wi.KEYEVENTF_SCANCODE | wi.KEYEVENTF_KEYUP) in u.sent
    assert ("mouse", 0x0004, 0, 0, 0) in u.sent
    assert vin.held_keys == set() and vin.mouse.held == set()


def test_a_failed_multi_press_unwinds(made):
    vin, u = made
    with pytest.raises(KeyError):
        vin.press("w", "shfit")
    assert vin.held_keys == set()


def test_mouse_moves_are_absolute_over_the_virtual_desktop(made):
    vin, u = made
    vin.move_mouse(960, 540)
    _, flags, dx, dy, _ = u.sent[-1]
    assert flags == (wi.MOUSEEVENTF_MOVE | wi.MOUSEEVENTF_ABSOLUTE | wi.MOUSEEVENTF_VIRTUALDESK)
    assert dx == round((100 + 960) * 65535 / 3839)
    assert dy == round((50 + 540) * 65535 / 1079)
    vin.move_mouse(99999, -5)               # clamped into the client, as on Linux
    _, _, dx, dy, _ = u.sent[-1]
    assert dx == round((100 + 1919) * 65535 / 3839) and dy == round(50 * 65535 / 1079)


def test_click_is_down_then_up_and_drag_lets_go(made):
    vin, u = made
    vin.click(5, 5)
    assert [e[1] for e in u.sent if e[1] in (2, 4)] == [2, 4]
    u.sent.clear()
    assert vin.drag(0, 0, 100, 100, steps=2, hold_s=0) is True
    flags = [e[1] for e in u.sent]
    assert flags.count(2) == 1 and flags[-1] == 4


def test_a_drag_that_loses_the_foreground_still_lets_go(made):
    vin, u = made
    moves = {"n": 0}
    real = vin.mouse.move_to

    def move(x, y):
        moves["n"] += 1
        if moves["n"] == 3:
            u.fg = OTHER
        real(x, y)
    vin.mouse.move_to = move
    with pytest.raises(api.GameNotFocused):
        vin.drag(0, 0, 100, 100, steps=4, hold_s=0)
    assert u.sent[-1][1] == 4 and vin.mouse.held == set()


def test_wheel_down_is_negative_and_right_is_positive(made):
    vin, u = made
    vin.scroll(2)
    vin.scroll(-1)
    vin.scroll(1, horizontal=True)
    assert [(e[1], e[4]) for e in u.sent] == [
        (wi.MOUSEEVENTF_WHEEL, -120), (wi.MOUSEEVENTF_WHEEL, -120),
        (wi.MOUSEEVENTF_WHEEL, 120), (wi.MOUSEEVENTF_HWHEEL, 120)]


def test_uipi_blocking_is_an_error_not_silence(made):
    vin, u = made
    u.blocked = True
    with pytest.raises(OSError, match="administrator"):
        vin.tap("e")


def test_never_chat_is_still_locked_on(made):
    vin, u = made
    vin.in_game = True
    with pytest.raises(PermissionError):
        vin.type_text("hi")
    vin.in_game = False
    vin.type_text("Hi!")
    downs = [k[1] for k in keys(u) if not k[2] & wi.KEYEVENTF_KEYUP]
    assert downs == [0x2A, 0x23, 0x17, 0x2A, 0x02]
    assert vin.held_keys == set()


def test_focus_game_brings_the_window_forward_then_moves(made):
    vin, u = made
    u.fg = OTHER
    vin.focus_game()
    assert u.fg == GAME and u.sent[-1][0] == "mouse"


def test_sigbreak_joins_the_safety_signals():
    assert wi.WinInput.SAFETY_SIGNALS == ("SIGINT", "SIGTERM", "SIGBREAK")
    from hivemind.platform.input import VirtualInput
    assert VirtualInput.SAFETY_SIGNALS == ("SIGINT", "SIGTERM")


def test_a_click_hovers_with_a_one_pixel_wiggle_first(made):
    """Run 5: a bare warp then press missed Roblox's quest button."""
    vin, u = made
    moves = []
    real = vin.mouse.move_to
    vin.mouse.move_to = lambda x, y: moves.append((x, y)) or real(x, y)
    vin.click(83, 128)
    assert moves == [(83, 128), (84, 128), (83, 128)]
