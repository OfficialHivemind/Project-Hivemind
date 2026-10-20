#!/usr/bin/env python3
"""Join the owner's private server through the Roblox app's server browser.

The route, as the owner described it:

    "u go to bss the game right then u scroll down to severs go in it
     then u join my priv server"

This runs `act.join.join_private_server` for real and reports what happened at
each step, saving a frame at every stage so a failure can be diagnosed from the
pictures rather than from a guess.
"""
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import cv2

from hivemind.act.appui import AppUI
from hivemind.act.join import join_private_server
from hivemind.platform.input import VirtualInput
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy
from hivemind.vision import screenstate as ss
from hivemind.vision import templates as T

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path("/tmp/hivemind-diag/join")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    templates = ss.load_templates(ROOT / "data/templates/digits")
    servers_label = T.load(ROOT / "data/templates/ui/servers_label.png")

    session = Session(width=1920, height=1080)
    session.start()
    env = {**os.environ, "WAYLAND_DISPLAY": session.socket}
    env.pop("DISPLAY", None)
    game = subprocess.Popen(["org.vinegarhq.Sober"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    conn = inp = cap = None
    try:
        conn = WlConnection(session.socket).connect()
        cap = ScreenCopy(conn, output_index=0)
        inp = VirtualInput(socket=session.socket)
        ui = AppUI(inp=inp, capture=cap, templates=templates)

        t0 = time.monotonic()
        while time.monotonic() - t0 < 60 and "class:" not in session.hyprctl("clients"):
            time.sleep(1)
        session.fullscreen_focused()
        time.sleep(1)

        state = ui.wait_for(ss.Screen.APP_HOME, timeout=120)
        print(f"  app settled on {state.value} after {time.monotonic() - t0:.0f}s",
              flush=True)
        cv2.imwrite(str(OUT / "00_home.png"), cap.capture()[:, :, :3])

        result = join_private_server(ui, servers_label)

        cv2.imwrite(str(OUT / "99_final.png"), cap.capture()[:, :, :3])
        print(f"\n  RESULT: {'JOINED' if result.ok else 'FAILED'} — {result.reason}")
        print("\n  trace:")
        for t, msg in result.trace:
            print(f"    {t:6.1f}s  {msg}")

        if result.ok:
            frame = cap.capture()
            from hivemind.vision import digits
            x, y, w, h = ss.HONEY_REGION
            text, score = digits.read(frame[y:y + h, x:x + w], templates)
            print(f"\n  in-game HUD reads honey {text!r} (confidence {score:.3f})")
        return 0 if result.ok else 1
    finally:
        if inp:
            inp.close()
        if cap:
            cap.close()
        if conn:
            conn.close()
        game.terminate()
        time.sleep(1)
        session.stop()


if __name__ == "__main__":
    raise SystemExit(main())
