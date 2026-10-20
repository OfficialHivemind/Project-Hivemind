"""From nothing to standing in the game, in one call.

Every session starts the same way: bring up the nested compositor, launch Sober,
wait for the app shell, navigate to the private server, and confirm the world is
actually on screen. Each of those steps has a way of failing that is worth
distinguishing, so this returns a `Ready` describing what happened rather than
raising a generic error.

The private server is the default rather than a public join. The owner asked for
it -- "this prolly is cleaner and wont raise suspictioun" -- and they are right
for a second reason: a private server has no other players, so nothing walks in
front of the camera mid-measurement, and optical flow sees only the world moving.
Every calibration run is quieter and more repeatable there.

MEASURED, and the reason the UI route exists at all: all four private-server
deeplink formats fail. Three return Join Error 524 behind the Bee Swarm loading
screen and the share-link form lands on the app home. Navigating the app's own
server browser works, takes about 40 seconds, and needs no credentials.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ..platform import current, lastserver
from ..platform import session as session_mod
from ..platform.api import Capture, CaptureFailed, GameSession, Input, PanicKey
from ..platform.session import BSS_PLACE_ID
from ..stream import privacy
from ..vision import screenstate as ss
from ..vision import templates as T
from ..world.settings import Settings
from .appui import AppUI
from .join import join_private_server

SOBER = "org.vinegarhq.Sober"
# HOW LONG TO WAIT FOR SOBER'S WINDOW. Raised from 60 s on 2026-09-20 after
# two consecutive overnight attempts failed with "Sober never opened a window"
# and had to be retried from scratch.
#
# A healthy launch shows the window in about 9 s ("app home after 7s", "8s",
# "9s" across the night), so this ceiling is never reached when things are
# well. It is reached when the machine is busy -- the failures both came
# immediately after a previous session's teardown, with swap full -- and the
# poll loop below exits the moment the window appears, so a larger number
# costs nothing on a good launch and saves a whole retry cycle on a slow one.
WINDOW_TIMEOUT = 150.0
APP_TIMEOUT = 150.0
WORLD_TIMEOUT = 300.0
# How long the link to the server the account was last in (platform/lastserver)
# is given to reach the world before the usual join takes over: APP_TIMEOUT's
# allowance for the app, the same again being generous for one join.
LINK_TIMEOUT = 150.0

# WHAT A START THAT RAISED LEAVES BEHIND, so the caller can put it away.
# Every return from `start` hands these to a `Ready`, whose `close` ends them;
# a raise in between stranded them. MEASURED in run-367.log:3-34: four
# "capture handshake failed", a CaptureFailed traceback out of run_farm's
# main, and the nested Hyprland and Sober (pid 68933) still running when the
# watchdog launched attempt 368's pair (pid 69083). Only these handles may end
# them -- this project never kills Sober or Roblox by name (DESIGN 8ds).
_STARTING: dict = {}


def abandon_start() -> None:
    """Put away what a `start` that raised had already brought up: every key
    released, the panic watcher stopped, OUR Sober ended through its own
    process handle, the nested session stopped. Safe when nothing is left."""
    held = dict(_STARTING)
    _STARTING.clear()
    try:
        if held.get("panic") is not None:
            held["panic"].stop()
    except Exception:
        pass
    try:
        if held.get("input") is not None:
            held["input"].close()          # releases every key first
    except Exception:
        pass
    game = held.get("game")
    if game is not None:
        try:
            game.terminate()
            game.wait(timeout=5)
        except subprocess.TimeoutExpired:
            game.kill()
        except Exception:
            pass
    session = held.get("session")
    if session is not None:
        try:
            session.stop()
        except Exception:
            pass


@dataclass
class Ready:
    """A live session with the game on screen."""
    session: GameSession
    conn: object                     # what the capture rides on (current.connect)
    capture: Capture
    input: Input
    ui: AppUI
    ok: bool
    reason: str
    seconds: float
    _game: subprocess.Popen | None = None
    panic: PanicKey | None = None
    # KEPT FROM THE LAST RUN (platform/session KEPT_FILE_NAME): no join, and
    # the server session's own start, for the Wealth Clock's hour
    attached: bool = False
    joined_at: float | None = None

    def _close_ours(self) -> None:
        """This run's own handles, keys first: the panic watcher, the input,
        the capture -- never the game or the compositor."""
        if self.panic:
            self.panic.stop()
        try:
            self.input.close()          # releases every key first
        except Exception:
            pass
        for closer in (self.capture, self.conn):
            try:
                closer.close()
            except Exception:
                pass

    def close(self) -> None:
        """Tear down in the order that avoids leaving a key held."""
        self._close_ours()
        if self._game:
            self._game.terminate()
            time.sleep(1)
        self.session.stop()             # an attached one by its verified pid

    def detach(self, path, joined_at: float | None = None) -> bool:
        """End this run and KEEP the game: its handles closed, the session
        written to `path` for the next run's `start` to attach to. False (and
        a full `close`) when there is nothing to keep."""
        pid = self.session.compositor_pid()
        game = self._game.pid if self._game is not None else None
        self._close_ours()
        if current.WINDOWS:
            # THE GAME'S OWN PID AND START TIME (win/session): no compositor.
            fields = self.session.kept_fields() if self.ok else None
            if fields:
                current.kept.keep_session(
                    path, game_pid=pid, **fields,
                    joined_at=joined_at if joined_at is not None else self.joined_at)
                return True
        if current.WINDOWS or not (self.ok and pid and self.session.socket
                                   and self.session.signature):
            if self._game:                   # nothing worth keeping: ended as `close` does
                self._game.terminate()
                time.sleep(1)
            self.session.stop()
            return False
        current.kept.keep_session(path, socket=self.session.socket,
                                 signature=self.session.signature, hypr_pid=pid,
                                 game_pid=game or 0,
                                 joined_at=joined_at if joined_at is not None else self.joined_at)
        return True

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()


# THE CAPTURE HANDSHAKE IS A RACE, AND IT IS RETRIED. A fresh nested Hyprland
# advertises its output a moment after it accepts connections, and the
# screencopy protocol rejects a request against an output that is not ready
# with a protocol error the connection cannot recover from. MEASURED:
# attempt 143 (2026-09-22) died two seconds in with "compositor advertised no
# wl_output"; attempt 233 and the camera diag at 22:20 died on
# "zwlr_screencopy_manager_v1: error -1: invalid output" (RuntimeError 71)
# at the FIRST capture. The watchdog masked it at ~45 s a time; a script
# with no watchdog simply died. So the connection is made, one frame is
# asked for, and on any failure the connection is closed and remade a few
# times before giving up.
# ROBLOX'S "UPDATED AGREEMENTS" BOX IS THE OWNER'S TO ANSWER. MEASURED
# 2026-10-02 00:55-01:01: three launches in a row stopped at "app never reached
# home (stuck on unknown)", and the screen was the Roblox home with a box over
# it -- "Updated Agreements / To continue using Roblox, please select "I agree"
# to agree to our updated terms below. If you are a minor, please show this to
# your parent or guardian." -- and one button, I Agree. Accepting terms is his,
# never the bot's, so it is recognised (tesseract read it word for word off the
# box at x 640-1220, y 340-740 of 1920x1080), the screen kept, and the start
# reported as waiting for him -- not pressed, not retried as a mystery.
AGREEMENT_BOX = (640, 340, 1220, 740)
AGREEMENT_WORDS = ("updated agreements", "to agree to our")
NEEDS_THE_OWNER = ("Roblox shows its \"Updated Agreements\" box (Terms of Use, "
                   "Privacy Policy) and waits for I Agree — accepting terms is the "
                   "owner's, never the bot's: press I Agree in Roblox and the next "
                   "start joins by itself")


def agreements_waiting(frame, run=subprocess.run) -> bool:
    """Is Roblox's "Updated Agreements" box on this frame?"""
    import cv2
    if frame is None or getattr(frame, "size", 0) == 0:
        return False
    h, w = frame.shape[:2]
    sx, sy = w / 1920.0, h / 1080.0
    x0, y0, x1, y1 = AGREEMENT_BOX
    crop = frame[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx), :3]
    if crop.size == 0:
        return False
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    grey = cv2.resize(grey, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    ok, png = cv2.imencode(".png", grey)
    if not ok:
        return False
    try:
        out = run(["tesseract", "stdin", "stdout", "-l", "afr", "--psm", "6"],
                  input=png.tobytes(), capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    text = out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes) \
        else str(out.stdout)
    low = " ".join(text.lower().split())
    return all(word in low for word in AGREEMENT_WORDS)


CAPTURE_TRIES = 4
CAPTURE_RETRY_SECONDS = 1.5


def connect_capture(make_conn, make_capture, *, tries: int = CAPTURE_TRIES,
                    sleep=time.sleep, say=print):
    """Connect, build the capture and prove it with one frame -- retrying the
    whole handshake on any failure. Returns `(conn, capture)`; raises the last
    error when every try failed."""
    last: Exception | None = None
    for attempt_no in range(1, tries + 1):
        conn = None
        try:
            conn = make_conn()
            capture = make_capture(conn)
            frame = capture.capture()
            if frame is None:
                raise CaptureFailed("the first capture returned no frame")
            if attempt_no > 1:
                say(f"capture handshake succeeded on try {attempt_no}")
            return conn, capture
        except Exception as exc:
            last = exc
            say(f"capture handshake failed ({type(exc).__name__}: {exc}) — "
                f"reconnecting, try {attempt_no} of {tries}")
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            sleep(CAPTURE_RETRY_SECONDS)
    raise last if last is not None else CaptureFailed("no capture")


def start(private: bool = True, width: int = 1920, height: int = 1080,
          root: Path | None = None, verbose: bool = True,
          server: "lastserver.LastServer | None" = None,
          keep_from: Path | None = None, row_name: str = "") -> Ready:
    """Bring everything up and land in the game world. `row_name`: the
    Servers drawer row to join (act/join `find_named_button`), "" for his own.

    A START THAT RAISES PUTS AWAY WHAT IT BROUGHT UP (`abandon_start`), then
    raises -- for every caller, the diag scripts as well as run_farm. Every
    return hands the handles to a `Ready`, whose `close` ends them."""
    try:
        if keep_from is not None:
            kept = _attach(keep_from, width=width, height=height, root=root,
                           verbose=verbose)
            if kept is not None:
                return kept
        return _bring_up(private=private, width=width, height=height,
                         root=root, verbose=verbose, server=server,
                         row_name=row_name)
    except BaseException:
        abandon_start()
        if server is not None:
            lastserver.note_result(server, False)
        raise


# THE KEPT GAME IS LOOKED AT MORE THAN ONCE. It was judged from one frame:
# MEASURED 2026-10-13, run-960 11:49 (19 min after run-959 detached) and
# run-961 12:34 (3.7 min after run-960 detached, its last step closing the
# inventory) both said "the kept game is not in the world (no HUD) --
# starting afresh"; each rejoin rebooked the Wealth Clock (11:53 -> 12:49 ->
# 13:34) and it went about 2 h unused. No frame of either was kept. So it is
# looked at ATTACH_LOOKS times ATTACH_LOOK_GAP_S apart (about 5 s), and
# Roblox's menu, if a look POSITIVELY sees it (stream/privacy.menu_in_frame:
# 0 fires on 800 route and respawn frames of 10-13, all 3 menu fixtures
# seen), gets ONE Escape -- the key that closes it, as act/routes'
# `_leave_menu` presses it there; never on an unseen screen, where Escape
# OPENS that menu, and never Enter. A kept game still not in the world after
# that is given up, its last frame kept in var/join/ for the next look.
ATTACH_LOOKS = 6
ATTACH_LOOK_GAP_S = 1.0


def kept_game_in_world(look, in_world, menu_up, escape, *, looks: int = ATTACH_LOOKS,
                       gap: float = ATTACH_LOOK_GAP_S, sleep=time.sleep):
    """(seen, last frame, escaped): whether any of `looks` looks, `gap`
    apart, showed the world, with one `escape()` the first time a look shows
    Roblox's menu (`menu_up`). `look` returns a frame or None."""
    frame, escaped = None, False
    for n in range(looks):
        frame = look()
        if frame is not None and in_world(frame):
            return True, frame, escaped
        if frame is not None and not escaped and menu_up(frame):
            escape()
            escaped = True
        if n < looks - 1:
            sleep(gap)
    return False, frame, escaped


def _attach(path: Path, width: int, height: int, root: Path | None,
            verbose: bool) -> Ready | None:
    """The last run's kept session (platform/session `kept_session`), joined
    to instead of started: a Ready on it when the world is on screen, else
    None -- with the record forgotten either way, so a later start never
    tries it twice, and a session that is not in the world left for `start`'s
    own `clear_stale` to end."""
    root = root or Path(__file__).resolve().parents[3]
    started = time.monotonic()

    def say(message: str) -> None:
        if verbose:
            print(f"  {message}", flush=True)
    probe = current.make_session(width, height)
    record, why = current.kept.kept_session_why(path, probe.config_path)
    current.kept.forget_session(path)
    if record is None:
        if why != "no kept-session record":
            say(f"not attaching to the kept game: {why} — starting afresh (a rejoin)")
        return None
    session = current.attach_session(record, width, height)
    say(f"the last run kept its game (Roblox pid {session.pid}) — attaching instead "
        f"of rejoining" if current.WINDOWS else
        f"the last run kept its game (compositor pid {session.pid}, "
        f"{session.socket}) — attaching instead of rejoining")
    templates = ss.load_templates(root / "data/templates/digits")
    conn = capture = inp = panic = None
    try:
        conn, capture = connect_capture(
            lambda: current.connect(session), current.make_capture, say=say)
        inp = current.make_input(session)
        ui = AppUI(inp=inp, capture=capture, templates=templates)
        panic_key = Settings().get("safety.panic_key", "F12")
        panic = current.make_panic(inp.release_all, str(panic_key)).start()
        say(f"panic key: {panic.reason}")
        def look():
            try:
                return ui.frame()
            except Exception:
                return None

        def escape():
            say("the kept game shows Roblox's menu — one Escape to close it")
            inp.focus_game()      # Roblox needs a pointer-enter before keys register
            time.sleep(0.3)
            inp.tap("escape")

        seen, frame, escaped = kept_game_in_world(look, ss.hud_present,
                                                  privacy.menu_in_frame, escape)
        if not seen:
            kept = ""
            try:
                if frame is not None:
                    import cv2
                    out = root / "var" / "join"
                    out.mkdir(parents=True, exist_ok=True)
                    kept = f"{time.strftime('%H%M%S')}-kept_game_no_hud.png"
                    cv2.imwrite(str(out / kept), frame[:, :, :3])
            except Exception:
                kept = ""
            say(f"the kept game is not in the world (no HUD in {ATTACH_LOOKS} looks over "
                f"{ATTACH_LOOK_GAP_S * (ATTACH_LOOKS - 1):.0f}s"
                + (", after one Escape for Roblox's menu" if escaped else "")
                + (f"; the screen is var/join/{kept}" if kept else "")
                + ") — starting afresh")
            Ready(session, conn, capture, inp, ui, False, "", 0.0, None, panic)._close_ours()
            return None
        if current.WINDOWS:
            say(session.fullscreen_focused())   # a kept game's window, checked too
        inp.focus_game()          # Roblox needs a pointer-enter before keys register
        time.sleep(0.8)
        say(f"in game after {time.monotonic() - started:.0f}s, the server session kept")
        return Ready(session, conn, capture, inp, ui, True, "in game (kept)",
                     time.monotonic() - started, None, panic, attached=True,
                     joined_at=record.get("joined_at"))
    except Exception as exc:
        say(f"could not attach to the kept game ({type(exc).__name__}: {exc}) "
            f"— starting afresh")
        for closer in (panic and panic.stop, inp and inp.close,
                       capture and capture.close, conn and conn.close):
            try:
                if closer:
                    closer()
            except Exception:
                pass
        return None


def _launch_sober(session, private: bool, server, root: Path, say) -> subprocess.Popen:
    """Linux: Sober into the nested session (the app shell for a private
    join, or the server's link)."""
    env = {**os.environ, "WAYLAND_DISPLAY": session.socket}
    env.pop("DISPLAY", None)
    # With no URI Sober opens the app shell, which is where the server browser
    # lives. A public join can skip straight to the world.
    argv = [SOBER] if private else [SOBER, f"roblox://placeId={BSS_PLACE_ID}"]
    # THE SERVER THE ACCOUNT WAS JUST IN, by its link (platform/lastserver,
    # `account.join_last_server`): the JobId is in this argv and nowhere else.
    if server is not None:
        argv = [SOBER, server.uri()]
    # THE ALT'S COPY IN ITS OWN NETWORK (tools/alt/sober-netns.sh): Sober will
    # not run a second copy on the PC otherwise, even as another Linux user.
    if session_mod.ROLE == "alt":
        argv = [str(root / "tools" / "alt" / "sober-netns.sh")] + argv[1:]
    # KEEP WHAT SOBER SAYS. This used to send both streams to DEVNULL, so a
    # launch that produced no window left the single line "Sober never opened a
    # window" and nothing whatsoever to read -- and that happened again on
    # 2026-09-21 at 23:19, costing a whole attempt and a manual reproduction to
    # find out that the very same launch works on the next try. Sober's own log
    # names the renderer, the manifest and every missing font; it is a few KB a
    # launch and it is the only account of why a launch failed.
    #
    # Truncated per launch rather than appended to: the interesting log is
    # always the one from the attempt that just failed, and an append would
    # bury it under the successful ones.
    sober_log = root / "var" / "sober.log"
    try:
        sober_log.parent.mkdir(parents=True, exist_ok=True)
        sink = open(sober_log, "wb")
    except OSError:
        sink = subprocess.DEVNULL
    # THE GAME OUTLIVES THIS RUN (session_mod.outliving): since the 17 Oct
    # flatpak/bubblewrap update bwrap's --die-with-parent watched run_farm, so
    # every keep-the-game restart killed the game (19 Oct 08:15, 08:32, 09:0x).
    game = subprocess.Popen(session_mod.outliving(argv), env=env, stdout=sink,
                            stderr=subprocess.STDOUT)
    _STARTING["game"] = game
    if sink is not subprocess.DEVNULL:
        sink.close()          # the child holds its own copy of the descriptor
    say(f"sober: pid {game.pid}, log {sober_log}")
    return game


# WINDOWS JOINS BY LINK (platform/win/session, WHICH LINK): the Windows
# player has no app shell, so the Servers drawer act/join walks on Sober is
# not there. A link -- the share link (server.link), the last server's, a
# friend's -- or, with none, the place itself: a public server.
WINDOWS_PUBLIC = ("no private server link set, joining a public Bee Swarm server "
                  "(set Settings > Server > link to use your private server)")


def _launch_windows(session, private: bool, server, say) -> subprocess.Popen:
    """Windows: Roblox by deep link (win/session.launch_game)."""
    if server is None and private:
        # NO LINK IS NO LONGER A STOP (owner, 19 Oct: needing a link makes
        # Windows harder): a public Bee Swarm server, roblox://placeId=...
        say(WINDOWS_PUBLIC)
    game = session.launch_game(server.uri() if server is not None else None)
    _STARTING["game"] = game
    say(f"roblox: launched by deep link (pid {game.pid})")
    # THE WINDOW BEFORE THE CAPTURE: on Linux capture rides the compositor,
    # there before the game; here it is the game's window (win/capture), so
    # the handshake would fail on a window that is not open yet.
    deadline = time.monotonic() + WINDOW_TIMEOUT
    while not session.game_window_open():
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Roblox never opened a window in {WINDOW_TIMEOUT:.0f}s "
                               f"(Roblox windows: {session.describe_windows()})")
        time.sleep(1)
    say(session.fullscreen_focused())      # the client sized before the capture crops it
    return game


