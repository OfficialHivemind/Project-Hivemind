#!/usr/bin/env python3
"""Where exactly does rendering stop? Phased, with the render_unfocused rule on."""
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import cv2, numpy as np
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy

def measure(cap, n=12, dt=0.15):
    prev = cap.capture()[:,:,:3].astype(np.int16); ds=[]
    for _ in range(n):
        time.sleep(dt)
        cur = cap.capture()[:,:,:3].astype(np.int16)
        ds.append(float(np.abs(cur-prev).mean())); prev=cur
    ident = sum(1 for d in ds if d < 0.01)
    return float(np.median(ds)), ident, n

s = Session(width=1920, height=1080); s.start()
game = s.launch_game()
conn = WlConnection(s.socket).connect(); cap = ScreenCopy(conn, output_index=0)
try:
    t0=time.monotonic(); full=False
    while time.monotonic()-t0<240:
        if not full and "class:" in s.hyprctl("clients"):
            s.fullscreen_focused(); full=True; time.sleep(0.5)
        if cv2.cvtColor(cap.capture()[:,:,:3],cv2.COLOR_BGR2HSV)[:,:,1].mean()>45: break
        time.sleep(1.5)
    print(f"  loaded at {time.monotonic()-t0:.1f}s; letting the world settle 8s")
    time.sleep(8)

    m,i,n = measure(cap)
    print(f"  A: on WAYLAND-1 (nested window unfocused in KDE)  median={m:6.3f}  identical={i}/{n}")
    cap.close(); conn.close()

    s.add_headless_output(); s.move_to_headless(); time.sleep(2.0)
    conn = WlConnection(s.socket).connect(); cap = ScreenCopy(conn, output_index=1)
    m,i,n = measure(cap)
    print(f"  B: on HEADLESS-1, just after move                 median={m:6.3f}  identical={i}/{n}")
    time.sleep(5)
    m,i,n = measure(cap)
    print(f"  C: on HEADLESS-1, 5s later                        median={m:6.3f}  identical={i}/{n}")
    cv2.imwrite("/tmp/hivemind-diag/phase_c.png", cap.capture()[:,:,:3])
finally:
    cap.close(); conn.close(); game.terminate(); time.sleep(1); s.stop()
