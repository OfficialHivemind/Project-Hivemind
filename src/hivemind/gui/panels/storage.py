"""Advanced > Storage: how big var is, and the retention switch.

The size is a walk of var (over a million files on 2026-10-14), so it runs on
a thread, the first time the tab is opened and on Measure -- never when the
window is built.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ...datapaths import VAR_ROOT
from ...telemetry import storage
from .settings import SettingsPanel


def measure(var: Path) -> str:
    """'var holds 179.0 GB: incidents 148.5 GB, routes 26.1 GB, ...' and the
    disk's free space. Reads only. A fresh install has no var yet: said
    plainly, not as a raw '[Errno 2]' (usability triage 2026-10-26 #14)."""
    if not var.exists():
        return "Nothing saved yet."
    sizes = {}
    for entry in os.scandir(var):
        sizes[entry.name] = storage._size(entry)
    total = sum(sizes.values())
    top = sorted(sizes.items(), key=lambda kv: -kv[1])[:5]
    return (f"var holds {storage.gb(total)}: "
            + ", ".join(f"{name} {storage.gb(n)}" for name, n in top)
            + f". {storage.free_gb(var):.0f} GB free on the disk; under "
            f"{storage.LOW_DISK_GB:.0f} GB the bot stops saving debug frames.")


class StorageTab(QWidget):
    _measured = Signal(str)

    def __init__(self, parent=None, var: Path = VAR_ROOT):
        super().__init__(parent)
        self.var = Path(var)
        self._spawn = lambda job: threading.Thread(target=job, daemon=True).start()
        self._measured.connect(self._show)      # bound: queued to the GUI thread
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 8, 0, 0)
        self.panel = SettingsPanel(only=("Storage",), title="storage",
                                   subtitle="debug frames on disk")
        self.size = QLabel("not measured yet")
        self.size.setWordWrap(True)
        self.button = QPushButton("Measure")
        self.button.clicked.connect(self.refresh)
        self.panel.add(self.size)
        self.panel.add(self.button)
        box.addWidget(self.panel)
        box.addStretch(1)
        self._looked = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._looked:
            self._looked = True
            self.refresh()

    def refresh(self) -> None:
        self.button.setEnabled(False)
        self.size.setText("measuring var...")

        def job() -> None:
            try:
                text = measure(self.var)
            except OSError as exc:
                text = f"could not measure {self.var}: {exc}"
            self._measured.emit(text)
        self._spawn(job)

    def _show(self, text: str) -> None:
        self.size.setText(text)
        self.button.setEnabled(True)
