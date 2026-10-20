"""The new Hivemind window (ROADMAP U18).

    +------------------------------------------------------------------+
    | logo  MACRO  AI PROGRESS  BOOSTING  STATS  SETTINGS      [Search] |
    +----------+-------------------------------------------------------+
    | side     | ( pill ) ( pill )                                     |
    | menu     | [ setting card ]  [ setting card ]                    |
    |          | [ setting card ]  [ setting card ]   or a whole panel |
    +----------+-------------------------------------------------------+
    | status · task                     | preset                       |
    | [Start F1] [Pause F2] [Stop F3]   | take over · stream · mode    |
    +------------------------------------------------------------------+

THE OWNER, 2026-10-16/17: "you launch hivemind, it shows tabs Macro, Ai
progress, Boosting, Stats and settings, they are all simple tabs and look
really nice and then in settings you can enable advanced mode with all the
rest of the options." He held up a popular macro's window as the bar ("it
looks clean and works") and turned down an
emoji-heavy draft as "too AI". The approved direction is
docs/pending/ui18_mockup.html.

IT IS THE CLASSIC WINDOW, REARRANGED -- not a second window. `ShellWindow`
subclasses `MainWindow`, so the event routing, Start / Pause / Stop, the stop
worker, the settings saving and every panel are the same objects; the shell
only moves them into its own frame. The classic central widget is kept
(hidden) rather than deleted, so a panel the shell does not show still gets
every event, exactly as on a hidden classic tab. Chosen by `gui.layout`
(gui/app), 'classic' until the owner approves this one.
"""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import (QAbstractAnimation, QByteArray, QEvent, QObject, QPoint,
                            QSize, Qt, Signal)
from PySide6.QtGui import (QColor, QFontMetrics, QIcon, QKeySequence, QPainter,
                           QPixmap, QShortcut)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea,
                               QApplication, QButtonGroup, QComboBox,
                               QDoubleSpinBox, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox,
                               QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget)

from . import gameicons, theme
from .panels import settings as settings_panel
from .panels.discord import DiscordPage
from .panels.credits import CreditsPage
from .panels.settings import SettingsPanel
from .simple import crossfade
from .widgets import Card, ElidedLabel, Glide, Meter, PulseDot, Ring
from .window import MainWindow
from ..telemetry.events import Considered, Thought
from ..telemetry.events import Timer as TimerEvent
from ..world import userpatterns
from ..world.settings import (BOUNDS, FEATURE_GROUPS, FEATURES, LOCKED,
                              MACRO_ENTRY, MACRO_NUMBERS, MACRO_PATTERNS, SECRET,
                              SECTIONS, macro_fields, macro_pattern_label, wired)

LOGO = Path(__file__).resolve().parents[3] / "data" / "brand" / "hivemind_logo.png"

# ---- icons -----------------------------------------------------------------
# THIN LINE ICONS, NOT EMOJI (the owner rejected an emoji draft as "too AI").
# The mockup's own 24x24 strokes, drawn by QtSvg in the colour asked for.
ICONS = {
    "macro": '<path d="M12 2l8 4.5v9L12 20l-8-4.5v-9z"/>',
    "ai": '<path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/>',
    "boost": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    "stats": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "settings": ('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3'
                 'M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1'
                 'l2.1-2.1M17 7l2.1-2.1"/>'),
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
}


def icon_pixmap(name: str, colour: str, size: int = 16, ratio: float = 2.0) -> QPixmap:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{colour}" stroke-width="2" stroke-linecap="round" '
           f'stroke-linejoin="round">{ICONS[name]}</svg>')
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def tab_icon(name: str) -> QIcon:
    """Dim when the tab is not shown, amber when it is (QIcon's On state)."""
    icon = QIcon()
    icon.addPixmap(icon_pixmap(name, theme.S_DIM), QIcon.Normal, QIcon.Off)
    icon.addPixmap(icon_pixmap(name, theme.S_AMBER), QIcon.Normal, QIcon.On)
    return icon


# ---- the controls on a card ---------------------------------------------------
class Toggle(QAbstractButton):
    """An on/off switch: a track and a knob, amber when on. A QCheckBox's
    square reads as a form; every card in the mockup is a switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(38, 22)
        self.setFocusPolicy(Qt.StrongFocus)
        # THE KNOB SLIDES (widgets.Glide, ~160 ms); a value set from the file
        # (signals blocked) just jumps, as it should
        self._glide = Glide(self, lambda _: self.update(), 160, start=0.0)
        self.toggled.connect(lambda on: (setattr(self._glide, "now", 0.0 if on else 1.0),
                                         self._glide.to(1.0 if on else 0.0)))

    def sizeHint(self) -> QSize:
        return QSize(38, 22)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        track = QColor(theme.S_AMBER if on else theme.S_LINE)
        knob = QColor(theme.S_ON_AMBER if on else "#cfd2da")
        if not self.isEnabled():
            track.setAlpha(90)
            knob.setAlpha(120)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(self.rect(), 11, 11)
        p.setBrush(knob)
        sliding = self._glide.state() == QAbstractAnimation.Running
        at = self._glide.now if sliding else (1.0 if on else 0.0)
        p.drawEllipse(round(3 + 16 * at), 3, 16, 16)
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor(theme.S_AMBER))
            p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 11, 11)


class _WheelToPage(QObject):
    """A wheel over an UNFOCUSED number box or dropdown scrolls the page.

    The same guard as panels/settings (DESIGN 8du): Qt lets a hovered spin
    box take the wheel, and the owner's file once held a spending limit of
    4999997 from scrolling past one. A click or Tab first, then the wheel."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            parent = obj.parentWidget()
            while parent is not None and not isinstance(parent, QAbstractScrollArea):
                parent = parent.parentWidget()
            if parent is not None:
                QApplication.sendEvent(parent.viewport(), event)
            return True
        return False


SCHEMA = {entry[0]: entry for _, entries in SECTIONS for entry in entries}

# THE GAME'S OWN ICON beside a card whose setting is about one item
# (gui/gameicons; a grey placeholder if the file was not fetched).
CARD_ICONS = {
    "gather.use_sprinklers": "Sprinkler Builder", "gather.sprinklers": "Sprinkler Builder",
    "gather.micro_convert": "Micro-Converter", "economy.dispensers": "Treat",
    "economy.shop_look": "Ticket", "economy.sticker_tickets": "Ticket",
    "economy.use_items": "Glue", "boost.glitter": "Glitter", "boost.dice": "Field Dice",
    "boost.item_buffs": "Blue Extract", "boost.boosters": "fields:Blue Flower",
    "economy.boosters": "fields:Blue Flower", "gather.follow_boost": "fields:Pine Tree",
    "hive.follow_plan": "Royal Jelly", "economy.auto_jelly_off": "Royal Jelly",
    "combat.bug_runs": "Stinger", "combat.bosses": "Coconut",
    "combat.ant_challenge": "Ant Pass",
    # U12's Features page
    "move.home_by_whirligig": "Whirligig", "economy.wealth_clock": "Ticket",
    "economy.buy": "Ticket", "economy.blender": "Oil", "combat.vicious": "Stinger",
    "hive.grind_basic": "Royal Jelly", "combat.stump_snail": "fields:Stump",
    "combat.mondo_loot": "fields:Mountain Top", "challenges.stick_bug": "fields:Mushroom",
    "gather.auto_field": "fields:Sunflower", "economy.planters": "Sunflower Seed",
}


def game_icon(kind: str, name: str, size: int = 24) -> QLabel:
    label = QLabel()
    label.setFixedSize(size, size)
    label.setPixmap(gameicons.pixmap(kind, name, size))
    label.setToolTip(name)
    return label


class SettingCard(QFrame):
    """One setting: its label, a (?) with the schema's own help text, and the
    right control. Saving is the caller's (`save(key, value)`), so the card
    cannot write the file a different way from the settings panel."""

    def __init__(self, key: str, label: str, value, save, wheel_guard, parent=None,
                 blurb: str = "", badge: str = ""):
        super().__init__(parent)
        self.setObjectName("SettingCard")
        # as tall as its words, never stretched to fill the page
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumHeight(50)          # one height, whatever the control
        self.key = key
        _, schema_label, kind, default, help_text, *rest = SCHEMA[key]
        choices = rest[0] if rest else []
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 9, 12, 9)
        row.setSpacing(8)
        if key in CARD_ICONS:
            folder, _, item = CARD_ICONS[key].rpartition(":")
            row.addWidget(game_icon(folder or "items", item), 0, Qt.AlignVCenter)
            row.addSpacing(2)
        name = QLabel(label or schema_label)
        name.setWordWrap(True)
        if blurb or badge:                  # U12's Features page: a line under it
            words = QVBoxLayout()
            words.setSpacing(2)
            top = QHBoxLayout()
            top.setSpacing(6)
            top.addWidget(name)
            if badge:
                tag = QLabel(BADGE_WORDS.get(badge, badge))
                tag.setObjectName("Badge")
                tag.setProperty("kind", badge)
                top.addWidget(tag, 0, Qt.AlignVCenter)
            top.addStretch(1)
            words.addLayout(top)
            sub = QLabel(blurb)
            sub.setObjectName("Dim")
            sub.setWordWrap(True)
            words.addWidget(sub)
            row.addLayout(words, 1)
        else:
            row.addWidget(name, 1)
        if help_text:
            ask = QLabel("?")
            ask.setObjectName("Help")
            ask.setFixedSize(16, 16)
            ask.setAlignment(Qt.AlignCenter)
            ask.setToolTip(f"<b>{html.escape(schema_label)}</b><br>"
                           f"{html.escape(help_text)}")
            ask.setCursor(Qt.WhatsThisCursor)
            row.addWidget(ask, 0, Qt.AlignVCenter)
        row.addSpacing(6)

        if kind == "bool":
            control = Toggle()
            control.toggled.connect(lambda v: save(key, bool(v)))
        elif kind in ("int", "float"):
            control = QSpinBox() if kind == "int" else QDoubleSpinBox()
            low, high, step = BOUNDS.get(key, (0, 1_000_000_000, None))
            control.setRange(type(control.value())(low), type(control.value())(high))
            if step:
                control.setSingleStep(type(control.value())(step))
            # WIDE ENOUGH FOR ITS NUMBER: 96 px cut 50000000 and "0.00" (render
            # probe, UI panel round 2, 2026-10-22: 129-148 px wanted)
            control.setMinimumWidth(130)
            if key == "safety.max_session_h":
                control.setDecimals(1)            # hours: "2.5", not "0.00"
            control.setAlignment(Qt.AlignRight)
            # NO ARROW BUTTONS: a plain number box, typed into, as on the
            # mockup. Hidden by theme's #Num rule -- setButtonSymbols(NoButtons)
            # under this stylesheet blanks the number itself (seen offscreen).
            control.setObjectName("Num")
            # ONE SAVE A NUMBER, not one a keystroke (UI review 2026-10-21:
            # typing 95 saved 9, then 95, and told the bot twice)
            control.setKeyboardTracking(False)
            control.valueChanged.connect(lambda v: save(key, v))
        elif kind == "choice":
            control = QComboBox()
            control.addItems([str(c) for c in choices])
            control.setMinimumWidth(130)
            control.currentTextChanged.connect(lambda v: save(key, v))
        else:
            control = QLineEdit()
            control.setFixedWidth(150)
            if key in SECRET:
                control.setEchoMode(QLineEdit.Password)   # dots: he streams
                # SHOWN ONLY WHILE HELD ON, never by default (UI panel item 12)
                self.reveal = QPushButton("Show")
                self.reveal.setCheckable(True)
                self.reveal.setCursor(Qt.PointingHandCursor)
                self.reveal.setToolTip("Show the text for a moment. It is hidden "
                                       "again when you press Hide or leave the page.")
                self.reveal.toggled.connect(lambda on: (
                    control.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                    self.reveal.setText("Hide" if on else "Show")))
                row.addWidget(self.reveal, 0, Qt.AlignVCenter)
            # one save per edit, not per keystroke: the bot is told each time
            control.editingFinished.connect(lambda: save(key, control.text()))
        if isinstance(control, (QSpinBox, QDoubleSpinBox, QComboBox)):
            control.setFocusPolicy(Qt.StrongFocus)
            control.installEventFilter(wheel_guard)
        if key in LOCKED:
            control.setEnabled(False)
        self.control = control
        self.show_value(value if value is not None else default)
        row.addWidget(control, 0, Qt.AlignVCenter)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if getattr(self, "reveal", None) is not None:
            self.reveal.setChecked(False)          # a page left behind hides it again

    def show_value(self, value) -> None:
        """Show a value saved elsewhere, without saving it again."""
        c = self.control
        c.blockSignals(True)
        try:
            if isinstance(c, Toggle):
                c.setChecked(bool(value))
            elif isinstance(c, (QSpinBox, QDoubleSpinBox)):
                c.setValue(type(c.value())(value))
            elif isinstance(c, QComboBox):
                c.setCurrentText(str(value))
            else:
                c.setText(str(value))
        except (TypeError, ValueError):
            pass                     # the settings panel reports a bad value
        finally:
            c.blockSignals(False)
        c.update()


