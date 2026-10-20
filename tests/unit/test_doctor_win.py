"""`hivemind doctor` on Windows (cli/doctor_win): every check with the PC faked.

No registry, screen, disk or memory is read here: each seam is replaced, so
this runs the same on Linux and Windows. What matters is that each problem a
beginner can have is a FAIL or WARN that says what to do, and that nothing a
Windows PC lacks on purpose (Wayland, Sober, a vision model) is a problem.
"""
from pathlib import Path

import pytest

from hivemind.cli import doctor, doctor_win as dw


@pytest.fixture
def healthy(monkeypatch, tmp_path):
    """A PC that has everything: Windows 11, Roblox, a 1080p screen at 100%,
    the bundled Tesseract with afr and tsv, every package, memory and disk."""
    tess = tmp_path / "tesseract"
    (tess / "tessdata" / "configs").mkdir(parents=True)
    (tess / "tesseract.exe").write_bytes(b"")
    (tess / "tessdata" / "afr.traineddata").write_bytes(b"")
    (tess / "tessdata" / "configs" / "tsv").write_text("", encoding="utf-8")
    monkeypatch.setenv("TESSDATA_PREFIX", str(tess / "tessdata"))
    monkeypatch.setattr(dw, "BUNDLED", tess / "tesseract.exe")
    monkeypatch.setattr(dw, "windows_version", lambda: (10, 22631))
    monkeypatch.setattr(dw, "monitors", lambda: [dw.Monitor(1920, 1080, 100, True)])
    monkeypatch.setattr(dw, "roblox_install",
                        lambda: (None, Path("C:/R/Versions/version-1/RobloxPlayerBeta.exe"), False))
    monkeypatch.setattr(dw, "find_spec", lambda name: object())
    monkeypatch.setattr(dw, "load_module", lambda name: object())
    monkeypatch.setattr(dw, "which", lambda name: None)
    monkeypatch.setattr(dw, "read_memory", lambda: (6.0, 16.0, 2.0))
    monkeypatch.setattr(dw, "free_gb", lambda path: 150.0)
    monkeypatch.setattr(dw, "panic_key", lambda: "F12")
    return tess


def missing(name):
    raise ImportError(f"No module named {name!r}")


def by_name(checks):
    return {c.name: c for c in checks}


def test_a_healthy_pc_passes_everything(healthy):
    checks = dw.environment() + dw.safety()
    assert [c for c in checks if c.status != doctor.OK] == []
    names = by_name(checks)
    assert "Windows 11" in names["Windows 10 (1903) or newer"].detail
    assert "RobloxPlayerBeta.exe" in names["Roblox"].detail


def test_no_vision_model_is_fine_on_windows(healthy):
    """Optional: never a warning, whether or not it is there."""
    assert dw.vision_model_check().status == doctor.OK
    assert "fine" in dw.vision_model_check().detail


def test_every_problem_says_how_to_fix_it(healthy, monkeypatch, tmp_path):
    """Everything missing at once: each FAIL and WARN carries a fix."""
    monkeypatch.setattr(dw, "windows_version", lambda: (10, 17763))   # 1809
    monkeypatch.setattr(dw, "monitors", lambda: [dw.Monitor(1366, 768, 125, True)])
    monkeypatch.setattr(dw, "roblox_install", lambda: (None, None, False))
    monkeypatch.setattr(dw, "BUNDLED", tmp_path / "none" / "tesseract.exe")
    monkeypatch.setattr(dw, "find_spec", lambda name: None)
    monkeypatch.setattr(dw, "load_module", missing)
    monkeypatch.setattr(dw, "read_memory", lambda: (0.7, 8.0, 2.0))
    monkeypatch.setattr(dw, "free_gb", lambda path: 5.0)
    monkeypatch.setattr(dw, "panic_key", lambda: "Banana")
    checks = dw.environment() + dw.safety()
    problems = [c for c in checks if c.status != doctor.OK]
    names = {c.name for c in problems}
    assert {"Windows 10 (1903) or newer", "Roblox", "screen 1920x1080 or bigger",
            "Tesseract (reads text)", "Python: OpenCV", "screen capture", "free memory",
            "free disk space", "panic key (Banana)"} <= names
    for c in problems:
        assert c.fix, f"{c.name} has no fix"


def test_old_windows(healthy, monkeypatch):
    monkeypatch.setattr(dw, "windows_version", lambda: (6, 9600))     # 8.1
    assert dw.version_check().status == doctor.FAIL
    monkeypatch.setattr(dw, "windows_version", lambda: (10, 17763))   # 1809: copies the screen
    c = dw.version_check()
    assert c.status == doctor.WARN and "Windows Update" in c.fix
    monkeypatch.setattr(dw, "windows_version", lambda: (10, 18362))   # 1903 exactly
    assert dw.version_check().status == doctor.OK


def test_roblox_from_the_registry_or_the_folder_or_neither(healthy, monkeypatch):
    monkeypatch.setattr(dw, "roblox_install",
                        lambda: ('"C:\\R\\RobloxPlayerBeta.exe" %1', None, False))
    assert dw.roblox_check().status == doctor.OK
    monkeypatch.setattr(dw, "roblox_install", lambda: (None, None, True))
    c = dw.roblox_check()
    assert c.status == doctor.FAIL and "Microsoft Store" in c.detail
    assert "roblox.com" in c.fix


