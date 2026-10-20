"""The panic key, in layers, from the window (RL1b step 3).

The bot's own panic key reads /dev/input (platform/panic) and needs the
`input` group. A friend's PC rarely has that, and a headless game has no
window to click. So the WINDOW arms what it can, every start, and says which:

    gui      F12 while Hivemind has focus, and the Stop button   always
    evdev    the bot's /dev/input watcher                         in the input group
    portal   org.freedesktop.portal.GlobalShortcuts (KDE, GNOME,  a Wayland desktop with
             Hyprland; not wlroots desktops)                      the portal, no evdev
    x11      XGrabKey on the root window                          an X11 desktop, no evdev

Every layer here ends in the window's Stop: the command (every key up), then
the process. The evdev layer stays the bot's and does what it always did
(release every key) -- WITH IT READABLE THE GLOBAL LAYERS ARE NOT ARMED, so a
machine that has it (the owner's) behaves exactly as before: no portal
dialog, no grabbed F12. The log line says which: "panic key: GUI F12 + portal".

Under pytest only the GUI layer is armed unless a test passes its own layers:
a test must never ask the real desktop for a shortcut.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import glob
import os
import select
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut

PORTAL_NAME = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_IFACE = "org.freedesktop.portal.GlobalShortcuts"
SHORTCUT_ID = "hivemind-panic"
DESCRIPTION = "Hivemind: stop the bot (panic key)"


def evdev_readable(paths=None) -> bool:
    """Can this user read a keyboard device? (The bot's PanicWatcher then
    can: it is the `input` group.) Cheap: no device is opened."""
    paths = glob.glob("/dev/input/event*") if paths is None else paths
    return any(os.access(p, os.R_OK) for p in paths)


def host(env=None) -> str:
    """'wayland', 'x11' or '' -- the desktop this window is on."""
    env = os.environ if env is None else env
    kind = env.get("XDG_SESSION_TYPE", "")
    if kind in ("wayland", "x11"):
        return kind
    if env.get("WAYLAND_DISPLAY"):
        return "wayland"
    return "x11" if env.get("DISPLAY") else ""


# ---- the portal ---------------------------------------------------------------
class PortalShortcut:
    """F12 through org.freedesktop.portal.GlobalShortcuts, over Gio (PyGObject,
    which the GNOME runtime Sober runs in ships; QtDBus from Python cannot
    marshal the a(sa{sv}) BindShortcuts takes).

    CreateSession, then BindShortcuts, each answered by a Response signal on
    its Request object, whose path is known before the call (the portal's
    documented handle_token rule) -- so it is subscribed first. Then the
    session's Activated signal fires `on_activated`. All on a thread of its
    own with its own GLib main context, so nothing depends on Qt's event
    dispatcher being GLib's. The desktop shows its approval dialog once."""

    def __init__(self, on_activated, trigger: str = "F12", bus=None, token: str = "hivemind"):
        self.on_activated = on_activated
        self.trigger = trigger
        self._bus = bus
        self.token = token
        self.state = "off"           # off -> asking -> bound | failed
        self.reason = ""
        self.session = ""
        self._loop = None

    @staticmethod
    def _glib():
        from gi.repository import Gio, GLib       # noqa: F401 -- PyGObject
        return Gio, GLib

    def available(self) -> tuple[bool, str]:
        """Is the portal there? A property read, nothing asked of the user."""
        try:
            Gio, GLib = self._glib()
        except Exception as exc:
            return False, f"PyGObject is not installed ({exc.__class__.__name__})"
        try:
            bus = self._bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
            reply = bus.call_sync(PORTAL_NAME, PORTAL_PATH, "org.freedesktop.DBus.Properties",
                                  "Get", GLib.Variant("(ss)", (PORTAL_IFACE, "version")),
                                  GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 1500, None)
            return True, f"version {reply.unpack()[0]}"
        except Exception as exc:
            return False, f"no GlobalShortcuts portal ({str(exc)[:80]})"

    def start(self) -> "PortalShortcut":
        """Ask for the shortcut; returns at once. `state` follows."""
        self.state = "asking"
        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready,), daemon=True,
                         name="hivemind-panic-portal").start()
        ready.wait(2.0)
        return self

    def _run(self, ready: threading.Event) -> None:
        try:
            Gio, GLib = self._glib()
            context = GLib.MainContext()
            context.push_thread_default()    # signals for this thread's loop
            bus = self._bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._loop = GLib.MainLoop(context)
            sender = bus.get_unique_name()[1:].replace(".", "_")
            self.session = f"{PORTAL_PATH}/session/{sender}/{self.token}"

            def request(token: str, then) -> str:
                path = f"{PORTAL_PATH}/request/{sender}/{token}"
                sub = []

                def answered(_bus, _sender, _path, _iface, _signal, params):
                    bus.signal_unsubscribe(sub[0])
                    code, results = params.unpack()
                    then(code, results)
                sub.append(bus.signal_subscribe(PORTAL_NAME, "org.freedesktop.portal.Request",
                                                "Response", path, None,
                                                Gio.DBusSignalFlags.NONE, answered))
                return path

            def activated(_bus, _sender, _path, _iface, _signal, params):
                session, shortcut = params.unpack()[:2]
                if session == self.session and shortcut == SHORTCUT_ID:
                    self.on_activated()

            def bound(code, results):
                if code == 0:
                    self.state = "bound"
                    self.reason = "bound" + (
                        f" ({results['shortcuts'][0][1].get('trigger_description', '')})"
                        if results.get("shortcuts") else "")
                else:
                    self.state, self.reason = "failed", f"the desktop declined (answer {code})"

            def created(code, results):
                if code != 0:
                    self.state, self.reason = "failed", f"no session (answer {code})"
                    return
                self.session = str(results.get("session_handle", self.session))
                bus.signal_subscribe(PORTAL_NAME, PORTAL_IFACE, "Activated", PORTAL_PATH,
                                     None, Gio.DBusSignalFlags.NONE, activated)
                request(self.token + "_bind", bound)
                shortcut = (SHORTCUT_ID, {"description": GLib.Variant("s", DESCRIPTION),
                                          "preferred_trigger": GLib.Variant("s", self.trigger)})
                bus.call(PORTAL_NAME, PORTAL_PATH, PORTAL_IFACE, "BindShortcuts",
                         GLib.Variant("(oa(sa{sv})sa{sv})",
                                      (self.session, [shortcut], "",
                                       {"handle_token": GLib.Variant("s", self.token + "_bind")})),
                         None, Gio.DBusCallFlags.NONE, -1, None, None)

            request(self.token, created)
            bus.call_sync(PORTAL_NAME, PORTAL_PATH, PORTAL_IFACE, "CreateSession",
                          GLib.Variant("(a{sv})", ({
                              "handle_token": GLib.Variant("s", self.token),
                              "session_handle_token": GLib.Variant("s", self.token)},)),
                          None, Gio.DBusCallFlags.NONE, 5000, None)
            ready.set()
            self._loop.run()
        except Exception as exc:
            self.state, self.reason = "failed", f"{exc.__class__.__name__}: {str(exc)[:80]}"
            ready.set()

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.quit()


