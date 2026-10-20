"""Lifecycle of the nested compositor and the game inside it.

Everything here was learned the hard way while spiking, so it is written down
once rather than rediscovered:

  * `Hyprland --socket NAME` does NOT name the socket. It is half of the
    socket-handover pair and errors without `--wayland-fd`. The only reliable
    way to learn the new socket is to diff $XDG_RUNTIME_DIR before and after.
  * The instance signature (needed for `hyprctl`) appears as a new directory
    under $XDG_RUNTIME_DIR/hypr, so it is found the same way.
  * Hyprland segfaults on SIGTERM during teardown. That is not a crash worth
    reporting -- a non-zero exit at shutdown is expected.
  * A headless output renders regardless of occlusion, which is what lets the
    bot keep running while the desktop is busy. Verified: capture from it runs
    at ~60 fps.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from ..datapaths import runtime_dir

# $XDG_RUNTIME_DIR, else /run/user/<uid>, as always -- by a call that imports
# on any OS (os.getuid here at import kept this module off Windows; RL6).
RUNTIME = runtime_dir()
BSS_PLACE_ID = "1537690962"

# THE ALT ACCOUNT'S BOT RUNS AS ANOTHER LINUX USER (tools/alt/README.md), and
# that user cannot open a window on the owner's desktop: his Wayland socket is
# in his own 0700 runtime dir. So the alt's nested Hyprland gets a parent with
# NO display -- KWin's virtual backend -- instead of the desktop.
#
# WHY A PARENT AT ALL. MEASURED 2026-10-12 22:15 (Hyprland 0.56.2, aquamarine
# 0.15.1): Hyprland with no parent dies "Cannot open backend: no allocator
# available" -- its headless backend has no DRM fd, and the DRM backend needs a
# seat session (its libseat gets EBUSY: KWin holds the seat). Nested in
# `kwin_wayland --virtual`, it takes the GPU from the parent's linux-dmabuf
# main device, and the bot's own ScreenCopy, VirtualKeyboard and
# VirtualPointer drove it end to end: all six protocols, 56.7 captures/s with
# vkcube changing in 170 of 170, typed text echoed by a terminal, the cursor
# where VirtualPointer put it. The game sees what the main's sees: a Hyprland
# WAYLAND-1 output, not Hyprland's own headless output (DESIGN 8a: worse).
#
# THE PARENT IS SHOWN ONLY THE DISCRETE GPU. KWin's virtual backend takes the
# first DRM device, here the 512 MB iGPU (renderD129), and KWIN_RENDER_NODES
# does not reach that backend (measured). A bwrap that leaves one render node
# in /dev/dri moved the whole chain to the main GPU (renderD128): Hyprland
# "eglDeviceFromDRMFD: Using device /dev/dri/card1", same 56.7 captures/s.
# Its own D-Bus (dbus-run-session) and config dir, so it never meets a KWin
# the user's desktop session may run, and nothing of its settings lands there.
ROLE = os.environ.get("HIVEMIND_ROLE", "main")
PARENT_SOCKET = "hivemind-parent"        # not wayland-N: _sockets() skips it
PARENT_MARK = f"--socket {PARENT_SOCKET}"


def render_node(drm: Path = Path("/sys/class/drm")) -> str | None:
    """The render node with the most VRAM -- the discrete GPU -- or None."""
    best = None
    for node in sorted(drm.glob("renderD*")):
        try:
            vram = int((node / "device/mem_info_vram_total").read_text())
        except (OSError, ValueError):
            continue
        if best is None or vram > best[0]:
            best = (vram, f"/dev/dri/{node.name}")
    return best[1] if best else None


def parent_argv(width: int, height: int, node: str | None) -> list[str]:
    """The display-less parent compositor's command line."""
    hide = (["bwrap", "--dev-bind", "/", "/", "--tmpfs", "/dev/dri",
             "--dev-bind", node, node] if node and shutil.which("bwrap") else [])
    return [*hide, "dbus-run-session", "--", "kwin_wayland", "--virtual",
            "--width", str(width), "--height", str(height),
            "--socket", PARENT_SOCKET, "--no-lockscreen",
            "--no-global-shortcuts", "--no-kactivities"]


