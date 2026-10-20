"""One place for colour and spacing.

Bee Swarm's own palette is yellow-on-green, which is cheerful and completely
unreadable for a dashboard you leave running for eight hours. So the window is
dark and neutral, and colour is spent only where it carries meaning: green for
a decision taken, amber for one waiting on you, red for a fault.
"""
from __future__ import annotations

from pathlib import Path

# HIVE GLASS (2026-10-09, the owner: "the current hivemind basic GUI ... looks
# super basic tacky"; his pick of the look: "u decide"). Warm honey-dark
# instead of slate: the window is a deep amber-black gradient, every panel a
# faint amber glass over it with a gold edge, and gold is still spent where it
# carries meaning -- the primary action, the selected tab, progress. GOOD /
# WARN / BAD / INFO keep their jobs.
BG = "#100c07"
BG_PANEL = "#19130b"
BG_RAISED = "#241b10"
BORDER = "#3b2d18"

TEXT = "#f5ecdc"
TEXT_DIM = "#bba98b"
# 4.5:1 OR BETTER on the panels (UI panel 2026-10-21, low vision): #7f6e54
# was 3.4:1 on BG_PANEL; #a8977a is 5.9:1
TEXT_FAINT = "#a8977a"

ACCENT = "#ffc53d"          # hive yellow
ACCENT_DEEP = "#f59e0b"     # the far end of the gold gradients
GOOD = "#4ade80"
WARN = "#fbbf24"
BAD = "#f87171"
INFO = "#60a5fa"

# PRESSED AND HOVER SHADES, because a button with no feedback is a button you
# cannot tell you pressed. The owner: "theres no click or hover animation on
# any of the buttons so i cant tell when my inputs gone though". Hover moves
# towards the gold, pressed towards black, unmistakable from each other.
BG_RAISED_HOVER = "#33260f"
BG_RAISED_PRESSED = "#160f07"
ACCENT_HOVER = "#ffd469"
ACCENT_PRESSED = "#e0a828"
BAD_HOVER = "#fb8f8f"
BAD_PRESSED = "#d95f5f"

# The glass: translucent fills and edges, over the window's gradient.
GLASS = "rgba(255, 190, 70, 0.05)"
GLASS_EDGE = "rgba(255, 197, 61, 0.22)"
GLASS_RAISED = "rgba(255, 210, 120, 0.08)"
GLASS_HOVER = "rgba(255, 197, 61, 0.16)"
HEX_UNKNOWN = "#3a3226"     # a Hive Planner cell whose bee is not known

MONO = "JetBrains Mono, DejaVu Sans Mono, monospace"
SANS = "Inter, Noto Sans, DejaVu Sans, sans-serif"

# THE GOLD BUTTON, apart so a panel can set it on the button itself: a Card's
# body says `background: transparent` to everything under it, which beats the
# window's #Primary rule and left a gold-bordered dark box (panels/telegram).
PRIMARY = f"""
QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {ACCENT_HOVER}, stop:1 {ACCENT_DEEP});
    color: #1a1206;
    border: 1px solid #ffdf8a;
    font-weight: 700;
}}
QPushButton#Primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffe8a8, stop:1 {ACCENT});
}}
QPushButton#Primary:pressed {{
    background: {ACCENT_PRESSED};
    padding-top: 8px;
    padding-bottom: 6px;
}}
QPushButton#Primary:disabled {{
    background: rgba(255, 197, 61, 0.12);
    color: {TEXT_FAINT};
    border-color: {BORDER};
}}
"""

