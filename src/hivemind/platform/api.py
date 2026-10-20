"""The platform seam (ROADMAP RL6): what the bot needs from the machine it runs on.

THE CONTRACT OF THE WINDOWS PORT. Since phase 2 every Linux class fits it
(tests/unit/test_platform_api.py checks it by signature), act/bootstrap builds
through platform/current, and CaptureFailed/CaptureTimeout live here.
docs/pending/windows-port.md is the plan this belongs to.

Every signature here is copied from how the code CALLS the Linux class today
(act/bootstrap, scripts/run_farm, gui/launcher, overnight.sh), not invented, so
phase 2 (Linux behind the seam) changes no behaviour: a Linux class that
already conforms is used as it is.

Rules every implementation keeps, on every platform:
  * frames are (h, w, 4) uint8 BGRA numpy arrays in GAME-CLIENT pixels,
    1920x1080 being the size every measured box assumes;
  * input coordinates are in the same pixels as the frames;
  * nothing reads or writes another process's memory, injects into it, or
    hooks it: a screen reader and an input sender, nothing more (no access to the game process: screen and input only);
  * the Roblox client is only ever ended through a handle this run started
    (DESIGN 8ds), never by name.

This module must import on any OS: stdlib only, no platform packages.
"""
from __future__ import annotations

import contextlib
import inspect
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, runtime_checkable

Region = tuple[int, int, int, int]          # x, y, w, h in client pixels


class CaptureFailed(RuntimeError):
    """A frame could not be had. Lives here (RL6 phase 2) so it imports on
    any OS; platform/wl/screencopy re-exports it for every old import."""


class CaptureTimeout(CaptureFailed):
    """The compositor never completed a frame. Subclasses CaptureFailed so
    existing handlers keep working, but is distinguishable for diagnosis."""


class GameNotFocused(RuntimeError):
    """Input refused: the game's window is not the foreground window. Only
    Windows raises it (SendInput reaches the foreground window, whatever it
    is), so a key meant for the game never lands in the owner's chat, browser
    or own game. Lives here so a caller on any OS can catch it; the controls
    turn it into a pause, like the minimized-window guard."""


@runtime_checkable
class Capture(Protocol):
    """Frames of the game. Linux: platform/wl/screencopy.ScreenCopy."""

    def capture(self, region: Region | None = None,
                timeout: float = 5.0) -> Any:
        """One frame, (h, w, 4) BGRA, of the whole client area or `region`.
        Raises CaptureFailed (CaptureTimeout when nothing arrived in
        `timeout`): callers hold keys across this, so it must never hang.
        Must be safe to call from several threads at once (the live view,
        the mob watch and the walker all do)."""

    def lock_waits(self) -> dict[str, tuple[int, float, float]]:
        """{thread name: (captures, seconds waited for the lock, the most)}
        for the live view's starvation check (telemetry/liveview)."""

    def close(self) -> None:
        """Free buffers and the capture session. Never ends the game."""


