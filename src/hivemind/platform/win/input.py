"""Keyboard and mouse into the Roblox window on Windows (platform/api Input).

WinInput IS platform/input.VirtualInput: the same class body -- press-all-or-
none, release-every-key, held() with the press inside the try, the four
stuck-key guarantees, drag/drag_seek letting the button go on every way out,
the locked never-chat rule -- over SendInput backends instead of the Wayland
virtual keyboard and pointer. Only what differs lives here.

WHAT DIFFERS, AND WHY:
  * SendInput goes to the FOREGROUND window, whatever it is [verified:
    "You can't simulate keyboard input with PostMessage"; Natro: ControlSend
    does not reach Roblox]. On Linux the game has its own screen; here a key
    sent while the owner's Discord has the foreground types into Discord. So
    every press, button-down, move and wheel notch first checks that the
    foreground window IS the game's, and otherwise refuses: everything held
    is let go, and GameNotFocused says what had the foreground instead.
  * Releases are NEVER refused. Injected key state is global [verified:
    SendInput "does not reset the keyboard's current state"]: a W the bot
    put down stays down for whichever window has the foreground until a
    key-up is sent, so a release must go out even (especially) when the game
    lost the foreground. This is the stuck-modifier lesson (the stuck Alt of
    2026-10, a Capture on every "1") carried over: the way out is always open.
  * Keys are sent as scan codes (KEYEVENTF_SCANCODE [verified]), so the
    owner's keyboard layout cannot turn "w" into "z" [verified: scan codes are
    layout-independent]. For every non-extended key the Set-1 make code equals
    the evdev code the Linux KEYS use [verified: Microsoft's scan code table
    against linux/input-event-codes.h]; the extended keys (arrows, PageUp/Down,
    Home/End, right Alt) carry the 0xE0 prefix as KEYEVENTF_EXTENDEDKEY.
  * The mouse is absolute over the virtual desktop, normalised 0..65535
    (MOUSEEVENTF_ABSOLUTE|VIRTUALDESK [verified]); a client pixel goes through
    ClientToScreen first. Exact-pixel landing after rounding is [assumed].
"""
from __future__ import annotations

import ctypes
import time
from typing import Callable

from ..api import GameNotFocused
from ..input import VirtualInput
from . import _user32 as w

KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0001, 0x0002, 0x0008
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
WHEEL_DELTA = 120                     # one notch; positive = away from the user (up) [verified]

# The evdev button codes VirtualInput passes (wl/vpointer), to SendInput's
# down/up flags [verified: MOUSEINPUT dwFlags].
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
BUTTONS = {BTN_LEFT: (0x0002, 0x0004), BTN_RIGHT: (0x0008, 0x0010), BTN_MIDDLE: (0x0020, 0x0040)}

EXTENDED = 0xE000
_ROWS = {"qwertyuiop": 0x10, "asdfghjkl": 0x1E, "zxcvbnm": 0x2C}
# The same names as wl/vkeyboard.KEYS, as Set-1 make codes [verified:
# learn.microsoft.com about-keyboard-input, "Scan Codes"].
SCANCODES: dict[str, int] = {
    **{ch: base + i for row, base in _ROWS.items() for i, ch in enumerate(row)},
    "space": 0x39, "escape": 0x01, "enter": 0x1C, "shift": 0x2A, "ctrl": 0x1D, "tab": 0x0F,
    "alt": 0x38, "rightalt": EXTENDED | 0x38, "backspace": 0x0E,
    "comma": 0x33, "period": 0x34, "slash": 0x35, "minus": 0x0C, "equal": 0x0D,
    "leftbracket": 0x1A, "rightbracket": 0x1B, "semicolon": 0x27, "apostrophe": 0x28,
    "grave": 0x29, "backslash": 0x2B,
    "pageup": EXTENDED | 0x49, "pagedown": EXTENDED | 0x51,
    "home": EXTENDED | 0x47, "end": EXTENDED | 0x4F,
    "up": EXTENDED | 0x48, "down": EXTENDED | 0x50,
    "left": EXTENDED | 0x4B, "right": EXTENDED | 0x4D,
    **{str(n): 1 + n for n in range(1, 10)}, "0": 0x0B,
    **{f"f{i}": 0x3A + i for i in range(1, 11)},
}

