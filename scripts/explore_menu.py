#!/usr/bin/env python3
"""Explore the in-game Roblox UI to find the server list.

Escape was tried before and appeared to do nothing -- but that was before we
knew a pointer-enter is required first. Retrying now that input demonstrably
works.
"""
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import cv2, numpy as np
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy
from hivemind.platform.input import VirtualInput
OUT = pathlib.Path("/tmp/hivemind-diag")

s = Session(width=1920, height=1080); s.start()
game = s.launch_game()
conn = WlConnection(s.socket).connect(); cap = ScreenCopy(conn, output_index=0)
vin=None
try:
    t0=time.monotonic(); full=False
    while time.monotonic()-t0<240:
        if not full and "class:" in s.hyprctl("clients"):
            s.fullscreen_focused(); full=True; time.sleep(0.5)
        if cv2.cvtColor(cap.capture()[:,:,:3],cv2.COLOR_BGR2HSV)[:,:,1].mean()>45: break
        time.sleep(1.5)
    time.sleep(8)
    vin = VirtualInput(s.socket, 1920, 1080)
    vin.focus_game()

    def shot(name):
        f = cap.capture()[:,:,:3]
        cv2.imwrite(str(OUT/f"menu_{name}.png"), f)
        return f.astype(np.int16)

    base = shot("00_ingame")
    print("  pressing Escape...")
    vin.tap("escape"); time.sleep(2.0)
    esc = shot("01_escape")
    print(f"    change vs in-game: {np.abs(esc-base).mean():.2f}")

    # The Roblox hamburger sits top-left; on the Android UI that is the usual
    # route to the menu.
    print("  clicking the top-left Roblox icon...")
    vin.tap("escape"); time.sleep(1.0)      # close whatever Escape did
    vin.click(38, 33); time.sleep(2.0)
    a = shot("02_roblox_icon")
    print(f"    change vs in-game: {np.abs(a-base).mean():.2f}")

    print("  clicking the hamburger...")
    vin.click(93, 33); time.sleep(2.0)
    b = shot("03_hamburger")
    print(f"    change vs in-game: {np.abs(b-base).mean():.2f}")
finally:
    if vin: vin.close()
    cap.close(); conn.close(); game.terminate(); time.sleep(1); s.stop()
