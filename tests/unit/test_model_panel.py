"""The vision-model panel must never claim a model it has not reached.

The failure this guards against is specific and has happened here before: a
control that reports the CONFIGURATION rather than the world. `perf.vlm` was a
checkbox wired to nothing, and a panel that painted green from that setting
would be the same bug with a bigger surface -- because `ask()` returns None
when the model is absent and the bot quietly carries on with classical CV, so a
false green sends you looking for the fault everywhere except at the model.

So the tests below hold the panel to three things:

  * green only ever follows a probe that CAME BACK -- not one that was started,
    not one that hung, not one that raised, and not one from a minute ago
  * when it is unavailable, the reason is shown whole, INCLUDING the shell
    command that fixes it, and that command is copyable exactly
  * nothing the panel does can take the window down, including being destroyed
    while a probe is still in flight

The unavailable cases are driven through the REAL `VisionModel` rather than a
stub, because the fix command is parsed out of the reason string that client
builds: if its wording changes, these tests are what notices.
"""
import http.server
import json
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtCore import QEventLoop, QTimer                       # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

from hivemind.brain.vlm import VisionModel                          # noqa: E402
from hivemind.gui import theme                                      # noqa: E402
from hivemind.gui.panels import model as panel_module               # noqa: E402
from hivemind.gui.panels.model import ModelPanel, fix_command       # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def settle(ms: int = 20) -> None:
    """Let Qt run its timers; the panel collects probes on one."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(predicate, timeout: float = 5.0) -> bool:
    """Spin the event loop until the panel reports something, or give up."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        settle(10)
    return predicate()


class FakeModel:
    """Only the four things the panel ever touches on a VisionModel.

    `gate` lets a test hold a probe open for as long as it likes, which is the
    only way to observe what the panel shows while it does not yet know.
    """

    host = "http://127.0.0.1:11434"

    def __init__(self, ok=True, model="qwen2.5vl:7b", reason="",
                 stats="not used yet", gate=None, raises=None):
        self.ok = ok
        self.model = model
        self.reason = reason
        self._stats = stats
        self.gate = gate
        self.raises = raises
        self.probes = 0

    def available(self) -> bool:
        if self.gate is not None:
            self.gate.wait(5)
        self.probes += 1
        if self.raises is not None:
            raise self.raises
        return self.ok

    def stats(self) -> str:
        return self._stats


@pytest.fixture
def build(app):
    """Builds panels, shows them, and stops their timers afterwards.

    Shown on purpose: a child of a widget that was never shown reports
    `isVisible() == False` whatever its own state, so the assertions about the
    reason and fix rows appearing would pass on a panel that displays nothing.
    """
    made = []

    def make(model):
        panel = ModelPanel(model=model)
        panel.resize(420, 260)
        panel.show()
        made.append(panel)
        settle()
        return panel

    yield make
    for panel in made:
        panel.stop()
        panel.hide()
    settle()


class _Tags(http.server.BaseHTTPRequestHandler):
    """The single endpoint `available()` calls: GET /api/tags."""
    models = [{"name": "llama3:8b"}]

    def log_message(self, *_):
        pass

    def do_GET(self):
        body = json.dumps({"models": type(self).models}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def tags_server():
    _Tags.models = [{"name": "llama3:8b"}]
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Tags)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


# ---- green is only ever painted from an answer -----------------------------

def test_it_does_not_claim_ready_before_the_probe_comes_back(build):
    """A panel that paints green on construction is reporting its config."""
    gate = threading.Event()
    model = FakeModel(ok=True, gate=gate)
    panel = build(model)
    settle(80)

    assert panel.verdict is None, "claimed a result nobody had yet"
    assert panel.shown_state() == ModelPanel.UNKNOWN
    assert "checking" in panel._headline.text()

    gate.set()
    assert wait_for(lambda: panel.shown_state() == ModelPanel.READY)


def test_a_reachable_model_is_named_with_its_cache_rate(build):
    """The whole point: which model, and how much of it was free."""
    model = FakeModel(ok=True, model="qwen2.5vl:7b",
                      stats="4 questions, 2 from cache (50% free)")
    panel = build(model)
    assert wait_for(lambda: panel.shown_state() == ModelPanel.READY)

    assert panel._model_field.text() == "qwen2.5vl:7b"
    assert panel._cache_field.text() == "4 questions, 2 from cache (50% free)"
    assert "qwen2.5vl:7b" in panel._headline.text()
    assert panel._badge.text() == "ready"
    assert theme.GOOD in panel._dot.styleSheet()
    assert not panel._reason.isVisible(), "a reason with nothing wrong"


