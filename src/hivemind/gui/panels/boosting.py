"""The Boosting tab's own two widgets (ROADMAP U19).

BoostStrip   every boost's timer, live: the field boost running, each field
             booster's cooldown and each item buff still running. Fed by the
             bot's Timer events (run_farm show_boost / show_boost_timers,
             categories boost / booster / item); it counts down by itself.
MeasuredGains what a boost is worth on each field, from the bot's own trips
             (brain/boostai.measure over var/trips.jsonl and var/boosts.jsonl)
             -- the numbers the boost AI decides by. A field with too few
             boosted trips says "not measured", never a guess.
HotbarRules  the `hotbar.rules` editor ($11): one row per rule, + and x;
             the list is saved whole, through the window's one save path.
"""
from __future__ import annotations

import time
import weakref

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QSpinBox, QToolButton, QVBoxLayout, QWidget)

from .. import gameicons, theme
from ..widgets import human_duration
from ...brain import boostai
from ...brain.hotbarrules import KEEPER_ITEMS
from ...world.settings import (HOTBAR_ENTRY, HOTBAR_ITEMS, HOTBAR_MAX,
                               HOTBAR_NUMBERS, HOTBAR_TRIGGERS, macro_field_names)

# (timer id, label, icon kind, icon name): the tiles shown before any event.
# A booster has no icon of its own on the wiki, so it wears its main field's.
FIXED = (("boost_running", "Field boost", "items", "Glitter", "none running"),
         ("booster:blue_field_booster", "Blue booster", "fields", "Blue Flower", "not pressed yet"),
         ("booster:red_field_booster", "Red booster", "fields", "Rose", "not pressed yet"),
         ("booster:white_field_booster", "Mountain booster", "fields", "Mountain Top",
          "not pressed yet"))
CATEGORIES = ("boost", "booster", "item")


def _icon(kind: str, name: str, size: int = 28) -> QLabel:
    label = QLabel()
    label.setFixedSize(size, size)
    label.setPixmap(gameicons.pixmap(kind, name, size))
    return label


