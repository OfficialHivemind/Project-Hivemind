"""THE ITEM REPORT AND THE RARE DROPS (ROADMAP ITEM-REP + TG4): what each item
gained and spent per day, from the inventory's own reads (act/inventory.write
keeps the last brain/goals.READS_KEPT reads' counts in var/inventory.json
"reads": [[at, {slug: count}], ...]), and the rare items whose count rose.

Stdlib only: the Telegram service (scripts/telegram_alerts.py, /report) runs
on the system python and imports this; only `load_rare` needs PyYAML.

A READ IS NOT A COUNT. MEASURED on the test account's inventory reads
(var/inventory.json, about three dozen reads over a week; the numbers below
are rounded examples of the shapes seen): a strawberry count near 10,000 read
as about 1,000 on some reads (a leading "1" dropped, twice in a row once); a
royal_jelly count under 10 read once as 20-80 and then back; moon_charm 20 ->
70 -> 30. Diffing reads as they come counted strawberry about +10,000 gained
and -10,000 spent in one day when it really rose a few hundred; over all the
reads about 90,000 items "moved", about 60,000 settled. So a
change counts only once a later read says the new count holds (`settled`):
  - a run of up to MAX_RUN reads is a misread when the read after it is back
    near the count before it (within SPIKE_MIN or SPIKE_SHARE of it), each
    read of the run is farther from that count than the read after is, and
    the run is FAR from it (past SPIKE_*) or the read after is exactly it
    (diamond_egg 2 -> 3 -> 2 is a misread; blueberry 4,700 -> 4,500 -> 4,700
    is a spend and a gather);
  - the newest read waits for the next one (an hour, act/inventory's skip),
    two when it is far from the count before.
Real drops of this size stay: tickets 400 -> 40 -> 50 (spent at a shop),
treats 50,000 -> 10,000 (fed), blueberry 6,000 -> 4,700 -> 4,500.
ponytail: three misreads in a row, or a real gain spent within two reads
(royal_jelly 3 -> 16 -> 10 -> 1 may have been a buy and two rolls), are
taken for misreads; the report undercounts those rather than invent them.

A missing key is UNKNOWN, not 0 (inventory.json's own note): the series of an
item skips the reads that did not count it.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# the same sizes as act/inventory.SPIKE_* (a count's jump that is doubted);
# kept here so this module needs nothing past the stdlib
SPIKE_MIN = 5
SPIKE_SHARE = 0.5
MAX_RUN = 2


def _far(a: int, b: int) -> bool:
    return abs(b - a) > max(SPIKE_MIN, SPIKE_SHARE * a)


def series(reads) -> dict:
    """{slug: [(at, count), ...]} oldest first, the reads that counted it."""
    out: dict = {}
    rows = [e for e in reads or () if isinstance(e, (list, tuple)) and len(e) == 2
            and isinstance(e[1], dict)]
    for at, counts in sorted(rows, key=lambda e: float(e[0])):
        for slug, n in counts.items():
            if isinstance(n, int) and not isinstance(n, bool):
                out.setdefault(slug, []).append((float(at), n))
    return out


def settled(pts: list) -> list:
    """The points of one item's series that later reads confirm (the module
    note): misread runs dropped, the undecided newest read(s) left out."""
    if not pts:
        return []
    out = [pts[0]]
    i = 1
    while i < len(pts):
        a = out[-1][1]
        v = pts[i][1]
        decided, dropped = True, 0
        for run in range(1, MAX_RUN + 1):
            if i + run >= len(pts):
                # nothing after the run yet: a near read needs one later
                # read, a far one MAX_RUN
                decided = run > 1 and not _far(a, v)
                break
            if run > 1 and not all(_far(a, x) for _t, x in pts[i:i + run]):
                break
            c = pts[i + run][1]
            run_pts = pts[i:i + run]
            if abs(c - a) <= max(SPIKE_MIN, SPIKE_SHARE * a) and all(
                    abs(x - a) > abs(c - a) for _t, x in run_pts) and (
                    c == a or all(_far(a, x) for _t, x in run_pts)):
                dropped = run
                break
        if dropped:
            i += dropped
            continue
        if not decided:
            break
        out.append(pts[i])
        i += 1
    return out


def changes(reads) -> list:
    """[(slug, at, delta), ...]: each settled change, at the read that made it."""
    out = []
    for slug, pts in series(reads).items():
        kept = settled(pts)
        out += [(slug, b[0], b[1] - a[1]) for a, b in zip(kept, kept[1:]) if b[1] != a[1]]
    return sorted(out, key=lambda c: (c[1], c[0]))


def day_of(at: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(at))


def by_day(reads) -> dict:
    """{day: {slug: [gained, spent]}} (spent positive). A change between reads
    on two days counts on the later read's day."""
    out: dict = {}
    for slug, at, delta in changes(reads):
        row = out.setdefault(day_of(at), {}).setdefault(slug, [0, 0])
        row[0 if delta > 0 else 1] += abs(delta)
    return out


