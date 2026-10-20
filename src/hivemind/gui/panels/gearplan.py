"""The Gear plan: pick the gear you want, in the order you want it.

THE OWNER, 2026-10-20: a gear section to pick the gear wanted, in order (this
tool, then that one), with the game's own images; and the Goals tab should be
simple -- select, then order. So this IS the new window's Goals
page (gui/shell); the old detail rows sit behind its Advanced button.

Left, every piece of gear the price table knows (brain/owned.prices(): the
goals of goals.yaml, the tools of progression.yaml, gear_prices.yaml) with its
wiki picture (data/knowledge/gear/wiki, scripts/fetch_gear_images.py); a click
adds it to the end of "My order". Owned gear (brain/owned.owned) is greyed and
cannot be added. Right, their order: drag, or Up / Down / Remove. Save writes the
keys, comma separated, into `goals.order` -- what brain/goals.from_files reads
(its `with_gear` makes any priced gear a goal; `hive_slot` / `hive_slot<=N` is
the next hive slot) -- and the line under the lists is from_files on the order
being edited: what the bot would save for next.

Not offered: the hive-slot ladder (the "Next hive slot" card stands for it),
and the Backpack and Port-O-Hive bags, whose names are aliases of the
Porcelain Port-O-Hive goal everywhere (goals.yaml) -- a pick of them would
plan the Porcelain one.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)

from ...brain import goals as goals_plan
from ...brain import owned as owned_mod
from ...datapaths import data
from .. import theme
from ..gameicons import _placeholder
from ..widgets import Card, human_number

SLOT = goals_plan.NEXT_SLOT                     # "hive_slot", and "hive_slot<=N"
ICON = 72
SHADOWED = ("backpack", "port_o_hive")          # aliases of a goal (see above)
SLOT_NAMES = {"tool": "Tools", "bag": "Bags", "hat": "Masks & hats", "belt": "Belts",
              "boots": "Boots", "right shoulder": "Guards (right)",
              "left shoulder": "Guards (left)", "amulet": "Amulets",
              "glider": "Gliders", "sprinkler": "Sprinklers", "hive": "Hive"}


def picture(key: str, label: str, size: int = ICON) -> QPixmap:
    """The wiki picture, or the label's initials on a tile when it is missing."""
    pix = QPixmap(str(data("knowledge", "gear", "wiki", f"{key}.png")))
    if pix.isNull():
        return _placeholder(label, size)
    pix = pix.scaled(size * 2, size * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pix.setDevicePixelRatio(2.0)
    return pix


def catalogue() -> dict:
    """{key: Item} of what can be planned: tools first, then each slot, cheapest first."""
    items = {k: i for k, i in owned_mod.prices().items()
             if i.slot != "hive" and k not in SHADOWED}
    rank = {slot: n for n, slot in enumerate(SLOT_NAMES)}
    return dict(sorted(items.items(), key=lambda kv: (rank.get(kv[1].slot, 99), kv[1].honey)))


def resolve(name: str, goals_data: dict, table: dict) -> str:
    """A name from `goals.order` as the key it plans (`with_gear`'s order:
    a goal first, then any priced gear); itself when it is neither."""
    if name == SLOT or name.startswith(SLOT + "<="):
        return name
    return goals_plan.goal_key(name, goals_data) or owned_mod.item_key(name, table) or name


class _Overlay:
    """settings.get with `goals.order` replaced: the preview's plan."""

    def __init__(self, settings, order: str):
        self._settings, self._order = settings, order

    def get(self, key, default=None):
        return self._order if key == "goals.order" else self._settings.get(key, default)


class GearPlanPanel(Card):
    def __init__(self, settings, save=None, var_root=None, parent=None):
        super().__init__("my gear plan", "click gear to add it · drag to reorder · Save", parent)
        self.settings, self._save, self.var_root = settings, save or (lambda text: None), var_root
        self.goals_data = goals_plan.load()
        self.table = owned_mod.prices()
        self.items = catalogue()
        self.owned: set = set()
        self._pro: dict = {}                    # the pro tester's entries, when used

        row = QHBoxLayout()
        row.setSpacing(14)
        left = QVBoxLayout()
        head = QHBoxLayout()
        title = QLabel("Choose gear")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        head.addWidget(title)
        head.addStretch(1)
        self.filter = QComboBox()
        self.filter.addItem("All gear", "")
        for slot in dict.fromkeys(i.slot for i in self.items.values()):
            self.filter.addItem(SLOT_NAMES.get(slot, slot.title()), slot)
        self.filter.addItem("Hive", "hive")
        self.filter.currentIndexChanged.connect(lambda _=0: self._apply_filter())
        head.addWidget(self.filter)
        left.addLayout(head)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setResizeMode(QListWidget.Adjust)
        self.grid.setMovement(QListWidget.Static)
        self.grid.setIconSize(QSize(ICON, ICON))
        self.grid.setGridSize(QSize(132, 138))
        self.grid.setWordWrap(True)
        self.grid.setSpacing(4)
        self.grid.itemClicked.connect(lambda item: self.add_item(item.data(Qt.UserRole)))
        left.addWidget(self.grid, 1)
        row.addLayout(left, 3)

        right = QVBoxLayout()
        mine = QLabel("My order")
        mine.setStyleSheet("font-size: 15px; font-weight: 700;")
        right.addWidget(mine)
        self.order = QListWidget()
        self.order.setIconSize(QSize(40, 40))
        self.order.setDragDropMode(QAbstractItemView.InternalMove)
        self.order.setDefaultDropAction(Qt.MoveAction)
        self.order.model().rowsMoved.connect(self._moved)
        self.order.currentRowChanged.connect(lambda _=0: self._sync_buttons())
        right.addWidget(self.order, 1)
        buttons = QHBoxLayout()
        made = []
        for text, act in (("▲ Up", lambda: self.move(-1)), ("▼ Down", lambda: self.move(1)),
                          ("Remove", self.remove), ("Reset", self.reset)):
            b = QPushButton(text)
            b.clicked.connect(act)
            buttons.addWidget(b)
            made.append(b)
        self.up_button, self.down_button, self.remove_button, _ = made
        right.addLayout(buttons)
        pro = QPushButton("Use the pro tester's order")
        pro.setToolTip("Fills My order with the pro tester's gear order for your hive "
                       "colour (Settings > Progression). Press Save to keep it.")
        pro.clicked.connect(self.use_pro_order)
        right.addWidget(pro)
        self.save_button = QPushButton("Save my order")
        self.save_button.setObjectName("Primary")
        self.save_button.setStyleSheet(theme.PRIMARY)
        self.save_button.clicked.connect(self.save)
        right.addWidget(self.save_button)
        row.addLayout(right, 2)
        self.add_layout(row)

        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(f"color: {theme.ACCENT}; font-size: 13px; font-weight: 600;")
        self.add(self.preview)
        credit = QLabel("Pictures: Bee Swarm Simulator Fandom wiki (CC BY-SA 3.0); "
                        "game art © Onett. Prices from the bot's price lists; ? = not known.")
        credit.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        self.add(credit)
        self.reload()

    # ---- what is shown ------------------------------------------------------
    def label(self, key: str) -> str:
        if key == SLOT:
            return "Next hive slot"
        if key.startswith(SLOT + "<="):
            return f"Next hive slot (until {key.split('<=')[1]} bees)"
        goal = ((self.goals_data.get("goals") or {}).get(key) or self._pro.get(key) or {})
        item = self.table.get(key)
        return str(goal.get("label") or (item.label if item else key))

    def price(self, key: str) -> str:
        item = self.table.get(key)
        return f"{human_number(item.honey)} honey" if item else "? honey"

    def reload(self) -> None:
        """Owned gear and `goals.order` (or the default order) read again."""
        try:
            from ...datapaths import VAR_ROOT
            self.owned = set(owned_mod.owned(self.settings.get("goals.owned") or "",
                                             self.var_root or VAR_ROOT, self.table))
        except Exception:                      # an unreadable record never empties the page
            self.owned = set()
        names = goals_plan._names(self.settings.get("goals.order") or "")
        if not names:
            names = [str(k) for k in self.goals_data.get("default_order") or ()]
        self.set_order([resolve(n, self.goals_data, self.table) for n in names])
        self._fill_grid()

    def _fill_grid(self) -> None:
        self.grid.clear()
        chosen = set(self.keys())
        cards = [(k, i.label, i.honey, i.slot) for k, i in self.items.items()]
        cards.append((SLOT, "Next hive slot", None, "hive"))
        for key, label, honey, slot in cards:
            have = key in self.owned
            text = (f"{label}\n" + ("✓ owned" if have else "✓ in order" if key in chosen
                                     else f"{human_number(honey)} honey" if honey
                                     else "price by slot"))
            item = QListWidgetItem(QIcon(picture(key, label)), text)
            item.setData(Qt.UserRole, key)
            item.setData(Qt.UserRole + 1, slot)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            item.setToolTip(f"{label} — {SLOT_NAMES.get(slot, slot)}, "
                            + (f"{honey:,} honey" if honey else "price set by your hive")
                            + ("\nYou own this." if have else "\nClick to add it to your order."))
            if have:
                item.setFlags(Qt.NoItemFlags)    # greyed, not addable
            self.grid.addItem(item)
        self._apply_filter()

    def _apply_filter(self) -> None:
        want = self.filter.currentData()
        for n in range(self.grid.count()):
            item = self.grid.item(n)
            item.setHidden(bool(want) and item.data(Qt.UserRole + 1) != want)

    # ---- the order ----------------------------------------------------------
    def keys(self) -> list[str]:
        return [self.order.item(n).data(Qt.UserRole) for n in range(self.order.count())]

    def set_order(self, keys) -> None:
        self.order.clear()
        for key in dict.fromkeys(keys):
            item = QListWidgetItem(QIcon(picture(key, self.label(key), 40)), "")
            item.setData(Qt.UserRole, key)
            self.order.addItem(item)
        self._sync_buttons()
        self._changed()

    def _changed(self) -> None:
        for n in range(self.order.count()):
            item = self.order.item(n)
            key = item.data(Qt.UserRole)
            known = key in self.table or key.startswith(SLOT)
            item.setText(f"{n + 1}.  {self.label(key)}   ·   "
                         + ("owned — skipped" if key in self.owned
                            else "price by slot" if key.startswith(SLOT)
                            else self.price(key) if known else "not an item the bot knows"))
        self.preview.setText(self.next_line())

    def _moved(self, *_args) -> None:
        self._changed()

    def add_item(self, key) -> None:
        if not key or key in self.owned or key in self.keys():
            return
        self.set_order(self.keys() + [key])
        self._fill_grid()

    def _sync_buttons(self) -> None:
        """Up / Down / Remove only with a row chosen, and only where it can
        go (UI render pass 2026-10-21: they did nothing, silently)."""
        if not hasattr(self, "up_button"):
            return                              # still being built
        row, last = self.order.currentRow(), self.order.count() - 1
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(0 <= row < last)
        self.remove_button.setEnabled(row >= 0)
        for b in (self.up_button, self.down_button, self.remove_button):
            b.setToolTip("" if b.isEnabled() else "Click a row in My order first")

    def move(self, step: int, row: int | None = None) -> None:
        row = self.order.currentRow() if row is None else row
        keys, to = self.keys(), row + step
        if not (0 <= row < len(keys) and 0 <= to < len(keys)):
            return
        keys[row], keys[to] = keys[to], keys[row]
        self.set_order(keys)
        self.order.setCurrentRow(to)

    def remove(self, row: int | None = None) -> None:
        row = self.order.currentRow() if row is None else row
        keys = self.keys()
        if 0 <= row < len(keys):
            del keys[row]
            self.set_order(keys)
            self._fill_grid()

    def reset(self) -> None:
        """Back to the built-in order (goals.yaml default_order); not saved yet."""
        self.set_order([str(k) for k in self.goals_data.get("default_order") or ()])
        self._fill_grid()

    def use_pro_order(self) -> None:
        """brain/protips' suggested order for their hive colour; not saved yet."""
        from ...brain import protips
        from ...brain.progression import hive_from
        picked = protips.suggested_order(hive_from(self.settings), self.goals_data)
        self._pro = dict(picked)
        self.set_order([k for k, _e in picked if k not in self.owned])
        self._fill_grid()

    def text(self) -> str:
        """`goals.order` as Save writes it: keys, in order, comma separated."""
        return ", ".join(self.keys())

    def save(self) -> None:
        self._save(self.text())
        self.preview.setText(self.next_line() + "   ✓ saved")

    def next_line(self) -> str:
        """What brain/goals plans first with this order -- its own words."""
        try:
            plan = goals_plan.from_files(settings=_Overlay(self.settings, self.text()),
                                         var_root=self.var_root)
        except Exception as exc:               # a preview never breaks the page
            return f"Next the bot saves for: ? (the plan could not be worked out: {exc})"
        row = plan.first_open()
        if row is None:
            return "Next the bot saves for: nothing — everything in your order is owned."
        needs = [f"{row.cost:,} honey" if row.cost else "? honey"]
        needs += [n.describe() for n in row.needs]
        short = f" — {row.queue_short:,} honey still to make" if row.queue_short else ""
        return f"Next the bot saves for: {row.label} (needs {', '.join(needs)}){short}"
