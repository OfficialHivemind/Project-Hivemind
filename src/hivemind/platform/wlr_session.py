"""The game in a HEADLESS labwc instead of a nested Hyprland (ROADMAP RL1b, step 1).

docs/pending/universal-linux.md is the why. In short: wlroots' headless
backend needs no parent compositor, no seat and no host display, so this
session opens no window on anyone's desktop -- no KWin minimize, no stolen
keyboard, no forwarded Alt -- and the same code runs under any desktop, X11
included. The bot's own capture and input (wl/screencopy, platform/input)
drive it unchanged: labwc offers all five protocols they bind (measured in
tools/universal/probe.py, 62 captures/s, key and click arrived).

What replaces hyprctl, all standard protocols, no IPC:
  * the output size: wlr-output-management (headless starts at 1280x720);
  * the windows: wlr-foreign-toplevel-management (app id, title, state),
    which also sets and unsets fullscreen;
  * fullscreen on map: our own rc.xml's window rule on the game's app id.

IDENTITY, the same argument as Session.clear_stale: labwc run with `-C <our
config dir>`, which nothing but this class writes. The kept-game record keeps
the Hyprland shape (socket, signature, hypr_pid); `signature` is the socket.

Chosen by the `platform.compositor` setting (platform/current); Hyprland stays
the default. The labwc binary: $HIVEMIND_LABWC (e.g. the one
tools/universal/fetch_compositor.sh unpacked, its libraries beside it), else
`labwc` on PATH.
"""
from __future__ import annotations

import array
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .session import (RUNTIME, SOBER, bss_uri, end_pid, kill_marked, ours_compositor,
                      outliving, render_node)

LABWC_ENV = "HIVEMIND_LABWC"
CONFIG_DIR = Path.home() / ".config/hivemind/labwc"
FULLSCREEN = 3            # zwlr_foreign_toplevel_handle_v1.state.fullscreen

# Every window with the game's app id is fullscreened as it maps: Sober opens
# windowed and letterboxed, and every measured box assumes 1920x1080. labwc
# has only a toggle, so fullscreen_focused() then SETS it (idempotent) over
# foreign-toplevel, in case the game asked for fullscreen itself.
RC_XML = """\
<?xml version="1.0"?>
<labwc_config>
  <windowRules>
    <windowRule identifier="{app_id}"><action name="ToggleFullscreen"/></windowRule>
  </windowRules>
</labwc_config>
"""


def find_labwc() -> tuple[str, str | None] | None:
    """(the labwc binary, a library dir it needs or None), or None.
    $HIVEMIND_LABWC first; a binary in fetch_compositor.sh's DIR/root/usr/bin
    takes its wlroots from DIR/root/usr/lib."""
    given = os.environ.get(LABWC_ENV)
    path = given or shutil.which("labwc")
    if not path or not os.access(path, os.X_OK):
        return None
    lib = Path(path).resolve().parent.parent / "lib"
    return path, (str(lib) if given and any(lib.glob("libwlroots-*.so*")) else None)


