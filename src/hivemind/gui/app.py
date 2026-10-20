"""Entry point for the Hivemind window.

    python -m hivemind.gui.app                 connect to a running bot
    python -m hivemind.gui.app --demo          replay the bundled demo session
    python -m hivemind.gui.app --replay FILE   replay a recorded session
    python -m hivemind.gui.app --stream        also open the stream window

The demo path exists so the interface can be opened, judged and changed with no
bot and no game running. It is not a mock: it feeds the same recorded event
lines through the same signals the live socket uses, so anything that looks
right in demo looks the same live.
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .bridge import EventBridge
from .window import MainWindow

DEMO = Path(__file__).resolve().parents[3] / "data" / "demo" / "session.jsonl"
LOGO = Path(__file__).resolve().parents[3] / "data" / "brand" / "hivemind_logo.png"
APP_ID = "Hivemind.Hivemind"


def window_class():
    """The new five-tab layout (gui/shell, ROADMAP U18) when `gui.layout` is
    'new'; the classic window otherwise, and whenever anything about the new
    one fails to load -- a window that will not open is the worst outcome."""
    try:
        from ..world.settings import Settings
        if Settings().get("gui.layout") == "new":
            from .shell import ShellWindow
            return ShellWindow
    except Exception:
        pass
    return MainWindow


def first_run_check(parent=None, marker: Path | None = None, run=None,
                    settings=None) -> str | None:
    """THE FIRST-RUN CHECK (RL1): a friend's PC is checked before Start is
    pressed, every requirement with its fix for their distro (cli/doctor), shown
    at every start until it passes once. Returns the text shown, or None.
    The text names the buttons as they are labelled (Start) and the panic
    key as it is set (`safety.panic_key`, read from `settings` or the file)."""
    from ..cli import doctor
    from ..datapaths import config_dir
    from ..world.settings import panic_key_name
    marker = marker or config_dir() / "first-run-passed"
    if marker.exists():
        return None
    checks = (run or doctor.run)()
    failed = [c for c in checks if c.status == doctor.FAIL]
    if failed:
        text = (f"{len(failed)} thing(s) to fix before Start will work. Each has its "
                "fix below; `hivemind doctor` in a terminal shows the same list.\n\n"
                + "\n".join(f"✗ {c.name}: {c.fix}" for c in failed))
    else:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("every check passed\n")
        text = ("✓ Everything Hivemind needs is on this PC. It starts with safe "
                "settings: one field, every optional errand off (Settings turns "
                f"them on). The panic key is {panic_key_name(settings)}.")
    if parent is not None:
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(parent)
        box.setWindowTitle("Hivemind: first-run check")
        box.setIcon(QMessageBox.Icon.Warning if failed else QMessageBox.Icon.Information)
        box.setText(text)
        box.setDetailedText(doctor.report(checks))
        box.open()
    return text


def show_first_run(window, fresh_install: bool, marker: Path | None = None,
                   windows: bool | None = None, run=None, autostart: bool = False):
    """The first-run window when it is wanted (firstrun.wanted), shown; else
    None. Kept by the caller: a window nothing holds is closed. On Windows
    it is the PC check alone (gui/wincheck), never Linux's Install Sober:
    at every start until it passes once (there is no fresh-install flag on
    Windows: the installer's shortcut has no arguments), never at a login
    start (--autostart), its checks on a worker thread."""
    from ..datapaths import config_dir
    from . import firstrun
    marker = marker or config_dir() / "first-run-passed"
    if (sys.platform == "win32") if windows is None else windows:
        from . import wincheck
        if not wincheck.wanted(marker, windows=True, autostart=autostart):
            return None
        check = wincheck.WinCheckWindow(marker=marker, doctor_run=run)
        check.show()
        check.raise_()
        check.check_soon()
        return check
    try:
        from ..world.settings import Settings
        compositor = str(Settings().get("platform.compositor", "hyprland"))
    except Exception:
        compositor = "hyprland"
    if not firstrun.wanted(compositor, fresh_install, marker):
        return None
    view = firstrun.FirstRunWindow(window, marker=marker, doctor_run=run)
    view.show()
    view.raise_()
    return view


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hivemind-gui")
    parser.add_argument("--socket", help="unix socket the bot is serving on")
    parser.add_argument("--replay", type=Path, help="replay a recorded .jsonl")
    parser.add_argument("--demo", action="store_true",
                        help="replay the bundled demo session")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--autostart", action="store_true",
                        help="opened at login: start farming after a 60 s grace "
                             "if gui.start_on_boot is on (gui/autostart)")
    parser.add_argument("--stream", action="store_true",
                        help="open the 1920x1080 stream window too (DESIGN 8dv)")
    parser.add_argument("--first-run-check", action="store_true",
                        help="show `hivemind doctor` until everything passes once "
                             "(the Linux launcher, installer/linux/hivemind)")
    args = parser.parse_args(argv)

    if sys.platform == "win32":                     # pragma: no cover (Windows)
        # THE TASKBAR SHOWS HIVEMIND, NOT PYTHON (RL6i): the same id the
        # installer's shortcuts carry (installer/hivemind.iss, APP_ID), so
        # Windows groups this pythonw.exe window under the Hivemind icon.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = QApplication(sys.argv[:1])
    if sys.platform == "win32":
        # FUSION ON WINDOWS: the window is styled by sheets in px, and the
        # native windows11 style warned "QFont::setPointSize: Point size <= 0
        # (-1)" over them (the owner's 5th Windows run, gui_error.txt)
        # [assumed: the style is the source]. Fusion draws what the sheets say.
        app.setStyle("Fusion")
    app.setApplicationName("Hivemind")
    app.setWindowIcon(QIcon(str(LOGO)))
    # U7 FONT SCALE, before anything is built (gui/widgets.apply_font_scale)
    try:
        from ..world.settings import Settings
        from .widgets import apply_font_scale
        apply_font_scale(app, Settings().get("gui.font_scale"))   # owned by app
    except Exception:
        pass                                # the window opens at 100 %

    # THE FIRST SECOND (gui/splash): the logo and the name while the window
    # builds behind it. Anything wrong with it and the window simply opens.
    splash = None
    try:
        from .splash import Splash
        splash = Splash(LOGO)
        splash.start()
        app.processEvents()
    except Exception:
        splash = None

    bridge = EventBridge(socket_path=args.socket)
    window = window_class()(bridge)
    if splash is not None:
        try:
            splash.finish(window)
        except Exception:
            window.show()
    else:
        window.show()

    source = args.replay or (DEMO if args.demo else None)
    if source is not None:
        if not source.exists():
            print(f"no such recording: {source}", file=sys.stderr)
            return 2
        # SAY SO, UNMISSABLY. Every number in a replay is invented: the honey,
        # the bee count, the planters, the reasoning, the live view. Shown
        # without a banner it is indistinguishable from a live session, and the
        # owner caught exactly that -- they asked where the stats came from when
        # the game was not even running. A demo that can be mistaken for real
        # is worse than no demo, so the window carries the warning for as long
        # as it is replaying.
        window.set_replay_banner(source.name)
        bridge.replay(source, speed=args.speed, loop=args.loop)
    else:
        bridge.connect_to_bot()
        if args.autostart:
            # after the socket is tried, so a bot already running is seen
            QTimer.singleShot(2000, window.begin_autostart)
    # THE FIRST-RUN WINDOW (gui/firstrun, RL1b step 3): Install Sober, Log
    # in to Roblox, Start -- with the headless labwc, or on a fresh install,
    # until it has passed once.
    # No first-run steps (install Sober, log in, Start) over a demo: it
    # starts nothing (window._start), and the UI preview build is a demo only.
    window.first_run = None if source is not None else show_first_run(
        window, args.first_run_check, autostart=args.autostart)
    # THE FIRST-WEEK TOUR (gui/tour, ROADMAP U10): what each tab is for,
    # once, in the new layout. A demo shows it too (its own config folder);
    # it is a card, not a dialog, so it blocks nothing. Anything wrong with
    # it and the window simply opens without it. Not on a boot autostart:
    # nobody is at the window then (gui/autostart). After the first-run
    # window closes, when there is one: one thing at a time.
    window.tour = None
    if not args.autostart:
        try:
            from .tour import show_tour_after
            show_tour_after(window, window.first_run)
        except Exception:
            window.tour = None
    if args.stream:
        # After the replay banner, so a demo on stream says DEMO there too.
        window.open_stream()

    # Qt swallows SIGINT unless the interpreter gets a chance to run
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    nudge = QTimer()
    nudge.start(200)
    nudge.timeout.connect(lambda: None)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
