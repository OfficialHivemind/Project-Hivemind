"""`hivemind doctor` -- check whether this machine can actually run the bot.

Every check here corresponds to something that has genuinely broken during
development, and each reports what to DO rather than just that it failed. The
order matters: a missing system package explains a dozen downstream failures, so
it is reported first and the rest is still checked rather than aborted.

Checks are grouped by what they gate:

    environment   can the compositor, capture and input layers exist at all
    safety        can the panic key be read (this one is not optional)
    calibration   has the vision layer been taught what it needs
    state         which server Start joins, settings readable
    game settings the game's own menu settings that break the bot
"""
from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..datapaths import VAR_ROOT, data

OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "✓", WARN: "!", FAIL: "✗"}
COLOUR = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}
RESET = "\033[0m"


@dataclass
class Check:
    group: str
    name: str
    status: str
    detail: str = ""
    fix: str = ""
    key: str = ""          # which requirement, for one_command


# ---- the friend's PC (RL1, docs/pending/linux-package.md) -----------------
# Every fix is the exact command for the distro in /etc/os-release. Python
# packages, tesseract and Hyprland come from the system on Arch, Debian/Ubuntu
# /Mint and Fedora, and from the flake (flake.nix) on NixOS. Probes are module
# names so the tests can stand in for the machine.
which = shutil.which
run_cmd = subprocess.run
import_module = importlib.import_module
OS_RELEASE = Path("/etc/os-release")
HYPRLAND_MIN = (0, 56)               # nested.lua; built and measured on 0.56.2

INSTALL = {"arch": "sudo pacman -S --needed {}", "debian": "sudo apt install {}",
           "fedora": "sudo dnf install {}"}
NIX_RUN = ("start Hivemind through its flake, which brings this with it: "
           "`nix run .` in the Hivemind folder")
# requirement -> its package on each family ("" = not packaged there)
PACKAGES = {
    "pywayland": {"arch": "python-pywayland", "debian": "python3-pywayland",
                  "fedora": "python3-pywayland"},
    "xkbcommon": {"arch": "python-xkbcommon", "debian": "python3-xkbcommon",
                  "fedora": "python3-xkbcommon"},
    "cv2": {"arch": "python-opencv", "debian": "python3-opencv", "fedora": "python3-opencv"},
    "numpy": {"arch": "python-numpy", "debian": "python3-numpy", "fedora": "python3-numpy"},
    "evdev": {"arch": "python-evdev", "debian": "python3-evdev", "fedora": "python3-evdev"},
    "yaml": {"arch": "python-yaml", "debian": "python3-yaml", "fedora": "python3-pyyaml"},
    "PySide6": {"arch": "pyside6", "debian": "python3-pyside6.qtwidgets",
                "fedora": "python3-pyside6"},
    "tesseract": {"arch": "tesseract", "debian": "tesseract-ocr", "fedora": "tesseract"},
    "afr": {"arch": "tesseract-data-afr", "debian": "tesseract-ocr-afr",
            "fedora": "tesseract-langpack-afr"},
    "flatpak": {"arch": "flatpak", "debian": "flatpak", "fedora": "flatpak"},
    "hyprland": {"arch": "hyprland", "debian": "", "fedora": "hyprland"},
    "labwc": {"arch": "labwc", "debian": "labwc", "fedora": "labwc"},
    "pgrep": {"arch": "procps-ng", "debian": "procps", "fedora": "procps-ng"},
}
NIXOS = {      # configuration.nix lines; `sudo nixos-rebuild switch` after
    "hyprland": "programs.hyprland.enable = true;",
    "flatpak": "services.flatpak.enable = true;",
    "input": 'users.users.<you>.extraGroups = [ "input" ];  (then log out and back in)',
}
SOBER_INSTALL = ("flatpak remote-add --user --if-not-exists flathub "
                 "https://dl.flathub.org/repo/flathub.flatpakrepo && "
                 "flatpak install --user -y flathub org.vinegarhq.Sober")


