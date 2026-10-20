"""The Roblox window on the Windows desktop (platform/api GameSession, KeptGame).

On Linux the game runs inside a nested Hyprland the bot owns (platform/
session). Here there is nothing to start: the game is a window on the
owner's desktop. This finds it, launches it, sizes it and remembers which
one is OURS. Every Windows behaviour relied on is tagged [verified] (a
Microsoft doc, or Natro Macro's source, the reference Windows BSS macro,
read at github.com/NatroTeam/NatroMacro 094f9c7, 2026-04-27) or [assumed].

HOW ROBLOX IS LAUNCHED. Natro starts every (re)join by running a roblox://
deep link through the shell (`Run "roblox://placeID=1537690962&linkcode=..."`,
natro_macro.ahk RunDeeplink) [verified: Natro]. The shell looks the
`roblox` scheme up in HKCR\\roblox\\shell\\open\\command, which the installer
points at RobloxPlayerBeta.exe (or a bootstrapper such as Bloxstrap, which
Natro detects the same way) [verified: Natro nm_GetRobloxWebPath /
nm_DetectRobloxType]. We read that command ourselves and start it with
Popen, so the run holds a handle (DESIGN 8ds: our game is ended only through
what we started). Fallback: the newest %LOCALAPPDATA%\\Roblox\\Versions\\
version-*\\RobloxPlayerBeta.exe, given the same link [assumed].

WHICH LINK (`win_uri`):
  * nothing          -> roblox://placeId=1537690962 (a public BSS server)
  * a legacy link    -> roblox://placeId=1537690962&linkCode=<code>
  * a share link     -> roblox://navigation/share_links?code=<code>&type=Server
  * a roblox:// URI  -> as it is (platform/lastserver's server objects)
The first two are Roblox's documented deep-link parameters [verified:
create.roblox.com deeplinks] and Natro's [verified]. The share form is
Natro's too [verified]; on Sober (the Android build) it landed on the app
home [code: platform/session.parse_private_link], so whether the Windows
client joins by it is [assumed]. There is NO app shell on Windows (the
player opens straight into a game), so the Linux route through the Servers
drawer (act/join) does not exist here: Windows joins by link, or with no
link by the place itself -- a public server (act/bootstrap WINDOWS_PUBLIC).

WHICH WINDOW IS OURS. The launcher may update and re-exec, so the game's pid
need not be the Popen's [assumed: the doc's #20]. Ours is a visible top-level
window of a RobloxPlayerBeta.exe that is the Popen's pid, or that was NOT
running before our launch and started after it. Of a Roblox process only its
name and start time are read (no access to the game process: screen and input only, the plan 4c). Once found, its pid
and start time are written to OURS_FILE: platform/win/gameguard reads it so
the bot's own Roblox is not "the owner playing", and `clear_stale` ends a
game a crashed run left behind only when BOTH still match.

THE WINDOW. The coordinates need a 1920x1080 CLIENT area. If it is not
already that, the window is made borderless (WS_CAPTION and the frame
removed with SetWindowLongW, [verified API]) and placed at its monitor's
origin sized to it -- the whole monitor when that is 1920x1080, else exactly
1920x1080 [assumed: Roblox redraws at the new size and does not put its
frame back]. Roblox's own F11 fullscreen is not used: it toggles, and from
outside its state cannot be told [assumed]. DPI: per-monitor v2 first, so
every rectangle is in physical pixels [verified: SetProcessDpiAwarenessContext].
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import psutil

from ... import datapaths
from ..session import BSS_PLACE_ID, forget_session, keep_session, parse_private_link
from . import _user32 as w

__all__ = ["WinSession", "win_uri", "kept_session", "kept_session_why", "keep_session",
           "forget_session", "our_game", "OURS_FILE"]

ROBLOX = "robloxplayerbeta.exe"
WINDOW_TITLE = "Roblox"            # Natro's GetRobloxHWND: "Roblox ahk_exe RobloxPlayerBeta.exe" [verified]
PROTOCOL_KEY = r"roblox\shell\open\command"
CREATE_NEW_PROCESS_GROUP, DETACHED_PROCESS = 0x00000200, 0x00000008
GWL_STYLE = -16
WS_CAPTION, WS_MAXIMIZE = 0x00C00000, 0x01000000
SW_RESTORE = 9
WS_FRAME = 0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000   # caption, thickframe, sysmenu, min, max
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x10, 0x20
HWND_BOTTOM = 1
SW_SHOWNOACTIVATE = 4
# Where the run notes the Roblox it launched (pid + start time), alive or kept.
OURS_FILE = ("night", "roblox.json")
LAUNCH_GRACE_S = 2.0               # a game "started after our launch" may be this early (clock rounding)


def win_uri(private_link: str | None = None) -> str:
    """The deep link to run (see the module docstring, WHICH LINK)."""
    if private_link and private_link.strip().lower().startswith("roblox://"):
        return private_link.strip()
    parsed = parse_private_link(private_link)
    if parsed is None:
        return f"roblox://placeId={BSS_PLACE_ID}"
    kind, code = parsed
    if kind == "share":
        return f"roblox://navigation/share_links?code={quote(code, safe='')}&type=Server"
    return f"roblox://placeId={BSS_PLACE_ID}&linkCode={quote(code, safe='')}"


def protocol_command() -> str | None:
    """HKCR\\roblox\\shell\\open\\command's default value, or None."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, PROTOCOL_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "")
    except (ImportError, OSError):
        return None
    return str(value) or None


