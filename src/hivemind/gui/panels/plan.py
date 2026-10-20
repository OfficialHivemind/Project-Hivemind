"""THE PLAN TAB: "What should Hivemind do?" (choose-design 2026-10-26).

    +-------------------------------------+  +-----------------------------+
    | WHAT SHOULD HIVEMIND DO?            |  | NOW   Gathering at Pine Tree |
    | (o) Progress my account  recommended|  | WHY   it pays the most blue  |
    | ( ) Get one item  [Porcelain Dipper]|  | NEXT  o Porcelain Dipper [I have it]
    | ( ) Make the most honey             |  | GOAL  Tad alt, blue hive     |
    | ...  Fuzzy alt / Tad alt / Hybrid   |  | PROOF bought Glue (3 h ago)  |
    | Hive colour: blue (guessed ...)     |  +-----------------------------+
    | 2 of your own changes kept  [Reset] |
    | Switched to ...             [Undo]  |
    +-------------------------------------+

NOTHING HERE ASKS. One click on a choice writes its recipe (brain/plan.apply),
says what it did, and offers one-tap Undo. A switch the player set by hand is
kept and counted ("N of your own changes kept"); Reset gives them all back to
the plan. The dropdowns come pre-filled with the sensible pick (the next item
on the route, the quest bear worth the most), so a click is enough.

Every write goes through the settings panel's file and its `changed` signal,
so the bot hears of each key exactly as if it had been flipped by hand.
"""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QRadioButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from .. import theme
from ...brain import plan

ORDER = ("progress", "item", "honey", "quests", "tickets", "macro",
         "fuzzy_alt", "tad_alt", "hybrid", plan.CUSTOM)
RECOMMENDED = "progress"
HYBRID_DEFAULT = ("fuzzy_alt", "tad_alt")
REFRESH_MS = 5000          # the NOW / NEXT card re-reads the bot's files this often
STATE_LOOK = {"yes": ("done", theme.S_GOOD), "no": ("to do", theme.S_AMBER),
              "?": ("can't tell yet", theme.S_DIM)}

RADIO_STYLE = (
    "QRadioButton { font-weight: 700; spacing: 8px; }"
    "QRadioButton::indicator { width: 12px; height: 12px; border-radius: 8px;"
    f" border: 2px solid {theme.S_DIM}; background: transparent; }}"
    f"QRadioButton::indicator:hover {{ border-color: {theme.S_AMBER}; }}"
    f"QRadioButton::indicator:checked {{ border: 2px solid {theme.S_AMBER};"
    " background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,"
    f" stop:0 {theme.S_AMBER}, stop:0.5 {theme.S_AMBER}, stop:0.6 transparent); }}")


def _config() -> Path:
    from . import settings as settings_panel
    return settings_panel.CONFIG              # read at call time: tests and --demo move it


def _var() -> Path:
    from ... import datapaths
    return datapaths.VAR_ROOT


def giver_names() -> list[str]:
    from ...act.bearvisit import GIVER_SETTINGS
    return [g.replace("_", " ").title() for g in GIVER_SETTINGS]


def best_giver(var_root) -> str:
    """The quest bear whose open quest pays the most per step (brain/questvalue
    on var/quests.json); Bucko Bee when nothing has been read (choose-design)."""
    try:
        from ...brain import questvalue
        quests = json.loads((Path(var_root) / "quests.json").read_text(encoding="utf-8"))
        for row in questvalue.ranked(quests.get("quests") or []):
            name = str(row.giver or "").strip()
            if plan.giver_key(name):
                return name.title()
    except Exception:              # no read yet, or a broken file: the default
        pass
    return "Bucko Bee"


def item_names(var_root, values) -> list[str]:
    """The next items on the route first (brain/progression), then every
    priced item, each once."""
    first = []
    try:
        from ...brain import progression
        first = [n.label for n in progression.progress(var_root, values, n=8).next
                 if n.goal.get("kind") in plan.HAVE_KINDS]
    except Exception:
        pass
    try:
        from ...brain import owned
        rest = sorted(str(i.label) for i in owned.prices().values())
    except Exception:
        rest = []
    return list(dict.fromkeys(first + rest))


