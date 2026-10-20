"""Presets: a whole setup as one file (gui/panels/settings export_preset /
import_preset). Secrets never leave; a preset never sets a secret, a locked
key or a key with no control."""
from __future__ import annotations

import os

import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QCheckBox  # noqa: E402

from hivemind.gui.panels import settings as panel_mod  # noqa: E402
from hivemind.world.settings import LOCKED, SECRET  # noqa: E402

APP = QApplication.instance() or QApplication([])


def _panel(tmp_path, monkeypatch, stored: dict):
    config = tmp_path / "settings.yaml"
    config.write_text(yaml.safe_dump(stored))
    monkeypatch.setattr(panel_mod, "CONFIG", config)
    return panel_mod.SettingsPanel(), config


def test_export_leaves_the_secrets_out(tmp_path, monkeypatch):
    secret = next(iter(SECRET))
    panel, _ = _panel(tmp_path, monkeypatch, {secret: "AIza-not-a-real-key"})
    out = tmp_path / "preset.yaml"
    assert panel.export_preset(out) > 10
    body = yaml.safe_load(out.read_text())
    assert secret not in body and "AIza-not-a-real-key" not in out.read_text()


def test_import_sets_the_controls_tells_the_bot_and_refuses_the_rest(tmp_path, monkeypatch):
    panel, config = _panel(tmp_path, monkeypatch, {})
    box_key = next(k for k, w in panel._widgets.items()
                   if isinstance(w, QCheckBox) and k not in LOCKED)
    want = not panel._widgets[box_key].isChecked()
    secret, locked = next(iter(SECRET)), next(iter(LOCKED))
    preset = tmp_path / "theirs.yaml"
    preset.write_text(yaml.safe_dump({box_key: want, secret: "AIza-theirs",
                                      locked: not LOCKED[locked], "no.such.key": 1}))
    told = []
    panel.changed.connect(lambda k, v: told.append((k, v)))
    taken, skipped = panel.import_preset(preset)
    assert taken == 1 and set(skipped) == {secret, locked, "no.such.key"}
    assert panel._widgets[box_key].isChecked() is want
    assert told == [(box_key, want)]
    stored = yaml.safe_load(config.read_text())
    assert stored[box_key] is want and secret not in stored and locked not in stored


def test_a_file_that_is_not_a_preset_is_refused(tmp_path, monkeypatch):
    panel, _ = _panel(tmp_path, monkeypatch, {})
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a list\n")
    try:
        panel.import_preset(bad)
    except ValueError:
        return
    raise AssertionError("a list was imported as a preset")
