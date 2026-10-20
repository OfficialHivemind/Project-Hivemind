"""Watching WHICH WAY the owner walked, so a walk can be learned.

THE GAP THIS FILLS. `brain/explore.watch` already records WHERE he went -- it
recognises places and notes which ones pay. What it cannot see is how he got
from one to the next, and that is the half the bot actually needs. MEASURED,
from his first mapping session: eight places found, seven of them paying, and
not one edge between them. The map says a field exists and says nothing about
reaching it.

His own words for what he wanted: "what if u put a mode in where it learns how
i play, not following what i do exactly but almost sorta maps it out like fake
nodes ect". The nodes exist now. This is what draws the lines.

WHY EVDEV RATHER THAN THE COMPOSITOR. The game runs inside a nested Hyprland
and he types into it directly; nothing in that path reports his keys back to
us. `platform/panic.py` already reads `/dev/input` for the F12 panic key and
that works on this machine -- three devices report it, one of them a mouse --
so the same approach is used here rather than a second, unproven one.

THE WHITELIST IS THE POINT, AND IT IS THE SAFETY BOUNDARY.

Reading a keyboard device sees every key on it, including keys pressed in other
windows. So this translates SEVEN codes and discards everything else before it
reaches a callback: w, a, s, d, space, and the two camera keys. There is no
path in this file by which any other key is reported, stored or written down --
not letters, not numbers, not modifiers. `test_keywatch.py` asserts exactly
that by feeding it a typed sentence and requiring silence.

The device is NOT grabbed, for the same reason the panic watcher does not grab
it: an exclusive grab would take his movement keys away from the game he is
playing, which would be an absurd way to learn how he plays.
"""
from __future__ import annotations

import select
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

try:
    import evdev
    from evdev import ecodes
except ImportError:                                   # pragma: no cover
    evdev = None
    ecodes = None

KEY_UP, KEY_DOWN, KEY_REPEAT = 0, 1, 2

# The whole vocabulary. Names on the right are the ones `platform.input` and
# `act/routes` already use, so what is recorded here can be replayed unchanged.
MOVEMENT = {
    "KEY_W": "w",
    "KEY_A": "a",
    "KEY_S": "s",
    "KEY_D": "d",
    "KEY_SPACE": "space",
    "KEY_COMMA": "comma",       # camera left
    "KEY_DOT": "period",        # camera right
}


def _codes() -> dict[int, str]:
    """evdev code -> our key name, for the seven keys we are allowed to see."""
    if ecodes is None:
        return {}
    out = {}
    for name, ours in MOVEMENT.items():
        code = getattr(ecodes, name, None)
        if code is not None:
            out[int(code)] = ours
    return out


@dataclass
class MoveWatcher:
    """Reports the owner's movement keys, and nothing else.

    `on_key(name, down, at)` is called once per real transition -- autorepeat
    is swallowed, because holding W produces a storm of repeats and every one
    of them would otherwise look like a fresh keypress.
    """

    on_key: Callable[[str, bool, float], None]
    clock: Callable[[], float] = time.monotonic
    available: bool = field(init=False, default=False)
    reason: str = field(init=False, default="")
    seen: int = field(init=False, default=0)

    _stop: threading.Event = field(init=False, default_factory=threading.Event)
    _devices: list = field(init=False, default_factory=list)
    _held: set = field(init=False, default_factory=set)

    def __post_init__(self) -> None:
        self._map = _codes()
        if evdev is None:
            self.reason = "python-evdev is not installed"

    # ---- the only place a key becomes a name ------------------------------
    def handle(self, code: int, value: int) -> bool:
        """One raw event. True if it was a movement key we reported.

        Separated from the read loop so the whitelist can be tested without a
        keyboard, which is how `test_keywatch` proves that typing a sentence
        produces nothing.
        """
        name = self._map.get(int(code))
        if name is None:
            return False                       # not ours: never leaves here
        if value == KEY_REPEAT:
            return False                       # a held key, not a new press
        down = value == KEY_DOWN
        if down and name in self._held:
            return False
        if not down and name not in self._held:
            return False
        if down:
            self._held.add(name)
        else:
            self._held.discard(name)
        self.seen += 1
        self.on_key(name, down, self.clock())
        return True

    @property
    def held(self) -> frozenset:
        return frozenset(self._held)

    # ---- devices ----------------------------------------------------------
    def find_devices(self, paths: Iterable[str] | None = None) -> list:
        """Keyboards that can produce W -- i.e. ones somebody could walk with."""
        if evdev is None or not self._map:
            return []
        want = getattr(ecodes, "KEY_W", None)
        found, denied = [], 0
        for path in (paths if paths is not None else evdev.list_devices()):
            try:
                device = evdev.InputDevice(path)
            except (PermissionError, OSError):
                denied += 1
                continue
            try:
                keys = device.capabilities().get(ecodes.EV_KEY, [])
            except OSError:
                device.close()
                continue
            if want in keys:
                found.append(device)
            else:
                device.close()
        if not found and denied:
            self.reason = (f"no readable keyboard ({denied} devices refused). "
                           "Add yourself to the 'input' group: "
                           "sudo usermod -aG input $USER")
        elif not found:
            self.reason = "no keyboard found"
        return found

    def start(self, paths: Iterable[str] | None = None) -> "MoveWatcher":
        self._devices = self.find_devices(paths)
        self.available = bool(self._devices)
        if self.available:
            self.reason = (f"learning from {len(self._devices)} keyboard(s); "
                           f"only {', '.join(sorted(set(MOVEMENT.values())))}")
            threading.Thread(target=self._loop, daemon=True,
                             name="hivemind-keywatch").start()
        return self

    def _loop(self) -> None:
        by_fd = {device.fd: device for device in self._devices}
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select(list(by_fd), [], [], 0.4)
            except (OSError, ValueError):
                return
            for fd in ready:
                device = by_fd.get(fd)
                if device is None:
                    continue
                try:
                    for event in device.read():
                        if event.type == ecodes.EV_KEY:
                            self.handle(event.code, event.value)
                except OSError:
                    by_fd.pop(fd, None)
            if not by_fd:
                return

    def stop(self) -> None:
        self._stop.set()
        for device in self._devices:
            try:
                device.close()
            except OSError:
                pass
        self._devices = []
        self.available = False