def parent_pids() -> list[int]:
    """THIS user's parent compositors, by their socket argument."""
    try:
        out = subprocess.run(["pgrep", "-u", str(os.getuid()), "-f",
                              f"kwin_wayland --virtual .*{PARENT_MARK}"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(p) for p in out.split() if p.isdigit() and int(p) != os.getpid()]


def _listening(path: Path) -> bool:
    import socket
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(str(path))
        return True
    except OSError:
        return False


SOBER = "org.vinegarhq.Sober"

_PUBLIC = (
    "https://assetgame.roblox.com/game/PlaceLauncher.ashx"
    "?request=RequestGame&browserTrackerId=0&placeId={pid}"
    "&isPlayTogetherGame=false"
)
# A private server is strictly better for a bot: nobody else walking through
# our optical flow, competing for tokens, or killing the boss we travelled to.
_PRIVATE = (
    "https://assetgame.roblox.com/game/PlaceLauncher.ashx"
    "?request=RequestPrivateGame&placeId={pid}&linkCode={link}"
)


def parse_private_link(value: str | None) -> tuple[str, str] | None:
    """Parse a private-server reference into (kind, code).

    Roblox changed the format in October 2023. Both are still in circulation:

      legacy  .../games/{id}?privateServerLinkCode={code}
      share   .../share?code={hex}&type=Server      <- current

    The share form deliberately drops the game id, so it cannot be turned into
    the old PlaceLauncher URL. Sober registers both the `roblox` and
    `roblox-player` schemes (checked in its .desktop MimeType), so a deeplink is
    at least accepted -- but MEASURED, none of the four we have tried joins:

      roblox://navigation/share_links?type=Server&code=...   -> app home page
      roblox://placeId={id}&linkCode={code}                  -> Join Error 524
      roblox://placeId={id}&accessCode={code}                -> Join Error 524
      https://www.roblox.com/games/start?placeId=..&linkCode=.. -> Error 524

    Error 524 is "You do not have permission to join this experience", raised
    behind the Bee Swarm loading screen -- so the URI routes to the right game
    and is refused at the access check. The share `code` is a share-link id that
    Roblox resolves server-side into the real private-server linkCode; passing
    the id where a linkCode belongs is consistent with exactly this failure.
    Resolving it needs an authenticated API call, so the supported route is the
    Roblox app's own server browser instead -- see nav/appui.py.

    A previous version of this comment claimed no server browser existed. That
    was measured on the *in-game* Escape menu, which indeed has only People /
    Settings / Gallery / Report / Help. Sober launches the full Roblox app UI,
    which does have a game page with a Servers tab; the earlier claim was drawn
    from too narrow a check.
    """
    if not value:
        return None
    value = value.strip()
    if "privateServerLinkCode=" in value:
        return ("legacy", value.split("privateServerLinkCode=")[1].split("&")[0].split("#")[0])
    if "share" in value and "code=" in value:
        code = value.split("code=")[1].split("&")[0].split("#")[0]
        return ("share", code)
    if "://" in value:
        raise ValueError(
            "could not find a private-server code in that URL - use the link from "
            "the server's Share button"
        )
    # a bare code: hex-looking ones are the new share format
    kind = "share" if len(value) >= 32 and all(c in "0123456789abcdefABCDEF" for c in value) else "legacy"
    return (kind, value)


def bss_uri(private_link: str | None = None) -> str:
    """Build the URI to hand Sober: public join, legacy private, or share link."""
    parsed = parse_private_link(private_link)
    if parsed and parsed[0] == "share":
        return f"roblox://navigation/share_links?type=Server&code={parsed[1]}"
    inner = (_PRIVATE.format(pid=BSS_PLACE_ID, link=parsed[1])
             if parsed else _PUBLIC.format(pid=BSS_PLACE_ID))
    return (f"roblox-player:1+launchmode:play+gameinfo:{BSS_PLACE_ID}"
            f"+placelauncherurl:{quote(inner, safe='')}")

# Lua, not hyprlang. Two reasons, both load-bearing:
#   * hyprlang support is REMOVED in Hyprland 0.57, which Arch will deliver on its
#     own schedule, and a silently-broken sandbox is the worst failure mode
#   * on 0.56 the deprecation warning is painted across the top-right of the
#     output -- directly over pixels we capture and run vision on. Observed in
#     the first real Sober capture.
CONFIG = """\
hl.monitor({{ output = "", mode = "{w}x{h}@60", position = "auto", scale = 1 }})

hl.config({{
    general = {{ gaps_in = 0, gaps_out = 0, border_size = 0, allow_tearing = true }},
    decoration = {{
        rounding = 0,
        blur   = {{ enabled = false }},
        shadow = {{ enabled = false }},
    }},
    animations = {{ enabled = false }},
    misc = {{
        disable_hyprland_logo    = true,
        force_default_wallpaper  = 0,
        vrr                      = 2,
        render_unfocused_fps     = 60,   -- keeps rendering while unfocused
        disable_xdg_env_checks   = true,
        anr_missed_pings         = 3,
        disable_watchdog_warning = true, -- we launch the bare binary on purpose
    }},
    ecosystem = {{ no_update_news = true, no_donation_nag = true }},
}})

-- misc.render_unfocused_fps sets the RATE; this per-window rule is the opt-in.
-- Without it the game is starved of frame callbacks whenever it is not focused,
-- which measured as ~1 fps (10 of 15 captured frames byte-identical).
hl.window_rule({{
    name  = "hivemind-render-unfocused",
    match = {{ class = "org.vinegarhq.Sober" }},
    render_unfocused = true,
}})
"""


def _sockets() -> set[str]:
    return {p.name for p in RUNTIME.glob("wayland-*") if p.name[8:].isdigit()}


def _signatures() -> set[str]:
    d = RUNTIME / "hypr"
    return {p.name for p in d.iterdir()} if d.is_dir() else set()


# THE COMPOSITOR'S OWN WINDOW ON THE OWNER'S DESKTOP. The nested Hyprland is
# a window on KDE, "aquamarine - WAYLAND-1", and a minimized window is given no
# frames to draw. MEASURED 2026-09-27 (attempt 497): found minimized at 12:27
# while the owner played Unturned, with every capture timing out since
# 12:24:41 ("no frame from the compositor within 5.0s") and the trip before it
# gathering nothing, the pollen counter unread for 727 s -- while Hyprland
# itself reported WAYLAND-1 enabled and Sober mapped. KWin says so over
# D-Bus: its window runner finds the window by that name ("0_{uuid}"), and
# getWindowInfo(uuid) gives its pid -- this session's Hyprland -- and
# "minimized: true".
KWIN_QDBUS = "qdbus6"
KWIN_QDBUS_TIMEOUT_S = 3.0
HOST_WINDOW_QUERY = "aquamarine"
# AND A NEW WINDOW TAKES THE OWNER'S KEYBOARD. MEASURED 2026-09-27 13:05:58
# (attempt 498): with the owner playing Unturned, the session's new window was
# KWin's active window as soon as it opened, so his keys -- chat included, on
# stream -- would have gone to Roblox. The bot's own input never needed that
# focus (its virtual keyboard and pointer are on the nested compositor's own
# socket), and a window covered by his own still draws (checked the same
# minute: the live view kept updating under fullscreen Unturned). So a new
# window that took the keyboard gives it back to the window he had on top:
# re-stacked below that one, never pinned below and never minimized (a
# minimized window draws nothing, above), so a click still brings it up.
# KWin's scripting does it (loadScript/run over qdbus6); its console line in
# the user journal, tagged per call, is how the result is known.
HOST_WINDOW_WAIT_S = 10.0
# AND A MINIMIZED WINDOW IS PUT BACK BELOW HIS, not left blind. The owner
# minimizes it out of his way (2026-09-27 12:27 and 13:33, both while he
# played Unturned), and his word is "u can continue the bot": so it is
# restored with KWin's keep-below, under whatever he has on top -- which
# still draws (measured, above) -- and the window he was using keeps the
# keyboard. Stopping the bot is the Pause button's job, not the taskbar's.
RESTORE_SCRIPT = """
const ws = workspace.windowList();
const prev = workspace.activeWindow;
let did = "no window";
for (let i = 0; i < ws.length; i++) {
  const w = ws[i];
  if (w.pid == %(pid)d && w.resourceClass == "%(cls)s") {
    w.keepBelow = true;
    w.minimized = false;
    did = w.minimized ? "still minimized" : "restored below";
  }
}
if (prev !== null && workspace.activeWindow !== prev) { workspace.activeWindow = prev; }
console.info("%(tag)s " + did);
"""
# AND ITS WINDOW IS THE OUTPUT'S SIZE. MEASURED 2026-10-21 01:04-02:51: after a
# server shutdown the relaunched session's window on his desktop opened at
# 1280x720, so the nested output was 1280x720 (nested.lua asks 1920x1080, but a
# nested compositor's output follows its host window) -- every menu frame was
# 1280 wide and, in the world, the HUD reader (measured on 1920x1080) found no
# HUD and stopped. Resizing the window to the session's size fixes the output.
SIZE_SCRIPT = """
const ws = workspace.windowList();
let did = "no window";
for (let i = 0; i < ws.length; i++) {
  const w = ws[i];
  if (w.pid == %(pid)d && w.resourceClass == "%(cls)s") {
    w.noBorder = true;
    const g = w.frameGeometry;
    w.frameGeometry = {x: g.x, y: g.y, width: %(width)d, height: %(height)d};
    did = "sized";
  }
}
console.info("%(tag)s " + did);
"""
FOCUS_SCRIPT = """
const ws = workspace.windowList();
let mine = null, top = null;
for (let i = 0; i < ws.length; i++) {
  const w = ws[i];
  if (w.pid == %(pid)d && w.resourceClass == "%(cls)s") { mine = w; continue; }
  if (w.normalWindow && !w.minimized && (top === null || w.stackingOrder > top.stackingOrder)) top = w;
}
let did = "left alone";
if (mine !== null && top !== null && workspace.activeWindow === mine) {
  workspace.activeWindow = top;
  did = "gave the keyboard back to " + top.resourceClass;
} else if (mine === null) {
  did = "no window";
}
console.info("%(tag)s " + did);
"""


# A HELD ALT THE BOT'S OWN KEYBOARD CANNOT LET GO OF. MEASURED 2026-10-05
# 22:41-22:58: every slot-1 press was Roblox's Capture (Alt+1). The nested
# compositor holds two keyboards (`hyprctl devices`: the desktop's forwarded
# wl_keyboard and the bot's virtual one, the main), and the Alt went down on the
# desktop's while this window had the focus; taps from the virtual keyboard and
# a focus round on the desktop (22:51) let go of nothing. The compositor's own
# key-state dispatcher (Lua API, Hyprland 0.56: hl.dsp.send_key_state) sends
# Alt up to the game's window -- after it (22:59) a "1" brought no Capture.
ALT_UP = ('hl.dsp.send_key_state({{ mods = "", key = "{key}", state = "up", '
          'window = "class:org.vinegarhq.Sober" }})')


# A SESSION KEPT ACROSS A RESTART (the owner's list, 2026-10-02, item 18).
# Every deploy ended run_farm, and its teardown ended the game with it, so
# every deploy was a rejoin -- and a rejoin resets the owner's Wealth Clock
# streak (1, 2, 3, 4, then 5 tickets an hour) and costs ~45 s of joining,
# with the chance of a box only he may answer (06:40 that morning). A run
# asked to keep the game closes only its own capture and input and writes
# this record; the next run attaches to the same compositor and game.
#
# CHECKED BY WHAT ONLY OURS CAN BE: the compositor, by exact PID, runs OUR
# config path (Session.clear_stale's own test), and the game is a client of
# THAT compositor. The owner's Sober runs on his desktop, so it can never
# match -- and, as before, the game is never signalled: it exits with its
# compositor, which is the only thing ever ended here.
KEPT_FILE_NAME = "session.json"


def _proc_text(pid, name: str) -> bytes:
    try:
        return Path(f"/proc/{int(pid)}/{name}").read_bytes()
    except (OSError, ValueError, TypeError):
        return b""


def _cmdline(pid) -> str:
    return _proc_text(pid, "cmdline").replace(b"\0", b" ").decode("utf-8", "replace")


def _environ(pid) -> dict:
    out = {}
    for item in _proc_text(pid, "environ").split(b"\0"):
        key, sep, value = item.partition(b"=")
        if sep:
            out[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return out


def _program(pid) -> str:
    return os.path.basename(_proc_text(pid, "cmdline").split(b"\0")[0].decode(
        "utf-8", "replace")).lower()


def is_labwc(pid) -> bool:
    """`pid` runs the labwc binary (platform/wlr_session, RL1b)."""
    return _program(pid) == "labwc"


def ours_compositor(pid, config_path) -> bool:
    """`pid` is a compositor started with OUR config (Session.clear_stale's own
    test): a nested Hyprland, or a headless labwc run with `-C <our dir>`."""
    line = _cmdline(pid)
    return bool(line) and str(config_path) in line and (
        "hyprland" in line.lower() or is_labwc(pid))


def kill_marked(marker: str, program: str) -> int:
    """SIGTERM every process of `program` whose command line holds `marker`
    (our own config path) -- Session.clear_stale's rule, never this process.
    How many were signalled."""
    try:
        listing = subprocess.run(["pgrep", "-a", "-f", marker],
                                 capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return 0
    killed = 0
    for line in listing.stdout.splitlines():
        pid, _, command = line.partition(" ")
        if marker not in command or program not in command.lower():
            continue
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        if program == "labwc" and not is_labwc(pid):
            continue                 # its `-s` helper shell, not labwc
        try:
            os.kill(int(pid), signal.SIGTERM)
            killed += 1
        except OSError:
            pass
    return killed


def outliving(argv: list) -> list:
    """`argv` run under its own `setsid sh`, so the game outlives the run that
    started it (see `Session.launch_game` for the 19 Oct measurement): bwrap's
    --die-with-parent then watches the sh, not run_farm."""
    return ["setsid", "sh", "-c", '"$@"; exit $?', "hivemind-game"] + list(argv)


def game_in(signature: str) -> bool:
    """OUR compositor (by its instance signature) has the game's window as a
    client -- bootstrap's own test that Sober opened. The owner's Sober can
    never be a client of the nested compositor. MEASURED 2026-10-02: the
    game's own processes cannot be read from outside its sandbox (bwrap
    clears the launcher's environment; /proc/<pid>/environ inside is denied),
    so the compositor's word is the check."""
    if not signature:
        return False
    env = {**os.environ, "HYPRLAND_INSTANCE_SIGNATURE": signature}
    try:
        out = subprocess.run(["hyprctl", "clients"], env=env, capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "class: org.vinegarhq.sober" in out.lower()


def kept_session(path, config_path) -> dict | None:
    """The kept session's record when its compositor and game are still the
    ones it names and its socket is there, else None."""
    return kept_session_why(path, config_path)[0]


def kept_session_why(path, config_path) -> tuple[dict | None, str]:
    """`kept_session`, and in words why a record was refused. MEASURED
    2026-10-19 08:15: run-1067 detached and kept its game, run-1068 started
    a fresh Sober instead -- the record refused without a word, so which
    check failed could not be told."""
    import json
    try:
        body = json.loads(Path(path).read_text())
    except OSError:
        return None, "no kept-session record"
    except ValueError:
        return None, "the kept-session record is not readable JSON"
    if not isinstance(body, dict):
        return None, "the kept-session record is not a record"
    socket, sig = str(body.get("socket") or ""), str(body.get("signature") or "")
    if not socket or not sig:
        return None, "the record names no socket or game"
    if not (RUNTIME / socket).exists():
        return None, f"the kept compositor's socket {socket} is gone"
    if not ours_compositor(body.get("hypr_pid"), config_path):
        return None, f"compositor pid {body.get('hypr_pid')} is not ours any more"
    # a labwc record (wlr_session) asks its compositor over foreign-toplevel
    if is_labwc(body.get("hypr_pid")):
        from .wlr_session import game_in_socket
        there = game_in_socket(socket)
    else:
        there = game_in(sig)
    if not there:
        return None, "the kept game is no longer running in that compositor"
    return body, ""


def keep_session(path, *, game_pid: int, joined_at: float | None, **extra) -> None:
    """Write the kept-session record (platform/api KeptGame). The Linux
    fields -- socket, signature, hypr_pid -- come in `extra` and lead the
    record, so the JSON on disk is key for key what it always was."""
    import json
    body = {k: extra.pop(k) for k in ("socket", "signature", "hypr_pid") if k in extra}
    if "hypr_pid" in body:
        body["hypr_pid"] = int(body["hypr_pid"])
    body.update({"game_pid": int(game_pid), "joined_at": joined_at,
                 "kept_at": time.time(), **extra})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(body, indent=1))
    os.replace(tmp, path)


def forget_session(path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def end_pid(pid, still_ours, wait_s: float = 5.0) -> bool:
    """SIGTERM `pid`, then SIGKILL after `wait_s` -- only while `still_ours()`
    says it is still the process we kept (a PID can be reused)."""
    if not pid or not still_ours():
        return False
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return False
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if not Path(f"/proc/{int(pid)}").exists():
            return True
        time.sleep(0.2)
    if still_ours():
        try:
            os.kill(int(pid), signal.SIGKILL)
        except OSError:
            pass
    return True


@dataclass
class Session:
    width: int = 1920
    height: int = 1080
    config_path: Path = field(default_factory=lambda: Path.home() / ".config/hivemind/nested.lua")
    proc: subprocess.Popen | None = None
    socket: str | None = None
    signature: str | None = None
    log: Path | None = None
    pid: int | None = None          # an ATTACHED compositor's, which has no Popen
    headless: bool = field(default_factory=lambda: ROLE == "alt")   # see ROLE

    # ---- compositor -------------------------------------------------------
    def start(self, timeout: float = 20.0, attempts: int = 3) -> "Session":
        """Launch the nested compositor, retrying a start that does not take.

        MEASURED: after the OOM killer ended two runs, four consecutive starts
        failed with "no wayland socket appeared" while a hand-run `hyprland`
        with the same config produced its socket in ONE second. Nothing was
        wrong with the config or the detection -- the machine was still
        recovering, and Hyprland quietly failed to come up.

        That is precisely the failure an unattended overnight run must survive:
        a single flaky start should cost seconds, not the night. Each attempt
        cleans up its own half-started process before the next one, so retries
        cannot leave a pile of orphaned compositors behind.
        """
        # A crash does not run `finally`, so a previous compositor can still
        # be alive with the game inside it -- and Sober refuses to start twice:
        # "An instance of Sober is already running." MEASURED after a
        # libwayland abort took the bot down: two orphaned Sober processes and
        # a nested Hyprland survived, and every restart then failed with "app
        # never reached home (stuck on loading)" until they were cleared.
        self.clear_stale()

        last: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                return self._start_once(timeout)
            except (RuntimeError, TimeoutError) as exc:
                last = exc
                self.stop()              # never leave a half-started one behind
                if attempt < attempts:
                    time.sleep(2.0 * attempt)
        raise last if last else RuntimeError("compositor would not start")

    def clear_stale(self) -> int:
        """Kill a nested compositor left behind by a previous run.

        IDENTIFIED BY OUR OWN CONFIG PATH, and that is the whole safety
        argument. The owner plays this game himself, and killing his session
        would be unforgivable -- so this never matches on "sober", "roblox" or
        "hyprland". It matches only a Hyprland invoked with
        `-c <our config path>`, which nothing but this class ever writes.

        The game is not killed directly either. It is a client of that
        compositor, so it exits when the compositor does; targeting the
        compositor means a Sober on the HOST display cannot be caught by this
        even in principle. Verified in practice: killing the nested Hyprland
        left zero orphaned Sober processes behind.
        """
        killed = kill_marked(str(self.config_path), "hyprland")
        # AND A HEADLESS LABWC OF OURS (platform.compositor was "labwc" for
        # the last run): Sober refuses to run twice, so its game would block
        # this start. Matched by OUR labwc config dir, the same rule.
        from .wlr_session import CONFIG_DIR
        killed += kill_marked(str(CONFIG_DIR), "labwc")
        if self.headless:
            killed += self._end_parent()
        if killed:
            time.sleep(3.0)      # let its clients notice and exit
        return killed

    def _start_once(self, timeout: float) -> "Session":
        hypr = shutil.which("hyprland") or shutil.which("Hyprland")
        if not hypr:
            raise RuntimeError("hyprland is not installed")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(CONFIG.format(w=self.width, h=self.height))

        env = None
        if self.headless:
            self._start_parent(timeout)
            # its parent, never the desktop; no seat to try for; and not one
            # variable pushed into the user's systemd environment
            env = {**os.environ, "WAYLAND_DISPLAY": PARENT_SOCKET,
                   "LIBSEAT_BACKEND": "seatd", "HYPRLAND_NO_SD_VARS": "1"}
            env.pop("DISPLAY", None)
        before_s, before_g = _sockets(), _signatures()
        self.log = self.config_path.parent / "nested.log"
        with open(self.log, "wb") as fh:
            self.proc = subprocess.Popen([hypr, "-c", str(self.config_path)],
                                         stdout=fh, stderr=subprocess.STDOUT, env=env)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            new = _sockets() - before_s
            if new:
                self.socket = sorted(new)[0]
                break
            if self.proc.poll() is not None:
                raise RuntimeError(f"compositor exited immediately; see {self.log}")
            time.sleep(0.2)
        else:
            self.stop()
            raise TimeoutError(f"no wayland socket appeared; see {self.log}")

        for _ in range(40):
            new = _signatures() - before_g
            if new:
                self.signature = sorted(new)[0]
                break
            time.sleep(0.1)
        time.sleep(0.8)          # let the output settle before clients connect
        return self

    def _start_parent(self, timeout: float) -> None:
        """The display-less parent (see ROLE), its own session: an attached
        run's stop and clear_stale find it again by PARENT_MARK."""
        if _listening(RUNTIME / PARENT_SOCKET):
            return
        conf = self.config_path.parent / "parent"
        conf.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "XDG_CONFIG_HOME": str(conf)}
        for key in ("WAYLAND_DISPLAY", "DISPLAY"):
            env.pop(key, None)
        with open(self.config_path.parent / "parent.log", "wb") as fh:
            subprocess.Popen(parent_argv(self.width, self.height, render_node()),
                             env=env, stdout=fh, stderr=subprocess.STDOUT,
                             start_new_session=True)
        deadline = time.monotonic() + timeout
        while not _listening(RUNTIME / PARENT_SOCKET):
            if time.monotonic() > deadline:
                raise TimeoutError("the display-less parent compositor never "
                                   "listened; see parent.log")
            time.sleep(0.2)

    def _end_parent(self, wait_s: float = 5.0) -> int:
        """End this user's parent compositor(s); bwrap and dbus-run-session
        exit with it. How many were signalled."""
        pids = parent_pids()
        for pid in pids:
            end_pid(pid, lambda pid=pid: PARENT_MARK in _cmdline(pid), wait_s)
        return len(pids)

    # ---- hyprctl ----------------------------------------------------------
    def hyprctl(self, *args: str) -> str:
        env = {**os.environ, "HYPRLAND_INSTANCE_SIGNATURE": self.signature or ""}
        return subprocess.run(["hyprctl", *args], env=env, capture_output=True,
                              text=True).stdout.strip()

    def game_window_open(self) -> bool:
        """The game has opened a window in our compositor (platform/api
        GameSession; bootstrap's WINDOW_TIMEOUT wait)."""
        return "class:" in self.hyprctl("clients")

    def describe_windows(self) -> str:
        """The compositor's windows in words, for a start-failure report."""
        return self.hyprctl("clients")

    # NOTE: with a Lua config, `hyprctl dispatch` takes LUA, not the old
    # space-separated words -- it wraps the argument as hl.dispatch(<arg>), so
    # `dispatch fullscreen 0` becomes invalid Lua and fails silently-ish. All
    # forms below were verified against a live compositor.
    def dispatch(self, lua: str) -> str:
        return self.hyprctl("dispatch", lua)

    def add_headless_output(self, name: str = "HEADLESS-1") -> None:
        """Add an output driven by its own timer rather than by the parent
        compositor's frame callbacks."""
        self.hyprctl("output", "create", "headless")
        time.sleep(0.8)
        self.hyprctl("keyword", "monitor",
                     f"{name},{self.width}x{self.height}@60,2000x0,1")
        time.sleep(0.5)

    def move_to_headless(self, name: str = "HEADLESS-1") -> None:
        """Park the game on the headless output.

        Why this is not optional: the nested compositor is itself a KWin client,
        and KWin stops sending frame callbacks to a window that is unfocused or
        occluded. Measured: the game rendered 10 of 15 frames IDENTICAL -- about
        1 fps -- while the nested window sat behind a terminal. A headless output
        has its own clock, so nothing outside can starve it.
        """
        self.dispatch(f'hl.dsp.workspace.move({{monitor="{name}"}})')
        time.sleep(0.8)
        self.dispatch(f'hl.dsp.focus({{monitor="{name}"}})')
        time.sleep(0.5)

    def fullscreen_focused(self) -> None:
        """Sober opens windowed and letterboxed; every screen coordinate depends
        on it filling the output exactly."""
        self.dispatch("hl.dsp.window.fullscreen()")

    def leave_fullscreen(self) -> None:
        """Drop the game out of fullscreen. The dispatcher toggles.

        WHY THIS EXISTS: handing the controls to a person.

        Fullscreen is what makes the game grab the pointer, and a grabbed
        pointer inside a nested compositor is a trapped one -- Hyprland
        honours the lock for its client, but Hyprland is not itself locked
        inside KWin, so the real cursor wanders off the window and the game
        stops receiving motion. From inside it looks frozen. The owner hit
        exactly this: "the mouse thats in the window is locked i cant move
        it", and could not open a quest menu.

        The bot still joins the server fullscreen, because every coordinate
        in `act/join.py` is measured against a 1920x1080 output. This is
        called afterwards, once the navigating is done and a human is about
        to take over.
        """
        self.dispatch("hl.dsp.window.fullscreen()")

    # ---- its window on the owner's desktop ---------------------------------
    def host_window_minimized(self) -> bool | None:
        """Is this compositor's own window minimized on the owner's desktop?
        None when that cannot be told: no qdbus6, no KWin, or no window of
        this session's pid. See HOST_WINDOW_QUERY."""
        if self.headless:                # no window on anyone's desktop
            return None
        pid = self.compositor_pid()      # an attached session has no proc
        qdbus = shutil.which(KWIN_QDBUS)
        if pid is None or qdbus is None:
            return None

        def ask(*args: str) -> str:
            return subprocess.run([qdbus, *args], capture_output=True, text=True,
                                  timeout=KWIN_QDBUS_TIMEOUT_S).stdout

        try:
            found = ask("--literal", "org.kde.KWin", "/WindowsRunner",
                        "org.kde.krunner1.Match", HOST_WINDOW_QUERY)
            for uuid in dict.fromkeys(re.findall(r"\{[0-9a-f-]{36}\}", found)):
                info = dict(line.split(": ", 1)
                            for line in ask("org.kde.KWin", "/KWin",
                                            "org.kde.KWin.getWindowInfo",
                                            uuid).splitlines()
                            if ": " in line)
                if info.get("pid") == str(pid):
                    return info.get("minimized") == "true"
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        return None

    def give_back_focus(self, wait_s: float = HOST_WINDOW_WAIT_S) -> str:
        """If this compositor's new window took the owner's keyboard, give it
        back to the window he had on top (FOCUS_SCRIPT). What was done, or ''
        when nothing could be (no KWin, no window of this pid in `wait_s`)."""
        if self.headless:
            return ""
        deadline = time.monotonic() + wait_s
        while self.host_window_minimized() is None:
            if time.monotonic() >= deadline:
                return ""
            time.sleep(0.5)
        return self._kwin_script(FOCUS_SCRIPT, "focus")

    def fit_host_window(self) -> str:
        """Size this compositor's window on the owner's desktop to the
        session's width x height (SIZE_SCRIPT), so the nested output is the
        1920x1080 every measured box assumes. What KWin said, or ''."""
        return self._kwin_script(SIZE_SCRIPT, "size")

    def restore_below(self) -> bool:
        """Un-minimize this compositor's window under the owner's windows
        (RESTORE_SCRIPT); True when KWin says it is restored."""
        return self._kwin_script(RESTORE_SCRIPT, "restore") == "restored below"

    def release_alt(self) -> str:
        """Both Alts let go of inside the compositor, to the game's window
        (ALT_UP): what hyprctl said for each."""
        if not self.signature:
            return "no compositor to ask"
        env = {**os.environ, "HYPRLAND_INSTANCE_SIGNATURE": self.signature}
        said = []
        for key in ("Alt_L", "Alt_R"):
            try:
                out = subprocess.run(["hyprctl", "dispatch", ALT_UP.format(key=key)], env=env,
                                     capture_output=True, text=True, timeout=5).stdout.strip()
            except (OSError, subprocess.SubprocessError) as exc:
                out = f"raised {exc}"
            said.append(f"{key} up: {out or 'no answer'}")
        return ", ".join(said)

    def _kwin_script(self, body: str, what: str) -> str:
        """Run one KWin script about this session's window over qdbus6 and
        return what its tagged console line said ('' when it could not run)."""
        if self.headless:
            return ""
        pid = self.compositor_pid()      # an attached session has no proc
        qdbus = shutil.which(KWIN_QDBUS)
        if pid is None or qdbus is None:
            return ""
        tag = f"HIVEMIND-{what.upper()}-{pid}-{int(time.time() * 1000)}"
        name = f"hivemind_{what}_{pid}"
        script = RUNTIME / f"{name}.js"
        try:
            script.write_text(body % {"pid": pid, "cls": HOST_WINDOW_QUERY, "tag": tag,
                                      "width": self.width, "height": self.height})

            def ask(*args: str) -> str:
                return subprocess.run([qdbus, "org.kde.KWin", *args], capture_output=True,
                                      text=True, timeout=KWIN_QDBUS_TIMEOUT_S).stdout.strip()

            number = ask("/Scripting", "org.kde.kwin.Scripting.loadScript", str(script), name)
            if not number.lstrip("-").isdigit() or int(number) < 0:
                return ""
            ask(f"/Scripting/Script{number}", "org.kde.kwin.Script.run")
            time.sleep(0.5)
            ask("/Scripting", "org.kde.kwin.Scripting.unloadScript", name)
            said = subprocess.run(["journalctl", "--user", "--since", "-20s", "-o", "cat"],
                                  capture_output=True, text=True,
                                  timeout=KWIN_QDBUS_TIMEOUT_S).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
        finally:
            try:
                script.unlink()
            except OSError:
                pass
        for line in said.splitlines():
            if tag in line:
                return line.split(tag, 1)[1].strip()
        return ""

    # ---- the game ----------------------------------------------------------
    def launch_game(self, private_link: str | None = None) -> subprocess.Popen:
        if not self.socket:
            raise RuntimeError("compositor not started")
        uri = bss_uri(private_link)
        env = {**os.environ, "WAYLAND_DISPLAY": self.socket}
        env.pop("DISPLAY", None)          # force Wayland, not XWayland
        # THE GAME OUTLIVES THE RUN THAT STARTED IT. MEASURED 2026-10-19 08:15
        # and 08:32: after flatpak 1.18.4 / bubblewrap 0.13.1 (17 Oct 20:02)
        # `flatpak run` execs bwrap in place, so bwrap -- started with
        # --die-with-parent -- had run_farm itself as its parent, and every
        # keep-the-game restart killed the game with the run (the Sober scope
        # "Consumed ... over 10h 41min" ending at the detach second; the next
        # run: "the kept game is no longer running in that compositor"). A
        # small sh in its own session is the parent instead: nothing ends it
        # when the run exits, and terminating it (Popen.terminate, as `close`
        # does) still ends the game through bwrap's own death-with-parent.
        return subprocess.Popen(outliving([SOBER, uri]), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def attach(cls, record: dict, width: int = 1920, height: int = 1080) -> "Session":
        """The kept session's compositor (`kept_session`), not started here."""
        return cls(width=width, height=height, socket=str(record["socket"]),
                   signature=str(record["signature"]), pid=int(record["hypr_pid"]))

    def compositor_pid(self) -> int | None:
        return self.proc.pid if self.proc is not None else self.pid

    # ---- teardown ----------------------------------------------------------
    def stop(self) -> None:
        if not self.proc:
            if self.pid:
                end_pid(self.pid, lambda: ours_compositor(self.pid, self.config_path))
                self.pid = None
        else:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            # a non-zero/segv exit here is Hyprland's known shutdown crash, not ours
            self.proc = None
        if self.headless:
            self._end_parent()

    def __enter__(self): return self.start()
    def __exit__(self, *exc): self.stop()
