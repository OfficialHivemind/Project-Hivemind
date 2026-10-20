"""`hivemind doctor` on Windows: can this PC run the bot? (RL6, the release gate)

The Linux checks (cli/doctor.environment) ask for Wayland, Hyprland, Sober and
evdev, none of which a Windows PC has, so on Windows these run instead. Every
check only LOOKS: it reads the registry, folders, the screen's mode and the
memory figures. Nothing is started -- not Roblox, not Tesseract, not a game
window -- and nothing is changed. Each problem says what is wrong and what to
do about it in plain words, for a beginner.

What the bot needs on Windows, and where each need comes from:

    Windows 10 1903+   window capture (Windows Graphics Capture) needs 1903;
                       older Windows falls back to copying the screen
                       (platform/win/capture, docs/pending/windows-port.md)
    Roblox             from roblox.com: the roblox:// handler in the registry
                       or %LOCALAPPDATA%\\Roblox\\Versions (platform/win/session)
    Tesseract + afr    every text read (vision/beemenu TESSERACT, LANGUAGE);
                       the installer bundles it (datapaths.use_bundled_tesseract)
    1920x1080, 100%    every screen box is measured on a 1920x1080 client
                       (platform/win/session, THE WINDOW)
    2 GB free memory   platform/win/memory.WIN_SAFE_TO_START_GB
    disk               telemetry/storage.LOW_DISK_GB

The seams (windows_version, monitors, roblox_install, BUNDLED, find_spec,
load_module, which, read_memory, free_gb, panic_key) are module names so the
tests stand in for the PC.
"""
from __future__ import annotations

import ctypes
import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .doctor import FAIL, OK, WARN, Check, ai_mode_check
from ..datapaths import VAR_ROOT, _PACKAGE_ROOT

# Windows 10 1903 is build 18362 [verified: learn.microsoft.com Windows 10
# release information]. WGC needs 1903+ (docs/pending/windows-port.md, risks).
WGC_BUILD = 18362
SCREEN = (1920, 1080)          # platform/win/session WinSession.width/height
REINSTALL = ("reinstall Hivemind (the installer brings it). Running from a copy of the "
             "code instead: .venv\\Scripts\\pip install -r installer\\requirements-windows.txt")
DISPLAY = "Windows Settings > System > Display"

BUNDLED = _PACKAGE_ROOT / "tesseract" / "tesseract.exe"   # the installer's copy
find_spec = importlib.util.find_spec
load_module = importlib.import_module
which = shutil.which


@dataclass
class Monitor:
    width: int                 # physical pixels
    height: int
    scale: int                 # Windows' "Scale" in percent (100, 125, 150...)
    primary: bool = False


def windows_version() -> tuple[int, int]:
    """(major, build): (10, 19045) for Windows 10 22H2, (10, 22631) for
    Windows 11 23H2 -- Windows 11 still says 10. These are the values Windows
    reports to THIS process [docs.python.org, sys.getwindowsversion]; they are
    the real ones because python.exe and pythonw.exe declare Windows 10 support
    in their manifest. platform_version is not used: it is kernel32.dll's file
    version, which lags (MEASURED 2026-10-26 on the Windows test PC: build
    26200, platform_version said 26100)."""
    v = sys.getwindowsversion()                       # type: ignore[attr-defined]
    return v.major, v.build


def monitors() -> list[Monitor]:
    """Every monitor, in physical pixels, with its scale. Read with the THREAD
    briefly per-monitor DPI aware (SetThreadDpiAwarenessContext, Windows 10
    1607+ [verified]) and put back as it was, so the GUI's own DPI mode is not
    touched. Before 1607 the sizes may be scaled ones [assumed: DPI
    virtualisation], and the scale reads 100."""
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)       # type: ignore[attr-defined]
    set_ctx = getattr(user32, "SetThreadDpiAwarenessContext", None)
    if set_ctx is not None:
        set_ctx.restype, set_ctx.argtypes = ctypes.c_void_p, [ctypes.c_void_p]
    try:
        get_dpi = ctypes.WinDLL("shcore").GetDpiForMonitor     # type: ignore[attr-defined]
        get_dpi.restype = ctypes.c_long
        get_dpi.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint),
                            ctypes.POINTER(ctypes.c_uint)]
    except (OSError, AttributeError):                 # shcore: Windows 8.1+
        get_dpi = None

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    found: list[Monitor] = []

    def one(hmon, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(info)):
            return True
        r = info.rcMonitor
        scale = 100
        if get_dpi is not None:
            x, y = ctypes.c_uint(), ctypes.c_uint()
            if get_dpi(ctypes.c_void_p(hmon), 0, ctypes.byref(x), ctypes.byref(y)) == 0:
                scale = round(x.value * 100 / 96)       # MDT_EFFECTIVE_DPI; 96 = 100%
        found.append(Monitor(r.right - r.left, r.bottom - r.top, scale,
                             bool(info.dwFlags & 1)))   # MONITORINFOF_PRIMARY
        return True

    proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,  # type: ignore[attr-defined]
                              ctypes.c_void_p, ctypes.c_void_p)(one)
    old = set_ctx(ctypes.c_void_p(-4)) if set_ctx is not None else None   # PER_MONITOR_AWARE_V2
    try:
        user32.EnumDisplayMonitors(None, None, proc, None)
    finally:
        if old:
            set_ctx(ctypes.c_void_p(old))
    return found