def _bring_up(private: bool, width: int, height: int, root: Path | None,
              verbose: bool, server=None, row_name: str = "") -> Ready:
    """The body of `start`."""
    root = root or Path(__file__).resolve().parents[3]
    started = time.monotonic()

    def say(message: str) -> None:
        if verbose:
            print(f"  {message}", flush=True)

    templates = ss.load_templates(root / "data/templates/digits")
    session = current.make_session(width, height)
    session.start()
    # THE OWNER'S KEYBOARD STAYS HIS (platform/session HOST_WINDOW_WAIT_S).
    focus = session.give_back_focus()
    if focus and focus != "left alone":
        say(f"the game's new window took the keyboard — {focus}")
    # AND THE WINDOW IS THE OUTPUT'S SIZE (platform/session SIZE_SCRIPT): 2026-10-21
    # a relaunch's window opened at 1280x720 and every measured box missed.
    fit = getattr(session, "fit_host_window", None)
    if fit is not None:
        try:
            sized = fit()
        except Exception:
            sized = ""
        if sized and sized != "sized":
            say(f"the session's window could not be sized to {width}x{height}: {sized}")
    _STARTING.clear()
    _STARTING["session"] = session           # see abandon_start

    if current.WINDOWS:
        game = _launch_windows(session, private, server, say)
    else:
        game = _launch_sober(session, private, server, root, say)
    _STARTING["game"] = game

    conn, capture = connect_capture(
        lambda: current.connect(session), current.make_capture, say=say)
    inp = current.make_input(session)
    _STARTING["input"] = inp
    ui = AppUI(inp=inp, capture=capture, templates=templates)

    # The panic key is armed BEFORE anything can press a key, and it reads
    # /dev/input directly -- below the compositor -- so it still works if the
    # nested Hyprland wedges with W held down.
    panic_key = Settings().get("safety.panic_key", "F12")
    panic = current.make_panic(inp.release_all, str(panic_key)).start()
    _STARTING["panic"] = panic
    say(f"panic key: {panic.reason}")

    def finish(ok: bool, reason: str) -> Ready:
        _STARTING.clear()              # the Ready owns them now
        return Ready(session, conn, capture, inp, ui, ok, reason,
                     time.monotonic() - started, game, panic)

    def stuck(reason: str) -> Ready:
        """A start that stopped short: the owner's agreements box, said as
        such and its screen kept (AGREEMENT_BOX), or `reason`."""
        try:
            frame = ui.frame()
        except Exception:
            frame = None
        try:
            if frame is not None and agreements_waiting(frame):
                import cv2
                out = root / "var" / "join"
                out.mkdir(parents=True, exist_ok=True)
                name = f"{time.strftime('%H%M%S')}-updated_agreements.png"
                cv2.imwrite(str(out / name), frame[:, :, :3])
                say(f"{NEEDS_THE_OWNER} (the screen is var/join/{name})")
                return finish(False, NEEDS_THE_OWNER)
        except Exception as exc:
            say(f"could not look for the agreements box ({exc})")
        return finish(False, reason)

    deadline = time.monotonic() + WINDOW_TIMEOUT
    while time.monotonic() < deadline and not session.game_window_open():
        time.sleep(1)
    if not session.game_window_open():
        # A START BY THE LINK THAT NEVER OPENS A WINDOW IS THAT SERVER'S
        # FAILURE TOO. MEASURED 2026-09-29 21:50, the first launch by
        # platform/lastserver's link: Sober wrote its two libcurl warnings
        # and no session log, and no window came in WINDOW_TIMEOUT -- and
        # with nothing noted, every relaunch would have tried the same link.
        if server is not None:
            lastserver.note_result(server, False)
        return finish(False, "Roblox never opened a window" if current.WINDOWS
                      else "Sober never opened a window")
    sized = session.fullscreen_focused()
    if sized:
        say(sized)
    time.sleep(1)

    there = False
    if server is not None:
        say(f"joining the server this account was last in (server "
            f"{server.digest}) by its link")
        state = ui.wait_for(ss.Screen.IN_GAME, timeout=LINK_TIMEOUT)
        there = state is ss.Screen.IN_GAME
        lastserver.note_result(server, there)
        say(f"in the server this account was last in (server {server.digest})"
            if there else
            f"the link to server {server.digest} did not reach the world "
            f"(on {state.value}) — the usual join instead, and that server is "
            f"not tried again")
    if there:
        pass
    elif current.WINDOWS and server is not None:
        return stuck(f"the link to server {server.digest} did not reach the world "
                     f"(Windows joins by link only, so there is no drawer to fall back to)")
    elif private and not current.WINDOWS:     # Windows has no app home: a public join waits below
        state = ui.wait_for(ss.Screen.APP_HOME, ss.Screen.IN_GAME,
                            timeout=APP_TIMEOUT)
        if state is ss.Screen.IN_GAME:
            say("already in a world; not navigating")
        else:
            if state is not ss.Screen.APP_HOME:
                return stuck(f"app never reached home (stuck on {state.value})")
            say(f"app home after {time.monotonic() - started:.0f}s")
            label = T.load(root / "data/templates/ui/servers_label.png")
            try:
                tile = T.load(root / "data/templates/ui/bss_tile.png")
            except FileNotFoundError:
                tile = None
                say("no Bee Swarm tile template; the first Continue tile will be clicked")
            result = join_private_server(ui, label, timeout=WORLD_TIMEOUT, bss_tile=tile,
                                         name=row_name)
            if not result.ok:
                # KEEP THE SCREEN IT FAILED ON. Attempts 227 and 228 on
                # 2026-09-22 failed the join two different ways ("ended on
                # app_home", "no private-server Join button") with nothing to
                # look at afterwards, and a second capture client cannot be
                # attached to a live session to peek (DESIGN 8a: it killed the
                # game twice). One PNG per failure, named by the reason, is
                # the cheapest diagnosis there is. Never fatal: a failed save
                # must not change the outcome it is recording.
                try:
                    import cv2
                    frame = ui.frame()
                    if frame is not None:
                        out = root / "var" / "join"
                        out.mkdir(parents=True, exist_ok=True)
                        stamp = time.strftime("%H%M%S")
                        slug = "".join(c if c.isalnum() else "_"
                                       for c in result.reason)[:48]
                        cv2.imwrite(str(out / f"{stamp}-{slug}.png"), frame[:, :, :3])
                        say(f"saved the failing screen to var/join/{stamp}-{slug}.png")
                except Exception as exc:
                    say(f"could not save the failing screen ({exc})")
                return finish(False, result.reason)
    else:
        state = ui.wait_for(ss.Screen.IN_GAME, timeout=WORLD_TIMEOUT)
        if state is not ss.Screen.IN_GAME:
            return stuck(f"never reached the world (stuck on {state.value})")

    if current.WINDOWS:
        # CHECKED AGAIN IN THE WORLD: Roblox may resize its window while it
        # loads (run 5 ended at 1920x1009 with nothing said), so the size the
        # boxes need is verified -- and fixed -- once more here.
        say(session.fullscreen_focused())
    inp.focus_game()          # Roblox needs a pointer-enter before keys register
    time.sleep(0.8)
    say(f"in game after {time.monotonic() - started:.0f}s")
    return finish(True, "in game")
