"""The first-run check on Windows (gui/wincheck), offscreen with a fake doctor.

It lists what is wrong with its fix, remembers a clean pass so it is not
shown again, starts nothing, and is never the window Linux gets.
"""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtCore import QObject, Signal                     # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel             # noqa: E402

from hivemind.cli import doctor                                # noqa: E402
from hivemind.gui import app as gui_app, wincheck              # noqa: E402

BAD = [doctor.Check("environment", "Roblox", doctor.FAIL, "not installed",
                    "install Roblox from roblox.com/download"),
       doctor.Check("environment", "display scale 100%", doctor.WARN, "125%",
                    "Scale: 100%"),
       doctor.Check("environment", "Python: numpy", doctor.OK)]
GOOD = [doctor.Check("environment", "Roblox", doctor.OK, "found"),
        doctor.Check("environment", "display scale 100%", doctor.WARN, "125%",
                      "Scale: 100%")]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def texts(view):
    return [label.text() for label in view._rows.findChildren(QLabel)]


def settle(app, view, seconds=10.0):
    """Let the worker thread's checks reach the window."""
    end = time.monotonic() + seconds
    while view._busy and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    assert not view._busy, "the checks never came back"


def test_shown_on_windows_until_it_passed(tmp_path):
    marker = tmp_path / "first-run-passed"
    assert wincheck.wanted(marker, windows=True)
    assert not wincheck.wanted(marker, windows=False)        # Linux has gui/firstrun
    assert not wincheck.wanted(marker, windows=True, autostart=True)   # nobody to read it
    marker.write_text("x", encoding="utf-8")
    assert not wincheck.wanted(marker, windows=True)


def test_problems_come_first_with_their_fix_and_play_waits(app, tmp_path):
    marker = tmp_path / "first-run-passed"
    view = wincheck.WinCheckWindow(marker=marker, doctor_run=lambda: BAD)
    view.check()
    shown = texts(view)
    assert shown[0].startswith("✗  Roblox: not installed")
    assert "How to fix: install Roblox from roblox.com/download" in shown
    assert shown.index("How to fix: Scale: 100%") < shown.index("✓  Python: numpy")
    assert "1 thing(s) to fix before Hivemind can play" in view.step.status.text()
    assert "Play" not in view.step.status.text().replace("can play", "")
    assert not marker.exists()
    view.close()


def test_a_clean_pass_is_remembered_and_starts_nothing(app, tmp_path, monkeypatch):
    marker = tmp_path / "cfg" / "first-run-passed"
    runs = []
    monkeypatch.setattr(wincheck, "panic_key", lambda: "F10")   # the player's own key
    view = wincheck.WinCheckWindow(marker=marker, doctor_run=lambda: runs.append(1) or GOOD)
    view.check()
    assert marker.exists()
    said = view.step.status.text()
    # the main window's button is called Start (gui/simple, panels/status, gui/shell)
    assert "Press Start (F1) in the main window" in said and "Play" not in said
    assert "F10 stops everything" in said and "F12" not in said
    view.step.button.click()                                  # Check again, in the background
    assert not view.step.button.isEnabled()
    settle(app, view)
    assert view.step.button.isEnabled()
    assert len(runs) == 2
    assert len([t for t in texts(view) if t.startswith("✓  Roblox")]) == 1   # rows replaced
    view.close()


class FakeMain(QObject):
    event_received = Signal(object)

    def __init__(self):
        super().__init__()
        self.bridge = self
        self.starts = 0

    def _start(self):
        self.starts += 1


def test_the_app_shows_it_on_windows_and_never_linuxs_steps(app, tmp_path, monkeypatch):
    marker = tmp_path / "first-run-passed"
    main = FakeMain()
    view = gui_app.show_first_run(main, False, marker=marker, windows=True,
                                  run=lambda: GOOD)
    assert isinstance(view, wincheck.WinCheckWindow)
    settle(app, view)                                         # the worker's checks
    assert marker.exists() and main.starts == 0
    view.close()
    assert gui_app.show_first_run(main, True, marker=marker, windows=True) is None
    marker.unlink()
    # a start at login (--autostart) shows nothing, even before a clean pass
    assert gui_app.show_first_run(main, False, marker=marker, windows=True,
                                  run=lambda: GOOD, autostart=True) is None
    marker.write_text("x", encoding="utf-8")
    # on Linux the Windows check is never built
    monkeypatch.setattr(wincheck, "WinCheckWindow", lambda *a, **k: pytest.fail("built"))
    marker.unlink()
    from hivemind.gui import firstrun
    monkeypatch.setattr(firstrun, "wanted", lambda *a: False)
    assert gui_app.show_first_run(main, False, marker=marker, windows=False) is None


def test_the_checks_run_off_the_gui_thread_and_errors_are_shown(app, tmp_path):
    import threading
    seen = []

    def run():
        seen.append(threading.current_thread() is threading.main_thread())
        raise RuntimeError("boom")
    view = wincheck.WinCheckWindow(marker=tmp_path / "m", doctor_run=run)
    view.check_soon()
    view.check_soon()                                         # once at a time
    settle(app, view)
    assert seen == [False]
    assert texts(view)[0].startswith("✗  the check itself: it stopped with an error (boom)")
    assert not (tmp_path / "m").exists()
    view.close()
