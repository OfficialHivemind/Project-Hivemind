#!/usr/bin/env python3
"""Third leg: open the Servers panel and read it from the top.

Run 2 opened the panel and landed mid-list, showing "Friends in this server"
and then "Other Servers". The owner's private server is not in either of those,
so this run scrolls the panel back to the top and photographs the whole thing.

Two corrections carried in from run 2:

  * scroll INSIDE the panel. It is a right-hand drawer occupying x 960-1920, so
    the previous scroll point of (960, 700) sat exactly on its left edge.
  * the panel loads asynchronously -- it showed the word "Loading" on the first
    frame after opening -- so wait for content instead of scrolling immediately.
"""
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import cv2
import numpy as np

from hivemind.act.appui import AppUI
from hivemind.platform.input import VirtualInput
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy
from hivemind.vision import screenstate as ss
from hivemind.vision import templates as T

OUT = pathlib.Path("/tmp/hivemind-diag/servers3")
ROOT = pathlib.Path(__file__).resolve().parents[1]
BSS_TILE = (193, 926)
VIEW_X = 1376
PANEL = (960, 600)          # a point inside the Servers drawer
MAX_SCROLLS = 12


def main() -> None:
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
    step = 0

    def shot(label: str):
        nonlocal step
        frame = cap.capture()
        cv2.imwrite(str(OUT / f"{step:02d}_{label}.png"), frame[:, :, :3])
        print(f"  {step:02d} {label}", flush=True)
        step += 1
        return frame[:, :, :3]

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
        ui.click(*BSS_TILE, settle=4.0)

        hit = None
        for _ in range(MAX_SCROLLS):
            hit = T.find(cap.capture(), servers_label, threshold=0.90)
            if hit is not None:
                break
            ui.scroll(3, at=(960, 700))
        if hit is None:
            print("  never found the Servers row"); return
        print(f"  Servers row at y={hit.cy} score={hit.score:.3f}", flush=True)

        ui.click(VIEW_X, hit.cy, settle=2.0)

        # wait for the drawer to finish loading: stop when two consecutive
        # frames match, i.e. the list has settled
        prev = None
        for i in range(20):
            frame = cap.capture()[:, :, :3]
            if prev is not None and np.array_equal(frame, prev):
                print(f"  panel settled after {i} polls", flush=True)
                break
            prev = frame
            time.sleep(1.0)
        shot("panel_settled")

        # back to the top of the drawer
        for i in range(MAX_SCROLLS):
            ui.scroll(-5, at=PANEL, settle=0.5)
        shot("panel_top")

        # then sweep down through it
        prev = None
        for i in range(8):
            ui.scroll(3, at=PANEL, settle=0.9)
            frame = shot(f"panel_down_{i + 1}")
            if prev is not None and np.array_equal(frame, prev):
                print("      bottom of panel", flush=True)
                break
            prev = frame
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
