"""U4: a mini-map of where the bot is -- the ZONES, not a picture of the mountain.

A SCHEMATIC ON PURPOSE (see gui/panels/fields: a drawn map would invent field
positions; nothing measures them yet). Each zone of data/world/fields.yaml is
one row, the Hive at the bottom and the Summit on top, as you climb; each field
is a chip in its colour. The lit chip is the field the bot's own compass says it
is in: the Thought(topic="where") that world/bearings and vision/whereami send,
"I am in the pine tree field, 4s ago (feed)". "I do not know where I am" lights
nothing -- an unknown position is drawn as unknown, never as the last guess.
"""
from __future__ import annotations

import re

import yaml
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...datapaths import data
from .. import theme

FIELDS_YAML = data("world", "fields.yaml")
WHERE = re.compile(r"\bin the (.+?) field\b", re.IGNORECASE)
ROW_H, ROW_GAP = 18, 4


def load_zones(path=FIELDS_YAML) -> list[tuple[str, list[tuple[str, str]]]]:
    """[(zone name, [(field name, colour)...])...], Summit first (the top row)."""
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except (OSError, ValueError):
        return []
    rows = []
    for zone in doc.get("zones") or []:
        fields = [(f["name"], f.get("colour") or theme.TEXT_DIM)
                  for f in doc.get("fields") or [] if f.get("zone") == zone.get("id")]
        if fields:
            rows.append((zone.get("name") or zone.get("id"), fields))
    return rows[::-1]


def field_from_where(text: str) -> str | None:
    """The field a "where" thought names, lower case, or None when it names none."""
    found = WHERE.search(str(text or ""))
    return " ".join(found.group(1).replace("_", " ").split()).lower() if found else None


class MiniMap(QWidget):
    """The zones as rows of field chips; the bot's field lit."""

    def __init__(self, path=FIELDS_YAML, parent=None):
        super().__init__(parent)
        self.zones = load_zones(path)
        self.current: str | None = None
        self.setFixedHeight(max(1, len(self.zones)) * (ROW_H + ROW_GAP))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_where(self, text: str) -> None:
        field = field_from_where(text)
        if field != self.current:
            self.current = field
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont(painter.font())
        font.setPixelSize(10)
        painter.setFont(font)
        label_w = 88.0
        for i, (zone, fields) in enumerate(self.zones):
            y = i * (ROW_H + ROW_GAP)
            painter.setPen(QColor(theme.TEXT_FAINT))
            painter.drawText(QRectF(0, y, label_w - 6, ROW_H),
                             Qt.AlignVCenter | Qt.AlignRight, zone)
            width = (self.width() - label_w) / max(1, len(fields))
            for j, (name, colour) in enumerate(fields):
                box = QRectF(label_w + j * width + 2, y + 1, width - 4, ROW_H - 2)
                here = name.lower() == self.current
                tint = QColor(colour)
                tint.setAlpha(255 if here else 40)
                painter.setBrush(tint)
                painter.setPen(QPen(QColor(theme.TEXT if here else theme.BORDER),
                                    2.0 if here else 1.0))
                painter.drawRoundedRect(box, 5, 5)
                painter.setPen(QColor(theme.BG if here else theme.TEXT_DIM))
                painter.drawText(box, Qt.AlignCenter, ("● " if here else "") + name)
