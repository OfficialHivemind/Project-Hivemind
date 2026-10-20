"""The live view must never go silently blank.

The bot rewrites ONE fixed frame path continuously, so reading it mid-write and
failing to decode is routine. The pane used to respond by discarding the last
good frame AND leaving its explanation invisible -- `_hint` is hidden for good
on the first successful frame and was never shown again, while paintEvent
returned early. The result was a bare dark rectangle that said nothing, during
normal operation, and permanently once the bot stopped writing.
"""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

cv2 = pytest.importorskip("cv2")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication                   # noqa: E402

from hivemind.gui.panels.liveview import LiveView            # noqa: E402
from hivemind.telemetry.events import Frame                  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(app):
    widget = LiveView()
    widget.resize(320, 200)
    widget.show()
    return widget


@pytest.fixture
def good_frame(tmp_path):
    path = tmp_path / "frame.png"
    cv2.imwrite(str(path), np.full((100, 160, 3), 90, np.uint8))
    return path


def _settle(app, until, seconds=3.0):
    """The pane decodes on its own thread (gui/panels/liveview _Decoder,
    DESIGN 8eb) and hears back by a queued signal: turn the event loop until
    `until()` holds."""
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if until():
            return True
        time.sleep(0.01)
    return until()


def test_a_missing_frame_keeps_the_last_good_one(view, good_frame, tmp_path, app):
    view.show_frame(Frame(path=str(good_frame)))
    assert _settle(app, lambda: view._picture is not None)
    view.show_frame(Frame(path=str(tmp_path / "rotated_away.png")))
    assert _settle(app, lambda: view._missing), "did not mark the view as stale"
    assert view._picture is not None, "threw away the last good frame"


def test_an_undecodable_frame_keeps_the_last_good_one(view, good_frame, tmp_path, app):
    """A half-written PNG is the common case, not an exotic one."""
    view.show_frame(Frame(path=str(good_frame)))
    assert _settle(app, lambda: view._picture is not None)
    truncated = tmp_path / "half.png"
    truncated.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    view.show_frame(Frame(path=str(truncated)))
    assert _settle(app, lambda: view._missing)
    assert view._picture is not None


def test_with_no_frame_ever_the_reason_is_visible(view, tmp_path, app):
    view.show_frame(Frame(path=str(tmp_path / "never.png")))
    assert _settle(app, lambda: view._missing)
    assert view._hint.isVisible(), "blank pane with no explanation"
    assert "never.png" in view._hint.toolTip()            # the path, for whoever needs it
    assert "Press Start" in view._hint.text()             # plain words on the pane


def test_it_recovers_when_frames_come_back(view, good_frame, tmp_path, app):
    view.show_frame(Frame(path=str(good_frame)))
    assert _settle(app, lambda: view._picture is not None)
    view.show_frame(Frame(path=str(tmp_path / "gone.png")))
    assert _settle(app, lambda: view._missing)
    view.show_frame(Frame(path=str(good_frame)))
    assert _settle(app, lambda: not view._missing)
    assert not view._hint.isVisible()


def test_painting_a_held_frame_does_not_raise(view, good_frame, tmp_path, app):
    """paintEvent draws the stale overlay; it must survive being called."""
    view.show_frame(Frame(path=str(good_frame)))
    _settle(app, lambda: view._picture is not None)
    view.show_frame(Frame(path=str(tmp_path / "gone.png")))
    _settle(app, lambda: view._missing)
    view.repaint()
    view.grab()                       # forces a real paint pass


# --------------------------------------- the Fields tab shows real numbers --
def test_a_field_card_shows_the_measured_rate_not_a_fake_health_bar(app):
    """THE OWNER: "the fields tab isnt linked". `health` defaulted to 1.0 and
    nothing set it, so every card was a full green bar, and the counts line
    read "0 tokens" for every field."""
    from hivemind.gui.panels.fields import FieldsPanel
    from hivemind.telemetry.events import FieldStatus
    panel = FieldsPanel()
    name = next(iter(panel._cards))
    panel.update_field(FieldStatus(name=name, rate=927.0, pollen=8_434,
                                   visits=2, deaths=1, mobs=2))
    shown = panel._cards[name]._counts.text()
    assert "927 pollen/s" in shown
    assert "8,434 over 2 visits" in shown
    assert "died here 1x" in shown
    assert "tokens" not in shown, "it invented a token count again"
    assert "health" not in shown, "it invented a health figure again"


def test_a_field_never_measured_says_so(app):
    from hivemind.gui.panels.fields import FieldsPanel
    from hivemind.telemetry.events import FieldStatus
    panel = FieldsPanel()
    name = next(iter(panel._cards))
    panel.update_field(FieldStatus(name=name))
    assert "never measured" in panel._cards[name]._counts.text()


def test_the_bars_are_redrawn_when_a_better_field_turns_up(app):
    """Otherwise the first field measured keeps a full bar for ever and a
    better one found later looks the same size."""
    from hivemind.gui.panels.fields import FieldsPanel
    from hivemind.telemetry.events import FieldStatus
    panel = FieldsPanel()
    names = list(panel._cards)[:2]
    panel.update_field(FieldStatus(name=names[0], rate=252.0))
    assert panel._cards[names[0]]._health._value == 1.0
    panel.update_field(FieldStatus(name=names[1], rate=927.0))
    assert panel._cards[names[1]]._health._value == 1.0
    assert panel._cards[names[0]]._health._value < 0.4, "the slower field was not rescaled"


