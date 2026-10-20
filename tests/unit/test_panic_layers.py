"""The panic key, in layers, from the window (gui/panic, RL1b step 3).

GUI F12 always; the bot's evdev when readable (and then nothing global, so a
machine that has it behaves as before); else the desktop's GlobalShortcuts
portal on Wayland, or an X11 grab. Each layer ends in Stop. The portal is
also driven for real, against a fake portal on a PRIVATE bus -- never the
desktop's.
"""
import os
import shutil
import subprocess
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QWidget              # noqa: E402

from hivemind.gui import panic                                   # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class FakeLayer:
    def __init__(self, fire, ok=True, why="version 1"):
        self.fire, self.ok, self.why = fire, ok, why
        self.started = self.stopped = False
        self.reason = why

    def available(self):
        return self.ok, self.why

    def start(self):
        self.started = True
        return self.ok

    def stop(self):
        self.stopped = True


def _layers(app, env, evdev=False, ok=True):
    made = {}

    def portal(fire):
        made["portal"] = FakeLayer(fire, ok)
        return made["portal"]

    def x11(fire):
        made["x11"] = FakeLayer(fire, ok, "grabbed F12 on the X11 desktop" if ok
                                else "another program already holds F12")
        return made["x11"]
    window = QWidget()
    layers = panic.PanicLayers(window, env=env, evdev=lambda: evdev, portal=portal, x11=x11)
    fired = []
    layers.fired.connect(fired.append)
    return layers, made, fired, window


def test_the_host_is_read_from_the_session():
    assert panic.host({"XDG_SESSION_TYPE": "wayland"}) == "wayland"
    assert panic.host({"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": "w"}) == "x11"
    assert panic.host({"WAYLAND_DISPLAY": "wayland-0"}) == "wayland"
    assert panic.host({"DISPLAY": ":0"}) == "x11"
    assert panic.host({}) == ""


@pytest.mark.skipif(os.name == "nt", reason="evdev and os.geteuid are Linux")
def test_evdev_readable_is_access_not_open(tmp_path):
    f = tmp_path / "event0"
    f.write_text("")
    assert panic.evdev_readable([str(f)])
    f.chmod(0)
    assert not panic.evdev_readable([str(f)]) or os.geteuid() == 0
    assert not panic.evdev_readable([])


def test_with_evdev_nothing_global_is_armed(app):
    """The owner's machine: the bot's watcher reads F12 -- no portal dialog,
    no grabbed key, exactly as before."""
    layers, made, _, _w = _layers(app, {"XDG_SESSION_TYPE": "wayland"}, evdev=True)
    assert layers.start() == ["GUI F12", "evdev (the bot's)"]
    assert made == {}
    assert layers.describe() == "panic key: GUI F12 + evdev (the bot's)"


def test_wayland_without_evdev_asks_the_portal_and_it_stops(app):
    layers, made, fired, _w = _layers(app, {"XDG_SESSION_TYPE": "wayland"})
    assert layers.start() == ["GUI F12", "portal"]
    assert made["portal"].started and layers.global_layer()
    made["portal"].fire()
    app.processEvents()
    assert fired == ["portal"]
    layers.stop()
    assert made["portal"].stopped


def test_no_portal_says_so_and_keeps_the_gui_layer(app):
    layers, made, _, _w = _layers(app, {"XDG_SESSION_TYPE": "wayland"}, ok=False)
    assert layers.start() == ["GUI F12"]
    assert not made["portal"].started and not layers.global_layer()


def test_x11_without_evdev_grabs(app):
    layers, made, fired, _w = _layers(app, {"XDG_SESSION_TYPE": "x11"})
    assert layers.start() == ["GUI F12", "X11 grab"]
    assert "portal" not in made
    made["x11"].fire()
    app.processEvents()
    assert fired == ["x11"]
    layers, made, _, _w = _layers(app, {"XDG_SESSION_TYPE": "x11"}, ok=False)
    assert layers.start() == ["GUI F12"]
    assert "already holds" in layers.notes["x11"]


