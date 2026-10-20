#!/usr/bin/env python3
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import cv2, numpy as np
from hivemind.platform.session import Session
from hivemind.platform.wl.connection import WlConnection
from hivemind.platform.wl.screencopy import ScreenCopy
from hivemind.platform.input import VirtualInput

def active(s, tag):
    a = s.hyprctl("activewindow")
    cls = next((l.strip() for l in a.splitlines() if l.strip().startswith("class:")), "(none)")
    print(f"  [{tag}] activewindow {cls}")

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
    time.sleep(3); active(s,"loaded"); cap.close(); conn.close()

    s.add_headless_output(); s.move_to_headless(); time.sleep(1.5)
    active(s,"after move")
    print("  trying explicit window focus:")
    for form in ['hl.dsp.focus({window="class:org.vinegarhq.Sober"})',
                 'hl.dsp.focus({class="org.vinegarhq.Sober"})',
                 'hl.dsp.window.bring_to_top()']:
        r = s.dispatch(form)
        print(f"    {form[:48]:50} -> {r[:40] or 'ok'}")
    time.sleep(0.5); active(s,"after focus attempts")

    conn = WlConnection(s.socket).connect(); cap = ScreenCopy(conn, output_index=1)
    vin = VirtualInput(s.socket)
    # Escape opens the Roblox menu - a huge, unmistakable visual change.
    base = cap.capture()[:,:,:3].astype(np.int16)
    vin.tap("escape"); time.sleep(1.5)
    after = cap.capture()[:,:,:3].astype(np.int16)
    d = np.abs(after-base).mean()
    print(f"\n  ESC test: mean|diff| = {d:.2f}  ({'MENU OPENED - input works' if d>8 else 'no reaction'})")
    cv2.imwrite("/tmp/hivemind-diag/esc_test.png", after.astype(np.uint8))
    vin.tap("escape"); time.sleep(1)
    vin.close(); cap.close(); conn.close()
finally:
    game.terminate(); time.sleep(1); s.stop()