STYLESHEET = f"""
QWidget {{
    background: transparent;
    color: {TEXT};
    font-family: {SANS};
    font-size: 13px;
}}
/* AFTER QWidget: two type selectors weigh the same, so the later wins. */
QMainWindow, QDialog {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #1c140a, stop:0.45 #0f0b06, stop:1 #1a1108);
}}
QMenu, QToolTip, QAbstractItemView, QComboBox QAbstractItemView {{
    background: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {GLASS_EDGE};
}}
QFrame#Panel {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 200, 90, 0.075), stop:1 rgba(255, 170, 40, 0.025));
    border: 1px solid {GLASS_EDGE};
    border-radius: 14px;
}}
QLabel#PanelTitle {{
    color: {ACCENT};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    padding: 8px 10px 4px 10px;
    background: transparent;
}}
QLabel#Hero {{
    font-size: 22px;
    font-weight: 800;
    color: {ACCENT};
    background: transparent;
}}
QLabel#Stat {{
    font-family: {MONO};
    font-size: 19px;
    font-weight: 700;
    color: #ffe2a0;
    background: transparent;
}}
QLabel#StatLabel {{
    color: {TEXT_FAINT};
    font-size: 10px;
    letter-spacing: 2px;
    background: transparent;
}}
QPushButton {{
    background: {GLASS_RAISED};
    border: 1px solid {GLASS_EDGE};
    border-radius: 10px;
    padding: 7px 16px;
    color: {TEXT};
}}
QPushButton:hover {{
    background: {GLASS_HOVER};
    border-color: {ACCENT};
}}
/* PRESSED HAS TO MOVE, not just change colour: a 1px downward shift is what
   makes a click feel registered at a glance. */
QPushButton:pressed {{
    background: {BG_RAISED_PRESSED};
    border-color: {ACCENT_PRESSED};
    padding-top: 8px;
    padding-bottom: 6px;
}}
QPushButton:focus {{ border-color: {ACCENT}; outline: none; }}
QPushButton:disabled {{
    color: {TEXT_FAINT};
    background: rgba(255, 255, 255, 0.02);
    border-color: {BORDER};
}}
{PRIMARY}
QPushButton#Danger {{ color: {BAD}; border-color: rgba(248, 113, 113, 0.35); }}
QPushButton#Danger:hover {{
    background: rgba(248, 113, 113, 0.14);
    color: {BAD_HOVER};
    border-color: {BAD};
}}
QPushButton#Danger:pressed {{
    background: {BG_RAISED_PRESSED};
    color: {BAD_PRESSED};
    padding-top: 8px;
    padding-bottom: 6px;
}}
QComboBox {{
    background: {GLASS_RAISED};
    border: 1px solid {GLASS_EDGE};
    border-radius: 10px;
    padding: 6px 12px;
}}
QComboBox:hover {{ background: {GLASS_HOVER}; border-color: {ACCENT}; }}
QComboBox:on {{ border-color: {ACCENT}; }}
QComboBox:disabled {{ color: {TEXT_FAINT}; }}
QComboBox QAbstractItemView {{
    selection-background-color: {BG_RAISED_HOVER};
}}
/* SWITCHES THAT SHOW WHEN THEY ARE OFF: an empty glass box, gold when on. */
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border-radius: 5px;
    border: 1px solid {GLASS_EDGE};
    background: rgba(255, 255, 255, 0.05);
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    border: 1px solid #ffdf8a;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {ACCENT_HOVER}, stop:1 {ACCENT_DEEP});
}}
QCheckBox::indicator:disabled {{ border-color: {BORDER}; background: transparent; }}
QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {GLASS_RAISED};
    border: 1px solid {GLASS_EDGE};
    border-radius: 8px;
    padding: 4px 8px;
    selection-background-color: {BG_RAISED_HOVER};
}}
QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{ border-color: {ACCENT}; }}
QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QListWidget, QTableWidget, QTextEdit, QPlainTextEdit {{
    background: transparent;
    border: none;
    selection-background-color: {BG_RAISED_HOVER};
}}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_FAINT};
    padding: 7px 15px;
    margin: 0 3px 4px 0;
    border: 1px solid transparent;
    border-radius: 12px;
}}
QTabBar::tab:hover {{ color: {TEXT}; background: {GLASS}; border-color: {GLASS_EDGE}; }}
QTabBar::tab:selected {{
    color: #1a1206;
    font-weight: 700;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {ACCENT_HOVER}, stop:1 {ACCENT_DEEP});
    border-color: #ffdf8a;
}}
QHeaderView::section {{
    background: transparent;
    color: {ACCENT};
    border: none;
    border-bottom: 1px solid {GLASS_EDGE};
    padding: 6px;
    font-size: 11px;
    font-weight: 600;
}}
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 197, 61, 0.28); border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(255, 197, 61, 0.5); }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QProgressBar {{
    background: rgba(255, 255, 255, 0.06);
    border: none; border-radius: 4px;
    height: 7px; text-align: center;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT_DEEP}, stop:1 {ACCENT_HOVER});
    border-radius: 4px;
}}
"""


