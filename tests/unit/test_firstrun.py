"""The first-run window: Install Sober, Log in to Roblox, Start (gui/firstrun).

No real program is ever started here: the runner and every probe are fakes.
What matters is checked as data -- every argv the window would run is --user,
and none is sudo, pkexec or anything that asks for a password.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtCore import QObject, Signal                     # noqa: E402
from PySide6.QtWidgets import QApplication                     # noqa: E402

from hivemind.cli import doctor                                # noqa: E402
from hivemind.gui import firstrun                              # noqa: E402
from hivemind.gui.panels.liveview import LiveView              # noqa: E402
from hivemind.telemetry.events import (Action, Command, Log,   # noqa: E402
                                       StatusUpdate)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeRunner(QObject):
    output = Signal(str)
    done = Signal(int)
    made: list = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.argv = self.env = None
        self.alive = False
        self.stopped = False
        FakeRunner.made.append(self)

    def start(self, argv, env=None):
        self.argv, self.env, self.alive = argv, env, True

    def running(self):
        return self.alive

    def stop(self):
        self.stopped = True

    def finish(self, code=0):
        self.alive = False
        self.done.emit(code)


class FakeMain(QObject):
    """The main window as the first-run window uses it."""
    event_received = Signal(object)

    def __init__(self):
        super().__init__()
        self.bridge = self
        self.live = LiveView()
        self.sent = []
        self.starts = 0

    def send(self, event):
        self.sent.append(event)
        return True

    def _start(self):
        self.starts += 1


class Machine:
    """flatpak's answers: which remotes the user has, and what is installed."""

    def __init__(self, remotes="", sober=False):
        self.remotes, self.sober = remotes, sober

    def __call__(self, argv):
        if argv == firstrun.REMOTES:
            return self.remotes
        if argv == firstrun.LISTED:
            return "org.vinegarhq.Sober\n" if self.sober else "org.gnome.Platform\n"
        raise AssertionError(f"unexpected probe {argv}")


@pytest.fixture
def setup(app, tmp_path):
    FakeRunner.made = []
    main = FakeMain()
    machine = Machine()
    checks = [doctor.Check("environment", "n", doctor.OK)]
    win = firstrun.FirstRunWindow(main, marker=tmp_path / "first-run-passed",
                                  run_text=machine, runner=FakeRunner,
                                  doctor_run=lambda: checks)
    yield win, main, machine, checks
    win.close()


def test_shown_with_labwc_or_on_a_fresh_install_until_it_passed(tmp_path):
    marker = tmp_path / "first-run-passed"
    assert firstrun.wanted("labwc", False, marker)
    assert firstrun.wanted("hyprland", True, marker)
    assert not firstrun.wanted("hyprland", False, marker), "the owner's machine: unchanged"
    marker.write_text("x")
    assert not firstrun.wanted("labwc", True, marker)


def test_install_adds_the_users_flathub_first_when_it_is_missing(setup):
    win, _, machine, _ = setup
    assert win.install.button.isEnabled() and not win.signin.button.isEnabled()
    win.install.button.click()
    [first] = FakeRunner.made
    assert first.argv == firstrun.REMOTE_ADD
    first.finish(0)
    assert FakeRunner.made[1].argv == firstrun.INSTALL
    machine.sober = True
    FakeRunner.made[1].finish(0)
    assert win.install.status.text() == "Sober is installed."
    assert win.signin.button.isEnabled()
    assert "$ flatpak install --user -y flathub org.vinegarhq.Sober" in win.log.toPlainText()


def test_install_skips_the_remote_when_the_user_has_flathub(setup):
    win, _, machine, _ = setup
    machine.remotes = "flathub\n"
    win.install_sober()
    assert [r.argv for r in FakeRunner.made] == [firstrun.INSTALL]


def test_a_failed_install_says_so_and_can_be_tried_again(setup):
    win, _, _, _ = setup
    win.install_sober()
    FakeRunner.made[0].output.emit("error: Unable to load summary from remote flathub")
    FakeRunner.made[0].finish(1)
    assert "did not work (exit 1)" in win.install.status.text()
    assert win.install.button.isEnabled() and not win.signin.button.isEnabled()
    assert "Unable to load summary" in win.log.toPlainText()


def test_never_root_never_a_password(setup):
    win, _, machine, _ = setup
    win.install_sober()
    for runner in list(FakeRunner.made):
        runner.finish(0)
    machine.sober = True
    win.refresh()
    win.open_roblox()
    for argv in win.commands:
        assert argv[0] not in ("sudo", "pkexec", "su", "doas", "run0")
        if argv[0] == "flatpak":
            assert "--user" in argv
    assert firstrun.INSTALL == ["flatpak", "install", "--user", "-y", "flathub",
                                "org.vinegarhq.Sober"]


