"""The panic hotkey: stop everything, from outside everything.

The bot holds keys down. That is the whole point of the persistent virtual
keyboard, and it is also the failure mode that matters most: if the process
wedges mid-walk, or the nested compositor stops responding, the character runs
into a wall indefinitely with W held.

Every other safety layer in this project lives INSIDE the thing that might be
stuck -- the context manager, `release_all()`, the atexit hook, the signal
handlers. All four are good and none of them help if the process is alive but
not making progress.

So this one reads the keyboard directly from `/dev/input` via evdev, in its own
thread, below the compositor entirely. It does not care whether Hyprland is
responding, whether Qt's event loop is running, or whether the bot's main loop
is blocked. If the kernel saw the key, this sees the key.

Two deliberate choices:

  * the device is NOT grabbed. Reading without an exclusive grab means the key
    still reaches whatever else wants it, so binding F12 does not steal F12 from
    your other applications. A panic button that breaks your keyboard would be
    its own kind of hazard.

  * every keyboard is watched, not just one. Which device a keypress arrives on
    depends on the hardware, and on this machine three separate devices report
    F12 -- including a mouse that presents a keyboard interface.

Requires membership of the `input` group. When that is missing the watcher says
so plainly and reports `available == False`, rather than appearing to work.
"""
from __future__ import annotations

import select
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable

try:
    import evdev
    from evdev import ecodes
except ImportError:                                   # pragma: no cover
    evdev = None
    ecodes = None

KEY_DOWN = 1


def key_code(name: str) -> int | None:
    """'F12' -> ecodes.KEY_F12. Returns None for an unknown name."""
    if ecodes is None:
        return None
    return getattr(ecodes, f"KEY_{name.upper()}", None)


@dataclass
class PanicWatcher:
    """Watches every keyboard for one key and fires a callback when it is pressed."""

    on_panic: Callable[[], None]
    key: str = "F12"
    available: bool = field(init=False, default=False)
    reason: str = field(init=False, default="")
    fired: int = field(init=False, default=0)

    _stop: threading.Event = field(init=False, default_factory=threading.Event)
    _devices: list = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self._code = key_code(self.key)
        if evdev is None:
            self.reason = "python-evdev is not installed"
        elif self._code is None:
            self.reason = f"unknown key name {self.key!r}"

    # ---- device discovery -------------------------------------------------
    def find_devices(self, paths: Iterable[str] | None = None) -> list:
        """Keyboards that can actually produce the panic key."""
        if evdev is None or self._code is None:
            return []
        found = []
        denied = 0
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
            if self._code in keys:
                found.append(device)
            else:
                device.close()
        if not found and denied:
            self.reason = (f"no readable keyboard ({denied} devices refused). "
                           "Add yourself to the 'input' group: "
                           "sudo usermod -aG input $USER")
        elif not found:
            self.reason = f"no keyboard reports {self.key}"
        return found

    # ---- lifecycle --------------------------------------------------------
    def start(self, paths: Iterable[str] | None = None) -> "PanicWatcher":
        self._devices = self.find_devices(paths)
        self.available = bool(self._devices)
        if self.available:
            self.reason = f"watching {len(self._devices)} keyboard(s) for {self.key}"
            threading.Thread(target=self._loop, daemon=True).start()
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
                        if (event.type == ecodes.EV_KEY
                                and event.code == self._code
                                and event.value == KEY_DOWN):
                            self.trigger()
                except OSError:
                    # device unplugged mid-session; drop it and keep watching
                    by_fd.pop(fd, None)
                    if not by_fd:
                        self.available = False
                        self.reason = "all watched keyboards disappeared"
                        return

    def trigger(self) -> None:
        """Fire the callback. Public so the GUI's own panic button can use it."""
        self.fired += 1
        try:
            self.on_panic()
        except Exception:
            # A failing callback must not kill the watcher: the next press has
            # to work too, and this is the last line of defence.
            pass

    def stop(self) -> None:
        self._stop.set()
        for device in self._devices:
            try:
                device.close()
            except OSError:
                pass
        self._devices = []
        self.available = False

    def __enter__(self): return self.start()
    def __exit__(self, *exc): self.stop()
