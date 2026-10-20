"""This machine's implementation of the platform seam (platform/api, RL6).

act/bootstrap builds the session, the capture, the input and the panic key
through these factories and nothing else, so a Windows port adds a branch
here instead of touching the start code (docs/pending/windows-port.md,
phase 2 step 5). On Linux each factory is exactly the constructor call
bootstrap made before.

Windows (phase 3): everything is platform/win's -- the session (the Roblox
window on the desktop), capture, input, panic key, memory, game guard,
processes and the kept record. Capture and input take the game's window from
the session (`session.game_hwnd`), which is also what `connect` hands
make_capture.

LIGHT TO IMPORT (RL6 phase 3 wiring). run_farm, brain/vlm, brain/farm,
act/startcheck and the scripts take `memory`, `gameguard`, `files` and `kept`
from here, so on Linux this imports only those (the very same module objects
as before); the Wayland classes the factories build are imported when a
factory is called, as bootstrap does, so a reader of `current.memory` never
pulls in pywayland or evdev.
"""
from __future__ import annotations

import sys

WINDOWS = sys.platform == "win32"

if sys.platform.startswith("linux"):
    from . import session as kept            # KeptGame: kept_session_why, keep_session, forget_session
    from .. import files                     # Processes
    from . import gameguard, memory          # GameGuard, Memory
elif WINDOWS:
    from .win import files, gameguard, memory
    from .win import session as kept         # KeptGame
    from .win.capture import WinCapture
    from .win.input import WinInput
    from .win.panic import WinPanicWatcher
    from .win.session import WinSession
else:
    raise ImportError(f"no Hivemind platform implementation for {sys.platform} "
                      f"(RL6, docs/pending/windows-port.md)")

from .. import datapaths as paths            # noqa: E402  Paths

__all__ = ["kept", "paths", "files", "gameguard", "memory", "make_session",
           "attach_session", "connect", "make_capture", "make_input", "make_panic"]


def _session_class():
    """Linux: the `platform.compositor` setting's session -- the nested
    Hyprland (the default) or a headless labwc (wlr_session, RL1b)."""
    from ..world.settings import Settings
    if Settings().get("platform.compositor", "hyprland") == "labwc":
        from .wlr_session import WlrSession
        return WlrSession
    from .session import Session
    return Session


def make_session(width: int = 1920, height: int = 1080):
    """A GameSession, not started."""
    if WINDOWS:
        return WinSession(width=width, height=height)
    return _session_class()(width=width, height=height)


def attach_session(record: dict, width: int = 1920, height: int = 1080):
    """The GameSession a kept record names (`kept.kept_session_why`), not started."""
    if WINDOWS:
        return WinSession.attach(record, width=width, height=height)
    return _session_class().attach(record, width=width, height=height)


def connect(session):
    """What capture rides on: the Wayland connection to the session (Windows:
    the session itself, whose game window is captured).
    bootstrap.connect_capture closes and remakes it on a failed handshake."""
    if WINDOWS:
        return session
    from .wl.connection import WlConnection
    return WlConnection(session.socket).connect()


def make_capture(conn):
    if WINDOWS:
        return WinCapture(window=conn.game_hwnd)
    from .wl.screencopy import ScreenCopy
    return ScreenCopy(conn, output_index=0)


def make_input(session):
    if WINDOWS:
        return WinInput(window=session.game_hwnd, width=session.width, height=session.height)
    from .input import VirtualInput
    return VirtualInput(socket=session.socket)


def make_panic(on_panic, key: str = "F12"):
    """A PanicKey, not started."""
    if WINDOWS:
        return WinPanicWatcher(on_panic=on_panic, key=key)
    from .panic import PanicWatcher
    return PanicWatcher(on_panic=on_panic, key=key)