class CardPage(QScrollArea):
    """A page of setting cards, two to a row, under pill sub-tabs when the
    page has more than one group. `top` widgets go above the pills."""

    def __init__(self, groups, make_card, top=(), parent=None, bottom=(),
                 headings: bool = False):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        box = QVBoxLayout(inner)
        box.setContentsMargins(20, 18, 20, 18)
        box.setSpacing(12)
        for widget in top:
            box.addWidget(widget)
        self.pills: list[QPushButton] = []
        # headings: no stack -- every group on the page, under its title
        stack = None if headings else QStackedWidget()
        if stack is not None:
            stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        if len(groups) > 1 and not headings:
            line = QHBoxLayout()
            line.setSpacing(6)
            pick = QButtonGroup(self)
            for i, (name, _) in enumerate(groups):
                pill = QPushButton(name)
                pill.setObjectName("Pill")
                pill.setCheckable(True)
                pill.setCursor(Qt.PointingHandCursor)
                pill.setChecked(i == 0)
                # room for the bold a checked pill is drawn in, plus ~6 px a
                # side (UI panel round 2, 2026-10-22: "Gifted Basic grinder"
                # touched its edge)
                bold = pill.font()
                bold.setBold(True)
                pill.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(name) + 42)
                pill.clicked.connect(lambda _=False, i=i: stack.setCurrentIndex(i))
                pick.addButton(pill)
                line.addWidget(pill)
                self.pills.append(pill)
            line.addStretch(1)
            box.addLayout(line)
        # where each card sits: {key: (pill index, card)}, for the search
        self.where: dict[str, tuple[int, QWidget]] = {}
        for g, (name, cards) in enumerate(groups):
            page = QWidget()
            grid = QGridLayout(page)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            made = [make_card(key, label) for key, label in cards]
            made = [card for card in made if card is not None]
            for i, card in enumerate(made):
                grid.addWidget(card, i // 2, i % 2)
                self.where.setdefault(card.key, (g, card))
            if headings:                    # every group on one page, titled
                title = QLabel(name.upper())
                title.setObjectName("Section")
                box.addWidget(title)
                box.addWidget(page)
                continue
            # the stack is as tall as its tallest group: a short group's
            # cards sit at the top, not spread down the page
            grid.setRowStretch((len(made) + 1) // 2, 1)
            stack.addWidget(page)
        self.stack = stack
        self._groups = [[c for g, c in self.where.values() if g == i] for i in range(len(groups))]
        if stack is not None:
            box.addWidget(stack)
        for widget in bottom:
            box.addWidget(widget)
        box.addStretch(1)
        self.setWidget(inner)


    def sync_pills(self) -> None:
        """A pill only over cards that show: macro mode hides the AI's own
        cards, and the Pollen pill then opened an empty group (UI panel item
        12). The pill row goes when one group is left."""
        live = [any(not c.isHidden() for c in cards) for cards in self._groups]
        for pill, on in zip(self.pills, live):
            pill.setVisible(on and sum(live) > 1)
        current = self.stack.currentIndex() if self.stack is not None else 0
        if self.pills and not live[current] and any(live):
            self.pills[live.index(True)].click()


def note(title: str, text: str) -> QFrame:
    """An amber-edged card of plain words: what the AI is thinking, or what
    an empty page will hold."""
    frame = QFrame()
    frame.setObjectName("Note")
    box = QVBoxLayout(frame)
    box.setContentsMargins(16, 12, 16, 12)
    box.setSpacing(4)
    head = QLabel(title.upper())
    head.setObjectName("Section")
    body = QLabel(text)
    body.setWordWrap(True)
    body.setTextInteractionFlags(Qt.TextSelectableByMouse)
    box.addWidget(head)
    box.addWidget(body)
    frame.body = body
    return frame


# ---- field picker, item picker -------------------------------------------------
class FieldPicker(QFrame):
    """Every field of `gather.field`, grouped by bee zone, each a tile with
    the game's icon. A popup: a click picks and closes it."""

    picked = Signal(str)

    def __init__(self, current: str = "", parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("Popup")
        self.setAttribute(Qt.WA_StyledBackground, True)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 14)
        box.setSpacing(6)
        self.tiles: dict[str, QToolButton] = {}
        for zone, fields in gameicons.field_zones():
            head = QLabel(f"{zone} Zone".upper())
            head.setObjectName("Section")
            box.addWidget(head)
            grid = QGridLayout()
            grid.setSpacing(6)
            for i, name in enumerate(fields):
                tile = QToolButton()
                tile.setObjectName("FieldTile")
                tile.setText(name)
                tile.setIcon(gameicons.icon("fields", name, 40))
                tile.setIconSize(QSize(40, 40))
                tile.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                tile.setCheckable(True)
                tile.setChecked(name == current)
                tile.setFixedSize(96, 78)
                tile.setCursor(Qt.PointingHandCursor)
                tile.clicked.connect(lambda _=False, n=name: self._pick(n))
                grid.addWidget(tile, i // 5, i % 5)
                self.tiles[name] = tile
            grid.setColumnStretch(5, 1)
            box.addLayout(grid)

    def _pick(self, name: str) -> None:
        self.picked.emit(name)
        self.close()


class FieldCard(QFrame):
    """`gather.field` as a card: the field's icon and name, and Change, which
    opens the zone picker. Greyed with "AI picks" while `gather.auto_field`
    is on -- the same two settings the dropdown wrote, nothing new."""

    def __init__(self, values: dict, save, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingCard")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumHeight(50)
        self.key = "gather.field"
        self._values, self._save = values, save
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 7, 12, 7)
        row.setSpacing(10)
        self._icon = QLabel()
        self._icon.setFixedSize(32, 32)
        row.addWidget(self._icon)
        words = QVBoxLayout()
        words.setSpacing(0)
        title = QLabel("Field")
        title.setObjectName("Dim")
        self._name = QLabel()
        self._name.setStyleSheet("font-weight: 700;")
        words.addWidget(title)
        words.addWidget(self._name)
        row.addLayout(words, 1)
        self.change = QPushButton("Change")
        self.change.setCursor(Qt.PointingHandCursor)
        self.change.clicked.connect(self.open_picker)
        row.addWidget(self.change, 0, Qt.AlignVCenter)
        self.control = self.change               # what the search focuses
        self.picker: FieldPicker | None = None
        self.refresh()

    def refresh(self) -> None:
        auto = bool(self._values.get("gather.auto_field", True))
        field = str(self._values.get("gather.field") or "auto")
        chosen = field if field != "auto" else ""
        self._name.setText("AI picks" if auto or not chosen else chosen)
        self._icon.setPixmap(gameicons.pixmap("fields", chosen, 32) if chosen and not auto
                             else icon_pixmap("ai", theme.S_DIM if auto else theme.S_AMBER, 32))
        self._icon.setEnabled(not auto)
        self._name.setEnabled(not auto)
        self.change.setEnabled(not auto)
        self.change.setToolTip("Switch off “Pick the field for me” to choose "
                               "one yourself." if auto else "Choose the field")

    def open_picker(self) -> None:
        self.picker = FieldPicker(str(self._values.get("gather.field") or ""), self)
        self.picker.picked.connect(lambda name: self._save("gather.field", name))
        self.picker.adjustSize()
        spot = self.mapToGlobal(QPoint(0, self.height() + 4))
        self.picker.move(spot)
        self.picker.show()


# ---- macro mode: the field list and its editor (ROADMAP U16) ------------------
# A FIELD LIST LIKE OTHER MACROS', OUR WAY: a card per field -- icon, name, gather time, pattern -- with a ⋮ menu
# (Copy / Paste / Delete / Default / Move up / Move down), "+" opening the zone
# picker, and an editor under the list for the chosen card. The whole list is
# ONE setting, `macro.fields`, saved through the window's one save path.
def macro_summary(entry: dict) -> str:
    minutes = entry["minutes"]
    stay = f"{minutes}:00" if minutes else "until full"
    sprinklers = entry["sprinklers"]
    return (f"{stay} · {macro_pattern_label(entry['pattern'])} · home at "
            f"{entry['convert_at']}% · {entry['return']} · "
            + ("no sprinkler" if not sprinklers else
               f"{sprinklers} sprinkler{'' if sprinklers == 1 else 's'}"))


def _entries(value) -> list[dict]:
    """The file's list as rows: a copy each, a missing key filled from
    MACRO_ENTRY as the bot fills it (an entry needs only its field; a
    hand-written one crashed the row), anything not a mapping left out."""
    if not isinstance(value, list):
        return []
    return [{"field": "", **MACRO_ENTRY, **e} for e in value if isinstance(e, dict)]


class MacroFieldRow(QFrame):
    """One field of the list: a click chooses it for the editor."""

    def __init__(self, index: int, entry: dict, owner: "MacroFieldList", parent=None):
        super().__init__(parent)
        self.setObjectName("FieldRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.index, self._owner = index, owner
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(10)
        number = QLabel(str(index + 1))
        number.setObjectName("Dim")
        number.setFixedWidth(14)
        row.addWidget(number)
        row.addWidget(game_icon("fields", entry["field"], 32))
        words = QVBoxLayout()
        words.setSpacing(0)
        # SHORTENED, NEVER WIDER THAN THE PAGE: a dropped entry is shown now,
        # and its field or pattern can be any length (render probe 2026-10-22)
        name = ElidedLabel(entry["field"])
        name.setStyleSheet("font-weight: 700;")
        self.summary = ElidedLabel(macro_summary(entry))
        self.summary.setObjectName("Dim")
        words.addWidget(name)
        words.addWidget(self.summary)
        row.addLayout(words, 1)
        self.menu_button = QToolButton()
        self.menu_button.setObjectName("Kebab")
        self.menu_button.setText("⋮")
        self.menu_button.setToolTip("Copy, paste, delete, reset or move this field")
        self.menu_button.setPopupMode(QToolButton.InstantPopup)
        self.menu_button.setCursor(Qt.PointingHandCursor)
        menu = QMenu(self.menu_button)
        last = len(owner.fields) - 1
        for text, act, enabled in (
                ("Copy", owner.copy, True),
                ("Paste", owner.paste, owner.clipboard is not None),
                ("Delete", owner.delete, True),
                ("Default", owner.reset, True),
                ("Move up", lambda i: owner.move(i, -1), index > 0),
                ("Move down", lambda i: owner.move(i, 1), index < last)):
            action = menu.addAction(text)
            action.setEnabled(enabled)
            action.triggered.connect(lambda _=False, act=act: act(self.index))
        self.menu = menu
        self.menu_button.setMenu(menu)
        row.addWidget(self.menu_button, 0, Qt.AlignVCenter)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:
        self._owner.select(self.index)
        super().mousePressEvent(event)


class MacroFieldList(QFrame):
    """`macro.fields` as cards, "+" and the editor. `save(key, value)` is the
    window's own; the list is saved whole on every change, a copy each time,
    so no widget ever holds the dict the settings panel keeps."""

    def __init__(self, values: dict, save, wheel_guard, parent=None, patterns=None):
        super().__init__(parent)
        self._save = save
        self._patterns = patterns          # T17: the user patterns' folder
        self.fields: list[dict] = _entries(values.get("macro.fields"))
        self.clipboard: dict | None = None
        self.selected: int | None = 0 if self.fields else None
        self.rows: list[MacroFieldRow] = []
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("YOUR FIELDS, IN ORDER")
        title.setObjectName("Section")
        head.addWidget(title)
        head.addStretch(1)
        self.add_button = QPushButton("+  Add a field")
        self.add_button.setObjectName("Primary")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(self.open_picker)
        head.addWidget(self.add_button)
        box.addLayout(head)
        self.empty = QLabel(EMPTY_LIST)
        self.empty.setObjectName("Dim")
        self.empty.setWordWrap(True)
        box.addWidget(self.empty)
        # WHAT THE BOT WILL SKIP, said here: world/settings.macro_fields drops
        # an entry with an unknown field or pattern, and the list used to
        # show it as if it would run (UI render pass 2026-10-21)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(f"color: {theme.S_BAD};")
        self.warning.hide()
        box.addWidget(self.warning)
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(6)
        box.addLayout(self._rows_box)
        self.editor = self._build_editor(wheel_guard)
        box.addWidget(self.editor)
        self.picker: FieldPicker | None = None
        self._rebuild()

    # ---- the editor --------------------------------------------------------
    def _build_editor(self, wheel_guard) -> QFrame:
        frame = QFrame()
        frame.setObjectName("SettingCard")
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        grid = QGridLayout(frame)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self._edit_icon = QLabel()
        self._edit_icon.setFixedSize(32, 32)
        self._edit_name = ElidedLabel()
        self._edit_name.setStyleSheet("font-weight: 700; font-size: 14px;")
        self.change = QPushButton("Change field")
        self.change.setCursor(Qt.PointingHandCursor)
        self.change.clicked.connect(lambda: self.open_picker(replace=True))
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self._edit_icon)
        top.addWidget(self._edit_name, 1)
        top.addWidget(self.change)
        grid.addLayout(top, 0, 0, 1, 6)

        self.minutes = QSpinBox()
        self.minutes.setRange(*MACRO_NUMBERS["minutes"])
        self.minutes.setSpecialValueText("until full")
        self.minutes.setSuffix(" min")
        self.pattern = QComboBox()
        self.refresh_patterns()
        self.convert_at = QSpinBox()
        self.convert_at.setRange(*MACRO_NUMBERS["convert_at"])
        self.convert_at.setSuffix(" %")
        self.back = QComboBox()
        # a file's long or unknown pattern name is shortened, never widens the
        # page (render probe 2026-10-22, now that a dropped entry is shown)
        for box in (self.pattern, self.back):
            box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(18)
        self.back.addItem("Walk", "walk")
        self.back.addItem("Respawn (only with an empty bag)", "respawn")
        self.sprinklers = QSpinBox()
        self.sprinklers.setRange(*MACRO_NUMBERS["sprinklers"])
        self.sprinklers.setSpecialValueText("none")
        tips = {
            "minutes": "How long to gather here before going home. 'until full' "
                       "(0) gathers until the backpack reaches the % beside it.",
            "pattern": "The walk inside the field. 'The field's own' is the classic "
                       "pattern sized for this field, what the AI walks; the "
                       "others are the same shape in every field. 'Yours' are "
                       "the ones saved in Macro > Patterns.",
            "convert_at": "The backpack % that ends the gather and sends it home "
                          "to convert, whatever the time says.",
            "return": "A respawn is a death, and a death empties the backpack, "
                      "so it respawns only when the bag reads empty (after a "
                      "Micro-Converter) and walks otherwise.",
            "sprinklers": "How many sprinklers to place when the gather starts "
                          "(0 = none). More than one are stacked on the spot.",
        }
        for n, (label, key, control) in enumerate((
                ("Gather time", "minutes", self.minutes),
                ("Pattern", "pattern", self.pattern),
                ("Max backpack %", "convert_at", self.convert_at),
                ("Return", "return", self.back),
                ("Sprinklers", "sprinklers", self.sprinklers))):
            name = QLabel(label)
            name.setToolTip(tips[key])
            control.setToolTip(tips[key])
            control.setFocusPolicy(Qt.StrongFocus)
            control.installEventFilter(wheel_guard)
            if isinstance(control, QSpinBox):
                # typed into, no arrows: the cards' number boxes (theme #Num)
                control.setObjectName("Num")
                control.setAlignment(Qt.AlignRight)
                control.setFixedWidth(120)
            else:                           # its longest choice shows whole
                control.setMinimumWidth(250)
                control.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            r, c = 1 + n // 2, (n % 2) * 3
            grid.addWidget(name, r, c)
            grid.addWidget(control, r, c + 1)
            if isinstance(control, QComboBox):
                control.currentIndexChanged.connect(
                    lambda _=0, k=key, w=control: self._edit(k, w.currentData()))
            else:
                control.valueChanged.connect(lambda v, k=key: self._edit(k, int(v)))
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(5, 1)
        return frame

    def refresh_patterns(self) -> None:
        """The shapes, then every saved Pattern Studio pattern (T17), read
        fresh: called again whenever one is saved or deleted."""
        box = self.pattern
        box.blockSignals(True)
        box.clear()
        for key, label in MACRO_PATTERNS.items():
            box.addItem(label, key)
        for p in userpatterns.load_user(self._patterns).values():
            route = userpatterns.route_name(p)
            box.addItem(f"Yours: {p['name']}", route)
        box.blockSignals(False)
        if hasattr(self, "editor") and self.selected is not None and self.fields:
            self._show_editor()

    def _show_editor(self) -> None:
        on = self.selected is not None
        self.editor.setVisible(on)
        if not on:
            return
        entry = self.fields[self.selected]
        self._edit_icon.setPixmap(gameicons.pixmap("fields", entry["field"], 32))
        self._edit_name.setText(f"{self.selected + 1}. {entry['field']}")
        for control, value in ((self.minutes, entry["minutes"]),
                               (self.convert_at, entry["convert_at"]),
                               (self.sprinklers, entry["sprinklers"])):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)
        if self.pattern.findData(entry["pattern"]) < 0:      # deleted since
            self.pattern.addItem(macro_pattern_label(entry["pattern"]) + " (not saved)",
                                 entry["pattern"])
        for control, value in ((self.pattern, entry["pattern"]), (self.back, entry["return"])):
            control.blockSignals(True)
            control.setCurrentIndex(control.findData(value))
            control.blockSignals(False)

    def _edit(self, key: str, value) -> None:
        if self.selected is None:
            return
        self.fields[self.selected][key] = value
        self.rows[self.selected].summary.setText(macro_summary(self.fields[self.selected]))
        self._commit()

    # ---- the list ----------------------------------------------------------
    def _commit(self) -> None:
        self._save("macro.fields", [dict(e) for e in self.fields])

    def _rebuild(self) -> None:
        for row in self.rows:
            self._rows_box.removeWidget(row)
            row.deleteLater()
        self.rows = [MacroFieldRow(i, e, self) for i, e in enumerate(self.fields)]
        for row in self.rows:
            self._rows_box.addWidget(row)
            row.set_selected(row.index == self.selected)
        self.empty.setVisible(not self.fields)
        self._show_problems()
        self._show_editor()

    def _show_problems(self) -> None:
        _, problems = macro_fields(self.fields)
        shown = [p.removeprefix("macro.fields ").removesuffix("; left out") for p in problems[:3]]
        more = f" and {len(problems) - 3} more" if len(problems) > 3 else ""
        self.warning.setText(
            f"⚠  The bot skips {len(problems)} of these: " + "; ".join(shown) + more
            + ". Change or delete them with ⋮." if problems else "")
        self.warning.setVisible(bool(problems))

    def show_fields(self, value) -> None:
        """A list saved elsewhere (a preset, the file): shown, not saved."""
        fields = _entries(value)
        if fields == self.fields:
            return                          # our own save, coming back
        self.fields = fields
        if self.selected is not None and self.selected >= len(fields):
            self.selected = len(fields) - 1 if fields else None
        self._rebuild()

    def select(self, index: int) -> None:
        self.selected = index
        for row in self.rows:
            row.set_selected(row.index == index)
        self._show_editor()

    def open_picker(self, replace: bool = False) -> None:
        current = self.fields[self.selected]["field"] if replace and self.selected is not None else ""
        self.picker = FieldPicker(current, self)
        self.picker.picked.connect(lambda name: self.set_field(name) if replace else self.add(name))
        self.picker.adjustSize()
        anchor = self.change if replace else self.add_button
        self.picker.move(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))
        self.picker.show()

    def add(self, name: str) -> None:
        self.fields.append({"field": name, **MACRO_ENTRY})
        self.selected = len(self.fields) - 1
        self._rebuild()
        self._commit()

    def set_field(self, name: str) -> None:
        if self.selected is not None:
            self.fields[self.selected]["field"] = name
            self._rebuild()
            self._commit()

    def copy(self, index: int) -> None:
        self.clipboard = {k: v for k, v in self.fields[index].items() if k != "field"}
        self._rebuild()                      # Paste comes alive on every card

    def paste(self, index: int) -> None:
        """The copied card's settings onto this one; its field stays."""
        if self.clipboard is not None:
            self.fields[index].update(self.clipboard)
            self.selected = index
            self._rebuild()
            self._commit()

    def delete(self, index: int) -> None:
        del self.fields[index]
        if self.selected is not None:
            self.selected = (None if not self.fields else
                             min(self.selected - (self.selected > index), len(self.fields) - 1))
        self._rebuild()
        self._commit()

    def reset(self, index: int) -> None:
        """Default: this card's settings back to a new card's; its field stays."""
        self.fields[index].update(MACRO_ENTRY)
        self.selected = index
        self._rebuild()
        self._commit()

    def move(self, index: int, step: int) -> None:
        other = index + step
        if 0 <= other < len(self.fields):
            self.fields[index], self.fields[other] = self.fields[other], self.fields[index]
            self.selected = other
            self._rebuild()
            self._commit()


class MacroModeCard(QFrame):
    """`mode.macro` as two choices side by side: the user's list, or the AI."""

    def __init__(self, on: bool, save, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingCard")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)
        line = QHBoxLayout()
        line.setSpacing(8)
        group = QButtonGroup(self)
        # ONE QUESTION, TWO ANSWERS (UI panel item 12: four controls for one
        # choice). The same `mode.macro`; "I choose" is the field list.
        ask = QLabel("WHO CHOOSES WHERE TO GATHER?")
        ask.setObjectName("Section")
        box.addWidget(ask)
        self.ai = QPushButton("Hivemind chooses")
        self.macro = QPushButton("I choose the fields")
        for button, value in ((self.ai, False), (self.macro, True)):
            button.setObjectName("Pill")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            # room for the bold the checked pill is drawn in (it clipped)
            bold = button.font()
            bold.setBold(True)
            button.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(button.text()) + 48)
            button.clicked.connect(lambda _=False, v=value: save("mode.macro", v))
            group.addButton(button)
            line.addWidget(button)
        line.addStretch(1)
        box.addLayout(line)
        self.said = QLabel()
        self.said.setObjectName("Dim")
        self.said.setWordWrap(True)
        box.addWidget(self.said)
        self.show_value(on)

    def show_value(self, on: bool) -> None:
        (self.macro if on else self.ai).setChecked(True)
        self.said.setText(
            "Each trip goes to the next field in your list, with its own time, "
            "pattern and backpack %. Errands you left on still run, and a field "
            "a boss guards is skipped."
            if on else
            "Hivemind picks the best field for every trip. Your list below is "
            "kept for when you choose yourself.")


class ItemPicker(QWidget):
    """A searchable list of the game's items, icon and name per row."""

    picked = Signal(str)

    def __init__(self, items=gameicons.ITEMS, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search items…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter)
        box.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("ItemList")
        self.list.setIconSize(QSize(26, 26))
        for name in items:
            self.list.addItem(QListWidgetItem(gameicons.icon("items", name, 26), name))
        self.list.itemClicked.connect(lambda item: self.picked.emit(item.text()))
        self.list.itemActivated.connect(lambda item: self.picked.emit(item.text()))
        box.addWidget(self.list, 1)
        self.empty = QLabel("No item matches.")
        self.empty.setObjectName("Dim")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.hide()
        box.addWidget(self.empty)

    def filter(self, text: str) -> None:
        words = text.casefold().split()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(not all(w in item.text().casefold() for w in words))
        self.empty.setVisible(not self.visible_items())

    def visible_items(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())
                if not self.list.item(i).isHidden()]


