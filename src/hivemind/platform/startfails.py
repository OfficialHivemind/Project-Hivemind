"""Starts that fail the same way again and again: said, looked at, and spaced out.

MEASURED 2026-10-12 22:37 to 23:17 (var/night/run-922..935.log, attempts.log):
"FAILED: Sober never opened a window" 14 times in a row, each start ~155 s
(act/bootstrap WINDOW_TIMEOUT) then the watchdog's 20 s gap, so ~40 min in
game lost, and nothing told the owner. That night's cause was a broken
xdg-document-portal: Sober's bwrap said "Can't find source path
/run/user/1000/doc", and `systemctl --user restart xdg-document-portal.service`
by hand at 23:17:09 (journalctl --user -u xdg-document-portal) fixed it: the
23:18 start (run-936) got in.

So run_farm keeps the streak in STREAK_FILE across the watchdog's attempts:
the ALERT_AT-th identical failure in a row logs the windows and the flatpak
instances and says it on Telegram (scripts/telegram_alerts.py --send, once a
streak), and from then on each attempt waits `backoff_s` before handing back
to the watchdog. A start that reaches the game clears it. The portal case is
recognised in var/sober.log (truncated per launch, so it is the failed one's)
and the portal restarted once a streak: a user service, nothing of the game's.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ALERT_AT = 2
BACKOFF_FIRST_S = 180.0           # the watchdog's own LONG_GAP (scripts/overnight.sh)
BACKOFF_MAX_S = 30 * 60.0
# A failure this long after the last one starts a new streak (the bot was
# stopped in between, not failing): longer than BACKOFF_MAX_S plus a start.
STALE_S = 60 * 60.0
PORTAL_SIGN = "Can't find source path /run/user/"
PORTAL_RESTART = ["systemctl", "--user", "restart", "xdg-document-portal.service"]
TELEGRAM = Path(__file__).resolve().parents[3] / "scripts" / "telegram_alerts.py"


def load(path: Path) -> dict:
    try:
        body = json.loads(Path(path).read_text())
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, path)


def clear(path: Path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def note(state: dict, reason: str, now: float) -> dict:
    """The streak after a failed start for `reason`."""
    if (state.get("reason") == reason
            and now - float(state.get("last") or 0.0) <= STALE_S):
        return dict(state, count=int(state.get("count") or 0) + 1, last=now)
    return {"reason": reason, "count": 1, "since": now, "last": now}


def backoff_s(count: int) -> float:
    """The wait after the count-th identical failure: none before ALERT_AT,
    then BACKOFF_FIRST_S doubling to BACKOFF_MAX_S."""
    if count < ALERT_AT:
        return 0.0
    return min(BACKOFF_FIRST_S * 2 ** (count - ALERT_AT), BACKOFF_MAX_S)


def portal_broken(sober_log: str) -> bool:
    """Sober's bwrap could not mount the document portal (/run/user/N/doc)."""
    return any(PORTAL_SIGN in line and "/doc" in line for line in sober_log.splitlines())


def _out(argv, run) -> str:
    try:
        r = run(argv, capture_output=True, text=True, timeout=30)
        return (r.stdout or "").strip() or f"(nothing, exit {r.returncode})"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"(could not run: {exc})"


def flatpak_instances(run=subprocess.run) -> str:
    """Every running flatpak instance (Sober is org.vinegarhq.Sober): read only."""
    return _out(["flatpak", "ps"], run)


def restart_portal(run=subprocess.run) -> str:
    return _out(PORTAL_RESTART, run)


def tell(text: str, run=subprocess.run) -> bool:
    """Say `text` on Telegram the way the build loop does. Never raises."""
    try:
        return run([sys.executable, str(TELEGRAM), "--send", text],
                   capture_output=True, timeout=90).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