def roblox_install() -> tuple[str | None, Path | None, bool]:
    """(the roblox:// handler's command, the newest RobloxPlayerBeta.exe, is
    the Microsoft Store's Roblox there). The first two are exactly what
    platform/win/session launches with; the Store's app keeps its files under
    %LOCALAPPDATA%\\Packages\\ROBLOXCORPORATION.ROBLOX_* [assumed]."""
    from ..platform.win.session import newest_player, protocol_command
    local = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    store = any(local.joinpath("Packages").glob("ROBLOXCORPORATION.ROBLOX*"))
    return protocol_command(), newest_player(), store


def read_memory() -> tuple[float, float, float]:
    """(available GB, total GB, GB the bot wants free to start); the first
    two are 0 when psutil cannot say."""
    from ..platform.win.memory import WIN_SAFE_TO_START_GB, read
    m = read()
    return m.available_gb, m.total_gb, WIN_SAFE_TO_START_GB


def panic_key() -> str:
    from ..world.settings import Settings
    return str(Settings().get("safety.panic_key", "F12"))


def free_gb(path: Path) -> float:
    from ..telemetry.storage import free_gb as free
    return free(path)


# ---- the checks ----------------------------------------------------------------
def version_check() -> Check:
    try:
        major, build = windows_version()
    except Exception as exc:                           # noqa: BLE001 - say it, don't crash
        return Check("environment", "Windows 10 (1903) or newer", WARN,
                     f"could not read the Windows version ({exc})")
    name = "Windows 11" if build >= 22000 else f"Windows {major}"
    if major < 10:
        return Check("environment", "Windows 10 (1903) or newer", FAIL,
                     f"this is {name} (build {build})",
                     "Hivemind needs Windows 10 or 11. Upgrade Windows first.")
    if build < WGC_BUILD:
        return Check("environment", "Windows 10 (1903) or newer", WARN,
                     f"build {build} is older than 1903: the bot can only copy the whole "
                     "screen, so any window over Roblox gets read as the game",
                     "Windows Settings > Update & Security > Windows Update: install the "
                     "updates, then check again")
    return Check("environment", "Windows 10 (1903) or newer", OK, f"{name}, build {build}")


def roblox_check() -> Check:
    try:
        handler, player, store = roblox_install()
    except Exception as exc:                           # noqa: BLE001
        return Check("environment", "Roblox", WARN, f"could not look for Roblox ({exc})")
    if handler or player:
        return Check("environment", "Roblox", OK,
                     str(player) if player else f"opens with: {handler}")
    detail = ("only the Microsoft Store's Roblox is installed, and Hivemind cannot "
              "start that one" if store else "not installed")
    return Check("environment", "Roblox", FAIL, detail,
                 "install Roblox from roblox.com/download (not the Microsoft Store), "
                 "open it once and log in, then check again", key="roblox")