def distro(os_release: Path | None = None) -> str:
    """arch, debian (Ubuntu, Mint, Pop...), fedora, nixos, or other."""
    try:
        text = (os_release or OS_RELEASE).read_text()
    except OSError:
        return "other"
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    ids = " ".join(fields.get(k, "").strip('"').lower() for k in ("ID", "ID_LIKE")).split()
    for family, names in (("nixos", {"nixos"}), ("arch", {"arch", "endeavouros", "manjaro"}),
                          ("fedora", {"fedora", "rhel"}),
                          ("debian", {"debian", "ubuntu", "linuxmint"})):
        if names & set(ids):
            return family
    return "other"


def fix_for(key: str, family: str) -> str:
    """The one command (or configuration.nix line) that provides `key`."""
    if family == "nixos":
        if key in NIXOS:
            return f"add to /etc/nixos/configuration.nix: {NIXOS[key]}  then: sudo nixos-rebuild switch"
        return NIX_RUN
    if key == "input":
        return "sudo usermod -aG input $USER  (then log out and back in)"
    package = PACKAGES.get(key, {}).get(family)
    if package:
        return INSTALL[family].format(package)
    if key == "hyprland" and family == "debian":
        # Not "too old": this is also the fix when Hyprland is simply missing.
        # labwc (platform.compositor) would avoid Hyprland, but it has not run
        # the real game yet (ROADMAP RL1b step 2), so it is not offered here.
        return ("Ubuntu, Mint and Debian do not have Hyprland 0.56 or newer yet, so "
                "Hivemind is not ready for them yet. If you are comfortable in a "
                "terminal: build it from https://wiki.hypr.land/Getting-Started/Installation/ "
                "or install Nix and start Hivemind with `nix run .`")
    return f"install {key} with your package manager"


def one_command(checks: list[Check], family: str) -> str:
    """Every missing package in one root command, for the installer to print."""
    if family not in INSTALL:
        return ""
    names = [PACKAGES[c.key][family] for c in checks
             if c.status == FAIL and c.key in PACKAGES and PACKAGES[c.key].get(family)]
    return INSTALL[family].format(" ".join(dict.fromkeys(names))) if names else ""


def _module(name: str, label: str, family: str) -> Check:
    try:
        import_module(name)
        return Check("environment", label, OK)
    except ImportError as exc:
        return Check("environment", label, FAIL, f"Python can't load it ({exc})",
                     fix_for(name, family), key=name)


def _binary(name: str, label: str, family: str, key: str = "") -> Check:
    path = which(name)
    if path:
        return Check("environment", label, OK, path)
    return Check("environment", label, FAIL, "not installed", fix_for(key or name, family),
                 key=key or name)


