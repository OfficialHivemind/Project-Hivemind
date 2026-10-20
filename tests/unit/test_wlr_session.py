"""platform/wlr_session (RL1b step 1): the game in a headless labwc.

Unit tests with the compositor mocked, then one live test that starts a real
labwc headless (when $HIVEMIND_LABWC or `labwc` on PATH gives one; skipped
otherwise), opens tools/universal/probe.py's stand-in window -- never Sober --
and drives it with the bot's own capture and input."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hivemind.platform import api, gameguard
from hivemind.platform import session as sm
from hivemind.platform import wlr_session as wm

ROOT = Path(__file__).resolve().parents[2]

# LINUX ONLY (MEASURED 2026-10-26 on the Windows PC: 6 tests fail there on
# os.getuid and a missing labwc). tests/conftest.py already leaves this module
# out of a Windows run of tests/unit; this covers naming the file.
pytestmark = pytest.mark.skipif(os.name == "nt", reason="the labwc / wlroots session: "
                                "needs Linux (os.getuid, labwc, Wayland)")


# ---- the seam ---------------------------------------------------------------
def test_it_fits_the_game_session_seam():
    assert api.differences(api.GameSession, wm.WlrSession()) == []


class _Settings:
    value = "hyprland"

    def get(self, key, fallback=None):
        assert key == "platform.compositor"
        return self.value


@pytest.mark.parametrize("value, cls", [("hyprland", sm.Session), ("labwc", wm.WlrSession),
                                        ("nonsense", sm.Session)])
def test_the_setting_picks_the_session(monkeypatch, value, cls):
    from hivemind.platform import current
    from hivemind.world import settings
    monkeypatch.setattr(settings, "Settings", type("S", (_Settings,), {"value": value}))
    made = current.make_session(1920, 1080)
    assert type(made) is cls and (made.width, made.height) == (1920, 1080)
    record = {"socket": "wayland-3", "signature": "wayland-3", "hypr_pid": 7}
    kept = current.attach_session(record)
    assert type(kept) is cls and kept.pid == 7 and kept.socket == "wayland-3"


# ---- finding labwc ----------------------------------------------------------
def test_labwc_from_the_env_brings_its_own_libraries(monkeypatch, tmp_path):
    bin_ = tmp_path / "root/usr/bin/labwc"
    lib = tmp_path / "root/usr/lib"
    bin_.parent.mkdir(parents=True)
    lib.mkdir()
    bin_.write_text("#!/bin/sh\n")
    bin_.chmod(0o755)
    monkeypatch.setenv(wm.LABWC_ENV, str(bin_))
    assert wm.find_labwc() == (str(bin_), None)          # no wlroots beside it
    (lib / "libwlroots-0.20.so").write_text("")
    assert wm.find_labwc() == (str(bin_), str(lib))
    monkeypatch.delenv(wm.LABWC_ENV)
    monkeypatch.setattr(wm.shutil, "which", lambda name: None)
    assert wm.find_labwc() is None


# ---- starting it (no compositor) --------------------------------------------
class _FakeProc:
    def __init__(self, argv, env, mark, **_kw):
        self.argv, self.env, self.pid = argv, env, 4242
        mark.write_text("wayland-7\n")       # what labwc's -s helper writes
        self.terminated = 0

    def poll(self):
        return None

    def terminate(self):
        self.terminated += 1

    def wait(self, timeout=None):
        return 0


def test_start_runs_labwc_headless_with_our_config(monkeypatch, tmp_path):
    cfg = tmp_path / "labwc"
    monkeypatch.setenv(wm.LABWC_ENV, "/bin/true")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/x")
    made = []
    monkeypatch.setattr(wm.subprocess, "Popen",
                        lambda argv, env, **kw: made.append(_FakeProc(argv, env, cfg / "socket"))
                        or made[-1])
    sizes = []

    class _Control:
        def __init__(self, socket):
            self.socket = socket

        def set_size(self, w, h):
            sizes.append((self.socket, w, h))
            return True

        def __enter__(self): return self
        def __exit__(self, *exc): pass

    monkeypatch.setattr(wm, "Control", _Control)
    monkeypatch.setattr(wm, "kill_marked", lambda marker, program: 0)
    s = wm.WlrSession(config_path=cfg, runtime=sm.RUNTIME).start(attempts=1)
    proc = made[0]
    assert proc.argv[:3] == ["/bin/true", "-C", str(cfg)] and proc.argv[3] == "-s"
    assert proc.env["WLR_BACKENDS"] == "headless"
    for gone in ("WAYLAND_DISPLAY", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
        assert gone not in proc.env, gone
    assert 'identifier="org.vinegarhq.Sober"' in (cfg / "rc.xml").read_text()
    assert (s.socket, s.signature, s.compositor_pid()) == ("wayland-7", "wayland-7", 4242)
    assert sizes == [("wayland-7", 1920, 1080)]
    s.stop()
    assert proc.terminated == 1 and s.proc is None
    # a private runtime dir gives an absolute socket (libwayland and flatpak take both)
    s2 = wm.WlrSession(config_path=cfg, runtime=tmp_path).start(attempts=1)
    assert s2.socket == str(tmp_path / "wayland-7")


def test_a_size_that_does_not_take_is_a_failed_start(monkeypatch, tmp_path):
    cfg = tmp_path / "labwc"
    monkeypatch.setenv(wm.LABWC_ENV, "/bin/true")
    monkeypatch.setattr(wm.subprocess, "Popen",
                        lambda argv, env, **kw: _FakeProc(argv, env, cfg / "socket"))
    monkeypatch.setattr(wm, "Control", type("C", (), {
        "__init__": lambda self, s: None, "set_size": lambda self, w, h: False,
        "__enter__": lambda self: self, "__exit__": lambda self, *e: None}))
    monkeypatch.setattr(wm, "kill_marked", lambda marker, program: 0)
    with pytest.raises(RuntimeError, match="1920x1080"):
        wm.WlrSession(config_path=cfg).start(attempts=1)


def test_no_labwc_is_said_plainly(monkeypatch, tmp_path):
    monkeypatch.setattr(wm, "find_labwc", lambda: None)
    monkeypatch.setattr(wm, "kill_marked", lambda marker, program: 0)
    with pytest.raises(RuntimeError, match=wm.LABWC_ENV):
        wm.WlrSession(config_path=tmp_path).start(attempts=1)


def test_no_desktop_window_means_nothing_to_minimize_or_focus():
    s = wm.WlrSession()
    assert s.host_window_minimized() is None and s.restore_below() is False
    assert s.give_back_focus() == "" and "headless" in s.release_alt()


# ---- identity -------------------------------------------------------------
def _fake_proc(monkeypatch, table):
    """table: pid -> argv list."""
    monkeypatch.setattr(sm, "_proc_text", lambda pid, name: (
        b"\0".join(a.encode() for a in table.get(int(pid), [])) if name == "cmdline" else b""))


def test_our_labwc_is_ours_and_nothing_else_is(monkeypatch):
    cfg = "/home/x/.config/hivemind/labwc"
    _fake_proc(monkeypatch, {
        1: ["/opt/l/usr/bin/labwc", "-C", cfg, "-s", "sh -c ..."],
        2: ["sh", "-c", f"echo $WAYLAND_DISPLAY > {cfg}/socket"],     # its -s helper
        3: ["labwc", "-C", "/home/x/.config/labwc"],                   # someone's own
        4: ["Hyprland", "-c", "/home/x/.config/hivemind/nested.lua"]})
    assert sm.ours_compositor(1, cfg) and sm.is_labwc(1)
    assert not sm.ours_compositor(2, cfg) and not sm.ours_compositor(3, cfg)
    assert sm.ours_compositor(4, "/home/x/.config/hivemind/nested.lua")


def test_the_stale_labwc_is_ended_but_never_its_helper_shell(monkeypatch):
    cfg = "/home/x/.config/hivemind/labwc"
    _fake_proc(monkeypatch, {11: ["/usr/bin/labwc", "-C", cfg], 12: ["sh", "-c", f"x {cfg}"]})
    listing = f"11 /usr/bin/labwc -C {cfg}\n12 sh -c x {cfg}\n"
    monkeypatch.setattr(sm.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout=listing, stderr=""))
    sent = []
    monkeypatch.setattr(sm.os, "kill", lambda pid, sig: sent.append(pid))
    assert sm.kill_marked(cfg, "labwc") == 1 and sent == [11]


def test_a_labwc_record_is_checked_by_its_own_windows(monkeypatch, tmp_path):
    """Same JSON as Hyprland's; the game is looked for over foreign-toplevel."""
    monkeypatch.setattr(sm, "RUNTIME", tmp_path)
    (tmp_path / "wayland-5").write_text("")
    monkeypatch.setattr(sm, "ours_compositor", lambda pid, cfg: True)
    monkeypatch.setattr(sm, "is_labwc", lambda pid: True)
    monkeypatch.setattr(sm, "game_in", lambda sig: pytest.fail("hyprctl asked"))
    there = {"v": True}
    monkeypatch.setattr(wm, "game_in_socket", lambda socket: there["v"])
    path = tmp_path / "session.json"
    sm.keep_session(path, socket="wayland-5", signature="wayland-5", hypr_pid=99,
                    game_pid=100, joined_at=5.0)
    assert list(json.loads(path.read_text()))[:5] == [
        "socket", "signature", "hypr_pid", "game_pid", "joined_at"]
    assert sm.kept_session_why(path, "/cfg")[0]["hypr_pid"] == 99
    there["v"] = False
    assert sm.kept_session_why(path, "/cfg") == (
        None, "the kept game is no longer running in that compositor")