# ---- settings search ----------------------------------------------------------
class CommandPalette(QFrame):
    """The magnifier's popup: one box that finds any setting (by its label,
    help or key) or any page, and jumps there. `entries` is the window's
    index: (title, where, words to match, target)."""

    chosen = Signal(object)
    LIMIT = 40

    def __init__(self, entries, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("Popup")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.entries = entries
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 10, 10, 10)
        box.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("PaletteSearch")
        self.search.setPlaceholderText("Search settings, tabs…")
        self.search.textChanged.connect(self.filter)
        self.search.returnPressed.connect(self.accept)
        self.search.installEventFilter(self)
        box.addWidget(self.search)
        self.results = QListWidget()
        self.results.setObjectName("Results")
        self.results.itemClicked.connect(lambda _: self.accept())
        box.addWidget(self.results, 1)
        self.resize(560, 420)
        self.filter("")

    def filter(self, text: str) -> None:
        words = text.casefold().split()
        self.results.clear()
        hits = [e for e in self.entries if all(w in e[2] for w in words)]
        # the title's own words first, then everything that only matched the help
        hits.sort(key=lambda e: not all(w in e[0].casefold() for w in words))
        for title, where, _, target in hits[:self.LIMIT]:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, target)
            item.setData(Qt.UserRole + 1, title)
            row = QLabel(f"{html.escape(title)}<br><span style='color:{theme.S_DIM};"
                         f" font-size:11px'>{html.escape(where)}</span>")
            row.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.setContentsMargins(4, 0, 0, 0)
            item.setSizeHint(QSize(0, 44))
            self.results.addItem(item)
            self.results.setItemWidget(item, row)
        if not hits:
            none = QListWidgetItem("Nothing matches. Try another word.")
            none.setFlags(Qt.NoItemFlags)
            self.results.addItem(none)
        self.results.setCurrentRow(0)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.search and event.type() == QEvent.KeyPress \
                and event.key() in (Qt.Key_Down, Qt.Key_Up):
            step = 1 if event.key() == Qt.Key_Down else -1
            row = max(0, min(self.results.count() - 1, self.results.currentRow() + step))
            self.results.setCurrentRow(row)
            return True
        return super().eventFilter(obj, event)

    def accept(self) -> None:
        item = self.results.currentItem()
        target = item.data(Qt.UserRole) if item is not None else None
        if target is not None:
            self.close()
            self.chosen.emit(target)


