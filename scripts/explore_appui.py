#!/usr/bin/env python3
"""Walk the Roblox app UI and photograph every step.

This is an observation run, not a test: it asserts nothing and concludes nothing.
Its whole job is to produce a numbered series of frames so the private-server
flow can be written from what the UI actually does, rather than from what a
reasonable person would expect it to do.

The question it exists to answer: does the game page have a Servers section
listing private servers, and can the keyboard reach it?

Usage:  python3 scripts/explore_appui.py [steps]
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

OUT = pathlib.Path("/tmp/hivemind-diag/appui")
ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    templates = ss.load_templates(ROOT / "data/templates/digits")
    session = Session(width=1920, height=1080)
    session.start()

    env = {**os.environ, "WAYLAND_DISPLAY": session.socket}
    env.pop("DISPLAY", None)
    # No URI at all: we want the app shell, not a game.
    game = subprocess.Popen(["org.vinegarhq.Sober"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    conn = inp = cap = None
    step = 0

    def shot(label: str) -> None:
        nonlocal step
        frame = cap.capture()
        state = ss.classify(frame, templates)
        path = OUT / f"{step:02d}_{label}.png"
        cv2.imwrite(str(path), frame[:, :, :3])
        print(f"  {step:02d} {label:22s} {state.value:9s} -> {path.name}", flush=True)
        step += 1

    try:
        conn = WlConnection(session.socket).connect()
        cap = ScreenCopy(conn, output_index=0)
        # its own Wayland connection; ScreenCopy keeps `conn` for capture
        inp = VirtualInput(socket=session.socket)
        ui = AppUI(inp=inp, capture=cap, templates=templates)

        # wait for the window, then fullscreen it so coordinates are 1:1
        t0 = time.monotonic()
        while time.monotonic() - t0 < 60 and "class:" not in session.hyprctl("clients"):
            time.sleep(1)
        session.fullscreen_focused()
        time.sleep(1)

        state = ui.wait_for(ss.Screen.APP_HOME, ss.Screen.IN_GAME,
                            ss.Screen.MODAL, timeout=180)
        print(f"  settled on {state.value} after {time.monotonic() - t0:.0f}s", flush=True)
        shot("settled")

        ui.focus()                      # pointer must enter before keys register
        shot("after_focus")

        ui.search("bee swarm simulator")
        shot("after_search_typed")

        ui.submit()
        time.sleep(4)
        shot("after_enter")

        for i in range(3):
            ui.scroll(1)
            time.sleep(1)
            shot(f"scrolled_{i + 1}")

        print("\n  trace:")
        for t, msg in ui.trace:
            print(f"    {t:6.1f}s  {msg}")
    finally:
        if inp:
            inp.close()
        elif conn:
            conn.close()
        if cap:
            cap.close()
        game.terminate()
        time.sleep(1)
        session.stop()
    print(f"\n  frames in {OUT}")


if __name__ == "__main__":
    main()