def test_the_screen(healthy, monkeypatch):
    # a 1440p main screen and a small second one: fine
    monkeypatch.setattr(dw, "monitors", lambda: [dw.Monitor(2560, 1440, 100, True),
                                                 dw.Monitor(1280, 1024, 100)])
    assert [c.status for c in dw.screen_checks()] == [doctor.OK, doctor.OK]
    # big enough but scaled: a warning with the setting to change
    monkeypatch.setattr(dw, "monitors", lambda: [dw.Monitor(1920, 1080, 125, True)])
    size, scale = dw.screen_checks()
    assert size.status == doctor.OK
    assert scale.status == doctor.WARN and "Scale: 100%" in scale.fix
    # too small: the bot cannot read the game
    monkeypatch.setattr(dw, "monitors", lambda: [dw.Monitor(1600, 900, 100, True)])
    [small] = dw.screen_checks()
    assert small.status == doctor.FAIL and "1600x900" in small.detail
    # unreadable: said, not crashed (below)


def test_the_screen_roblox_opens_on_is_the_main_one(healthy, monkeypatch):
    """Roblox is sized on the monitor it is on, and opens on the main one:
    a big SECOND screen is a warning that says to move Roblox there."""
    monkeypatch.setattr(dw, "monitors", lambda: [dw.Monitor(1600, 900, 100, True),
                                                 dw.Monitor(1920, 1080, 100)])
    size, scale = dw.screen_checks()
    assert size.status == doctor.WARN and "main screen" in size.detail
    assert "1920x1080 screen" in size.fix and "main display" in size.fix
    assert scale.status == doctor.OK
    # a scaled main screen is not excused by a second screen at 100%
    monkeypatch.setattr(dw, "monitors", lambda: [dw.Monitor(1920, 1080, 125, True),
                                                 dw.Monitor(1920, 1080, 100)])
    size, scale = dw.screen_checks()
    assert size.status == doctor.OK
    assert scale.status == doctor.WARN and "main screen is at 125%" in scale.detail


def test_the_screen_unreadable(healthy, monkeypatch):
    monkeypatch.setattr(dw, "monitors", lambda: 1 / 0)
    assert dw.screen_checks()[0].status == doctor.WARN


def test_tesseract_files_are_looked_at_never_run(healthy, monkeypatch, tmp_path):
    # a hand-installed copy on PATH, its tessdata beside it, afr missing
    hand = tmp_path / "Tesseract-OCR"
    (hand / "tessdata").mkdir(parents=True)
    monkeypatch.setattr(dw, "BUNDLED", tmp_path / "none" / "tesseract.exe")
    monkeypatch.setattr(dw, "which", lambda name: str(hand / "tesseract.exe"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    found = by_name(dw.tesseract_checks())
    assert found["Tesseract (reads text)"].status == doctor.OK
    assert found["Tesseract's afr language"].status == doctor.FAIL
    assert "afr.traineddata" in found["Tesseract's afr language"].fix
    assert found["Tesseract's tsv config"].status == doctor.WARN
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ran a program"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("ran a program"))
    dw.environment()


def test_capture_falls_back_to_the_screen_copy(healthy, monkeypatch):
    monkeypatch.setattr(dw, "find_spec", lambda name: None if name == "windows_capture" else 1)
    monkeypatch.setattr(dw, "load_module",
                        lambda name: missing(name) if name == "windows_capture" else 1)
    [cap] = [c for c in dw.module_checks() if c.name == "screen capture"]
    assert cap.status == doctor.WARN


def test_a_package_that_will_not_load_is_a_problem(healthy, monkeypatch):
    """Windows' "DLL load failed" (a missing Visual C++ runtime under cv2):
    installed, but not working -- a FAIL with the runtime as the fix."""
    def load(name):
        if name == "cv2":
            raise ImportError("DLL load failed while importing cv2: The specified "
                              "module could not be found.")
        return object()
    monkeypatch.setattr(dw, "load_module", load)
    found = by_name(dw.module_checks())
    cv2 = found["Python: OpenCV"]
    assert cv2.status == doctor.FAIL and "will not load" in cv2.detail
    assert "Visual C++ Redistributable" in cv2.fix
    assert found["Python: numpy"].status == doctor.OK
    # dxcam is never imported (its import opens DirectX)
    seen = []
    monkeypatch.setattr(dw, "load_module", lambda name: seen.append(name) or object())
    dw.module_checks()
    assert "dxcam" not in seen and "cv2" in seen


def test_doctor_runs_the_windows_checks_on_windows_only(healthy, monkeypatch):
    env, safe, calib, state, game = doctor.sections(windows=True)
    assert (env, safe) == (dw.environment, dw.safety)
    assert doctor.sections(windows=False)[:2] == (doctor.environment, doctor.safety)
    monkeypatch.setattr(doctor, "sections", lambda: (dw.environment, dw.safety))
    names = {c.name for c in doctor.run()}
    assert "Roblox" in names
    assert not {"a Wayland desktop session", "Hyprland 0.56+", "Flatpak"} & names
