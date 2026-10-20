"""RL1, the Linux test package: the first-run checker with the machine mocked,
and the launcher run against a throwaway HOME with a stand-in python (no GUI,
no bot, no game is ever started here)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from hivemind.cli import doctor

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
LAUNCHER = ROOT / "installer/linux/hivemind"

RELEASES = {
    "arch": 'NAME="Arch Linux"\nID=arch\n',
    "debian": 'NAME="Linux Mint"\nID=linuxmint\nID_LIKE="ubuntu debian"\n',
    "fedora": 'NAME="Fedora Linux"\nID=fedora\n',
    "nixos": 'NAME=NixOS\nID=nixos\n',
    "other": 'NAME=Gentoo\nID=gentoo\n',
}


@pytest.mark.parametrize("family", sorted(RELEASES))
def test_distro_from_os_release(tmp_path, family):
    path = tmp_path / "os-release"
    path.write_text(RELEASES[family])
    assert doctor.distro(path) == family
    assert doctor.distro(tmp_path / "missing") == "other"


def test_ubuntu_is_debian_family(tmp_path):
    path = tmp_path / "os-release"
    path.write_text('ID=ubuntu\nID_LIKE=debian\n')
    assert doctor.distro(path) == "debian"


def _bare_machine(monkeypatch, session="x11"):
    """Nothing installed: every import fails, nothing on PATH, no Wayland."""
    def no_import(name):
        raise ImportError(f"No module named {name!r}")
    monkeypatch.setattr(doctor, "import_module", no_import)
    monkeypatch.setattr(doctor, "which", lambda name: None)
    monkeypatch.setenv("XDG_SESSION_TYPE", session)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)


@pytest.mark.parametrize("family", ["arch", "debian", "fedora", "nixos", "other"])
def test_every_missing_requirement_fails_with_a_fix(monkeypatch, family):
    _bare_machine(monkeypatch)
    checks = doctor.environment(family)
    failed = {c.name: c for c in checks if c.status == doctor.FAIL}
    for name in ("a Wayland desktop session", "Python: pywayland", "Python: PySide6 (the window)",
                 "Hyprland 0.56+", "Tesseract (reads text)", "Flatpak"):
        assert name in failed, name
    for check in failed.values():
        assert check.fix, check.name
        if family == "nixos":
            assert "apt" not in check.fix and "pacman" not in check.fix and "dnf" not in check.fix
    if family == "arch":
        assert failed["Python: pywayland"].fix == "sudo pacman -S --needed python-pywayland"
    if family == "nixos":
        assert "nix run" in failed["Python: OpenCV"].fix
        assert "programs.hyprland.enable = true;" in failed["Hyprland 0.56+"].fix
        assert "services.flatpak.enable = true;" in failed["Flatpak"].fix


def test_one_root_command_for_everything_missing(monkeypatch):
    _bare_machine(monkeypatch)
    command = doctor.one_command(doctor.environment("debian"), "debian")
    assert command.startswith("sudo apt install ")
    for package in ("python3-pywayland", "python3-opencv", "tesseract-ocr", "flatpak"):
        assert package in command.split()
    assert doctor.one_command(doctor.environment("nixos"), "nixos") == ""


def test_hyprland_version(monkeypatch):
    assert doctor.hyprland_version("Hyprland 0.56.2 built from branch main") == (0, 56, 2)
    assert doctor.hyprland_version("Hyprland v0.41.2") == (0, 41, 2)
    assert doctor.hyprland_version("garbage") is None

    monkeypatch.setattr(doctor, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(doctor, "import_module", lambda n: None)

    def fake_run(argv, **kw):
        out = {"--version": "Hyprland 0.41.2 built from branch",
               "--list-langs": "List of available languages (2):\neng\nosd\n"}.get(argv[-1], "")
        if argv[0] == "flatpak":
            out = "org.vinegarhq.Sober\n"
        return subprocess.CompletedProcess(argv, 0, out, "")
    monkeypatch.setattr(doctor, "run_cmd", fake_run)
    checks = {c.name: c for c in doctor.environment("fedora")}
    assert checks["Hyprland 0.56+"].status == doctor.FAIL
    assert checks["Hyprland 0.56+"].fix.endswith("sudo dnf install hyprland")
    assert checks["Tesseract's afr language"].fix == "sudo dnf install tesseract-langpack-afr"
    assert checks["Sober (Roblox, from Flathub)"].status == doctor.OK


def test_report_is_plain_english_with_marks(monkeypatch):
    _bare_machine(monkeypatch)
    text = doctor.report(doctor.environment("arch"), "arch")
    assert "✗" in text and "fix: sudo pacman -S --needed" in text
    assert "One command installs every missing package" in text
    ok = doctor.report([doctor.Check("g", "n", doctor.OK)], "arch")
    assert "✓" in ok and "Everything Hivemind needs is here." in ok


def test_first_run_check_shows_until_it_passes(tmp_path):
    from hivemind.gui.app import first_run_check
    marker = tmp_path / "first-run-passed"
    bad = [doctor.Check("environment", "Flatpak", doctor.FAIL, fix="sudo apt install flatpak")]
    text = first_run_check(marker=marker, run=lambda: bad)
    assert "✗ Flatpak: sudo apt install flatpak" in text and not marker.exists()
    text = first_run_check(marker=marker, run=lambda: [doctor.Check("g", "n", doctor.OK)])
    assert text.startswith("✓") and marker.exists()
    assert first_run_check(marker=marker, run=lambda: bad) is None   # passed once: quiet


# ---- the launcher, against a throwaway HOME --------------------------------
def _store(tmp_path) -> tuple[Path, Path, dict]:
    """A read-only 'store' copy of the bits the launcher touches, a stand-in
    python that only prints its arguments, and the environment for it."""
    store = tmp_path / "store"
    for rel in ("installer/linux/hivemind", "data/presets/safe-first-run.yaml",
                "scripts/overnight.sh"):
        (store / rel).parent.mkdir(parents=True, exist_ok=True)
        (store / rel).write_bytes((ROOT / rel).read_bytes())
    python = tmp_path / "python"
    python.write_text('#!/bin/sh\necho "python $*"\n')
    python.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(home),
           "HIVEMIND_SOURCE": str(store), "HIVEMIND_PYTHON": str(python)}
    return store, home, env


def test_launcher_installs_from_the_store_and_writes_safe_settings(tmp_path):
    store, home, env = _store(tmp_path)
    done = subprocess.run(["bash", str(LAUNCHER), "doctor"], env=env,
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "python -m hivemind.cli.main doctor"
    app = home / ".local/share/hivemind/app"
    assert (app / ".source").read_text().strip() == str(store)
    assert os.readlink(app / ".venv/bin/python") == env["HIVEMIND_PYTHON"]
    assert os.access(app / "scripts/overnight.sh", os.X_OK)
    settings = (home / ".config/hivemind/settings.yaml").read_text()
    assert "server.join: my private server" in settings      # Linux joins its own server
    assert "quests.enabled: false" in settings and "gui.layout: new" in settings
    assert (home / ".config/hivemind/presets/Safe first run.yaml").read_text() == settings

    # the GUI gets the first-run check; existing settings are never replaced
    (home / ".config/hivemind/settings.yaml").write_text("mine: true\n")
    done = subprocess.run(["bash", str(LAUNCHER)], env=env, capture_output=True,
                          text=True, timeout=30)
    assert done.stdout.strip() == "python -m hivemind.gui --first-run-check"
    assert (home / ".config/hivemind/settings.yaml").read_text() == "mine: true\n"


def test_uninstall_keeps_what_it_learned_unless_purged(tmp_path):
    store, home, env = _store(tmp_path)
    subprocess.run(["bash", str(LAUNCHER), "doctor"], env=env, capture_output=True, timeout=30)
    app = home / ".local/share/hivemind/app"
    (app / "var").mkdir()
    (app / "var/trips.jsonl").write_text("{}\n")
    env.pop("HIVEMIND_SOURCE")
    done = subprocess.run(["bash", str(LAUNCHER), "uninstall"], env=env,
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in app.iterdir()) == ["var"]
    assert (home / ".config/hivemind/settings.yaml").exists()
    # and --purge still works afterwards, with the code already gone
    done = subprocess.run(["bash", str(LAUNCHER), "uninstall", "--purge"], env=env,
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert not app.exists() and not (home / ".config/hivemind").exists()


def test_the_flake_and_the_desktop_entry_agree_with_the_checker():
    flake = (ROOT / "flake.nix").read_text()
    for nix_name in ("pyside6", "pywayland", "xkbcommon", "opencv4", "numpy", "evdev", "pyyaml"):
        assert nix_name in flake
    assert 'enableLanguages = [ "afr"' in flake
    assert "installer/linux/hivemind" in flake
    desktop = (ROOT / "installer/linux/hivemind.desktop").read_text()
    assert "Exec=hivemind\n" in desktop and "Icon=hivemind\n" in desktop
