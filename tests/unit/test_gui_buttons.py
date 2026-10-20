"""Every button, switch and dropdown in the main window is wired to something
(the owner, 2026-10-09: "make sure every button actually works")."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QMetaMethod  # noqa: E402
from PySide6.QtGui import QShortcut  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,  # noqa: E402
                               QPushButton, QSpinBox, QDoubleSpinBox, QLineEdit)


@pytest.fixture
def window(tmp_path, monkeypatch):
    from hivemind.gui.panels import settings as settings_panel
    monkeypatch.setattr(settings_panel, "CONFIG", tmp_path / "settings.yaml")
    from hivemind.gui.bridge import EventBridge
    from hivemind.gui.window import MainWindow
    app = QApplication.instance() or QApplication([])
    w = MainWindow(EventBridge(socket_path=None))
    yield w
    w.close()


def _wired(widget, signal) -> bool:
    return widget.isSignalConnected(QMetaMethod.fromSignal(signal))


def test_every_button_does_something(window):
    dead = [b.text() for b in window.findChildren(QPushButton)
            if not _wired(b, b.clicked) and not _wired(b, b.pressed)
            and not _wired(b, b.released) and not _wired(b, b.toggled)]
    assert dead == [], f"buttons wired to nothing: {dead}"


def _form_field(w) -> bool:
    """An input a button reads when pressed (property 'read_on_click' names
    that button) -- the session goals' amount and hours: it needs no signal."""
    return bool(w.property("read_on_click"))


def test_every_switch_and_box_saves(window):
    dead = []
    for box in window.findChildren(QCheckBox):
        if box.isEnabled() and not _wired(box, box.toggled):
            dead.append(box.objectName() or box.text() or "a checkbox")
    for combo in window.findChildren(QComboBox):
        if combo.isEnabled() and not _form_field(combo) and not any(_wired(combo, s) for s in (
                combo.currentIndexChanged, combo.currentTextChanged,
                combo.activated, combo.textActivated)):
            dead.append(combo.objectName() or combo.currentText() or "a dropdown")
    for spin in window.findChildren(QSpinBox) + window.findChildren(QDoubleSpinBox):
        if spin.isEnabled() and not _form_field(spin) and not _wired(spin, spin.valueChanged):
            dead.append(spin.objectName() or "a number box")
    for edit in window.findChildren(QLineEdit):
        if (edit.isEnabled() and not edit.isReadOnly() and edit.parent() is not None
                and not isinstance(edit.parent(), (QComboBox, QSpinBox, QDoubleSpinBox))
                and not any(_wired(edit, s) for s in (edit.textChanged, edit.textEdited, edit.returnPressed,
                                                        edit.editingFinished))):
            dead.append(edit.objectName() or edit.placeholderText() or "a text box")
    assert dead == [], f"controls wired to nothing: {dead}"


def test_a_macro_tab_switch_writes_the_settings_file(window, tmp_path):
    import yaml
    panel = window.macro_tabs[0]
    key, box = next((k, w) for k, w in panel._widgets.items() if isinstance(w, QCheckBox)
                    and w.isEnabled())
    box.setChecked(not box.isChecked())
    saved = yaml.safe_load((tmp_path / "settings.yaml").read_text())
    assert saved[key] == box.isChecked()


def test_f1_f2_f3(window):
    keys = {s.key().toString() for s in window.findChildren(QShortcut)}
    assert {"F1", "F2", "F3"} <= keys


@pytest.fixture
def shell(tmp_path, monkeypatch):
    """The NEW layout (ROADMAP U18), every page built, Advanced mode on."""
    from hivemind.gui.panels import settings as settings_panel
    monkeypatch.setattr(settings_panel, "CONFIG", tmp_path / "settings.yaml")
    monkeypatch.setenv("HOME", str(tmp_path))
    from hivemind.gui.bridge import EventBridge
    from hivemind.gui import shell as shell_mod
    app = QApplication.instance() or QApplication([])
    w = shell_mod.ShellWindow(EventBridge(socket_path=None))
    yield w
    w.close()


def test_every_button_in_the_new_layout_does_something(shell):
    """The owner, 2026-10-19: "make sure each option toggle setting and button works"."""
    dead = [b.text() or b.toolTip() or b.objectName() or "a button"
            for b in shell.findChildren(QPushButton)
            if b.isEnabled() and not any(_wired(b, s) for s in (b.clicked, b.pressed, b.released, b.toggled))]
    assert dead == [], f"buttons wired to nothing in the new layout: {dead}"


def test_every_switch_and_box_in_the_new_layout_saves(shell):
    dead = []
    for box in shell.findChildren(QCheckBox):
        if box.isEnabled() and not _wired(box, box.toggled):
            dead.append(box.objectName() or box.text() or "a checkbox")
    for combo in shell.findChildren(QComboBox):
        if combo.isEnabled() and not _form_field(combo) and not any(_wired(combo, s) for s in (
                combo.currentIndexChanged, combo.currentTextChanged, combo.activated, combo.textActivated)):
            dead.append(combo.objectName() or combo.currentText() or "a dropdown")
    for spin in shell.findChildren(QSpinBox) + shell.findChildren(QDoubleSpinBox):
        if spin.isEnabled() and not _form_field(spin) and not _wired(spin, spin.valueChanged):
            dead.append(spin.objectName() or "a number box")
    assert dead == [], f"controls wired to nothing in the new layout: {dead}"