class Control:
    """One short-lived client connection for the compositor's own questions
    (never the bot's capture or input connection).

    EVERY OBJECT THE COMPOSITOR CREATES IS FREED HERE BEFORE THE DISCONNECT.
    MEASURED 2026-10-19 (segfault in the live test): pywayland gives an
    event-created object (a head, a mode, a window handle) the Display of the
    first WlRegistry still in memory -- with several connections in one
    process, often a closed one -- so `disconnect` did not free them, and the
    garbage collector later ran wl_proxy_destroy on a freed connection."""

    def __init__(self, socket: str):
        from pywayland.client import Display
        from .wl.gen.wlr_foreign_toplevel_management_unstable_v1 import \
            ZwlrForeignToplevelManagerV1
        from .wl.gen.wlr_output_management_unstable_v1 import ZwlrOutputManagerV1
        wanted = {"zwlr_output_manager_v1": ZwlrOutputManagerV1,
                  "zwlr_foreign_toplevel_manager_v1": ZwlrForeignToplevelManagerV1}
        self.bound: dict[str, object] = {}
        self.heads: list = []
        self.serial: int | None = None
        self.windows: list[dict] = []
        self.created: list = []          # event-created proxies, freed by close()
        self.display = Display(socket)
        self.display.connect()

        def on_global(registry, name, interface, version):
            iface = wanted.get(interface)
            if iface is not None:
                self.bound[interface] = registry.bind(name, iface, min(version, iface.version))

        registry = self.display.get_registry()
        registry.dispatcher["global"] = on_global
        self.display.roundtrip()
        out = self.bound.get("zwlr_output_manager_v1")
        if out is not None:
            out.dispatcher["head"] = self._head
            out.dispatcher["done"] = lambda _m, serial: setattr(self, "serial", serial)
        top = self.bound.get("zwlr_foreign_toplevel_manager_v1")
        if top is not None:
            top.dispatcher["toplevel"] = self._toplevel
        self.display.roundtrip()      # the heads and the toplevels
        self.display.roundtrip()      # and their details

    def _head(self, _manager, head) -> None:
        self.heads.append(head)
        self.created.append(head)
        head.dispatcher["mode"] = lambda _h, mode: self.created.append(mode)

    def _toplevel(self, _manager, handle) -> None:
        self.created.append(handle)
        w = {"handle": handle, "app_id": "", "title": "", "state": set(), "closed": False}
        self.windows.append(w)
        handle.dispatcher["app_id"] = lambda _h, v: w.__setitem__("app_id", v)
        handle.dispatcher["title"] = lambda _h, v: w.__setitem__("title", v)
        handle.dispatcher["state"] = lambda _h, v: w.__setitem__(
            "state", set(array.array("I", bytes(v))))
        handle.dispatcher["closed"] = lambda _h: w.__setitem__("closed", True)

    def open_windows(self) -> list[dict]:
        return [w for w in self.windows if not w["closed"]]

    def set_size(self, width: int, height: int, refresh_mhz: int = 60000) -> bool:
        """Every head to width x height through wlr-output-management; True
        when the compositor says the configuration succeeded."""
        manager = self.bound.get("zwlr_output_manager_v1")
        if manager is None or self.serial is None or not self.heads:
            return False
        said: list[str] = []
        config = manager.create_configuration(self.serial)
        for event in ("succeeded", "failed", "cancelled"):
            config.dispatcher[event] = lambda _c, e=event: said.append(e)
        for head in self.heads:
            config.enable_head(head).set_custom_mode(width, height, refresh_mhz)
        config.apply()
        for _ in range(20):
            if said:
                break
            self.display.roundtrip()
        config.destroy()
        return said[:1] == ["succeeded"]

    def set_fullscreen(self, app_id: str, on: bool) -> int:
        """Fullscreen (or not) every window of `app_id`; how many."""
        hit = [w for w in self.open_windows() if w["app_id"].lower() == app_id.lower()]
        for w in hit:
            w["handle"].set_fullscreen(None) if on else w["handle"].unset_fullscreen()
        self.display.roundtrip()
        return len(hit)

    def close(self) -> None:
        from pywayland.protocol_core import Proxy
        for proxy in self.created:
            Proxy._destroy(proxy)        # client side only; safe whatever its Display
        self.created.clear()
        self.display.disconnect()

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()


def windows(socket: str) -> list[dict] | None:
    """The compositor's open windows ({app_id, title, fullscreen}), or None
    when it cannot be asked."""
    try:
        with Control(socket) as c:
            return [{"app_id": w["app_id"], "title": w["title"],
                     "fullscreen": FULLSCREEN in w["state"]} for w in c.open_windows()]
    except Exception:
        return None


def game_in_socket(socket: str, app_id: str = SOBER) -> bool:
    """The game's window is a client of the labwc on `socket`
    (session.kept_session_why's check for a labwc record)."""
    return any(w["app_id"].lower() == app_id.lower() for w in windows(socket) or [])


