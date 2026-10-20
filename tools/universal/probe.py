"""RL1b prototype: drive a bundled wlroots compositor with Hivemind's OWN
Wayland classes (WlConnection, ScreenCopy, VirtualInput), end to end.

  probe.py window LOG   a stand-in game: a PySide6 window that is red, turns
                        green on the W key and logs keys and clicks to LOG
  probe.py drive LOG    connect to $WAYLAND_DISPLAY, require the bot's three
                        protocols, capture, tap W, click, and check the window
                        saw both (by its pixels and by LOG)

Run inside the compositor by tools/universal/probe_headless.sh. Never Sober.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def window(log: str) -> None:
    """A GL window with vsync on, like the game: eglSwapBuffers waits for the
    compositor's frame callback, so frames/s is the rate the compositor lets
    a game draw at (DESIGN 8a: Hyprland's own headless output starved it)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtOpenGL import QOpenGLWindow

    out = open(log, "a", buffering=1)
    GL_COLOR, GL_SCISSOR = 0x4000, 0x0C11

    class W(QOpenGLWindow):
        rgb = (1.0, 0.0, 0.0)
        paints = 0
        t0 = time.monotonic()

        def paintGL(self):
            f = self.context().functions()
            r = self.devicePixelRatio()
            w, h = int(self.width() * r), int(self.height() * r)
            f.glDisable(GL_SCISSOR)
            f.glClearColor(*self.rgb, 1.0)
            f.glClear(GL_COLOR)
            f.glEnable(GL_SCISSOR)              # top band: orientation (GL's y is up)
            f.glScissor(0, h - h // 10, w, h // 10)
            f.glClearColor(0.0, 0.0, 1.0, 1.0)
            f.glClear(GL_COLOR)
            self.paints += 1
            self.update()                       # draw again after the swap

        def keyPressEvent(self, e):
            out.write(f"key {e.text()!r}\n")
            out.write(f"client drew {self.paints / (time.monotonic() - self.t0):.1f} frames/s (vsync)\n")
            if e.key() == Qt.Key_W:
                self.rgb = (0.0, 1.0, 0.0)

        def mousePressEvent(self, e):
            p = e.position()
            out.write(f"click {int(p.x())} {int(p.y())} size {self.width()}x{self.height()}\n")

    app = QGuiApplication([])
    # the Wayland app id, which labwc's window rule and foreign-toplevel see
    # (tests/unit/test_wlr_session.py waits for this one, as bootstrap does for Sober)
    app.setDesktopFileName(os.environ.get("PROBE_APP_ID", "hivemind-probe"))
    w = W()
    if os.environ.get("PROBE_WINDOWED"):
        w.resize(800, 600)
        w.show()            # the compositor's window rule must fullscreen it
    else:
        w.showFullScreen()
    app.exec()


def drive(log: str) -> int:
    from hivemind.platform.input import VirtualInput
    from hivemind.platform.wl.connection import WlConnection
    from hivemind.platform.wl.screencopy import ScreenCopy

    sock = os.environ["WAYLAND_DISPLAY"]
    conn = WlConnection(sock).connect()
    conn.require("zwp_virtual_keyboard_manager_v1", "zwlr_virtual_pointer_manager_v1",
                 "zwlr_screencopy_manager_v1", "wl_shm", "wl_seat")
    print("protocols: all five bound", flush=True)
    offered = []
    f = conn.globals["zwlr_screencopy_manager_v1"].capture_output(0, conn.outputs[0])
    f.dispatcher["buffer"] = lambda _f, fmt, w, h, s: offered.append(f"shm 0x{fmt:08x} {w}x{h}")
    f.dispatcher["flags"] = lambda _f, fl: offered.append(f"flags {fl} ({'Y-INVERTED' if fl & 1 else 'upright'})")
    f.dispatcher["linux_dmabuf"] = lambda _f, fmt, w, h: offered.append(f"dmabuf 0x{fmt:08x}")
    conn.roundtrip()
    f.destroy()
    print("screencopy offers:", offered, "(the bot takes shm ARGB/XRGB, and XBGR/ABGR since RL1b)", flush=True)
    cap = ScreenCopy(conn)
    frame = cap.capture()
    h, w = frame.shape[:2]
    top = tuple(int(x) for x in frame[5, w // 2])
    print(f"frame {w}x{h}, centre BGRA {tuple(int(x) for x in frame[h // 2, w // 2])}, "
          f"top BGRA {top} -> {'blue band on top: upright, channels right' if top[0] > 200 and top[2] < 50 else 'WRONG'}",
          flush=True)

    t0, n = time.monotonic(), 120
    for _ in range(n):
        cap.capture()
    print(f"capture rate {n / (time.monotonic() - t0):.1f}/s (full output)", flush=True)

    vi = VirtualInput(socket=sock, width=w, height=h)
    vi.focus_game(w // 2, h // 2)
    vi.tap("w")
    vi.click(w // 4, h // 4)
    time.sleep(0.5)
    after = cap.capture()
    b, g, r, _ = (int(x) for x in after[h // 2, w // 2])
    print(f"after W: centre BGRA {(b, g, r)} -> {'GREEN (key arrived)' if g > 200 and r < 50 else 'not green'}", flush=True)
    seen = Path(log).read_text() if Path(log).exists() else ""
    print("window log:\n  " + "\n  ".join(seen.splitlines()), flush=True)
    vi.close()
    cap.close()
    conn.close()
    ok = (top[0] > 200 and top[2] < 50 and g > 200 and "key 'w'" in seen
          and f"size {w}x{h}" in seen)
    print("PROBE", "PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    mode, log = sys.argv[1], sys.argv[2]
    sys.exit(window(log) if mode == "window" else drive(log))
