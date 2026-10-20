"""The panic hotkey on Windows (platform/api PanicKey).

platform/panic.PanicWatcher's semantics: one key, watched from its own
thread outside the bot's main loop, fires `on_panic` on every press, never
dies of its callback, never takes the key from anything else, and says
plainly when it cannot watch (`available`, `reason`).

How: GetAsyncKeyState polled every 50 ms, fired on the down edge. It reads
the key wherever the foreground is, without a hook (no SetWindowsHookEx at
all: the plan, 4c) and without grabbing anything [verified: GetAsyncKeyState,
"the most significant bit ... is set if the key is currently down"]. It reads
0 while another desktop is active (UAC prompt, lock screen) or when UIPI
stops it reading the foreground thread (an elevated window in front)
[verified: its "Return value"]: a press there is missed, which `reason`
says. A 50 ms tap shorter than the poll can be missed [assumed: rare, a
human press lasts ~80-150 ms]; the least-significant "pressed since" bit is
documented as unreliable, so it is not used.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from . import _user32 as w

DOWN = 0x8000
POLL_S = 0.05
# Virtual-key codes [verified: learn.microsoft.com virtual-key-codes].
VK = {**{f"F{i}": 0x6F + i for i in range(1, 25)},         # VK_F1 0x70 .. VK_F24 0x87
      "PAUSE": 0x13, "SCROLLLOCK": 0x91, "INSERT": 0x2D, "ESC": 0x1B}


def key_code(name: str) -> int | None:
    """'F12' -> VK_F12 (0x7B); None for an unknown name."""
    return VK.get(str(name).upper())


@dataclass
class WinPanicWatcher:
    on_panic: Callable[[], None]
    key: str = "F12"
    poll_s: float = POLL_S
    user32: Any = None
    available: bool = field(init=False, default=False)
    reason: str = field(init=False, default="")
    fired: int = field(init=False, default=0)

    _stop: threading.Event = field(init=False, default_factory=threading.Event)

    def __post_init__(self) -> None:
        self._vk = key_code(self.key)
        if self._vk is None:
            self.reason = f"unknown key name {self.key!r}"

    def start(self) -> "WinPanicWatcher":
        if self._vk is None:
            return self
        try:
            self.user32 = self.user32 or w.dll("user32")
        except OSError as exc:
            self.reason = f"cannot read the keyboard: {exc}"
            return self
        self.available = True
        self.reason = (f"polling {self.key} every {self.poll_s * 1000:.0f} ms "
                       f"(missed while a UAC prompt or an elevated window is in front)")
        threading.Thread(target=self._loop, name="panic-key", daemon=True).start()
        return self

    def _loop(self) -> None:
        was_down = False
        while not self._stop.wait(self.poll_s):
            try:
                down = bool(self.user32.GetAsyncKeyState(self._vk) & DOWN)
            except Exception as exc:
                self.available = False
                self.reason = f"the keyboard poll failed: {exc}"
                return
            if down and not was_down:
                self.trigger()
            was_down = down

    def trigger(self) -> None:
        """Fire the callback. Public so the GUI's own panic button can use it."""
        self.fired += 1
        try:
            self.on_panic()
        except Exception:
            pass                           # the next press has to work too

    def stop(self) -> None:
        self._stop.set()
        self.available = False

    def __enter__(self): return self.start()
    def __exit__(self, *exc): self.stop()
