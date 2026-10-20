"""YOUR OWN PROGRESSION ROUTE, THE EDITOR (ROADMAP G10, a community idea,
22 Oct: "the blue/red/white plans editable (reorder, add, remove goals) and
saved as your own plan; shareable as a preset").

    My route [v]   Name [________]   Based on [blue v]
    +-- the route, as the bot will take it --+  Put first, in this order
    | EARLY                                  |   1. Noob/Pro Shop tools
    |   * 1. Noob/Pro Shop tools             |  [Up] [Down] [Not first]
    |   25 bees                              |  A goal of your own
    |   x Basic Boots (skipped)              |  [label____] [Early v] [Add]
    |   + 30 bees on the alt (yours)         |
    +----------------------------------------+
    [Put first] [Skip] [Delete my goal]
    notes: what the route could not use (brain/progression.customise)
    [Save and use] [Import...] [Export...] [Follow the researched route]

This page only edits a route dict -- {name, base, first, skip, add}, the
format brain/progression documents -- and shows customise() on it. Save
writes <config>/progression/<name>.yaml (progression.route_path) and sets
`progression.plan` through the window's one save path; the bot reads it at
its next plan (READ_AT_EVERY_USE). The researched files are never changed.
Sharing a route is sharing its file: Import copies one in, Export saves one out.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .. import theme
from ...brain import progression as prog
from ..widgets import Card

ROUTE_KEYS = ("name", "base", "first", "skip", "add")


def clean_route(body, hive: str = prog.DEFAULT_HIVE) -> dict:
    """A route dict with only the keys customise() reads, each of the right
    kind -- what a file from someone else is cut down to before it is used.
    ponytail: a hand-written file's other keys (and its comments) are not
    kept when the editor saves it again."""
    body = body if isinstance(body, dict) else {}
    base = str(body.get("base") or hive).lower()
    add = body.get("add") if isinstance(body.get("add"), list) else []
    return {"name": str(body.get("name") or "").strip(),
            "base": base if base in prog.HIVES else prog.DEFAULT_HIVE,
            "first": list(dict.fromkeys(prog.route_ids(body, "first"))),
            "skip": list(dict.fromkeys(prog.route_ids(body, "skip"))),
            "add": [_clean_goal(g) for g in add if isinstance(g, dict)]}


def _clean_goal(goal: dict) -> dict:
    """An `add` goal without a priority that is not a whole number (customise
    gives it 2): `priority: high` from a shared file raised in every sort by
    priority, and the window would not start (review 2026-10-26)."""
    return {k: v for k, v in goal.items()
            if k != "priority" or prog._is_priority(v)}


def stage_title(stage: dict) -> str:
    """"Early" from "Early -- fresh account to 25 bees (...)", or the stage id."""
    name = str(stage.get("name") or "").split(" -- ")[0].strip()
    return name or str(stage.get("id") or "?").title()


def _dump(route: dict) -> str:
    import yaml
    body = {k: route[k] for k in ROUTE_KEYS if route.get(k)}
    return yaml.safe_dump(body, sort_keys=False, allow_unicode=True)


class RouteEditor(Card):
    def __init__(self, settings, save=None, parent=None):
        super().__init__("my progression route",
                         "put goals first · skip some · add your own · Save", parent)
        self.settings, self._save = settings, save or (lambda name: None)
        self.first: list = []
        self.skip: list = []
        self.add_goals: list = []
        self.notes: list = []
        self.opened = None          # the route file being edited (a Path), None for a new one
        self.as_opened: dict = {}   # route() when it was opened or saved: unsaved changes differ

        top = QHBoxLayout()
        top.addWidget(QLabel("My route"))
        self.routes = QComboBox()
        self.routes.setToolTip("Open a route saved on this PC, or start a new one")
        self.routes.activated.connect(lambda _=0: self._route_picked())
        top.addWidget(self.routes, 1)
        top.addWidget(QLabel("Name"))
        self.name = QLineEdit()
        self.name.setPlaceholderText("My blue route")
        self.name.setProperty("read_on_click", "Save and use")   # read by Save, not on change
        top.addWidget(self.name, 1)
        top.addWidget(QLabel("Based on"))
        self.base_box = QComboBox()
        for hive in prog.HIVES:
            self.base_box.addItem(f"the {hive} route", hive)
        self.base_box.currentIndexChanged.connect(lambda _=0: self._base_changed())
        top.addWidget(self.base_box)
        self.add_layout(top)

        row = QHBoxLayout()
        row.setSpacing(14)
        left = QVBoxLayout()
        title = QLabel("The route, as the bot will take it")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        left.addWidget(title)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.itemSelectionChanged.connect(self._sync_buttons)
        left.addWidget(self.tree, 1)
        goal_buttons = QHBoxLayout()
        self.first_button = QPushButton("Put first")
        self.first_button.clicked.connect(lambda: self.put_first(self.chosen()))
        self.skip_button = QPushButton("Skip")
        self.skip_button.clicked.connect(lambda: self.toggle_skip(self.chosen()))
        self.delete_button = QPushButton("Delete my goal")
        self.delete_button.clicked.connect(lambda: self.delete_goal(self.chosen()))
        for b in (self.first_button, self.skip_button, self.delete_button):
            goal_buttons.addWidget(b)
        left.addLayout(goal_buttons)
        row.addLayout(left, 3)

        right = QVBoxLayout()
        mine = QLabel("Put first, in this order")
        mine.setStyleSheet("font-size: 15px; font-weight: 700;")
        right.addWidget(mine)
        self.first_list = QListWidget()
        self.first_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.first_list.currentRowChanged.connect(lambda _=0: self._sync_buttons())
        right.addWidget(self.first_list, 1)
        order = QHBoxLayout()
        self.up_button = QPushButton("▲ Up")
        self.up_button.clicked.connect(lambda: self.move(-1))
        self.down_button = QPushButton("▼ Down")
        self.down_button.clicked.connect(lambda: self.move(1))
        self.unfirst_button = QPushButton("Not first")
        self.unfirst_button.clicked.connect(self.not_first)
        for b in (self.up_button, self.down_button, self.unfirst_button):
            order.addWidget(b)
        right.addLayout(order)
        own = QLabel("A goal of your own")
        own.setStyleSheet("font-size: 15px; font-weight: 700;")
        right.addWidget(own)
        adding = QHBoxLayout()
        self.new_label = QLineEdit()
        self.new_label.setPlaceholderText("e.g. 30 bees on the alt")
        self.new_label.setProperty("read_on_click", "Add goal")
        self.new_label.returnPressed.connect(self._add_clicked)
        adding.addWidget(self.new_label, 1)
        self.new_stage = QComboBox()
        self.new_stage.setProperty("read_on_click", "Add goal")
        adding.addWidget(self.new_stage)
        self.add_button = QPushButton("Add goal")
        self.add_button.clicked.connect(self._add_clicked)
        adding.addWidget(self.add_button)
        right.addLayout(adding)
        row.addLayout(right, 2)
        self.add_layout(row)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {theme.ACCENT}; font-size: 13px; font-weight: 600;")
        self.add(self.note)
        bottom = QHBoxLayout()
        self.save_button = QPushButton("Save and use")
        self.save_button.setObjectName("Primary")
        self.save_button.setStyleSheet(theme.PRIMARY)
        self.save_button.setToolTip("Saves the route in the 'progression' folder beside "
                                    "settings.yaml and makes it the one the bot follows")
        self.save_button.clicked.connect(lambda: self.save())
        bottom.addWidget(self.save_button)
        importing = QPushButton("Import…")
        importing.setToolTip("Copy a route file someone shared into your routes")
        importing.clicked.connect(self._import_clicked)
        bottom.addWidget(importing)
        exporting = QPushButton("Export…")
        exporting.setToolTip("Save a copy of this route to share")
        exporting.clicked.connect(self._export_clicked)
        bottom.addWidget(exporting)
        bottom.addStretch(1)
        researched = QPushButton("Follow the researched route")
        researched.setToolTip("The bot stops using your route (it stays saved)")
        researched.clicked.connect(self.use_researched)
        bottom.addWidget(researched)
        self.add_layout(bottom)

        self.fill_routes()
        plan = self.plan()
        self.open_route(prog.route_path(plan) if plan else "")

    # ---- the route being edited ---------------------------------------------
    def plan(self) -> str:
        return str(self.settings.get("progression.plan") or "").strip()

    @property
    def base(self) -> str:
        return self.base_box.currentData() or prog.DEFAULT_HIVE

    def route(self) -> dict:
        """The route as Save writes it."""
        return {"name": self.name.text().strip(), "base": self.base,
                "first": list(self.first), "skip": list(self.skip),
                "add": [dict(g) for g in self.add_goals]}

    def set_route(self, route: dict) -> None:
        route = clean_route(route, prog.hive_from(self.settings))
        self.name.setText(route["name"])
        self.first, self.skip, self.add_goals = route["first"], route["skip"], route["add"]
        self.base_box.blockSignals(True)
        self.base_box.setCurrentIndex(max(0, self.base_box.findData(route["base"])))
        self.base_box.blockSignals(False)
        self._base_changed()

    def open_route(self, path) -> None:
        """A saved route by its file (any name: read as it is, not slugged
        again), or a new one (empty `path`)."""
        path = Path(path) if path else None
        body = prog.read_route(path) if path else {}
        problem = ""
        if path and not body:
            problem = (f"{path.name} is not a route file that can be read; this is a new route."
                       if path.exists() else f"No route file {path.name}; this is a new route.")
        else:
            try:
                self.set_route(body or {"name": "", "base": prog.hive_from(self.settings)})
            except Exception as exc:     # a file nothing above caught must not stop the window
                problem = (f"{path.name if path else 'The route'} could not be shown ({exc}); "
                           f"this is a new route.")
        if problem:
            path = None
            self.set_route({"name": "", "base": prog.hive_from(self.settings)})
        elif path and not self.name.text():
            self.name.setText(path.stem)
        self.opened = path
        self.as_opened = self.route()
        self._select_route(path)
        if problem:
            self._show_notes(problem)

    def unsaved(self) -> bool:
        return self.route() != self.as_opened

    def _route_picked(self) -> None:
        """Another route chosen in 'My route': unsaved changes are asked about."""
        picked = self.routes.currentData()
        if self.unsaved() and not self.confirm(
                "Open another route?", "Your changes to this route are not saved. Drop them?"):
            self._select_route(self.opened)
            return
        self.open_route(picked)

    def _base_changed(self) -> None:
        data = prog.load(self.base)
        keep = self.new_stage.currentData()
        self.new_stage.clear()
        for st in data.get("stages") or []:
            self.new_stage.addItem(stage_title(st), str(st.get("id")))
        self.new_stage.setCurrentIndex(max(0, self.new_stage.findData(keep)))
        self.refresh()

    def refresh(self) -> None:
        """customise() on the route, shown: each stage's goals in the order
        next_goals takes them (by priority, stable), and its notes."""
        data, self.notes = prog.customise(prog.load(self.base), self.route())
        mine = {str(g.get("id")) for g in self.add_goals}
        chosen = self.chosen()
        self.tree.clear()
        for st in data.get("stages") or []:
            head = QTreeWidgetItem([stage_title(st).upper()])
            head.setFlags(Qt.ItemIsEnabled)
            head.setToolTip(0, str(st.get("name") or ""))
            self.tree.addTopLevelItem(head)
            goals = sorted((g for g in st.get("goals") or [] if isinstance(g, dict)),
                           key=lambda g: int(g.get("priority") or 9))
            for g in goals:
                gid = str(g.get("id"))
                text = str(g.get("label") or gid)
                if gid in self.first and gid not in self.skip:
                    text = f"★ {self.first.index(gid) + 1}. {text}"
                if gid in self.skip:
                    text = f"✕ {text}  (skipped)"
                if gid in mine:
                    text = f"+ {text}  (yours)"
                item = QTreeWidgetItem([text])
                item.setData(0, Qt.UserRole, gid)
                item.setToolTip(0, str(g.get("why") or g.get("name") or ""))
                head.addChild(item)
                if gid == chosen:
                    item.setSelected(True)
            head.setExpanded(True)
        labels = {str(g.get("id")): str(g.get("label") or g.get("id"))
                  for _i, g in prog._goals(data)}
        row = self.first_list.currentRow()
        self.first_list.clear()
        for n, gid in enumerate(self.first):
            item = QListWidgetItem(f"{n + 1}.  {labels.get(gid, gid + '  (not in this route)')}")
            item.setData(Qt.UserRole, gid)
            self.first_list.addItem(item)
        if 0 <= row < self.first_list.count():
            self.first_list.setCurrentRow(row)
        self._sync_buttons()
        self._show_notes()

    def _show_notes(self, extra: str = "") -> None:
        plan = self.plan()
        using = (f"The bot follows your route '{plan}'." if plan and prog.load_route(plan)
                 else f"The bot follows the researched {prog.hive_from(self.settings)} route."
                 + (f" (Its route '{plan}' has no file.)" if plan else ""))
        lines = [using] + [f"Not used: {n}" for n in self.notes] + ([extra] if extra else [])
        self.note.setText("\n".join(lines))

    # ---- the goal buttons ---------------------------------------------------
    def chosen(self) -> str:
        items = self.tree.selectedItems()
        return str(items[0].data(0, Qt.UserRole) or "") if items else ""

    def _sync_buttons(self) -> None:
        """Each button only where it can do something (the gear plan's rule,
        UI render pass 2026-10-21: buttons that did nothing, silently)."""
        if not hasattr(self, "unfirst_button"):
            return                              # still being built
        gid = self.chosen()
        mine = gid in {str(g.get("id")) for g in self.add_goals}
        self.first_button.setEnabled(bool(gid) and gid not in self.first)
        self.skip_button.setEnabled(bool(gid))
        self.skip_button.setText("Don't skip" if gid in self.skip else "Skip")
        self.delete_button.setEnabled(mine)
        row, last = self.first_list.currentRow(), self.first_list.count() - 1
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(0 <= row < last)
        self.unfirst_button.setEnabled(row >= 0)

    def put_first(self, gid: str) -> None:
        if gid and gid not in self.first:
            self.first.append(gid)
            if gid in self.skip:
                self.skip.remove(gid)
            self.refresh()

    def toggle_skip(self, gid: str) -> None:
        if not gid:
            return
        if gid in self.skip:
            self.skip.remove(gid)
        else:
            self.skip.append(gid)
            if gid in self.first:
                self.first.remove(gid)
        self.refresh()

    def delete_goal(self, gid: str) -> None:
        self.add_goals = [g for g in self.add_goals if str(g.get("id")) != gid]
        self.first = [x for x in self.first if x != gid]
        self.skip = [x for x in self.skip if x != gid]
        self.refresh()

    def move(self, step: int) -> None:
        row, to = self.first_list.currentRow(), self.first_list.currentRow() + step
        if 0 <= row < len(self.first) and 0 <= to < len(self.first):
            self.first[row], self.first[to] = self.first[to], self.first[row]
            self.refresh()
            self.first_list.setCurrentRow(to)

    def not_first(self) -> None:
        row = self.first_list.currentRow()
        if 0 <= row < len(self.first):
            del self.first[row]
            self.refresh()

    def add_goal(self, label: str, stage: str) -> str:
        """Your own goal in `stage`; its id is made from the label, kept apart
        from every goal the route already has. The id, or "" when no label."""
        label = " ".join(str(label or "").split())
        if not label:
            self._show_notes("Type what the goal is first.")
            return ""
        taken = {str(g.get("id")) for _i, g in prog._goals(prog.load(self.base))}
        taken |= {str(g.get("id")) for g in self.add_goals}
        root = prog._slug(label) or "my_goal"
        gid, n = root, 2
        while gid in taken:
            gid, n = f"{root}_{n}", n + 1
        self.add_goals.append({"id": gid, "label": label, "stage": stage})
        self.refresh()
        return gid

    def _add_clicked(self) -> None:
        if self.add_goal(self.new_label.text(), self.new_stage.currentData() or ""):
            self.new_label.clear()

    # ---- saving and sharing -------------------------------------------------
    def confirm(self, title: str, text: str) -> bool:
        """The owner says yes; tests replace this."""
        return QMessageBox.question(self.window(), title, text) == QMessageBox.Yes

    def _is_opened(self, path: Path) -> bool:
        if self.opened is None:
            return False
        try:
            return path.samefile(self.opened)      # 'Alpha.yaml' is alpha.yaml on Windows
        except OSError:
            return False

    def save(self) -> bool:
        """Writes the route file and makes it the bot's (`progression.plan`).
        A name whose file is another saved route asks first: two names can
        make one file name ('Alpha' / 'alpha'), review 2026-10-26."""
        route = self.route()
        if not route["name"]:
            self._show_notes("Give your route a name first.")
            return False
        path = prog.route_path(route["name"])
        if path.exists() and not self._is_opened(path):
            other = str(prog.read_route(path).get("name") or path.stem)
            if not self.confirm("Replace a saved route?",
                                f"Your route '{other}' is already saved as {path.name}. "
                                f"Replace it with this one?"):
                self._show_notes(f"Not saved: '{other}' already uses {path.name}. "
                                 f"Give this route another name.")
                return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_dump(route), encoding="utf-8")
        except OSError as exc:
            self._show_notes(f"Could not save {path.name}: {exc}")
            return False
        self._save(route["name"])
        self.opened, self.as_opened = path, route
        self.fill_routes()
        self._select_route(path)
        self._show_notes(f"✓ saved as {path.name}; the bot uses it from its next plan.")
        return True

    def use_researched(self) -> None:
        self._save("")
        self._show_notes("Your route stays saved; pick it and press Save and use to go back to it.")

    def import_file(self, source) -> str:
        """A shared route file copied into your routes (never over one of
        yours: a clash gets a new name). Opened here, not used until Save.
        Its name, or "" when the file is not a route."""
        import yaml
        source = Path(source)
        try:
            body = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self._show_notes(f"Could not read {source.name}: {exc}")
            return ""
        if not isinstance(body, dict) or not any(k in body for k in ROUTE_KEYS[1:]):
            self._show_notes(f"{source.name} is not a route file (it needs base, first, skip or add).")
            return ""
        route = clean_route(body, prog.hive_from(self.settings))
        name = route["name"] or source.stem
        root, n = name, 2
        while prog.route_path(name).exists():
            name, n = f"{root} {n}", n + 1
        route["name"] = name
        path = prog.route_path(name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_dump(route), encoding="utf-8")
        except OSError as exc:
            self._show_notes(f"Could not copy it in: {exc}")
            return ""
        self.fill_routes()
        self.open_route(path)
        self._show_notes(f"Imported as '{name}'. Press Save and use to follow it.")
        return name

    def export_file(self, target) -> bool:
        target = Path(target)
        route = self.route()
        route["name"] = route["name"] or target.stem
        try:
            target.write_text(_dump(route), encoding="utf-8")
        except OSError as exc:
            self._show_notes(f"Could not export: {exc}")
            return False
        self._show_notes(f"✓ exported to {target.name}; share that file.")
        return True

    def _import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self.window(), "Import a route", str(Path.home()),
                                              "Route (*.yaml *.yml)")
        if path:
            self.import_file(path)

    def _export_clicked(self) -> None:
        stem = prog._slug(self.name.text()) or "my_route"
        path, _ = QFileDialog.getSaveFileName(self.window(), "Export the route",
                                              str(Path.home() / f"{stem}.yaml"),
                                              "Route (*.yaml)")
        if path:
            self.export_file(path)

    # ---- the saved routes ---------------------------------------------------
    def fill_routes(self) -> None:
        """Every route file in the folder, by its file (a hand-written
        'My Route.yml' too, read as it is named)."""
        self.routes.clear()
        self.routes.addItem("A new route", "")
        folder = prog.route_path("x").parent
        try:
            files = sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")])
        except OSError:
            files = []
        for f in files:
            body = prog.read_route(f)
            self.routes.addItem(str(body.get("name") or f.stem), str(f))

    def _select_route(self, path) -> None:
        self.routes.setCurrentIndex(max(0, self.routes.findData(str(path) if path else "")))