# ---- X11 ------------------------------------------------------------------------
class X11Grab:
    """F12 grabbed on the X11 root window (XGrabKey via ctypes libX11: no
    python-xlib needed). With Caps/Num Lock too, so the locks do not hide it.
    A grab another program already holds is BadAccess, caught by our own
    error handler (Xlib's default one exits the process) and reported."""

    KEYPRESS, GRAB_ASYNC = 2, 1
    LOCK_MASK, MOD2_MASK = 1 << 1, 1 << 4

    def __init__(self, on_press, key: str = "F12", lib=None):
        self.on_press = on_press
        self.key = key
        self._lib = lib
        self._dpy = None
        self._stop = threading.Event()
        self.reason = ""
        self._errors: list[int] = []
        self._handler = None

    def _load(self):
        if self._lib is not None:
            return self._lib
        name = ctypes.util.find_library("X11")
        if not name:
            raise OSError("libX11 not found")
        lib = ctypes.CDLL(name)
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XStringToKeysym.restype = ctypes.c_ulong
        lib.XStringToKeysym.argtypes = [ctypes.c_char_p]
        lib.XKeysymToKeycode.restype = ctypes.c_ubyte
        lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong]
        lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XPending.argtypes = [ctypes.c_void_p]
        lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.XConnectionNumber.argtypes = [ctypes.c_void_p]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        return lib

    def start(self) -> bool:
        try:
            lib = self._load()
            dpy = lib.XOpenDisplay(None)
            if not dpy:
                self.reason = "cannot open the X display"
                return False
            handler_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

            def on_error(_dpy, event):
                self._errors.append(1)
                return 0
            self._handler = handler_type(on_error)        # kept: ctypes must not free it
            lib.XSetErrorHandler(self._handler)
            code = lib.XKeysymToKeycode(dpy, lib.XStringToKeysym(self.key.encode()))
            if not code:
                self.reason = f"no keycode for {self.key}"
                lib.XCloseDisplay(dpy)
                return False
            root = lib.XDefaultRootWindow(dpy)
            self._grabs = [(code, mods) for mods in (0, self.LOCK_MASK, self.MOD2_MASK,
                                                     self.LOCK_MASK | self.MOD2_MASK)]
            for c, mods in self._grabs:
                lib.XGrabKey(dpy, c, mods, root, 0, self.GRAB_ASYNC, self.GRAB_ASYNC)
            lib.XSync(dpy, 0)
            if self._errors:
                self.reason = f"another program already holds {self.key}"
                lib.XCloseDisplay(dpy)
                return False
        except Exception as exc:
            self.reason = f"{exc.__class__.__name__}: {exc}"
            return False
        self._lib, self._dpy, self._root = lib, dpy, root
        self.reason = f"grabbed {self.key} on the X11 desktop"
        threading.Thread(target=self._loop, daemon=True, name="hivemind-panic-x11").start()
        return True

    def _loop(self) -> None:
        lib, dpy = self._lib, self._dpy
        fd = lib.XConnectionNumber(dpy)
        event = ctypes.create_string_buffer(192)          # sizeof(XEvent) is 192 on 64-bit
        while not self._stop.is_set():
            try:
                select.select([fd], [], [], 0.4)
            except (OSError, ValueError):
                break
            while lib.XPending(dpy):
                lib.XNextEvent(dpy, event)
                if ctypes.c_int.from_buffer(event).value == self.KEYPRESS:
                    try:
                        self.on_press()
                    except Exception:
                        pass                  # the next press must still work
        for c, mods in self._grabs:
            lib.XUngrabKey(dpy, c, mods, self._root)
        lib.XCloseDisplay(dpy)

    def stop(self) -> None:
        self._stop.set()