def fmt_score(value: float, unit: str = "") -> str:
    """Format an option score without destroying small ones.

    A flat "{:,.0f}" turns a 1.18x multiplier into "1", which silently erases
    the difference between the options it is meant to compare. Precision
    therefore follows magnitude.
    """
    if value == 0:
        # "0 honey/hr" is information; a bare "honey/hr" reads as missing data.
        return f"0 {unit}".strip()
    magnitude = abs(value)
    if magnitude < 10:
        text = f"{value:,.2f}"
    elif magnitude < 1000:
        text = f"{value:,.1f}"
    else:
        text = f"{value:,.0f}"
    return f"{text} {unit}".strip()


# ---- THE NEW LAYOUT (gui/shell, ROADMAP U18) ---------------------------------
# The owner, 2026-10-17, on a popular macro's window: "his UI is 10000x
# better due to its simplicity and how good it looks". So the new layout drops
# Hive Glass's gradients and glow for flat, neutral greys with ONE accent, the
# amber of the approved mockup (docs/pending/ui18_mockup.html). These rules
# are appended after STYLESHEET on the shell window only, so the classic
# window keeps its look; the old panels embedded in the shell pick up the
# flat cards and controls from here.
# the dropdown's arrow: QSS draws an image or nothing once the drop-down is styled
CHEVRON = (Path(__file__).resolve().parents[3]
           / "data" / "brand" / "chevron-down.svg").as_posix()
S_BG = "#121418"
S_PANEL = "#1b1e25"
S_CARD = "#232731"
S_CARD_HOVER = "#2a2f3a"
S_LINE = "#2e333f"
S_TEXT = "#eceae4"
S_DIM = "#9a9fab"
# THE FAINT TEXT READS (UI panel 2026-10-21, low vision): #6b707c was 3.0:1
# on a card; #8a8f9b is 4.6:1 on S_CARD, 5.2:1 on S_PANEL. Disabled controls
# keep the old grey, S_DISABLED, so they still look switched off.
S_FAINT = "#8a8f9b"
S_DISABLED = "#6b707c"
S_AMBER = "#f5aa1c"
S_AMBER_HOVER = "#ffbb3d"
S_AMBER_PRESSED = "#d99412"
S_ON_AMBER = "#14161a"      # text on an amber fill
S_GOOD = "#3ccf7a"
S_BAD = "#e5484d"

