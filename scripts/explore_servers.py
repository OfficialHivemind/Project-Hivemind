#!/usr/bin/env python3
"""Follow the owner's route to the private server and photograph every step.

    "u go to bss the game right then u scroll down to severs go in it
     then u join my priv server"

So: home page -> the Bee Swarm Simulator tile -> scroll down -> Servers.

Run 1 established that this UI is focus-and-activate, not type-anywhere: Slash
did not open search, and Enter activated whatever the focus ring had wandered
onto. So this run uses the mouse, and never presses Enter -- the page Enter
landed on last time carried "Log Out" and "Exit" as ordinary tiles.

MEASURED tile position: the Continue row's first entry is Bee Swarm Simulator,
thumbnail spanning x 128-258, y 862-990, so its centre is (193, 926). Verified
by cropping that rectangle out of the home capture and reading the label.
"""
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import cv2

from hivemind.act.appui import AppUI
from hivemind.platform.input import VirtualInput
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy
from hivemind.vision import screenstate as ss

OUT = pathlib.Path("/tmp/hivemind-diag/servers")
ROOT = pathlib.Path(__file__).resolve().parents[1]
BSS_TILE = (193, 926)
SCROLLS = 8


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    templates = ss.load_templates(ROOT / "data/templates/digits")
    session = Session(width=1920, height=1080)
    session.start()

    env = {**os.environ, "WAYLAND_DISPLAY": session.socket}
    env.pop("DISPLAY", None)
    game = subprocess.Popen(["org.vinegarhq.Sober"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    conn = inp = cap = None
    step = 0

    def shot(label: str):
        nonlocal step
        frame = cap.capture()
        state = ss.classify(frame, templates)
        cv2.imwrite(str(OUT / f"{step:02d}_{label}.png"), frame[:, :, :3])
        print(f"  {step:02d} {label:20s} {state.value}", flush=True)
        step += 1
        return frame

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

        ui.wait_for(ss.Screen.APP_HOME, timeout=120)
        ui.focus()
        shot("home")

        ui.click(*BSS_TILE, settle=4.0)
        shot("after_tile_click")

        # Scroll the game page a notch at a time, photographing as we go. The
        # Servers section is somewhere below the fold and we do not yet know
        # how far, so this is a sweep, not a targeted jump.
        prev = None
        for i in range(SCROLLS):
            ui.scroll(3, at=(960, 700))
            frame = shot(f"scroll_{i + 1}")
            if prev is not None and (frame[:, :, :3] == prev).all():
                print("      page stopped changing - reached the bottom", flush=True)
                break
            prev = frame[:, :, :3].copy()

        print("\n  trace:")
        for t, msg in ui.trace:
            print(f"    {t:6.1f}s  {msg}")
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
    print(f"\n  frames in {OUT}")


if __name__ == "__main__":
    main()
