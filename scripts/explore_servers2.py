#!/usr/bin/env python3
"""Second leg: game page -> Servers -> find the private server.

Run 1 got as far as the Bee Swarm Simulator page and found the row the owner
described:

    Badges    View >
    Servers   View >     <- this one

Rather than remember that it sat at y=543, this run finds the word "Servers" by
template match and clicks the View link on the same row. MEASURED: the label
lands at y=543 on one capture and y=547 on another taken at a different scroll
offset, so a fixed coordinate would already be wrong between two runs minutes
apart. The View link's x is stable at 1376 because the row is right-aligned to a
fixed-width content column.
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
from hivemind.vision import templates as T

OUT = pathlib.Path("/tmp/hivemind-diag/servers2")
ROOT = pathlib.Path(__file__).resolve().parents[1]
BSS_TILE = (193, 926)
VIEW_X = 1376          # right-aligned View link on the details rows
MAX_SCROLLS = 10


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
        print(f"  {step:02d} {label:22s} {ss.classify(frame, templates).value}", flush=True)
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
        shot("game_page")

        # scroll until the Servers row is on screen
        hit = None
        for i in range(MAX_SCROLLS):
            frame = cap.capture()
            # MEASURED threshold. "Servers" is a prefix of the "Server Size"
            # row further up the page, and a tight crop of the word scored 0.877
            # against it -- so the first run matched Server Size, stopped
            # scrolling and clicked the wrong row. Widening the template past the
            # word (blank column for "Servers", the word "Size" for the other)
            # pushed that false match down to 0.695 while true matches stay at
            # 1.000 on every frame tested.
            hit = T.find(frame, servers_label, threshold=0.90)
            if hit is not None:
                print(f"      found 'Servers' at y={hit.cy} score={hit.score:.3f} "
                      f"after {i} scrolls", flush=True)
                break
            ui.scroll(3, at=(960, 700))
        shot("servers_row_visible")

        if hit is None:
            print("      never found the Servers row - stopping", flush=True)
            return

        ui.click(VIEW_X, hit.cy, settle=3.5)
        shot("after_view_click")

        for i in range(3):
            ui.scroll(3, at=(960, 700))
            shot(f"servers_scroll_{i + 1}")

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