def test_a_model_that_goes_away_stops_being_green(build):
    """Green must not stick. The server can be stopped mid-session."""
    model = FakeModel(ok=True)
    panel = build(model)
    assert wait_for(lambda: panel.shown_state() == ModelPanel.READY)

    model.ok = False
    model.reason = "no model server at http://127.0.0.1:11434"
    panel.refresh()
    assert wait_for(lambda: panel.shown_state() == ModelPanel.UNAVAILABLE)
    assert theme.GOOD not in panel._dot.styleSheet()


def test_a_verdict_that_has_aged_out_is_no_longer_green(build, monkeypatch):
    """A stale yes is not a yes: if the checking stopped, say so.

    Without this, a panel whose refresh loop had died -- a wedged probe, a
    stopped timer -- would sit on a green dot indefinitely, which is the exact
    false confidence this panel exists to remove.
    """
    panel = build(FakeModel(ok=True))
    assert wait_for(lambda: panel.shown_state() == ModelPanel.READY)

    monkeypatch.setattr(panel_module, "STALE_AFTER_S", 0.05)
    assert wait_for(lambda: panel.shown_state() == ModelPanel.UNKNOWN)
    # and it has to SAY so, not merely believe it internally
    assert wait_for(lambda: "no longer current" in panel._checked_field.text())
    assert theme.GOOD not in panel._dot.styleSheet()
    assert panel._badge.text() != "ready"


def test_a_probe_that_raises_is_reported_rather_than_left_green(build):
    """An exception in the check must still produce a verdict, not silence."""
    panel = build(FakeModel(raises=RuntimeError("socket exploded")))
    assert wait_for(lambda: panel.shown_state() == ModelPanel.UNAVAILABLE)
    assert "the check itself failed" in panel._reason.text()
    assert "socket exploded" in panel._reason.text()


def test_only_one_probe_runs_at_a_time(build):
    """A hung probe must not be answered by piling up threads behind it."""
    gate = threading.Event()
    model = FakeModel(ok=True, gate=gate)
    panel = build(model)
    for _ in range(5):
        panel.refresh()
    settle(60)
    gate.set()
    assert wait_for(lambda: panel.shown_state() == ModelPanel.READY)
    assert model.probes == 1, f"started {model.probes} overlapping probes"


# ---- the reason, whole, with the command that fixes it ---------------------

def test_a_server_that_is_not_running_shows_the_install_command(build, tmp_path):
    """Measured against the real client, not a copy of its wording."""
    client = VisionModel(host="http://127.0.0.1:1", cache_dir=tmp_path,
                         timeout=1.0)
    panel = build(client)
    assert wait_for(lambda: panel.shown_state() == ModelPanel.UNAVAILABLE)

    shown = panel._reason.text()
    assert shown == panel.verdict.reason, "the reason was not shown verbatim"
    assert "no model server at http://127.0.0.1:1" in shown
    assert "sudo pacman -S ollama-vulkan" in shown, "the fix was dropped"
    assert panel._reason.isVisible()
    assert panel._fix_row.isVisible()
    assert panel._fix_label.text() == (
        "sudo pacman -S ollama-vulkan && sudo systemctl enable --now ollama")


def test_a_model_that_is_not_pulled_shows_the_pull_command(build, tmp_path,
                                                           tags_server):
    """The command must come out without the '(installed: ...)' tail on it."""
    client = VisionModel(host=tags_server, cache_dir=tmp_path,
                         model="qwen2.5vl:7b")
    panel = build(client)
    assert wait_for(lambda: panel.shown_state() == ModelPanel.UNAVAILABLE)

    assert "is not pulled yet" in panel._reason.text()
    assert "installed: llama3:8b" in panel._reason.text(), (
        "the panel hid what IS installed, which is half the diagnosis")
    assert panel._fix_label.text() == "ollama pull qwen2.5vl:7b"


