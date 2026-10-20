"""Disk: the low-disk guard for debug frames, and the retention policy.

WHY THIS EXISTS. MEASURED 2026-10-14 22:10: var/ held 179 GB with /home 88%
full, 146 GB of it var/incidents (5,167 folders of 150 full-HD JPEGs, ~30 MB
each, 4,479 of them mob-sighting) and 26 GB var/routes (637 attempts, one
frame per route step, ~41 MB an attempt). Nothing ever deleted any of it.

THE GUARD. `frames_allowed` is False while the disk under var has less than
LOW_DISK_GB free; the incident recorder and the route snapshots ask it before
writing (97% of var's bytes). It prints LOW_DISK_LINE once per process, which
the Telegram alerts service (scripts/telegram_alerts.py) turns into one alert.
It never raises: a guard that crashes the bot is worse than a full disk.

RETENTION is the OWNER'S SWITCH: storage.retention_gb, 0 (off) by default.
On, the oldest debug units (a folder or file directly under one of
DEBUG_ROOTS) go until those roots fit the budget. Never deleted: the newest
KEEP_NEWEST of each root, anything written in the last FRESH_S, a unit holding
a file named KEEP_MARK, and a unit whose name (or its stamp) the docs or the
code mention -- those are the measurements the comments cite.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

LOW_DISK_GB = 20.0
CHECK_EVERY_S = 60.0
LOW_DISK_LINE = "low disk:"

# The folders of saved debug frames. Not var/night (the run logs), not the
# json state files, not vlm_cache (a cache the bot reads).
DEBUG_ROOTS = ("incidents", "routes", "homing", "shoplook", "hotbar",
               "antchallenge", "respawn", "bears", "sprinkler_frames",
               "badges", "places", "planters", "frames2")
KEEP_NEWEST = 20
FRESH_S = 3600.0
KEEP_MARK = "KEEP"
PRUNE_EVERY_S = 6 * 3600.0
STAMP_FILE = ".retention-last"

_guard = {"at": -1e18, "ok": True, "told": False}


def _existing(path: Path) -> Path:
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def free_gb(path) -> float:
    return shutil.disk_usage(_existing(path)).free / 1e9


def floor_gb(path, min_free_gb: float = LOW_DISK_GB) -> float:
    """LOW_DISK_GB, or a tenth of a smaller disk: a 16 GB tmpfs (where the
    tests write) is not full just because it is small. /home is 831 GB."""
    return min(min_free_gb, shutil.disk_usage(_existing(path)).total / 1e10)


def frames_allowed(path, min_free_gb: float = LOW_DISK_GB,
                   clock=time.monotonic, state: dict | None = None) -> bool:
    """May a debug frame be written under `path`? Looks at the disk at most
    once a minute. Never raises (an unreadable disk counts as room)."""
    st = _guard if state is None else state
    now = clock()
    if now - st["at"] < CHECK_EVERY_S:
        return st["ok"]
    st["at"] = now
    try:
        free = free_gb(path)
        min_free_gb = floor_gb(path, min_free_gb)
    except OSError:
        st["ok"] = True
        return True
    st["ok"] = free >= min_free_gb
    if not st["ok"] and not st["told"]:
        st["told"] = True
        print(f"{LOW_DISK_LINE} {free:.1f} GB free under {_existing(path)} "
              f"(less than {min_free_gb:.0f} GB) -- the debug frames "
              f"(incidents, route snapshots) are off until there is room again",
              flush=True)
    return st["ok"]


def _size(entry: os.DirEntry) -> int:
    try:
        if not entry.is_dir(follow_symlinks=False):
            return entry.stat(follow_symlinks=False).st_size
        total = 0
        for top, _dirs, files in os.walk(entry.path):
            for name in files:
                try:
                    total += os.lstat(os.path.join(top, name)).st_size
                except OSError:
                    pass
        return total
    except OSError:
        return 0


STAMP = re.compile(r"\d{8}-\d{6}|\d{6}")


def referenced(repo: Path) -> set[str]:
    """Every word of the docs and the code that could name a debug unit:
    whole names ("233113-refused", "attempt-296", "black_bear-021910.jpg")
    and bare stamps ("var/incidents/233202", "20261004-223849-blender-").
    ponytail: a reference wrapped across lines or written as a glob is not
    seen; mark that folder KEEP."""
    words: set[str] = set()
    repo = Path(repo)
    for pattern in ("docs/**/*.md", "src/**/*.py", "scripts/**/*.py",
                    "tests/**/*.py"):
        for path in repo.glob(pattern):
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            words.update(re.findall(r"[\w.+-]+", text))
            words.update(re.findall(r"(?<!\d)\d{8}-\d{6}(?!\d)", text))
            words.update(re.findall(r"(?<!\d)\d{6}(?!\d)", text))
    return words


def _is_referenced(name: str, words: set[str]) -> bool:
    if name in words or Path(name).stem in words:
        return True
    m = STAMP.match(name)
    return bool(m and m.group(0) in words)


@dataclass
class Unit:
    root: str
    path: Path
    bytes: int
    mtime: float


@dataclass
class Plan:
    budget: int
    total: int = 0
    by_root: dict = field(default_factory=dict)
    doomed: list = field(default_factory=list)      # [Unit], oldest first
    protected: int = 0

    @property
    def freed(self) -> int:
        return sum(u.bytes for u in self.doomed)


def plan(var: Path, budget_gb: float, words: set[str] = frozenset(),
         now: float | None = None) -> Plan:
    """What would go to bring DEBUG_ROOTS under `budget_gb`. Reads only."""
    now = time.time() if now is None else now
    out = Plan(budget=int(budget_gb * 1e9))
    candidates: list[Unit] = []
    for root in DEBUG_ROOTS:
        try:
            entries = list(os.scandir(Path(var) / root))
        except OSError:
            continue
        units = []
        for e in entries:
            try:
                mtime = e.stat(follow_symlinks=False).st_mtime
            except OSError:
                continue
            units.append(Unit(root, Path(e.path), _size(e), mtime))
        out.by_root[root] = sum(u.bytes for u in units)
        out.total += out.by_root[root]
        units.sort(key=lambda u: u.mtime, reverse=True)
        for i, u in enumerate(units):
            if (i < KEEP_NEWEST or now - u.mtime < FRESH_S
                    or (u.path / KEEP_MARK).exists()
                    or _is_referenced(u.path.name, words)):
                out.protected += 1
            else:
                candidates.append(u)
    candidates.sort(key=lambda u: u.mtime)
    left = out.total
    for u in candidates:
        if left <= out.budget:
            break
        out.doomed.append(u)
        left -= u.bytes
    return out


def apply(p: Plan) -> int:
    """Delete what `plan` chose. Returns the bytes freed."""
    freed = 0
    for u in p.doomed:
        try:
            if u.path.is_dir() and not u.path.is_symlink():
                shutil.rmtree(u.path)
            else:
                u.path.unlink()
            freed += u.bytes
        except OSError:
            pass
    return freed


def maybe_prune(var: Path, repo: Path, budget_gb: float,
                every_s: float = PRUNE_EVERY_S) -> int | None:
    """The bot's call: prune when the switch is on and the last prune is
    `every_s` old. Returns bytes freed, or None when it did not run."""
    if not budget_gb or budget_gb <= 0:
        return None
    stamp = Path(var) / STAMP_FILE
    try:
        if time.time() - stamp.stat().st_mtime < every_s:
            return None
    except OSError:
        pass
    try:
        stamp.touch()
        p = plan(var, budget_gb, referenced(repo))
        return apply(p)
    except OSError:
        return None


def gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"