def _output(argv: list[str]) -> str:
    try:
        done = run_cmd(argv, capture_output=True, text=True, timeout=10)
        return (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def hyprland_version(text: str) -> tuple[int, ...] | None:
    match = re.search(r"Hyprland\s+v?(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(g) for g in match.groups() if g is not None) if match else None


def compositor_setting() -> str:
    """platform.compositor: "hyprland" (the default) or "labwc" (RL1b)."""
    from ..world.settings import Settings
    return str(Settings().get("platform.compositor", "hyprland"))


def labwc_checks(family: str) -> list[Check]:
    """The headless labwc session (platform/wlr_session): the binary only --
    it needs no desktop session, no Hyprland and no hyprctl."""
    from ..platform.wlr_session import LABWC_ENV, find_labwc
    found = find_labwc()
    if found:
        return [Check("environment", "labwc (headless compositor)", OK, found[0])]
    fix = fix_for("labwc", family)
    return [Check("environment", "labwc (headless compositor)", FAIL, "not found",
                  f"{fix}, or unpack one with tools/universal/fetch_compositor.sh DIR "
                  f"and set {LABWC_ENV}=DIR/root/usr/bin/labwc", key="labwc")]


def environment(family: str | None = None, compositor: str | None = None) -> list[Check]:
    family = family or distro()
    labwc = (compositor or compositor_setting()) == "labwc"
    import sys
    py = sys.version_info[:2]
    checks = [Check("environment", "Python 3.12 or newer", OK if py >= (3, 12) else FAIL,
                    f"this is {py[0]}.{py[1]}",
                    "" if py >= (3, 12) else
                    (NIX_RUN if family == "nixos" else
                     "your distro's Python is too old: Ubuntu 24.04 / Mint 22 / "
                     "Debian 13 / Fedora 40 or newer"))]

    session = os.environ.get("XDG_SESSION_TYPE", "")
    wayland = session == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
    if labwc:                  # headless: no window on any desktop, X11 too
        checks.append(Check("environment", "a Wayland desktop session", OK,
                            f"{session or 'unknown'} (not needed: labwc runs headless)"))
    else:
        checks.append(Check("environment", "a Wayland desktop session", OK if wayland else FAIL,
                            session or "unknown",
                            "" if wayland else "log out and pick the Wayland session at the "
                            "login screen (Plasma (Wayland), GNOME, Hyprland, Sway...): the "
                            "game's own Hyprland opens as a window of it, and cannot under X11"))

    for name, label in (("pywayland", "Python: pywayland"), ("xkbcommon", "Python: xkbcommon"),
                        ("cv2", "Python: OpenCV"), ("numpy", "Python: numpy"),
                        ("evdev", "Python: evdev"), ("yaml", "Python: PyYAML"),
                        ("PySide6", "Python: PySide6 (the window)")):
        checks.append(_module(name, label, family))

    hypr = which("hyprland") or which("Hyprland")
    if labwc:
        checks.extend(labwc_checks(family))
    elif not hypr:
        checks.append(Check("environment", "Hyprland 0.56+", FAIL, "not installed",
                            fix_for("hyprland", family), key="hyprland"))
    else:
        version = hyprland_version(_output([hypr, "--version"]))
        if version is None:
            checks.append(Check("environment", "Hyprland 0.56+", WARN,
                                f"{hypr}: could not read its version"))
        else:
            new = version[:2] >= HYPRLAND_MIN
            checks.append(Check("environment", "Hyprland 0.56+", OK if new else FAIL,
                                ".".join(map(str, version)),
                                "" if new else "this Hyprland is too old (needs 0.56 or "
                                "newer): " + fix_for("hyprland", family), key="hyprland"))
    if not labwc:
        checks.append(_binary("hyprctl", "hyprctl (comes with Hyprland)", family, "hyprland"))

    tess = _binary("tesseract", "Tesseract (reads text)", family)
    checks.append(tess)
    if tess.status == OK:
        langs = _output(["tesseract", "--list-langs"]).split()
        checks.append(Check("environment", "Tesseract's afr language",
                            OK if "afr" in langs else FAIL,
                            "" if "afr" in langs else "not installed",
                            "" if "afr" in langs else fix_for("afr", family), key="afr"))

    flatpak = _binary("flatpak", "Flatpak", family)
    checks.append(flatpak)
    if flatpak.status == OK:
        listed = _output(["flatpak", "list", "--app", "--columns=application"])
        has = "org.vinegarhq.Sober" in listed
        checks.append(Check("environment", "Sober (Roblox, from Flathub)", OK if has else FAIL,
                            "installed" if has else "not installed",
                            "" if has else SOBER_INSTALL + "  (no root needed)", key="sober"))
        if has and not which("org.vinegarhq.Sober"):
            checks.append(Check("environment", "Sober's launcher on PATH", FAIL,
                                "flatpak's exports/bin is not on PATH",
                                "start Hivemind with the `hivemind` launcher (it adds "
                                "~/.local/share/flatpak/exports/bin and "
                                "/var/lib/flatpak/exports/bin)", key="sober-path"))

    for name, label in (("pgrep", "pgrep"), ("setsid", "setsid")):
        checks.append(_binary(name, label, family, "pgrep" if name == "pgrep" else "util-linux"))

    # The generated Wayland bindings ship in git (platform/wl/gen)
    gen = Path(__file__).resolve().parents[1] / "platform" / "wl" / "gen"
    count = len(list(gen.glob("*.py")))
    checks.append(Check("environment", "Wayland bindings", OK if count else FAIL,
                        f"{count} modules" if count else "not shipped",
                        "" if count else "reinstall: they ship with Hivemind"))

    nodes = sorted(Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []
    nvidia = Path("/proc/driver/nvidia/version").exists()
    checks.append(Check("environment", "GPU", WARN if (not nodes or nvidia) else OK,
                        ("no GPU render node" if not nodes else
                         f"NVIDIA's driver: untested with {'headless labwc' if labwc else 'nested Hyprland'}"
                         if nvidia
                         else f"{len(nodes)} render node(s)"),
                        "" if nodes and not nvidia else
                        "it may still work; tell the owner what you see"))
    checks += [memory_check(), disk_check(), vision_model_check(family), ai_mode_check()]
    return checks


# ---- what a beginner hits after the packages (U15 release gate) ------------
# The Windows doctor has had these since 26 Oct (cli/doctor_win); on Linux a PC
# with too little free memory only found out from a refused Start.
def memory_check() -> Check:
    from ..platform.memory import SAFE_TO_START_GB, read
    m = read()
    if m.total_gb == 0.0:
        return Check("environment", "free memory", WARN, "could not read /proc/meminfo")
    said = f"{m.available_gb:.1f} GB free of {m.total_gb:.0f} GB"
    # FAIL, not WARN: the start refuses on this same rule (Memory.under_pressure,
    # run_farm), so a doctor that only warned said "Everything is here" to a PC
    # whose Start was then refused.
    if m.under_pressure:
        why = (f"Hivemind needs {SAFE_TO_START_GB:.0f} GB free to start, you have "
               f"{m.available_gb:.1f} GB"
               if m.available_gb < SAFE_TO_START_GB else
               "your PC is already short of memory, so Hivemind will not start")
        return Check("environment", "free memory", FAIL, said,
                     f"{why} (the game alone takes 3-4 GB). Close big programs first "
                     "(a browser with many tabs, Discord, another game), then check again")
    return Check("environment", "free memory", OK, said)


def ai_mode_check() -> Check:
    """Eco / Standard / Max, measured now (world/aimode, ROADMAP AI-N4).
    Never a warning: every mode runs; it only says what this PC can carry."""
    from ..platform import hardware
    from ..world import aimode
    from ..world.settings import Settings
    try:
        hw = hardware.probe()
    except Exception as exc:
        return Check("environment", "AI mode", OK, f"PC not measured ({exc})")
    return Check("environment", "AI mode", OK,
                 aimode.describe(hw, str(Settings().get(aimode.SETTING))))


def disk_check() -> Check:
    from ..telemetry.storage import LOW_DISK_GB, free_gb
    try:
        free = free_gb(VAR_ROOT)
    except OSError as exc:
        return Check("environment", "free disk space", WARN, f"could not read it ({exc})")
    said = f"{free:.0f} GB free"
    if free < LOW_DISK_GB:
        return Check("environment", "free disk space", WARN, said,
                     f"under {LOW_DISK_GB:.0f} GB free the bot stops saving the pictures "
                     "it keeps for fixing problems: free some space if you can")
    return Check("environment", "free disk space", OK, said)


def vision_model_check(family: str) -> Check:
    """The local vision model (brain/vlm) answers some reads (prompts, field
    names); without it those fall back to templates and OCR (run_farm's
    `if not model.available()` branches), so it is a warning, never a fail."""
    from ..brain.vlm import from_settings
    model = from_settings()
    if not model.enabled:
        return Check("environment", "local vision model", OK, "turned off in settings")
    if model.available():
        return Check("environment", "local vision model", OK, model.model)
    fix = model.reason
    if fix.startswith("no model server") and family != "arch":
        fix = ("install Ollama (https://ollama.com/download), start it, then: "
               f"ollama pull {model.model}")
    elif fix.startswith("no model server"):
        # brain/vlm's Arch reason installs and starts the server but never
        # pulled the model, and opens with the raw error ("[Errno 111]...")
        fix = fix.split(" — ", 1)[-1] + f" && ollama pull {model.model}"
    return Check("environment", "local vision model", WARN,
                 "not in use: some reads are less sure without it", fix)


def safety() -> list[Check]:
    from ..platform.panic import PanicWatcher
    from ..world.settings import Settings

    key = str(Settings().get("safety.panic_key", "F12"))
    watcher = PanicWatcher(on_panic=lambda: None, key=key)
    devices = watcher.find_devices()
    for device in devices:
        device.close()
    if devices:
        return [Check("safety", f"panic key ({key})", OK,
                      f"{len(devices)} keyboard(s) readable")]
    # ANOTHER GLOBAL LAYER WILL DO (gui/panic, RL1b step 3): the window arms
    # the desktop's GlobalShortcuts portal, or an X11 grab, when /dev/input is
    # not readable -- each ends in Stop, wherever the focus is.
    layer = global_panic_layer(key)
    if layer:
        return [Check("safety", f"panic key ({key})", OK,
                      f"{layer}; /dev/input is not readable, so the window's layer "
                      "stops the bot (the input group would add the bot's own)")]
    # Not a warning. Running unattended with no panic key is the scenario this
    # whole project is most careful about.
    return [Check("safety", f"panic key ({key})", FAIL, watcher.reason,
                  fix_for("input", distro()) + ", or use a desktop with the "
                  "GlobalShortcuts portal (KDE, GNOME, Hyprland) or X11", key="input")]


def global_panic_layer(key: str = "F12") -> str:
    """The window's global panic layer on this desktop, described, or ""."""
    import ctypes.util
    try:
        from ..gui import panic
    except Exception:                    # no PySide6: doctor says so above
        return ""
    where = panic.host()
    if where == "wayland":
        ok, why = panic.PortalShortcut(None, key).available()
        return f"{key} through the desktop's GlobalShortcuts portal ({why})" if ok else ""
    if where == "x11" and ctypes.util.find_library("X11"):
        return f"{key} grabbed on the X11 desktop"
    return ""


def calibration() -> list[Check]:
    checks = []
    index = data("templates", "digits", "index.json")
    if index.exists():
        chars = set(json.loads(index.read_text()).values())
        missing = [d for d in "0123456789" if d not in chars]
        checks.append(Check("calibration", "digit templates",
                            OK if not missing else WARN,
                            f"{len(chars)} glyphs"
                            + (f", missing {missing}" if missing else ", all ten digits"),
                            "" if not missing else
                            "run scripts/learn_digits.py on a frame containing them"))
    else:
        checks.append(Check("calibration", "digit templates", FAIL, "none",
                            "scripts/learn_digits.py FRAME --honey <value>"))

    # Every FAIL carries a fix. doctor's whole promise is that it tells you
    # what to DO -- and a fix naming a tool that does not exist is worse than
    # none: scripts/measure_regions.py, regions.example.yaml, scripts/
    # learn_ui.py and `hivemind calibrate` were never written, and all three
    # files ship with the project (git ls-files data/calib data/templates/ui),
    # so "reinstall" is the true answer (DESIGN 8du). These four were once
    # constructed with no fix= at all -- which
    # went unnoticed because the test guarding it only asserts inside
    # `if status == FAIL`, and nothing here fails on a healthy checkout.
    for name, parts, fix in [
            ("screen regions", ("calib", "regions.yaml"),
             "reinstall: this ships with the project and should never be missing"),
            ("field list", ("world", "fields.yaml"),
             "reinstall: this ships with the project and should never be missing"),
            ("expiry durations", ("economy", "expiries.yaml"),
             "reinstall: this ships with the project and should never be missing"),
            ("UI templates", ("templates", "ui", "servers_label.png"),
             "reinstall: this ships with the project and should never be missing")]:
        p = data(*parts)
        checks.append(Check("calibration", name, OK if p.exists() else FAIL,
                            str(p) if p.exists() else f"missing: {p}",
                            "" if p.exists() else fix))

    homography = data("calib", "homography.yaml")
    checks.append(Check("calibration", "ground homography",
                        OK if homography.exists() else WARN,
                        str(homography) if homography.exists()
                        else "not calibrated — distances will be unavailable",
                        "" if homography.exists() else
                        "reinstall: data/calib/homography.yaml ships with the "
                        "project, and nothing here regenerates it"))
    return checks


def state() -> list[Check]:
    from ..world.settings import CONFIG, Settings

    from ..platform.lastserver import BY_LINK, MY_SERVER, share_link

    # WHICH SERVER START JOINS is `server.join` (platform/lastserver.target),
    # not the old server.yaml: a fresh install joins "my private server" with
    # no file at all. Only a share-link choice with no link is worth a warning
    # (target() then falls back to the private server, and says so in the log).
    settings = Settings()
    join = str(settings.get("server.join") or MY_SERVER)
    if join == BY_LINK and share_link(settings.get("server.link", "")) is None:
        checks = [Check("state", "which server it joins", WARN,
                        f"'{join}', but there is no share link",
                        "paste the link in Settings > Server > Share link to join, or pick "
                        f"'{MY_SERVER}'. Until then it joins your own private server")]
    else:
        checks = [Check("state", "which server it joins", OK, join)]

    checks.append(Check("state", "settings",
                        OK if not settings.problems else WARN,
                        str(CONFIG) if CONFIG.exists() else "using defaults",
                        "; ".join(settings.problems)))

    harvests = VAR_ROOT / "harvests.jsonl"
    if harvests.exists():
        from ..economy.degradation import HarvestLog
        evidence = HarvestLog(harvests).evidence()
        checks.append(Check("state", "degradation evidence", OK,
                            evidence.summary()))
    else:
        checks.append(Check("state", "degradation evidence", WARN,
                            "no harvests recorded yet",
                            "accumulates automatically once the bot farms"))
    return checks


def game_settings() -> list[Check]:
    """The game's own menu settings (platform/gameprefs): one line each that
    is wrong, a FAIL for one that breaks the bot outright."""
    from ..platform import gameprefs
    path = gameprefs.settings_file()
    if path is None:
        return [Check("game settings", "Roblox settings", WARN, "not found yet",
                      "start the game once: it saves its settings on the first launch")]
    found = gameprefs.problems(gameprefs.read(path))
    if not found:
        return [Check("game settings", "Roblox settings", OK,
                      f"all as the bot was measured with ({path.name})")]
    return [Check("game settings", name, FAIL if breaks else WARN, wrong, how)
            for name, wrong, how, breaks in found]


WINDOWS = os.name == "nt"


def sections(windows: bool = WINDOWS) -> tuple:
    """What is checked: on Windows its own environment and panic key
    (cli/doctor_win: no Wayland, Hyprland, Sober or evdev there), and the
    same calibration and state as Linux."""
    if windows:
        from . import doctor_win
        return (doctor_win.environment, doctor_win.safety, calibration, state,
                game_settings)
    return environment, safety, calibration, state, game_settings


def run() -> list[Check]:
    checks: list[Check] = []
    for section in sections():
        try:
            checks.extend(section())
        except Exception as exc:                       # a broken check is a finding
            checks.append(Check(section.__name__, "check itself", FAIL, repr(exc)))
    return checks


def report(checks: list[Check], family: str | None = None, colour: bool = False) -> str:
    """Plain English, one line a check, the fix under each one that is not ✓,
    and every missing package as ONE root command at the end."""
    family = family or distro()
    lines, current = [], ""
    for check in checks:
        if check.group != current:
            current = check.group
            lines.append(f"\n  {current.upper()}")
        mark = MARK[check.status]
        if colour:
            mark = f"{COLOUR[check.status]}{mark}{RESET}"
        lines.append(f"    {mark}  {check.name:30s} {check.detail}".rstrip())
        if check.fix and check.status != OK:
            lines.append(f"         fix: {check.fix}")
    failed = sum(1 for c in checks if c.status == FAIL)
    warned = sum(1 for c in checks if c.status == WARN)
    lines.append(f"\n  {len(checks)} checks · {failed} to fix · {warned} warnings"
                 + (" · Windows" if WINDOWS else f" · distro: {family}"))
    command = one_command(checks, family)
    if command:
        lines.append("\n  One command installs every missing package (it needs your password,"
                     "\n  so run it yourself):\n      " + command)
        # a FAIL no package fixes (Hyprland on Ubuntu, free memory, the input
        # group): the command alone would never turn it into a ✓
        if any(c.status == FAIL and not PACKAGES.get(c.key, {}).get(family)
               for c in checks):
            lines.append("\n  That command does not fix every ✗ line: some need the fix"
                         "\n  written under them instead.")
    if not failed:
        lines.append("\n  Everything Hivemind needs is here.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    checks = run()
    print(report(checks, colour=os.isatty(1)))
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
