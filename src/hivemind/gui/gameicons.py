"""Bee Swarm's own field and item icons for the cards (ROADMAP U18: "icons
are from the game"). The PNGs are fetched by scripts/fetch_game_icons.py into
data/game_icons/{fields,items}/<slug>.png, each one's wiki source listed in
data/game_icons/SOURCES.md. A missing file draws a neutral placeholder (the
name's first letters on a grey tile), never a broken image.
"""
from __future__ import annotations

from functools import lru_cache

import yaml
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

from . import theme
from ..datapaths import data

# The items the bot uses (and the hotbar picker lists), in the game's own names.
ITEMS = ("Glitter", "Field Dice", "Smooth Dice", "Loaded Dice", "Gumdrops",
         "Micro-Converter", "Coconut", "Jelly Beans", "Royal Jelly", "Ticket",
         "Enzymes", "Oil", "Blue Extract", "Red Extract", "Glue",
         "Sprinkler Builder", "Whirligig", "Ant Pass", "Robo Pass", "Treat",
         "Blueberry", "Strawberry", "Pineapple", "Sunflower Seed", "Moon Charm",
         "Stinger")


def slug(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


@lru_cache(maxsize=1)
def field_zones() -> list[tuple[str, list[str]]]:
    """[("Starter", [...]), ("5 Bee", [...]), ...]: the fields of the
    settings' own `gather.field` choices, grouped by the bees each zone's gate
    needs (data/knowledge/world.yaml bees_required)."""
    from ..world.settings import SECTIONS
    choices = next(e[5] for _, es in SECTIONS for e in es if e[0] == "gather.field")
    try:
        world = yaml.safe_load(data("knowledge", "world.yaml").read_text())["fields"]
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        world = {}
    zones: dict[int, list[str]] = {}
    for name in choices:
        if name != "auto":
            need = (world.get(slug(name)) or {}).get("bees_required", 0)
            zones.setdefault(int(need), []).append(name)
    return [("Starter" if need == 0 else f"{need} Bee", names)
            for need, names in sorted(zones.items())]


def _placeholder(name: str, size: int) -> QPixmap:
    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.S_LINE))
    p.drawRoundedRect(0, 0, size * 2, size * 2, size / 2, size / 2)
    font = QFont()
    font.setPixelSize(int(size * 0.8))
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor(theme.S_DIM))
    letters = "".join(w[0] for w in name.replace("-", " ").split()[:2]).upper()
    p.drawText(pix.rect(), Qt.AlignCenter, letters)
    p.end()
    pix.setDevicePixelRatio(2.0)
    return pix


@lru_cache(maxsize=256)
def pixmap(kind: str, name: str, size: int = 24) -> QPixmap:
    """`kind` 'fields' or 'items'; the icon at `size` logical pixels, sharp
    on a 2x screen. A placeholder when the file is missing."""
    pix = QPixmap(str(data("game_icons", kind, slug(name) + ".png")))
    if pix.isNull():
        return _placeholder(name, size)
    pix = pix.scaled(size * 2, size * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pix.setDevicePixelRatio(2.0)
    return pix


def icon(kind: str, name: str, size: int = 24) -> QIcon:
    return QIcon(pixmap(kind, name, size))


def has(kind: str, name: str) -> bool:
    return data("game_icons", kind, slug(name) + ".png").exists()
