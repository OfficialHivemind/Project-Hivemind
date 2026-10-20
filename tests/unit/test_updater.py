"""U15f's second half (gui/updater): the Updates card on Settings > General.
Offscreen, with fakes for GitHub, the download, the installer and the app:
nothing here reaches the network or starts a process."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind import update  # noqa: E402
from hivemind.gui import updater  # noqa: E402
from hivemind.world.settings import defaults, describe, takes_effect  # noqa: E402

APP = QApplication.instance() or QApplication([])

NEWER = update.Release(tag="v0.2.0", version=(0, 2, 0), url="https://example.invalid/Hivemind-Setup.exe",
                       size=150_000_000, sha256="a" * 64, prerelease=False,
                       page="https://example.invalid/releases/v0.2.0")


class World:
    """Everything the card reaches, recorded."""

    def __init__(self, on=False, chosen=True, found=NEWER, why_not=""):
        self.values = {"gui.check_updates": on}
        self.saved, self.checks, self.downloads, self.started = [], 0, [], []
        self.stopped, self.quits, self.notes = True, 0, []
        self.found, self.why, self._chosen = found, why_not, chosen
        self.download_error = None

    def check(self):
        self.checks += 1
        return self.found, "Hivemind 0.2.0 is out (you have 0.1.0)" if self.found else \
            "Hivemind 0.1.0 is the newest"

    def download(self, release):
        self.downloads.append(release.tag)
        if self.download_error:
            raise self.download_error
        return Path("C:/fake/Hivemind-Setup.exe")

    def save(self, key, value):
        self.saved.append((key, value))
        self.values[key] = value

    def card(self, **kw) -> updater.UpdateCard:
        def quit_app():
            self.quits += 1
        return updater.UpdateCard(
            lambda: self.values, self.save, lambda: self.stopped, quit_app,
            chosen=lambda: self._chosen, check=self.check, download=self.download,
            start=self.started.append, run=lambda work: work(), why_not=lambda: self.why,
            tell=self.notes.append, **kw)


def test_the_setting_is_off_by_default_and_says_what_it_does():
    assert defaults()["gui.check_updates"] is False          # AGENTS rule 5
    assert "never contacts GitHub" in describe("gui.check_updates")
    assert takes_effect("gui.check_updates") == "at its next use"
    from hivemind.gui.panels.settings import SettingsPanel
    assert "gui.check_updates" in SettingsPanel.NOT_IN_PRESETS   # a preset cannot say yes
    # the installer's first-run settings leave it unchosen, so the card asks
    import yaml
    preset = Path(update.__file__).resolve().parents[2] / "data/presets/safe-first-run.yaml"
    assert "gui.check_updates" not in yaml.safe_load(preset.read_text(encoding="utf-8"))


def test_off_it_never_contacts_github():
    w = World(on=False)
    card = w.card()
    assert not card.check_button.isEnabled()
    card.check()
    card.check_soon(0)
    APP.processEvents()
    assert w.checks == 0 and "does not contact GitHub" in card.line.text()
    assert not card.question.isVisible() and card.question.isHidden()      # chosen already


def test_the_first_run_question_yes_saves_and_checks():
    w = World(on=False, chosen=False)
    card = w.card()
    assert not card.question.isHidden()
    card.yes_button.click()
    assert w.saved == [("gui.check_updates", True)] and w.checks == 1
    assert card.question.isHidden() and "0.2.0 is out" in card.line.text()


def test_the_question_shows_alone_and_promises_only_what_this_copy_does():
    """Usability triage 2026-10-27 #9: the question and its "Off" answer
    showed at once, and Linux was promised a Download and install button."""
    from PySide6.QtWidgets import QLabel
    card = World(on=False, chosen=False, why_not="The installer is for Windows").card()
    assert card.line.isHidden() and card.check_button.isHidden()
    words = " ".join(lab.text() for lab in card.question.findChildren(QLabel))
    assert "only tells you" in words and "Download and install" not in words
    card.no_button.click()
    assert not card.line.isHidden() and not card.check_button.isHidden()
    windows = World(on=False, chosen=False).card()
    assert "Download and install" in " ".join(lab.text() for lab in windows.question.findChildren(QLabel))


def test_the_first_run_question_no_saves_off_and_checks_nothing():
    w = World(on=False, chosen=False)
    card = w.card()
    card.no_button.click()
    assert w.saved == [("gui.check_updates", False)] and w.checks == 0
    assert card.question.isHidden()


def test_newest_already_offers_nothing():
    w = World(on=True, found=None)
    card = w.card()
    card.check_button.click()
    assert "is the newest" in card.line.text() and card.install_button.isHidden()


def test_install_is_offered_only_while_the_bot_is_stopped():
    w = World(on=True)
    card = w.card()
    card.check_button.click()
    assert not card.install_button.isHidden() and card.install_button.isEnabled()
    assert w.notes and "0.2.0 is out" in w.notes[0]
    w.stopped = False                      # Start pressed: the window calls sync
    card.sync()
    assert not card.install_button.isEnabled() and "mid-trip" in card.install_button.toolTip()
    card.install()                         # even called directly: nothing
    assert w.downloads == [] and w.started == [] and w.quits == 0


def test_install_downloads_starts_the_installer_and_closes():
    w = World(on=True)
    card = w.card()
    card.check_button.click()
    card.install_button.click()
    assert w.downloads == ["v0.2.0"]
    assert w.started == [Path("C:/fake/Hivemind-Setup.exe")] and w.quits == 1
    assert "settings" in card.line.text()


def test_a_bad_download_is_said_and_nothing_runs():
    w = World(on=True)
    w.download_error = ValueError("the download's sha256 is 00, not the aa the release notes give")
    card = w.card()
    card.check_button.click()
    card.install_button.click()
    assert "did not work" in card.line.text() and "sha256" in card.line.text()
    assert w.started == [] and w.quits == 0 and card.install_button.isEnabled()


def test_a_bot_started_during_the_download_waits_then_installs_without_downloading_again():
    w = World(on=True)
    card = w.card()
    card.check_button.click()
    real = w.download

    def download_while_start_pressed(release):
        w.stopped = False
        return real(release)
    card._download_fn = download_while_start_pressed
    card.install_button.click()
    assert w.started == [] and w.quits == 0 and "stop it" in card.line.text()
    assert card.install_button.text() == "Install" and not card.install_button.isEnabled()
    w.stopped = True
    card.sync()
    card.install_button.click()
    assert w.downloads == ["v0.2.0"] and len(w.started) == 1 and w.quits == 1


def test_where_it_cannot_install_it_gives_the_releases_link():
    w = World(on=True, why_not="The installer is for Windows: get the new version from "
                               "the releases page.")
    card = w.card()
    card.check_button.click()
    assert card.install_button.isHidden()
    assert "example.invalid/releases/v0.2.0" in card.line.text()
    card.install()
    assert w.downloads == [] and w.started == []


def test_turning_the_setting_off_takes_the_offer_away():
    w = World(on=True)
    card = w.card()
    card.check_button.click()
    w.values["gui.check_updates"] = False
    card.show_setting(False)
    assert not card.install_button.isEnabled() and not card.check_button.isEnabled()


def test_the_check_runs_off_the_gui_thread_and_lands_on_it():
    import threading
    w = World(on=True)
    seen = []

    def check():
        seen.append(threading.current_thread() is threading.main_thread())
        return w.check()
    card = updater.UpdateCard(lambda: w.values, w.save, lambda: True, lambda: None,
                              check=check, why_not=lambda: "")
    card.check()
    for _ in range(200):
        APP.processEvents()
        if card.release is not None:
            break
        threading.Event().wait(0.01)
    assert seen == [False] and card.release is NEWER and not card.busy


def test_only_an_installed_windows_copy_runs_the_installer(tmp_path):
    assert "Windows" in updater.why_not_install("linux", tmp_path)
    assert "git pull" in updater.why_not_install("win32", tmp_path)        # a checkout
    (tmp_path / "unins000.exe").write_bytes(b"")
    assert updater.why_not_install("win32", tmp_path) == ""


def test_the_installer_is_started_as_its_own_process():
    calls = []
    updater.start_installer(Path("C:/fake/Hivemind-Setup.exe"),
                            popen=lambda args, **kw: calls.append((args, kw)))
    (args, kw), = calls
    assert args == [str(Path("C:/fake/Hivemind-Setup.exe"))] and kw["close_fds"] is True


def test_the_ui_preview_never_offers_an_update(monkeypatch):
    """A demo (the UI Preview) gets a plain line: no first-run question, no
    GitHub, no Download and install of the FULL app (review 2026-10-26)."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    QApplication.instance() or QApplication([])
    from hivemind.gui import shell as shell_mod
    monkeypatch.setenv("HIVEMIND_DEMO", "1")
    me = SimpleNamespace()
    card = shell_mod.ShellWindow._update_card(me)
    assert not hasattr(me, "updates")
    assert not card.findChildren(QPushButton)
    assert any("releases" in l.text() for l in card.findChildren(QLabel))
