"""$7 CODES FROM THE PHONE: the owner sends `/code Beesbuzz123` by Telegram,
the code is queued in var/codes.json, and the bot says what redeeming it
would do. LOOK-ONLY.

NOTHING about the game's code box is MEASURED: no frame, log or survey in
var/ shows where it is, what it says after a good, used or expired code, or
whether the chat steals the typed letters. So `would` only logs
"codes would: ..." while CODES_LIVE is False; the live redeem (open the box,
type, Enter, read the answer, mark it) is not written until those frames
are captured. The code itself is checked here, at the trust boundary: only
letters and digits (every code in data/knowledge/progression/white.yaml's
guide list is), so nothing but a code is ever typed into the game.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

# LOOK-ONLY until the code box, its answers and the typing path are measured.
CODES_LIVE = False
FILE = "codes.json"
CODE_RE = re.compile(r"[A-Za-z0-9]{2,40}")
USE = "Send it as: /code Beesbuzz123 (letters and digits only)."


def _path(var_root) -> Path:
    if var_root is None:
        from ..datapaths import VAR_ROOT
        var_root = VAR_ROOT
    return Path(var_root) / FILE


def load(var_root=None) -> list:
    try:
        got = json.loads(_path(var_root).read_text())
    except (OSError, ValueError):
        return []
    return [r for r in got if isinstance(r, dict) and r.get("code")] \
        if isinstance(got, list) else []


def add(words: str, var_root=None, now: float | None = None) -> str:
    """Queue one code from the owner's words; the answer for Telegram.
    A code already in the file (any case: Roblox codes are typed as sent,
    but a repeat is the same code) is not queued twice."""
    code = words.strip()
    if not CODE_RE.fullmatch(code):
        return USE
    rows = load(var_root)
    if any(r["code"].lower() == code.lower() for r in rows):
        return f"{code} is already queued."
    rows.append({"code": code, "at": time.time() if now is None else now,
                 "state": "queued"})
    path = _path(var_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1))
    return (f"Queued {code}. Redeeming is look-only for now: the bot logs what it "
            "would do (the game's code box is not measured yet).")


def pending(var_root=None) -> list:
    return [r["code"] for r in load(var_root) if r.get("state") == "queued"]


def would(var_root=None):
    """(live, message) for the queued codes, or None when none is queued.
    `live` is always False while CODES_LIVE is False."""
    codes = pending(var_root)
    if not codes:
        return None
    plan = (f"redeem {', '.join(codes)} on the pad: open the game's code box, type each "
            "code, press Enter, read the answer and mark it redeemed or refused")
    if not CODES_LIVE:
        return False, f"codes would: {plan}; look-only (act/codes CODES_LIVE is False)"
    return True, f"codes: {plan}"
