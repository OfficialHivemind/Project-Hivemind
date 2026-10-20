#!/usr/bin/env python3
"""Is the nested compositor actually producing new frames?"""
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import cv2, numpy as np
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy

s = Session(width=1920, height=1080); s.start()
game = s.launch_game()
conn = WlConnection(s.socket).connect()
cap = ScreenCopy(conn, output_index=0)
try:
    t0=time.monotonic(); full=False
    while time.monotonic()-t0 < 240:
        if not full and "class:" in s.hyprctl("clients"):
            s.fullscreen_focused(); full=True; time.sleep(0.5)
        if cv2.cvtColor(cap.capture()[:,:,:3],cv2.COLOR_BGR2HSV)[:,:,1].mean() > 45:
            print(f"  loaded at {time.monotonic()-t0:.1f}s"); break
        time.sleep(1.5)
    time.sleep(3)

    print("\n  Are consecutive frames different?")
    prev = cap.capture()[:,:,:3].astype(np.int16)
    identical = 0
    for i in range(15):
        time.sleep(0.15)
        cur = cap.capture()[:,:,:3].astype(np.int16)
        diff = np.abs(cur-prev).mean()
        changed = np.mean(np.abs(cur-prev) > 6)
        print(f"    frame {i:2}: mean|diff|={diff:6.3f}  changed_px={changed*100:5.2f}%")
        if diff < 0.01: identical += 1
        prev = cur
    print(f"\n  {identical}/15 frames identical to the previous one")
    print(f"  hyprland monitors:\n{s.hyprctl('monitors')[:300]}")
finally:
    cap.close(); conn.close(); game.terminate(); time.sleep(1); s.stop()
