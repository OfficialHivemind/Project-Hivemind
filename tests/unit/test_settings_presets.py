"""Presets: a whole setup as one file (gui/panels/settings export_preset /
import_preset). Secrets never leave; a preset never sets a secret, a locked
key or a key with no control."""
from __future__ import annotations

import os
import re

import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QCheckBox  # noqa: E402

from hivemind.gui.panels import settings as panel_mod  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402
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


# ---- PRESET-HYG: account/PC facts never travel; renamed keys carry over ----

# A key whose NAME says it is an identity, a link, a channel, a path, a slot,
# a key on this keyboard or this PC's software. (stream.voice_name is a choice
# of voice, not anyone's name, so the pattern does not match it.)
PRIVATE_NAME = re.compile(r"(\.username|link|server\.name|channel|_file|follow_user|"
                          r"_slot|panic_key|compositor|_model|\.games|_id)$")


def test_every_account_or_pc_key_stays_out_of_presets():
    keys = set(schema.defaults())
    assert schema.NOT_IN_PRESETS <= keys                   # no typo'd name
    named = {k for k in keys if PRIVATE_NAME.search(k)}
    assert named and named <= schema.NOT_IN_PRESETS, named - schema.NOT_IN_PRESETS


def test_export_and_import_leave_this_account_and_pc_alone(tmp_path, monkeypatch):
    mine = {"account.username": "Someone_Real", "server.name": "Someone's server",
            "move.hive_slot": 4, "stream.twitch_channel": "somechan",
            "safety.panic_key": "F9", "gather.convert_at": 80}
    panel, config = _panel(tmp_path, monkeypatch, mine)
    out = tmp_path / "shared.yaml"
    panel.export_preset(out)
    body = yaml.safe_load(out.read_text())
    assert body["gather.convert_at"] == 80
    assert not set(body) & schema.NOT_IN_PRESETS
    assert "Someone" not in out.read_text() and "somechan" not in out.read_text()
    theirs = tmp_path / "theirs.yaml"
    theirs.write_text(yaml.safe_dump({"account.username": "Other", "move.hive_slot": 1,
                                      "safety.panic_key": "F1", "gather.convert_at": 60}))
    taken, skipped = panel.import_preset(theirs)
    stored = yaml.safe_load(config.read_text())
    assert taken == 1 and stored["gather.convert_at"] == 60
    assert [stored[k] for k in ("account.username", "move.hive_slot", "safety.panic_key")] \
        == ["Someone_Real", 4, "F9"]
    assert set(skipped) == {"account.username", "move.hive_slot", "safety.panic_key"}


def test_an_old_preset_imports_migrated(tmp_path, monkeypatch):
    """The measured case: `gather.rotate_camera: true` from when it was a switch
    (every settings.yaml* on the owner's PC, 2026-10-27)."""
    panel, config = _panel(tmp_path, monkeypatch, {})
    old = tmp_path / "old.yaml"
    old.write_text("gather.rotate_camera: true\ngather.convert_at: 70\n")
    panel.import_preset(old)
    stored = yaml.safe_load(config.read_text())
    assert stored["gather.rotate_camera"] == "never" and stored["gather.convert_at"] == 70


def test_a_named_migration_runs_once_on_load_and_is_written_back(tmp_path, monkeypatch):
    def rename(values):
        if "gather.old_name" in values and "gather.convert_at" not in values:
            values["gather.convert_at"] = values.pop("gather.old_name")
    monkeypatch.setattr(schema, "MIGRATIONS",
                        schema.MIGRATIONS + (("old_name_to_convert_at", rename),))
    config = tmp_path / "settings.yaml"
    config.write_text("gather.old_name: 77\ngather.rotate_camera: true\n")
    # read before anything rewrote the file: already migrated, nothing said
    s = schema.Settings(config)
    assert s.get("gather.convert_at") == 77 and s.get("gather.rotate_camera") == "never"
    assert not s.problems
    # written back once, with the marker...
    assert schema.migrate_secrets(config) == []
    stored = yaml.safe_load(config.read_text())
    assert stored["gather.convert_at"] == 77 and "gather.old_name" not in stored
    assert stored["_migrated"] == [name for name, _ in schema.MIGRATIONS]
    assert stored["_migrated"][-1] == "old_name_to_convert_at"
    # ...and never again: a marked file is not rewritten, a marked dict not touched
    before = config.read_text()
    schema.migrate_secrets(config)
    assert config.read_text() == before
    marked = {"_migrated": list(stored["_migrated"]), "gather.old_name": 5}
    assert schema.migrate(marked) == [] and marked["gather.old_name"] == 5
