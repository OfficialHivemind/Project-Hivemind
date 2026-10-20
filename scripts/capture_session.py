#!/usr/bin/env python3
"""Capture a real Bee Swarm session for offline calibration.

Waits for the game to finish loading by watching image statistics (the loading
screen is dark and desaturated; the game world is bright and colourful), then
records a burst of frames.

Everything downstream -- HSV token bands, HUD probe coordinates, the camera-pitch
question -- gets answered from these frames rather than guessed at.
"""
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import cv2
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy
from hivemind.telemetry.recorder import Recorder

OUT = pathlib.Path("/tmp/hivemind-diag")
LOAD_WAIT = 240


def stats(img):
    hsv = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2HSV)
    return float(hsv[:, :, 1].mean()), float(hsv[:, :, 2].mean())


s = Session(width=1920, height=1080)
s.start()
print(f"  compositor {s.socket} @1920x1080")
game = s.launch_game()
conn = WlConnection(s.socket).connect()
cap = ScreenCopy(conn, output_index=0)

try:
    t0 = time.monotonic()
    fullscreened = False
    loaded_at = None
    print("  waiting for the world to load (saturation is the tell)...")
    while time.monotonic() - t0 < LOAD_WAIT:
        if not fullscreened and "class:" in s.hyprctl("clients"):
            s.fullscreen_focused(); fullscreened = True; time.sleep(0.5)
        img = cap.capture()
        sat, val = stats(img)
        el = time.monotonic() - t0
        if int(el) % 10 < 1:
            print(f"    [{el:5.1f}s] saturation={sat:5.1f}  brightness={val:5.1f}")
        # loading screen is near-grey; the game world is strongly coloured
        if sat > 45 and val > 60:
            loaded_at = el
            print(f"    [{el:5.1f}s] WORLD LOADED  saturation={sat:.1f} brightness={val:.1f}")
            break
        time.sleep(1.5)

    if loaded_at is None:
        print(f"  did not detect a loaded world in {LOAD_WAIT}s - saving what we have")

    with Recorder(OUT / "bss_session", note="first real BSS capture",
                  lossless=True) as r:
        r.meta["loaded_at_s"] = loaded_at
        for i in range(24):
            f = cap.capture()
            sat, val = stats(f)
            r.add(f, label="idle", sat=round(sat, 1), val=round(val, 1))
            time.sleep(0.25)
    print(f"  recorded 24 frames -> {OUT/'bss_session'}")
    cv2.imwrite(str(OUT / "bss_frame.png"), cap.capture()[:, :, :3])
finally:
    cap.close(); conn.close()
    game.terminate()
    time.sleep(1)
    s.stop()
    print("  torn down")
