"""Suite-wide setup, and a guard that stops the suite killing the machine.

WHY THIS FILE EXISTS, MEASURED TODAY

Running `pytest tests -q` while the owner was using the desktop froze the
machine and the run ended on exit 137 -- SIGKILL, the Linux OOM killer. That
is the third OOM event on this box in two days: twice it took the agent, once
it took the desktop with it. The suite is not entitled to do that. It is a
test suite; if there is not room for it, the correct behaviour is to decline
and say so, not to page the machine to death and take the user's game with it.

Two protections, and they are deliberately different in kind:

  * this file refuses to START a run when memory is already tight, which is
    advisory and can be overridden;
  * `scripts/run_tests.sh` runs pytest inside a systemd scope with a hard
    `MemoryMax` and swap denied, which is not advisory. Under cgroup v2 the
    kernel kills the test process at the limit instead of hunting the largest
    process on the system -- which is how a `pytest` run ends up killing
    Sober, the agent, or the desktop rather than itself.

The second one is the real fix. A guard written in the same process it is
meant to protect cannot save you from the allocation that actually kills you.

QT

Every GUI test module already sets QT_QPA_PLATFORM=offscreen, but each one does
it at import time, which only works because each is also the first thing that
imports PySide6 in a fresh worker. Setting it here removes the ordering
dependency: conftest is imported before any test module, so there is no path
where a real X/Wayland window gets opened by a test run.
"""
from __future__ import annotations

import os
import sys
import pathlib

import pytest

# Before PySide6 can be imported by anything. Not `setdefault`-with-a-comment:
# an inherited value of "wayland" from the desktop session is exactly the case
# this needs to override, and no test wants a real window.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
# Qt otherwise writes a cache into $HOME during runs; harmless but not ours.
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.platform import memory  # noqa: E402


# How much headroom the suite wants before it will start. This is NOT
# `memory.SAFE_TO_START_GB` (6.0), which is sized for launching the game plus a
# nested compositor. A pytest run is much smaller, so demanding the game's
# budget would refuse to run tests on a machine that can comfortably run them.
# 2.5 GB is the measured working set of a full run (OpenCV, NumPy, a handful of
# offscreen QApplications and ~20 MB of PNG fixtures) with room to spare.
SUITE_NEEDS_GB = 2.5

SKIP_GUARD = "HIVEMIND_TEST_ANYWAY"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "heavy: allocates enough that it is skipped when memory is tight")
    config.addinivalue_line(
        "markers",
        "game: needs the real game running; never selected by default")


def pytest_sessionstart(session: pytest.Session) -> None:
    """Decline to start a run that the machine cannot afford.

    Overridable with HIVEMIND_TEST_ANYWAY=1, because "I know, run it anyway"
    is a legitimate thing to want and a guard you cannot turn off gets
    deleted by the next person in a hurry.
    """
    if os.environ.get(SKIP_GUARD):
        return
    state = memory.read()
    if state.total_gb == 0.0:            # unreadable /proc; not our business
        return
    if state.available_gb >= SUITE_NEEDS_GB:
        return
    raise pytest.UsageError(
        f"not enough memory to run the test suite: {state.describe()}. "
        f"It needs about {SUITE_NEEDS_GB} GB and a run that gets OOM-killed "
        f"takes the desktop down with it. Use scripts/run_tests.sh, which "
        f"caps the run in a cgroup so it can only kill itself, or set "
        f"{SKIP_GUARD}=1 to override.")


@pytest.fixture(scope="session")
def qt_app():
    """One QApplication for the whole session.

    Qt permits exactly one per process and never frees a destroyed one's
    static state, so per-module fixtures that each call `QApplication([])`
    quietly rely on `instance()` returning the first. Naming it once makes
    that explicit and gives GUI tests a single place to change.
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# WHAT THE BOT KEEPS FOR LATER IS NOT THE SUITE'S TO WRITE. Three modules keep
# frames in var/ through a module-level folder, and one of them prunes it:
# act/quests._keep_unparsed deletes the oldest past UNPARSED_KEEP * 2 files.
# MEASURED 2026-09-29 21:04-21:06: a suite run from a tree whose var/quest_reads
# linked to the live one left eight synthetic frames there (moved out the same
# evening), next to the real close failures tests/unit/test_quests_close.py
# reads -- which that pruning could have deleted. Every test gets its own.
KEEP_FOLDERS = (("hivemind.act.quests", "UNPARSED_DIR"),
                ("hivemind.act.inventory", "KEEP_DIR"),
                ("hivemind.act.beemenu", "KEEP_DIR"),
                ("hivemind.act.badges", "KEEP_DIR"),
                ("hivemind.platform.lastserver", "RECORD"),
                ("hivemind.act.questscroll", "KEEP_DIR"))


@pytest.fixture(autouse=True)
def _keep_folders_are_the_tests_own(tmp_path, monkeypatch):
    import importlib
    for module, name in KEEP_FOLDERS:
        try:
            mod = importlib.import_module(module)
        except Exception:
            continue
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, tmp_path / "kept" / module.rsplit(".", 1)[-1])


# LINUX-ONLY MODULES, NOT COLLECTED ON WINDOWS (RL6, MEASURED 2026-10-21 on the
# owner's Windows PC): each imports something Windows does not have at module
# level -- pywayland (the Wayland capture/input layer), os.getuid (the Linux
# gameguard and the wlr session), or tests the Linux package. Windows has its
# own tests for the same jobs (test_win_*). Collected as before on Linux.
if os.name == "nt":
    collect_ignore = [
        "unit/test_bootstrap_capture.py",     # platform/wl/screencopy -> pywayland
        "unit/test_camera_input.py",          # platform/wl/vkeyboard -> pywayland
        "unit/test_capture_threading.py",     # platform/wl/screencopy -> pywayland
        "unit/test_screencopy_formats.py",    # platform/wl/screencopy -> pywayland
        "unit/test_gameguard.py",             # os.getuid at import (win/gameguard is separate)
        "unit/test_wlr_session.py",           # labwc / wlroots session, os.getuid
        "unit/test_linux_package.py",         # the Linux .deb/flatpak/nix package
    ]
