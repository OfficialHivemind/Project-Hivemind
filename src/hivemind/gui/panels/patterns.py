"""The PATTERN STUDIO (ROADMAP T17): make, preview, save and share gather
patterns. A viewer's ask, "like natro and other macros but better".

    +-------------+-------------------------------+----------------------+
    | YOUR        | name  author  size            |  [field v]           |
    |  zigzag     | 1. Move W 20 studs            |   +--------------+   |
    | BUILT-IN    | 2. Repeat 3x: A 6, S 20       |   |   path, start |   |
    |  Snake ...  | [W v][20][Add] [Turn L][R]... |   +--------------+   |
    | New Import  | OK · 98 studs a pass          |  Copy code           |
    +-------------+-------------------------------+----------------------+

Every check is world/userpatterns' -- this page only edits a dict and shows
what `validate` says about it. Built-in patterns are read-only; "Save a copy"
makes one of them yours.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                               QDialog, QDoubleSpinBox, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from .. import gameicons, theme
from ...act.patterns import FIELD_STUDS
from ...world import userpatterns as up

KEY_ARROWS = {"w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0)}


def step_text(step: dict) -> str:
    if "move" in step:
        return f"Move {step['move'].upper()}  {step['studs']:g} studs"
    if "turn" in step:
        return f"Turn camera {step['turn']}"
    inner = ", ".join(f"{s['move'].upper()} {s['studs']:g}" if "move" in s
                      else f"turn {s['turn']}" for s in step["steps"])
    return f"Repeat {step['repeat']}x:  {inner}"


def trace(pattern: dict) -> list[tuple[float, float]]:
    """The path in studs from the start (0, 0), x right, y down (W is up).
    A camera turn rotates every later move 45 degrees, as in the game."""
    x = y = 0.0
    heading = 0.0
    points = [(x, y)]
    size = float(pattern.get("size", 1.0))
    for leg in up.legs(pattern):
        if "turn" in leg:
            heading += math.pi / 4 * (-1 if leg["turn"] == "left" else 1)
            continue
        dx = sum(KEY_ARROWS[k][0] for k in leg["move"])
        dy = sum(KEY_ARROWS[k][1] for k in leg["move"])
        norm = math.hypot(dx, dy) or 1.0
        dx, dy = dx / norm, dy / norm
        c, s = math.cos(heading), math.sin(heading)
        dist = leg["studs"] * size
        x += (dx * c - dy * s) * dist
        y += (dx * s + dy * c) * dist
        points.append((x, y))
    return points


class PatternPreview(QWidget):
    """Top-down: the field, the path, where it starts, which way it goes, and
    the line back to the start that the next pass walks from."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.pattern: dict | None = None
        self.field = ""

    def show_pattern(self, pattern: dict | None, field: str = "") -> None:
        self.pattern, self.field = pattern, field
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.S_PANEL))
        try:
            points = trace(self.pattern) if self.pattern else [(0.0, 0.0)]
        except (KeyError, TypeError, ValueError):     # a half-made step
            points = [(0.0, 0.0)]
        half = FIELD_STUDS / 2
        reach = max([half] + [max(abs(x), abs(y)) for x, y in points]) * 1.08
        side = min(self.width(), self.height()) - 24
        scale = side / (2 * reach)
        cx, cy = self.width() / 2, self.height() / 2

        def at(x, y):
            return QPointF(cx + x * scale, cy + y * scale)

        # THE FIELD: the act/patterns estimate, square, centred on the start
        field = QRectF(at(-half, -half), at(half, half))
        p.setPen(QPen(QColor(theme.S_LINE), 1))
        p.setBrush(QColor(theme.S_CARD))
        p.drawRoundedRect(field, 6, 6)
        p.setPen(QPen(QColor(theme.S_LINE), 1, Qt.DotLine))
        for k in range(-3, 4):
            v = k * FIELD_STUDS / 8
            p.drawLine(at(v, -half), at(v, half))
            p.drawLine(at(-half, v), at(half, v))
        if self.field:
            p.drawPixmap(8, 8, gameicons.pixmap("fields", self.field, 28))
        p.setPen(QColor(theme.S_DIM))
        p.drawText(self.rect().adjusted(8, 4, -8, -4), Qt.AlignBottom | Qt.AlignLeft,
                   f"{self.field or 'Field'} ~{FIELD_STUDS:.0f} studs (estimate) · W is up")
        if len(points) < 2:
            return
        # THE LOOP: from the end back to the start, dashed
        p.setPen(QPen(QColor(theme.S_FAINT), 1.5, Qt.DashLine))
        p.drawLine(at(*points[-1]), at(*points[0]))
        path = QPainterPath(at(*points[0]))
        for pt in points[1:]:
            path.lineTo(at(*pt))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(theme.S_AMBER), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        # DIRECTION: an arrowhead at the middle of every leg
        p.setBrush(QColor(theme.S_AMBER))
        p.setPen(Qt.NoPen)
        for a, b in zip(points, points[1:]):
            ax, ay, bx, by = *a, *b
            if math.hypot(bx - ax, by - ay) * scale < 14:
                continue
            ang = math.atan2(by - ay, bx - ax)
            mid = at((ax + bx) / 2, (ay + by) / 2)
            tip = QPointF(mid.x() + 6 * math.cos(ang), mid.y() + 6 * math.sin(ang))
            left = QPointF(mid.x() + 6 * math.cos(ang + 2.5), mid.y() + 6 * math.sin(ang + 2.5))
            right = QPointF(mid.x() + 6 * math.cos(ang - 2.5), mid.y() + 6 * math.sin(ang - 2.5))
            p.drawPolygon(QPolygonF([tip, left, right]))
        # START: a green dot
        p.setBrush(QColor(theme.S_GOOD))
        p.setPen(QPen(QColor(theme.S_BG), 2))
        p.drawEllipse(at(*points[0]), 6, 6)


