"""RL6i, the Windows installer: what can be proved on Linux.

The bundled-Tesseract lookup, the icon file, the selftest's verdict, and that
the installer script, the GUI, the workflow and the pinned wheels agree with
each other. The build itself only runs on Windows (installer/README.md).
"""
from __future__ import annotations

import importlib.util
import os
import re
import struct
from pathlib import Path

import yaml

from hivemind import datapaths, selftest

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
ISS = (ROOT / "installer/hivemind.iss").read_text()


def test_bundled_tesseract_goes_first_on_path_once(tmp_path):
    env = {"PATH": "C:/Windows"}
    assert datapaths.use_bundled_tesseract(tmp_path, env) is False
    assert env == {"PATH": "C:/Windows"}                    # dev kit, Linux: untouched

    folder = tmp_path / "tesseract"
    folder.mkdir()
    (folder / "tesseract.exe").write_bytes(b"MZ")
    assert datapaths.use_bundled_tesseract(tmp_path, env) is True
    assert env["PATH"] == f"{folder}{os.pathsep}C:/Windows"
    assert env["TESSDATA_PREFIX"] == str(folder / "tessdata")
    datapaths.use_bundled_tesseract(tmp_path, env)          # a child process, inheriting it
    assert env["PATH"].count(str(folder)) == 1


def test_icon_is_one_png_per_size():
    spec = importlib.util.spec_from_file_location("make_icon", ROOT / "installer/make_icon.py")
    make_icon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_icon)
    import cv2
    blob = make_icon.ico(cv2.imread(str(make_icon.SOURCE), cv2.IMREAD_UNCHANGED))
    reserved, kind, count = struct.unpack_from("<HHH", blob)
    assert (reserved, kind, count) == (0, 1, len(make_icon.SIZES))
    for i, size in enumerate(make_icon.SIZES):
        w, h, _, _, planes, bits, length, offset = struct.unpack_from("<BBBBHHII", blob, 6 + 16 * i)
        assert (w or 256, h or 256, planes, bits) == (size, size, 1, 32)
        assert blob[offset:offset + 8] == b"\x89PNG\r\n\x1a\n" and offset + length <= len(blob)


def test_selftest_passes_only_when_every_check_does():
    said = []
    assert selftest.run((("a", lambda: None), ("b", lambda: "fine")), said.append) == 0
    assert said[-1] == "all checks passed"

    def broken():
        raise SystemExit(2)                                  # a script's exit counts as a failure
    said = []
    assert selftest.run((("a", lambda: None), ("b", broken)), said.append) == 1
    assert any(line.startswith("FAIL  b: SystemExit") for line in said)


def test_version_is_pyprojects():
    assert re.fullmatch(r"\d+\.\d+\.\d+", selftest.version())     # Inno's VersionInfoVersion
    assert f'version = "{selftest.version()}"' in (ROOT / "pyproject.toml").read_text()


def test_installer_gui_and_workflow_agree():
    from hivemind.gui.app import APP_ID
    assert f'#define AppUserModel "{APP_ID}"' in ISS
    assert re.search(r"^AppId=\{\{[0-9A-F-]{36}\}$", ISS, re.M)
    assert "PrivilegesRequired=lowest" in ISS and "DefaultDirName={autopf}\\" in ISS
    # The first-run settings land where datapaths.config_dir() reads them on
    # Windows (platformdirs: %LOCALAPPDATA%\Hivemind), and the preset is real.
    assert 'DestDir: "{localappdata}\\Hivemind"; DestName: "settings.yaml"' in ISS
    assert (ROOT / "data/presets/safe-first-run.yaml").is_file()
    flow = yaml.safe_load((ROOT / ".github/workflows/windows-installer.yml").read_text())
    steps = flow["jobs"]["build"]["steps"]
    assert flow["jobs"]["build"]["runs-on"] == "windows-latest"
    assert any("installer/build.ps1" in s.get("run", "") for s in steps)
    assert any("--selftest" in s.get("run", "") for s in steps)
    assert any(s.get("with", {}).get("path") == "installer/build/Hivemind-Setup.exe" for s in steps)


def test_every_wheel_is_pinned_with_a_hash():
    lines = [ln for ln in (ROOT / "installer/requirements-windows.txt").read_text().splitlines()
             if ln.strip() and not ln.startswith("#")]
    assert lines
    for line in lines:
        assert re.fullmatch(r"[A-Za-z0-9_.-]+==[\w.]+ --hash=sha256:[0-9a-f]{64}", line), line


def test_the_windows_opencv_wheel_is_the_one_with_cv2_ml():
    """MEASURED 2026-10-21: OpenCV 5's opencv-python(-headless) wheels have no
    cv2/ml; fieldsense and the school classifier need it."""
    pins = [ln.split("==")[0] for ln in
            (ROOT / "installer/requirements-windows.txt").read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]
    opencv = [p for p in pins if p.startswith("opencv")]
    assert opencv == ["opencv-contrib-python-headless"], opencv


def test_the_selftest_fails_an_opencv_without_ml(monkeypatch):
    import cv2
    assert ("opencv ml", selftest._opencv_ml) in selftest.CHECKS
    monkeypatch.delattr(cv2, "ml", raising=False)
    said = []
    assert selftest.run((("opencv ml", selftest._opencv_ml),), said.append) == 1
    assert any(s.startswith("FAIL  opencv ml") for s in said), said


def test_the_shortcut_starts_the_gui_in_utf8_mode():
    """MEASURED 2026-10-22: without it the installed GUI reads data/ as
    cp1252 (bees.yaml raised UnicodeDecodeError)."""
    assert '#define LaunchArgs "-X utf8 -m hivemind.gui"' in ISS


def test_a_split_build_has_its_own_name():
    """2026-10-22: a split Hivemind-Setup.exe without its -3.bin asked for
    Disk 3; the one-file installer must never share the split one's name."""
    split = ISS.split("#ifdef Split", 1)[1].split("#endif", 1)[0]
    assert "OutputBaseFilename=Hivemind-Setup-PARTS" in split.split("#else")[0]
    assert "OutputBaseFilename=Hivemind-Setup\n" in split.split("#else")[1]


def test_the_ui_preview_is_its_own_demo_only_app():
    """The owner, 2026-10-22: a UI to look at, no features. --demo, its own
    name and AppId (it never upgrades or removes a real install), no old-kit copy."""
    pre = ISS.split("#ifdef Preview")
    assert '#define LaunchArgs "-X utf8 -m hivemind.gui --demo --loop"' in ISS
    assert '#define AppName "Hivemind UI Preview"' in ISS
    assert "OutputBaseFilename=Hivemind-UI-Preview" in ISS
    ids = [line for line in ISS.splitlines() if line.startswith("AppId=")]
    assert len(ids) == 2 and ids[0] != ids[1]
    assert any("OldKit := ''" in part for part in pre)


def test_the_preview_uninstaller_removes_its_own_demo_folder():
    r"""datapaths.use_demo_dirs keeps a demo's settings in %LOCALAPPDATA%\Hivemind
    Demo; uninstalling the preview takes that throwaway folder with it."""
    block = ISS[ISS.index("[UninstallDelete]"):ISS.index("[Code]")]
    preview = block[block.index("#ifdef Preview"):block.index("#endif")]
    assert r'{localappdata}\Hivemind Demo' in preview