def newest_player(local: Path | None = None) -> Path | None:
    """The newest installed RobloxPlayerBeta.exe, or None."""
    local = local or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Roblox" / "Versions"
    found = sorted(local.glob("version-*/RobloxPlayerBeta.exe"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def launch_command(uri: str, command: str | None = None, player: Path | None = None):
    """What Popen runs: the protocol handler's command line with the link in
    place of %1 (a string: CreateProcess parses it as the shell would), or
    [newest player, link]. RuntimeError when Roblox is not installed."""
    command = command if command is not None else protocol_command()
    if command and "%1" in command:
        return command.replace('"%1"', "%1").replace("%1", f'"{uri}"')
    player = player or newest_player()
    if player is None:
        raise RuntimeError("Roblox is not installed: no roblox:// handler in the registry "
                           "and no %LOCALAPPDATA%\\Roblox\\Versions\\*\\RobloxPlayerBeta.exe")
    return [str(player), uri]


def _start_time(pid) -> str | None:
    try:
        p = psutil.Process(int(pid))
        if p.name().lower() != ROBLOX:     # its name and start time only (no access to the game process)
            return None
        return f"{p.create_time():.3f}"
    except (psutil.Error, ValueError, TypeError, OSError):
        return None


def _roblox_pids() -> dict[int, float]:
    out = {}
    for p in psutil.process_iter(["name", "create_time"]):
        if (p.info.get("name") or "").lower() == ROBLOX:
            out[p.pid] = p.info.get("create_time") or 0.0
    return out


def _ours_path() -> Path:
    return datapaths.var(*OURS_FILE)


def our_game(path: Path | None = None) -> int | None:
    """The pid of the Roblox this bot launched (or kept), while that very
    process -- pid AND start time -- still runs; else None."""
    try:
        body = json.loads((path or _ours_path()).read_text())
        pid, started = int(body["game_pid"]), str(body["started"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return pid if _start_time(pid) == started else None


def kept_session_why(path, config_path=None) -> tuple[dict | None, str]:
    """The kept record when its game -- pid and start time, a Roblox -- is
    still running, else None and why (platform/session's words where they
    apply). `config_path` is Linux's and unused."""
    try:
        body = json.loads(Path(path).read_text())
    except OSError:
        return None, "no kept-session record"
    except ValueError:
        return None, "the kept-session record is not readable JSON"
    if not isinstance(body, dict):
        return None, "the kept-session record is not a record"
    pid, started = body.get("game_pid"), body.get("started")
    if not pid or not started:
        return None, "the record names no game"
    if _start_time(pid) != str(started):
        return None, f"game pid {pid} is not our Roblox any more"
    return body, ""


def kept_session(path, config_path=None) -> dict | None:
    return kept_session_why(path, config_path)[0]


@dataclass
class WinSession:
    width: int = 1920
    height: int = 1080
    proc: subprocess.Popen | None = None   # what launch_game started
    pid: int | None = None                 # the game's (RobloxPlayerBeta.exe)
    started: str | None = None             # its start time, "%.3f"
    hwnd: int | None = None
    launched_at: float | None = None
    before: set = field(default_factory=set)   # Roblox pids alive before our launch: never ours
    user32: object = None
    config_path = None                     # Linux's kept-record check; nothing here
    socket = signature = None              # Linux's; a Ready on Windows has neither
    _saved: tuple | None = None            # style and rect before fullscreen_focused

    def _u(self):
        if self.user32 is None:
            self.user32 = w.dll("user32")
        return self.user32

    # ---- start ----------------------------------------------------------------
    def start(self, timeout: float = 20.0, attempts: int = 3) -> "WinSession":
        """DPI awareness, and a game a crashed run of ours left behind ended.
        Nothing to launch: the desktop is already there."""
        w.dpi_aware(self._u())
        self.clear_stale()
        return self

    def clear_stale(self) -> int:
        """End the Roblox OURS_FILE names, only while pid AND start time match
        (DESIGN 8ds; never by name, so the owner's own Roblox is safe)."""
        pid = our_game()
        if pid is None or pid == self.pid:
            return 0
        self._end(pid, _start_time(pid))
        forget_session(_ours_path())
        return 1

    def launch_game(self, private_link: str | None = None) -> subprocess.Popen:
        """Run the deep link (win_uri) through Roblox's own protocol command,
        detached so the game outlives this run (as Linux's `outliving`)."""
        self.before = set(_roblox_pids())
        self.launched_at = time.time()
        self.pid = self.started = self.hwnd = None
        self.proc = subprocess.Popen(
            launch_command(win_uri(private_link)),
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self.proc

    @classmethod
    def attach(cls, record: dict, width: int = 1920, height: int = 1080) -> "WinSession":
        """The kept game (`kept_session_why`), not started here."""
        return cls(width=width, height=height, pid=int(record["game_pid"]),
                   started=str(record["started"]), hwnd=record.get("hwnd") or None)

    # ---- the window -------------------------------------------------------------
    def _ours(self, pid: int, created: float) -> bool:
        if self.pid is not None:
            return pid == self.pid
        if self.proc is not None and pid == self.proc.pid:
            return True
        return (self.launched_at is not None and pid not in self.before
                and created >= self.launched_at - LAUNCH_GRACE_S)

    def game_hwnd(self) -> int | None:
        """The game's top-level window, OURS only; None while there is none.
        Cheap when the window is known (two calls); a search otherwise."""
        u = self._u()
        if self.hwnd and u.IsWindow(self.hwnd) and w.window_pid(u, self.hwnd) == self.pid:
            return self.hwnd
        self.hwnd = None
        if self.started is not None and _start_time(self.pid) != self.started:
            return None                    # our game ended: never adopt another
        roblox = _roblox_pids()
        best = None
        for hwnd in w.top_windows(u):
            pid = w.window_pid(u, hwnd)
            if pid not in roblox or not u.IsWindowVisible(hwnd):
                continue
            if not self._ours(pid, roblox[pid]):
                continue
            if w.window_title(u, hwnd) == WINDOW_TITLE:
                best = (hwnd, pid)
                break
            best = best or (hwnd, pid)
        if best is None:
            return None
        self.hwnd, pid = best
        if self.pid != pid:
            self.pid, self.started = pid, _start_time(pid)
            self._note_ours()
        return self.hwnd

    def _note_ours(self) -> None:
        if self.pid and self.started:
            datapaths.var(*OURS_FILE[:-1]).mkdir(parents=True, exist_ok=True)
            keep_session(_ours_path(), game_pid=self.pid, joined_at=None, started=self.started)

    def game_window_open(self) -> bool:
        return self.game_hwnd() is not None

    def game_focused(self) -> bool:
        """Is our game's window the foreground window (where SendInput goes)?"""
        hwnd = self.game_hwnd()
        return bool(hwnd) and w.foreground(self._u()) == hwnd

    def describe_windows(self) -> str:
        u = self._u()
        roblox = _roblox_pids()
        lines = []
        for hwnd in w.top_windows(u):
            pid = w.window_pid(u, hwnd)
            if pid in roblox and u.IsWindowVisible(hwnd):
                lines.append(f"hwnd {hwnd}: {w.window_title(u, hwnd)!r} pid {pid}"
                             + (" (ours)" if self._ours(pid, roblox[pid]) else ""))
        return "\n".join(lines) or "no Roblox window"

    def fullscreen_focused(self, tries: int = 3, settle_s: float = 0.5) -> str:
        """A 1920x1080 client area (see THE WINDOW), then the foreground.
        Returns the line bootstrap logs: "roblox window: client WxH,
        borderless yes/no", loud when it is still not 1920x1080.

        THE CLIENT IS CHECKED AFTER EVERY TRY. MEASURED 2026-10-19 (the
        owner's 5th Windows run): the client was 1920x1009 -- a MAXIMIZED
        captioned window on a 1080p monitor (1080 - 40 taskbar - 31 caption)
        -- and nothing was logged, so every 1080-measured box was off. A
        maximized window is restored first (SW_RESTORE): Windows keeps its
        maximized placement otherwise and may put it back over our size
        [assumed: why the frame came back]."""
        u, hwnd = self._u(), self.game_hwnd()
        if not hwnd:
            return "roblox window: none open to size"
        want = (self.width, self.height)
        size = w.client_size(u, hwnd)
        mon = None
        for attempt in range(max(1, tries)):
            if size == want:
                break
            mon = w.monitor_rect(u, hwnd)
            if mon is None:
                break
            mx, my, mw, mh = mon
            if self._saved is None:
                self._saved = (u.GetWindowLongW(hwnd, GWL_STYLE), w.window_rect(u, hwnd))
            if u.GetWindowLongW(hwnd, GWL_STYLE) & WS_MAXIMIZE or u.IsIconic(hwnd):
                u.ShowWindow(hwnd, SW_RESTORE)
            u.SetWindowLongW(hwnd, GWL_STYLE, u.GetWindowLongW(hwnd, GWL_STYLE) & ~WS_FRAME)
            u.SetWindowPos(hwnd, None, mx, my, self.width, self.height,
                           SWP_NOZORDER | SWP_FRAMECHANGED)
            if settle_s:
                time.sleep(settle_s)
            size = w.client_size(u, hwnd)
        u.SetForegroundWindow(hwnd)
        borderless = not u.GetWindowLongW(hwnd, GWL_STYLE) & WS_CAPTION
        line = (f"roblox window: client {size[0]}x{size[1]}, "
                f"borderless {'yes' if borderless else 'no'}")
        if size != want:
            line += (f" -- NOT {want[0]}x{want[1]}, every screen box is measured at that size "
                     f"and will be off; carrying on")
            if mon is not None and (mon[2] < self.width or mon[3] < self.height):
                line += (f" (its monitor is {mon[2]}x{mon[3]}: move Roblox to a monitor of "
                         f"at least {want[0]}x{want[1]} at 100% scaling)")
        return line

    def leave_fullscreen(self) -> None:
        """Its own frame and place back, for a person (teach_map, watch_me_play)."""
        u, hwnd = self._u(), self.game_hwnd()
        if not hwnd or self._saved is None:
            return
        style, rect = self._saved
        u.SetWindowLongW(hwnd, GWL_STYLE, style)
        if rect:
            u.SetWindowPos(hwnd, None, *rect, SWP_NOZORDER | SWP_FRAMECHANGED)
        self._saved = None

    def host_window_minimized(self) -> bool | None:
        hwnd = self.game_hwnd()
        return None if not hwnd else bool(self._u().IsIconic(hwnd))

    def restore_below(self) -> bool:
        """Un-minimized without activation, at the bottom of the z-order. It
        draws (WGC captures a covered window [verified]) but gets no input
        until it is in front again (run_farm's focus guard pauses for that)."""
        u, hwnd = self._u(), self.game_hwnd()
        if not hwnd:
            return False
        u.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        u.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        return not u.IsIconic(hwnd)

    def give_back_focus(self, wait_s: float = 10.0) -> str:
        """Nothing to give back: the bot needs the foreground to send input at
        all (the plan, 4b). Pausing hands the PC back instead."""
        return ""

    def release_alt(self) -> str:
        """Both Alts up by SendInput (a release is never refused: injected
        key state is global [verified: SendInput])."""
        from .input import SCANCODES, key_event, send
        said = []
        for name, key in (("Alt_L", "alt"), ("Alt_R", "rightalt")):
            try:
                send(self._u(), [key_event(SCANCODES[key], up=True)])
                said.append(f"{name} up")
            except OSError as exc:
                said.append(f"{name} up: raised {exc}")
        return ", ".join(said)

    def compositor_pid(self) -> int | None:
        """The pid a kept record is checked by: the game's own here."""
        return self.pid

    def kept_fields(self) -> dict | None:
        """What `keep_session` needs beside game_pid/joined_at, or None when
        there is no game of ours to keep."""
        if not (self.pid and self.started and _start_time(self.pid) == self.started):
            return None
        return {"started": self.started, "hwnd": self.hwnd}

    # ---- teardown ----------------------------------------------------------------
    @staticmethod
    def _end(pid: int, started: str | None, wait_s: float = 5.0) -> None:
        """terminate, then kill -- only while `pid` is still that game."""
        if not started or _start_time(pid) != started:
            return
        try:
            p = psutil.Process(pid)
            p.terminate()                       # TerminateProcess: Roblox has no clean-exit signal
            p.wait(timeout=wait_s)
        except psutil.TimeoutExpired:
            if _start_time(pid) == started:
                try:
                    psutil.Process(pid).kill()
                except psutil.Error:
                    pass
        except psutil.Error:
            pass

    def stop(self) -> None:
        """End our game by our own handles only: the Popen, and the game pid
        with its start time."""
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        if self.pid:
            self._end(self.pid, self.started)
            if our_game() in (None, self.pid):
                forget_session(_ours_path())
        self.proc = None
        self.pid = self.started = self.hwnd = None

    def __enter__(self): return self.start()
    def __exit__(self, *exc): self.stop()
