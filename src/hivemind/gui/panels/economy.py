"""Shadow prices: what one of each resource is worth to you right now.

A shadow price is the honey you would gain by having one more of something. It
sounds abstract and is the most practical number in the project, because the
same table answers four different questions at once:

    "is this planter worth the slot?"      compare its output to its cost
    "should I spend 3,333 royal jelly?"    compare to the jelly's price
    "which quest should I take?"           price the reward bundle
    "why did it do that?"                  the price IS the explanation

It is also genuinely dynamic. Glitter is worth little when you have nothing to
craft and a great deal the moment a Blender recipe is one ingredient short, and
no human player has that number in front of them.

The trend column is the hour-over-hour change, which is what tells you a price
is about to move -- usually because a cooldown is coming up or an event started.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                               QWidget)

from ...telemetry.events import ShadowPrice
from .. import theme
from ..widgets import Card, ElidedLabel, Sparkline, Trend, human_number


class PriceRow(QWidget):
    def __init__(self, price: ShadowPrice, parent=None):
        super().__init__(parent)
        self.resource = price.resource
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(10)

        self._name = ElidedLabel(price.resource)
        self._name.setStyleSheet(f"color: {theme.TEXT};")
        self._name.setFixedWidth(128)
        row.addWidget(self._name)

        self._spark = Sparkline(capacity=60, colour=theme.INFO)
        self._spark.setFixedHeight(22)
        row.addWidget(self._spark, 1)

        self._value = QLabel("")
        self._value.setStyleSheet(
            f"color: {theme.TEXT}; font-family: {theme.MONO};"
            " font-size: 12px; font-weight: 600;")
        self._value.setFixedWidth(74)
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self._value)

        self._trend = Trend(price.trend)
        self._trend.setFixedWidth(52)
        self._trend.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self._trend)

        self.update_from(price)

    def update_from(self, price: ShadowPrice) -> None:
        if not price.known:
            # Honest gap, shown as a gap. The bot has heard of this resource but
            # has never observed a path from it to honey, so it has no value to
            # report and will not make one up.
            self._value.setText("unknown")
            self._value.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; font-family: {theme.MONO};"
                " font-size: 12px; font-style: italic;")
            self._trend.set_value(0.0)
            self._name.setStyleSheet(f"color: {theme.TEXT_DIM};")
            self.setToolTip(price.basis or
                            "no observed exchange from this to honey yet")
            return

        self._value.setText(human_number(price.honey_value))
        self._value.setStyleSheet(
            f"color: {theme.TEXT}; font-family: {theme.MONO};"
            " font-size: 12px; font-weight: 600;")
        self._name.setStyleSheet(f"color: {theme.TEXT};")
        self._trend.set_value(price.trend)
        self._spark.push(price.honey_value)
        self._spark.set_colour(theme.GOOD if price.trend > 0
                               else theme.BAD if price.trend < 0 else theme.INFO)
        tip = price.basis or ""
        if price.confidence < 0.95:
            tip += f"\n(confidence {price.confidence:.0%} — ageing observation)"
        if tip:
            self.setToolTip(tip.strip())


class EconomyPanel(Card):
    def __init__(self, parent=None):
        super().__init__("shadow prices", "worth in honey, right now", parent)
        self._rows: dict[str, PriceRow] = {}

        header = QHBoxLayout()
        header.setContentsMargins(6, 0, 6, 2)
        for text, width, align in (("resource", 128, Qt.AlignLeft),
                                   ("", 0, Qt.AlignLeft),
                                   ("value", 74, Qt.AlignRight),
                                   ("1h", 52, Qt.AlignRight)):
            label = QLabel(text.upper())
            label.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; font-size: 9px; letter-spacing: 1px;")
            if width:
                label.setFixedWidth(width)
            label.setAlignment(align | Qt.AlignVCenter)
            header.addWidget(label, 0 if width else 1)
        self.add_layout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(inner)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(0)
        self._list.addStretch(1)
        scroll.setWidget(inner)
        self.add(scroll, 1)

    def update_price(self, price: ShadowPrice) -> None:
        row = self._rows.get(price.resource)
        if row is None:
            row = PriceRow(price)
            self._rows[price.resource] = row
            self._list.insertWidget(self._list.count() - 1, row)
        else:
            row.update_from(price)
        self.set_badge(str(len(self._rows)))
