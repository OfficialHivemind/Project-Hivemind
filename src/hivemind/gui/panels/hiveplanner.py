"""The hive planner (ROADMAP H13, the owner's idea): the hive's 50 slots as
hexes, the bee wanted in each, and how many match. Click a hex to pick its bee.

PRESETS (ROADMAP H17): the Presets menu fills the plan from a built-in
starter (brain/hivepresets, Blue / Red / White per stage) or a pasted HMH1
share code, previewed first and applied only after a confirm; "Copy share
code" puts this plan on the clipboard for the Discord hive-presets forum.

When the bot has read the hive cell by cell (var/hive_slots.json, brain/
hiveplanner.load_read) each hex shows the bee really in that slot and matches
by it. Otherwise the bee menu's COUNTS place the bees by type: each planned
slot the hive holds that bee for shows it (green ring), the rest fill the
other open slots in name order. The note under the grid says which.
"""
from __future__ import annotations

import json
import math
from collections import Counter

import yaml
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QSizePolicy, QToolTip, QVBoxLayout, QWidget)

from ...brain import hiveplanner as hp
from ...brain import hivepresets
from ...brain.hivejudge import stage_for
from ...datapaths import data, var
from ...world.settings import Settings
from .. import theme
from ..widgets import Card

COLS, ROWS, R = 5, 10, 32                 # 5 wide, 10 high: the game's hive
FILL = {"blue": "#2f5f9e", "red": "#9e3434", "colourless": "#cfc6b4"}
CLEAR = "— clear —"
FOLLOW = "hive.follow_plan"
GRIND_SLOT = "hive.grind_slot"            # ROADMAP H16, brain/grinder
_FACES: dict = {}


def face(bee) -> QPixmap | None:
    """The bee's icon (data/bee_faces/<type>.png, scripts/fetch_bee_faces.py);
    None when there is none -- the hex keeps its colour and name."""
    if not bee:
        return None
    if bee not in _FACES:
        pix = QPixmap(str(data("bee_faces", f"{bee}.png")))
        _FACES[bee] = None if pix.isNull() else pix
    return _FACES[bee]


# THE GAME'S CELLS ARE WIDER THAN A REGULAR HEXAGON. MEASURED 2026-10-06
# (vision/hivecell): the columns 55.5 px apart, the cells 53.5 px apart down a
# column -- nested like a honeycomb, so a cell is 4/3 x 55.5 = 74 px wide and
# 53.5 tall, where a regular one would be 62 wide. Drawn regular, the hive
# came out tall and narrow (the owner, 2026-10-26: a full hive's hexagons
# are a different shape). So the height stays R's and the width
# is RX's.
COL_PER_ROW = 55.5 / 53.5
RX = R * COL_PER_ROW * math.sqrt(3) / 1.5     # a cell's half-width (R = 32 -> 38.3)


def _centre(slot: int) -> QPointF:
    """Slot 1 bottom-left, filling each row left to right, upward, numbered as
    brain/hiveplanner and vision/hivecell.slot_point number it.

    THE 1ST, 3RD AND 5TH COLUMNS SIT HALF A CELL LOWER: three cells along the
    bottom, two along the top. The owner, 2026-10-26: three at the bottom,
    not two, and the wiki's Hive picture (the 2024-01-12 design) shows it. This
    drew the 2nd and 4th lower, after vision/hivecell's ODD_DROP."""
    i = slot - 1
    col, row = i % COLS, ROWS - 1 - i // COLS
    h = math.sqrt(3) * R
    return QPointF(RX + 4 + col * 1.5 * RX,
                   h / 2 + 4 + row * h + (h / 2 if col % 2 == 0 else 0))


def _hexagon(c: QPointF, r: float) -> QPolygonF:
    """A flat-topped cell, `r` tall from its centre to a point, widened to the
    game's proportions (RX / R)."""
    wide = r * RX / R
    return QPolygonF([QPointF(c.x() + wide * math.cos(math.radians(60 * k)),
                              c.y() + r * math.sin(math.radians(60 * k))) for k in range(6)])


