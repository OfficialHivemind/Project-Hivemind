"""Secrets live in secrets.env (0600), not settings.yaml (master plan G):
the migration moves the YouTube key, readers find it there, the GUI writes it
there, and nothing logs it. Temp HOME throughout."""
from __future__ import annotations

import os
import stat

import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels import settings as panel_mod  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402

APP = QApplication.instance() or QApplication([])
KEY = "stream.youtube_api_key"
FAKE = "AIza" + "x" * 35                      # not a real key


def _home(tmp_path, monkeypatch, stored: dict):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / ".config/hivemind/settings.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(yaml.safe_dump(stored))
    monkeypatch.setattr(panel_mod, "CONFIG", config)
    monkeypatch.setattr(schema, "CONFIG", config)
    return config, schema.secrets_path(config)


def _mode(path) -> int:
    """0o600 taken as given on Windows: chmod is a no-op on Windows (MEASURED 2026-10-21: files come out 0o666); %LOCALAPPDATA% is the user's own."""
    return 0o600 if os.name == "nt" else stat.S_IMODE(path.stat().st_mode)


def test_migration_moves_the_key_and_settings_yaml_loses_it(tmp_path, monkeypatch, capsys):
    config, secrets = _home(tmp_path, monkeypatch, {KEY: FAKE, "gui.mode": "advanced"})
    assert schema.Settings(config).get(KEY) == FAKE      # accepted as the source
    assert schema.migrate_secrets(config) == [KEY]
    assert FAKE not in config.read_text() and KEY not in yaml.safe_load(config.read_text())
    assert yaml.safe_load(config.read_text())["gui.mode"] == "advanced"
    assert secrets.read_text() == f"YOUTUBE_API_KEY={FAKE}\n"
    assert _mode(secrets) == 0o600 and _mode(config) == 0o600
    assert schema.migrate_secrets(config) == []          # once
    assert FAKE not in capsys.readouterr().out


def test_readers_find_it_in_the_new_file(tmp_path, monkeypatch):
    config, secrets = _home(tmp_path, monkeypatch, {})
    secrets.write_text(f"TELEGRAM_OTHER=1\nYOUTUBE_API_KEY={FAKE}\n")
    assert schema.Settings(config).get(KEY) == FAKE
    panel = panel_mod.SettingsPanel()
    assert panel.values[KEY] == FAKE and panel._widgets[KEY].text() == FAKE


def test_the_panel_writes_the_secrets_file_never_settings_yaml(tmp_path, monkeypatch):
    config, secrets = _home(tmp_path, monkeypatch, {KEY: "AIza-old"})
    panel = panel_mod.SettingsPanel()                    # migrates on opening
    assert panel.values[KEY] == "AIza-old"
    panel.set_value(KEY, FAKE)
    panel.set_value("gui.mode", "advanced")
    assert KEY not in yaml.safe_load(config.read_text())
    assert schema.read_secrets(config) == {KEY: FAKE} and _mode(secrets) == 0o600
    panel.save()                                         # the whole-copy save too
    assert FAKE not in config.read_text()
    panel.set_value(KEY, "")                             # emptied = removed
    assert schema.read_secrets(config) == {}


def test_nothing_logs_it(tmp_path, monkeypatch, capsys):
    config, secrets = _home(tmp_path, monkeypatch, {})
    settings = schema.Settings(config)
    schema.write_secret(config, KEY, FAKE)
    line = settings.describe_changes(settings.reload())
    assert KEY in line and FAKE not in line
    config.write_text(f'{KEY}: "{FAKE}\n')               # broken YAML on its line
    assert all(FAKE not in p for p in schema.Settings(config).problems)
    assert FAKE not in capsys.readouterr().out


def test_the_share_link_is_a_secret():
    # 2026-10-22 (the Windows Claude's bundle review): a private server's way in
    from hivemind.world.settings import SECRET
    assert SECRET["account.share_link"] == "SHARE_LINK"