def test_the_game_guard_knows_our_labwc_sober(tmp_path):
    # THE BOT'S SOBER RUNS UNDER ITS LAUNCHER (gameguard.OURS_TAG, b029b0f,
    # 2026-10-20): "sh -c ... hivemind-game ..." is its parent. Without that
    # ancestor a Sober is the owner's (red here from 20 Oct until the full
    # suite ran on 2026-10-21: this fixture's Sober had no parent at all).
    cfg = "/home/x/.config/hivemind/labwc"
    uid = os.getuid()
    for pid, ppid, argv, comm in (
            (40, 1, ["/usr/bin/labwc", "-C", cfg], "labwc"),
            (41, 40, ["sh", "-c", f"exec -a {gameguard.OURS_TAG} sober roblox://x"], "sh"),
            (42, 41, ["sober", "roblox://x"], "sober")):
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (d / "comm").write_text(comm + "\n")
        (d / "environ").write_bytes(b"")
        (d / "status").write_text(f"Name:\t{comm}\nPPid:\t{ppid}\nUid:\t{uid}\t0\t0\t0\n")
    assert gameguard.playing(proc=tmp_path, uid=uid, labwc_config=cfg) is None
    # and a Sober NOT under our launcher is the owner's, compositor up or not
    (tmp_path / "42" / "status").write_text(f"Name:\tsober\nPPid:\t1\nUid:\t{uid}\t0\t0\t0\n")
    assert gameguard.playing(proc=tmp_path, uid=uid, labwc_config=cfg) \
        == "Roblox (your own Sober)"


