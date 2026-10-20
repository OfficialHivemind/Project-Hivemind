"""The alt account's bot (HIVEMIND_ROLE=alt, tools/alt) must not disturb the
main's: a display-less parent instead of the owner's desktop, no KWin window
calls, the shared vision model left alone, and the memory lines raised so the
alt steps aside first."""
from __future__ import annotations

import os
import subprocess
import sys


def test_render_node_is_the_one_with_most_vram(tmp_path):
    from hivemind.platform import session as mod
    for name, vram in (("renderD128", 16 << 30), ("renderD129", 512 << 20)):
        (tmp_path / name / "device").mkdir(parents=True)
        (tmp_path / name / "device/mem_info_vram_total").write_text(f"{vram}\n")
    (tmp_path / "renderD130").mkdir()                 # no vram file: skipped
    assert mod.render_node(tmp_path) == "/dev/dri/renderD128"
    assert mod.render_node(tmp_path / "none") is None


def test_parent_argv_hides_other_gpus_only_when_it_can(monkeypatch):
    from hivemind.platform import session as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/" + name)
    argv = mod.parent_argv(1920, 1080, "/dev/dri/renderD128")
    assert argv[:9] == ["bwrap", "--dev-bind", "/", "/", "--tmpfs", "/dev/dri",
                        "--dev-bind", "/dev/dri/renderD128", "/dev/dri/renderD128"]
    assert mod.PARENT_MARK in " ".join(argv) and "--virtual" in argv
    assert mod.parent_argv(1920, 1080, None)[0] == "dbus-run-session"


def test_a_headless_session_asks_no_desktop_about_its_window(monkeypatch):
    from hivemind.platform import session as mod

    def no_run(*a, **k):
        raise AssertionError("a headless session has no window to ask KWin about")
    monkeypatch.setattr(mod.subprocess, "run", no_run)
    s = mod.Session(headless=True, pid=4242)
    assert s.host_window_minimized() is None
    assert s.give_back_focus(wait_s=5) == ""
    assert s.restore_below() is False


def test_hyprland_is_put_on_the_parent_not_the_desktop(monkeypatch, tmp_path):
    from hivemind.platform import session as mod
    seen = {}

    class Hypr:
        pid = 1

        def poll(self):
            return 0                     # "exited": _start_once stops there

    def popen(argv, **kw):
        seen.update(argv=argv, env=kw.get("env"))
        return Hypr()
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(mod.subprocess, "Popen", popen)
    monkeypatch.setattr(mod.Session, "_start_parent", lambda self, t: None)
    s = mod.Session(headless=True, config_path=tmp_path / "nested.lua")
    try:
        s._start_once(timeout=1)
    except RuntimeError:
        pass
    env = seen["env"]
    assert env["WAYLAND_DISPLAY"] == mod.PARENT_SOCKET and "DISPLAY" not in env
    assert env["HYPRLAND_NO_SD_VARS"] == "1" and env["LIBSEAT_BACKEND"] == "seatd"
    # and the main's start is exactly as before: the inherited environment
    monkeypatch.setattr(mod.Session, "_start_parent",
                        lambda self, t: (_ for _ in ()).throw(AssertionError("no parent")))
    try:
        mod.Session(headless=False, config_path=tmp_path / "n2.lua")._start_once(timeout=1)
    except RuntimeError:
        pass
    assert seen["env"] is None


def test_a_bot_with_the_model_off_never_unloads_the_shared_one(monkeypatch):
    from hivemind.brain import vlm

    def no_http(*a, **k):
        raise AssertionError("the model server was called")
    monkeypatch.setattr(vlm.urllib.request, "urlopen", no_http)
    assert vlm.VisionModel(enabled=False).unload() is False


def test_the_alt_steps_aside_before_the_main():
    probe = ("from hivemind.platform import memory as m; "
             "print(m.SAFE_TO_START_GB, m.STEP_ASIDE_GB)")

    def lines(role):
        env = {**os.environ, "HIVEMIND_ROLE": role, "PYTHONDONTWRITEBYTECODE": "1"}
        out = subprocess.run([sys.executable, "-c", probe], env=env,
                             capture_output=True, text=True, check=True).stdout
        return [float(x) for x in out.split()]
    main, alt = lines("main"), lines("alt")
    assert main == [6.0, 2.0]
    assert alt == [8.0, 4.0]