class BoostTile(QFrame):
    def __init__(self, label: str, kind: str, icon: str, idle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("SettingCard")
        self.setMinimumWidth(170)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(10)
        self.icon = _icon(kind, icon)
        row.addWidget(self.icon, 0, Qt.AlignVCenter)
        words = QVBoxLayout()
        words.setSpacing(1)
        self.name = QLabel(label)
        self.name.setStyleSheet("font-weight: 600;")
        self.left = QLabel()
        self.left.setStyleSheet(f"font-family: {theme.MONO}; font-size: 12px;")
        words.addWidget(self.name)
        words.addWidget(self.left)
        row.addLayout(words, 1)
        self.idle = idle
        self.category = ""
        self.ready_at = 0.0
        self.refresh()

    def set_icon(self, kind: str, name: str) -> None:
        self.icon.setPixmap(gameicons.pixmap(kind, name, 28))

    def refresh(self) -> None:
        if not self.ready_at:
            text, colour = self.idle, theme.S_FAINT
        else:
            left = self.ready_at - time.time()
            if self.category == "booster":
                text, colour = ((f"ready in {human_duration(left)}", theme.S_DIM) if left > 0
                                else ("ready", theme.S_GOOD))
            else:
                text, colour = ((f"{human_duration(left)} left", theme.S_GOOD) if left > 0
                                else ("ended", theme.S_FAINT))
        self.left.setText(text)
        self.left.setStyleSheet(f"font-family: {theme.MONO}; font-size: 12px; color: {colour};")


class BoostStrip(QWidget):
    """The live timers, four to a row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)
        self.tiles: dict[str, BoostTile] = {}
        for tid, label, kind, icon, idle in FIXED:
            self._add(tid, BoostTile(label, kind, icon, idle))
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self.refresh)
        self._ticker.start(1000)

    def _add(self, tid: str, tile: BoostTile) -> None:
        n = len(self.tiles)
        self.tiles[tid] = tile
        self.grid.addWidget(tile, n // 4, n % 4)

    def update_timer(self, timer) -> None:
        """A Timer event from the bot; anything not a boost is ignored."""
        if timer.category not in CATEGORIES:
            return
        tile = self.tiles.get(timer.id)
        if tile is None:
            # an item buff: the game's own item icon, by its name
            tile = BoostTile(timer.name, "items", timer.name)
            self._add(timer.id, tile)
        if timer.category == "boost":
            # "Boost · pine tree x2": the boosted field's icon and words
            words = timer.name.split("·", 1)[-1].strip()
            field = words.rsplit(" x", 1)[0]
            tile.name.setText(f"Field boost · {words}" if words else "Field boost")
            if field and field != "field not read":
                tile.set_icon("fields", field.title())
        tile.category = timer.category
        tile.ready_at = float(timer.ready_at or 0.0)
        tile.setToolTip(timer.note or "")
        tile.refresh()

    def refresh(self) -> None:
        for tile in self.tiles.values():
            tile.refresh()


class MeasuredGains(QFrame):
    """What a boost adds on each field, measured -- re-read when shown."""

    def __init__(self, var=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Note")
        if var is None:
            from ...datapaths import VAR_ROOT
            var = VAR_ROOT
        self.var = var
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(8)
        head = QLabel("WHAT A BOOST IS WORTH, MEASURED")
        head.setObjectName("Section")
        box.addWidget(head)
        sub = QLabel("Each field's boosted trips against its own unboosted trips the "
                     "same day. The boost AI decides only by these.")
        sub.setObjectName("Dim")
        sub.setWordWrap(True)
        box.addWidget(sub)
        self.rows = QGridLayout()
        self.rows.setHorizontalSpacing(18)
        self.rows.setVerticalSpacing(6)
        box.addLayout(self.rows)
        self.unmeasured = QHBoxLayout()
        self.unmeasured.setSpacing(6)
        later = QLabel("Not measured yet")
        later.setObjectName("Dim")
        self.unmeasured.addWidget(later)
        box.addLayout(self.unmeasured)
        self.missing = QLabel()
        self.missing.setObjectName("Dim")
        self.missing.setWordWrap(True)
        box.addWidget(self.missing)
        self.gains: dict = {}

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload()

    def reload(self) -> None:
        trips = boostai.read_jsonl(self.var / "trips.jsonl")
        presses = boostai.read_jsonl(self.var / "boosts.jsonl")
        self.show_gains(boostai.measure(trips, presses), presses)

    def show_gains(self, gains: dict, presses=()) -> None:
        self.gains = gains
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for r, g in enumerate(sorted(gains.values(), key=lambda g: -g.extra_rate)):
            name = g.field.replace("_", " ").title()
            cells = (_icon("fields", name, 22), QLabel(name), QLabel(f"x{g.ratio:.2f}"),
                     QLabel(f"+{g.extra_rate:,.0f} pollen/s"), QLabel(f"{g.pairs} trips"))
            cells[2].setStyleSheet(f"color: {theme.S_AMBER}; font-weight: 700;")
            cells[4].setObjectName("Dim")
            for c, cell in enumerate(cells):
                self.rows.addWidget(cell, r, c)
        self.rows.setColumnStretch(5, 1)
        names = [n for _, ns in gameicons.field_zones() for n in ns]
        self.not_yet = [n for n in names if gameicons.slug(n) not in gains]
        while self.unmeasured.count() > 1:
            item = self.unmeasured.takeAt(1)
            if item.widget() is not None:
                item.widget().deleteLater()
        for n in self.not_yet:
            icon = _icon("fields", n, 22)
            icon.setToolTip(f"{n}: under {boostai.MIN_PAIRS} boosted trips to compare")
            self.unmeasured.addWidget(icon)
        self.unmeasured.addStretch(1)
        dice = [p for p in presses if p.get("booster") == "field_dice"]
        read = sum(1 for p in dice if p.get("field"))
        self.missing.setText(
            ("No field's boost is measured yet. " if not gains else "")
            + f"Field Dice: {read} of {len(dice)} rolls had their field read, so where "
            + ("one lands is measured." if read >= boostai.MIN_PAIRS
               else "one lands is not measured: in Act the AI rolls none."))


class HotbarRuleRow(QFrame):
    """One rule: item, trigger and its interval on the first line, the
    conditions on the second. Every edit goes to `edit(index, key, value)`."""

    def __init__(self, index: int, rule: dict, edit, remove, wheel_guard=None, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingCard")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.index = index
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 9, 10, 9)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.icon = _icon("items", HOTBAR_ITEMS[rule["item"]], 30)
        grid.addWidget(self.icon, 0, 0, 2, 1, Qt.AlignTop)

        self.item = QComboBox()
        for key, label in HOTBAR_ITEMS.items():
            self.item.addItem(gameicons.icon("items", label, 20), label, key)
        self.trigger = QComboBox()
        for key, label in HOTBAR_TRIGGERS.items():
            self.trigger.addItem(label, key)
        self.minutes = self._number("minutes", " min", rule)
        self.seconds = self._number("seconds", " s", rule)
        self.field = QComboBox()
        self.field.addItem("Any field", "")
        for name in macro_field_names():
            self.field.addItem(gameicons.icon("fields", name, 18), name, name)
        self.keep = self._number("keep", "", rule)
        self.keep.setPrefix("keep ")
        self.level = self._number("hive_level", "", rule)
        self.level.setSpecialValueText("any level")
        self.level.setPrefix("hive lvl ≥ ")
        self.over_ai = QCheckBox("Rule over AI")
        self.over_ai.setToolTip("When the boost keeper also uses this item (Field Dice), "
                                "the rule wins. Unticked, the keeper and the boost AI "
                                "decide. The boost AI's veto in 'act' still stands.")
        self.remove = QToolButton()
        self.remove.setObjectName("Kebab")
        self.remove.setText("✕")
        self.remove.setToolTip("Remove this rule")
        self.remove.setCursor(Qt.PointingHandCursor)
        self.remove.clicked.connect(lambda: remove(self.index))

        for combo, value in ((self.item, rule["item"]), (self.trigger, rule["trigger"]),
                             (self.field, rule["field"])):
            combo.setCurrentIndex(max(0, combo.findData(value)))
        self.over_ai.setChecked(bool(rule["over_ai"]))
        self.item.setMinimumWidth(170)
        self.trigger.setMinimumWidth(210)
        self.field.setMinimumWidth(170)
        top = QHBoxLayout()
        top.setSpacing(8)
        for w in (self.item, self.trigger, self.minutes, self.seconds):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(self.remove)
        grid.addLayout(top, 0, 1)
        low = QHBoxLayout()
        low.setSpacing(8)
        only = QLabel("Only")
        only.setObjectName("Dim")
        for w in (only, self.field, self.keep, self.level, self.over_ai):
            low.addWidget(w)
        low.addStretch(1)
        grid.addLayout(low, 1, 1)
        grid.setColumnStretch(1, 1)

        for combo, key in ((self.item, "item"), (self.trigger, "trigger"), (self.field, "field")):
            combo.currentIndexChanged.connect(
                lambda _=0, k=key, w=combo: edit(self.index, k, w.currentData()))
        for spin, key in ((self.minutes, "minutes"), (self.seconds, "seconds"),
                          (self.keep, "keep"), (self.level, "hive_level")):
            spin.valueChanged.connect(lambda v, k=key: edit(self.index, k, int(v)))
        self.over_ai.toggled.connect(lambda on: edit(self.index, "over_ai", bool(on)))
        if wheel_guard is not None:
            for w in (self.item, self.trigger, self.field, self.minutes, self.seconds,
                      self.keep, self.level):
                w.setFocusPolicy(Qt.StrongFocus)
                w.installEventFilter(wheel_guard)
        self.show_trigger(rule["trigger"])
        self.show_item(rule["item"])

    def show_item(self, item: str) -> None:
        """'Rule over AI' only matters for an item the boost keeper also uses."""
        self.icon.setPixmap(gameicons.pixmap("items", HOTBAR_ITEMS[item], 30))
        self.over_ai.setEnabled(item in KEEPER_ITEMS)

    @staticmethod
    def _number(key: str, suffix: str, rule: dict) -> QSpinBox:
        spin = QSpinBox()
        spin.setObjectName("Num")
        spin.setRange(*HOTBAR_NUMBERS[key])
        spin.setSuffix(suffix)
        spin.setAlignment(Qt.AlignRight)
        spin.setFixedWidth(130 if key in ("keep", "hive_level") else 90)
        spin.setValue(int(rule[key]))
        return spin

    def show_trigger(self, trigger: str) -> None:
        """Only the interval the trigger uses is shown."""
        self.minutes.setVisible(trigger == "every")
        self.seconds.setVisible(trigger == "gathering")


class HotbarRules(QFrame):
    """`hotbar.rules` as rows, "+" and x. `save(key, value)` is the window's
    own; the list is saved whole, a copy each time."""

    def __init__(self, values: dict, save, wheel_guard=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Note")
        self._save = save
        # A WEAK REFERENCE: holding the window's wheel guard outright crashed
        # the interpreter at exit (shiboken, after the window was deleted)
        self._wheel = weakref.ref(wheel_guard) if wheel_guard is not None else (lambda: None)
        self.rules: list[dict] = [dict(r) for r in values.get("hotbar.rules") or []]
        self.rows: list[HotbarRuleRow] = []
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("HOTBAR RULES")
        title.setObjectName("Section")
        head.addWidget(title)
        head.addStretch(1)
        self.add_button = QPushButton("+  Add a rule")
        self.add_button.setObjectName("Primary")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(self.add)
        head.addWidget(self.add_button)
        box.addLayout(head)
        sub = QLabel("Press a hotbar item on a rule, like a classic macro's hotbar slots. The slot is "
                     "found by the item's picture. A use is skipped, and logged, when the "
                     "item is greyed or cooling down, the reserve would be touched, "
                     "materials are for crafting (under hive level 16) or the boost AI "
                     "vetoes it. Never Robux.")
        sub.setObjectName("Dim")
        sub.setWordWrap(True)
        box.addWidget(sub)
        self.empty = QLabel("No rules: nothing is pressed on a rule. Press + to add one "
                            f"(up to {HOTBAR_MAX}).")
        self.empty.setObjectName("Dim")
        self.empty.setWordWrap(True)
        box.addWidget(self.empty)
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(6)
        box.addLayout(self._rows_box)
        self._rebuild()

    def _rebuild(self) -> None:
        for row in self.rows:
            self._rows_box.removeWidget(row)
            row.deleteLater()
        self.rows = [HotbarRuleRow(i, r, self.edit, self.remove, self._wheel())
                     for i, r in enumerate(self.rules)]
        for row in self.rows:
            self._rows_box.addWidget(row)
        self.empty.setVisible(not self.rules)
        self.add_button.setEnabled(len(self.rules) < HOTBAR_MAX)

    def _commit(self) -> None:
        self._save("hotbar.rules", [dict(r) for r in self.rules])

    def add(self) -> None:
        if len(self.rules) >= HOTBAR_MAX:
            return
        used = {r["item"] for r in self.rules}
        item = next((k for k in HOTBAR_ITEMS if k not in used), next(iter(HOTBAR_ITEMS)))
        self.rules.append({"item": item, **HOTBAR_ENTRY})
        self._rebuild()
        self._commit()

    def remove(self, index: int) -> None:
        del self.rules[index]
        self._rebuild()
        self._commit()

    def edit(self, index: int, key: str, value) -> None:
        self.rules[index][key] = value
        row = self.rows[index]
        if key == "item":
            row.show_item(value)
        elif key == "trigger":
            row.show_trigger(value)
        self._commit()

    def show_rules(self, value) -> None:
        """A list saved elsewhere (a preset, the file): shown, not saved."""
        rules = [dict(r) for r in value or []]
        if rules != self.rules:
            self.rules = rules
            self._rebuild()
