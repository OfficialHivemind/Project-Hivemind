"""Start farming when the PC starts (ROADMAP U13). No Qt here.

THE ASK (a viewer, 2026-10-15): start farming as soon as the computer starts
up, as Natro can. The setting `gui.start_on_boot`
(default OFF, and off for the owner unless they turn it on) writes a user
autostart entry, ~/.config/autostart/hivemind.desktop (the freedesktop
autostart spec: KDE, GNOME and Hyprland's xdg-autostart all read it), that
opens Hivemind with --autostart after login. Turning it off removes the entry.

AFTER LOGIN (gui/window.begin_autostart): a 60 s grace with a visible Cancel
and a Telegram note 'starting in 60 s, /stop to cancel' -- /stop deletes the
countdown's file (var/night/autostart.pending, scripts/telegram_alerts
stop_bot) and the window sees it gone -- then Play, only if the gates pass:

  * THE GAME GUARD (platform/gameguard.playing), whatever `guard.enabled`
    says: an unattended start never goes beside another game (2026-10-03 and
    2026-10-08, both test-PC crashes);
  * FREE MEMORY (platform/memory.check), the same gate the watchdog uses.

Windows / macOS equivalents (Startup folder, LaunchAgent) are later (RL6).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

GRACE_S = 60
ENTRY = "hivemind.desktop"
PENDING = "autostart.pending"
ROOT = Path(__file__).resolve().parents[3]


def entry_path() -> Path:
    """$XDG_CONFIG_HOME/autostart/hivemind.desktop, read at call time."""
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "autostart" / ENTRY


def launch_command(python: str | None = None, root: Path = ROOT) -> str:
    """THE INSTALLED LAUNCHER when there is one (~/.local/bin/hivemind, as an
    absolute path: autostart promises no PATH). It sets PYTHONPATH and the
    flatpak PATH for Sober; a bare `python -m hivemind.gui` could not even
    import hivemind at login (usability check 2026-10-26). A checkout with
    no install gets the same PYTHONPATH through `env`."""
    launcher = Path.home() / ".local" / "bin" / "hivemind"
    if python is None and os.access(launcher, os.X_OK):
        return f"{launcher.absolute()} --autostart"
    return f"env PYTHONPATH={root / 'src'} {python or sys.executable} -m hivemind.gui --autostart"


def entry_text(python: str | None = None, root: Path = ROOT) -> str:
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Hivemind (start farming)\n"
            "Comment=Opens Hivemind after login; it starts farming after a 60 s "
            "grace unless a game is running or memory is short. Turn off in "
            "Hivemind > Settings.\n"
            f"Exec={launch_command(python, root)}\n"
            f"Path={root}\n"
            f"Icon={root / 'data' / 'icon.png'}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n")


def apply(on: bool, python: str | None = None) -> str:
    """Write or remove the entry to match the setting; says what it did."""
    path = entry_path()
    try:
        if on:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(entry_text(python))
            return f"Hivemind will open after login and start farming ({path})"
        if path.exists():
            path.unlink()
            return f"start on boot is off: removed {path}"
        return "start on boot is off"
    except OSError as exc:
        return f"could not change {path}: {exc.strerror or exc}"


def wanted(settings) -> bool:
    """`gui.start_on_boot`, read when the window opens with --autostart: an
    entry left behind by an old install starts nothing once it is off."""
    return bool(settings.bool("gui.start_on_boot"))


from ..act.startcheck import blocker  # the GUI may not import platform

__all__ = ["blocker"]


def pending_path() -> Path:
    from ..datapaths import var
    return var("night", PENDING)