def test_login_runs_the_bots_session_and_the_picture_takes_control(setup):
    win, main, machine, _ = setup
    machine.sober = True
    win.refresh()
    win.signin.button.click()
    [login] = FakeRunner.made
    assert login.argv[1:] == ["-m", "hivemind.act.login"]
    assert str(firstrun.SRC) in login.env["PYTHONPATH"]
    assert not win.view.isHidden()
    main.event_received.emit(StatusUpdate(running=False, paused=True, handed_over=True))
    assert win.view.taking and win.view.control == main.send
    main.event_received.emit(Log(message="Roblox is open.", source="login"))
    assert "Roblox is open." in win.log.toPlainText()
    win.signin.button.click()                          # Done, I'm logged in
    assert not win.view.taking
    assert [e.action for e in main.sent if isinstance(e, Command)] == [Action.STOP]
    login.finish(0)
    assert win.login is None and win.view.isHidden()
    assert win.start.button.objectName() == "Primary"


def test_the_login_hint_names_the_configured_panic_key(setup):
    win, main, machine, _ = setup
    main.settings = type("Panel", (), {"values": {"safety.panic_key": "F9"}})()
    machine.sober = True
    win.refresh()
    win.signin.button.click()
    main.event_received.emit(StatusUpdate(running=False, paused=True, handed_over=True))
    assert "F9 or Done stops it." in win.signin.status.text()
    assert "F12" not in win.signin.status.text()


def test_start_checks_first_then_plays_and_remembers(setup):
    win, main, machine, checks = setup
    machine.sober = True
    checks[:] = [doctor.Check("environment", "labwc (headless compositor)", doctor.FAIL,
                              fix="sudo apt install labwc")]
    assert not win.check_and_start()
    assert "labwc (headless compositor): sudo apt install labwc" in win.log.toPlainText()
    assert main.starts == 0 and not win.marker.exists()
    checks[:] = [doctor.Check("environment", "n", doctor.OK)]
    assert win.check_and_start()
    assert main.starts == 1 and win.marker.exists()


def test_start_waits_for_the_login_to_end(setup):
    """Sober runs once: the bot cannot start beside the login's game."""
    win, main, machine, _ = setup
    machine.sober = True
    win.refresh()
    win.open_roblox()
    assert not win.check_and_start()
    assert main.starts == 0 and "Done" in win.start.status.text()


def test_under_tests_without_a_runner_nothing_starts(app, tmp_path):
    main = FakeMain()
    win = firstrun.FirstRunWindow(main, marker=tmp_path / "m", run_text=Machine())
    win.install_sober()
    assert win.commands == [] and "never starts real programs" in win.log.toPlainText()
    win.close()


# ---- the bot's half: act/login --------------------------------------------------
def test_login_hands_the_controls_over_and_puts_everything_away(monkeypatch, tmp_path):
    """Sober in the bot's session, the controls the owner's at once, and on
    the GUI's Stop: Sober, the input, the capture and the session all ended."""
    import threading
    import time as _time
    from hivemind.act import login
    from hivemind.ipc.bus import EventClient
    from hivemind.telemetry.events import GameInput
    ended = []

    class Session:
        def start(self): ended.append("started")
        def game_window_open(self): return True
        def fullscreen_focused(self): return "fullscreen"
        def stop(self): ended.append("session")

    class Game:
        def poll(self): return None
        def terminate(self): ended.append("sober")
        def wait(self, timeout=None): return 0

    class Input:
        def __init__(self): self.keys = []
        def press(self, key): self.keys.append(key)
        def release_all(self): pass
        def close(self): ended.append("input")

    class Capture:
        def capture(self):
            import numpy as np
            return np.zeros((1080, 1920, 4), np.uint8)
        def close(self): ended.append("capture")

    inp = Input()
    path = str(tmp_path / "hm.sock")
    monkeypatch.setattr(login.current, "make_session", lambda: Session())
    monkeypatch.setattr(login.current, "make_input", lambda s: inp)
    monkeypatch.setattr(login.bootstrap, "_launch_sober", lambda *a: Game())
    monkeypatch.setattr(login.bootstrap, "connect_capture",
                        lambda *a, **k: (Capture(), Capture()))
    monkeypatch.setattr(login.LiveView, "start", lambda self: self)
    monkeypatch.setattr(login.LiveView, "stop", lambda self: ended.append("live"))
    result = []
    thread = threading.Thread(target=lambda: result.append(login.main(path)))
    thread.start()
    seen = []
    client = EventClient(path, on_event=seen.append).start()
    deadline = _time.monotonic() + 10
    while not any(isinstance(e, StatusUpdate) and e.handed_over for e in seen):
        assert _time.monotonic() < deadline, seen
        _time.sleep(0.05)
    client.send(GameInput(op="key_down", key="w"))
    while not inp.keys:
        assert _time.monotonic() < deadline
        _time.sleep(0.02)
    client.send(Command(action=Action.STOP))
    thread.join(10)
    client.stop()
    assert result == [0] and inp.keys == ["w"]
    assert {"live", "input", "capture", "sober", "session"} <= set(ended)
