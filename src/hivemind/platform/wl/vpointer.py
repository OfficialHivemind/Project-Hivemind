"""Virtual pointer over zwlr_virtual_pointer_v1.

Unlike `wlrctl pointer move`, which is relative-only and needs the
slam-into-the-corner trick to fake absolute positioning, this protocol exposes
motion_absolute directly. It also gives real button press/release as separate
events, which `wlrctl` cannot do -- that limitation is why the old bash macro
degraded continuous auto-dig into 3.3 clicks per second of spam.
"""
from __future__ import annotations

import time

from .connection import WlConnection

BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
RELEASED, PRESSED = 0, 1

# wl_pointer enums, as referenced by the wlr-virtual-pointer protocol
AXIS_VERTICAL, AXIS_HORIZONTAL = 0, 1
AXIS_SOURCE_WHEEL = 0
WHEEL_STEP = 15.0        # conventional value one physical wheel notch reports


class VirtualPointer:
    def __init__(self, conn: WlConnection, width: int, height: int):
        conn.require("zwlr_virtual_pointer_manager_v1")
        self._conn = conn
        mgr = conn.globals["zwlr_virtual_pointer_manager_v1"]
        self._p = mgr.create_virtual_pointer(conn.globals.get("wl_seat"))
        self.width, self.height = width, height
        self._t0 = time.monotonic()
        self.held: set[int] = set()

    def _ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def move_to(self, x: float, y: float) -> None:
        """Absolute move, in pixels of the output."""
        x = max(0, min(self.width - 1, int(x)))
        y = max(0, min(self.height - 1, int(y)))
        self._p.motion_absolute(self._ms(), x, y, self.width, self.height)
        self._p.frame()
        self._conn.flush()

    def button(self, btn: int, state: int) -> None:
        # Same ordering rule as VirtualKeyboard.press: record before the button
        # goes down, forget only after it is confirmed up. A panic or a signal
        # landing between the flush and the bookkeeping must never leave a
        # button held with nothing tracking it.
        if state:
            self.held.add(btn)
        self._p.button(self._ms(), btn, state)
        self._p.frame()
        self._conn.flush()
        if not state:
            self.held.discard(btn)

    def click(self, x: float | None = None, y: float | None = None,
              btn: int = BTN_LEFT, hold_ms: int = 40) -> None:
        if x is not None and y is not None:
            self.move_to(x, y)
            time.sleep(0.02)
        self.button(btn, PRESSED)
        time.sleep(hold_ms / 1000)
        self.button(btn, RELEASED)

    def scroll(self, steps: int = 1, horizontal: bool = False) -> None:
        """Wheel scroll. Positive is down (or right). One step = one notch.

        Needed for the Roblox app, where the Servers section of a game page sits
        below the fold. MEASURED: three PageDown presses on the app's More page
        produced byte-identical frames, so the keyboard hint bar's "Scroll Down"
        binding does not drive every view and a real wheel event is worth having.

        Sent as axis_source + axis_discrete + axis + frame: compositors expect
        the discrete notch count alongside the continuous value, and the 15.0
        magnitude is the conventional per-notch value a physical wheel reports.
        """
        axis = AXIS_HORIZONTAL if horizontal else AXIS_VERTICAL
        direction = 1 if steps >= 0 else -1
        for _ in range(abs(steps)):
            now = self._ms()
            self._p.axis_source(AXIS_SOURCE_WHEEL)
            self._p.axis_discrete(now, axis, float(direction * WHEEL_STEP), direction)
            self._p.axis(now, axis, float(direction * WHEEL_STEP))
            self._p.frame()
            self._conn.flush()
            time.sleep(0.05)

    def release_all(self) -> None:
        for b in list(self.held):
            try:
                self.button(b, RELEASED)
            except Exception:
                pass