# ---- what each tab shows -------------------------------------------------------
# A SHORT, CURATED LIST PER TAB (U18: "each tab shows only the few choices that
# matter"). Short labels here; the schema's long label and its help text are
# in the (?) tooltip. Only keys the bot actually reads belong here --
# `make_card` drops any that are not wired, so a switch that does nothing can
# never reach the simple tabs. Every other setting stays reachable through
# Advanced mode.
MACRO_GATHER = [
    ("Field", [("gather.auto_field", "Pick the field for me"),
               ("gather.field", "Field"),
               ("gather.follow_boost", "Follow field boosts"),
               ("move.use_cannon", "Use the red cannon")]),
    ("Pollen", [("gather.convert_at", "Convert at bag %"),
                ("gather.use_sprinklers", "Place sprinklers"),
                ("gather.sprinklers", "Sprinklers owned"),
                ("gather.micro_convert", "Micro-Converter when full"),
                ("gather.stay_in_field", "Stay inside the field"),
                ("gather.leave_at_empty_bag", "Leave the hive when emptied")]),
    ("Tokens", [("gather.chase_tokens", "Chase tokens"),
                ("gather.token_radius", "Chase radius (studs)"),
                ("gather.rotate_camera", "Sweep the camera for bubbles")]),
    # no gather.chase_confidence card: an expert number (feature sweep
    # 2026-10-21), kept on Advanced > Gather and All settings
]
MACRO_COLLECT = [
    ("Collect", [("economy.dispensers", "Dispensers"),
                 ("economy.wealth_clock", "Wealth Clock"),
                 ("economy.memory_match", "Memory Match"),
                 ("economy.blender", "Blender"),
                 ("economy.shop_look", "Check the Ticket Tent"),
                 ("planner.errand_profit", "Do the best errands first")]),
]
MACRO_QUESTS = [
    ("Quests", [("quests.enabled", "Do quests"),
                ("quests.first", "Quest fields first"),
                ("quests.scroll", "Read the whole quest list")]),
    ("Quest givers", [(k, "") for k in (
        "quests.polar", "quests.honey", "quests.bucko", "quests.riley",
        "quests.spirit", "quests.black_bear", "quests.brown_bear",
        "quests.panda", "quests.mother")]),
]
MACRO_BUGS = [
    ("Bug runs", [("combat.bug_runs", "Bug runs"),
                  ("combat.bug_worth_it", "Only when the drops pay"),
                  ("combat.bug_loot", "Collect the drops"),
                  ("combat.retreat_health", "Run away below health %")]),
    ("Mobs", [("combat.bug_ladybug", "Ladybugs"),
              ("combat.bug_rhino_beetle", "Rhino Beetles"),
              ("combat.bug_spider", "Spider"),
              ("combat.bug_mantis", "Mantises"),
              ("combat.bug_scorpion", "Scorpions"),
              ("combat.bug_werewolf", "Werewolf")]),
    ("Bosses", [("combat.bosses", "Bosses: Coconut Crab, King Beetle, Tunnel Bear, Stump Snail"),
                ("combat.commando", "Commando Chick"),
                ("combat.mondo_loot", "Mondo Chick loot (watch only)"),
                ("combat.vicious", "Vicious Bee"),
                ("combat.stump_snail", "Stump Snail")]),
    ("Challenges", [("combat.ant_challenge", "Ant Challenge for quests"),
                    ("challenges.stick_bug", "Stick Bug Challenge (watch only)")]),
]
MACRO_PLANTERS = [
    ("Planters", [("economy.planters", "Manage planters"),
                  ("economy.early_harvest", "Harvest early for field health")]),
]
AI_OVERVIEW = [
    ("Auto-progress", [("economy.buy", "Buy gear and slots"),
                       ("hive.follow_plan", "Royal Jelly follows the plan"),
                       ("hive.new_bees", "Where new bees go"),
                       ("progression.hive", "Hive colour"),
                       ("eggs.save_diamond", "Save Diamond Eggs"),
                       ("eggs.hatch_mythic", "Hatch Mythic Eggs"),
                       ("economy.auto_jelly_off", "Game's Auto-Jelly"),
                       ("hive.read_bees", "Read the hive"),
                       ("goals.read_inventory", "Read the inventory")]),
    # ROADMAP H16: the slot is also chosen by clicking a hex in the Hive Planner
    ("Gifted Basic grinder", [("hive.grind_basic", "Grind a gifted Basic Bee"),
                              ("hive.grind_slot", "Slot to grind in (0 = none)"),
                              ("hive.grind_max_honey", "Most honey a session"),
                              ("hive.grind_max_jellies", "Most Royal Jelly a session")]),
]
# U19: WHICH BOOSTS ARE KEPT UP, then the rest of the boosting switches.
# The boost keeper's own three only matter with it on; the (?) says so.
BOOSTS = [
    ("Keep up", [("boost.keeper", "Keep boosts going"),
                 ("boost.boosters", "Field boosters on cooldown"),
                 ("boost.glitter", "Glitter before a boost ends"),
                 ("boost.dice", "Field Dice before a boost ends"),
                 ("boost.item_buffs", "Item buffs (Glue, extracts, Enzymes)"),
                 ("economy.sticker_tickets", "Sticker Stack with tickets")]),
    ("More", [("economy.boosters", "Walk to field boosters when it pays"),
              ("gather.follow_boost", "Gather where a boost lands"),
              ("economy.use_items", "Use spare items in the field"),
              # no Wind Shrine card: no route to it exists, so the switch
              # decides nothing yet (SETTINGS AUDIT 2026-10-19); it stays in
              # Advanced > All settings, where its help says so
              ("economy.beesmas", "Beesmas machines")]),
]
BOOST_AI = [("Boost AI", [("boost.ai", "Boost helper")])]
GENERAL = [
    ("General", [("gui.layout", "Window layout"),
                 ("guard.enabled", "Pause while I play a game"),
                 ("gui.start_on_boot", "Start farming when the PC starts"),
                 ("safety.max_session_h", "Stop after (hours, 0 = never)"),
                 ("safety.panic_key", "Emergency stop key"),
                 ("safety.jitter", "Human-like timing"),
                 ("move.hive_slot", "Hive slot (0 = unknown)"),
                 ("perf.vlm", "Use the vision model")]),
]