def tesseract_checks() -> list[Check]:
    """Tesseract and its afr language: FILES only, it is never run here."""
    exe = str(BUNDLED) if BUNDLED.is_file() else which("tesseract")
    if not exe:
        return [Check("environment", "Tesseract (reads text)", FAIL, "not found",
                      "reinstall Hivemind (the installer brings Tesseract). Running from "
                      "a copy of the code instead: install Tesseract from UB Mannheim "
                      "(github.com/UB-Mannheim/tesseract) and tick 'add to PATH'",
                      key="tesseract")]
    checks = [Check("environment", "Tesseract (reads text)", OK, exe)]
    # The bundled copy sets TESSDATA_PREFIX to its own folder (datapaths);
    # a hand-installed one keeps tessdata beside tesseract.exe.
    tessdata = Path(os.environ.get("TESSDATA_PREFIX") or Path(exe).parent / "tessdata")
    afr = tessdata / "afr.traineddata"
    checks.append(Check("environment", "Tesseract's afr language",
                        OK if afr.is_file() else FAIL,
                        str(afr) if afr.is_file() else f"missing: {afr}",
                        "" if afr.is_file() else
                        "reinstall Hivemind. Running from a copy of the code instead: "
                        "download afr.traineddata from github.com/tesseract-ocr/tessdata "
                        f"into {tessdata}", key="afr"))
    # vision/amulet asks tesseract for `tsv` output, a config file in tessdata
    tsv = tessdata / "configs" / "tsv"
    if not tsv.is_file():
        checks.append(Check("environment", "Tesseract's tsv config", WARN, f"missing: {tsv}",
                            "reinstall Hivemind (amulet reading needs it; everything "
                            "else works without)"))
    return checks


def _screen(m: Monitor) -> str:
    return "your main screen" if m.primary else f"your {m.width}x{m.height} screen"


def screen_checks() -> list[Check]:
    """A screen of at least 1920x1080 for Roblox, at 100% scaling -- on the
    screen Roblox is on. The bot sizes Roblox on the monitor its window is on
    (platform/win/session, _user32.monitor_rect), and a new window opens on
    the main screen [assumed: Windows' default; Roblox may remember where it
    was moved]. So the MAIN screen is the one that counts: a big second
    screen helps only when Roblox is moved onto it, and the check says so."""
    try:
        found = monitors()
    except Exception as exc:                           # noqa: BLE001
        return [Check("environment", "screen 1920x1080 or bigger", WARN,
                      f"could not read the screen ({exc})")]
    if not found:
        return [Check("environment", "screen 1920x1080 or bigger", WARN, "no monitor found")]
    want_w, want_h = SCREEN
    big = [m for m in found if m.width >= want_w and m.height >= want_h]
    main = next((m for m in found if m.primary), found[0])
    said = ", ".join(f"{m.width}x{m.height} at {m.scale}%" + (" (main)" if m.primary else "")
                     for m in found)
    if not big:
        return [Check("environment", "screen 1920x1080 or bigger", FAIL, said,
                      f"Hivemind reads the game at 1920x1080. {DISPLAY} > Display "
                      "resolution: 1920 x 1080 or more. A screen that cannot go that "
                      "high cannot run the bot yet.", key="screen")]
    if main in big:
        where = main
        checks = [Check("environment", "screen 1920x1080 or bigger", OK, said)]
    else:
        where = big[0]
        checks = [Check("environment", "screen 1920x1080 or bigger", WARN,
                        f"{said}: Roblox opens on your main screen, which is too small "
                        "for it", f"drag the Roblox window onto {_screen(where)} before "
                        f"you press Start, or make that screen the main one ({DISPLAY}: "
                        "click it, then 'Make this my main display')")]
    # THE SCALE. The bot is DPI aware, so it sizes Roblox in real pixels at
    # any scale, but every box was measured at 100% and Roblox may draw its
    # menus bigger at 125%+ [assumed]; windows-port.md's test steps call 100%
    # the safest. So a warning, not a stop -- for the screen Roblox is on.
    if where.scale != 100:
        checks.append(Check("environment", "display scale 100%", WARN,
                            f"{_screen(where)} is at {where.scale}%",
                            f"{DISPLAY} > click {_screen(where)} > Scale: 100% (text on "
                            "the desktop gets smaller; the game reads best)"))
    else:
        checks.append(Check("environment", "display scale 100%", OK,
                            f"{_screen(where)} is at 100%"))
    return checks


def memory_check() -> Check:
    try:
        available, total, need = read_memory()
    except Exception as exc:                           # noqa: BLE001
        return Check("environment", "free memory", WARN, f"could not read it ({exc})")
    if total == 0.0:
        return Check("environment", "free memory", WARN, "could not read the memory figures")
    said = f"{available:.1f} GB free of {total:.0f} GB"
    if available < need:
        return Check("environment", "free memory", WARN, said,
                     f"the bot wants {need:.0f} GB free when Start is pressed: close big "
                     "programs first (a browser with many tabs, another game)")
    return Check("environment", "free memory", OK, said)


