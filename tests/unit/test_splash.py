"""The splash hands over to the main window when its animation ends, and at
once when it is not running (gui/splash)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from hivemind.gui.splash import Splash  # noqa: E402

APP = QApplication.instance() or QApplication([])
LOGO = os.path.join(os.path.dirname(__file__), "..", "..", "data", "brand", "hivemind_logo.png")


def test_the_window_waits_for_the_animation_then_shows():
    s, w = Splash(LOGO), QWidget()
    s.start()
    s.finish(w)
    assert s.isVisible() and not w.isVisible()
    s.anim.setCurrentTime(s.anim.duration())       # the animation's end
    APP.processEvents()
    assert w.isVisible() and not s.isVisible()


def test_with_no_animation_running_the_window_shows_at_once():
    s, w = Splash(LOGO), QWidget()
    s.finish(w)
    assert w.isVisible()


def test_a_missing_logo_still_paints():
    s = Splash("/nonexistent.png")
    s._tick(0.5)
    assert not s.grab().isNull()
