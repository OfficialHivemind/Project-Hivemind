#!/usr/bin/env python3
"""Does moving the game to a HEADLESS output fix the throttling?

A headless output is driven by its own timer, not by the parent compositor's
frame callbacks, so an unfocused or occluded nested window should stop mattering.
"""
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import cv2, numpy as np
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy

s = Session(width=1920, height=1080); s.start()
game = s.launch_game()
conn0 = WlConnection(s.socket).connect()
cap0 = ScreenCopy(conn0, output_index=0)
try:
    t0=time.monotonic(); full=False
    while time.monotonic()-t0 < 240:
        if not full and "class:" in s.hyprctl("clients"):
            s.fullscreen_focused(); full=True; time.sleep(0.5)
        if cv2.cvtColor(cap0.capture()[:,:,:3],cv2.COLOR_BGR2HSV)[:,:,1].mean() > 45:
            print(f"  loaded at {time.monotonic()-t0:.1f}s"); break
        time.sleep(1.5)
    time.sleep(2)
    cap0.close(); conn0.close()

    print("  creating headless output and moving the game to it...")
    s.hyprctl("output", "create", "headless"); time.sleep(1.0)
    s.hyprctl("keyword", "monitor", "HEADLESS-1,1920x1080@60,2000x0,1"); time.sleep(0.8)
    s.hyprctl("dispatch", "moveworkspacetomonitor", "1 HEADLESS-1"); time.sleep(1.2)
    print("  monitors:", [l for l in s.hyprctl("monitors").splitlines() if l.startswith("Monitor")])

    conn = WlConnection(s.socket).connect()
    print(f"  client sees {len(conn.outputs)} outputs")
    for idx in range(len(conn.outputs)):
        cap = ScreenCopy(conn, output_index=idx)
        prev = cap.capture()[:,:,:3].astype(np.int16)
        sat = cv2.cvtColor(prev.astype(np.uint8),cv2.COLOR_BGR2HSV)[:,:,1].mean()
        ident=0; diffs=[]
        for _ in range(12):
            time.sleep(0.15)
            cur = cap.capture()[:,:,:3].astype(np.int16)
            d = np.abs(cur-prev).mean(); diffs.append(d)
            if d < 0.01: ident += 1
            prev = cur
        print(f"    output[{idx}]  sat={sat:5.1f}  identical={ident}/12  "
              f"mean|diff|={np.mean(diffs):.3f}")
        if idx == 1:
            cv2.imwrite("/tmp/hivemind-diag/headless_frame.png", cap.capture()[:,:,:3])
        cap.close()
    conn.close()
finally:
    game.terminate(); time.sleep(1); s.stop()