# ---- the layers -------------------------------------------------------------------
class PanicLayers(QObject):
    """Arms every layer this machine allows (see the module doc). `fired`
    carries the layer's name; connect it to the window's Stop."""

    fired = Signal(str)

    def __init__(self, window, key: str = "F12", env=None, evdev=None,
                 portal=None, x11=None, allow_global: bool | None = None):
        super().__init__(window)
        self.window = window
        self.key = key or "F12"
        self.env = os.environ if env is None else env
        self._evdev = evdev if evdev is not None else evdev_readable
        self._portal = portal if portal is not None else (
            lambda fire: PortalShortcut(fire, self.key))
        self._x11 = x11 if x11 is not None else (lambda fire: X11Grab(fire, self.key))
        # A TEST NEVER ASKS THE REAL DESKTOP (module doc), unless it brings
        # its own layers.
        self.allow_global = (allow_global if allow_global is not None else
                             not self.env.get("PYTEST_CURRENT_TEST")
                             or portal is not None or x11 is not None)
        self.active: list[str] = []
        self.notes: dict[str, str] = {}
        self.portal = self.grab = None

    def _fire(self, layer: str) -> None:
        """From any thread: Qt queues the signal to the window's thread."""
        self.fired.emit(layer)

    def start(self) -> list[str]:
        # ALWAYS: the window's own shortcut, wherever the focus is in it
        self.shortcut = QShortcut(QKeySequence(self.key), self.window,
                                  context=Qt.ApplicationShortcut)
        self.shortcut.activated.connect(lambda: self._fire("gui"))
        self.active = [f"GUI {self.key}"]
        self.notes["gui"] = "while Hivemind has focus, and the Stop button"
        if self._evdev():
            self.active.append("evdev (the bot's)")
            self.notes["evdev"] = "the bot reads the keyboard (input group)"
            return self.active
        self.notes["evdev"] = "not in the input group"
        if not self.allow_global:
            self.notes["global"] = "not armed under tests"
            return self.active
        where = host(self.env)
        if where == "wayland":
            self.portal = self._portal(lambda: self._fire("portal"))
            ok, why = self.portal.available()
            self.notes["portal"] = why
            if ok:
                self.portal.start()
                self.active.append("portal")
        elif where == "x11":
            self.grab = self._x11(lambda: self._fire("x11"))
            if self.grab.start():
                self.active.append("X11 grab")
            self.notes["x11"] = self.grab.reason
        return self.active

    def describe(self) -> str:
        """The log line: "panic key: GUI F12 + portal"."""
        return "panic key: " + " + ".join(self.active or ["none"])

    def global_layer(self) -> bool:
        """Does a layer work while Hivemind does NOT have focus?"""
        return len(self.active) > 1

    def stop(self) -> None:
        for layer in (self.portal, self.grab):
            if layer is not None:
                try:
                    layer.stop()
                except Exception:
                    pass