@runtime_checkable
class Input(Protocol):
    """Keyboard and mouse into the game. Linux: platform/input.VirtualInput.

    Key names are the platform/wl/vkeyboard.KEYS spellings ("w", "space",
    "comma", "pageup", "1", "f1"...); a Windows implementation maps the same
    names to scan codes. Four stuck-key guarantees stay: `held` releases on
    every exit, `release_all` between tasks, an atexit hook, signal handlers.
    """

    refuse_to_type: bool
    in_game: bool

    def no_chat_from(self, settings: Any) -> None:
        """Lock the never-chat rule on (DESIGN 8du); the setting cannot undo it."""

    def press(self, *keys: str) -> None:
        """Press every key, or none: a failure part-way releases the earlier ones."""

    def release(self, *keys: str) -> None:
        """Release every key even if one raises."""

    def held(self, *keys: str) -> contextlib.AbstractContextManager:
        """Hold keys for a `with` block; released on every way out."""

    def tap(self, key: str, ms: int = 40) -> None: ...

    def camera_left(self, taps: int = 1, gap: float = 0.1) -> None: ...

    def camera_right(self, taps: int = 1, gap: float = 0.1) -> None: ...

    def camera_up(self, taps: int = 1, gap: float = 0.1) -> None: ...

    def camera_down(self, taps: int = 1, gap: float = 0.1) -> None: ...

    def type_text(self, text: str, delay: float = 0.04) -> None:
        """The Roblox app's search box only; raises PermissionError in game."""

    def focus_game(self, x: int = 960, y: int = 540) -> None:
        """Make the game take keys (Linux: a pointer-enter; Windows: the
        window in the foreground and the cursor over it)."""

    def click(self, x: float | None = None, y: float | None = None) -> None: ...

    def move_mouse(self, x: float, y: float) -> None: ...

    def drag(self, x0: float, y0: float, x1: float, y1: float, *,
             steps: int = 12, hold_s: float = 0.15, check: Any = None) -> bool:
        """Press at (x0, y0), carry to (x1, y1), let go; `check()` False
        carries it back. The button is let go on every way out."""

    def drag_seek(self, x0: float, y0: float, px: float, py: float, find: Any, *,
                  check: Any = None, steps: int = 12, hold_s: float = 0.15) -> Any: ...

    def scroll(self, steps: int = 1, horizontal: bool = False) -> None:
        """Wheel notches; positive is down."""

    def release_all(self) -> None:
        """Every key and button up. Never raises; the panic key calls it."""

    @property
    def held_keys(self) -> set[str]: ...

    def close(self) -> None:
        """release_all, then free the device."""


@runtime_checkable
class GameSession(Protocol):
    """Where the game runs, and its window. Linux: platform/session.Session
    (a nested Hyprland); Windows: the RobloxPlayerBeta window on the desktop.

    `hyprctl` is deliberately NOT here: its two callers ask "has the game
    opened a window?" (act/bootstrap) and "what windows are there?" (run_farm's
    start-failure report), which are `game_window_open` and `describe_windows`.
    """

    width: int
    height: int

    def start(self, timeout: float = 20.0, attempts: int = 3) -> Any:
        """Bring up whatever the game needs to run in (Linux: the nested
        compositor; Windows: DPI awareness, nothing to launch). Returns self."""

    def clear_stale(self) -> int:
        """End what a crashed run of OURS left behind, identified by
        something only ours can have; never the owner's own game. How many."""

    def launch_game(self, private_link: str | None = None) -> Any:
        """Start the client (a URI or none for the app home); its Popen-like
        handle is the only thing that may later end it."""

    def game_window_open(self) -> bool:
        """The game's window exists (bootstrap's WINDOW_TIMEOUT wait)."""

    def describe_windows(self) -> str:
        """The session's windows in words, for a start-failure report."""

    def fullscreen_focused(self) -> None:
        """Make the game fill the measured 1920x1080 client area."""

    def leave_fullscreen(self) -> None:
        """Hand the window to a person (teach_map, watch_me_play)."""

    def host_window_minimized(self) -> bool | None:
        """Is the game's window minimized (no frames while it is)? None
        when it cannot be told."""

    def restore_below(self) -> bool:
        """Un-minimize it without taking the owner's keyboard; True if done."""

    def give_back_focus(self, wait_s: float = 10.0) -> str:
        """If the new window took the owner's keyboard, give it back.
        What was done, '' when nothing could be. (Windows: the bot needs the
        foreground to send input at all, so there this only applies while
        the bot is paused -- see the plan, 'the focus problem'.)"""

    def release_alt(self) -> str:
        """Let go of an Alt the game believes is held; what was done."""

    def compositor_pid(self) -> int | None:
        """The pid a kept session is checked by (Linux: the compositor's;
        Windows: the game's)."""

    def stop(self) -> None:
        """End this session (and so our game) by our own handles only."""


