"""ROADMAP U7, the rest of accessibility: gui.colour_blind swaps the status
colours to a colour-blind-safe set (gui/theme), and Ctrl+1..N open the shown
tabs of the new layout (gui/shell). Offscreen; the real settings are never
read or written."""
from __future__ import annotations

import importlib
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hivemind.gui import theme  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402


def _lum(hex_colour: str) -> float:
    """WCAG 2 relative luminance."""
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_safe_colours_read_and_good_and_bad_split_on_blue_yellow():
    safe = theme.COLOUR_BLIND
    for name in ("GOOD", "BAD", "WARN", "INFO"):
        for bg in (theme.S_CARD, theme.S_PANEL, theme.BG_PANEL):
            assert _contrast(safe[name], bg) >= 4.5, (name, bg)
    # red-green blind readers keep the blue channel: good and bad differ there
    blue = lambda c: int(c[5:7], 16)  # noqa: E731
    assert blue(safe["GOOD"]) - blue(safe["BAD"]) > 0x80
    assert safe["INFO"] != safe["GOOD"]


def test_the_swap_rebinds_the_names_and_the_sheets():
    try:
        old_bad = theme.BAD
        assert old_bad in theme.STYLESHEET
        theme.use_colour_blind_palette()
        assert theme.GOOD == theme.S_GOOD == theme.COLOUR_BLIND["GOOD"]
        assert old_bad not in theme.STYLESHEET
        assert theme.COLOUR_BLIND["S_GOOD"] in theme.SHELL
    finally:
        importlib.reload(theme)            # the other tests keep the usual set


def test_the_setting_is_a_window_setting_read_at_start():
    keys = {row[0]: row for _, rows in schema.SECTIONS for row in rows}
    assert keys["gui.colour_blind"][3] is False
    assert schema.takes_effect("gui.colour_blind") == "when the app next starts"
    from hivemind.gui import app
    assert "use_colour_blind_palette" in open(app.__file__, encoding="utf-8").read()


def test_ctrl_number_opens_the_shown_tabs(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    path = tmp_path / "settings.yaml"
    from hivemind.gui.panels import settings as panel_mod
    monkeypatch.setattr(panel_mod, "CONFIG", path)
    monkeypatch.setattr(schema, "CONFIG", path)
    monkeypatch.setattr(schema.Settings.__init__, "__defaults__", (path,))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    from hivemind.gui.bridge import EventBridge
    from hivemind.gui.shell import ShellWindow

    class Bot:
        process = None
        log_path = "nowhere"
        running = staticmethod(lambda: False)
        describe_state = staticmethod(lambda: "")
        exit_code = staticmethod(lambda: None)

    window = ShellWindow(EventBridge(), bot=Bot())
    try:
        window.tab_by_number(3)
        assert window.tab_buttons["stats"].isChecked()
        window.tab_by_number(9)                    # no 9th tab: nothing moves
        assert window.tab_buttons["stats"].isChecked()
    finally:
        window.close()
        window.deleteLater()


# CATEGORY TABLES: names of things (graph groups, live-view boxes, seeds,
# timers, the stream's event tags, the gather reticle), not good/bad; ROADMAP
# U7 keeps them as they are.
_CATEGORY_TABLES = {
    ("hivemind.gui.panels.graphs", "GROUP_COLOURS"),
    ("hivemind.gui.panels.liveview", "DETECTION_COLOURS"),
    ("hivemind.gui.panels.planters", "SEED_COLOURS"),
    ("hivemind.gui.panels.timers", "CATEGORY_COLOURS"),
    ("hivemind.gui.stream", "CATEGORY"),
    ("hivemind.gui.stream_extras", "EXTRA_CATEGORY"),
    ("hivemind.gui.stream_hud", "GATHER_TINT"),
}


def _old_hexes(value, old, module, depth=0):
    """The old hexes in a module or class table (dicts, tuples, a class's own
    attributes), a few levels deep."""
    if isinstance(value, str):
        return {h for h in old if h in value.lower()}
    if depth > 3:
        return set()
    if isinstance(value, dict):
        value = list(value.keys()) + list(value.values())
    if isinstance(value, type) and value.__module__ == module:
        value = [v for k, v in vars(value).items() if not k.startswith("__")]
    if isinstance(value, (list, tuple, set, frozenset)):
        return set().union(*(_old_hexes(v, old, module, depth + 1) for v in value))
    return set()


def test_no_panel_keeps_an_old_status_hex_after_the_swap():
    """Every hivemind.gui module, imported with gui.app the way main() has
    them before it swaps, then swapped: no module or class table (gear/goals
    STATE_COLOUR, sentinel SEVERITY_COLOURS, simple ACTIVITY, plan STATE_LOOK,
    the stream's goals card and its own status badge _Header.STATES) may
    still hold an old GOOD/BAD/WARN/INFO/S_GOOD/S_BAD hex."""
    import pkgutil
    import hivemind.gui as gui
    from hivemind.gui import app  # noqa: F401
    modules = [importlib.import_module(m.name)
               for m in pkgutil.walk_packages(gui.__path__, "hivemind.gui.")
               if not m.name.endswith("__main__")]
    old = {getattr(theme, n).lower() for n in theme.COLOUR_BLIND}
    try:
        theme.use_colour_blind_palette()
        left = {(m.__name__, k): hexes for m in modules if m is not theme
                for k, v in vars(m).items()
                if (m.__name__, k) not in _CATEGORY_TABLES
                and (hexes := _old_hexes(v, old, m.__name__))}
        assert not left, left
    finally:
        importlib.reload(theme)            # the other tests keep the usual set


def test_the_stream_badge_draws_the_swapped_colour():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from hivemind.gui import stream
    try:
        theme.use_colour_blind_palette()
        header = stream._Header()
        header.set_state("live")
        assert theme.COLOUR_BLIND["GOOD"] in header.state.styleSheet()
        header.deleteLater()
    finally:
        importlib.reload(theme)
