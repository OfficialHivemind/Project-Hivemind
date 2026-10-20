"""What a restart would otherwise forget: var/resume.json (ROADMAP S14).

MOST OF IT IS ON DISK ALREADY. The errand timers (var/errand_log.json,
errand_ready.json), the boost (boosts.jsonl), the bosses, memory match, bug
runs, planters, jelly, purchases, goals and quests each have their own file
and are re-read at start. The audit (docs/pending/resume-audit.md) measured
what was still lost across the 152 runs of 13-19 Oct, about 22 restarts a day:

- THE QUEST CLOCK (brain/questclock). Its next read could be up to two hours
  off, but a new process read the menu at start whenever the last read was
  ten minutes old: 57 start-up reads came before the last process's own due
  time (median 59 min early), about 62 s each with the menu open, and
  run-1088 froze right after one.
- THE BALLOON'S 45 MINUTES and its empty-backoff: 70 balloon waits came
  sooner than 45 min after the last, 57 of them on an empty balloon.
- THE ANT CHALLENGE'S 20-MINUTE REPLAY GAP: 2 walks inside it.

Only wall-clock times are kept, so they stay true across a restart. Never the
position or the bag (the game says those), and the balloon only on the same
server (lastserver's digest): a new server is not trusted to have kept it.

A FILE THAT CANNOT BE BELIEVED IS IGNORED AND SAID SO, never raised: missing,
unreadable, another version, older than MAX_AGE_S, from the future, another
account. Each part is checked on its own, so one bad part drops only itself.
"""
from __future__ import annotations

import json
import time

from hivemind.files import atomic_write

VERSION = 1
MAX_AGE_S = 3 * 3600.0       # older than this is another day's state
FUTURE_SLACK_S = 60.0        # a clock step, not a file from the future


def save(path, *, server: str, account: str, quests: dict | None = None,
         balloon: dict | None = None, ant: dict | None = None,
         now: float | None = None) -> None:
    """Write the resume file atomically (hivemind.files.atomic_write)."""
    body = {"version": VERSION, "saved_at": time.time() if now is None else now,
            "server": server or "", "account": account or ""}
    for name, part in (("quests", quests), ("balloon", balloon), ("ant", ant)):
        if part:
            body[name] = part
    atomic_write(path, json.dumps(body, indent=1))


def _num(part, *keys) -> bool:
    return isinstance(part, dict) and all(
        isinstance(part.get(k), (int, float)) and not isinstance(part.get(k), bool)
        for k in keys)


def load(path, *, server: str, account: str, now: float | None = None) -> tuple[dict, str]:
    """(the parts still usable, what was said about the file). Never raises."""
    now = time.time() if now is None else now
    try:
        body = json.loads(open(path).read())
    except FileNotFoundError:
        return {}, "no resume file (a first start)"
    except (OSError, ValueError) as exc:
        return {}, f"resume file unreadable ({type(exc).__name__}) — ignored"
    if not isinstance(body, dict) or body.get("version") != VERSION:
        return {}, "resume file of another version — ignored"
    if not _num(body, "saved_at"):
        return {}, "resume file without a time — ignored"
    age = now - float(body["saved_at"])
    if age > MAX_AGE_S or age < -FUTURE_SLACK_S:
        return {}, f"resume file {age / 60:.0f} min old — ignored"
    if account and body.get("account") and body.get("account") != account:
        return {}, "resume file of another account — ignored"
    same_server = bool(server) and body.get("server") == server
    got, notes = {}, []
    q = body.get("quests")
    if _num(q, "last_at", "due_at"):
        got["quests"] = {"last_at": float(q["last_at"]), "due_at": float(q["due_at"]),
                         "why": str(q.get("why") or "")}
    elif q is not None:
        notes.append("its quest clock was malformed")
    b = body.get("balloon")
    if _num(b, "at", "empty"):
        if same_server:
            got["balloon"] = {"at": float(b["at"]), "empty": int(b["empty"])}
        else:
            notes.append("the balloon's wait is not kept on a new server")
    elif b is not None:
        notes.append("its balloon was malformed")
    a = body.get("ant")
    if _num(a, "at"):
        got["ant"] = {"at": float(a["at"])}
    elif a is not None:
        notes.append("its ant replay time was malformed")
    said = (f"resume file from {age / 60:.0f} min ago"
            + (" (same server)" if same_server else "")
            + (": kept " + ", ".join(got) if got else ": nothing in it to keep")
            + ("; " + "; ".join(notes) if notes else ""))
    return got, said


def quest_skip(part: dict | None, file_read_at: float, now: float) -> bool:
    """Whether the start-up quest read can wait for the last process's own
    due time: the clock was saved after the read var/quests.json holds (no
    newer read it did not see) and its due time is still ahead."""
    if not part or not file_read_at:
        return False
    return file_read_at <= part["last_at"] + 5.0 and part["due_at"] > now