SERVER = [
    ("Server", [("server.join", "Which server Start joins"),
                ("server.link", "Share link to join"),
                ("server.name", "Server name to join"),
                ("server.hop", "Server hopping"),
                ("server.hop_per_night", "Hops a night, at most"),
                ("server.hop_minutes", "Minutes in one public server"),
                ("server.hop_return", "Back to my private server after")]),
]

# PLAIN WORDS AND A SHAPE on the Features badges (UI panel round 2, 2026-10-22:
# kid, grandad, ESL and parent readers did not know "LOOK-ONLY")
BADGE_WORDS = {"live": "✓ live", "look-only": "◌ watch only", "needs measuring": "? not measured"}


# THE GATHER LIST'S EMPTY LINE follows the mode: with Hivemind choosing,
# "Press +" told kid and pro readers the list was needed (UI panel round 2)
EMPTY_LIST = ("Press + to gather at a field. Each trip goes to the "
              "next field in the list, then back to the first.")
EMPTY_LIST_AI = "Hivemind picks the fields. This list is only used with I choose the fields."


def _first_sentence(text: str) -> str:
    head, dot, _rest = text.partition(". ")
    return head + dot.strip() if dot else text


def run_look(status, process_up: bool, exit_code=None, replay=False) -> tuple[str, str, str]:
    """(glyph, word, colour) of the bottom bar's state. A SHAPE AND A WORD,
    not a colour alone (UI panel 2026-10-21: colourblind readers could not
    tell the red dot from the green one, and the dot followed the socket, so
    an idle app looked broken). Red is kept for a bot that exited badly."""
    if replay:      # a demo is not a bot (UI panel round 2, 2026-10-22)
        return "◌", "Demo replay", theme.S_DIM
    if status._handed_over:
        return "❚❚", "You have the controls", theme.S_AMBER
    if status._running and status._paused:
        return "❚❚", "Paused", theme.S_AMBER
    if status._running:
        return "▶", "Running", theme.S_GOOD
    if process_up and not status._connected:
        return "◌", "Starting", theme.S_AMBER
    if exit_code not in (None, 0):
        return "⚠", "Stopped with an error", theme.S_BAD
    return "■", "Idle" if status._connected else "Stopped", theme.S_DIM


# THE HELP PAGE (UI panel 2026-10-21 item 11: "Understand" scored 4.5 of 10,
# the lowest; six of eight readers met words nobody explained). Short
# sentences, for a ten-year-old and for someone reading in a second language.
HOW_TO_START = (
    "Open Roblox and sign in yourself. Hivemind never asks for your password.",
    "Choose where to gather: Macro › Gather. Let Hivemind choose, or add your own fields.",
    "Press Start (F1). The bot joins your server and starts to farm.",
    "Watch it in Macro › Live view. Pause is F2. Stop is F3.",
    "If it has a question, it shows at the top. If you do nothing, it picks the best answer.",
)
# (word, what it means, icon kind, icon name): the game's icon where one fits,
# the letters tile (gameicons' placeholder) where none does
GLOSSARY = (
    ("Pollen", "What your bees collect from the flowers in a field. It fills your "
               "backpack.", "fields", "Sunflower"),
    ("Convert", "Going home to your hive with a full backpack. The bees turn the "
                "pollen into honey there.", "items", "Micro-Converter"),
    ("Honey", "The game's money. It buys gear, eggs and more hive slots.", "items", "Honey"),
    ("Studs", "How Roblox measures distance. Your character is about 5 studs tall.",
     "items", "Studs"),
    ("Gifted", "A special bee with a star on its picture. It is stronger, and it gives "
               "your whole hive a bonus.", "items", "Gifted"),
    ("Royal Jelly", "An in-game item that turns a bee into a random other bee: "
                    "sometimes a rarer one, rarely a gifted one. Hivemind never buys it "
                    "with Robux.", "items", "Royal Jelly"),
    ("Nectar", "Five kinds of boost for your whole hive. You get them by harvesting "
               "planters.", "items", "Sunflower Seed"),
)


