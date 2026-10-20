"""S7: the owner's "what's new", once after each update, in the GUI and on Telegram.

THE WORDS ARE WRITTEN BY A PERSON, in data/whats_new.md, never made from
commit messages (the owner's rule for the changelog, 16 Oct: it says what
changed, not how; tools/post_changelog.py follows the same rule). Newest entry
on top, each one a `## heading` and a few plain lines under it. An update that
brings a new top entry is "what's new"; one that does not says nothing.

ONCE PER READER: var/whats_new_seen.json keeps the heading each reader
("gui", "telegram") last showed, so the app and the phone each say it once.
A missing or broken file means nothing was seen yet: the newest entry shows.

Stdlib only: the Telegram service imports this on the system python.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import datapaths

NOTES = datapaths.data("whats_new.md")


def _seen_path() -> Path:
    # at call time: a demo moves var/ after import (datapaths.use_demo_dirs)
    return datapaths.var("whats_new_seen.json")


def newest(path: Path | None = None) -> tuple[str, str]:
    """The top entry as (heading, body); ("", "") with no file or no entry."""
    try:
        lines = Path(path or NOTES).read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", ""
    head, body = "", []
    for line in lines:
        if head and line.startswith("#"):    # the next entry (or any heading)
            break
        if line.startswith("## "):
            head = line[3:].strip()
        elif head:
            body.append(line)
    return head, "\n".join(body).strip()


def _seen(seen: Path) -> dict:
    try:
        out = json.loads(seen.read_text(encoding="utf-8"))
        return out if isinstance(out, dict) else {}
    except (OSError, ValueError):
        return {}


def unseen(reader: str, path: Path | None = None, seen: Path | None = None):
    """(heading, body) when `reader` has not shown the newest entry yet, else None."""
    head, body = newest(path)
    if not head or _seen(Path(seen or _seen_path())).get(reader) == head:
        return None
    return head, body


def mark_seen(reader: str, heading: str, seen: Path | None = None) -> None:
    seen = Path(seen or _seen_path())
    rows = _seen(seen)
    rows[reader] = heading
    try:
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    except OSError:
        pass                                 # a read-only folder: it shows again
