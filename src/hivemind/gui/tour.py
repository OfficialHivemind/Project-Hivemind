"""The first-week tour (ROADMAP U10): what each tab is for, shown once.

A small card in the corner of the new window (gui/shell), one step per tab:
a plain sentence on what the tab is for and the one page to look at first.
Each step opens that tab and page, so the words sit beside the thing they
describe. Next / Skip; Settings > Help > "Show the tour again" brings it back.

IT ACTS ON NOTHING IN THE GAME and blocks nothing: it is not a dialog, the
window behind it works as usual, and Skip is always one click away. A demo
(UI Preview) may show it too, once, in the demo's own config folder
(datapaths.use_demo_dirs), so the real app still shows it on its first open.

SHOWN ONCE: the `tour-seen` marker sits in the config folder beside gui/app's
`first-run-passed`, and is written when the tour is skipped or finished.
# ponytail: a window closed mid-tour leaves no marker, so the tour starts
# again on the next open; it was not seen to the end, and Skip stops it.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

MARKER_NAME = "tour-seen"

# (tab key in shell.TABS, the page to look at first, the plain words).
# Short sentences, for a ten-year-old and for someone reading in a second
# language (the Help page's rule, UI panel 2026-10-21 item 11).
STEPS = (
    ("plan", "Plan",
     "Plan is where you tell the bot what to do. Look at Plan first: pick one "
     "thing, and it shows what it is doing now, why, and what comes next."),
    ("boost", "Boosts",
     "Boosting keeps your boosts and their timers in one place. Look at "
     "Boosts first: each boost shows how long it has left."),
    ("stats", "Overview",
     "Stats shows how the bot is doing. Look at Overview first: your honey, "
     "pollen and bees this session, and the graphs."),
    ("settings", "General",
     "Settings has everything else. Look at General first: it says what the "
     "bot never does and how to stop it. Turn on Advanced mode there to see "
     "every option. Help explains the game's words."),
)


def marker_path() -> Path:
    from ..datapaths import config_dir
    return config_dir() / MARKER_NAME


class Tour(QFrame):
    """The card. `window` is the shell (it has `_show_tab` and `_menus`)."""

    MARGIN = 18

    def __init__(self, window, marker: Path | None = None, parent=None):
        super().__init__(parent if parent is not None else window.centralWidget())
        self.window = window
        self.marker = marker or marker_path()
        self.step = 0
        self.setObjectName("Note")                   # the amber-edged card
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(360)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(8)
        self.head = QLabel()
        self.head.setObjectName("Section")
        self.body = QLabel()
        self.body.setWordWrap(True)
        box.addWidget(self.head)
        box.addWidget(self.body)
        row = QHBoxLayout()
        row.addStretch(1)
        self.skip_button = QPushButton("Skip")
        self.skip_button.setToolTip("Close the tour. Settings > Help can show it again.")
        self.skip_button.clicked.connect(self.skip)
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("Primary")
        self.next_button.clicked.connect(self.next)
        row.addWidget(self.skip_button)
        row.addWidget(self.next_button)
        box.addLayout(row)
        self._follow = _Follow(self)
        self.parentWidget().installEventFilter(self._follow)
        self._show_step()

    def _show_step(self) -> None:
        key, page, text = STEPS[self.step]
        self.head.setText(f"QUICK TOUR · {self.step + 1} OF {len(STEPS)}")
        self.body.setText(text)
        last = self.step == len(STEPS) - 1
        self.next_button.setText("Done" if last else "Next")
        self.skip_button.setVisible(not last)
        # OPEN THE TAB AND THE PAGE the words are about (navigation only)
        try:
            self.window._show_tab(key)
            menu = self.window._menus[key]
            rows = [menu.item(r).text() for r in range(menu.count())]
            if page in rows:
                menu.setCurrentRow(rows.index(page))
        except (AttributeError, KeyError):
            pass                                   # a window without that tab
        self.adjustSize()
        self.place()

    def next(self) -> None:
        if self.step >= len(STEPS) - 1:
            self.finish()
            return
        self.step += 1
        self._show_step()

    def skip(self) -> None:
        self.finish()

    def finish(self) -> None:
        """Skip or Done: never shown by itself again."""
        try:
            self.marker.parent.mkdir(parents=True, exist_ok=True)
            self.marker.write_text("the first-week tour was seen\n", encoding="utf-8")
        except OSError:
            pass                                   # a read-only folder: it shows again
        self.hide()
        self.parentWidget().removeEventFilter(self._follow)
        self.deleteLater()
        if getattr(self.window, "tour", None) is self:
            self.window.tour = None

    def place(self) -> None:
        """Bottom right of the window's middle, above the run bar."""
        parent = self.parentWidget()
        bottom = parent.height()
        pages = getattr(self.window, "tab_stack", None)
        if pages is not None and pages.parentWidget() is parent:
            bottom = pages.geometry().bottom()    # the run bar sits below it
        x = max(0, parent.width() - self.width() - self.MARGIN)
        y = max(0, bottom - self.height() - self.MARGIN)
        self.move(x, y)
        self.raise_()


class _Follow(QObject):
    """Keeps the card in its corner when the window is resized."""

    def __init__(self, tour: Tour):
        super().__init__(tour)
        self.tour = tour

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Resize, QEvent.Show):
            self.tour.place()
        return False


class _AfterClose(QObject):
    """Shows the tour once `first` (the set-up window) has closed."""

    def __init__(self, first, window, marker: Path | None):
        super().__init__(first)                    # lives as long as that window
        self.window, self.marker = window, marker

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Close and self.window is not None:
            window, self.window = self.window, None
            obj.removeEventFilter(self)
            try:
                show_tour(window, self.marker)
            except Exception:
                window.tour = None                 # gui/app's rule: no tour, not a crash
        return False


def show_tour_after(window, first, marker: Path | None = None) -> None:
    """THE TOUR WAITS FOR SET-UP (usability triage 2026-10-26 #16): the
    first-run window and the tour card opened together, two things asking
    for a new player's eyes. With a first-run window (`first`) open, the
    tour shows when it closes; with none, now."""
    if first is None:
        show_tour(window, marker)
    else:
        first.installEventFilter(_AfterClose(first, window, marker))


def show_tour(window, marker: Path | None = None, force: bool = False) -> Tour | None:
    """The tour, shown, when it is wanted; else None. `force` is the Help
    page's button: shown again whatever the marker says. Only the new
    window has the tabs it describes."""
    if not hasattr(window, "_menus") or window.centralWidget() is None:
        return None
    marker = marker or marker_path()
    if not force and marker.exists():
        return None
    old = getattr(window, "tour", None)
    if old is not None:
        try:
            old.hide()
            old.deleteLater()
        except RuntimeError:
            pass                                   # already gone
    tour = Tour(window, marker=marker)
    tour.show()
    tour.place()
    window.tour = tour
    return tour
