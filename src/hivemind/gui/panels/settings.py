"""Settings, built from a declaration rather than hand-laid widgets.

The owner's requirement was a full set of options, every feature configurable.
Writing ~60 controls by hand would be sixty chances to forget to save one, so
the panel is generated from `world.settings.SECTIONS`: each entry declares a key,
a type, a default and — mandatory — an explanation.

The explanation is not decoration. A macro with sixty cryptic toggles is worse
than one with ten, because the user cannot tell which of them is costing them
honey. Every control here says what it does and, where it matters, what it costs.

Values round-trip through ~/.config/hivemind/settings.yaml. Each change is saved
and then announced to the running bot, which re-reads the file at once -- but
most settings are only READ when an attempt starts, and those are labelled
"applies from the next attempt" rather than promised sooner (DESIGN 8du,
world/settings.READ_AT_EVERY_USE). The bot's Log line says which took effect.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QCoreApplication, QEvent, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QPushButton,
                               QLabel, QLineEdit, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import theme
from ..widgets import Card

# The schema lives in world.settings because BOTH processes need it: the GUI
# builds controls from it, the bot reads the same keys back. One declaration
# means a control cannot exist without something reading it, and a setting
# cannot be read that no control can reach.
from ...files import atomic_write  # noqa: E402
from ...world.settings import (BOUNDS, CONFIG, LOCKED,  # noqa: E402
                               LISTS, NOT_IN_PRESETS, SECRET, SECTIONS, blocked_by,
                               migrate_secrets, take_values,
                               read_secrets, settle, takes_effect, unreadable,
                               wired, write_secret)


# WHAT AN EMPTY GOAL FIELD MEANS, shown in the field itself: an empty box
# otherwise reads as a control that is missing. DESIGN 8dp.
PLACEHOLDERS = {
    "goals.order": "empty = the order you asked for (see below)",
    "goals.have": "e.g. treats=1200, oil=4, gold eggs=1",
    "goals.owned": "e.g. Porcelain Dipper",
    "stream.youtube_channel": "@handle, UC… channel ID, or live-stream link",
    "stream.youtube_api_key": "paste the key (shown as dots)",
}
WIDE = {"stream.youtube_channel", "stream.youtube_api_key"}

# A GOOGLE API KEY IN THE TWITCH BOX (it happened in testing,
# 2026-09-26). Google keys are "AIza" and 35 more of [A-Za-z0-9_-] (39 in all);
# the Twitch reader refuses such a name (stream/chat CHANNEL), so it is sent
# nowhere, but it sits there in plain text. A button under the Twitch row moves
# it, on the owner's own click, into the dotted YouTube key box.
import re as _re
GOOGLE_KEY = _re.compile(r"^AIza[0-9A-Za-z_\-]{35}$")


class SettingsPanel(Card):
    changed = Signal(str, object)

    def __init__(self, parent=None, only=None, title="settings",
                 subtitle="every option, what it costs you, and when the bot picks it up",
                 compact=False):
        # `compact`: the macro tabs' rows -- a label and its switch, the
        # explanation in the hover tooltip, and only the switches the bot
        # reads (the rest stay on Advanced > All settings).
        self._compact = bool(compact)
        # `only`: the SECTIONS names this panel shows (the macro-style tabs,
        # one per job), all of them by default. Saving is one key at a time
        # (`save`), so several of these share the file safely.
        super().__init__(title, subtitle, parent)
        sections = [(name, entries) for name, entries in SECTIONS
                    if only is None or name in only]
        self.values: dict[str, Any] = {}
        self._widgets: dict[str, QWidget] = {}
        # A LIST HAS NO ROW HERE (macro.fields, ROADMAP U16): its editor is
        # the new layout's Macro > Gather. Kept in `values`, loaded and saved
        # like the rest (`set_value` with no widget saves it).
        self._lists: set[str] = set()
        # a list as the FILE has it, before the bot's check drops entries: the
        # Gather list shows a dropped entry with its warning (render probe,
        # UI panel round 2, 2026-10-22: the warning could never fire)
        self.raw_lists: dict[str, Any] = {}
        # Anything load() could not use, shown to the user rather than hidden:
        # a setting that silently reverted to its default is a wrong answer.
        self.problems: list[str] = []

        scroll = QScrollArea()
        # kept so a wheel over an unfocused control can be handed to it
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        column = QVBoxLayout(inner)
        column.setContentsMargins(2, 0, 8, 0)
        column.setSpacing(4)

        for section, entries in sections:
            heading = QLabel(section.upper())
            heading.setStyleSheet(
                f"color: {theme.ACCENT}; font-size: 10px; font-weight: 700;"
                " letter-spacing: 1px; padding: 12px 0 2px 0;"
                " background: transparent;")
            column.addWidget(heading)
            for entry in entries:
                if self._compact and not wired(entry[0]):
                    continue
                if entry[2] == "list":
                    self._lists.add(entry[0])
                    self.values[entry[0]] = list(entry[3])
                    continue
                column.addWidget(self._build_row(entry))

        column.addStretch(1)
        scroll.setWidget(inner)
        if only is None and not self._compact:
            self.add(self._preset_row())
        self.add(scroll, 1)

        self.load()
        self._check_misplaced_key()
        if self.problems:
            # Say so. A setting that quietly reverted to its default is a wrong
            # answer the user has no way to notice.
            warning = QLabel("could not read some settings:\n• "
                             + "\n• ".join(self.problems))
            warning.setWordWrap(True)
            warning.setStyleSheet(
                f"color: {theme.WARN}; background: transparent;"
                " font-size: 11px; padding: 4px 0;")
            column.insertWidget(0, warning)
        self.set_badge(str(sum(len(e) for _, e in sections)))

    # ---- presets -------------------------------------------------------------
    # A WHOLE SETUP AS ONE FILE (2026-10-14: the owner asked for setups that
    # import and export as one .yaml file). The
    # secrets never leave in one (SECRET), and a preset -- maybe someone
    # else's -- never sets a secret, a LOCKED key or a key with no control.
    def _preset_row(self) -> QWidget:
        from PySide6.QtWidgets import QFileDialog
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 6)
        note = QLabel("")
        note.setStyleSheet(f"color: {theme.TEXT_DIM}; background: transparent; font-size: 11px;")

        def export() -> None:
            path, _ = QFileDialog.getSaveFileName(self, "Export preset", str(Path.home() / "hivemind-preset.yaml"),
                                                  "Hivemind preset (*.yaml)")
            if path:
                try:
                    note.setText(f"exported {self.export_preset(path)} settings (no keys or tokens)")
                except OSError as exc:
                    note.setText(f"not exported: {exc.strerror or exc}")

        def import_() -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Import preset", str(Path.home()),
                                                  "Hivemind preset (*.yaml *.yml)")
            if path:
                try:
                    taken, skipped = self.import_preset(path)
                    note.setText(f"imported {taken} settings" + (f", skipped {len(skipped)}" if skipped else ""))
                except (OSError, ValueError, yaml.YAMLError) as exc:
                    note.setText(f"not imported: {unreadable(exc) if isinstance(exc, yaml.YAMLError) else exc}")

        for text, act in (("Export preset…", export), ("Import preset…", import_)):
            button = QPushButton(text)
            button.clicked.connect(act)
            line.addWidget(button)
        line.addWidget(note, 1)
        return row

    # THIS PC'S, NOT A PLAYSTYLE (world/settings.NOT_IN_PRESETS)
    NOT_IN_PRESETS = NOT_IN_PRESETS

    def export_preset(self, path) -> int:
        """Every setting but the secrets, written to `path`; how many."""
        body = {k: v for k, v in {**(self._stored() or {}), **self.values}.items()
                if k not in SECRET and k not in self.NOT_IN_PRESETS}
        atomic_write(Path(path), yaml.safe_dump(body, sort_keys=True))
        return len(body)

    def import_preset(self, path) -> tuple[int, list[str]]:
        """A preset's settings into the file and the controls, the bot told of
        each; (how many taken, the keys skipped). Raises ValueError for a file
        that is not a mapping."""
        loaded = yaml.safe_load(Path(path).read_text())
        if not isinstance(loaded, dict):
            raise ValueError("that file is not a Hivemind preset")
        take, skipped = take_values(loaded, CONFIG,
                                    allowed=set(self._widgets) | self._lists)
        self.load()                           # the controls show it (signals blocked)
        for key in take:
            self.changed.emit(key, self.values.get(key))   # the bot re-reads
        return len(take), skipped

    def _build_row(self, entry: tuple) -> QWidget:
        key, label, kind, default, help_text, *rest = entry
        choices = rest[0] if rest else []

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        box = QVBoxLayout(row)
        box.setContentsMargins(0, 3, 0, 3)
        box.setSpacing(1)

        # A control for something that is not built yet is DISABLED and says
        # so. It stays visible because the schema is the roadmap and hiding it
        # would just mean nobody can see what is coming -- but a toggle that
        # looks live and changes nothing is the interface telling a lie, and
        # `NOT_WIRED` plus its tests are what stop that happening by accident.
        live = wired(key)

        line = QHBoxLayout()
        line.setSpacing(10)
        # SAY WHAT IS STOPPING IT, not just that something is. "not built yet"
        # cannot tell the owner whether a switch needs a week of work or one
        # walk around the map, and most of these need the walk. The reasons
        # live in `world/settings.BLOCKED_BY` beside the NOT_WIRED list they
        # explain, so the two cannot drift apart.
        why = blocked_by(key)
        # WHEN IT APPLIES, where that is not "at once" (DESIGN 8du): the bot
        # reads most settings once per attempt, and the panel used to promise
        # every change reached it immediately.
        when = takes_effect(key)
        # NO "applies from the next attempt" ON EVERY ROW (UI panel
        # 2026-10-21 item 8): it was on most rows and drowned the labels;
        # the control's tooltip below still says it.
        name = QLabel(f"{label}   ·   locked on" if key in LOCKED else
                      label if self._compact or live else
                      f"{label}   ·   not built yet — {why}" if why else
                      f"{label}   ·   not built yet")
        name.setStyleSheet(
            f"color: {theme.TEXT if live else theme.TEXT_FAINT};"
            " background: transparent;")
        # WRAPPED, or the longest "not built yet" reason sets the width of
        # the whole list. MEASURED offscreen on master, panel at 944x560 (the
        # Settings tab of the 1560x940 window; DESIGN 8dp): the list was
        # 2,214 px wide in a 908 px viewport whose horizontal bar is switched
        # off, the Mode box started at x=2,036, and every control -- Mode,
        # walkspeed, the goal fields -- sat past the right edge where it could
        # not be reached. Wrapped: 908 px, Mode at x=730.
        name.setWordWrap(True)
        line.addWidget(name, 1)

        widget = self._control(key, kind, default, choices)
        self._widgets[key] = widget
        self.values[key] = default
        if not live:
            widget.setEnabled(False)
            widget.setToolTip("Nothing reads this setting yet — changing it "
                              "will not affect what the bot does.")
        elif key in LOCKED:
            # DRAWN AS WHAT IT IS: on, and not a switch (DESIGN 8du). The live
            # checkbox wrote `false` in one click.
            widget.setEnabled(False)
            self.values[key] = LOCKED[key]
            widget.setToolTip("Locked on. The bot never types into the game, "
                              "and neither this box nor the file can change "
                              "that.")
        elif when == "from the next attempt":
            widget.setToolTip("The bot reads this once, when an attempt "
                              "starts (after every rejoin), so a change "
                              "applies from the next one.")
        line.addWidget(widget)
        box.addLayout(line)

        if key == "stream.twitch_channel":
            self._move_key = QPushButton("That is a YouTube API key — move it "
                                         "to the YouTube key box")
            self._move_key.setCursor(Qt.PointingHandCursor)
            self._move_key.setStyleSheet(
                f"QPushButton {{ color: {theme.TEXT}; background: {theme.ACCENT_SOFT}; "
                "border-radius: 6px; padding: 6px 12px; font-weight: 700; }}"
                if hasattr(theme, "ACCENT_SOFT") else
                "QPushButton { font-weight: 700; padding: 6px 12px; }")
            self._move_key.clicked.connect(self._move_misplaced_key)
            self._move_key.hide()
            box.addWidget(self._move_key)
        if help_text and self._compact:
            tip = help_text + (f"\n\nApplies {when}." if when else "")
            name.setToolTip(tip)
            widget.setToolTip(tip)
        elif help_text:
            hint = QLabel(help_text)
            hint.setWordWrap(True)
            hint.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; font-size: 11px;"
                " background: transparent;")
            box.addWidget(hint)
        return row

    def _control(self, key: str, kind: str, default, choices) -> QWidget:
        if kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(default))
            widget.toggled.connect(lambda v, k=key: self._on_change(k, v))
        elif kind == "int":
            widget = QSpinBox()
            low, high, _step = BOUNDS.get(key, (0, 1_000_000_000, None))
            widget.setRange(int(low), int(high))
            widget.setValue(int(default))
            widget.setMinimumWidth(150)   # 130 cut its number (2026-10-22)
            widget.valueChanged.connect(lambda v, k=key: self._on_change(k, v))
        elif kind == "float":
            widget = QDoubleSpinBox()
            low, high, step = BOUNDS.get(key, (0.0, 1e9, None))
            widget.setRange(float(low), float(high))
            if step:
                widget.setSingleStep(float(step))
            widget.setValue(float(default))
            widget.setMinimumWidth(150)   # 130 cut its number (2026-10-22)
            widget.valueChanged.connect(lambda v, k=key: self._on_change(k, v))
        elif kind == "choice":
            widget = QComboBox()
            widget.addItems([str(c) for c in choices])
            widget.setCurrentText(str(default))
            # as wide as its longest choice, never under 170 (UI panel item 7)
            widget.setMinimumWidth(170)
            widget.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            widget.currentTextChanged.connect(lambda v, k=key: self._on_change(k, v))
        else:
            widget = QLineEdit(str(default))
            # THE GOAL LISTS ARE SENTENCES, not a hotkey or a username: six
            # item names do not fit in 130 px, and a list you cannot read is
            # a list you cannot check (DESIGN 8dp). A pasted YouTube link and
            # a 39-character key are not short either (DESIGN 8ed).
            widget.setFixedWidth(420 if key.startswith("goals.") else
                                 320 if key in WIDE else 130)
            widget.setPlaceholderText(PLACEHOLDERS.get(key, ""))
            if key in SECRET:
                # DOTS, NOT THE KEY (DESIGN 8ed): the settings tab can be on
                # screen while the owner streams. Qt's Password mode also
                # refuses to copy the text out of the box.
                widget.setEchoMode(QLineEdit.Password)
            widget.textChanged.connect(lambda v, k=key: self._on_change(k, v))
        if isinstance(widget, (QSpinBox, QDoubleSpinBox, QComboBox)):
            # A WHEEL OVER A CONTROL SCROLLS THE PAGE (DESIGN 8du). Qt's
            # default lets a hovered spin box or combo take the wheel, so
            # scrolling down this tab to read it changed whatever passed under
            # the cursor, and every step was saved: the owner's file holds
            # autonomy.max_spend 4999997 and min_confidence 8.9. StrongFocus
            # means a click or Tab is needed before the wheel may change it.
            widget.setFocusPolicy(Qt.StrongFocus)
            widget.installEventFilter(self)
        return widget

    def set_value(self, key: str, value) -> None:
        """Change a setting from elsewhere in the window, exactly as if it had
        been typed: the control shows it, the file is saved and the bot is
        told. The Decision Inbox's "I bought it" writes `goals.owned` here."""
        widget = self._widgets.get(key)
        if isinstance(widget, QLineEdit):
            widget.setText(str(value))        # textChanged -> _on_change
        elif isinstance(widget, QComboBox):
            # the window's Simple / Advanced switch writes `gui.mode` here
            if widget.currentText() == str(value):
                self._on_change(key, str(value))
            else:
                widget.setCurrentText(str(value))   # currentTextChanged -> _on_change
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))    # toggled -> _on_change
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            # the new layout's number cards (gui/shell) save through here
            widget.setValue(type(widget.value())(value))   # valueChanged -> _on_change
        elif widget is None:
            self._on_change(key, value)

    def _check_misplaced_key(self) -> None:
        button = getattr(self, "_move_key", None)
        if button is not None:
            value = str(self.values.get("stream.twitch_channel") or "").strip()
            button.setVisible(bool(GOOGLE_KEY.match(value)))

    def _move_misplaced_key(self) -> None:
        """The owner's click: the key goes into the (dotted) YouTube key box
        and the Twitch box is emptied. Nothing is sent anywhere by this."""
        value = str(self.values.get("stream.twitch_channel") or "").strip()
        if not GOOGLE_KEY.match(value):
            return
        self.set_value("stream.youtube_api_key", value)
        self.set_value("stream.twitch_channel", "")
        self._check_misplaced_key()

    def _on_change(self, key: str, value) -> None:
        self.values[key] = value
        if key == "stream.twitch_channel":
            self._check_misplaced_key()
        # SAVE, THEN SAY SO. The bot re-reads the file when it hears of a
        # change (run_farm on_command), and the announcement used to go first
        # -- so the bot could read the old file.
        self.save(key)
        self.changed.emit(key, value)

    def eventFilter(self, obj, event) -> bool:
        """Hand an unfocused control's wheel to the page instead.

        Returning True alone would swallow it -- a filtered event does not
        propagate -- and the page would stop scrolling wherever a control sat
        under the cursor, so it is given to the scroll area first.
        """
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            QCoreApplication.sendEvent(self._scroll.viewport(), event)
            return True
        return super().eventFilter(obj, event)

    # ---- persistence ------------------------------------------------------
    def load(self) -> None:
        """Apply the stored settings, surviving anything the file contains.

        NOTHING here may raise. This runs inside SettingsPanel.__init__, which
        runs inside MainWindow.__init__, so an exception means the application
        exits with a traceback and NO WINDOW -- leaving the user with a GUI
        that will not start and no way to reach the setting that broke it.

        And a bad file is reachable without hand-editing: a QLineEdit fires
        textChanged once per keystroke, so this file used to be rewritten in
        place on every character typed. A kill or a full disk mid-write left a
        truncated document. (save() below is atomic now, which closes that
        door, but the door stays locked from this side too.)
        """
        # NO FILE IS NOT A PROBLEM. Until something is changed there is
        # nothing to store, and every default is already in the widgets. The
        # owner opened a fresh install and was met with
        #
        #     could not read some settings:
        #     could not read /home/<user>/.config/hivemind/settings.yaml:
        #     [Errno 2] No such file or directory
        #
        # in a red warning above the list, which reads as a broken program
        # rather than as "you have not changed anything yet". `world/settings`
        # has always treated a missing file this way; this panel did not.
        # THE SECRETS, from secrets.env (world/settings SECRET); one still in
        # settings.yaml is moved there first, once.
        migrate_secrets(CONFIG)
        stored = {}
        if CONFIG.exists():
            try:
                stored = yaml.safe_load(CONFIG.read_text()) or {}
            except (OSError, yaml.YAMLError) as exc:
                # its problem and line only: PyYAML's own text quotes the
                # line, which can be the YouTube key's (settings.unreadable)
                self._note_problem(f"could not read {CONFIG}: {unreadable(exc)}")
                stored = {}
            if not isinstance(stored, dict):
                self._note_problem(f"{CONFIG} is not a mapping — using defaults")
                stored = {}
        stored = {**stored, **read_secrets(CONFIG)}
        for key, value in stored.items():
            widget = self._widgets.get(key)
            if key in self._lists:
                # checked the way the bot checks it (world/settings), so the
                # editor never shows an entry the bot would leave out
                self.raw_lists[key] = value
                self.values[key], why = LISTS[key](value)
                for problem in why:
                    self._note_problem(problem)
                continue
            if widget is None:
                continue                     # a setting from a newer version
            if key in LOCKED:
                if value != LOCKED[key]:
                    self._note_problem(f"{key} is locked to {LOCKED[key]}; "
                                       f"the file's {value!r} is ignored")
                continue
            try:
                widget.blockSignals(True)
                if isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                    # bool is an int subclass, so `no` would silently become 0
                    if isinstance(value, bool):
                        raise ValueError("expected a number, got a boolean")
                    # A VALUE THE BOX CANNOT HOLD IS SAID, not quietly moved,
                    # and it becomes what the bot makes of it (world/settings
                    # settle): the default where the reader reads it as
                    # unset, not the bound. Clamped, hive_slot 7 showed 6 and
                    # the next unrelated change saved 6 for the bot to walk.
                    value, why = settle(key, value)
                    if why:
                        self._note_problem(why)
                    widget.setValue(type(widget.value())(value))
                    # a number with no BOUNDS entry, outside the box's range
                    if not widget.minimum() <= value <= widget.maximum():
                        self._note_problem(
                            f"{key}: {value} is outside {widget.minimum():g}.."
                            f"{widget.maximum():g}; shown and used as "
                            f"{widget.value():g}")
                        value = widget.value()
                elif isinstance(widget, QComboBox):
                    widget.setCurrentText(str(value))
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(value))
                self.values[key] = value
            except (TypeError, ValueError) as exc:
                # one unusable value must not cost the other forty-one. Text
                # in a number's place is not quoted: int()'s message would
                # repeat it, and it could be the YouTube key, misplaced.
                self._note_problem(f"{key}: " + (
                    "expected a number, got text" if isinstance(value, str)
                    else str(exc)) + " — keeping the default")
            finally:
                widget.blockSignals(False)

    def _note_problem(self, message: str) -> None:
        self.problems.append(message)

    def save(self, key: str | None = None) -> None:
        """`key` -- or with none, every value here -- written into the file
        as it is NOW.

        ONE KEY, NOT THE WINDOW'S WHOLE COPY (2026-10-01). The panel reads the
        file once, when the window opens, and this wrote all of `self.values`
        back on every keystroke -- so a line changed in the file while the
        window stayed open (the stream window runs for days: the Pine Tree pin
        and a goal marked owned were set by hand after it opened) went back to
        what the window had first read, and a setting newer than the window's
        own code (it has no control here, so `load` skips it) was dropped,
        whatever key the owner touched. A file that cannot be read as a
        mapping is written whole from here, as before -- that is the repair."""
        try:
            # A SECRET GOES TO secrets.env, never here (world/settings SECRET):
            # one left in this file by an older version moves on this save.
            migrate_secrets(CONFIG)
            if key in SECRET:
                write_secret(CONFIG, key, self.values.get(key))
                return
            stored = self._stored()
            if key is not None and stored is not None:
                stored[key] = self.values.get(key)
                body = stored
            else:
                body = {**(stored or {}), **self.values}
            body = {k: v for k, v in body.items() if k not in SECRET}
            # Atomically: see hivemind.files. This is rewritten on every
            # keystroke, so an interrupted write is a routine event, not an
            # exotic one, and a truncated settings file used to stop the whole
            # window from opening.
            atomic_write(CONFIG, yaml.safe_dump(body, sort_keys=True))
        except OSError:
            pass                             # a read-only home must not crash the GUI

    @staticmethod
    def _stored() -> dict | None:
        """The file as it is now: {} when there is none, None when it cannot
        be read as a mapping."""
        if not CONFIG.exists():
            return {}
        try:
            loaded = yaml.safe_load(CONFIG.read_text())
        except (OSError, yaml.YAMLError):
            return None
        if loaded is None:
            return {}
        return loaded if isinstance(loaded, dict) else None