def _label(slug: str, labels: dict) -> str:
    return str(labels.get(slug) or slug.replace("_", " ").title())


def day_lines(day: dict, labels: dict) -> list:
    """'Blueberry +267 / -147' lines, the most moved first."""
    rows = sorted(day.items(), key=lambda kv: (-(kv[1][0] + kv[1][1]), kv[0]))
    out = []
    for slug, (got, spent) in rows:
        parts = ([f"+{got:,}"] if got else []) + ([f"-{spent:,}"] if spent else [])
        out.append(f"{_label(slug, labels)} {' / '.join(parts)}")
    return out


def load(path) -> tuple:
    """(reads, {slug: label}) from var/inventory.json; ([], {}) when unread."""
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
        labels = {k: (v or {}).get("label") or k for k, v in (body.get("items") or {}).items()}
        return list(body.get("reads") or []), labels
    except (OSError, ValueError, TypeError, AttributeError):
        return [], {}


def report_text(path, day: str | None = None) -> str:
    """The day's item report (today by default), for /report and the Stats page."""
    reads, labels = load(path)
    day = day or day_of(time.time())
    lines = day_lines(by_day(reads).get(day, {}), labels)
    if not reads:
        return "Items: the inventory has not been read yet."
    if not lines:
        return f"Items {day}: no change confirmed yet (a change counts once the next read agrees)."
    return f"Items {day} (from the inventory reads): " + ", ".join(lines)


def load_rare(path=None) -> dict:
    """{slug: label} of data/knowledge/rare_drops.yaml (PyYAML: the bot's venv)."""
    import yaml
    from ..datapaths import data
    path = path or data("knowledge", "rare_drops.yaml")
    body = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {str(k): str((v or {}).get("label") or k) for k, v in (body.get("items") or {}).items()}


def rare_drops(reads, rare: dict) -> list:
    """[(slug, gained, count)] for each rare item whose gain the NEWEST read
    settled: the changes with every read, less those without the newest --
    so each gain is told once, by the read that confirmed it.
    ponytail: a FIRST one, from none held, is never told -- the game lists
    no row at 0 and a read writes no count (unknown, not 0), so the series
    starts at the drop. MEASURED (review 2026-10-27): 11 of the 14 rare
    items had no count in any of the 36 kept reads, and star_jelly read 1
    on 11 reads and none since, so the next Star Jelly is
    silent. Not fixed by taking "no row" as 0: on 138 complete reads in the
    run logs 153 of 3,763 items counted on the reads
    before and after had no count and no unsure reading in between (about
    4%), some two reads running, which would tell false drops. Needs the
    read to say a row is truly gone first."""
    rows = [e for e in reads or () if isinstance(e, (list, tuple)) and len(e) == 2]
    if len(rows) < 2:
        return []
    rows = sorted(rows, key=lambda e: float(e[0]))
    before = set(changes(rows[:-1]))
    out = []
    for slug, at, delta in changes(rows):
        if slug in rare and delta > 0 and (slug, at, delta) not in before:
            count = next(n for t, n in series(rows)[slug] if t == at)
            out.append((slug, delta, count))
    return out


def rare_lines(path, rare: dict) -> list:
    """The run-log lines for the rare drops the newest read settled
    (scripts/telegram_alerts "rare drop:"): item names and counts only."""
    reads, _labels = load(path)
    return [f"rare drop: +{n:,} {rare.get(slug, slug)} (now {count:,})"
            for slug, n, count in rare_drops(reads, rare)]