def test_a_test_never_asks_the_real_desktop(app):
    window = QWidget()
    layers = panic.PanicLayers(window, env={"PYTEST_CURRENT_TEST": "x",
                                            "XDG_SESSION_TYPE": "wayland"},
                               evdev=lambda: False)
    assert layers.start() == ["GUI F12"]
    assert layers.portal is None and layers.grab is None


def test_the_window_shortcut_fires(app):
    layers, _, fired, window = _layers(app, {}, evdev=True)
    layers.start()
    layers.shortcut.activated.emit()
    app.processEvents()
    assert fired == ["gui"]


def test_the_window_stops_on_any_layer(app):
    from hivemind.gui.window import MainWindow
    from hivemind.telemetry.events import Action, Command, StatusUpdate
    from test_run_controls import FakeBot, FakeBridge
    bridge = FakeBridge()
    win = MainWindow(bridge, bot=FakeBot())
    win._connected = True
    win.handle(StatusUpdate(running=True, paused=True, handed_over=True))
    assert win.live.taking
    assert win.panic.describe().startswith("panic key: GUI F12")
    win.panic.fired.emit("portal")
    app.processEvents()
    assert not win.live.taking, "the owner's held keys come up first"
    assert [e.action for e in bridge.sent if isinstance(e, Command)] == [Action.STOP]


# ---- X11, with libX11 faked --------------------------------------------------------
class FakeX11:
    def __init__(self, error=False):
        self.error, self.grabs, self.handler = error, [], None

    def XOpenDisplay(self, name): return 1234
    def XSetErrorHandler(self, handler): self.handler = handler
    def XStringToKeysym(self, name): return 0xFFC9 if name == b"F12" else 0
    def XKeysymToKeycode(self, dpy, sym): return 96 if sym else 0
    def XDefaultRootWindow(self, dpy): return 1
    def XGrabKey(self, dpy, code, mods, root, owner, a, b): self.grabs.append((code, mods))
    def XSync(self, dpy, discard):
        if self.error:
            self.handler(None, None)
    def XCloseDisplay(self, dpy): self.closed = True
    def XConnectionNumber(self, dpy): return -1
    def XPending(self, dpy): return 0
    def XUngrabKey(self, *a): pass


def test_x11_grab_takes_f12_with_the_locks_and_reports_a_clash():
    lib = FakeX11()
    grab = panic.X11Grab(lambda: None, "F12", lib=lib)
    assert grab.start(), grab.reason
    assert lib.grabs == [(96, 0), (96, 2), (96, 16), (96, 18)]   # plain, Caps, Num, both
    grab.stop()
    lib = FakeX11(error=True)
    grab = panic.X11Grab(lambda: None, "F12", lib=lib)
    assert not grab.start()
    assert "already holds F12" in grab.reason


# ---- the portal, for real, on a private bus -------------------------------------
FAKE_PORTAL = """<node><interface name="org.freedesktop.portal.GlobalShortcuts">
<method name="CreateSession"><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
<method name="BindShortcuts"><arg type="o" direction="in"/><arg type="a(sa{sv})" direction="in"/>
<arg type="s" direction="in"/><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
<signal name="Activated"><arg type="o"/><arg type="s"/><arg type="t"/><arg type="a{sv}"/></signal>
<property name="version" type="u" access="read"/></interface></node>"""


def _connect(Gio, address):
    return Gio.DBusConnection.new_for_address_sync(
        address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)