class HiveGrid(QWidget):
    def __init__(self, panel):
        super().__init__()
        self._panel = panel
        self.setMouseTracking(True)
        self.setFixedSize(int(RX * 2 + (COLS - 1) * 1.5 * RX + 8),
                          int(math.sqrt(3) * R * (ROWS + 0.5) + 8))

    def slot_at(self, p) -> int | None:
        for slot in range(1, hp.SLOTS + 1):
            c = _centre(slot)
            if ((p.x() - c.x()) * R / RX) ** 2 + (p.y() - c.y()) ** 2 < (R * 0.87) ** 2:
                return slot
        return None

    def paintEvent(self, _event) -> None:
        pn = self._panel
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        small = QFont(theme.SANS.split(",")[0], 7, QFont.DemiBold)
        for slot in range(1, hp.SLOTS + 1):
            c, now, want = _centre(slot), pn.shown.get(slot), pn.slots.get(slot)
            locked = pn.total is not None and slot > pn.total
            unknown = theme.HEX_UNKNOWN          # read now: the shell recolours theme
            colour = (theme.BG_PANEL if locked else unknown if now is None
                      else FILL.get(pn.colour(now), unknown))
            p.setBrush(QColor(colour))
            edge = (theme.GOOD if pn.matched.get(slot) else theme.WARN) if want else theme.BORDER
            pen = QPen(QColor(edge), 3 if want else 1)
            if locked and not want:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawPolygon(_hexagon(c, R - 2))
            p.setFont(small)
            ink = "#1b1409" if colour == FILL["colourless"] else theme.TEXT
            p.setPen(QColor(ink if now else theme.TEXT_FAINT))
            todo = want and not pn.matched.get(slot)
            pix = face(now) or (None if now else face(want))
            if pix is not None:           # the face, clipped to the hex; the name small under
                clip = QPainterPath()
                clip.addPolygon(_hexagon(c, R - 3))
                p.save()
                p.setClipPath(clip)
                p.setOpacity(1.0 if now else 0.35)
                side = R * 1.45
                p.drawPixmap(QRectF(c.x() - side / 2, c.y() - side / 2 - 5, side, side),
                             pix, QRectF(pix.rect()))
                p.restore()
                # the name under the face is ALWAYS the bee in the slot (the
                # owner, 2026-10-15: the names did not match the images -- a
                # to-do slot used to show only "-> wanted" under the face of
                # the bee that is there now)
                p.drawText(QRectF(c.x() - R, c.y() + R * 0.42, 2 * R, 11), Qt.AlignCenter,
                           (now or want or "")[:9])
            else:
                box = QRectF(c.x() - R, c.y() - (13 if todo else 6), 2 * R, 12)
                p.drawText(box, Qt.AlignCenter, (now or ("" if locked else "?"))[:8])
            if todo and now:              # the WANTED bee: a small face badge, top right
                wpix = face(want)
                b = R * 0.62
                badge = QRectF(c.x() + R * 0.18, c.y() - R * 0.92, b, b)
                p.setPen(QPen(QColor(theme.WARN), 2))
                p.setBrush(QColor(theme.BG))
                p.drawEllipse(badge)
                if wpix is not None:
                    p.drawPixmap(badge.adjusted(2, 2, -2, -2), wpix, QRectF(wpix.rect()))
                else:
                    p.setPen(QColor(theme.WARN))
                    p.drawText(badge, Qt.AlignCenter, "→" + want[:2])
        p.end()

    def mouseMoveEvent(self, event) -> None:
        slot = self.slot_at(event.position())
        if slot is None:
            QToolTip.hideText()
            return
        pn = self._panel
        want = pn.slots.get(slot)
        text = (f"slot {slot}: {pn.label(pn.shown.get(slot)) if pn.shown.get(slot) else 'unknown'}"
                + (f"\nwanted: {pn.label(want)} — {'matches' if pn.matched.get(slot) else 'to do'}"
                   if want else "\nno bee planned — click to plan one"))
        QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def mousePressEvent(self, event) -> None:
        slot = self.slot_at(event.position())
        if slot is not None:
            self._panel.pick(slot)