def test_the_fix_command_is_copied_exactly(build, tmp_path, tags_server, app):
    """Retyping a command out of a label is how it gets typed wrong."""
    client = VisionModel(host=tags_server, cache_dir=tmp_path,
                         model="qwen2.5vl:7b")
    panel = build(client)
    assert wait_for(lambda: panel.shown_state() == ModelPanel.UNAVAILABLE)

    app.clipboard().setText("something else entirely")
    panel.copy_fix()
    assert app.clipboard().text() == "ollama pull qwen2.5vl:7b"


def test_being_turned_off_is_reported_without_inventing_a_command(build, tmp_path):
    """"turned off in settings" has no shell fix, so no button offers one."""
    client = VisionModel(cache_dir=tmp_path, enabled=False)
    panel = build(client)
    assert wait_for(lambda: panel.shown_state() == ModelPanel.UNAVAILABLE)

    assert panel._reason.text() == "turned off in settings"
    assert not panel._fix_row.isVisible(), "offered a command that does not exist"


def test_a_reason_with_no_separator_yields_no_command():
    """The parse is a rule about the client's wording, not a guess at one.

    Every reason vlm.py builds for a fault it cannot fix from the shell -- an
    unusable reply, a timeout, an empty answer -- is a plain sentence with no
    em dash, so the separator is also the test for whether a command exists.
    """
    assert fix_command("model server gave an unusable reply: bad json") == ""
    assert fix_command("the model did not answer: timed out") == ""
    assert fix_command("the model returned an empty answer") == ""
    assert fix_command("") == ""


def test_the_command_is_taken_from_the_reason_the_client_produced(tmp_path):
    """Locks the parse to the live wording of both fixable faults."""
    down = VisionModel(host="http://127.0.0.1:1", cache_dir=tmp_path,
                       timeout=1.0)
    down.available()
    assert fix_command(down.reason) == (
        "sudo pacman -S ollama-vulkan && sudo systemctl enable --now ollama")

    off = VisionModel(cache_dir=tmp_path, enabled=False)
    off.available()
    assert fix_command(off.reason) == ""


# ---- it cannot take the window down ----------------------------------------

def test_a_panel_destroyed_mid_probe_does_not_abort(app):
    """The reason the probe is a daemon thread and not a QThread.

    A QThread deleted while it is still running calls abort() -- the window
    closing during a 2 s probe of a dead server would take the process with it.
    Here the panel is dropped with a probe held open, and the probe is only
    then allowed to finish.
    """
    gate = threading.Event()
    model = FakeModel(ok=True, gate=gate)
    panel = ModelPanel(model=model)
    settle(40)
    panel.stop()
    panel.deleteLater()
    del panel
    settle(40)

    gate.set()
    assert wait_for(lambda: model.probes == 1), "the probe never finished"
    settle(60)          # anything fatal lands here


def test_stopping_the_panel_stops_the_checking_and_the_claiming(build):
    """A panel that stopped probing must not keep the last green dot.

    It is left on screen by `stop()`, so a frozen "ready" would be the same
    false confidence as a stale one -- nothing is checking behind it any more.
    """
    panel = build(FakeModel(ok=True))
    assert wait_for(lambda: panel.shown_state() == ModelPanel.READY)

    panel.stop()
    before = panel.model.probes
    settle(120)
    assert panel.model.probes == before, "kept probing after being stopped"
    assert panel.shown_state() == ModelPanel.UNKNOWN
    assert panel._badge.text() == "unknown"
    assert theme.GOOD not in panel._dot.styleSheet(), "left a green dot behind"


def test_checking_a_stopped_panel_starts_it_again(build):
    """Otherwise the button starts a probe whose answer nothing collects.

    The panel would then sit on "checking the model server…" for ever, with
    `_probing` latched true so no later check could run either -- a claim that
    work is happening when none is.
    """
    panel = build(FakeModel(ok=True))
    assert wait_for(lambda: panel.shown_state() == ModelPanel.READY)
    panel.stop()
    settle(60)
    assert panel.shown_state() == ModelPanel.UNKNOWN

    panel.refresh()                          # what the Check now button does
    assert wait_for(lambda: panel.shown_state() == ModelPanel.READY)
    assert panel.model.probes == 2


# ---- an answer is as old as the answer, not as old as the pickup -----------

