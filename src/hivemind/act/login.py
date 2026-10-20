"""The first-run Roblox login: Sober in the bot's own compositor, the owner
driving it through the GUI's live view (RL1b step 3).

    python -m hivemind.act.login

Headless (labwc) the game has no window anyone can click, so logging in to
Roblox happens in the live view: this brings up the session the bot would
(`platform.compositor`), opens Sober's app home, streams the picture to the
GUI and hands the controls to the owner at once (Controls.owner_drives). Their
mouse and keys come back down the same socket as GameInput and go into the
game through this process's own VirtualInput -- the one input path, as when
the bot plays. Nothing here presses anything of its own.

It ends on the GUI's Stop (the first-run window's "Done"), on SIGTERM, or
when Sober exits. Sober keeps the login in its own data dir, so the bot's
next start finds the account signed in. The socket is the bot's: while a bot
is running this refuses to start (EventServer: a server is already listening).
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from ..brain.controls import Controls
from ..ipc.bus import DEFAULT_SOCKET, EventServer
from ..platform import current
from ..telemetry.events import Log
from ..telemetry.liveview import LiveView
from ..world.settings import Settings
from . import bootstrap

ROOT = Path(__file__).resolve().parents[3]
READY_TEXT = ("Roblox is open. Click the picture and log in; press Done in the "
              "set-up window when you see the Roblox home.")


def main(socket: str = DEFAULT_SOCKET) -> int:
    def say(message: str) -> None:
        print(f"  {message}", flush=True)

    stop = threading.Event()
    controls = Controls()
    server = EventServer(socket, on_message=lambda event: (controls.handle(event),
                                                           controls.stopped and stop.set()))
    server.start()                          # refuses while the bot serves the socket
    controls.emit = server.send
    session = game = conn = capture = inp = live = None
    try:
        server.send(Log(message="opening Roblox for the login", source="login"))
        session = current.make_session()
        session.start()
        game = bootstrap._launch_sober(session, True, None, ROOT, say)
        conn, capture = bootstrap.connect_capture(
            lambda: current.connect(session), current.make_capture, say=say)
        inp = current.make_input(session)
        controls.vin = inp
        live = LiveView(capture.capture, server.send,
                        fps=LiveView.fps_from(Settings())).start()
        deadline = time.monotonic() + bootstrap.WINDOW_TIMEOUT
        while not session.game_window_open() and time.monotonic() < deadline:
            if stop.wait(1.0) or game.poll() is not None:
                break
        if session.game_window_open():
            say(session.fullscreen_focused() or "fullscreen")
        controls.owner_drives()
        server.send(Log(message=READY_TEXT, source="login"))
        say(READY_TEXT)
        while not stop.wait(1.0):
            if game.poll() is not None:
                say("Sober exited")
                break
        return 0
    except KeyboardInterrupt:                 # SIGTERM, through VirtualInput's handler
        return 0
    finally:
        for closer in (live and live.stop, inp and inp.close, capture and capture.close,
                       conn and conn.close):
            try:
                if closer:
                    closer()
            except Exception:
                pass
        if game is not None:
            game.terminate()
            try:
                game.wait(timeout=10)
            except Exception:
                game.kill()
        if session is not None:
            try:
                session.stop()
            except Exception:
                pass
        server.stop()


if __name__ == "__main__":
    sys.exit(main())