class HelpPage(QScrollArea):
    """How to start, and the game's words in plain English."""

    def __init__(self, panic_key: str = "F12", parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        box = QVBoxLayout(inner)
        box.setContentsMargins(20, 18, 20, 18)
        box.setSpacing(12)
        steps = list(HOW_TO_START)
        steps[3] += f" The emergency stop key is {panic_key or 'F12'}: it stops everything."
        start = note("How to start", "<br>".join(
            f"<b>{n}.</b>&nbsp; {html.escape(s)}" for n, s in enumerate(steps, 1)))
        start.body.setTextFormat(Qt.RichText)
        box.addWidget(start)
        head = QLabel("WORDS USED HERE")
        head.setObjectName("Section")
        box.addWidget(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for i, (word, text, kind, icon) in enumerate(GLOSSARY):
            card = QFrame()
            card.setObjectName("SettingCard")
            row = QHBoxLayout(card)
            row.setContentsMargins(14, 10, 14, 10)
            row.setSpacing(12)
            row.addWidget(game_icon(kind, icon, 32), 0, Qt.AlignTop)
            words = QLabel(f"<b>{html.escape(word)}</b><br>{html.escape(text)}")
            words.setWordWrap(True)
            row.addWidget(words, 1)
            grid.addWidget(card, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        box.addLayout(grid)
        box.addStretch(1)
        self.setWidget(inner)
        # what the search finds on this page: every word and its meaning
        self.terms = [(word, text) for word, text, *_ in GLOSSARY]


TABS = (("macro", "MACRO"), ("ai", "AI PROGRESS"), ("boost", "BOOSTING"),
        ("stats", "STATS"), ("settings", "SETTINGS"))


class ShellWindow(MainWindow):
    """The five-tab window, built on the classic one (see the module doc)."""

    def __init__(self, bridge, parent=None, bot=None):
        self._cards: dict[str, list[SettingCard]] = {}
        self._menus: dict[str, QListWidget] = {}
        self._advanced_rows: list[tuple[QListWidget, int]] = []
        self._stacks: dict[str, QStackedWidget] = {}
        self._field_card: FieldCard | None = None
        theme.use_shell_palette()          # the old panels, built next, in greys
        # EVERY BAR AND RING EASES to its new value here (widgets.Glide; they
        # jump when off screen), as Simple's do: a state change you can see
        Meter.ease_ms, Ring.ease_ms = 500, 700
        super().__init__(bridge, parent, bot)
        self.setObjectName("Shell")
        self.setStyleSheet(theme.STYLESHEET + theme.SHELL)
        self.resize(1280, 800)
        self.setMinimumSize(1100, 640)
        self._wheel = _WheelToPage(self)

        # KEPT, NOT DELETED: setCentralWidget would delete the classic page
        # and every panel the shell does not move out of it.
        self._classic = self.takeCentralWidget()
        self._classic.setParent(self)
        self._classic.hide()
        old = self._classic_pages()

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._replay_banner)
        outer.addWidget(self._boot_banner)
        self.tab_buttons = {}
        outer.addWidget(self._top_bar())
        # QUESTIONS WAIT ABOVE EVERY TAB, as above the classic tabs: the bot
        # keeps playing and the question waits, whichever tab is up.
        self._take(self.inbox)
        holder = QWidget()
        hold = QVBoxLayout(holder)
        hold.setContentsMargins(16, 10, 16, 0)
        hold.addWidget(self.inbox)
        holder.setVisible(False)
        self.inbox.installEventFilter(self)
        self._inbox_holder = holder
        outer.addWidget(holder)
        self.tab_stack = QStackedWidget()
        outer.addWidget(self.tab_stack, 1)
        outer.addWidget(self._bottom_bar())
        self.setCentralWidget(root)

        self._build_tabs(old)
        self._show_tab("macro")
        self._advanced = False
        self.show_mode(self.settings.values.get("gui.mode") or "simple", animate=False)
        self.status.controls_changed.connect(self._sync_bar)
        self._sync_bar()
        self._sync_inbox()
        self._show_mode_label()

    # ---- moving the classic panels ------------------------------------------
    def _classic_pages(self) -> dict[str, QWidget]:
        """Every classic tab's page by its label, taken out of the tabs."""
        pages = {}
        advanced = None
        while self.tabs.count():
            label, page = self.tabs.tabText(0), self.tabs.widget(0)
            self.tabs.removeTab(0)
            if label == "Advanced":
                advanced = page
            else:
                pages[label] = page
        while advanced is not None and advanced.count():
            label, page = advanced.tabText(0), advanced.widget(0)
            advanced.removeTab(0)
            pages["adv:" + label] = page
        return pages

    @staticmethod
    def _take(widget: QWidget) -> QWidget:
        """Lift a widget out of the layout it sits in, to be placed anew."""
        parent = widget.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().removeWidget(widget)
        widget.setParent(None)
        return widget

    @staticmethod
    def _padded(*widgets, stretch=(1,)) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(20, 14, 20, 16)
        box.setSpacing(12)
        for i, widget in enumerate(widgets):
            box.addWidget(widget, stretch[i] if i < len(stretch) else 0)
        return page

    # ---- the frame ---------------------------------------------------------
    def _top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(4)
        logo = QLabel()
        pixmap = QPixmap(str(LOGO))
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(26, 26, Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation))
        row.addWidget(logo)
        brand = QLabel("Hivemind")
        brand.setObjectName("Brand")
        row.addWidget(brand)
        row.addSpacing(22)
        group = QButtonGroup(self)
        for key, label in TABS:
            button = QPushButton(label)
            button.setObjectName("TopTab")
            button.setCheckable(True)
            button.setIcon(tab_icon(key))
            button.setIconSize(QSize(16, 16))
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self._show_tab(k))
            group.addButton(button)
            row.addWidget(button)
            self.tab_buttons[key] = button
        row.addStretch(1)
        self.search_button = QPushButton("Search")
        self.search_button.setObjectName("SearchButton")
        self.search_button.setIcon(QIcon(icon_pixmap("search", theme.S_DIM)))
        self.search_button.setIconSize(QSize(15, 15))
        self.search_button.setToolTip("Search settings and pages (Ctrl+K)")
        self.search_button.setCursor(Qt.PointingHandCursor)
        self.search_button.clicked.connect(self.open_search)
        row.addWidget(self.search_button)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_search)
        return bar

    def _bottom_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("BottomBar")
        grid = QGridLayout(bar)
        grid.setContentsMargins(12, 8, 12, 10)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)

        # STATUS: the classic bar's own text, and what the bot is doing now
        status = self._bar_row()
        self._dot = PulseDot(theme.S_DIM, 8)     # breathes while it runs
        keep = self._dot.sizePolicy()
        keep.setRetainSizeWhenHidden(True)       # the words do not jump when it shows
        self._dot.setSizePolicy(keep)
        self._word = QLabel()                    # the state in bold, with its shape
        # ELIDED, NOT CUT MID-WORD where the two met (UI panel item 9)
        self._state = ElidedLabel()
        self._state.setObjectName("Dim")
        self._state.setMinimumWidth(80)
        self._doing = ElidedLabel("idle")
        self._doing.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status.layout().setContentsMargins(4, 4, 8, 4)
        status.layout().addWidget(self._dot)
        status.layout().addWidget(self._word)
        status.layout().addWidget(self._state, 3)
        status.layout().addWidget(self._doing, 2)
        grid.addWidget(status, 0, 0)

        # PRESET: the settings panel's own import/export, as a switcher
        preset = self._bar_row()
        name = QLabel("Preset")
        name.setObjectName("Dim")
        self.preset = QComboBox()
        self.preset.setObjectName("Preset")
        self.preset.setMinimumWidth(170)
        # a long preset name is cut with "…", not allowed to widen the bar
        self.preset.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.preset.setMinimumContentsLength(18)
        self.preset.activated.connect(self._preset_chosen)
        preset.layout().addWidget(name)
        preset.layout().addStretch(1)
        preset.layout().addWidget(self.preset)
        grid.addWidget(preset, 0, 1)
        self._fill_presets()

        # START / PAUSE / STOP: the window's own three slots, F1-F3 as before
        runs = QHBoxLayout()
        runs.setSpacing(8)
        self.run_buttons = []
        for text, key, slot, primary in (("Start", "F1", self._start, True),
                                         ("Pause", "F2", self._pause_or_resume, False),
                                         ("Stop", "F3", self._stop, False)):
            button = QPushButton(text)
            button.setObjectName("Run")
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumHeight(36)
            hint = QLabel(key, button)
            hint.setAttribute(Qt.WA_TransparentForMouseEvents)
            button.hint = hint
            self._set_primary(button, primary)
            inner = QHBoxLayout(button)
            inner.setContentsMargins(12, 0, 12, 0)
            inner.addStretch(1)
            inner.addWidget(hint)
            button.clicked.connect(slot)
            runs.addWidget(button, 1)
            self.run_buttons.append(button)
        self.start_button, self.pause_button, self.stop_button = self.run_buttons
        grid.addLayout(runs, 1, 0)

        # TAKE OVER, STREAM, MODE: the classic bar's own two buttons, moved
        mode = self._bar_row()
        for button in (self.status._handover, self.status._stream):
            self._take(button)
            mode.layout().addWidget(button)
        mode.layout().addStretch(1)
        label = QLabel("Mode")
        label.setObjectName("Dim")
        self._mode_label = QLabel()
        self._mode_label.setStyleSheet(f"color: {theme.S_AMBER}; font-weight: 700;")
        mode.layout().addWidget(label)
        mode.layout().addWidget(self._mode_label)
        grid.addWidget(mode, 1, 1)
        return bar

    @staticmethod
    def _set_primary(button: QPushButton, primary: bool) -> None:
        """The amber fill on the ONE run button to press now: Start when
        stopped, Stop while it runs (UI panel 2026-10-21 item 2)."""
        if button.property("primary") == primary and button.hint.styleSheet():
            return
        button.setProperty("primary", primary)
        button.hint.setStyleSheet("background: transparent; font-size: 11px;"
                                  f" color: {theme.S_ON_AMBER if primary else theme.S_FAINT};")
        button.style().unpolish(button)          # a property change needs a re-polish
        button.style().polish(button)

    @staticmethod
    def _bar_row() -> QFrame:
        row = QFrame()
        row.setObjectName("BarRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(12, 4, 8, 4)
        line.setSpacing(8)
        row.setMinimumHeight(36)
        return row

    # ---- the five tabs -----------------------------------------------------
    def _build_tabs(self, old: dict[str, QWidget]) -> None:
        card = self._make_card
        live = Card("live view", "what it sees")
        self._take(self.live)
        live.add(self.live, 1)
        task = self._take(self.task_label.parentWidget())
        self._take(self.planters)
        # above the cards on a scrolling page, where it would otherwise get
        # one planter row's height
        self.planters.setMinimumHeight(330)

        self._thinking = note("AI is thinking",
                              "Waiting for the bot's next decision. It says "
                              "here what it chose and why before every trip.")
        goals_page = old.pop("Goals")
        # THE MATERIALS CHECKLIST (ROADMAP G11): the gear panel's own plan
        from .panels.materials import MaterialsPage
        self.materials = MaterialsPage()
        self.materials.show_plan(self.gear.plan)
        self._take(self.session_goals)

        timers = QWidget()
        both = QHBoxLayout(timers)
        both.setContentsMargins(0, 0, 0, 0)
        both.setSpacing(12)
        for panel in (self.timers, self.sentinel):
            both.addWidget(self._take(panel), 1)

        vitals = QFrame()
        vitals.setObjectName("Panel")
        column = QVBoxLayout(vitals)
        column.setContentsMargins(8, 10, 8, 10)
        column.setSpacing(2)
        # LIVE, NOT THE RECORDS (UI panel 2026-10-21: live HONEY beside "no
        # trips recorded yet" read as a contradiction)
        caption = QLabel("THIS SESSION (LIVE)")
        caption.setObjectName("Section")
        caption.setContentsMargins(12, 0, 0, 0)
        column.addWidget(caption)
        row = QHBoxLayout()
        column.addLayout(row)
        for vital in (self.status.honey, self.status.pollen, self.status.bees,
                      self.status.rate):
            row.addWidget(self._take(vital), 1)
        # THE GRAPHS (ROADMAP U17): read from the bot's own files when the
        # page is first shown, never at build time
        from .panels.graphs import StatsGraphs
        self.stats_graphs = StatsGraphs(parent=self)
        graphs = self.stats_graphs.graphs_page
        graphs.layout().setContentsMargins(0, 0, 0, 0)

        # MACRO MODE (U16) above the gather cards: who picks, and the list
        self.macro_mode = MacroModeCard(bool(self.settings.values.get("mode.macro")),
                                        self._save_card)
        patterns_dir = settings_panel.CONFIG.parent / "patterns"   # beside settings.yaml
        raw = getattr(self.settings, "raw_lists", {})
        self.macro_list = MacroFieldList({**self.settings.values, **raw}, self._save_card,
                                         self._wheel, patterns=patterns_dir)
        # THE PATTERN STUDIO (ROADMAP T17): make, preview, save and share
        from .panels.patterns import PatternStudio
        self.pattern_studio = PatternStudio(patterns_dir)
        self.pattern_studio.saved.connect(self.macro_list.refresh_patterns)
        self._gather_page = CardPage(MACRO_GATHER, card, top=(self.macro_mode, self.macro_list))
        self._add_tab("macro", [
            ("Gather", self._gather_page),
            ("Patterns", self.pattern_studio),
            ("Collect", CardPage(MACRO_COLLECT, card)),
            ("Quests", CardPage(MACRO_QUESTS, card)),
            ("Bug runs", CardPage(MACRO_BUGS, card)),
            ("Planters", CardPage(MACRO_PLANTERS, card, top=(self.planters,))),
            ("Live view", self._padded(live, task, stretch=(1, 0))),
        ])
        self._add_tab("ai", [
            ("Overview", CardPage(AI_OVERVIEW, card, top=(self._thinking,))),
            ("Goals", self._goals_page(goals_page)),
            ("Materials", self.materials),
            ("Hive Planner", old.pop("Hive Planner")),
            ("Quests", old.pop("adv:Quest steps")),
            ("Thinking", old.pop("adv:Think")),
        ])
        from .panels.boosting import BoostStrip, MeasuredGains
        self.boost_strip = BoostStrip()
        self.boost_gains = MeasuredGains()
        not_yet = QLabel("Nectar is kept up by the planters and 'Keep the nectars up' "
                         "(Settings > Features; vials watch only). Not kept up yet: "
                         "Haste, Focus and bear morphs (the buff bar is read, not timed).")
        not_yet.setObjectName("Dim")
        not_yet.setWordWrap(True)
        # THREE SHORT LINES, not one long sentence (UI panel item 11)
        ai_says = note("Boost AI",
                       "<b>Look</b>: it says what it would do, and changes nothing.<br>"
                       "<b>Act</b>: it uses Glitter, Field Dice and extra booster presses, "
                       "only where a boost is measured to pay. Where to farm stays watch only.<br>"
                       "It spends honey and tickets only, never Robux.")
        ai_says.body.setTextFormat(Qt.RichText)
        self._add_tab("boost", [
            ("Boosts", CardPage(BOOSTS, card, top=(self.boost_strip,), bottom=(not_yet,))),
            ("Boost AI", CardPage(BOOST_AI, card, top=(ai_says,), bottom=(self.boost_gains,))),
            ("Timers", self._padded(timers)),
            ("Hotbar", self._hotbar_page()),
        ])
        self._add_tab("stats", [
            ("Overview", self._padded(vitals, graphs, stretch=(0, 1))),
            ("Compare", self.stats_graphs.compare_page),
            ("Trips", old.pop("adv:Ledger")),
            ("Fields", old.pop("adv:Fields")),
            ("Account", old.pop("adv:Account")),
        ])
        advanced = self._advanced_card()
        self.safety = note("Safety", "")
        self.safety.body.setTextFormat(Qt.RichText)
        self._show_safety()
        settings = [
            ("General", CardPage(GENERAL, card, top=(self.safety, advanced))),
            ("Features", self._features_page()),
            ("Server", CardPage(SERVER, card)),
            ("Telegram", old.pop("Telegram")),
            ("Notifications", DiscordPage()),
            ("Help", HelpPage(self.settings.values.get("safety.panic_key"))),
            ("Credits", CreditsPage()),             # who came up with each idea
            None,                                   # the ADVANCED heading
        ]
        # EVERY OTHER OPTION: today's full panels, as they are, in the order
        # the classic window had them.
        for label, name in (("Gather", "Gather"), ("Collect", "Collect"),
                            ("Kill", "Kill"), ("Quest givers", "Quests"),
                            ("More settings", "Settings"), ("Economy", "adv:Economy"),
                            ("All settings", "adv:All settings"),
                            ("Storage", "adv:Storage"), ("Log", "adv:Log")):
            settings.append((label, old.pop(name)))
        # THE VISION PAGE IS A DEVELOPER TOOL (ask the local vision model about
        # the screen by hand), not a setting; the owner, 19 Oct: "why is vision
        # model a tab it does like nothing". Kept in the classic window only.
        old.pop("adv:Vision", None)
        for label, page in old.items():             # anything added since
            settings.append((label.removeprefix("adv:"), page))
        self._add_tab("settings", settings)

    def _show_safety(self) -> None:
        """THE PARENTS' CARD (UI panel 2026-10-21: parent42 trusted it 4/10):
        what it never does, and how to stop it, at the top of General."""
        key = html.escape(str(self.settings.values.get("safety.panic_key") or "F12"))
        self.safety.body.setText(
            "Never spends Robux &nbsp;·&nbsp; never asks for your password &nbsp;·&nbsp; "
            f"Stop: <b>F3</b> &nbsp;·&nbsp; emergency stop key: <b>{key}</b> (stops everything)")

    def _goals_page(self, details: QWidget) -> QWidget:
        """THE GOALS PAGE IS THE GEAR PLAN (the owner, 2026-10-20: "the goals
        tab is super complex it should be super simple and have options to
        select and choose a order"): pick gear, order it, save. The old
        goal web and per-goal rows are kept, behind the Advanced button."""
        from .panels.gearplan import GearPlanPanel
        self.gear_plan = GearPlanPanel(self.settings.values, save=self._save_goal_order)
        page = QWidget()
        box = QVBoxLayout(page)
        box.setSpacing(8)
        stack = QStackedWidget()
        stack.addWidget(self.gear_plan)
        # ADVANCED: the old goal rows and goal web, and the session goals
        # (G9, its hours box: "why is there a hours thing", 2026-10-20)
        more_page = QWidget()
        more_box = QVBoxLayout(more_page)
        more_box.setContentsMargins(0, 0, 0, 0)
        more_box.addWidget(details, 3)
        more_box.addWidget(self.session_goals, 1)
        stack.addWidget(more_page)
        more = QPushButton("Advanced: full goal details")
        more.setCheckable(True)
        more.toggled.connect(lambda on: (stack.setCurrentIndex(int(on)), more.setText(
            "Back to my gear plan" if on else "Advanced: full goal details")))
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(more)
        box.addLayout(top)
        box.addWidget(stack, 1)
        return page

    def _save_goal_order(self, text: str) -> None:
        self._save_card("goals.order", text)
        self.refresh_goals()

    def _add_tab(self, key: str, pages) -> None:
        tab = QWidget()
        row = QHBoxLayout(tab)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        menu = QListWidget()
        menu.setObjectName("SideMenu")
        menu.setFixedWidth(178)
        menu.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        stack = QStackedWidget()
        advanced = False
        for entry in pages:
            if entry is None:                       # the rest is Advanced mode
                advanced = True
                heading = QListWidgetItem("ADVANCED")
                heading.setFlags(Qt.NoItemFlags)
                menu.addItem(heading)
                stack.addWidget(QWidget())
                self._advanced_rows.append((menu, menu.count() - 1))
                continue
            label, page = entry
            if not isinstance(page, CardPage) and page.layout() is not None:
                # the classic pages sat flush in a tab; here they get the
                # same breathing room as the card pages
                page.layout().setContentsMargins(20, 14, 20, 16)
            menu.addItem(QListWidgetItem(label))
            stack.addWidget(page)
            if advanced:
                self._advanced_rows.append((menu, menu.count() - 1))
        # PAGES CROSSFADE (simple.crossfade, 320 ms; a jump when not on screen)
        menu.currentRowChanged.connect(
            lambda row, s=stack: crossfade(s, s.widget(row)) if s.widget(row) else None)
        menu.setCurrentRow(0)
        row.addWidget(menu)
        row.addWidget(stack, 1)
        self._menus[key] = menu
        self._stacks[key] = stack
        self.tab_stack.addWidget(tab)

    def _advanced_card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("SettingCard")
        row = QHBoxLayout(frame)
        row.setContentsMargins(16, 12, 14, 12)
        words = QVBoxLayout()
        words.setSpacing(2)
        title = QLabel("Advanced mode")
        title.setStyleSheet("font-weight: 700; font-size: 14px;")
        sub = QLabel("Show every option: the full settings, the bot's "
                     "reasoning, economy, vision, storage and the log.")
        sub.setObjectName("Dim")
        sub.setWordWrap(True)
        words.addWidget(title)
        words.addWidget(sub)
        row.addLayout(words, 1)
        # `gui.mode` IS the switch: "advanced" in both layouts means every tab
        self.advanced_switch = Toggle()
        self.advanced_switch.toggled.connect(
            lambda on: self.set_mode("advanced" if on else "simple"))
        row.addWidget(self.advanced_switch, 0, Qt.AlignVCenter)
        return frame

    def _features_page(self) -> "CardPage":
        """U12: every errand and behaviour, on or off, on one page --
        world/settings.FEATURES, through the same cards and save path."""
        info = {key: (blurb, badge) for _, key, _, blurb, badge in FEATURES}
        groups = [(group, [(key, label) for g, key, label, *_ in FEATURES if g == group])
                  for group in FEATURE_GROUPS]
        about = note("Features",
                     "Every errand and behaviour the bot has, on or off. Live: it does "
                     "it. Watch only: it only says what it would do. Not measured: it "
                     "does it, on a guess nobody has measured yet.")
        return CardPage(groups, lambda key, label: self._make_card(key, label, *info[key]),
                        top=(about,), headings=True)

    def _hotbar_page(self) -> QWidget:
        """$11: the hotbar rules card (gui/panels/boosting.HotbarRules)."""
        from .panels.boosting import HotbarRules
        self.hotbar_rules = HotbarRules(self.settings.values, self._save_card, self._wheel)
        return self._padded(self.hotbar_rules, QWidget(), stretch=(0, 1))

    def refresh_goals(self, honey: int | None = None, decision=None) -> None:
        super().refresh_goals(honey, decision)
        if hasattr(self, "materials"):        # not yet inside MainWindow.__init__
            self.materials.show_plan(self.gear.plan)

    def _make_card(self, key: str, label: str, blurb: str = "", badge: str = ""):
        if key not in SCHEMA or not wired(key):
            return None
        if key == "gather.field":
            self._field_card = FieldCard(self.settings.values, self._save_card)
            return self._field_card
        card = SettingCard(key, label, self.settings.values.get(key),
                           self._save_card, self._wheel, blurb=blurb, badge=badge)
        self._cards.setdefault(key, []).append(card)
        return card

    def _save_card(self, key: str, value) -> None:
        """THE SAME PATH AS THE SETTINGS PANEL: its control is set, it saves
        the file, and `_setting_changed` tells the bot -- one way to save."""
        self.settings.set_value(key, value)

    def _show_tab(self, key: str) -> None:
        self.tab_buttons[key].setChecked(True)
        crossfade(self.tab_stack, self.tab_stack.widget([k for k, _ in TABS].index(key)))

    # ---- settings search -------------------------------------------------
    def search_index(self) -> list[tuple]:
        """Every tab, every page and every setting the window shows, as
        (title, where, words to match, target). A setting found on a simple
        page goes there; one only in the Advanced panels goes there."""
        names = dict(TABS)
        entries, found = [], {}
        for tab, menu in self._menus.items():
            # "AI progress", not .title()'s "Ai Progress" (UI panel round 2)
            tab_name = names[tab].capitalize().replace("Ai ", "AI ")
            entries.append((tab_name, "Tab", tab_name.casefold(), (tab, 0, None, None)))
            for row in range(menu.count()):
                item = menu.item(row)
                if not item.flags() & Qt.ItemIsEnabled:
                    continue                        # the ADVANCED heading
                advanced = (menu, row) in self._advanced_rows
                where = f"{tab_name} › {item.text()}" + (" (Advanced)" if advanced else "")
                entries.append((item.text(), "Page · " + where,
                                where.casefold(), (tab, row, None, None)))
                page = self._stacks[tab].widget(row)
                for word, text in getattr(page, "terms", ()):     # the Help page's words
                    entries.append((f"{word}: what it means", "Help · " + where,
                                    f"{word} {text} help".casefold(), (tab, row, None, None)))
                if isinstance(page, CardPage):
                    places = {k: (pill, card) for k, (pill, card) in page.where.items()}
                else:
                    places = {k: (None, w) for panel in page.findChildren(SettingsPanel)
                              for k, w in panel._widgets.items()}
                for key, (pill, widget) in places.items():
                    found.setdefault(key, []).append((advanced, where, (tab, row, pill, widget)))
        for key, places in found.items():
            places.sort(key=lambda place: place[0])    # a simple page first
            _, where, target = places[0]
            entry = SCHEMA.get(key)
            label, help_text = (entry[1], entry[4]) if entry else (key, "")
            entries.append((label, where, f"{label} {help_text} {key} {where}".casefold(),
                            target))
        return entries

    def open_search(self) -> None:
        self.command_palette = CommandPalette(self.search_index(), self)
        self.command_palette.chosen.connect(self.go_to)
        self.command_palette.move(self.mapToGlobal(QPoint(
            max(0, (self.width() - self.command_palette.width()) // 2), 64)))
        self.command_palette.show()
        self.command_palette.search.setFocus()

    def go_to(self, target) -> None:
        """Show a search hit: its tab, its page (Advanced mode switched on
        first when the page lives there), its pill, and the setting itself."""
        tab, row, pill, widget = target
        menu = self._menus[tab]
        if menu.isRowHidden(row):
            self.set_mode("advanced")
        self._show_tab(tab)
        menu.setCurrentRow(row)
        page = self._stacks[tab].widget(row)
        if pill is not None and isinstance(page, CardPage) and pill < len(page.pills):
            page.pills[pill].click()
        if widget is None:
            return
        area = widget.parentWidget()
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parentWidget()
        if area is not None:
            QApplication.processEvents()            # the page is laid out first
            area.ensureWidgetVisible(widget, 40, 60)
        getattr(widget, "control", widget).setFocus(Qt.OtherFocusReason)

    # ---- advanced mode -----------------------------------------------------
    def show_mode(self, mode: str, animate: bool = True) -> None:
        super().show_mode(mode, animate=False)
        if not self._menus:
            return                         # still inside MainWindow.__init__
        self._advanced = str(mode) == "advanced"
        self.advanced_switch.blockSignals(True)
        self.advanced_switch.setChecked(self._advanced)
        self.advanced_switch.blockSignals(False)
        for menu, row in self._advanced_rows:
            menu.setRowHidden(row, not self._advanced)
            if not self._advanced and menu.currentRow() == row:
                menu.setCurrentRow(0)

    @property
    def advanced_mode(self) -> bool:
        return self._advanced

    # ---- keeping the frame in step ---------------------------------------
    def _sync_bar(self) -> None:
        """The bottom bar copies the classic bar, which stays the ONE place
        that decides what is live (StatusBar._apply_buttons)."""
        s = self.status
        for mine, theirs in zip(self.run_buttons, (s._start, s._pause, s._stop)):
            mine.setEnabled(theirs.isEnabled())
            mine.setText(theirs.text().split()[0])
        replay = bool(getattr(self, "_replay_name", ""))
        running = s._running and not replay
        self._set_primary(self.start_button, not running)
        self._set_primary(self.stop_button, running)
        glyph, word, colour = run_look(s, self.bot.running(), self.bot.exit_code(), replay)
        self.live.set_running(running)
        if hasattr(self, "stats_graphs"):
            self.stats_graphs.set_running(running)
        self._word.setText(f"{glyph}  {word}")
        self._word.setStyleSheet(f"color: {colour}; font-weight: 700;")
        self._dot.set_state(colour, pulsing=word == "Running")
        # the dot only for a bot that is alive: beside "■ Stopped" it was a
        # second, meaningless shape
        self._dot.setVisible(word in ("Running", "Starting"))
        # the word is said once: "running — gathering" shows as "gathering"
        detail = s._state.text()
        head, dash, rest = detail.partition(" — ")
        if head.casefold() == word.casefold() or (replay and head in ("running", "paused")):
            detail = rest
        if word == "Stopped" and detail.startswith("not connected"):
            detail = "Press Start (F1) to begin."         # the plain version
        self._state.setText(detail)
        self._state.setToolTip(s._state.text())
        self._show_doing()

    def _task(self, event) -> None:
        super()._task(event)
        self._show_doing()

    def _show_doing(self) -> None:
        """What it is doing, unless that only repeats the state ("idle idle")."""
        doing = self.task_label.text()
        said = f"{self._word.text()} {self._state.text()}".casefold()
        self._doing.setText(doing)
        self._doing.setVisible(doing.casefold() not in ("", "idle") and doing.casefold() not in said)

    def handle(self, event) -> None:
        super().handle(event)
        if isinstance(event, TimerEvent):
            self.boost_strip.update_timer(event)
        # ONE LINE, THE WHOLE REASON ON HOVER (UI panel round 2, 2026-10-22:
        # kid, teen, grandad and ESL readers met a paragraph)
        if isinstance(event, Thought) and event.topic == "plan":
            self._thinking.body.setText(_first_sentence(event.text))
            self._thinking.body.setToolTip(event.text)
        elif isinstance(event, Considered) and event.chosen:
            # THE LATEST DECISION, not "waiting for one" while the Thinking
            # page already shows it (UI panel 2026-10-21, the streamer)
            self._thinking.body.setText(f"It chose “{event.chosen}”.")
            self._thinking.body.setToolTip(f"{event.question} It chose “{event.chosen}”."
                                           + (f" {event.rationale}" if event.rationale else ""))

    def _sync_take_control(self) -> None:
        """THE PICTURE COMES FORWARD when the controls become the owner's
        (RL1b step 3): Macro's Live view page, where his mouse and keys reach
        the game."""
        was = self.live.taking
        super()._sync_take_control()
        menu = self._menus.get("macro")
        if self.live.taking and not was and menu is not None:
            for row in range(menu.count()):
                if menu.item(row).text() == "Live view":
                    self.go_to(("macro", row, None, None))
                    break

    def eventFilter(self, obj, event) -> bool:
        # ...ToParent: sent whether or not the holder is on screen yet
        if (obj is getattr(self, "inbox", None)
                and event.type() in (QEvent.ShowToParent, QEvent.HideToParent)):
            self._sync_inbox()
        return super().eventFilter(obj, event)

    def _sync_inbox(self) -> None:
        self._inbox_holder.setVisible(not self.inbox.isHidden())

    def _setting_changed(self, key: str, value) -> None:
        super()._setting_changed(key, value)
        # EVERY COPY SHOWS IT: the cards, and the classic panels that hold
        # the same key (a change on Advanced > Gather shows on the card).
        for card in self._cards.get(key, ()):
            card.show_value(value)
        for panel in self.findChildren(SettingsPanel):
            widget = panel._widgets.get(key)
            if widget is None or panel.values.get(key) == value:
                continue
            panel.values[key] = value
            widget.blockSignals(True)
            try:
                if hasattr(widget, "setChecked"):
                    widget.setChecked(bool(value))
                elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                    widget.setValue(type(widget.value())(value))
                elif isinstance(widget, QComboBox):
                    widget.setCurrentText(str(value))
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(value))
            except (TypeError, ValueError):
                pass
            finally:
                widget.blockSignals(False)
        if key == "mode.macro" and hasattr(self, "macro_mode"):
            self.macro_mode.show_value(bool(value))
        elif key == "macro.fields" and hasattr(self, "macro_list"):
            self.macro_list.show_fields(value)
        elif key == "hotbar.rules" and hasattr(self, "hotbar_rules"):
            self.hotbar_rules.show_rules(value)
        elif key == "safety.panic_key" and hasattr(self, "safety"):
            self._show_safety()
        elif key == "goals.owned" and hasattr(self, "gear_plan"):
            self.gear_plan.reload()           # owned gear greys out on the Goals page
        if key in ("gather.auto_field", "gather.field", "mode.macro", "macro.fields"):
            self._show_mode_label()
            if self._field_card is not None:
                self._field_card.refresh()

    # IN MACRO MODE THE AI'S FIELD CARDS ARE HIDDEN: they do nothing there
    # (run_farm skips the pin and the boost redirect in macro mode), and the
    # owner read them as live options (2026-10-19 review of the U16 shots).
    # + the ones each macro field sets for itself (SETTINGS AUDIT 2026-10-19:
    # macro mode overrides convert_at, both sprinkler settings and quests.first)
    AI_FIELD_KEYS = ("gather.auto_field", "gather.follow_boost", "gather.convert_at",
                     "gather.use_sprinklers", "gather.sprinklers", "quests.first")

    def _show_ai_field_cards(self) -> None:
        values = self.settings.values
        macro = bool(values.get("mode.macro"))
        # "Hivemind chooses" IS the AI picking (UI panel item 12): its own
        # pick-a-field switch and card show only to someone who pinned a
        # field before, so they can unpin it; the list is the way to choose.
        pinned = not values.get("gather.auto_field", True)
        page = getattr(self, "_gather_page", None)
        for key in self.AI_FIELD_KEYS:
            for card in self._cards.get(key, []):
                # only on Gather: Settings > Features lists every switch
                on_gather = page is not None and page.isAncestorOf(card)
                card.setVisible(not macro and (key != "gather.auto_field" or pinned
                                               or not on_gather))
        if self._field_card is not None:
            self._field_card.setVisible(not macro and pinned)
        if hasattr(self, "macro_list"):
            self.macro_list.empty.setText(EMPTY_LIST if macro else EMPTY_LIST_AI)
        if page is not None:
            page.sync_pills()

    def _show_mode_label(self) -> None:
        """What is driving the field choice, in two words: macro mode's
        list (U16), the AI, or the owner's one pinned field."""
        self._show_ai_field_cards()
        values = self.settings.values
        fields = macro_fields(values.get("macro.fields"))[0]    # what the bot uses
        if values.get("mode.macro") and fields:
            self._mode_label.setText(f"Macro · {len(fields)} field{'' if len(fields) == 1 else 's'}")
            return
        if values.get("mode.macro"):
            # an empty or all-bad list is AI mode to the bot (brain/macro.active)
            self._mode_label.setText("No valid fields: add one with +")
            return
        self._mode_label.setText(
            "AI picks the field" if values.get("gather.auto_field", True)
            else f"Macro · {values.get('gather.field') or 'auto'}")

    # ---- presets -----------------------------------------------------------
    SAVE_PRESET = "Save current as preset…"

    def _preset_dir(self):
        return settings_panel.CONFIG.parent / "presets"

    def _fill_presets(self, current: str = "") -> None:
        """The presets folder beside settings.yaml, read fresh each time."""
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItem("Current settings")
        try:
            names = sorted(p.stem for p in self._preset_dir().glob("*.yaml"))
        except OSError:
            names = []
        self.preset.addItems(names)
        self.preset.addItem(self.SAVE_PRESET)
        if current in names:
            self.preset.setCurrentText(current)
        self.preset.blockSignals(False)

    def _preset_chosen(self, index: int) -> None:
        """Load a preset through the settings panel's own import (secrets,
        locked keys and unknown keys are never taken), or save one."""
        text = self.preset.itemText(index)
        folder = self._preset_dir()
        if text == self.SAVE_PRESET:
            name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
            name = "".join(c for c in name if c.isalnum() or c in " -_").strip()
            if ok and name:
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    count = self.settings.export_preset(folder / f"{name}.yaml")
                    self.status.set_note(f"saved preset {name} ({count} settings)")
                except OSError as exc:
                    self.status.set_note(f"preset not saved: {exc.strerror or exc}")
            self._fill_presets(name if ok else "")
            return
        if index == 0:
            return
        try:
            taken, skipped = self.settings.import_preset(folder / f"{text}.yaml")
            self.status.set_note(f"loaded preset {text}: {taken} settings"
                                 + (f", {len(skipped)} skipped" if skipped else ""))
        except Exception as exc:                      # never break the GUI
            self.status.set_note(f"preset {text} not loaded: {exc}")
            self._fill_presets()
