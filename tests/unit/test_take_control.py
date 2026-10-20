"""Take control through the live view (RL1b step 3).

Headless, the game has no window a person can click: while the owner has the
controls the live view forwards their mouse and keys as GameInput, and the bot
applies them through its own input -- only then, and only there. The live
check at the bottom drives a headless labwc with a stand-in game window,
through the real socket, from the real widget.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt              # noqa: E402
from PySide6.QtGui import (QFocusEvent, QKeyEvent, QMouseEvent,     # noqa: E402
                           QWheelEvent)
from PySide6.QtWidgets import QApplication                           # noqa: E402

from hivemind.brain.controls import Controls                         # noqa: E402
from hivemind.gui.panels import liveview as lv                       # noqa: E402
from hivemind.ipc.bus import EventClient, EventServer                # noqa: E402
from hivemind.telemetry.events import (Action, Command, Frame,       # noqa: E402
                                       GameInput, StatusUpdate, from_json)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeInput:
    def __init__(self):
        self.calls = []

    def move_mouse(self, x, y):
        self.calls.append(("move", round(x), round(y)))

    def mouse_button(self, name, down):
        if name not in ("left", "right", "middle"):
            raise KeyError(name)
        self.calls.append(("button", name, down))

    def press(self, *keys):
        if keys[0] == "nope":
            raise KeyError("unknown key 'nope'")
        self.calls.append(("press",) + keys)

    def release(self, *keys):
        self.calls.append(("release",) + keys)

    def scroll(self, steps, horizontal=False):
        self.calls.append(("scroll", steps))

    def release_all(self):
        self.calls.append(("release_all",))


# ---- the bot's half: brain/controls ----------------------------------------
def test_game_input_travels_as_one_json_line():
    back = from_json(GameInput(op="key_down", key="w").to_json())
    assert isinstance(back, GameInput) and back.op == "key_down" and back.key == "w"


def test_nothing_reaches_the_game_unless_the_owner_has_the_controls():
    vin = FakeInput()
    c = Controls(vin=vin)
    assert c.owner_input(GameInput(op="key_down", key="w")) is False
    c.handle(Command(action=Action.TAKE_OVER))
    vin.calls.clear()                     # the handover's own release
    # asked for, not yet given: the step in progress still owns the input
    assert c.handle(GameInput(op="key_down", key="w")) is None
    assert vin.calls == [] and c.owner_dropped == 2
    c._resume.wait(0)                     # the loop parks
    assert c.owner_input(GameInput(op="key_down", key="w"))
    assert vin.calls == [("press", "w")]


def test_every_op_goes_through_the_bots_own_input():
    vin = FakeInput()
    c = Controls(vin=vin)
    c.owner_drives()
    vin.calls.clear()
    for event in (GameInput(op="move", x=960.4, y=540.6), GameInput(op="down", button="left"),
                  GameInput(op="up", button="left"), GameInput(op="key_down", key="space"),
                  GameInput(op="key_up", key="space"), GameInput(op="scroll", steps=-2),
                  GameInput(op="release_all")):
        c.handle(event)
    assert vin.calls == [("move", 960, 541), ("button", "left", True),
                         ("button", "left", False), ("press", "space"),
                         ("release", "space"), ("scroll", -2), ("release_all",)]


def test_a_bad_input_is_dropped_not_raised():
    """It runs on the socket's reader thread: a raise would end it."""
    vin = FakeInput()
    c = Controls(vin=vin)
    c.owner_drives()
    assert c.owner_input(GameInput(op="key_down", key="nope")) is False
    assert c.owner_input(GameInput(op="down", button="thumb")) is False
    assert c.owner_input(GameInput(op="dance")) is False
    assert c.owner_dropped == 3


def test_stop_and_pass_back_end_it_and_let_go():
    vin = FakeInput()
    c = Controls(vin=vin)
    c.owner_drives()
    vin.calls.clear()
    c.handle(Command(action=Action.PASS_BACK))
    assert vin.calls == [("release_all",)], "what the owner held must come up first"
    assert c.owner_input(GameInput(op="key_down", key="w")) is False
    c.owner_drives()
    c.handle(Command(action=Action.STOP))
    assert c.owner_input(GameInput(op="key_down", key="w")) is False


def test_owner_drives_tells_the_gui_the_controls_are_his():
    sent = []
    c = Controls(vin=FakeInput(), emit=sent.append)
    c.owner_drives()
    status = [e for e in sent if isinstance(e, StatusUpdate)][-1]
    assert status.handed_over and not status.handing_over


def test_over_the_real_socket(tmp_path):
    vin = FakeInput()
    c = Controls(vin=vin)
    path = str(tmp_path / "hm.sock")
    with EventServer(path, on_message=c.handle) as server:
        c.emit = server.send
        c.owner_drives()
        client = EventClient(path).start()
        deadline = time.monotonic() + 5
        while not client.connected and time.monotonic() < deadline:
            time.sleep(0.02)
        vin.calls.clear()
        assert client.send(GameInput(op="key_down", key="w"))
        while not vin.calls and time.monotonic() < deadline:
            time.sleep(0.02)
        client.stop()
    assert vin.calls == [("press", "w")]


