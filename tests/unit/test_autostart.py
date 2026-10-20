"""Start farming when the PC starts (gui/autostart, ROADMAP U13). A temp HOME
and XDG_CONFIG_HOME: the real ~/.config/autostart is never touched, nothing
is sent to Telegram and the bot is a stand-in that only counts Starts."""
from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

os.environ["HIVEMIND_TELEGRAM_ENV"] = str(Path(tempfile.mkdtemp()) / "telegram.env")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui import autostart  # noqa: E402
from hivemind.gui.panels import settings as panel_mod  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402

APP = QApplication.instance() or QApplication([])


class FakeBot:
    process = None
    log_path = "nowhere"

    def __init__(self):
        self.starts = 0

    def running(self) -> bool:
        return False

    def start(self):
        self.starts += 1

        class Launch:
            ok = False

            def describe(self):
                return "not started (test)"
        return Launch()

    def describe_state(self) -> str:
        return ""

    def exit_code(self):
        return None


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    config = tmp_path / "settings.yaml"
    monkeypatch.setattr(panel_mod, "CONFIG", config)
    monkeypatch.setattr(schema, "CONFIG", config)
    monkeypatch.setattr(schema.Settings.__init__, "__defaults__", (config,))
    pending = tmp_path / "var" / "night" / "autostart.pending"
    monkeypatch.setattr(autostart, "pending_path", lambda: pending)
    return tmp_path


@pytest.fixture
def window(home):
    from hivemind.gui.bridge import EventBridge
    from hivemind.gui.window import MainWindow
    w = MainWindow(EventBridge(), bot=FakeBot())
    w.told = []
    w._boot_tell = w.told.append
    yield w
    w.close()


def test_the_entry_is_written_and_removed(home):
    path = autostart.entry_path()
    assert path == home / "xdg" / "autostart" / "hivemind.desktop"
    assert "will open after login" in autostart.apply(True, python="/venv/bin/python")
    text = path.read_text()
    assert "Exec=/venv/bin/python -m hivemind.gui --autostart" in text
    assert text.startswith("[Desktop Entry]") and "Type=Application" in text
    assert "removed" in autostart.apply(False) and not path.exists()
    assert autostart.apply(False) == "start on boot is off"


def test_the_setting_writes_the_entry(window, home):
    assert schema.Settings().bool("gui.start_on_boot") is False      # off by default
    window.settings.set_value("gui.start_on_boot", True)
    assert autostart.entry_path().exists()
    assert yaml.safe_load((home / "settings.yaml").read_text())["gui.start_on_boot"] is True
    window.settings.set_value("gui.start_on_boot", False)
    assert not autostart.entry_path().exists()


def test_off_means_a_login_start_does_nothing(window):
    assert window.begin_autostart() is False
    assert window._boot_banner.isHidden() and window.told == [] and window.bot.starts == 0


def _on(window):
    window.settings.set_value("gui.start_on_boot", True)
    assert window.begin_autostart() is True
    assert not window._boot_banner.isHidden() and autostart.pending_path().exists()
    assert window.told[-1] == "Hivemind opened at login: starting to farm in 60 s. /stop to cancel."
    assert "60 s" in window._boot_label.text()


def test_cancel_stops_the_countdown(window):
    _on(window)
    window.boot_cancel.click()
    assert window._boot_banner.isHidden() and not autostart.pending_path().exists()
    assert not window._boot_timer.isActive() and window.bot.starts == 0


def test_telegram_stop_cancels_it(window, monkeypatch, home):
    _on(window)
    spec = importlib.util.spec_from_file_location(
        "telegram_alerts_t", Path(__import__("hivemind").__file__).resolve().parents[2] / "scripts" / "telegram_alerts.py")
    tg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tg)
    monkeypatch.setattr(tg, "ROOT", home)                  # var/night under the temp HOME
    assert tg.stop_bot().startswith("Cancelled")
    window._boot_tick()
    assert window._boot_banner.isHidden() and window.bot.starts == 0


def test_after_the_grace_the_gates_decide(window, monkeypatch):
    _on(window)
    monkeypatch.setattr(autostart, "blocker", lambda s: "you are playing Minecraft (the game guard)")
    for _ in range(autostart.GRACE_S):
        window._boot_tick()
    assert window.bot.starts == 0 and "Minecraft" in window.told[-1]
    _on(window)
    monkeypatch.setattr(autostart, "blocker", lambda s: "")
    for _ in range(autostart.GRACE_S):
        window._boot_tick()
    assert window.bot.starts == 1 and not autostart.pending_path().exists()


def test_the_gates_are_the_game_guard_then_memory():
    s = schema.Settings(Path(tempfile.mkdtemp()) / "none.yaml")
    assert "Minecraft" in autostart.blocker(s, playing=lambda games: "Minecraft",
                                            memory_check=lambda what: (True, ""))
    assert autostart.blocker(s, playing=lambda games: None,
                             memory_check=lambda what: (False, "not enough memory")) == "not enough memory"
    assert autostart.blocker(s, playing=lambda games: None,
                             memory_check=lambda what: (True, "fine")) == ""


def test_a_preset_never_changes_it(window, home):
    panel = window.settings
    panel.set_value("gui.start_on_boot", True)
    preset = home / "p.yaml"
    panel.export_preset(preset)
    assert "gui.start_on_boot" not in yaml.safe_load(preset.read_text())
    preset.write_text(yaml.safe_dump({"gui.start_on_boot": False}))
    taken, skipped = panel.import_preset(preset)
    assert taken == 0 and skipped == ["gui.start_on_boot"] and autostart.entry_path().exists()