def test_a_measured_health_figure_is_shown_when_one_ever_arrives(app):
    from hivemind.gui.panels.fields import FieldsPanel
    from hivemind.telemetry.events import FieldStatus
    panel = FieldsPanel()
    name = next(iter(panel._cards))
    panel.update_field(FieldStatus(name=name, health=0.4, tokens=3))
    shown = panel._cards[name]._counts.text()
    assert "40% health" in shown and "3 tokens" in shown


# --- the picture must not wait for the boxes ------------------------------
# MEASURED 2026-09-22, four consecutive runs configured for 20 fps: 7.3, 8.0,
# 8.2 and 8.4 achieved. The overlay pass is ~38 ms and ran on every frame.
# The owner: "also make it have smoother vision fps, hive minds fps looks low".

def _view(detect, tmp_path, sent=None, overlay_seconds=0.05):
    import numpy as np
    from hivemind.telemetry.liveview import LiveView
    frame = np.zeros((16, 16, 4), dtype=np.uint8)
    return LiveView(lambda: frame, (sent.append if sent is not None else (lambda e: None)),
                    path=tmp_path / "live.jpg", detect=detect,
                    overlay_seconds=overlay_seconds)


def test_a_slow_overlay_never_holds_up_the_picture(tmp_path):
    """THE OVERLAY ON ITS OWN THREAD (DESIGN 8eb): at one pass a frame the
    view made 7.3-8.4 of 20 fps. A pass that takes 0.3 s must not slow one."""
    import time

    def slow(frame):
        time.sleep(0.3)
        return [{"kind": "token"}]
    view = _view(slow, tmp_path)
    began = time.monotonic()
    for _ in range(5):
        assert view.once() is True
    assert time.monotonic() - began < 0.25, "the picture waited for the boxes"
    assert view.sent == 5


def test_the_finished_boxes_ride_on_later_frames(tmp_path):
    import time
    sent = []
    view = _view(lambda f: [{"kind": "token", "x": 5}], tmp_path, sent)
    view.once()
    end = time.monotonic() + 2.0
    while time.monotonic() < end and not (view.overlay and view.overlay.ran):
        time.sleep(0.01)
    time.sleep(0.06)
    view.once()
    assert sent[-1].detections == [{"kind": "token", "x": 5}], [e.detections for e in sent]


def test_a_broken_overlay_still_streams_the_picture(tmp_path):
    """A detector having a bad frame must never stop the camera."""
    def explode(frame):
        raise RuntimeError("bad frame")
    view = _view(explode, tmp_path)
    assert view.once() is True
    assert view.sent == 1


def test_it_says_where_the_time_went(tmp_path):
    """The first guess at the low frame rate blamed the JPEG encode, which
    measures 2.5ms. Without this the next person guesses too."""
    view = _view(lambda f: [], tmp_path)
    for _ in range(4):
        view.once()
    said = view.describe()
    assert "capture" in said and "encode" in said and "frame hook" in said, said


def test_the_setting_is_read_and_clamped():
    from hivemind.telemetry.liveview import DEFAULT_OVERLAY_MS, LiveView

    class S:
        def __init__(self, v): self.v = v
        def int(self, key): return int(self.v)

    assert LiveView.overlay_seconds_from(S(500)) == 0.5
    assert LiveView.overlay_seconds_from(S(99999)) == 3.0, "clamped"
    assert LiveView.overlay_seconds_from(S(10)) == 0.05, "clamped"
    assert LiveView.overlay_seconds_from(S("nonsense")) == DEFAULT_OVERLAY_MS / 1000.0, "falls back"


# ---- the overlay's look ---------------------------------------------------------
# The owner, 2026-09-27: the token boxes "look basic and ugly and there are so
# many of them". Each kind is drawn as its own mark (panels/liveview
# paint_detections); these pin that every kind draws and a broken one is skipped.

def test_every_kind_of_detection_is_drawn_and_a_broken_one_is_skipped(app):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from hivemind.gui.panels import liveview

    image = QImage(640, 360, QImage.Format_RGB32)
    image.fill(0)
    dets = [
        {"kind": "token", "x": 900, "y": 450, "w": 120, "h": 120, "tag": "token 84%"},
        {"kind": "target", "x": 300, "y": 300, "w": 90, "h": 90, "tag": "chasing"},
        {"kind": "maybe", "x": 1500, "y": 600, "w": 60, "h": 60, "label": "below the chase"},
        {"kind": "mob", "x": 1200, "y": 150, "w": 170, "h": 40, "label": "Rhino Beetle"},
        {"kind": "landmark", "x": 660, "y": 20, "w": 290, "h": 36, "tag": "honey 4,088,602"},
        {"kind": "token", "y": 10},                       # no x: skipped, not raised
    ]
    painter = QPainter(image)
    drawn = liveview.paint_detections(painter, dets, 0.0, 0.0, 1 / 3, 1 / 3,
                                      QRectF(0, 0, 640, 360))
    painter.end()
    assert drawn == 5
    lit = sum(1 for x in range(0, 640, 4) for y in range(0, 360, 4)
              if image.pixel(x, y) & 0xFFFFFF)
    assert lit > 50, "nothing visible was drawn"


def test_a_pill_is_cut_short_and_prefers_the_short_tag():
    from hivemind.gui.panels import liveview
    assert liveview._short({"tag": "token 84%", "label": "a long explanation"}) == "token 84%"
    long = liveview._short({"label": "x" * 80})
    assert len(long) == liveview.PILL_MOST_CHARS and long.endswith("…")