@runtime_checkable
class KeptGame(Protocol):
    """Keeping the game across a bot restart (deploy_keep: the Wealth Clock
    streak). Module-level functions; Linux: the platform/session module."""

    def kept_session_why(self, path: Any, config_path: Any) -> tuple[dict | None, str]: ...

    def keep_session(self, path: Any, *, game_pid: int,
                     joined_at: float | None, **extra: Any) -> None:
        """Write the record. Platform fields (Linux socket/signature/pid of
        the compositor; Windows the game's hwnd and start time) go in extra."""

    def forget_session(self, path: Any) -> None: ...


@runtime_checkable
class ClientLog(Protocol):
    """The Roblox client's own FLog, read as written. Linux and Windows share
    platform/clientlog.ClientLog; only the file it tails differs
    (Paths.client_log)."""

    joined: Any
    ended: Any
    version: str | None
    crashed: bool
    heartbeats: int
    lines: int
    problems: int

    def start(self) -> Any: ...

    def stop(self) -> None: ...

    def poll(self) -> list: ...

    def heartbeat_age(self, now: float | None = None) -> float | None: ...

    def alive(self, now: float | None = None) -> bool | None: ...

    def describe(self) -> str: ...

    def describe_end(self) -> str: ...


@runtime_checkable
class GameGuard(Protocol):
    """Is the owner playing a game of their own? Linux: platform/gameguard
    (reads /proc); Windows: psutil's process list (names only, no handles
    into the processes' memory)."""

    def playing(self, games: Iterable[str] = ()) -> str | None: ...

    def check(self, settings: Any) -> str | None: ...


@runtime_checkable
class Memory(Protocol):
    """The machine's memory, for the start gate and the step-aside rule.
    The policy (platform/memory.Memory, check, SelfWatch) is shared; only these
    readers are per platform. Linux: /proc and /sys; Windows: psutil."""

    def read(self) -> Any:
        """A platform/memory.Memory (stall_pct None where there is no PSI)."""

    def rss_gb(self) -> float: ...

    def model_rss_gb(self) -> float | None: ...

    def vram_free_gb(self) -> float | None: ...

    def read_stall(self) -> tuple[float | None, float | None]: ...

    def check(self, what: str = "this", kept: bool = False) -> tuple[bool, str]: ...


@runtime_checkable
class PanicKey(Protocol):
    """A key that releases everything from outside the bot's main loop.
    Linux: platform/panic.PanicWatcher (evdev); Windows: GetAsyncKeyState
    polled in a thread. Constructed as PanicKey(on_panic=..., key="F12")."""

    available: bool
    reason: str
    fired: int

    def start(self) -> Any: ...

    def trigger(self) -> None: ...

    def stop(self) -> None: ...


@runtime_checkable
class Paths(Protocol):
    """Where things live: the hivemind.datapaths module on every OS (it is
    there, not in platform/, because world/ and telemetry/ need it and may
    not import platform -- tests/unit/test_layering.py)."""

    def data(self, *parts: str) -> Path: ...

    def var(self, *parts: str) -> Path: ...

    def config_dir(self) -> Path:
        """settings.yaml, server.yaml, telegram.env (Linux ~/.config/hivemind,
        Windows %APPDATA%\\Hivemind via platformdirs)."""

    def runtime_dir(self) -> Path:
        """Short-lived files: the live-view JPEG, locks, the IPC endpoint."""

    def client_log(self) -> Path | None:
        """The client log to tail now (Linux var/sober.log; Windows the
        newest %LOCALAPPDATA%\\Roblox\\logs\\*Player*.log)."""

    def session_logs_dir(self) -> Path:
        """Where the client keeps one log per session (platform/lastserver)."""


@runtime_checkable
class Processes(Protocol):
    """Believing a pid, and the one-farm lock. Linux: hivemind.files (/proc,
    flock); Windows: psutil create_time and msvcrt.locking."""

    def process_identity(self, pid: int) -> tuple[str, str] | None: ...

    def process_parent(self, pid: int) -> int | None: ...

    def pid_running(self, path: Any, script: str, identity: Any = None,
                    start_path: Any = None) -> int | None: ...

    def take_lock(self, path: Any) -> Any: ...


