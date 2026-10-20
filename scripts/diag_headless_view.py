#!/usr/bin/env python3
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import cv2
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy
OUT=pathlib.Path("/tmp/hivemind-diag")

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
    time.sleep(3)
    cv2.imwrite(str(OUT/"before_move.png"), cap.capture()[:,:,:3])
    cap.close(); conn.close()

    s.add_headless_output(); s.move_to_headless(); time.sleep(2)
    print("  clients after move:")
    for l in s.hyprctl("clients").splitlines():
        ls=l.strip()
        if ls.startswith(("class:","monitor:","workspace:","fullscreen:","at:","size:","floating:","mapped:","hidden:")):
            print("   ", ls)
    conn = WlConnection(s.socket).connect()
    for idx in range(len(conn.outputs)):
        c = ScreenCopy(conn, output_index=idx); img=c.capture()
        sat=cv2.cvtColor(img[:,:,:3],cv2.COLOR_BGR2HSV)[:,:,1].mean()
        cv2.imwrite(str(OUT/f"after_move_out{idx}.png"), img[:,:,:3])
        print(f"  output[{idx}] sat={sat:6.1f} mean={img.mean():6.1f} -> after_move_out{idx}.png")
        c.close()
    conn.close()
finally:
    game.terminate(); time.sleep(1); s.stop()