class ImportDialog(QDialog):
    """Paste a code: it is decoded and checked as you type, previewed, and
    saved only when it passes."""

    def __init__(self, parent=None, field: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Import a pattern code")
        self.pattern: dict | None = None
        box = QVBoxLayout(self)
        self.code = QPlainTextEdit()
        self.code.setPlaceholderText("Paste a code that starts with HMP1:")
        self.code.setFixedHeight(70)
        self.preview = PatternPreview()
        self.verdict = QLabel("Paste a code.")
        self.verdict.setWordWrap(True)
        self.save_button = QPushButton("Save to my patterns")
        self.save_button.setObjectName("Primary")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        box.addWidget(self.code)
        box.addWidget(self.preview, 1)
        box.addWidget(self.verdict)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(self.save_button)
        box.addLayout(row)
        self._field = field
        self.code.textChanged.connect(lambda: self.check(self.code.toPlainText()))
        self.resize(460, 560)

    def check(self, text: str) -> up.Checked | None:
        self.pattern = None
        try:
            checked = up.decode(text)
        except up.InvalidCode as exc:
            self.verdict.setText(f"<span style='color:{theme.S_BAD}'>{exc}</span>"
                                 if text.strip() else "Paste a code.")
            self.preview.show_pattern(None, self._field)
            self.save_button.setEnabled(False)
            return None
        self.pattern = checked.pattern
        self.preview.show_pattern(checked.pattern, self._field)
        self.verdict.setText(verdict_html(checked))
        self.save_button.setEnabled(checked.ok)
        return checked


def verdict_html(checked: up.Checked) -> str:
    if not checked.ok:
        return (f"<span style='color:{theme.S_BAD}'>Not valid:</span> "
                + "<br>".join(map(_esc, checked.errors)))
    p = checked.pattern
    said = (f"<span style='color:{theme.S_GOOD}'>Valid</span> · <b>{_esc(p['name'])}</b>"
            + (f" by {_esc(p['author'])}" if p["author"] else "")
            + f" · v{p['version']} · {len(up.legs(p))} legs · {up.studs(p):,.0f} studs a pass")
    if checked.notes:
        said += "<br><span style='color:%s'>%s</span>" % (theme.S_DIM, "<br>".join(map(_esc, checked.notes)))
    return said


def _esc(text) -> str:
    import html
    return html.escape(str(text))


class PatternStudio(QWidget):
    """The page. `folder` is where user patterns live (the shell passes the
    one beside settings.yaml); `saved` fires after a save or a delete, so
    the macro field list can offer the new set."""

    saved = Signal()

    def __init__(self, folder=None, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.builtin = up.builtins()
        self.mine: dict[str, dict] = {}
        self.current: dict = self._blank()
        self.read_only = False
        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 16)
        outer.setSpacing(14)

        # ---- the list -----------------------------------------------------
        left = QVBoxLayout()
        title = QLabel("PATTERNS")
        title.setObjectName("Section")
        left.addWidget(title)
        self.list = QListWidget()
        self.list.setFixedWidth(210)
        self.list.currentItemChanged.connect(self._picked)
        left.addWidget(self.list, 1)
        buttons = QGridLayout()
        self.new_button = QPushButton("New")
        self.new_button.clicked.connect(self.new)
        self.import_button = QPushButton("Import code")
        self.import_button.clicked.connect(self.open_import)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete)
        self.record_button = QPushButton("Record")
        self.record_button.setEnabled(False)
        self.record_button.setToolTip("Recording a pattern from your own walk is "
                                      "coming. Draw it with the steps for now.")
        # NOT SHOWN UNTIL IT WORKS (UI panel item 12: a dead control)
        self.record_button.setVisible(False)
        for i, b in enumerate((self.new_button, self.import_button, self.delete_button)):
            buttons.addWidget(b, 0, i)
        left.addLayout(buttons)
        outer.addLayout(left)

        # ---- the editor -----------------------------------------------------
        mid = QVBoxLayout()
        meta = QGridLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(up.MAX_NAME)
        self.author = QLineEdit()
        self.author.setMaxLength(up.MAX_AUTHOR)
        self.author.setPlaceholderText("you (optional)")
        self.size = QDoubleSpinBox()
        self.size.setRange(up.MIN_SIZE, up.MAX_SIZE)
        self.size.setSingleStep(0.25)
        self.size.setPrefix("x")
        self.size.setToolTip("Every move's studs times this: a bigger or smaller "
                             "copy of the same shape.")
        self.version = QSpinBox()
        self.version.setRange(1, up.MAX_VERSION)
        self.version.setPrefix("v")
        for box in (self.size, self.version):
            box.setObjectName("Num")
        for n, (label, w) in enumerate((("Name", self.name), ("Author", self.author),
                                        ("Size", self.size), ("Version", self.version))):
            meta.addWidget(QLabel(label), n // 2, (n % 2) * 2)
            meta.addWidget(w, n // 2, (n % 2) * 2 + 1)
        mid.addLayout(meta)
        self.name.textEdited.connect(lambda t: self._meta("name", t))
        self.author.textEdited.connect(lambda t: self._meta("author", t))
        self.size.valueChanged.connect(lambda v: self._meta("size", round(v, 3)))
        self.version.valueChanged.connect(lambda v: self._meta("version", int(v)))

        steps_title = QLabel("STEPS (ONE PASS; IT LOOPS)")
        steps_title.setObjectName("Section")
        mid.addWidget(steps_title)
        self.steps = QListWidget()
        self.steps.setSelectionMode(QAbstractItemView.ContiguousSelection)
        self.steps.itemSelectionChanged.connect(self._step_picked)
        mid.addWidget(self.steps, 1)

        add = QHBoxLayout()
        self.key = QComboBox()
        for k in up.MOVE_KEYS:
            self.key.addItem(k.upper(), k)
        self.studs = QDoubleSpinBox()
        self.studs.setRange(up.MIN_STUDS_STEP, up.MAX_STUDS_STEP)
        self.studs.setValue(20.0)
        self.studs.setSuffix(" studs")
        self.studs.setObjectName("Num")
        self.add_move = QPushButton("Add move")
        self.add_move.setObjectName("Primary")
        self.add_move.clicked.connect(lambda: self.add_step(
            {"move": self.key.currentData(), "studs": round(self.studs.value(), 2)}))
        self.turn_left = QPushButton("Turn left")
        self.turn_left.clicked.connect(lambda: self.add_step({"turn": "left"}))
        self.turn_right = QPushButton("Turn right")
        self.turn_right.clicked.connect(lambda: self.add_step({"turn": "right"}))
        for w in (self.key, self.studs, self.add_move, self.turn_left, self.turn_right):
            add.addWidget(w)
        mid.addLayout(add)
        self.key.currentIndexChanged.connect(lambda _=0: self._edit_move())
        self.studs.valueChanged.connect(lambda _=0: self._edit_move())

        tools = QHBoxLayout()
        self.times = QSpinBox()
        self.times.setRange(2, up.MAX_REPEAT)
        self.times.setValue(3)
        self.times.setPrefix("x")
        self.times.setObjectName("Num")
        self.repeat_button = QPushButton("Repeat")
        self.repeat_button.setToolTip("Group the selected steps into a repeat")
        self.repeat_button.clicked.connect(self.group)
        self.ungroup_button = QPushButton("Ungroup")
        self.ungroup_button.clicked.connect(self.ungroup)
        self.up_button = QPushButton("Up")
        self.up_button.clicked.connect(lambda: self.move_step(-1))
        self.down_button = QPushButton("Down")
        self.down_button.clicked.connect(lambda: self.move_step(1))
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_step)
        self.times.valueChanged.connect(lambda _=0: self._edit_repeat())
        # TWO ROWS OF THREE: six in one row overlapped by 4 px at 1280 px and
        # 150% scale (render probe, UI panel round 2, 2026-10-22)
        order = QHBoxLayout()
        for w in (self.times, self.repeat_button, self.ungroup_button):
            tools.addWidget(w)
        for w in (self.up_button, self.down_button, self.remove_button):
            order.addWidget(w)
        tools.addStretch(1)
        order.addStretch(1)
        # the number boxes were 3-4 px short of their text (same probe)
        self.times.setMinimumWidth(80)
        self.studs.setMinimumWidth(100)
        # NEVER SQUEEZED PAST THEIR WORDS ("Jngroup", "Add mov" at 1280 px)
        for b in (self.add_move, self.turn_left, self.turn_right, self.repeat_button,
                  self.ungroup_button, self.up_button, self.down_button, self.remove_button):
            # measured in bold, plus the theme's 14 px padding a side: the size
            # hint here is taken before the stylesheet's padding applies
            bold = QFont(b.font())
            bold.setBold(True)
            b.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(b.text()) + 36)
        mid.addLayout(tools)
        mid.addLayout(order)

        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.verdict.setTextFormat(Qt.RichText)
        mid.addWidget(self.verdict)
        actions = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self.save)
        self.copy_button = QPushButton("Copy share code")
        self.copy_button.clicked.connect(self.copy_code)
        self.said = QLabel()
        self.said.setObjectName("Dim")
        self.said.setWordWrap(True)
        actions.addWidget(self.save_button)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.said, 1)
        mid.addLayout(actions)
        outer.addLayout(mid, 3)

        # ---- the preview ------------------------------------------------------
        right = QVBoxLayout()
        self.field = QComboBox()
        for _, fields in gameicons.field_zones():
            for name in fields:
                self.field.addItem(gameicons.icon("fields", name, 20), name)
        self.field.currentTextChanged.connect(lambda _: self.refresh())
        right.addWidget(self.field)
        self.preview = PatternPreview()
        right.addWidget(self.preview, 1)
        hint = QLabel("Green dot: where it starts (the field's spot). Arrows: "
                      "which way each leg walks. Dashed: back to the start, "
                      "where the next pass begins.")
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        right.addWidget(hint)
        outer.addLayout(right, 3)
        self.reload()

    # ---- the list ---------------------------------------------------------
    @staticmethod
    def _blank() -> dict:
        return {"name": "My pattern", "author": "", "version": 1, "size": 1.0,
                "steps": [{"move": "w", "studs": 20.0}, {"move": "a", "studs": 8.0},
                          {"move": "s", "studs": 20.0}, {"move": "d", "studs": 8.0}]}

    def reload(self, select: str | None = None) -> None:
        self.mine = up.load_user(self.folder)
        self.list.blockSignals(True)
        self.list.clear()
        self._heading("YOUR PATTERNS" if self.mine else "YOUR PATTERNS (none yet)")
        for key, p in self.mine.items():
            item = QListWidgetItem(p["name"])
            item.setData(Qt.UserRole, ("mine", key))
            self.list.addItem(item)
        self._heading("BUILT-IN (READ-ONLY)")
        for i, p in enumerate(self.builtin):
            field = p["name"].removeprefix("Classic ").removesuffix(" Field")
            item = QListWidgetItem(p["name"])
            if gameicons.has("fields", field):
                item.setIcon(gameicons.icon("fields", field, 20))
            item.setData(Qt.UserRole, ("builtin", i))
            self.list.addItem(item)
        self.list.blockSignals(False)
        for row in range(self.list.count()):
            data = self.list.item(row).data(Qt.UserRole)
            if data and (select is None or data == ("mine", select)):
                self.list.setCurrentRow(row)
                return
        self.show_editing(self._blank(), False)

    def _heading(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)
        font = item.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 0.85)
        item.setFont(font)
        item.setForeground(QColor(theme.S_AMBER))
        self.list.addItem(item)

    def _picked(self, item, _old=None) -> None:
        data = item.data(Qt.UserRole) if item is not None else None
        if not data:
            return
        kind, key = data
        if kind == "mine":
            self.show_editing(dict(self.mine[key]), False)
        else:
            p = {k: v for k, v in self.builtin[key].items() if k != "route"}
            self.show_editing(p, True)
            field = p["name"].removeprefix("Classic ").removesuffix(" Field")
            if self.field.findText(field) >= 0:
                self.field.setCurrentText(field)

    def show_editing(self, pattern: dict, read_only: bool) -> None:
        self.current = {k: (list(v) if k == "steps" else v) for k, v in pattern.items()}
        self.read_only = read_only
        for w, v in ((self.name, pattern.get("name", "")), (self.author, pattern.get("author", ""))):
            w.blockSignals(True)
            w.setText(str(v))
            w.blockSignals(False)
        for w, v in ((self.size, float(pattern.get("size", 1.0))),
                     (self.version, int(pattern.get("version", 1)))):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        for w in (self.name, self.author, self.size, self.version, self.steps,
                  self.key, self.studs, self.add_move, self.turn_left, self.turn_right,
                  self.times, self.repeat_button, self.ungroup_button, self.up_button,
                  self.down_button, self.remove_button):
            w.setEnabled(not read_only)
        self.save_button.setText("Save a copy" if read_only else "Save")
        self.delete_button.setEnabled(not read_only and up.slug(pattern.get("name", "")) in self.mine)
        self._fill_steps()

    # ---- editing ----------------------------------------------------------
    def _fill_steps(self, select: list[int] | None = None) -> None:
        self.steps.blockSignals(True)
        self.steps.clear()
        for n, step in enumerate(self.current["steps"], 1):
            self.steps.addItem(f"{n}.  {step_text(step)}")
        for i in select or []:
            if 0 <= i < self.steps.count():
                self.steps.item(i).setSelected(True)
                self.steps.setCurrentRow(i)
        self.steps.blockSignals(False)
        self.refresh()

    def selected(self) -> list[int]:
        return sorted(self.steps.row(i) for i in self.steps.selectedItems())

    def _meta(self, key: str, value) -> None:
        self.current[key] = value
        self.refresh()

    def add_step(self, step: dict) -> None:
        rows = self.selected()
        at = rows[-1] + 1 if rows else len(self.current["steps"])
        self.current["steps"].insert(at, step)
        self._fill_steps([at])

    def _step_picked(self) -> None:
        rows = self.selected()
        if len(rows) != 1:
            return
        step = self.current["steps"][rows[0]]
        if "move" in step:
            for w, v in ((self.key, self.key.findData(step["move"])), (self.studs, step["studs"])):
                w.blockSignals(True)
                (w.setCurrentIndex if w is self.key else w.setValue)(v)
                w.blockSignals(False)
        elif "repeat" in step:
            self.times.blockSignals(True)
            self.times.setValue(step["repeat"])
            self.times.blockSignals(False)

    def _edit_move(self) -> None:
        """A move row picked: the key and studs boxes edit it in place."""
        rows = self.selected()
        if len(rows) == 1 and "move" in self.current["steps"][rows[0]]:
            self.current["steps"][rows[0]] = {"move": self.key.currentData(),
                                              "studs": round(self.studs.value(), 2)}
            self._fill_steps(rows)

    def _edit_repeat(self) -> None:
        rows = self.selected()
        if len(rows) == 1 and "repeat" in self.current["steps"][rows[0]]:
            self.current["steps"][rows[0]]["repeat"] = int(self.times.value())
            self._fill_steps(rows)

    def group(self) -> None:
        rows = self.selected()
        chosen = [self.current["steps"][i] for i in rows]
        if not chosen or any("repeat" in s for s in chosen):
            self.said.setText("Pick moves and turns (not a repeat) to repeat.")
            return
        steps = self.current["steps"]
        steps[rows[0]:rows[-1] + 1] = [{"repeat": int(self.times.value()),
                                        "steps": [dict(s) for s in chosen]}]
        self._fill_steps([rows[0]])

    def ungroup(self) -> None:
        rows = self.selected()
        if len(rows) == 1 and "repeat" in self.current["steps"][rows[0]]:
            inner = self.current["steps"][rows[0]]["steps"]
            self.current["steps"][rows[0]:rows[0] + 1] = [dict(s) for s in inner]
            self._fill_steps(list(range(rows[0], rows[0] + len(inner))))

    def move_step(self, by: int) -> None:
        rows = self.selected()
        steps = self.current["steps"]
        if not rows or rows[0] + by < 0 or rows[-1] + by >= len(steps):
            return
        block = steps[rows[0]:rows[-1] + 1]
        del steps[rows[0]:rows[-1] + 1]
        steps[rows[0] + by:rows[0] + by] = block
        self._fill_steps([i + by for i in rows])

    def remove_step(self) -> None:
        rows = self.selected()
        for i in reversed(rows):
            del self.current["steps"][i]
        self._fill_steps([min(rows[0], len(self.current["steps"]) - 1)] if rows else [])

    # ---- check, preview, save, share -------------------------------------
    def check(self) -> up.Checked:
        return up.validate(self.current)

    def refresh(self) -> up.Checked:
        checked = self.check()
        self.verdict.setText(verdict_html(checked))
        self.copy_button.setEnabled(checked.ok)
        self.save_button.setEnabled(checked.ok)
        self.preview.show_pattern(checked.pattern or self._drawable(), self.field.currentText())
        return checked

    def _drawable(self) -> dict | None:
        """An invalid pattern is still drawn, as far as its steps can be."""
        try:
            steps = [s for s in self.current["steps"]
                     if "turn" in s or ("move" in s and s["move"] in up.MOVE_KEYS)
                     or ("repeat" in s)]
            return {"size": float(self.current.get("size", 1.0)), "steps": steps}
        except Exception:
            return None

    def new(self) -> None:
        self.list.clearSelection()
        self.show_editing(self._blank(), False)

    def save(self) -> bool:
        if self.read_only:
            self.current["name"] = self.current["name"].removeprefix("Classic ") + " (copy)"
            self.current["author"] = ""
        checked = self.check()
        if not checked.ok:
            self.said.setText("Not saved: " + "; ".join(checked.errors))
            return False
        path = up.save(checked.pattern, self.folder)
        self.reload(select=up.slug(checked.pattern["name"]))
        self.said.setText(f"Saved as {path.name}. Pick it in a macro field's "
                          "Pattern box to walk it.")
        self.saved.emit()
        return True

    def delete(self) -> None:
        name = self.current.get("name", "")
        if self.read_only or up.slug(name) not in self.mine:
            return
        up.delete(name, self.folder)
        self.reload()
        self.said.setText(f"Deleted {name}.")
        self.saved.emit()

    def share_code(self) -> str | None:
        checked = self.check()
        return up.encode(checked.pattern) if checked.ok else None

    def copy_code(self) -> None:
        code = self.share_code()
        if code:
            QApplication.clipboard().setText(code)
            self.said.setText(f"Copied ({len(code)} characters). Paste it in the "
                              "Discord configs or hive-presets forum.")

    def open_import(self) -> ImportDialog:
        self.import_dialog = ImportDialog(self, self.field.currentText())
        self.import_dialog.accepted.connect(lambda: self._imported(self.import_dialog.pattern))
        self.import_dialog.open()
        return self.import_dialog

    def _imported(self, pattern: dict | None) -> None:
        if pattern:
            mine = self.mine.get(up.slug(pattern["name"]))
            if mine is not None and mine != pattern:      # never over one of yours
                pattern = {**pattern, "name": pattern["name"][:up.MAX_NAME - 11] + " (imported)"}
            path = up.save(pattern, self.folder)
            self.reload(select=up.slug(pattern["name"]))
            self.said.setText(f"Imported {pattern['name']} ({path.name}).")
            self.saved.emit()