def disk_check() -> Check:
    from ..telemetry.storage import LOW_DISK_GB
    try:
        free = free_gb(VAR_ROOT)
    except Exception as exc:                           # noqa: BLE001
        return Check("environment", "free disk space", WARN, f"could not read it ({exc})")
    said = f"{free:.0f} GB free"
    if free < LOW_DISK_GB:
        return Check("environment", "free disk space", WARN, said,
                     f"under {LOW_DISK_GB:.0f} GB free the bot stops saving the pictures "
                     "it keeps for fixing problems. Free some space (Windows Settings > "
                     "System > Storage) if you can.")
    return Check("environment", "free disk space", OK, said)


# selftest.PACKAGES + WINDOWS_PACKAGES, by what each gives the player
MODULES = (("cv2", "Python: OpenCV"), ("numpy", "Python: numpy"),
           ("yaml", "Python: PyYAML"), ("platformdirs", "Python: platformdirs"),
           ("PySide6", "Python: PySide6 (the window)"), ("psutil", "Python: psutil"))
VCREDIST = ("install the Microsoft Visual C++ Redistributable (x64) from Microsoft's "
            "website (search 'latest supported Visual C++ Redistributable'), restart "
            "the PC, then check again. If that does not help: ")


def _load(name: str, label: str, fix: str, key: str) -> Check:
    """IMPORTED, as the Linux doctor does (doctor._module): a package that is
    there but cannot load -- Windows' "DLL load failed", most often a missing
    Visual C++ runtime under cv2 or numpy -- is the likeliest beginner
    failure, and find_spec alone would call it fine. Importing these runs
    no game, window or capture: they only load."""
    try:
        load_module(name)
    except ImportError as exc:
        if find_spec(name) is None:
            return Check("environment", label, FAIL, "not installed", fix, key=key)
        return Check("environment", label, FAIL,
                     f"installed but will not load ({str(exc)[:160]})", VCREDIST + fix, key=key)
    except Exception as exc:                           # noqa: BLE001 - broken, not missing
        return Check("environment", label, FAIL,
                     f"installed but will not load ({str(exc)[:160]})", fix, key=key)
    return Check("environment", label, OK)


def module_checks() -> list[Check]:
    checks = [_load(name, label, REINSTALL, name) for name, label in MODULES]
    wgc = _load("windows_capture", "screen capture", REINSTALL, "capture")
    if wgc.status == OK:
        checks.append(Check("environment", "screen capture", OK, "window capture"))
    # dxcam is only LOOKED for: importing it opens DirectX (its DXFactory)
    elif find_spec("dxcam") is not None:
        checks.append(Check("environment", "screen capture", WARN,
                            "only the whole-screen copy: a window over Roblox gets read "
                            "as the game" + (f" (window capture is {wgc.detail})"
                                             if wgc.detail != "not installed" else ""),
                            wgc.fix if wgc.detail != "not installed" else REINSTALL))
    else:
        checks.append(wgc)
    return checks


def vision_model_check() -> Check:
    """The local vision model is optional on Windows (platform/win/memory: no
    vision model there yet; windows-port.md: "ollama if the vision model is
    wanted"): most text is read with Tesseract. Never a warning."""
    found = which("ollama")
    return Check("environment", "local vision model (optional)", OK,
                 f"found: {found}" if found else
                 "not installed: fine, Tesseract reads the text")


def environment() -> list[Check]:
    py = sys.version_info[:2]
    checks = [Check("environment", "Python 3.12 or newer", OK if py >= (3, 12) else FAIL,
                    f"this is {py[0]}.{py[1]}",
                    "" if py >= (3, 12) else REINSTALL)]
    checks.append(version_check())
    checks.append(roblox_check())
    checks.extend(screen_checks())
    checks.extend(tesseract_checks())
    checks.extend(module_checks())
    checks.append(memory_check())
    checks.append(disk_check())
    checks.append(vision_model_check())
    checks.append(ai_mode_check())
    return checks


def safety() -> list[Check]:
    """The panic key: on Windows it is polled (platform/win/panic), so it
    works wherever the focus is with no permission to set up. What can be
    wrong is only the key's name in the settings."""
    from ..platform.win.panic import VK, key_code
    key = panic_key()
    if key_code(key) is None:
        return [Check("safety", f"panic key ({key})", FAIL, f"{key!r} is not a key Hivemind knows",
                      "Settings > Safety > Emergency stop key: type F12 (or another of "
                      + ", ".join(k for k in VK if not k.startswith("F")) + ", F1 to F24)")]
    return [Check("safety", f"panic key ({key})", OK,
                  "works whichever window is in front (not over a UAC prompt)")]
