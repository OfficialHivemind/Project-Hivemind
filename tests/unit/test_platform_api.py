"""RL6 phase 1: the platform interfaces exist, and today's Linux classes fit
them -- or differ in exactly the places docs/pending/windows-port.md names.

A new difference fails here: either the Linux class drifted from the seam, or
the seam needs updating, and the plan with it."""
from __future__ import annotations

import ast
from pathlib import Path

import os

import pytest

from hivemind.platform import api

# What phase 2 has to add or change on the Linux side; everything else fits.
EXPECTED = {
    "Capture": [],
    "Input": [],
    "GameSession": [],
    "KeptGame": [],
    "ClientLog": [],
    "GameGuard": [],
    "Memory": [],
    "PanicKey": [],
    "Paths": [],
    "Processes": [],
    "Watchdog": [],
}


def _linux(name):
    """The Linux implementation of one interface (imported here, so a box
    without pywayland skips rather than fails)."""
    if name == "Capture":
        return pytest.importorskip("hivemind.platform.wl.screencopy").ScreenCopy
    if name == "Input":
        return pytest.importorskip("hivemind.platform.input").VirtualInput
    from hivemind.platform import clientlog, gameguard, memory, panic, session
    from hivemind import datapaths, files
    if name == "Watchdog":
        from hivemind.gui.launcher import BotProcess
        return BotProcess
    return {
        "GameSession": lambda: session.Session(),        # a dataclass: starts nothing
        "KeptGame": lambda: session,
        "ClientLog": lambda: clientlog.ClientLog("/nonexistent/hivemind-test.log"),
        "GameGuard": lambda: gameguard,
        "Memory": lambda: memory,
        "PanicKey": lambda: panic.PanicWatcher(on_panic=lambda: None),  # not started
        "Paths": lambda: datapaths,
        "Processes": lambda: files,
    }[name]()


def test_every_interface_is_listed():
    assert {p.__name__ for p in api.INTERFACES} == set(EXPECTED)


@pytest.mark.parametrize("proto", api.INTERFACES, ids=lambda p: p.__name__)
def test_linux_fits_or_differs_exactly_as_planned(proto):
    assert api.differences(proto, _linux(proto.__name__)) == EXPECTED[proto.__name__]


def test_differences_catches_drift():
    class Moved:
        refuse_to_type = in_game = True

        def tap(self, key, *, ms=40): ...            # ms went keyword-only

        def drag(self, x0, y0, x1, y1, extra): ...   # a new required parameter

    found = api.differences(api.Input, Moved)
    assert "tap: 'ms' is keyword-only" in found
    assert "drag: requires extra 'extra'" in found
    assert "missing press" in found
    assert "missing held_keys" in found


def test_api_imports_nothing_platform_specific():
    """It must import on Windows: stdlib only."""
    tree = ast.parse(Path(api.__file__).read_text())
    names = {a.name.split(".")[0] for n in ast.walk(tree)
             if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree)
              if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
    assert names <= {"__future__", "contextlib", "inspect", "pathlib", "typing"}


def test_capture_errors_live_in_api_and_are_reexported():
    """Phase 2 step 1: every old `from ...wl.screencopy import CaptureFailed`
    still catches the same class."""
    sc = pytest.importorskip("hivemind.platform.wl.screencopy")
    assert sc.CaptureFailed is api.CaptureFailed
    assert sc.CaptureTimeout is api.CaptureTimeout
    assert issubclass(api.CaptureTimeout, api.CaptureFailed)


def test_linux_paths_are_the_old_literals(monkeypatch):
    """Phase 2 step 2: the Paths functions move nothing on Linux."""
    import os
    from hivemind import datapaths as dp
    if dp.WINDOWS:
        pytest.skip("Linux paths")
    home = Path.home()
    assert dp.config_dir() == home / ".config/hivemind"
    assert dp.session_logs_dir() == home / ".var/app/org.vinegarhq.Sober/data/sober/sober_logs"
    assert dp.client_log() == dp.var("sober.log")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert dp.runtime_dir() == Path("/run/user/1000")
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert dp.runtime_dir() == Path(f"/run/user/{os.getuid()}")


def test_game_window_open_is_the_old_hyprctl_test(monkeypatch):
    """Phase 2 step 3: the same `"class:" in hyprctl("clients")` as before."""
    from hivemind.platform import session
    s = session.Session()
    asked = []
    out = {"text": ""}
    monkeypatch.setattr(s, "hyprctl", lambda *a: asked.append(a) or out["text"])
    assert s.game_window_open() is False
    out["text"] = "Window 1 -> x:\n\tclass: org.vinegarhq.Sober"
    assert s.game_window_open() is True
    assert s.describe_windows() == out["text"]
    assert asked == [("clients",)] * 3


@pytest.mark.skipif(os.name == "nt", reason="on Windows current builds the win classes")
def test_current_builds_the_linux_classes():
    """Phase 2 step 5: bootstrap builds through platform/current, whose
    factories are the constructors it called before."""
    current = pytest.importorskip("hivemind.platform.current")
    from hivemind.platform import panic, session
    s = current.make_session(1920, 1080)
    assert type(s) is session.Session and (s.width, s.height) == (1920, 1080)
    assert current.kept is session
    p = current.make_panic(lambda: None, "F12")
    assert isinstance(p, panic.PanicWatcher) and p.key == "F12"
    import hivemind
    src = (Path(hivemind.__file__).parent / "act" / "bootstrap.py").read_text()
    for direct in ("ScreenCopy(", "VirtualInput(", "WlConnection(", "PanicWatcher(", "Session("):
        assert direct not in src, direct


