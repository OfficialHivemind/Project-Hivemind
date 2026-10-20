#!/usr/bin/env python3
"""Does the game keep rendering when the nested window is MINIMISED?

This is the real background-gaming question: unfocused is already measured as
fine, but a fullscreen game on top means the nested window gets no frame
callbacks from KWin at all.
"""
import pathlib, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import cv2, numpy as np
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy
from hivemind.platform.input import VirtualInput

S = "/tmp/hivemind-diag"
def kwin(script):
    subprocess.run(["busctl","--user","call","org.kde.KWin","/Scripting",
                    "org.kde.kwin.Scripting","loadScript","ss",f"{S}/{script}",""],
                   capture_output=True, timeout=10)
    # scripts are run by loading then starting; try the simpler run path too
    subprocess.run(["qdbus6","org.kde.KWin","/Scripting","loadScript",f"{S}/{script}"],
                   capture_output=True, timeout=10)

def measure(cap, n=14, dt=0.15):
    prev = cap.capture()[:,:,:3].astype(np.int16); ds=[]
    for _ in range(n):
        time.sleep(dt)
        cur = cap.capture()[:,:,:3].astype(np.int16)
        ds.append(float(np.abs(cur-prev).mean())); prev=cur
    return float(np.median(ds)), sum(1 for d in ds if d<0.01), n

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
    vin = VirtualInput(s.socket, 1920, 1080); vin.focus_game()

    vin.press("w")   # keep the world moving so there is something to measure
    m,i,n = measure(cap); print(f"  window VISIBLE    median={m:6.2f} identical={i}/{n}")
    kwin("minimize.js"); time.sleep(2.0)
    m,i,n = measure(cap); print(f"  window MINIMISED  median={m:6.2f} identical={i}/{n}")
    kwin("restore.js"); time.sleep(2.0)
    m,i,n = measure(cap); print(f"  window RESTORED   median={m:6.2f} identical={i}/{n}")
    vin.release("w")
finally:
    kwin("restore.js")
    if vin: vin.close()
    cap.close(); conn.close(); game.terminate(); time.sleep(1); s.stop()