# wl/vkeyboard's type_text tables (that module imports pywayland, so they are
# copied; tests/unit/test_win_input.py checks they still match).
_SHIFTED = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
            "&": "7", "*": "8", "(": "9", ")": "0", "_": "minus", "+": "equal",
            ":": "semicolon", "?": "slash", "~": "grave", "|": "backslash",
            '"': "apostrophe", "<": "comma", ">": "period"}
_PLAIN = {" ": "space", ",": "comma", ".": "period", "/": "slash",
          "-": "minus", "=": "equal", ";": "semicolon", "'": "apostrophe",
          "`": "grave", "\\": "backslash", "[": "leftbracket",
          "]": "rightbracket", "\n": "enter", "\t": "tab"}


def send(user32, events: list) -> None:
    """SendInput, all or an error. A short count is UIPI (the game runs at a
    higher integrity level, e.g. as administrator) or input blocked by
    another thread; Windows does not say which [verified]."""
    arr = (w.INPUT * len(events))(*events)
    n = user32.SendInput(len(events), arr, ctypes.sizeof(w.INPUT))
    if n != len(events):
        raise OSError(f"SendInput inserted {n} of {len(events)} events: input is "
                      f"blocked (is Roblox running as administrator? UIPI drops it)")


def key_event(code: int, up: bool) -> w.INPUT:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    if code & 0xFF00:
        flags |= KEYEVENTF_EXTENDEDKEY
    ev = w.INPUT(type=w.INPUT_KEYBOARD)
    ev.ki = w.KEYBDINPUT(wVk=0, wScan=code & 0xFF, dwFlags=flags)
    return ev