def use_shell_palette() -> None:
    """THE OLD PANELS IN THE NEW FRAME, IN ITS GREYS. Every panel reads its
    colours as `theme.X` when it draws or restyles, so rebinding the Hive
    Glass names here (before the shell builds them) turns the warm browns
    and gold gradients flat and neutral, with no change to any panel. Only
    the shell calls it, and a process builds one window, so the classic
    window keeps its look. GOOD / WARN / BAD / INFO keep their jobs."""
    global BG, BG_PANEL, BG_RAISED, BORDER, TEXT, TEXT_DIM, TEXT_FAINT
    global ACCENT, ACCENT_DEEP, ACCENT_HOVER, ACCENT_PRESSED, BG_RAISED_HOVER
    global BG_RAISED_PRESSED, GLASS, GLASS_EDGE, GLASS_RAISED, GLASS_HOVER, PRIMARY
    global HEX_UNKNOWN
    HEX_UNKNOWN = S_LINE
    BG, BG_PANEL, BG_RAISED, BORDER = S_BG, S_PANEL, S_CARD, S_LINE
    TEXT, TEXT_DIM, TEXT_FAINT = S_TEXT, S_DIM, S_FAINT
    ACCENT, ACCENT_DEEP, ACCENT_HOVER, ACCENT_PRESSED = (
        S_AMBER, S_AMBER, S_AMBER_HOVER, S_AMBER_PRESSED)
    BG_RAISED_HOVER, BG_RAISED_PRESSED = S_CARD_HOVER, S_PANEL
    GLASS, GLASS_EDGE, GLASS_RAISED, GLASS_HOVER = S_PANEL, S_LINE, S_CARD, S_CARD_HOVER
    PRIMARY = f"""
QPushButton#Primary {{
    background: {S_AMBER}; color: {S_ON_AMBER}; border: 1px solid {S_AMBER};
    font-weight: 700;
}}
QPushButton#Primary:hover {{ background: {S_AMBER_HOVER}; }}
QPushButton#Primary:pressed {{ background: {S_AMBER_PRESSED}; }}
QPushButton#Primary:disabled {{
    background: {S_PANEL}; color: {S_DISABLED}; border-color: {S_LINE};
}}
"""