# ---- the GUI's half: panels/liveview ----------------------------------------
@pytest.fixture
def view(app):
    w = lv.LiveView()
    w.resize(960, 640)                     # 960x540 picture, 50 px bars top and bottom
    w.show()
    sent = []
    w.set_take_control(True, sent.append)
    w.setFocus()
    app.processEvents()
    yield w, sent
    w.set_take_control(False)
    w.close()


def _mouse(kind, x, y, button=Qt.LeftButton):
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button,
                       button if kind != QEvent.MouseButtonRelease else Qt.NoButton,
                       Qt.NoModifier)


def _key(kind, key, repeat=False):
    return QKeyEvent(kind, key, Qt.NoModifier, "", repeat)


def test_widget_points_scale_to_the_game_and_bars_are_not_the_game(view):
    w, _ = view
    assert w.game_point(480, 320) == (960.0, 540.0)
    assert w.game_point(0, 50) == (0.0, 0.0)
    assert w.game_point(480, 20) is None                   # the letterbox bar
    w._frame = Frame(path="x", width=1280, height=720)     # a frame says its size
    assert w.game_point(480, 320) == (640.0, 360.0)


def test_a_click_is_a_move_then_the_button(view):
    w, sent = view
    w.mousePressEvent(_mouse(QEvent.MouseButtonPress, 240, 185))
    w.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, 240, 185))
    ops = [(e.op, round(e.x), round(e.y), e.button) for e in sent]
    assert ops[0] == ("move", 480, 270, "left") and ops[1][0] == "down"
    assert ops[-1][0] == "up"


def test_a_click_on_the_bars_goes_nowhere(view):
    w, sent = view
    w.mousePressEvent(_mouse(QEvent.MouseButtonPress, 480, 10))
    w.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, 480, 10))
    assert sent == []


def test_moves_are_rate_limited(view):
    w, sent = view
    t = 1000.0
    for i in range(20):                    # 20 moves in 10 ms
        w._move(QPointF(100 + i, 100), now=t + i * 0.0005)
    assert len(sent) == 1, "only the first goes at once"
    assert w._move_wait is not None and w._move_timer.isActive()
    w._send_waiting_move()                 # the timer: the NEWEST position
    assert len(sent) == 2 and round(sent[-1].x) == round((119 - 0) * 2)


def test_moves_need_focus(view, app):
    """On Hyprland the owner's mouse crosses this window on its way to the
    nested one; without a click here it must not drag the game's pointer."""
    w, sent = view
    w.clearFocus()
    app.processEvents()
    w.mouseMoveEvent(_mouse(QEvent.MouseMove, 300, 300, Qt.NoButton))
    assert [e for e in sent if e.op == "move"] == []


def test_keys_are_named_held_once_and_f12_is_not_the_games(view):
    w, sent = view
    w.keyPressEvent(_key(QEvent.KeyPress, Qt.Key_W))
    w.keyPressEvent(_key(QEvent.KeyPress, Qt.Key_W, repeat=True))     # auto-repeat
    w.keyPressEvent(_key(QEvent.KeyPress, Qt.Key_F12))
    w.keyReleaseEvent(_key(QEvent.KeyRelease, Qt.Key_W))
    assert [(e.op, e.key) for e in sent] == [("key_down", "w"), ("key_up", "w")]


def test_the_take_control_words_name_the_configured_panic_key(app, monkeypatch):
    """Not a hard-coded F12: the key is the setting safety.panic_key."""
    from hivemind.world import settings as settings_mod

    class Fake:
        def get(self, key):
            return {"safety.panic_key": "F9"}.get(key)
    monkeypatch.setattr(settings_mod, "Settings", Fake)
    w = lv.LiveView()
    w.set_take_control(True, lambda e: True)
    assert w.toolTip().endswith("F9 stops the bot.") and "F12" not in w.toolTip()
    assert "F12" not in w.take_control_hint()
    w.set_take_control(False)
    w.close()


def test_the_wheel_scrolls_down_as_positive(view):
    w, sent = view
    w.wheelEvent(QWheelEvent(QPointF(300, 300), QPointF(300, 300), QPoint(0, 0),
                             QPoint(0, -240), Qt.NoButton, Qt.NoModifier,
                             Qt.NoScrollPhase, False))
    assert [(e.op, e.steps) for e in sent] == [("scroll", 2)]


def test_hand_back_and_focus_loss_let_go_of_everything(view, app):
    w, sent = view
    w.keyPressEvent(_key(QEvent.KeyPress, Qt.Key_W))
    w.mousePressEvent(_mouse(QEvent.MouseButtonPress, 300, 300))
    sent.clear()
    w.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    assert [(e.op, e.key or e.button) for e in sent] == [
        ("key_up", "w"), ("up", "left"), ("release_all", "left")]
    w.keyPressEvent(_key(QEvent.KeyPress, Qt.Key_A))
    sent.clear()
    w.set_take_control(False)
    assert [e.op for e in sent] == ["key_up", "release_all"]
    w.keyPressEvent(_key(QEvent.KeyPress, Qt.Key_D))
    assert [e.op for e in sent] == ["key_up", "release_all"], "off sends nothing"


