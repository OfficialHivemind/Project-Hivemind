#!/usr/bin/env python3
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import cv2
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy

def state(s, tag):
    cl = s.hyprctl("clients")
    win = {}
    for line in cl.splitlines():
        line=line.strip()
        for k in ("monitor:","workspace:","fullscreen:","class:","at:","size:"):
            if line.startswith(k): win[k.rstrip(':')] = line[len(k):].strip()
    mons = [l.split()[1] for l in s.hyprctl("monitors").splitlines() if l.startswith("Monitor")]
    print(f"  [{tag}] monitors={mons} window={win}")

s = Session(width=1920, height=1080); s.start()
game = s.launch_game()
conn = WlConnection(s.socket).connect(); cap = ScreenCopy(conn, output_index=0)
try:
    t0=time.monotonic(); full=False
    while time.monotonic()-t0 < 240:
        if not full and "class:" in s.hyprctl("clients"):
            s.fullscreen_focused(); full=True; time.sleep(0.5)
        if cv2.cvtColor(cap.capture()[:,:,:3],cv2.COLOR_BGR2HSV)[:,:,1].mean() > 45: break
        time.sleep(1.5)
    time.sleep(2); cap.close(); conn.close()
    state(s, "loaded")

    s.hyprctl("output","create","headless"); time.sleep(1.0); state(s,"headless created")
    print("  ", s.hyprctl("keyword","monitor","HEADLESS-1,1920x1080@60,2000x0,1") or "(keyword ok)")
    time.sleep(0.8)
    print("  moveworkspacetomonitor ->", s.hyprctl("dispatch","moveworkspacetomonitor","1 HEADLESS-1") or "(ok)")
    time.sleep(1.0); state(s,"after ws move")
    print("  movewindow mon ->", s.hyprctl("dispatch","movewindow","mon:HEADLESS-1") or "(ok)")
    time.sleep(1.0); state(s,"after window move")
    print("  focusmonitor ->", s.hyprctl("dispatch","focusmonitor","HEADLESS-1") or "(ok)")
    time.sleep(1.0); state(s,"after focus")
    print("\n  workspaces:\n", "\n".join("   "+l for l in s.hyprctl("workspaces").splitlines()[:14]))
finally:
    game.terminate(); time.sleep(1); s.stop()