def mouse_event(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> w.INPUT:
    ev = w.INPUT(type=w.INPUT_MOUSE)
    ev.mi = w.MOUSEINPUT(dx=dx, dy=dy, mouseData=data & 0xFFFFFFFF, dwFlags=flags)
    return ev


class ForegroundGuard:
    """Send only while the game's window has the foreground."""

    def __init__(self, window: Callable[[], int | None], user32, on_lost: Callable[[], None]):
        self.window, self.user32, self.on_lost = window, user32, on_lost
        self.refusals = 0
        self.last_refusal = ""

    def hwnd(self) -> int:
        """The game's window, when it has the foreground; else refuse."""
        hwnd = self.window()
        fg = w.foreground(self.user32)
        if hwnd and fg == hwnd:
            return hwnd
        if not hwnd:
            why = "the Roblox window was not found"
        else:
            title = w.window_title(self.user32, fg) if fg else ""
            why = (f"the Roblox window is not in the foreground "
                   f"({repr(title) if title else 'no window'} is)")
        self.refusals += 1
        self.last_refusal = why
        self.on_lost()                     # nothing stays down in someone else's window
        raise GameNotFocused(f"input refused: {why}")


class WinKeyboard:
    """wl/vkeyboard.VirtualKeyboard's shape over SendInput scan codes."""

    def __init__(self, guard: ForegroundGuard, user32):
        self.guard, self.user32 = guard, user32
        self.held: set[str] = set()

    def _send(self, name: str, up: bool) -> None:
        code = SCANCODES.get(name.lower())
        if code is None:
            raise KeyError(f"unknown key {name!r}")
        send(self.user32, [key_event(code, up)])

    def press(self, name: str) -> None:
        # The Linux order (vkeyboard.press): recorded BEFORE it goes down, so
        # the panic key and the signal handlers can always see it.
        key = name.lower()
        if key not in SCANCODES:
            raise KeyError(f"unknown key {name!r}")
        self.guard.hwnd()
        self.held.add(key)
        self._send(key, up=False)

    def release(self, name: str) -> None:
        self._send(name, up=True)          # never guarded: see the module docstring
        self.held.discard(name.lower())

    def release_all(self) -> None:
        for name in list(self.held):
            try:
                self.release(name)
            except Exception:
                pass

    def tap(self, name: str, hold: float = 0.02) -> None:
        self.press(name)
        try:
            time.sleep(hold)
        finally:
            self.release(name)

    def type_text(self, text: str, delay: float = 0.04) -> None:
        """The Roblox app's search box only; VirtualInput.type_text refuses in game."""
        for ch in text:
            if ch in _PLAIN:
                self.tap(_PLAIN[ch])
            elif ch in _SHIFTED or ch.isupper():
                self.press("shift")
                try:
                    self.tap(_SHIFTED.get(ch, ch.lower()))
                finally:
                    self.release("shift")
            elif ch.lower() in SCANCODES:
                self.tap(ch.lower())
            else:
                raise KeyError(f"cannot type {ch!r}")
            time.sleep(delay)


class WinPointer:
    """wl/vpointer.VirtualPointer's shape: absolute moves in client pixels."""

    def __init__(self, guard: ForegroundGuard, user32, width: int, height: int):
        self.guard, self.user32 = guard, user32
        self.width, self.height = width, height
        self.held: set[int] = set()

    def move_to(self, x: float, y: float) -> None:
        hwnd = self.guard.hwnd()
        x = max(0, min(self.width - 1, int(x)))
        y = max(0, min(self.height - 1, int(y)))
        ox, oy = w.client_origin(self.user32, hwnd)
        vx, vy, vw, vh = w.virtual_screen(self.user32)
        nx = round((ox + x - vx) * 65535 / max(1, vw - 1))
        ny = round((oy + y - vy) * 65535 / max(1, vh - 1))
        send(self.user32, [mouse_event(
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny)])

    def button(self, btn: int, state: int) -> None:
        down, up = BUTTONS[btn]
        if state:                          # downs are guarded, ups never
            self.guard.hwnd()
            self.held.add(btn)
        send(self.user32, [mouse_event(down if state else up)])
        if not state:
            self.held.discard(btn)

    def click(self, x: float | None = None, y: float | None = None,
              btn: int = BTN_LEFT, hold_ms: int = 40) -> None:
        if x is not None and y is not None:
            # A HOVER BEFORE THE CLICK. Run 5's quest click at (83, 128) changed
            # 6% of the screen although the button sits exactly there in a
            # Windows frame (IoU 0.95, probe_capture_wgc.png). Roblox's buttons
            # act on a press over a hovered button, and one warp may land
            # between its frames; a 1-px wiggle makes it see the pointer
            # arrive [assumed: not measured on Windows yet].
            self.move_to(x, y)
            time.sleep(0.03)
            self.move_to(x + 1, y)
            time.sleep(0.03)
            self.move_to(x, y)
            time.sleep(0.03)
        self.button(btn, 1)
        try:
            time.sleep(hold_ms / 1000)
        finally:
            self.button(btn, 0)

    def scroll(self, steps: int = 1, horizontal: bool = False) -> None:
        """Positive is down (or right), as on Linux. Windows' vertical wheel is
        positive AWAY from the user, i.e. up, so it is negated; the horizontal
        one is positive to the right [verified: MOUSEINPUT mouseData]."""
        direction = 1 if steps >= 0 else -1
        flag = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
        data = direction * WHEEL_DELTA * (1 if horizontal else -1)
        for _ in range(abs(steps)):
            self.guard.hwnd()
            send(self.user32, [mouse_event(flag, data=data)])
            time.sleep(0.05)

    def release_all(self) -> None:
        for b in list(self.held):
            try:
                self.button(b, 0)
            except Exception:
                pass


class WinInput(VirtualInput):
    """platform/api Input on Windows. `window()` gives the game's HWND (or
    None); win/session will provide it (Session.game_hwnd)."""

    SAFETY_SIGNALS = ("SIGINT", "SIGTERM", "SIGBREAK")

    def __init__(self, window: Callable[[], int | None],
                 width: int = 1920, height: int = 1080, user32=None):
        if user32 is None:
            user32 = w.dll("user32")
            w.dpi_aware(user32)            # client pixels = captured pixels
        self.user32 = user32
        self.guard = ForegroundGuard(window, user32, self.release_all)
        self.kb = WinKeyboard(self.guard, user32)
        self.mouse = WinPointer(self.guard, user32, width, height)
        self._install_safety()

    def focus_game(self, x: int = 960, y: int = 540) -> None:
        """The game in the foreground and the cursor over it. Windows may
        refuse SetForegroundWindow while the owner works in another window
        [verified: its foreground rules]; the guarded move then raises
        GameNotFocused rather than send anything elsewhere."""
        hwnd = self.guard.window()
        if hwnd and w.foreground(self.user32) != hwnd:
            self.user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)
        self.mouse.move_to(x, y)
        time.sleep(0.3)

    def close(self) -> None:
        self.release_all()                 # no connection to close
