"""Persistent Wayland client connection.

One connection, held open for the process lifetime. This is the whole point:
a virtual keyboard object lives as long as its client, so a key held here stays
held across as many observation frames as we like. One-shot tools like `wtype`
cannot do this -- the compositor destroys their keyboard on exit and releases
every key.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from pywayland.client import Display

from .gen.wayland import WlSeat, WlShm
from .gen.virtual_keyboard_unstable_v1 import ZwpVirtualKeyboardManagerV1
from .gen.wlr_virtual_pointer_unstable_v1 import ZwlrVirtualPointerManagerV1
from .gen.wlr_screencopy_unstable_v1 import ZwlrScreencopyManagerV1
from .gen.wayland import WlOutput

WANTED = {
    "wl_seat": WlSeat,
    "wl_shm": WlShm,
    "wl_output": WlOutput,
    "zwp_virtual_keyboard_manager_v1": ZwpVirtualKeyboardManagerV1,
    "zwlr_virtual_pointer_manager_v1": ZwlrVirtualPointerManagerV1,
    "zwlr_screencopy_manager_v1": ZwlrScreencopyManagerV1,
}


class MissingProtocol(RuntimeError):
    """The compositor does not advertise something we require.

    On KWin this is expected and total -- it advertises none of them, which is
    why the game runs inside a nested Hyprland.
    """


@dataclass
class WlConnection:
    socket: str | None = None          # WAYLAND_DISPLAY, e.g. "wayland-1"
    display: Display | None = None
    globals: dict[str, object] = field(default_factory=dict)
    outputs: list[object] = field(default_factory=list)

    def connect(self) -> "WlConnection":
        self.display = Display(self.socket) if self.socket else Display()
        self.display.connect()
        registry = self.display.get_registry()
        registry.dispatcher["global"] = self._on_global
        self.display.roundtrip()   # populate globals
        self.display.roundtrip()   # let output metadata land
        return self

    def _on_global(self, registry, name, interface, version):
        iface = WANTED.get(interface)
        if iface is None:
            return
        bound = registry.bind(name, iface, min(version, iface.version))
        if interface == "wl_output":
            self.outputs.append(bound)
        else:
            self.globals[interface] = bound

    def require(self, *interfaces: str) -> None:
        missing = [i for i in interfaces if i not in self.globals]
        if missing:
            raise MissingProtocol(
                "compositor does not advertise: " + ", ".join(missing)
                + "\nAre you connected to the nested Hyprland rather than KWin?"
            )

    def flush(self) -> None:
        if self.display:
            self.display.flush()

    def roundtrip(self) -> None:
        if self.display:
            self.display.roundtrip()

    def close(self) -> None:
        if self.display:
            self.display.disconnect()
            self.display = None

    def __enter__(self): return self.connect()
    def __exit__(self, *exc): self.close()


def nested_socket() -> str | None:
    """WAYLAND_DISPLAY of the nested compositor, if we were told about one."""
    return os.environ.get("HIVEMIND_WAYLAND_DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