def test_current_is_light_and_the_same_modules_on_linux():
    """Phase 3 wiring: readers of current.memory/gameguard/files get exactly
    the modules they imported before, and importing current pulls in no
    Wayland or evdev (the factories import those when called)."""
    import os
    import subprocess
    import sys
    from hivemind import files
    from hivemind.platform import current, gameguard, memory, session
    if current.WINDOWS:
        pytest.skip("Linux modules")
    assert (current.memory, current.gameguard, current.files, current.kept) == (
        memory, gameguard, files, session)
    code = ("import sys, hivemind.platform.current as c; "
            "print(sorted(m for m in ('pywayland', 'evdev', 'hivemind.platform.wl.connection') "
            "if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert out.stdout.strip() == "[]", out.stderr


def test_the_import_time_breakers_are_gone():
    """Phase 2 step 6: nothing evaluated at import needs a POSIX-only call
    (session's os.getuid, the launcher's os.killpg/os.getpgid defaults,
    run_farm's signal.SIGUSR1)."""
    import inspect
    import hivemind
    from hivemind.gui.launcher import BotProcess
    params = inspect.signature(BotProcess.__init__).parameters
    assert params["killpg"].default is None and params["getpgid"].default is None
    root = Path(hivemind.__file__).resolve().parents[2]
    tree = ast.parse((root / "src/hivemind/platform/session.py").read_text())
    top = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    assert "getuid" not in "".join(ast.unparse(n) for n in top)
    assert 'if hasattr(signal, "SIGUSR1"):' in (root / "scripts/run_farm.py").read_text()


# ---------------------------------------------------------------------------
# RL6 phase 3: the Windows implementations fit the same seam. They import on
# Linux (DLLs and Windows-only libraries are loaded lazily), so this runs here.
# Watchdog: gui/launcher's BotProcess over hivemind/watchdog on Windows.
# ---------------------------------------------------------------------------
def _windows(name):
    from hivemind.platform.win import capture, files, gameguard, input, memory, panic, session
    return {
        "GameSession": lambda: session.WinSession,
        "KeptGame": lambda: session,
        "Capture": lambda: capture.WinCapture,
        "Input": lambda: input.WinInput,
        "GameGuard": lambda: gameguard,
        "Memory": lambda: memory,
        "PanicKey": lambda: panic.WinPanicWatcher(on_panic=lambda: None),  # not started
        "Processes": lambda: files,
        "ClientLog": lambda: pytest.importorskip("hivemind.platform.clientlog").ClientLog(
            "/nonexistent/hivemind-test.log"),                            # shared class
        "Paths": lambda: pytest.importorskip("hivemind.datapaths"),       # shared module
    }[name]()


WINDOWS_BUILT = ("Capture", "Input", "GameSession", "KeptGame", "GameGuard", "Memory",
                 "PanicKey", "Processes", "ClientLog", "Paths")


@pytest.mark.parametrize("name", WINDOWS_BUILT)
def test_windows_fits_the_seam(name):
    assert api.differences(getattr(api, name), _windows(name)) == []


def test_windows_modules_import_nothing_windows_only_at_top_level():
    """win/* must import on Linux for these tests and must not crash on a
    Windows box missing an optional library: ctypes.WinDLL, winreg, msvcrt,
    windows_capture and dxcam are only touched inside functions."""
    import hivemind
    win = Path(hivemind.__file__).parent / "platform" / "win"
    lazy = {"winreg", "msvcrt", "windows_capture", "dxcam", "win32api", "pywintypes"}
    for path in sorted(win.glob("*.py")):
        tree = ast.parse(path.read_text())
        top = {a.name.split(".")[0] for n in tree.body if isinstance(n, ast.Import) for a in n.names}
        top |= {n.module.split(".")[0] for n in tree.body
                if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
        assert not top & lazy, f"{path.name} imports {sorted(top & lazy)} at top level"


def test_current_picks_the_windows_classes_on_win32(monkeypatch):
    """Phase 3 step 5: under sys.platform == "win32", platform/current builds
    win/*; Linux keeps its own (test_current_builds_the_linux_classes)."""
    import importlib
    import sys
    import hivemind.platform as pkg
    from hivemind.platform.win import files, gameguard, input, memory, panic
    from hivemind.platform.win import session as win_session
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delitem(sys.modules, "hivemind.platform.current", raising=False)
    if hasattr(pkg, "current"):
        monkeypatch.setattr(pkg, "current", pkg.current)
    current = importlib.import_module("hivemind.platform.current")
    try:
        assert current.WINDOWS
        assert (current.files, current.gameguard, current.memory) == (files, gameguard, memory)
        p = current.make_panic(lambda: None, "F11")
        assert isinstance(p, panic.WinPanicWatcher) and p.key == "F11"
        assert current.kept is win_session
        s = current.make_session(1920, 1080)
        assert type(s) is win_session.WinSession and (s.width, s.height) == (1920, 1080)
        a = current.attach_session({"game_pid": 9, "started": "1.000", "hwnd": 7})
        assert (a.pid, a.started, a.hwnd) == (9, "1.000", 7)
        session = type("S", (), {"game_hwnd": lambda self: 7, "width": 1920, "height": 1080})()
        assert current.connect(session) is session
        vin = input.WinInput.__new__(input.WinInput)
        made = {}
        monkeypatch.setattr(current, "WinInput", lambda **kw: made.update(kw) or vin)
        assert current.make_input(session) is vin and made["window"]() == 7
        monkeypatch.setattr(current, "WinCapture", lambda **kw: made.update(cap=kw) or "cap")
        assert current.make_capture(session) == "cap" and made["cap"]["window"]() == 7
    finally:
        sys.modules.pop("hivemind.platform.current", None)