# ---- the doctor -------------------------------------------------------------
def test_the_doctor_asks_for_labwc_not_hyprland(monkeypatch):
    from hivemind.cli import doctor
    monkeypatch.setattr(wm, "find_labwc", lambda: None)
    names = {c.name: c for c in doctor.environment("arch", compositor="labwc")}
    assert "hyprctl (comes with Hyprland)" not in names and "Hyprland 0.56+" not in names
    check = names["labwc (headless compositor)"]
    assert check.status == doctor.FAIL and "pacman" in check.fix and wm.LABWC_ENV in check.fix
    assert names["a Wayland desktop session"].status == doctor.OK
    monkeypatch.setattr(wm, "find_labwc", lambda: ("/usr/bin/labwc", None))
    names = {c.name: c for c in doctor.environment("arch", compositor="labwc")}
    assert names["labwc (headless compositor)"].status == doctor.OK
    hypr = {c.name for c in doctor.environment("arch", compositor="hyprland")}
    assert "hyprctl (comes with Hyprland)" in hypr and "labwc (headless compositor)" not in hypr


# ---- live: a real labwc, the bot's own capture and input, a stand-in game ----
def _wait(cond, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.2)
    return cond()


@pytest.mark.skipif(wm.find_labwc() is None,
                    reason="no labwc: set HIVEMIND_LABWC (tools/universal/fetch_compositor.sh)")
