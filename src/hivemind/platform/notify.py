"""Telling the owner, on their own desktop, when only they can do something.

THE OWNER'S LIST, 2026-10-02, item 19: Roblox's "Updated Agreements" box held
the bot at the join from 06:40 to 11:27 that morning -- accepting the terms is
theirs, never the bot's (act/bootstrap NEEDS_THE_OWNER) -- and nothing told them.
A desktop notification (KDE, over the session bus, by notify-send) is seen
whenever they are at the machine. Each reason is said at most once per
ALERT_EVERY_S in a process, and a failure to notify never stops anything.
"""
from __future__ import annotations

import subprocess
import time

ALERT_EVERY_S = 15 * 60.0
_last: dict = {}


def owner_alert(title: str, body: str, *, key: str | None = None,
                urgency: str = "critical", clock=time.monotonic,
                run=subprocess.run) -> bool:
    """Show `title`/`body` on the owner's desktop. True when it was sent."""
    which = key or title
    now = clock()
    if which in _last and now - _last[which] < ALERT_EVERY_S:
        return False
    _last[which] = now
    try:
        run(["notify-send", "--app-name=Hivemind", f"--urgency={urgency}",
             "--icon=dialog-warning", title, body],
            capture_output=True, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