def test_a_verdict_collected_late_is_dated_from_when_it_answered(app, monkeypatch):
    """Stamping on collection re-dates an old answer as a new one.

    The panel's whole claim is that green means a probe came back RECENTLY, and
    it tests that with `age()`. If `age()` is measured from the moment the GUI
    thread happened to lift the verdict off the queue, then anything that stops
    the poller running -- `stop()`, a blocked GUI thread, a long repaint --
    banks the answer and re-dates it as fresh the moment polling resumes.

    Measured before the fix, with STALE_AFTER_S at 0.5 s and a verdict held for
    2 s: the panel painted READY, badge "ready", CHECKED row "0s ago".
    """
    monkeypatch.setattr(panel_module, "STALE_AFTER_S", 0.5)
    gate = threading.Event()
    model = FakeModel(ok=True, gate=gate)
    panel = ModelPanel(model=model)
    try:
        settle(60)
        panel.stop()                    # the poller stops; the probe is still out
        gate.set()
        assert wait_for(lambda: model.probes == 1), "the probe never ran"
        time.sleep(1.0)                 # it has now been sitting in the queue

        panel.refresh()                 # what "Check now" does: timers restart
        assert wait_for(lambda: panel.verdict is not None), "never collected"

        assert panel.age() >= 1.0, (
            f"a {panel.age():.2f}s-old answer was dated as if it had just "
            "arrived")
        assert panel.shown_state() == ModelPanel.UNKNOWN, (
            "painted green from an answer older than STALE_AFTER_S")
        assert theme.GOOD not in panel._dot.styleSheet()
    finally:
        panel.stop()
        panel.deleteLater()


# ---- a sentence we wrote ourselves is not mined for a command --------------

def test_our_own_failure_sentence_is_never_mined_for_a_command(build):
    """The em-dash rule is about vlm.py's wording, not about any string.

    "the check itself failed: ..." is composed HERE, around an arbitrary
    exception repr. An em dash inside that repr is punctuation, and parsing it
    as the separator hands the user a fragment of a traceback in a mono row
    with a Copy button beside it -- which this panel's own docstring calls
    worse than showing nothing, because a command in a status panel gets run
    before it gets doubted.

    Measured before the fix: this exact reason yielded the offered "command"
    `rm -rf /var/lib/ollama')`.
    """
    boom = RuntimeError("ollama died — rm -rf /var/lib/ollama")
    panel = build(FakeModel(raises=boom))
    assert wait_for(lambda: panel.shown_state() == ModelPanel.UNAVAILABLE)

    assert "the check itself failed" in panel._reason.text()
    assert panel._fix == "", f"invented the command {panel._fix!r}"
    assert not panel._fix_row.isVisible(), "offered a shell command it made up"


# ---- the cache row is a reading or it is not there ------------------------

def test_a_panel_that_built_its_own_client_shows_no_cache_rate(app, monkeypatch):
    """`stats()` counts one client's questions, and we never ask ours any.

    `VisionModel.calls` and `.cache_hits` are instance attributes. A panel that
    calls `from_settings()` for itself holds a client that nothing will ever
    call `ask()` on, so the CACHE row would read "not used yet" for the whole
    session while the bot's own client answered hundreds of questions through
    a different object. That is a figure nothing computed, dressed as a
    measurement, so there must be no row at all.
    """
    from hivemind.brain import vlm

    built = FakeModel(ok=True, stats="not used yet")
    monkeypatch.setattr(vlm, "from_settings", lambda *a, **k: built)
    panel = ModelPanel()
    try:
        assert wait_for(lambda: panel.shown_state() == ModelPanel.READY)
        assert panel._cache_field is None, (
            "showed a cache rate for a client it never asks anything")
        texts = [panel._model_field.text(), panel._checked_field.text()]
        assert "not used yet" not in texts
    finally:
        panel.stop()
        panel.deleteLater()


def test_a_panel_handed_a_client_does_show_its_cache_rate(build):
    """The row is not dropped altogether -- it is dropped where it is empty."""
    panel = build(FakeModel(ok=True, stats="37 questions, 29 from cache (78% free)"))
    assert wait_for(lambda: panel.shown_state() == ModelPanel.READY)
    assert panel._cache_field is not None, "hid a rate that was really measured"
    assert panel._cache_field.text() == "37 questions, 29 from cache (78% free)"