NO_PLAN = "Optional. No plan yet: pick a preset or press Fill from guide plan."


class HivePlannerPanel(Card):
    """The owner's hive plan, saved to var/hive_plan.json for the jelly errand."""

    def __init__(self, hive=lambda: "blue", set_follow=None, set_grind=None, parent=None):
        super().__init__("hive planner", "the bee you want in each slot — Royal Jelly follows it",
                         parent)
        self._hive = hive
        self.path = var(hp.PLAN_FILE)
        self.types = (yaml.safe_load(data("knowledge", "bee_types.yaml").read_text()) or {}).get("types") or {}
        self.slots, self.have, self.total = hp.load(self.path), {}, None
        self.shown, self.matched = {}, {}
        row = QHBoxLayout()
        self.grid = HiveGrid(self)
        # SCROLLS WHEN SHORT: the 588 px hive was cut off at 768 px tall (7 of
        # 8 readers, UI panel round 2, 2026-10-22)
        # ponytail: a scroll, not a scale-to-fit; scale R in resizeEvent if
        # seeing the whole hive at once on small screens matters
        holder = QScrollArea()
        holder.setWidget(self.grid)
        holder.setFrameShape(QScrollArea.NoFrame)
        holder.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder.setStyleSheet("background: transparent;")
        holder.setFixedWidth(self.grid.width() + holder.verticalScrollBar().sizeHint().width() + 2)
        holder.setMaximumHeight(self.grid.height() + 2)
        row.addWidget(holder)
        side = QVBoxLayout()
        # THE OWNER'S SWITCH (setting hive.follow_plan): saved through the
        # window's settings panel, which tells the bot to re-read the file
        self._set_follow = set_follow or (lambda v: None)
        self._set_grind = set_grind or (lambda slot: None)
        self.follow = QCheckBox("Royal Jelly follows this plan")
        self.follow.setToolTip("On: Royal Jelly follows the Hive Planner. Off: the planner is "
                               "only a picture; the bot uses its own guide.")
        self.follow.toggled.connect(lambda v: self._set_follow(bool(v)))
        side.addWidget(self.follow)
        why = QLabel("Off: the bot uses its own guide.")   # said, not only hovered
        why.setObjectName("Dim")
        why.setWordWrap(True)
        side.addWidget(why)
        self._progress = QLabel("")
        self._progress.setObjectName("Hero")
        self._progress.setWordWrap(True)
        side.addWidget(self._progress)
        # PRESETS (ROADMAP H17): starters, share codes
        self.presets_button = QPushButton("Presets")
        menu = QMenu(self.presets_button)
        menu.addAction("Starter presets…", self.open_starters)
        menu.addAction("Import share code…", self.open_import)
        menu.addAction("Copy share code", self.copy_code)
        self.presets_button.setMenu(menu)
        side.addWidget(self.presets_button)
        for text, slot in (("Fill from guide plan", self.fill), ("Clear plan", self.clear_all)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            side.addWidget(b)
        legend = QLabel(
            f"<span style='color:{FILL['blue']}'>■</span> blue  "
            f"<span style='color:{FILL['red']}'>■</span> red  "
            f"<span style='color:{FILL['colourless']}'>■</span> white  "
            f"<span style='color:{theme.HEX_UNKNOWN}'>■</span> unknown<br>"
            f"<span style='color:{theme.GOOD}'>⬡</span> matches  "
            f"<span style='color:{theme.WARN}'>⬡</span> to do (corner badge = the bee wanted)")
        legend.setTextFormat(Qt.RichText)
        side.addWidget(legend)
        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        side.addWidget(self._note)
        side.addStretch(1)
        row.addLayout(side, 1)
        self.add_layout(row)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.refresh()

    def label(self, bee) -> str:
        return str((self.types.get(bee) or {}).get("label") or bee)

    def colour(self, bee) -> str:
        return str((self.types.get(bee) or {}).get("colour") or "")

    def refresh(self) -> None:
        """Re-read the bot's last bee read (var/bees.json) and redraw."""
        self.follow.blockSignals(True)
        self.follow.setChecked(Settings().bool(FOLLOW))
        self.follow.blockSignals(False)
        try:
            body = json.loads(var("bees.json").read_text())
            self.have = {k: int(v) for k, v in (body.get("bees") or {}).items()}
            self.total = int(body.get("total") or sum(self.have.values()))
        except (OSError, ValueError, TypeError):
            self.have, self.total = {}, None
        read, _gifted = hp.load_read(var(hp.SLOTS_FILE), self.have if self.total else None)
        if read:
            self.shown, self.matched = dict(read), hp.match_slots(self.slots, read)
        else:
            self.matched = hp.match(self.slots, self.have)
            # place the bees by type: matched slots first, the rest in name order
            self.shown = {s: self.slots[s] for s, ok in self.matched.items() if ok}
        rest = Counter() if read else Counter(self.have) - Counter(self.shown.values())
        free = (s for s in range(1, (self.total or 0) + 1) if s not in self.shown)
        for bee in sorted(rest.elements()):
            slot = next(free, None)
            if slot is None:
                break
            self.shown[slot] = bee
        n = len(self.slots)
        # A NEXT STEP, NOT A BIG ORANGE "no plan yet" (UI panel round 2, 2026-10-22)
        self._progress.setText(f"{sum(self.matched.values())} of {n} slots match" if n
                               else NO_PLAN)
        self._progress.setStyleSheet("" if n else
                                     f"color: {theme.TEXT_DIM}; font-size: 13px; font-weight: 400;")
        said = "no bee read yet" if self.total is None else f"{self.total} bees read"
        self._note.setText(
            f"{said}. Each slot read off its bee card ({len(read)} read): Royal Jelly goes "
            f"on exactly the slots whose bee is not the planned one (never a gifted one)."
            if read else
            f"{said}. The bee menu counts bees but does not say which slot each is in, so "
            f"bees are drawn on the slots they match first (until the bot reads the hive "
            f"slot by slot). Royal Jelly goes only on bees you have more of than planned.")
        self.grid.update()

    def _save(self) -> None:
        hp.save(self.path, self.slots)
        self.refresh()

    def pick(self, slot: int) -> None:
        now = self.slots.get(slot)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Hive planner: bee wanted in slot {slot}")
        lst = QListWidget()
        lst.setIconSize(QSize(36, 36))
        lst.addItem(CLEAR)
        for bee in sorted(self.types, key=self.label):
            item = QListWidgetItem(self.label(bee))
            item.setData(Qt.UserRole, bee)
            pix = face(bee)
            if pix is not None:
                item.setIcon(QIcon(pix))
            lst.addItem(item)
            if bee == now:
                lst.setCurrentItem(item)
        if lst.currentItem() is None:
            lst.setCurrentRow(0)
        # THE GIFTED BASIC GRINDER'S SLOT (ROADMAP H16): ticked, this slot is
        # the one it grinds in (setting hive.grind_slot); its switch is on the
        # AI PROGRESS tab. Choosing it again re-arms a grinder that stopped.
        grind_now = Settings().int(GRIND_SLOT) == slot
        grind = QCheckBox("Grind a gifted Basic Bee in this slot")
        grind.setChecked(grind_now)
        grind.setToolTip("The gifted Basic grinder (AI PROGRESS > Overview): Basic Egg, "
                         "Royal Jelly, Basic Egg... in this slot until a gifted Basic Bee "
                         "sits here. Its on/off switch and budgets are on that card.")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lst.itemDoubleClicked.connect(lambda _i: dlg.accept())
        lay = QVBoxLayout(dlg)
        lay.addWidget(lst)
        lay.addWidget(grind)
        lay.addWidget(buttons)
        dlg.resize(280, 520)
        if dlg.exec() != QDialog.Accepted or lst.currentItem() is None:
            return
        if grind.isChecked():
            self.grind_here(slot)
        elif grind_now:
            self._set_grind(0)
        bee = lst.currentItem().data(Qt.UserRole)
        if bee:
            self.slots[slot] = bee
        else:
            self.slots.pop(slot, None)
        self._save()

    def grind_here(self, slot: int) -> None:
        """The grinder's slot set to `slot`, and a stop it kept for that
        slot let go (var/grinder.json `done`), so it starts again there."""
        from ...brain import grinder
        path = var(grinder.STATE_FILE)
        state = grinder.load(path)
        if state.pop("done", None) is not None:
            grinder.save(path, state)
        self._set_grind(int(slot))

    def fill(self) -> None:
        if self._hive() != "blue":
            self._note.setText(f"no guide plan for a {self._hive()} hive yet (only blue_hive_plan.yaml)")
            return
        plan = yaml.safe_load(data("knowledge", "blue_hive_plan.yaml").read_text()) or {}
        stage = stage_for(plan, self.total if self.total is not None else 0) or {}
        self.slots = hp.fill_from_comp(stage.get("comp_bees") or {})
        self._save()

    def clear_all(self) -> None:
        self.slots = {}
        self._save()

    # ---- presets and share codes (ROADMAP H17) ------------------------------
    def open_starters(self) -> None:
        self._offer(PresetDialog(self, hive=self._hive()))

    def open_import(self) -> None:
        self._offer(PresetDialog(self))

    def _offer(self, dlg: "PresetDialog") -> None:
        if dlg.exec() == QDialog.Accepted and dlg.plan:
            self.apply_plan(dlg.plan, dlg.title)

    def confirm(self, text: str) -> bool:
        """The owner says yes; tests replace this."""
        return QMessageBox.question(self, "Replace the hive plan?", text) == QMessageBox.Yes

    def apply_plan(self, plan: dict, title: str = "this plan") -> bool:
        """`plan` replaces the hive plan, saved by hiveplanner.save as a
        click-by-click plan is -- after a confirm when one is there."""
        if self.slots and not self.confirm(
                f"{title} replaces your plan of {len(self.slots)} slots. "
                f"Copy its share code first to keep it."):
            return False
        self.slots = dict(plan)
        self._save()
        return True

    def share_code(self) -> str | None:
        return hivepresets.encode(self.slots) if self.slots else None

    def copy_code(self) -> None:
        code = self.share_code()
        if code is None:
            self._note.setText("No plan to share yet: plan a slot or pick a preset first.")
            return
        QApplication.clipboard().setText(code)
        self._note.setText(f"Share code copied ({len(code)} characters). Post it in the "
                           f"Discord 🍯・hive-presets forum; anyone pastes it with "
                           f"Presets > Import share code.")


class _PlanView:
    """What HiveGrid reads, for a plan that is only shown (no hive, no rings):
    the slots past the plan's last are drawn empty."""

    def __init__(self, panel):
        self.label, self.colour = panel.label, panel.colour
        self.shown, self.slots, self.matched, self.total = {}, {}, {}, 0


class _PreviewGrid(HiveGrid):
    """The hive grid, read-only: the tooltip names the bee, a click does nothing."""

    def mouseMoveEvent(self, event) -> None:
        slot = self.slot_at(event.position())
        bee = self._panel.shown.get(slot) if slot else None
        if bee:
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"slot {slot}: {self._panel.label(bee)}", self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, _event) -> None:
        pass


