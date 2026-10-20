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
import socket
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
# NO INTERNET LOOKS LIKE "STUCK ON LOADING". MEASURED 2026-10-26 01:04-17:49
# (var/night/run-1211..1243.log, Sober's own data/sober/sober_logs/*.log): 33
# starts in a row failed "app never reached home (stuck on loading)", the
# nested session showing Sober's "Crash" window, while its log said
#   ERROR: download: couldn't download resource from: https://sober.vinegarhq.org/app
#          (error=Could not resolve hostname)
#   FATAL: Crash: Failed to fetch remote manifest required for operation. ...
# and the Telegram poller failed the same 16 hours (journalctl --user). Each
# start then sat out the whole back-off, up to 30 min after the network was back.
OFFLINE_SIGNS = ("Could not resolve hostname", "Failed to fetch remote manifest")
# The first host Sober fetches (above); Windows has no Sober, and its client is
# ASSUMED to need Roblox's own site first.
ONLINE_HOST = "www.roblox.com" if os.name == "nt" else "sober.vinegarhq.org"
ONLINE_POLL_S = 30.0
# A SERVER ROBLOX SHUT DOWN (reason 275) CANNOT BE JOINED AT ONCE. MEASURED
# 2026-10-20 06:28:32 (run-1101 -> 1102 -> 1103) and 2026-10-22 02:48:56
# (1178 -> 1179 -> 1180): the start launched 28 s and 25 s after the end got
# "Connection Failed ... No response from server (Error Code: 279)" at its Join
# (var/join/062951-ended_on_modal.png, 025019-ended_on_modal.png); the next,
# launched 101 s and 105 s after the end, was in game 45 s and 44 s later. So
# a start after a shutdown launches no sooner than this after it.
# ponytail: two samples bracket it (fails at +25-28 s, joins at +101-105 s);
# a 279 later than this is still a failed start, spaced out as ever.
SHUTDOWN_REJOIN_S = 105.0
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


def offline(sober_log: str) -> bool:
    """Sober could not reach the internet (OFFLINE_SIGNS in its log)."""
    return any(sign in sober_log for sign in OFFLINE_SIGNS)


def online(resolve=socket.getaddrinfo) -> bool:
    """Does ONLINE_HOST resolve? Sober cannot start without it (OFFLINE_SIGNS)."""
    try:
        resolve(ONLINE_HOST, 443)
        return True
    except OSError:
        return False


def loss_wait_s(loss: dict, now: float) -> float:
    """How long a start waits after the disconnect `loss` (run_farm's
    LOSS_FILE: its kind and end time): SHUTDOWN_REJOIN_S from a shutdown."""
    if loss.get("kind") != "shutdown":
        return 0.0
    return max(0.0, float(loss.get("at") or 0.0) + SHUTDOWN_REJOIN_S - now)


def wait_online(wait, budget_s: float, resolve=socket.getaddrinfo) -> bool:
    """Wait up to `budget_s`, a look every ONLINE_POLL_S, until ONLINE_HOST
    resolves: True when it does. `wait(s)` is `threading.Event.wait`, so a
    stop ends it early (False)."""
    waited = 0.0
    while True:
        if online(resolve):
            return True
        if waited >= budget_s:
            return False
        step = min(ONLINE_POLL_S, budget_s - waited)
        if wait(step):
            return False
        waited += step


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