@runtime_checkable
class Watchdog(Protocol):
    """The GUI's handle on the bot process and its relauncher. Linux:
    gui/launcher.BotProcess over scripts/overnight.sh; Windows: the same class
    over a Python watchdog. `stop(keep_game=True)` replaces SIGUSR1 (sent today
    by deploy_keep.sh), which Windows does not have."""

    def start(self, extra: list[str] | None = None) -> Any: ...

    def stop(self, grace: float = 25.0, sleep: Callable = ..., keep_game: bool = False) -> str: ...

    def running(self) -> bool: ...

    def watchdog_pid(self) -> int | None: ...

    def farm_pid(self) -> int | None: ...

    def describe_state(self) -> str: ...


INTERFACES = (Capture, Input, GameSession, KeptGame, ClientLog, GameGuard,
              Memory, PanicKey, Paths, Processes, Watchdog)


# ---------------------------------------------------------------------------
# Conformance, by signature rather than by isinstance: runtime_checkable only
# asks whether a name exists, and a method whose parameters moved is exactly
# the drift that would break a caller.
# ---------------------------------------------------------------------------
def _members(proto) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for klass in reversed(proto.__mro__):
        if klass in (object, Protocol) or not getattr(klass, "_is_protocol", False):
            continue
        for name in getattr(klass, "__annotations__", {}):
            out[name] = None                         # a data attribute
        for name, value in vars(klass).items():
            if not name.startswith("_") and (callable(value) or isinstance(value, property)):
                out[name] = value
    return out


def _params(fn) -> list[inspect.Parameter] | None:
    try:
        ps = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return None
    if ps and ps[0].name in ("self", "cls"):
        ps = ps[1:]
    return ps


_POS = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)


def differences(proto, impl) -> list[str]:
    """How `impl` (a class, an instance or a module) differs from `proto`:
    one line per missing member or incompatible signature, [] when it fits.
    Extra parameters in the implementation are fine when they have defaults."""
    found = []
    for name, want in _members(proto).items():
        if not hasattr(impl, name):
            found.append(f"missing {name}")
            continue
        if want is None or isinstance(want, property):
            continue
        have = getattr(impl, name)
        p_want, p_have = _params(want), _params(have)
        if p_want is None or p_have is None:
            continue
        by_name = {p.name: p for p in p_have}
        has_var = {p.kind for p in p_have}
        for p in p_want:
            if p.kind is inspect.Parameter.VAR_POSITIONAL:
                if inspect.Parameter.VAR_POSITIONAL not in has_var:
                    found.append(f"{name}: does not take *{p.name}")
                continue
            if p.kind is inspect.Parameter.VAR_KEYWORD:
                if inspect.Parameter.VAR_KEYWORD not in has_var:
                    found.append(f"{name}: does not take **{p.name}")
                continue
            q = by_name.get(p.name)
            if q is None:
                if p.kind in _POS and inspect.Parameter.VAR_POSITIONAL in has_var:
                    continue
                if inspect.Parameter.VAR_KEYWORD in has_var and p.kind not in _POS:
                    continue
                found.append(f"{name}: no parameter {p.name!r}")
                continue
            if p.kind in _POS and q.kind not in _POS:
                found.append(f"{name}: {p.name!r} is keyword-only")
            if p.default is not inspect.Parameter.empty and q.default is inspect.Parameter.empty:
                found.append(f"{name}: {p.name!r} has no default")
        wanted = {p.name for p in p_want}
        for q in p_have:
            if (q.name not in wanted and q.default is inspect.Parameter.empty
                    and q.kind not in (inspect.Parameter.VAR_POSITIONAL,
                                       inspect.Parameter.VAR_KEYWORD)):
                found.append(f"{name}: requires extra {q.name!r}")
    return found
