"""The first-week tour (gui/tour, ROADMAP U10). Offscreen; HIVEMIND_CONFIG
points at a temporary folder, so the real config folder is never read or
written, and the bot is a stand-in that never starts."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QMetaMethod  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui import tour as tour_mod  # noqa: E402
from hivemind.gui.panels import settings as panel_mod  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402

APP = QApplication.instance() or QApplication([])


class _Bot:
    process = None
    log_path = "nowhere"

    def running(self) -> bool:
        return False

    def start(self):
        raise AssertionError("a test must never start the bot")

    def describe_state(self) -> str:
        return ""

    def exit_code(self):
        return None


@pytest.fixture(scope="module")
def shell(tmp_path_factory):
    """ONE WINDOW FOR THE MODULE (a whole window takes seconds to build);
    each test points HIVEMIND_CONFIG at its own folder."""
    root = tmp_path_factory.mktemp("tour")
    path = root / "settings.yaml"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(panel_mod, "CONFIG", path)
        mp.setattr(schema, "CONFIG", path)
        mp.setattr(schema.Settings.__init__, "__defaults__", (path,))
        mp.setenv("XDG_CONFIG_HOME", str(root / "xdg"))
        mp.setenv("HIVEMIND_CONFIG", str(root / "config"))
        from hivemind.gui.bridge import EventBridge
        from hivemind.gui.shell import ShellWindow
        window = ShellWindow(EventBridge(), bot=_Bot())
        window.bridge.send = lambda event: True
        yield window
        window.close()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def config(tmp_path, monkeypatch, shell):
    monkeypatch.setenv("HIVEMIND_CONFIG", str(tmp_path))
    yield tmp_path
    old = getattr(shell, "tour", None)
    if old is not None:
        old.finish()                    # leave no card for the next test
    shell.tour = None


def _wired(widget, signal) -> bool:
    return widget.isSignalConnected(QMetaMethod.fromSignal(signal))


def _help_page(shell):
    menu = shell._menus["settings"]
    rows = [menu.item(r).text() for r in range(menu.count())]
    return shell._stacks["settings"].widget(rows.index("Help"))


def test_every_tab_has_its_words_and_its_first_page(shell):
    from hivemind.gui.shell import TABS
    assert [key for key, _, _ in tour_mod.STEPS] == [key for key, _ in TABS]
    for key, page, text in tour_mod.STEPS:
        menu = shell._menus[key]
        assert page in [menu.item(r).text() for r in range(menu.count())], (key, page)
        assert text.strip().endswith(".") and "Look at " + page in text


def test_the_marker_sits_beside_the_first_run_marker(config):
    assert tour_mod.marker_path() == config / "tour-seen"


def test_it_shows_once_and_done_writes_the_marker(shell, config):
    card = tour_mod.show_tour(shell)
    assert card is not None and shell.tour is card and not card.isHidden()
    assert not (config / "tour-seen").exists()       # not yet seen to the end
    for _ in tour_mod.STEPS[:-1]:
        assert card.next_button.text() == "Next"
        card.next_button.click()
    assert card.next_button.text() == "Done"
    card.next_button.click()
    assert (config / "tour-seen").exists()
    assert card.isHidden() and shell.tour is None
    assert tour_mod.show_tour(shell) is None          # never by itself again


def test_skip_writes_the_marker(shell, config):
    card = tour_mod.show_tour(shell)
    card.skip_button.click()
    assert (config / "tour-seen").exists()
    assert card.isHidden()
    assert tour_mod.show_tour(shell) is None


def test_each_step_opens_its_tab_and_page(shell, config):
    card = tour_mod.show_tour(shell)
    for key, page, _ in tour_mod.STEPS:
        assert shell.tab_buttons[key].isChecked(), key
        assert shell._menus[key].currentItem().text() == page
        assert card.head.text().startswith("QUICK TOUR")
        if key != tour_mod.STEPS[-1][0]:
            card.next_button.click()


def test_the_help_page_shows_it_again(shell, config):
    (config / "tour-seen").write_text("seen\n", encoding="utf-8")
    assert tour_mod.show_tour(shell) is None
    button = _help_page(shell).tour_button
    assert button is not None and button.text() == "Show the tour again"
    button.click()
    assert shell.tour is not None and not shell.tour.isHidden()
    assert shell.tour.step == 0
    button.click()                                    # twice: still one card
    cards = [c for c in shell.findChildren(tour_mod.Tour) if not c.isHidden()]
    assert cards == [shell.tour]


def test_its_buttons_are_wired(shell, config):
    card = tour_mod.show_tour(shell)
    for button in (card.next_button, card.skip_button):
        assert _wired(button, button.clicked)


def test_the_help_page_alone_has_no_dead_button():
    from hivemind.gui.shell import HelpPage
    assert HelpPage("F12").tour_button is None


def test_the_app_shows_it_after_the_first_run_window():
    """gui/app's main: after the first-run window, demo or not, never on a
    boot autostart, and a broken tour never stops the window opening."""
    text = (Path(tour_mod.__file__).parent / "app.py").read_text(encoding="utf-8")
    main = text[text.index("def main("):]
    call = "show_tour_after(window, window.first_run)"
    assert main.index("show_first_run(") < main.index(call)
    block = main[main.index(call) - 120:main.index(call) + 80]
    assert "try:" in block and "except Exception" in block
    assert "if not args.autostart:" in block


def test_the_tour_waits_for_the_set_up_window_to_close(shell, config):
    """Usability triage 2026-10-26 #16: not both at once on a first open."""
    from PySide6.QtWidgets import QWidget
    first = QWidget()
    first.show()
    tour_mod.show_tour_after(shell, first)
    assert shell.tour is None                       # set-up still open
    first.close()
    assert shell.tour is not None and not shell.tour.isHidden()
    shell.tour.finish()
    first.show()
    first.close()                                   # once only
    assert shell.tour is None
    tour_mod.show_tour_after(shell, None)           # no set-up: seen already
    assert shell.tour is None