@dataclass
class WlrSession:
    width: int = 1920
    height: int = 1080
    config_path: Path = field(default_factory=lambda: CONFIG_DIR)   # a DIRECTORY: labwc -C
    proc: subprocess.Popen | None = None
    socket: str | None = None
    signature: str | None = None     # = socket: the kept record's shape (session.keep_session)
    log: Path | None = None
    pid: int | None = None           # an ATTACHED compositor's, which has no Popen
    runtime: Path = field(default_factory=lambda: RUNTIME)
    game_id: str = SOBER             # the app id the window rule and the checks look for

    # ---- compositor -------------------------------------------------------
    def start(self, timeout: float = 20.0, attempts: int = 3) -> "WlrSession":
        """Clear a crashed run's leftovers, then start labwc headless,
        retrying a start that does not take (Session.start's reasons)."""
        self.clear_stale()
        last: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                return self._start_once(timeout)
            except (RuntimeError, TimeoutError) as exc:
                last = exc
                self.stop()
                if attempt < attempts:
                    time.sleep(2.0 * attempt)
        raise last if last else RuntimeError("compositor would not start")

    def clear_stale(self) -> int:
        """End a labwc of OURS a previous run left behind (by our config dir,
        as Session.clear_stale does by its config path), and a nested
        Hyprland of ours too: Sober refuses to run twice, so one left by a
        run before the compositor setting changed would block this start."""
        from .session import Session
        killed = kill_marked(str(self.config_path), "labwc")
        killed += kill_marked(str(Session().config_path), "hyprland")
        if killed:
            time.sleep(3.0)          # let its clients notice and exit
        return killed

    def _env(self, lib: str | None) -> dict:
        env = {**os.environ, "XDG_RUNTIME_DIR": str(self.runtime),
               "WLR_BACKENDS": "headless", "WLR_LIBINPUT_NO_DEVICES": "1"}
        # no host display, no seat; and no D-Bus, so nothing of ours can
        # reach the user's activation environment
        for key in ("WAYLAND_DISPLAY", "WAYLAND_SOCKET", "DISPLAY",
                    "DBUS_SESSION_BUS_ADDRESS", "HYPRLAND_INSTANCE_SIGNATURE"):
            env.pop(key, None)
        node = render_node()             # the discrete GPU, not the iGPU
        if node:
            env["WLR_RENDER_DRM_DEVICE"] = node
        if lib:
            env["LD_LIBRARY_PATH"] = os.pathsep.join(
                p for p in (lib, os.environ.get("LD_LIBRARY_PATH", "")) if p)
        return env

    def _start_once(self, timeout: float) -> "WlrSession":
        found = find_labwc()
        if not found:
            raise RuntimeError(f"labwc is not installed: install it, or set {LABWC_ENV} "
                               f"to a labwc binary (tools/universal/fetch_compositor.sh)")
        binary, lib = found
        self.config_path.mkdir(parents=True, exist_ok=True)
        (self.config_path / "rc.xml").write_text(RC_XML.format(app_id=self.game_id))
        mark = self.config_path / "socket"
        mark.unlink(missing_ok=True)
        # labwc runs this once its socket listens: the socket's name, written
        # where only we look (no diff of the runtime dir, unlike Hyprland)
        tell = "sh -c " + shlex.quote('echo "$WAYLAND_DISPLAY" > ' + shlex.quote(str(mark)))
        self.log = self.config_path / "labwc.log"
        with open(self.log, "wb") as fh:
            self.proc = subprocess.Popen([binary, "-C", str(self.config_path), "-s", tell],
                                         stdout=fh, stderr=subprocess.STDOUT,
                                         env=self._env(lib))
        deadline = time.monotonic() + timeout
        name = ""
        while not name:
            if self.proc.poll() is not None:
                raise RuntimeError(f"compositor exited immediately; see {self.log}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"no wayland socket appeared; see {self.log}")
            time.sleep(0.2)
            name = mark.read_text().strip() if mark.exists() else ""
        self.socket = name if self.runtime == RUNTIME else str(self.runtime / name)
        self.signature = self.socket
        with Control(self.socket) as c:
            if not c.set_size(self.width, self.height):
                raise RuntimeError(f"could not set the output to {self.width}x{self.height}")
        time.sleep(0.5)          # let the output settle before clients connect
        return self

    # ---- windows (wlr-foreign-toplevel) ----------------------------------
    def game_window_open(self) -> bool:
        return bool(self.socket) and game_in_socket(self.socket, self.game_id)

    def describe_windows(self) -> str:
        found = windows(self.socket) if self.socket else None
        if found is None:
            return "(the compositor could not be asked)"
        return "\n".join(f"app_id: {w['app_id']}  title: {w['title']}"
                         f"{'  fullscreen' if w['fullscreen'] else ''}"
                         for w in found) or "(no windows)"

    def _fullscreen(self, on: bool) -> None:
        if self.socket:
            try:
                with Control(self.socket) as c:
                    c.set_fullscreen(self.game_id, on)
            except Exception:
                pass

    def fullscreen_focused(self) -> None:
        """The game fills the output (the window rule did it on map; this
        makes sure, since the rule can only toggle)."""
        self._fullscreen(True)

    def leave_fullscreen(self) -> None:
        """Out of fullscreen, for a person to take over. NOTE headless: no
        person can reach this window until the GUI forwards input (step 3)."""
        self._fullscreen(False)

    # ---- no window on any desktop: nothing to minimize, focus or let go of
    def host_window_minimized(self) -> bool | None:
        return None

    def restore_below(self) -> bool:
        return False

    def give_back_focus(self, wait_s: float = 10.0) -> str:
        return ""

    def release_alt(self) -> str:
        return "headless: no forwarded keyboard to hold an Alt"

    # ---- the game ----------------------------------------------------------
    def launch_game(self, private_link: str | None = None) -> subprocess.Popen:
        if not self.socket:
            raise RuntimeError("compositor not started")
        # the socket's name in the user's runtime dir, as Hyprland's is (an
        # absolute path when self.runtime is elsewhere: flatpak takes both)
        env = {**os.environ, "WAYLAND_DISPLAY": self.socket}
        env.pop("DISPLAY", None)          # force Wayland, not XWayland
        return subprocess.Popen(outliving([SOBER, bss_uri(private_link)]), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def attach(cls, record: dict, width: int = 1920, height: int = 1080) -> "WlrSession":
        """The kept session's compositor (session.kept_session), not started here."""
        return cls(width=width, height=height, socket=str(record["socket"]),
                   signature=str(record["signature"]), pid=int(record["hypr_pid"]))

    def compositor_pid(self) -> int | None:
        return self.proc.pid if self.proc is not None else self.pid

    # ---- teardown ----------------------------------------------------------
    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
            self.proc = None
        elif self.pid:
            end_pid(self.pid, lambda: ours_compositor(self.pid, self.config_path))
            self.pid = None

    def __enter__(self): return self.start()
    def __exit__(self, *exc): self.stop()