def plan_summary(plan: dict, label) -> str:
    counts = Counter(plan.values()).most_common()
    return f"{len(plan)} slots: " + ", ".join(f"{n} {label(b)}" for b, n in counts)


class PresetDialog(QDialog):
    """Pick a starter preset (`hive` given) or paste a share code (`hive`
    None); the plan is previewed on the hive grid and Apply hands it back as
    `plan` -- the panel confirms and saves."""

    def __init__(self, panel, hive: str | None = None):
        super().__init__(panel)
        self.panel, self.plan, self.title = panel, None, ""
        self.starters = hivepresets.starters() if hive is not None else []
        self.setWindowTitle("Hive presets: starters" if hive is not None
                            else "Hive presets: import a share code")
        outer = QHBoxLayout(self)
        left = QVBoxLayout()
        if hive is not None:
            self.hive = QComboBox()
            for h in hivepresets.HIVES:
                self.hive.addItem(f"{h.title()} hive", h)
            self.list = QListWidget()
            self.list.currentRowChanged.connect(self._picked)
            self.hive.currentIndexChanged.connect(lambda _=0: self._fill_list())
            left.addWidget(self.hive)
            left.addWidget(self.list, 1)
            self.code = None
        else:
            self.code = QPlainTextEdit()
            self.code.setPlaceholderText(f"Paste a code that starts with {hivepresets.CODE_PREFIX}")
            self.code.setFixedHeight(90)
            self.code.textChanged.connect(lambda: self.check(self.code.toPlainText()))
            left.addWidget(QLabel("Share code (from the Discord 🍯・hive-presets forum)"))
            left.addWidget(self.code)
        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        self.verdict.setTextFormat(Qt.RichText)
        left.addWidget(self.verdict)
        self.source = QLabel("")
        self.source.setWordWrap(True)
        self.source.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        left.addWidget(self.source)
        left.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.apply_button = QPushButton("Apply to my plan")
        self.apply_button.setObjectName("Primary")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.apply_button)
        left.addLayout(buttons)
        outer.addLayout(left, 1)
        self.view = _PlanView(panel)
        self.grid = _PreviewGrid(self.view)
        outer.addWidget(self.grid, 0, Qt.AlignTop)
        self.resize(720, self.grid.height() + 24)
        if hive is not None:
            self.hive.setCurrentIndex(max(0, self.hive.findData(hive)))
            self._fill_list()
        else:
            self._show(None)

    def _fill_list(self) -> None:
        hive = self.hive.currentData()
        self.shown = [p for p in self.starters if p["hive"] == hive]
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.shown:
            self.list.addItem(f"{p['stage'].title()} · {p['name']}")
        self.list.blockSignals(False)
        self.list.setCurrentRow(0 if self.shown else -1)
        if not self.shown:
            self._show(None)

    def _picked(self, row: int) -> None:
        if not 0 <= row < len(self.shown):
            return self._show(None)
        p = self.shown[row]
        self.title = f"{p['hive'].title()} preset “{p['name']}”"
        self._show(hivepresets.slots_of(p), p["note"], f"From: {p['source']}")

    def check(self, text: str) -> dict | None:
        try:
            plan = hivepresets.decode(text)
        except hivepresets.InvalidCode as exc:
            import html
            self._show(None, f"<span style='color:{theme.BAD}'>{html.escape(str(exc))}</span>"
                       if text.strip() else "Paste a code.")
            return None
        self.title = "The pasted plan"
        self._show(plan, f"<span style='color:{theme.GOOD}'>Valid</span> hive plan code.")
        return plan

    def _show(self, plan: dict | None, said: str = "", source: str = "") -> None:
        self.plan = plan
        self.view.shown = dict(plan or {})
        self.view.total = max(plan) if plan else 0
        summary = plan_summary(plan, self.panel.label) if plan else ""
        self.verdict.setText("<br>".join(t for t in (said, summary) if t))
        self.source.setText(source + ("\nThe rest of the hive is left open for you."
                                      if plan and len(plan) < hp.SLOTS and source else ""))
        self.apply_button.setEnabled(bool(plan))
        self.grid.update()
