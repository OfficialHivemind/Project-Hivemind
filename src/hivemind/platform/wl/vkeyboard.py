"""Virtual keyboard: press and release as independent events.

Keycodes are EVDEV codes. Wayland's wl_keyboard (and therefore this protocol)
carries evdev codes; the compositor adds the XKB offset of 8 itself. Sending
XKB codes here produces the wrong glyph, which is a classic and confusing bug.
"""
from __future__ import annotations

import time

from .connection import WlConnection
from .keymap import XKB_KEYMAP_FORMAT_TEXT_V1, build_keymap_fd

KEY_RELEASED, KEY_PRESSED = 0, 1

# evdev codes (linux/input-event-codes.h) for everything Bee Swarm needs.
# Letters are generated from the three keyboard rows rather than written out as
# 26 separate constants: evdev numbers the keys in physical order, so "qwertyuiop"
# is exactly 16..25. Deriving them means a typo is impossible, and it documents
# where the numbers come from. (Cross-checks against the hand-written values this
# replaced: w=17, a=30, s=31, d=32, e=18, r=19, o=24 -- all agree.)
_ROWS = {"qwertyuiop": 16, "asdfghjkl": 30, "zxcvbnm": 44}

KEYS: dict[str, int] = {
    **{ch: base + i for row, base in _ROWS.items() for i, ch in enumerate(row)},
    "space": 57, "escape": 1, "enter": 28, "shift": 42, "ctrl": 29, "tab": 15,
    # KEY_LEFTALT, for one thing only: letting go of an Alt that Roblox still
    # believes is down (act/hotbar.release_alt) -- Alt+1 is its Capture.
    "alt": 56,
    "rightalt": 100,                    # KEY_RIGHTALT, the same reason
    "backspace": 14,
    "comma": 51, "period": 52, "slash": 53, "minus": 12, "equal": 13,
    "leftbracket": 26, "rightbracket": 27, "semicolon": 39, "apostrophe": 40,
    "grave": 41, "backslash": 43,
    "pageup": 104, "pagedown": 109, "home": 102, "end": 107,
    "up": 103, "down": 108, "left": 105, "right": 106,
    **{str(n): 1 + n for n in range(1, 10)},   # "1"->2 ... "9"->10
    "0": 11,
    # function keys, used for isolation probes
    **{f"f{i}": 58 + i for i in range(1, 11)},   # f1->59 ... f10->68
}

# Characters that a plain key press produces, and those needing shift. Used by
# VirtualKeyboard.type_text so callers can pass ordinary strings.
_SHIFTED = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
            "&": "7", "*": "8", "(": "9", ")": "0", "_": "minus", "+": "equal",
            ":": "semicolon", "?": "slash", "~": "grave", "|": "backslash",
            '"': "apostrophe", "<": "comma", ">": "period"}
_PLAIN = {" ": "space", ",": "comma", ".": "period", "/": "slash",
          "-": "minus", "=": "equal", ";": "semicolon", "'": "apostrophe",
          "`": "grave", "\\": "backslash", "[": "leftbracket",
          "]": "rightbracket", "\n": "enter", "\t": "tab"}


class VirtualKeyboard:
    def __init__(self, conn: WlConnection, layout: str = "us"):
        conn.require("zwp_virtual_keyboard_manager_v1", "wl_seat")
        self._conn = conn
        self._kb = conn.globals["zwp_virtual_keyboard_manager_v1"].create_virtual_keyboard(
            conn.globals["wl_seat"]
        )
        fd, size = build_keymap_fd(layout)
        self._kb.keymap(XKB_KEYMAP_FORMAT_TEXT_V1, fd, size)
        conn.roundtrip()
        self._t0 = time.monotonic()
        self.held: set[str] = set()

    def _now_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def _send(self, name: str, state: int) -> None:
        code = KEYS.get(name.lower())
        if code is None:
            raise KeyError(f"unknown key {name!r}")
        self._kb.key(self._now_ms(), code, state)
        self._conn.flush()

    def press(self, name: str) -> None:
        # ORDER MATTERS. Record the key BEFORE it physically goes down.
        #
        # release_all() iterates `held`, and two other threads can run between
        # any two bytecodes here: the PanicWatcher (bootstrap wires it to
        # release_all) and the SIGINT/SIGTERM handler. A key that is down but
        # not yet recorded is invisible to every release path, so it stays
        # down forever. Recording a key that never went down is harmless --
        # releasing an unpressed key is a no-op to the compositor -- so the
        # asymmetry decides the order.
        key = name.lower()
        if key not in KEYS:
            raise KeyError(f"unknown key {name!r}")
        self.held.add(key)
        # A failure in _send leaves the key in `held` on purpose: the event may
        # already have been marshalled, and an extra release costs nothing.
        self._send(name, KEY_PRESSED)

    def release(self, name: str) -> None:
        self._send(name, KEY_RELEASED)
        self.held.discard(name.lower())

    def release_all(self) -> None:
        for name in list(self.held):
            try:
                self.release(name)
            except Exception:
                pass

    def tap(self, name: str, hold: float = 0.02) -> None:
        self.press(name)
        time.sleep(hold)
        self.release(name)

    def type_text(self, text: str, delay: float = 0.04) -> None:
        """Type a string. Used for the Roblox app's search box, not for chat.

        Deliberately has no chat path: the agent never types to other players.
        """
        for ch in text:
            if ch in _PLAIN:
                self.tap(_PLAIN[ch])
            elif ch in _SHIFTED:
                self.press("shift")
                self.tap(_SHIFTED[ch])
                self.release("shift")
            elif ch.isupper():
                self.press("shift")
                self.tap(ch.lower())
                self.release("shift")
            elif ch.lower() in KEYS:
                self.tap(ch.lower())
            else:
                raise KeyError(f"cannot type {ch!r}")
            time.sleep(delay)
