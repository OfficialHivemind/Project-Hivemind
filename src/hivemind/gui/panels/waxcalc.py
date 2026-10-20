"""STATS > WAX CALCULATOR (ROADMAP H4b, a community idea, 22 Oct): pick a
beequip, its potential and the waxes you plan, and see the chance a stat gets
the wax points you want (brain/waxcalc).

You fill it in yourself; H4's beequip reader fills it later. The beequip's
stat table is read from the wiki only when asked (brain/waxcalc.fetch, cached
a week), in a thread, never while the app starts. No odds are shown without
that table: Calculate stays off until it has loaded.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ...brain import knowledge, waxcalc

NO_WAX = "—"
MAX_WAXES = 5                       # beequips.yaml mechanics.waxes.limit


def beequip_names() -> list[str]:
    """The beequips this project knows, as the wiki names them ("Camphor Lip Balm")."""
    keys = (knowledge.beequips().get("beequips") or {}).keys()
    return sorted(" ".join(k.split("_")).title() for k in keys)


def wax_choices(table: dict | None = None) -> list[str]:
    """The waxes `waxcalc.odds` can model: those that add points (Swirled
    rerolls instead, and is left out until that is modelled)."""
    table = waxcalc.wax_table() if table is None else table
    out = []
    for name, spec in table.items():
        try:
            if isinstance(spec, dict) and int(spec.get("power", 0)) > 0:
                out.append(name)
        except (TypeError, ValueError):
            continue
    return out


def describe(result: dict, stat: str, points: int) -> str:
    """The answer in plain words, with how it was worked out."""
    pct = lambda p: f"{100 * p:.1f}%"
    line = (f"<b>{pct(result['p'])}</b> chance that {stat} gets "
            f"{points} or more wax point{'s' if points != 1 else ''}.")
    if result.get("destroyed"):
        line += f"<br>{pct(result['destroyed'])} chance a Caustic Wax fails and destroys the beequip."
    line += (f"<br><span style='color:gray'>{result['method']}, {result['trials']:,} tries. "
             f"{result['note']}.</span>")
    return line


class _Loaded(QObject):
    done = Signal(object, str)          # the pool (or None), and a line to show


class WaxCalcPage(QWidget):
    def __init__(self, parent=None, fetch=waxcalc.fetch):
        super().__init__(parent)
        self._fetch = fetch
        self.pool: list = []
        self._loaded = _Loaded()
        self._loaded.done.connect(self._on_loaded)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        head = QLabel("<b style='font-size:16px'>Wax calculator</b><br>"
                      "Pick a beequip and the waxes you plan, and see the chance a stat "
                      "gets the points you want. The stat tables come from the Bee Swarm "
                      "Simulator wiki when you press Load.")
        head.setWordWrap(True)
        outer.addWidget(head)

        panel = QFrame()
        panel.setObjectName("Panel")
        form = QFormLayout(panel)
        self.beequip = QComboBox()
        self.beequip.setEditable(True)
        self.beequip.addItems(beequip_names())
        self.load = QPushButton("Load its stats")
        self.load.clicked.connect(self.load_stats)
        row = QHBoxLayout()
        row.addWidget(self.beequip, 1)
        row.addWidget(self.load)
        form.addRow("Beequip", row)

        self.potential = QSpinBox()
        self.potential.setRange(0, 5)
        self.potential.setValue(3)
        self.potential.setSuffix(" ★")
        form.addRow("Potential", self.potential)

        self.waxes = []
        waxes = QHBoxLayout()
        for _ in range(MAX_WAXES):
            box = QComboBox()
            box.addItems([NO_WAX] + [w.title() for w in wax_choices()])
            self.waxes.append(box)
            waxes.addWidget(box)
        form.addRow("Waxes, in order", waxes)

        self.stat = QComboBox()
        self.stat.setEnabled(False)
        form.addRow("Stat you want", self.stat)
        self.points = QSpinBox()
        self.points.setRange(1, 20)
        form.addRow("Wax points on it", self.points)
        outer.addWidget(panel)
        # A TOOL'S INPUTS, NOT SETTINGS: read when Load or Calculate is pressed
        # (tests/unit/test_gui_buttons _form_field)
        self.beequip.setProperty("read_on_click", "Load its stats")
        for field in [self.potential, self.stat, self.points, *self.waxes]:
            field.setProperty("read_on_click", "Calculate")

        self.calculate = QPushButton("Calculate")
        self.calculate.setEnabled(False)
        self.calculate.clicked.connect(self.run)
        outer.addWidget(self.calculate)
        self.answer = QLabel("Load a beequip's stats to start. Swirled Wax rerolls "
                             "stats instead of adding points, so it isn't offered yet.")
        self.answer.setWordWrap(True)
        outer.addWidget(self.answer)
        outer.addStretch(1)

    # ---- loading the wiki's table, off the GUI thread ----------------------
    def load_stats(self) -> None:
        name = self.beequip.currentText().strip()
        if not name:
            return
        self.load.setEnabled(False)
        self.calculate.setEnabled(False)
        self.answer.setText(f"Reading {name}'s stats from the wiki…")

        def work():
            try:
                pool = self._fetch(name)
            except (KeyError, RuntimeError) as exc:
                self._loaded.done.emit(None, str(exc).strip("'\""))
                return
            except Exception as exc:                 # never a traceback in the GUI
                self._loaded.done.emit(None, f"could not read the stats ({exc})")
                return
            self._loaded.done.emit(pool, f"{name}: {len(pool)} stats a wax can raise.")

        threading.Thread(target=work, name="waxcalc-fetch", daemon=True).start()

    def _on_loaded(self, pool, line: str) -> None:
        self.load.setEnabled(True)
        self.pool = list(pool or [])
        self.stat.clear()
        self.stat.addItems([u.name for u in self.pool])
        self.stat.setEnabled(bool(self.pool))
        self.calculate.setEnabled(bool(self.pool))
        self.answer.setText(line)

    # ---- the odds -----------------------------------------------------------
    def chosen_waxes(self) -> list[str]:
        return [b.currentText().lower() for b in self.waxes if b.currentText() != NO_WAX]

    def run(self) -> None:
        waxes = self.chosen_waxes()
        if not waxes:
            self.answer.setText("Choose at least one wax.")
            return
        stat, points = self.stat.currentText(), self.points.value()
        try:
            result = waxcalc.odds(self.pool, waxes, stat, points,
                                  quality=self.potential.value() / 5)
        except (KeyError, ValueError) as exc:
            self.answer.setText(str(exc).strip("'\""))
            return
        self.answer.setText(describe(result, stat, points))