def test_live_headless_labwc_with_a_stand_in_game(tmp_path):
    pytest.importorskip("pywayland")
    pytest.importorskip("PySide6")
    from hivemind.platform import current
    runtime = Path(f"/tmp/hm-rl1c-{os.getpid()}")      # a socket path fits in 108 bytes
    runtime.mkdir(mode=0o700)
    log = tmp_path / "window.log"
    s = wm.WlrSession(config_path=tmp_path / "labwc", runtime=runtime,
                      game_id="hivemind-probe")
    window = conn = cap = inp = None
    try:
        s.start(timeout=20, attempts=1)
        assert not s.game_window_open()
        env = {**os.environ, "WAYLAND_DISPLAY": s.socket, "QT_QPA_PLATFORM": "wayland",
               "PROBE_WINDOWED": "1", "PROBE_APP_ID": "hivemind-probe"}
        env.pop("DISPLAY", None)
        window = subprocess.Popen([sys.executable, str(ROOT / "tools/universal/probe.py"),
                                   "window", str(log)], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert _wait(s.game_window_open, 20), s.describe_windows()
        # the rc.xml rule fullscreened it on map (it opened 800x600)
        assert _wait(lambda: "fullscreen" in s.describe_windows(), 5), s.describe_windows()
        assert "app_id: hivemind-probe" in s.describe_windows()
        time.sleep(1.0)                        # let the fullscreen frame land

        conn = current.connect(s)
        cap = current.make_capture(conn)
        frame = cap.capture()
        assert frame.shape[:2] == (1080, 1920)            # wlr-output-management took
        top = frame[5, 960]
        assert top[0] > 200 and top[2] < 50, top           # upright, channels right
        inp = current.make_input(s)
        inp.focus_game(960, 540)
        inp.tap("w")
        inp.click(480, 270)
        assert _wait(lambda: cap.capture()[540, 960][1] > 200, 3)   # green: W arrived
        seen = log.read_text()
        assert "key 'w'" in seen and "size 1920x1080" in seen, seen

        s.leave_fullscreen()
        assert _wait(lambda: "fullscreen" not in s.describe_windows(), 3)
        s.fullscreen_focused()
        assert _wait(lambda: "fullscreen" in s.describe_windows(), 3)

        # the kept-session checks: socket and pid pass for OUR labwc, and the
        # game check looks for Sober over foreign-toplevel (not here: a stand-in)
        rec = tmp_path / "session.json"
        sm.keep_session(rec, socket=s.socket, signature=s.signature,
                        hypr_pid=s.compositor_pid(), game_pid=window.pid, joined_at=None)
        assert sm.kept_session_why(rec, s.config_path) == (
            None, "the kept game is no longer running in that compositor")
        assert wm.game_in_socket(s.socket, "hivemind-probe")
    finally:
        for closer in (inp, cap, conn):
            if closer is not None:
                closer.close()
        if window is not None:
            window.kill()
            window.wait(timeout=5)
        pid = s.compositor_pid()
        s.stop()
        if pid:
            assert not Path(f"/proc/{pid}").exists() or \
                b"zombie" in Path(f"/proc/{pid}/status").read_bytes().lower()
        for p in runtime.iterdir():
            p.unlink()
        runtime.rmdir()
