"""The settings panel must open whatever is in the settings file.

It is constructed inside MainWindow.__init__, so anything it raises kills the
application before a window appears -- leaving the user with a GUI that will
not start and no way to reach the setting that broke it. That is the worst
possible place for an unguarded parse.

A bad file is also reachable without hand-editing: a QLineEdit fires
textChanged once per keystroke, so the file used to be rewritten in place on
every character typed, and a kill or a full disk mid-write left a truncated
document.
"""
import os

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication            # noqa: E402

from hivemind.gui.panels import settings as panel     # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "settings.yaml"
    monkeypatch.setattr(panel, "CONFIG", path)
    return path


MALFORMED = {
    "a bare string": "just a string\n",
    "a list": "- one\n- two\n",
    "a non-numeric int": "gather.convert_at: auto\n",
    "a boolean for a float": "autonomy.min_confidence: no\n",
    "a boolean for an int": "gather.convert_at: yes\n",
    "truncated mid-write": "gather.convert_at: 8\nautonomy.min_c",
    "an empty file": "",
}


@pytest.mark.parametrize("name", sorted(MALFORMED))
def test_a_malformed_file_still_opens_the_panel(app, config, name):
    config.write_text(MALFORMED[name])
    built = panel.SettingsPanel()            # must not raise
    assert built.values["gather.convert_at"] == 95, "the default must survive"   # pro tester round 1


@pytest.mark.parametrize("name", sorted(set(MALFORMED) - {"an empty file"}))
def test_the_user_is_told_what_could_not_be_read(app, config, name):
    config.write_text(MALFORMED[name])
    assert panel.SettingsPanel().problems, "a silent revert is a wrong answer"


def test_a_valid_file_loads_and_reports_nothing(app, config):
    config.write_text("gather.convert_at: 85\nsafety.never_chat: true\n")
    built = panel.SettingsPanel()
    assert built.problems == []
    assert built.values["gather.convert_at"] == 85


def test_one_bad_value_does_not_cost_the_good_ones(app, config):
    config.write_text("gather.convert_at: auto\nsafety.panic_key: F9\n")
    built = panel.SettingsPanel()
    assert built.values["gather.convert_at"] == 95        # rejected: the default (pro tester round 1)
    assert built.values["safety.panic_key"] == "F9"       # kept
    assert len(built.problems) == 1


def test_saving_is_atomic(app, config):
    built = panel.SettingsPanel()
    built.values["gather.convert_at"] = 77
    built.save()
    assert yaml.safe_load(config.read_text())["gather.convert_at"] == 77
    strays = [p.name for p in config.parent.iterdir() if p.name != config.name]
    assert strays == [], f"left a temporary file behind: {strays}"


# --- a save writes one key into the file as it is now (2026-10-01) ----------------

def test_a_change_keeps_lines_edited_after_the_window_opened(app, config):
    """The stream window stays open for days; a line changed by hand meanwhile
    (the Pine Tree pin, a goal marked owned) must survive the owner's next
    keystroke on some other setting."""
    config.write_text("gather.convert_at: 85\ngather.auto_field: true\n")
    built = panel.SettingsPanel()                       # reads the file once
    edited = yaml.safe_load(config.read_text())
    edited["gather.auto_field"] = False                 # by hand, window still open
    config.write_text(yaml.safe_dump(edited))
    built._on_change("gather.convert_at", 70)
    after = yaml.safe_load(config.read_text())
    assert after["gather.convert_at"] == 70
    assert after["gather.auto_field"] is False


def test_a_change_keeps_settings_newer_than_the_window(app, config):
    """A key this panel has no control for (a newer version's) is skipped by
    `load`, so writing the panel's copy dropped it."""
    config.write_text("gather.convert_at: 85\nmove.some_newer_knob: 1.5\n")
    built = panel.SettingsPanel()
    built._on_change("gather.convert_at", 70)
    after = yaml.safe_load(config.read_text())
    assert after["move.some_newer_knob"] == 1.5
    assert after["gather.convert_at"] == 70


def test_the_owners_change_wins_for_its_own_key(app, config):
    config.write_text("gather.convert_at: 85\n")
    built = panel.SettingsPanel()
    config.write_text("gather.convert_at: 60\n")        # changed meanwhile
    built._on_change("gather.convert_at", 75)           # and then by the owner
    assert yaml.safe_load(config.read_text())["gather.convert_at"] == 75


def test_an_unreadable_file_is_repaired_whole(app, config):
    config.write_text("gather.convert_at: 8\nautonomy.min_c")   # truncated mid-write
    built = panel.SettingsPanel()
    config.write_text("- not\n- a mapping\n")
    built._on_change("gather.convert_at", 70)
    after = yaml.safe_load(config.read_text())
    assert isinstance(after, dict) and after["gather.convert_at"] == 70
    assert "safety.never_chat" in after                  # every value written back