def _dim(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Dim")
    label.setWordWrap(True)
    return label


class PlanPanel(QScrollArea):
    """The PLAN tab's page. `settings` is the window's SettingsPanel."""

    def __init__(self, settings, parent=None, clock=time.time):
        super().__init__(parent)
        self.settings = settings
        self.clock = clock
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        cols = QHBoxLayout(inner)
        cols.setContentsMargins(20, 14, 20, 16)
        cols.setSpacing(16)
        cols.addWidget(self._choices(), 5, Qt.AlignTop)
        cols.addWidget(self._status_card(), 4, Qt.AlignTop)
        self.setWidget(inner)
        self._undo = None                       # the last one-tap undo
        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.refresh)
        settings.changed.connect(self._changed)
        self.show_choice()
        self.refresh()

    # ---- the choice list --------------------------------------------------
    def _choices(self) -> QFrame:
        card = QFrame()
        card.setObjectName("SettingCard")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # A RING YOU CAN SEE on every choice (the shell's sheet left only the
        # chosen one's dot), amber when chosen
        card.setStyleSheet(RADIO_STYLE)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(6)
        head = QLabel("WHAT SHOULD HIVEMIND DO?")
        head.setObjectName("Section")
        box.addWidget(head)
        self.group = QButtonGroup(self)
        self.radios: dict[str, QRadioButton] = {}
        values = self.settings.values
        var_root = _var()
        # the two dropdowns, filled with the sensible pick
        self.item_box = QComboBox()
        self.item_box.addItems(item_names(var_root, values))
        self.quest_box = QComboBox()
        self.quest_box.addItems(giver_names())
        self.quest_box.setCurrentText(best_giver(var_root))
        for combo, choice in ((self.item_box, "item"), (self.quest_box, "quests")):
            combo.setMinimumWidth(190)
            combo.activated.connect(lambda _i, c=choice: self.choose(c))
        # Hybrid: tick the targets it merges into one order (brain/hybrid)
        self.hybrid_box = QWidget()
        picks = QGridLayout(self.hybrid_box)
        picks.setContentsMargins(26, 0, 0, 4)
        picks.setHorizontalSpacing(14)
        self.hybrid_checks: dict[str, QCheckBox] = {}
        self._quiet = False                     # show_choice is showing, not choosing
        for i, (tid, entry) in enumerate(plan.alt_goals().items()):
            check = QCheckBox(str(entry.get("label") or tid))
            check.setToolTip(str(entry.get("line") or ""))
            check.setChecked(tid in HYBRID_DEFAULT)
            check.toggled.connect(lambda _on: self._quiet or self.choose("hybrid"))
            picks.addWidget(check, i // 3, i % 3)
            self.hybrid_checks[tid] = check
        for choice in ORDER:
            name, line = plan.label(choice)
            radio = QRadioButton(name)
            radio.setCursor(Qt.PointingHandCursor)
            radio.clicked.connect(lambda _on=False, c=choice: self.choose(c))
            self.group.addButton(radio)
            self.radios[choice] = radio
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(radio)
            if choice == RECOMMENDED:
                star = QLabel("recommended")
                star.setObjectName("Badge")
                row.addWidget(star)
            extra = {"item": self.item_box, "quests": self.quest_box}.get(choice)
            if extra is not None:
                row.addWidget(extra)
            row.addStretch(1)
            box.addLayout(row)
            words = _dim(line)
            words.setContentsMargins(26, 0, 0, 2)
            box.addWidget(words)
            if choice == "hybrid":
                box.addWidget(self.hybrid_box)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {theme.S_LINE};")
        box.addWidget(line)
        self.hive_line = _dim()
        box.addWidget(self.hive_line)
        kept = QHBoxLayout()
        self.kept_line = _dim()
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Give all your own changes back to the plan")
        self.reset_button.clicked.connect(self.reset)
        kept.addWidget(self.kept_line, 1)
        kept.addWidget(self.reset_button)
        box.addLayout(kept)
        said = QHBoxLayout()
        self.said = QLabel()
        self.said.setWordWrap(True)
        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo)
        self.undo_button.setVisible(False)
        said.addWidget(self.said, 1)
        said.addWidget(self.undo_button)
        box.addLayout(said)
        return card

    def _target(self, choice: str) -> str:
        if choice == "item":
            return self.item_box.currentText()
        if choice == "quests":
            return self.quest_box.currentText()
        if choice == "hybrid":
            return ", ".join(t for t, c in self.hybrid_checks.items() if c.isChecked())
        return ""

    def show_choice(self) -> None:
        """The radios and boxes show what the file says (no saving)."""
        goal = str(self.settings.values.get("plan.goal") or plan.CUSTOM)
        target = str(self.settings.values.get("plan.target") or "")
        radio = self.radios.get(goal, self.radios[plan.CUSTOM])
        radio.setChecked(True)
        if goal == "item" and target:
            if self.item_box.findText(target) < 0:
                self.item_box.insertItem(0, target)
            self.item_box.setCurrentText(target)
        elif goal == "quests" and target:
            self.quest_box.setCurrentText(target.title())
        elif goal == "hybrid" and target:
            picked = plan.picks(target)
            self._quiet = True
            for tid, check in self.hybrid_checks.items():
                check.setChecked(tid in picked)
            self._quiet = False
        self.hybrid_box.setVisible(goal == "hybrid")

    # ---- doing it --------------------------------------------------------
    def _tell(self, keys) -> None:
        """The file changed under the settings panel: it re-reads, then the
        bot and every other view hear of each key."""
        self.settings.load()
        for key in keys:
            self.settings.changed.emit(key, self.settings.values.get(key))

    def choose(self, choice: str) -> None:
        name = plan.label(choice)[0]
        try:
            if choice == plan.CUSTOM:
                # brain/plan writes nothing for "custom"; the choice itself is saved
                self.settings.set_value("plan.goal", plan.CUSTOM)
                result = {"changed": {}, "kept": {}}
                self._undo = None
            else:
                result = plan.apply(choice, self._target(choice), config=_config(),
                                    var_root=_var())
                self._tell(result["changed"])
                self._undo = self._undo_plan
        except (ValueError, OSError) as exc:
            self.said.setText(f"Could not switch: {exc}")
            return
        changed = [k for k in result["changed"] if not k.startswith("plan.")]
        if choice == plan.CUSTOM:
            text = "Your own setup: Hivemind leaves every switch as you set it."
        else:
            text = f"Now: {name}. {len(changed)} switch{'' if len(changed) == 1 else 'es'} changed"
            text += (f", {len(result['kept'])} of yours kept." if result["kept"] else ".")
        self.said.setText(text)
        self.undo_button.setVisible(self._undo is not None)
        self.show_choice()
        self.refresh()

    def _undo_plan(self) -> tuple[str, list]:
        back = plan.undo(_config())
        return f"Put back {len(back)} setting{'' if len(back) == 1 else 's'} as they were.", list(back)

    def undo(self) -> None:
        fn, self._undo = self._undo, None
        if fn is None:
            return
        try:
            text, keys = fn()
            self._tell(keys)
        except (ValueError, OSError) as exc:
            text = f"Could not undo: {exc}"
        self.said.setText(text)
        self.undo_button.setVisible(False)
        self.show_choice()
        self.refresh()

    def reset(self) -> None:
        """Give every kept key back to the plan."""
        goal = str(self.settings.values.get("plan.goal") or plan.CUSTOM)
        keys = list(plan.conflicts(_config(), _var()))
        if goal == plan.CUSTOM or not keys:
            return
        try:
            result = plan.apply(goal, str(self.settings.values.get("plan.target") or ""),
                                config=_config(), var_root=_var(), take=keys)
        except (ValueError, OSError) as exc:
            self.said.setText(f"Could not reset: {exc}")
            return
        self._tell(result["changed"])
        self._undo = self._undo_plan
        self.said.setText(f"Gave {len(keys)} of your changes back to the plan.")
        self.undo_button.setVisible(True)
        self.refresh()

    def have_it(self, item: str) -> None:
        """One tap: the player owns `item` (goals.owned, their word)."""
        before = str(self.settings.values.get("goals.owned") or "")
        names = [n.strip() for n in before.replace(";", ",").split(",") if n.strip()]
        if item.casefold() not in {n.casefold() for n in names}:
            self.settings.set_value("goals.owned", ", ".join(names + [item]))

        def back() -> tuple[str, list]:
            self.settings.set_value("goals.owned", before)     # tells everyone itself
            return f"OK, {item} is not marked as yours any more.", []
        self._undo = back
        self.said.setText(f"Marked {item} as yours. Hivemind moves on to the next thing.")
        self.undo_button.setVisible(True)
        self.refresh()

    def _changed(self, key: str, _value) -> None:
        if key in ("plan.goal", "plan.target"):
            self.show_choice()

    # ---- NOW / WHY / NEXT / GOAL / PROOF ---------------------------------
    def _status_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Note")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        self.lines: dict[str, QLabel] = {}
        for row, word in enumerate(("NOW", "WHY", "NEXT", "GOAL", "PROOF")):
            head = QLabel(word)
            head.setObjectName("Section")
            grid.addWidget(head, row, 0, Qt.AlignTop)
            if word == "NEXT":
                self.next_box = QVBoxLayout()
                self.next_box.setSpacing(4)
                grid.addLayout(self.next_box, row, 1)
                continue
            label = QLabel()
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText if word != "PROOF" else Qt.RichText)
            grid.addWidget(label, row, 1)
            self.lines[word] = label
        grid.setColumnStretch(1, 1)
        return card

    def refresh(self) -> None:
        """Re-read the bot's files (brain/plan.status). Never raises."""
        var_root = _var()
        try:
            from ...world.settings import Settings
            settings = Settings(_config())
            got = plan.status(var_root, settings, clock=self.clock)
            kept = {} if settings.get("plan.goal") in (None, plan.CUSTOM) else \
                plan.conflicts(_config(), var_root)
        except Exception as exc:       # a broken file never breaks the window
            got = {"now": "", "why": f"could not read the bot's files ({exc})",
                   "next": [], "goal": {}, "proof": []}
            kept = {}
        self.status = got
        self.lines["NOW"].setText(got["now"] or "Not started yet. Press Start (F1).")
        self.lines["WHY"].setText(got["why"] or "It says why after its first trip.")
        goal = got.get("goal") or {}
        aim = goal.get("label") or ""
        if goal.get("target") and goal.get("id") == "hybrid":
            aim += ": " + ", ".join(self.hybrid_checks[t].text() if t in self.hybrid_checks
                                    else t for t in plan.picks(goal["target"]))
        elif goal.get("target"):
            aim += f": {goal['target']}"
        hive = goal.get("hive")
        self.lines["GOAL"].setText(aim + (f" ({hive} hive)" if hive else ""))
        proof = got["proof"][:4]
        self.lines["PROOF"].setText("<br>".join(f"· {html.escape(str(p))}" for p in proof)
                                    or "Nothing done yet that it can show.")
        why = str(goal.get("hive_why") or "no read yet")
        self.hive_line.setText(f"Hive colour: {hive or 'not known yet'}. {why[:1].upper()}{why[1:]}.")
        self._show_next(got["next"])
        self.kept_line.setText(f"{len(kept)} of your own change{'' if len(kept) == 1 else 's'} kept"
                               if kept else "")
        self.kept_line.setToolTip("\n".join(
            f"{k}: yours {mine!r}, the plan's {theirs!r}" for k, (mine, theirs) in kept.items()))
        self.reset_button.setVisible(bool(kept))
        self.kept_line.setVisible(bool(kept))

    def _show_next(self, rows) -> None:
        while self.next_box.count():
            item = self.next_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)          # off the page now, freed later
                widget.deleteLater()
        if not rows:
            self.next_box.addWidget(_dim("Nothing to work toward yet."))
            return
        # YOUR OWN SETUP DOES ONLY WHAT ITS SWITCHES ALLOW: the next gear and
        # egg quests are bought and done by economy.buy and quests.enabled,
        # both off on a fresh install (data/presets/safe-first-run.yaml), so
        # listing them read as a promise (usability triage 2026-10-27 #3)
        values = self.settings.values
        if str(values.get("plan.goal") or plan.CUSTOM) in (plan.CUSTOM, "macro") \
                and not values.get("economy.buy") and not values.get("quests.enabled"):
            self.next_box.addWidget(_dim(
                "Nothing: buying and quests are off in your own setup. Pick a plan "
                "on the left and it works toward the next item."))
            return
        offered = False
        for row in rows[:5]:
            word, colour = STATE_LOOK.get(row.get("state"), STATE_LOOK["?"])
            line = QWidget()
            box = QHBoxLayout(line)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(8)
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {colour};")
            dot.setToolTip(word)
            box.addWidget(dot, 0, Qt.AlignTop)
            text = QLabel(str(row.get("what") or ""))
            text.setWordWrap(True)
            box.addWidget(text, 1)
            if row.get("item") and row.get("state") == "no" and not offered:
                offered = True
                button = QPushButton("I have it")
                button.setToolTip(f"Tell Hivemind you already own {row['item']}")
                button.clicked.connect(lambda _=False, i=row["item"]: self.have_it(i))
                box.addWidget(button, 0, Qt.AlignTop)
            self.next_box.addWidget(line)

    # live only while on screen
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.timer.stop()
