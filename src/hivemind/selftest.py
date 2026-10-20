"""`python -m hivemind.gui --selftest` (or `--version`): proof that an installed
copy imports everything it needs, without starting the bot or a game (RL6i).

The Windows installer's CI build runs this against the built app folder before
packing it, so a missing wheel, DLL, data file or the bundled Tesseract fails
the build instead of a tester's first start. One line per check, exit code 0
only when every check passed.
"""
from __future__ import annotations

import importlib
import os
import runpy
import subprocess
import sys
import tomllib

from . import datapaths

ROOT = datapaths._PACKAGE_ROOT
WINDOWS = os.name == "nt"


def version() -> str:
    """The version in pyproject.toml, the one place it is written (the
    installer is stamped from the same file)."""
    try:
        with open(ROOT / "pyproject.toml", "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


PACKAGES = ("cv2", "numpy", "yaml", "platformdirs", "PySide6.QtCore", "PySide6.QtGui",
            "PySide6.QtSvg", "PySide6.QtWidgets")
WINDOWS_PACKAGES = ("psutil", "windows_capture", "dxcam")


def _imports() -> None:
    for name in PACKAGES + (WINDOWS_PACKAGES if WINDOWS else ()):
        importlib.import_module(name)


def _opencv_ml() -> str:
    """cv2.ml is there (vision/fieldsense, brain/school). OpenCV 5's plain pip
    wheels lack it (installer/requirements-windows.txt), and both callers stay
    silent without it, so only this check would say."""
    import cv2
    cv2.ml.SVM_create()
    return f"opencv {cv2.__version__}"


def _qt() -> str:
    """The Qt platform plugin loads (a missing qwindows.dll only shows here)."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["hivemind-selftest"])
    return app.platformName()


def _app_modules() -> None:
    for name in ("hivemind.gui.app", "hivemind.gui.launcher", "hivemind.platform.current",
                 "hivemind.watchdog"):
        importlib.import_module(name)


def _farm() -> None:
    """run_farm's top level: every import and module-level table it builds,
    without main()."""
    runpy.run_path(str(ROOT / "scripts" / "run_farm.py"), run_name="hivemind_selftest")


def _data() -> None:
    for part in (("icon.png",), ("brand", "hivemind_logo.png"), ("world",), ("templates",)):
        if not datapaths.data(*part).exists():
            raise FileNotFoundError(datapaths.data(*part))


def _tesseract() -> str:
    out = subprocess.run(["tesseract", "--list-langs"], capture_output=True,
                         text=True, timeout=30)
    langs = (out.stdout + out.stderr).split()
    if "afr" not in langs:
        raise RuntimeError(f"no afr language (got {langs[-5:]})")
    return "afr found"


CHECKS = (("python packages", _imports), ("opencv ml", _opencv_ml), ("qt platform", _qt),
          ("data files", _data),
          ("hivemind modules", _app_modules), ("run_farm imports", _farm),
          ("tesseract", _tesseract))


def run(checks=CHECKS, say=print) -> int:
    say(f"Hivemind {version()} selftest, python {sys.version.split()[0]}, {sys.executable}")
    failed = 0
    for name, check in checks:
        try:
            note = check()
            say(f"ok    {name}" + (f": {note}" if note else ""))
        except BaseException as exc:                           # SystemExit from a script too
            failed += 1
            say(f"FAIL  {name}: {type(exc).__name__}: {exc}")
    say("all checks passed" if not failed else f"{failed} check(s) failed")
    return 1 if failed else 0
