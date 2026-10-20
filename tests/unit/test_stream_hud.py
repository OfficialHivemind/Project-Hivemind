"""Stream mode's HUD layout (gui/stream_hud): the game fills the window and the
cards float on it, clear of Bee Swarm's own HUD. The owner, 2026-10-06: "it
should be like the whole screen is like the bots view plus overlays"."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QRect  # noqa: E402

# Bee Swarm's own HUD on a 1920x1080 frame (gui/stream _ToastLayer's survey):
# the menu icons, the honey and pollen counters, the hotbar, the game's notices
GAME_HUD = {"menu icons": QRect(0, 0, 340, 160), "counters": QRect(660, 10, 590, 56),
            "hotbar": QRect(700, 940, 650, 140), "notices": QRect(1560, 970, 360, 110)}


def _window(qt_app, tmp_path, **settings):
    from hivemind.gui.stream import StreamWindow
    settings.setdefault("stream.voice", False)
    return StreamWindow(settings=settings, var_root=tmp_path)


def test_the_game_fills_the_window_and_the_cards_keep_off_the_games_hud(qt_app, tmp_path):
    win = _window(qt_app, tmp_path)
    try:
        assert win._hud
        assert (win.view.width(), win.view.height()) == (1920, 1080)
        assert win.view.viewfinder is not None
        cards = {"header": win.header, "now": win.now, "thinking": win.thinking,
                 "stats": win.stats, "pager": win.pager, "chat": win.chat,
                 "subtitle": win.subtitle}
        canvas = QRect(0, 0, 1920, 1080)
        for name, card in cards.items():
            rect = card.geometry()
            assert canvas.contains(rect), (name, rect)
            for hud, zone in GAME_HUD.items():
                assert not rect.intersects(zone), f"{name} {rect} covers the {hud} {zone}"
        assert win.view.toasts.anchor == "top-centre"
    finally:
        win.close()


def test_over_the_key_colour_the_cards_are_solid(qt_app, tmp_path):
    win = _window(qt_app, tmp_path, **{"stream.game_view": "key colour"})
    try:
        css = win.styleSheet()
        assert "rgb(13,15,21)" in css and "rgba(9,11,17" not in css
        assert win.view.viewfinder.keyed
    finally:
        win.close()


def test_the_classic_layout_is_still_there(qt_app, tmp_path):
    win = _window(qt_app, tmp_path, **{"stream.layout": "classic"})
    try:
        assert not win._hud
        assert (win.view.width(), win.view.height()) == (1280, 720)
        assert win.view.viewfinder is None
    finally:
        win.close()


def test_the_cards_follow_the_key_colour_while_open(qt_app, tmp_path):
    win = _window(qt_app, tmp_path)
    try:
        assert "rgba(9,11,17" in win.styleSheet()
        win.setting_changed("stream.game_view", "key colour")
        assert "rgb(13,15,21)" in win.styleSheet() and win.view.viewfinder.keyed
        win.setting_changed("stream.game_view", "live view")
        assert "rgba(9,11,17" in win.styleSheet() and not win.view.viewfinder.keyed
    finally:
        win.close()


def test_the_reticle_shows_only_while_the_bot_gathers(qt_app, tmp_path):
    # the owner, 2026-10-06: "make it smaller and only show while gathering"
    from hivemind.telemetry.events import TaskUpdate
    win = _window(qt_app, tmp_path)
    try:
        finder = win.view.viewfinder
        assert not finder.gathering                       # nothing yet
        win.handle(TaskUpdate(name="travel to the field", status="running", progress=-1))
        assert not finder.gathering
        win.handle(TaskUpdate(name="gather", status="running", progress=0.4))
        assert finder.gathering
        win.handle(TaskUpdate(name="gather", status="done", progress=1.0))
        assert not finder.gathering
    finally:
        win.close()


def _wait(ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_the_left_cards_make_way_while_the_bot_reads_a_game_menu(qt_app, tmp_path):
    # the game's inventory, quest and bee menus open on the left, under them
    # (the owner's screen, 2026-10-06 21:46)
    from hivemind.gui import stream_hud
    from hivemind.telemetry.events import Log
    win = _window(qt_app, tmp_path)
    try:
        win.handle(Log(message="reading the inventory — once a session, on the pad with the bag empty"))
        _wait(600)
        assert all(card.x() + card.width() <= 0 for card in (win.stats, win.pager, win.chat))
        win.handle(Log(message="inventory: read 6 page(s) of the inventory in 67s: ant_pass 8"))
        _wait(600)
        assert all(card.x() == stream_hud.LEFT_X for card in (win.stats, win.pager, win.chat))
        # an old line replayed as the window opens moves nothing
        win.handle(Log(message="reading the quest menu — it was due"), quiet=True)
        _wait(100)
        assert win.stats.x() == stream_hud.LEFT_X
    finally:
        win.close()


def test_the_stream_shows_the_vision_brackets_without_the_landmark_words(qt_app, tmp_path):
    win = _window(qt_app, tmp_path)
    try:
        assert win.view.live.landmark_words is False
    finally:
        win.close()
    from hivemind.gui.panels.liveview import LiveView
    assert LiveView().landmark_words is True          # the main window keeps them


def test_a_short_shopping_card_drops_rows_instead_of_overlapping(qt_app):
    """UI panel round 2 (2026-10-22, the streamer): three rows squeezed into a
    short card were drawn over each other."""
    from PySide6.QtWidgets import QWidget
    from hivemind.gui.stream import _GoalsCard
    host = QWidget()                     # a child is not grown to its minimum
    host.resize(400, 1000)
    card = _GoalsCard()
    card.setParent(host)
    card._wanted = 3
    host.show()
    card.setGeometry(0, 0, 380, 190)
    shown = sum(not row[0].isHidden() for row in card._rows)
    assert shown < 3
    assert shown == 1 or card.layout().minimumSize().height() <= card.height()
    card.setGeometry(0, 0, 380, 900)
    assert all(not row[0].isHidden() for row in card._rows)
    host.close()