def _serve_fake_portal(Gio, GLib, address, seen):
    """A portal that answers like KDE's: Response on the request path, then
    the shortcut pressed once (Activated) 200 ms after it is bound."""
    context = GLib.MainContext()
    context.push_thread_default()
    bus = _connect(Gio, address)

    def call(conn, sender, path, iface, method, params, invocation):
        who = sender[1:].replace(".", "_")
        args = params.unpack()
        token = args[-1]["handle_token"]
        request = f"/org/freedesktop/portal/desktop/request/{who}/{token}"
        invocation.return_value(GLib.Variant("(o)", (request,)))
        if method == "CreateSession":
            session = (f"/org/freedesktop/portal/desktop/session/{who}/"
                       f"{args[0]['session_handle_token']}")
            seen["session"] = session
            conn.emit_signal(sender, request, "org.freedesktop.portal.Request", "Response",
                             GLib.Variant("(ua{sv})", (0, {"session_handle":
                                                            GLib.Variant("s", session)})))
            return
        seen["bind"] = args[:3]
        conn.emit_signal(sender, request, "org.freedesktop.portal.Request", "Response",
                         GLib.Variant("(ua{sv})", (0, {"shortcuts": GLib.Variant(
                             "a(sa{sv})", [(args[1][0][0], {"trigger_description":
                                                             GLib.Variant("s", "F12")})])})))

        def press():
            conn.emit_signal(None, "/org/freedesktop/portal/desktop", panic.PORTAL_IFACE,
                             "Activated", GLib.Variant("(osta{sv})",
                                                       (args[0], args[1][0][0], 1, {})))
            return False
        timer = GLib.timeout_source_new(200)
        timer.set_callback(lambda *_: press())
        timer.attach(context)

    bus.register_object(panic.PORTAL_PATH,
                        Gio.DBusNodeInfo.new_for_xml(FAKE_PORTAL).interfaces[0],
                        call, lambda *a: GLib.Variant("u", 1), None)
    Gio.bus_own_name_on_connection(bus, panic.PORTAL_NAME, Gio.BusNameOwnerFlags.NONE,
                                   None, None)
    seen["ready"] = True
    GLib.MainLoop(context).run()


@pytest.mark.skipif(shutil.which("dbus-daemon") is None, reason="no dbus-daemon")
def test_live_portal_binds_f12_and_its_press_fires():
    gi = pytest.importorskip("gi")
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    daemon = subprocess.Popen(["dbus-daemon", "--session", "--print-address=1", "--nofork"],
                              stdout=subprocess.PIPE, text=True)
    try:
        address = daemon.stdout.readline().strip()
        seen = {}
        threading.Thread(target=_serve_fake_portal, args=(Gio, GLib, address, seen),
                         daemon=True).start()
        deadline = time.monotonic() + 5
        while not seen.get("ready"):
            assert time.monotonic() < deadline
            time.sleep(0.02)
        time.sleep(0.2)
        fired = []
        portal = panic.PortalShortcut(lambda: fired.append(1), "F12",
                                      bus=_connect(Gio, address))
        assert portal.available() == (True, "version 1")
        portal.start()
        while not fired:
            assert time.monotonic() < deadline + 5, (portal.state, portal.reason)
            time.sleep(0.02)
        assert portal.state == "bound" and portal.session == seen["session"]
        session, shortcuts, parent = seen["bind"]
        assert shortcuts == [(panic.SHORTCUT_ID, {"description": panic.DESCRIPTION,
                                                  "preferred_trigger": "F12"})]
        portal.stop()
    finally:
        daemon.terminate()
        daemon.wait(timeout=5)


# ---- doctor ----------------------------------------------------------------------
def test_doctor_counts_a_global_layer_without_the_input_group(monkeypatch):
    from hivemind.cli import doctor
    from hivemind.platform import panic as bot_panic
    monkeypatch.setattr(bot_panic.PanicWatcher, "find_devices", lambda self, paths=None: [])
    monkeypatch.setattr(doctor, "global_panic_layer", lambda key="F12": "F12 through the "
                        "desktop's GlobalShortcuts portal (version 1)")
    [check] = doctor.safety()
    assert check.status == doctor.OK and "portal" in check.detail
    monkeypatch.setattr(doctor, "global_panic_layer", lambda key="F12": "")
    [check] = doctor.safety()
    assert check.status == doctor.FAIL and "GlobalShortcuts portal" in check.fix
