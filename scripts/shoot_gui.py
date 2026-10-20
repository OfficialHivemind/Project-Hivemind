#!/usr/bin/env python3
"""Render the GUI to a PNG without opening a window.

Runs under QT_QPA_PLATFORM=offscreen, feeds the demo events in synchronously
(no replay timing), and grabs the result. Useful for reviewing the interface
without interrupting whatever is on screen, and as a cheap regression check
that every panel still constructs and paints.

    QT_QPA_PLATFORM=offscreen python3 scripts/shoot_gui.py out.png
    ... out.png 1560 940 0 simple      the Simple page (or "advanced")
    ... out.png 1366 768 0 new:stats   the new layout (gui/shell) on a tab;
                                       "new:settings:advanced" with Advanced on

The page is the one the window would open on (`gui.mode`) unless named; it
is shown, never saved, so a render does not change the owner's setting.
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# NEVER THE REAL TOKEN: the Telegram tab reads (and could check) telegram.env,
# so a render gets an empty one of its own unless told otherwise.
os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", os.path.join(
    __import__("tempfile").mkdtemp(prefix="shoot-gui-"), "telegram.env"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
# THE DEMO'S OWN FOLDERS, before any settings load: these renders become the
# public repo's screenshots (docs/pending/launch-plan.md), and without this the
# window read the real settings.yaml, so a server name or username in it could
# land in a picture (the same leak datapaths.use_demo_dirs fixed for --demo).
from hivemind.datapaths import use_demo_dirs  # noqa: E402

use_demo_dirs()

from PySide6.QtWidgets import QApplication

from hivemind.gui.bridge import EventBridge
from hivemind.gui.window import MainWindow
from hivemind.telemetry.events import from_json

ROOT = pathlib.Path(__file__).resolve().parents[1]
SESSION = ROOT / "data/demo/session.jsonl"


def main() -> int:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "hivemind_gui.png")
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 1480
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 880
    tab = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    mode = sys.argv[5] if len(sys.argv) > 5 else None

    app = QApplication(sys.argv[:1])
    bridge = EventBridge()
    if mode and mode.startswith("new"):
        from hivemind.gui.shell import ShellWindow
        window = ShellWindow(bridge)
    else:
        window = MainWindow(bridge)
    window.resize(width, height)
    window.show()

    fed = 0
    for line in SESSION.read_text().splitlines():
        event = from_json(line)
        if event is not None:
            window.handle(event)
            fed += 1
    window.status.set_connected(True)
    # SAY IT IS THE DEMO, ON THE PICTURE. Every number here comes from
    # data/demo/session.jsonl and none of it is the owner's account, and they have
    # already been caught by exactly that once -- they looked at a render showing
    # honey 10.2M, 446K pollen and 25 bees and asked where the figures came
    # from, with the game not even open; their real figures were different. The
    # window has carried a banner for this since; the renderer just never
    # turned it on.
    # PROMO RENDERS (SHOOT_NO_BANNER=1, the owner's UI showcase video, 19 Oct):
    # the layout is the subject, so the banner is left off -- and the video
    # keeps the made-up numbers out of focus instead of presenting them as theirs.
    if os.environ.get("SHOOT_NO_BANNER") != "1":
        window.set_replay_banner(SESSION.name)
    if mode and mode.startswith("new"):
        # shown, never saved: the owner's gui.mode is left as it is
        _, tab_key, *advanced = mode.split(":") + ["plan"]
        window.show_mode("advanced" if advanced[:1] == ["advanced"] else "simple")
        window._show_tab(tab_key or "plan")
        window._menus[tab_key or "plan"].setCurrentRow(tab)
    else:
        window.tabs.setCurrentIndex(tab)
        if mode:
            window.show_mode(mode, animate=False)

    # THE CROSSFADE IS WAITED OUT (simple.crossfade, 320 ms): grabbed at
    # once, a tab showed the old page's fading picture over it
    import time
    end = time.monotonic() + 0.6
    while time.monotonic() < end:
        app.processEvents()

    window.grab().save(str(out))
    print(f"  fed {fed} events, wrote {out} ({width}x{height})")
    print(f"  pending questions: {window.inbox.pending}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