def test_the_window_follows_who_is_driving(app):
    from hivemind.gui.window import MainWindow
    from test_run_controls import FakeBot, FakeBridge
    bridge = FakeBridge()
    win = MainWindow(bridge, bot=FakeBot())
    win._connected = True
    win.handle(StatusUpdate(running=True, paused=True, handed_over=True))
    assert win.live.taking and win.live.control == bridge.send
    win._on_connection(False)
    assert not win.live.taking, "a dead socket is no place to send keys"
    win._connected = True
    win.handle(StatusUpdate(running=True, paused=True, handed_over=True))
    win._handover(False)                   # Pass back: off before the command
    assert not win.live.taking
    assert [e.action for e in bridge.sent if isinstance(e, Command)] == [Action.PASS_BACK]


def test_the_new_window_brings_the_picture_forward(app):
    from hivemind.gui.shell import ShellWindow
    from test_run_controls import FakeBot, FakeBridge
    win = ShellWindow(FakeBridge(), bot=FakeBot())
    win._connected = True
    win._show_tab("ai")
    win.handle(StatusUpdate(running=True, paused=True, handed_over=True))
    assert win.live.taking
    assert win._menus["plan"].currentItem().text() == "Live view"     # Plan first, 2026-10-26
    assert win.tab_buttons["plan"].isChecked()


# ---- live: a headless labwc, a stand-in game, the real socket ---------------
def _labwc():
    try:
        from hivemind.platform import wlr_session as wm
    except Exception:
        return None
    return wm.find_labwc()


@pytest.mark.skipif(_labwc() is None,
                    reason="no labwc: set HIVEMIND_LABWC (tools/universal/fetch_compositor.sh)")
def test_live_the_owners_click_and_key_reach_the_game(app, tmp_path):
    pytest.importorskip("pywayland")
    from hivemind.platform import current
    from hivemind.platform import wlr_session as wm
    runtime = Path(f"/tmp/hm-rl1d-{os.getpid()}")
    runtime.mkdir(mode=0o700)
    log = tmp_path / "window.log"
    s = wm.WlrSession(config_path=tmp_path / "labwc", runtime=runtime,
                      game_id="hivemind-probe")
    window = conn = cap = inp = None
    path = str(runtime / "hm.sock")
    try:
        s.start(timeout=20, attempts=1)
        env = {**os.environ, "WAYLAND_DISPLAY": s.socket, "QT_QPA_PLATFORM": "wayland",
               "PROBE_WINDOWED": "1", "PROBE_APP_ID": "hivemind-probe"}
        env.pop("DISPLAY", None)
        window = subprocess.Popen([sys.executable, str(ROOT / "tools/universal/probe.py"),
                                   "window", str(log)], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 20
        while not (s.game_window_open() and "fullscreen" in s.describe_windows()):
            assert time.monotonic() < deadline, s.describe_windows()
            time.sleep(0.2)
        time.sleep(1.0)
        conn = current.connect(s)
        cap = current.make_capture(conn)
        inp = current.make_input(s)
        controls = Controls(vin=inp)
        with EventServer(path, on_message=controls.handle) as server:
            controls.emit = server.send
            controls.owner_drives()
            client = EventClient(path).start()
            while not client.connected:
                assert time.monotonic() < deadline + 10
                time.sleep(0.05)
            view = lv.LiveView()
            view.resize(960, 540)
            view.show()
            view.set_take_control(True, client.send)
            # the owner clicks a quarter of the way in -- the press right
            # behind the pointer's first arrival -- then holds W
            view.mousePressEvent(_mouse(QEvent.MouseButtonPress, 240, 135))
            view.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, 240, 135))
            view.keyPressEvent(_key(QEvent.KeyPress, Qt.Key_W))
            green = False
            t = time.monotonic() + 3
            while time.monotonic() < t and not green:
                green = cap.capture()[540, 960][1] > 200
                time.sleep(0.05)
            frame = cap.capture()
            view.keyReleaseEvent(_key(QEvent.KeyRelease, Qt.Key_W))
            view.set_take_control(False)
            client.stop()
        seen = log.read_text()
        assert green, "W from the live view did not reach the game"
        assert "key 'w'" in seen
        assert "click 480 270 size 1920x1080" in seen, seen
        out = os.environ.get("HIVEMIND_SHOT_FRAME")
        if out:                                # the screenshot script's real frame
            import cv2
            cv2.imwrite(out, frame[:, :, :3])
    finally:
        for closer in (inp, cap, conn):
            if closer is not None:
                closer.close()
        if window is not None:
            window.kill()
            window.wait(timeout=5)
        s.stop()
        for p in runtime.iterdir():
            p.unlink()
        runtime.rmdir()