SHELL = f"""
QMainWindow, QDialog {{ background: {S_BG}; }}
QWidget {{ color: {S_TEXT}; }}
QToolTip {{
    background: {S_PANEL}; color: {S_TEXT};
    border: 1px solid {S_LINE}; border-radius: 6px; padding: 6px 8px;
}}
QMenu, QAbstractItemView, QComboBox QAbstractItemView {{
    background: {S_PANEL}; color: {S_TEXT}; border: 1px solid {S_LINE};
    selection-background-color: {S_CARD_HOVER};
}}
QFrame#Panel {{
    background: {S_PANEL};
    border: 1px solid {S_LINE};
    border-radius: 10px;
}}
QLabel#PanelTitle {{ color: {S_AMBER}; }}
QLabel#Hero {{ color: {S_AMBER}; }}
QLabel#Stat {{ color: {S_TEXT}; }}
QLabel#StatLabel {{ color: {S_DIM}; }}
QPushButton {{
    background: {S_CARD}; border: 1px solid {S_LINE}; border-radius: 8px;
    padding: 7px 14px; color: {S_TEXT};
}}
QPushButton:hover {{ background: {S_CARD_HOVER}; border-color: {S_FAINT}; }}
QPushButton:pressed {{ background: {S_PANEL}; padding-top: 8px; padding-bottom: 6px; }}
QPushButton:focus {{ border-color: {S_AMBER}; }}
QPushButton:disabled {{ color: {S_DISABLED}; background: {S_PANEL}; border-color: {S_LINE}; }}
QPushButton#Primary {{
    background: {S_AMBER}; color: {S_ON_AMBER}; border: 1px solid {S_AMBER};
    font-weight: 700;
}}
QPushButton#Primary:hover {{ background: {S_AMBER_HOVER}; }}
QPushButton#Primary:pressed {{ background: {S_AMBER_PRESSED}; }}
QPushButton#Primary:disabled {{
    background: {S_PANEL}; color: {S_DISABLED}; border-color: {S_LINE};
}}
QPushButton#Danger {{ color: {S_BAD}; border-color: {S_LINE}; }}
QPushButton#Danger:hover {{ background: {S_CARD_HOVER}; border-color: {S_BAD}; }}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {S_PANEL}; border: 1px solid {S_LINE}; border-radius: 7px;
    padding: 4px 10px; color: {S_TEXT};
    selection-background-color: {S_CARD_HOVER};
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{
    border-color: {S_FAINT}; background: {S_PANEL};
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus,
QComboBox:on {{ border-color: {S_AMBER}; }}
QSpinBox#Num::up-button, QSpinBox#Num::down-button,
QDoubleSpinBox#Num::up-button, QDoubleSpinBox#Num::down-button {{
    width: 0px; border: none;
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({CHEVRON}); width: 12px; height: 12px; }}
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled {{ color: {S_DISABLED}; }}
QCheckBox::indicator {{
    border: 1px solid {S_LINE}; background: {S_PANEL}; border-radius: 4px;
}}
QCheckBox::indicator:hover {{ border-color: {S_FAINT}; }}
QCheckBox::indicator:checked {{ border: 1px solid {S_AMBER}; background: {S_AMBER}; }}
QTabBar::tab {{ color: {S_DIM}; border-radius: 13px; }}
QTabBar::tab:hover {{ color: {S_TEXT}; background: {S_CARD}; border-color: {S_LINE}; }}
QTabBar::tab:selected {{
    color: {S_ON_AMBER}; background: {S_AMBER}; border-color: {S_AMBER};
}}
QHeaderView::section {{ color: {S_DIM}; border-bottom: 1px solid {S_LINE}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {S_LINE}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {S_FAINT}; }}
QProgressBar {{ background: {S_PANEL}; }}
QProgressBar::chunk {{ background: {S_AMBER}; border-radius: 4px; }}

/* the frame: top bar, side menu, bottom bar */
QWidget#TopBar {{ background: {S_PANEL}; border-bottom: 1px solid {S_LINE}; }}
QLabel#Brand {{ font-size: 15px; font-weight: 800; color: {S_TEXT}; }}
QPushButton#TopTab {{
    background: transparent; border: 1px solid transparent; border-radius: 9px;
    color: {S_DIM}; font-weight: 600; padding: 7px 14px;
    letter-spacing: 1px;
}}
QPushButton#TopTab:hover {{ color: {S_TEXT}; background: {S_CARD}; }}
QPushButton#TopTab:checked {{ color: {S_AMBER}; background: {S_CARD}; border-color: {S_LINE}; }}
QListWidget#SideMenu {{
    background: {S_PANEL}; border: none; border-right: 1px solid {S_LINE};
    padding: 10px 8px; outline: none;
}}
QListWidget#SideMenu::item {{
    color: {S_DIM}; padding: 5px 12px; margin-bottom: 1px; border-radius: 8px;
}}
QListWidget#SideMenu::item:hover {{ background: {S_CARD}; color: {S_TEXT}; }}
QListWidget#SideMenu::item:selected {{
    background: {S_AMBER}; color: {S_ON_AMBER}; font-weight: 700;
}}
QListWidget#SideMenu::item:disabled {{
    color: {S_FAINT}; background: transparent; font-size: 10px; font-weight: 700;
    padding: 10px 12px 3px 12px; letter-spacing: 1px;
}}
QPushButton#Pill {{
    background: transparent; border: 1px solid {S_LINE}; border-radius: 13px;
    color: {S_DIM}; padding: 4px 14px;
}}
QPushButton#Pill:hover {{ color: {S_TEXT}; border-color: {S_FAINT}; }}
QPushButton#Pill:checked {{
    background: {S_AMBER}; border-color: {S_AMBER}; color: {S_ON_AMBER}; font-weight: 700;
}}
QFrame#SettingCard {{
    background: {S_CARD}; border: 1px solid {S_LINE}; border-radius: 10px;
}}
QFrame#SettingCard:hover {{ border-color: {S_FAINT}; }}
QLabel#Help {{
    background: {S_LINE}; color: {S_DIM}; border-radius: 8px;
    font-size: 10px; font-weight: 700;
}}
QLabel#Help:hover {{ background: {S_FAINT}; color: {S_TEXT}; }}
QLabel#Section {{
    color: {S_AMBER}; font-size: 11px; font-weight: 700; letter-spacing: 1px;
}}
QLabel#Dim {{ color: {S_DIM}; }}
QLabel#Badge {{
    border: 1px solid {S_FAINT}; border-radius: 7px; padding: 0 6px;
    font-size: 10px; font-weight: 700; color: {S_DIM};
}}
QLabel#Badge[kind="live"] {{ color: {S_GOOD}; border-color: {S_GOOD}; }}
QLabel#Badge[kind="look-only"] {{ color: {S_AMBER}; border-color: {S_AMBER}; }}
QFrame#Note {{
    background: {S_CARD}; border: 1px solid {S_LINE};
    border-left: 3px solid {S_AMBER}; border-radius: 10px;
}}
QFrame#BottomBar {{ background: {S_PANEL}; border-top: 1px solid {S_LINE}; }}
QFrame#BarRow {{ background: {S_CARD}; border-radius: 8px; }}
QPushButton#Run {{ padding: 8px 12px; font-weight: 800; text-align: left; }}
QPushButton#Run[primary="true"] {{
    background: {S_AMBER}; color: {S_ON_AMBER}; border-color: {S_AMBER};
}}
QPushButton#Run[primary="true"]:hover {{ background: {S_AMBER_HOVER}; }}
QPushButton#Run[primary="true"]:disabled {{
    background: {S_CARD}; color: {S_DISABLED}; border-color: {S_LINE};
}}
QComboBox#Preset {{ background: transparent; border: none; padding: 2px 6px; }}
QComboBox#Preset:hover {{ background: {S_PANEL}; }}

/* search, pickers */
QPushButton#SearchButton {{
    background: {S_CARD}; border: 1px solid {S_LINE}; border-radius: 9px;
    color: {S_DIM}; padding: 6px 14px; text-align: left; min-width: 150px;
}}
QPushButton#SearchButton:hover {{ color: {S_TEXT}; border-color: {S_FAINT}; }}
QFrame#Popup {{
    background: {S_PANEL}; border: 1px solid {S_FAINT}; border-radius: 12px;
}}
QLineEdit#PaletteSearch {{ font-size: 15px; padding: 8px 12px; }}
QListWidget#Results, QListWidget#ItemList {{ background: transparent; outline: none; }}
QListWidget#Results::item {{ padding: 7px 10px; border-radius: 8px; color: {S_TEXT}; }}
QListWidget#ItemList::item {{ padding: 5px 8px; border-radius: 8px; color: {S_TEXT}; }}
QListWidget#Results::item:hover, QListWidget#ItemList::item:hover {{ background: {S_CARD}; }}
QListWidget#Results::item:selected, QListWidget#ItemList::item:selected {{
    background: {S_CARD_HOVER}; color: {S_TEXT}; border-left: 3px solid {S_AMBER};
}}
QListWidget#ItemList {{
    background: {S_CARD}; border: 1px solid {S_LINE}; border-radius: 10px; padding: 4px;
}}
QToolButton#FieldTile {{
    background: {S_CARD}; border: 1px solid {S_LINE}; border-radius: 10px;
    color: {S_TEXT}; font-size: 11px; padding: 6px 2px 4px 2px;
}}
QToolButton#FieldTile:hover {{ border-color: {S_FAINT}; background: {S_CARD_HOVER}; }}
QToolButton#FieldTile:checked {{ border: 2px solid {S_AMBER}; }}
QPushButton:disabled#Run {{ color: {S_DISABLED}; }}

/* macro mode's field list (U16) */
QFrame#FieldRow {{
    background: {S_CARD}; border: 1px solid {S_LINE}; border-radius: 10px;
}}
QFrame#FieldRow:hover {{ border-color: {S_FAINT}; }}
QFrame#FieldRow[selected="true"] {{ border: 1px solid {S_AMBER}; }}
QToolButton#Kebab {{
    background: transparent; border: 1px solid transparent; border-radius: 7px;
    color: {S_DIM}; font-size: 16px; font-weight: 800; padding: 0 6px;
}}
QToolButton#Kebab:hover {{ background: {S_CARD_HOVER}; color: {S_TEXT}; }}
QToolButton#Kebab::menu-indicator {{ image: none; width: 0px; }}
QMenu::item {{ padding: 5px 18px; }}
QMenu::item:selected {{ background: {S_CARD_HOVER}; }}
QMenu::item:disabled {{ color: {S_DISABLED}; }}
"""
