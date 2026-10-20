"""Where the data files live, resolved from the package rather than the cwd.

Six modules used to spell their defaults as `Path("data/world/...")`, which is
relative to whatever directory the process happened to start in. That is not a
theoretical problem:

  * running the identical test suite from /tmp gave 9 failures and 19 skips
    instead of 414 passes
  * `hivemind.gui --demo` launched from the home directory showed an EMPTY
    Fields tab, because load_layout swallows the OSError and every subsequent
    FieldStatus event is dropped for an unknown field -- a silent wrong answer,
    which is the worst kind
  * the .desktop entry happens to set Path=, but its [Desktop Action Demo]
    entry does not, and any shell launch from elsewhere hits it

The project is ~80% data by design, so "find the data" is load-bearing enough
to have one answer in one place.

An environment override exists for the case where the data directory is
genuinely somewhere else (a packaged install, a test fixture tree). It is read
once at import; nothing here caches a stat, so a missing file still surfaces as
a normal OSError at the point of use.
"""
from __future__ import annotations

import os
from pathlib import Path

# src/hivemind/datapaths.py -> parents[2] is the project root that holds data/
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]

DATA_ROOT = Path(os.environ.get("HIVEMIND_DATA", _PACKAGE_ROOT / "data"))

# Runtime state the bot ACCUMULATES, as opposed to data it ships with: the
# harvest log the degradation regression reads, and anything else that grows
# while it plays. Separate from DATA_ROOT because one is read-only content and
# the other is written during a session.
VAR_ROOT = Path(os.environ.get("HIVEMIND_VAR", _PACKAGE_ROOT / "var"))


def data(*parts: str) -> Path:
    """Resolve a path under the data root: data('world', 'fields.yaml')."""
    return DATA_ROOT.joinpath(*parts)


def var(*parts: str) -> Path:
    """Resolve a path under the runtime-state root: var('harvests.jsonl')."""
    return VAR_ROOT.joinpath(*parts)


# WHERE THE REST LIVES (RL6 phase 2, the `Paths` seam of platform/api).
# Here and not in platform/, because world/ and telemetry/ may not import
# platform (tests/unit/test_layering.py) and both need these. On Linux each is
# exactly the path that was spelt out at its call sites before; platformdirs
# is imported only on Windows, so the system python (telegram_alerts) needs
# nothing new.
WINDOWS = os.name == "nt"


def config_dir() -> Path:
    """settings.yaml, server.yaml, telegram.env: ~/.config/hivemind
    (HIVEMIND_CONFIG overrides it: a demo's own folder, use_demo_dirs)."""
    if os.environ.get("HIVEMIND_CONFIG"):
        return Path(os.environ["HIVEMIND_CONFIG"])
    if WINDOWS:
        import platformdirs
        return Path(platformdirs.user_config_dir("Hivemind", appauthor=False))
    return Path.home() / ".config/hivemind"


def runtime_dir() -> Path:
    """Short-lived files (the live-view JPEG, the IPC socket): $XDG_RUNTIME_DIR."""
    if WINDOWS:
        import platformdirs
        return Path(platformdirs.user_runtime_dir("Hivemind", appauthor=False))
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))


def session_logs_dir() -> Path:
    """Where the client keeps one log per session (platform/lastserver).
    Windows: unverified until phase 4 (docs/pending/windows-port.md)."""
    if WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Roblox" / "logs"
    return Path.home() / ".var/app/org.vinegarhq.Sober/data/sober/sober_logs"


def client_log() -> Path | None:
    """The client log to tail now. Linux: var/sober.log, Sober's stdout as
    act/bootstrap keeps it. Windows: the newest Player log, None before any."""
    if WINDOWS:
        logs = sorted(session_logs_dir().glob("*_Player_*_last.log"),
                      key=lambda p: p.stat().st_mtime)
        return logs[-1] if logs else None
    return var("sober.log")


def use_bundled_tesseract(root: Path = _PACKAGE_ROOT, environ=os.environ) -> bool:
    """THE INSTALLED APP'S TESSERACT (RL6i). The Windows installer puts the UB
    Mannheim build in <install>/tesseract, which is not on PATH. Prepending it
    here lets every caller that runs a bare `tesseract` (14 modules) find it
    unchanged, in this process and in every child it starts (the watchdog, the
    farm), and points TESSDATA_PREFIX at its own afr data. Called once from
    hivemind/__init__ on Windows; does nothing without the bundled copy (the
    dev .bat kit, Linux). True when it is in use."""
    folder = Path(root) / "tesseract"
    if not (folder / "tesseract.exe").is_file():
        return False
    path = environ.get("PATH", "")
    if not path.startswith(str(folder) + os.pathsep):   # a child inherits it already
        environ["PATH"] = str(folder) + os.pathsep + path
    environ["TESSDATA_PREFIX"] = str(folder / "tessdata")
    return True


def use_demo_dirs(environ=os.environ) -> Path:
    """A DEMO KEEPS AWAY FROM THE REAL APP'S FILES (the Windows Claude's check
    of the UI preview, 2026-10-22: it showed the owner's real server name and
    share link from settings, and its switches would change the real bot).
    Settings and var/ go to a separate demo folder, so a replay never reads
    or writes the user's settings.yaml, secrets.env, telegram.env or var/.
    Called by gui/__main__ for --demo / --replay, before settings load."""
    global VAR_ROOT
    if WINDOWS:
        import platformdirs
        root = Path(platformdirs.user_data_dir("Hivemind Demo", appauthor=False))
    else:
        root = Path.home() / ".local/share/hivemind-demo"
    environ["HIVEMIND_DEMO"] = "1"                  # read by pages that say "Press Start"
    environ["HIVEMIND_CONFIG"] = str(root / "config")
    environ["HIVEMIND_VAR"] = str(root / "var")
    VAR_ROOT = root / "var"
    return root
