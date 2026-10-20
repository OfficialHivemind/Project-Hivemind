"""Backups of the bot's brain (ROADMAP S5): one dated copy a day, to a folder
the OWNER picks (storage.backup_dir, empty = off, the default).

WHAT IS THE BRAIN. What the bot learned and cannot get back from the repo:
  * the state files directly under var (skill_stats.json = the skills,
    quests.json, field_notes.json, world_map.json, measured_routes.yaml,
    trips.jsonl ...): .json, .jsonl and .yaml only
  * var/fieldsense: the field classifier's live-labelled shards (the model it
    trains itself; the shipped data/models are in git)
  * data/knowledge: shipped in git, BUT brain/knowledge.learn appends to
    data/knowledge/learned.yaml while it plays, and a deploy writes data/
NOT the debug frames (incidents, routes ...: telemetry/storage's job), not
vlm_cache (a cache), not var/night (the run logs).

Each copy is <dir>/brain-YYYYmmdd-HHMMSS; the newest KEEP stay, older ones
go (only folders named brain-*, nothing else in the owner's folder). A file
over MAX_FILE_MB is skipped and named: sizes are NOT measured on the live
tree, the cap (ESTIMATED) only stops one runaway log from filling the disk.
It never raises: a backup that crashes the bot is worse than no backup.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

KEEP = 7
EVERY_S = 24 * 3600.0
MAX_FILE_MB = 200          # ESTIMATED, see above
SUFFIXES = (".json", ".jsonl", ".yaml")
PREFIX = "brain-"


def _sources(var_root: Path, data_root: Path) -> list[tuple[Path, Path]]:
    """(source file, path inside the backup) for everything that is brain."""
    out = [(p, Path("var") / p.name) for p in sorted(var_root.glob("*"))
           if p.is_file() and p.suffix in SUFFIXES]
    for root, name in ((var_root / "fieldsense", "var/fieldsense"),
                       (data_root / "knowledge", "data/knowledge")):
        out += [(p, Path(name) / p.relative_to(root))
                for p in sorted(root.rglob("*")) if p.is_file()]
    return out


def _copies(dest: Path) -> list[Path]:
    return sorted(p for p in dest.glob(PREFIX + "*") if p.is_dir())


def maybe_backup(var_root, data_root, dest, now: float | None = None) -> str | None:
    """Copy the brain to `dest` unless the newest copy is under EVERY_S old.
    Returns the line to print, or None when nothing was due."""
    try:
        if not str(dest or "").strip():
            return None
        var_root, data_root = Path(var_root), Path(data_root)
        dest = Path(dest).expanduser()
        now = time.time() if now is None else now
        if dest.resolve().is_relative_to(var_root.resolve()):
            return f"backup: {dest} is inside var, not a second folder: skipped"
        copies = _copies(dest) if dest.is_dir() else []
        if copies and now - copies[-1].stat().st_mtime < EVERY_S:
            return None
        folder = dest / (PREFIX + time.strftime("%Y%m%d-%H%M%S", time.localtime(now)))
        tmp = dest / ("." + folder.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        count, size, skipped = 0, 0, []
        for src, rel in _sources(var_root, data_root):
            n = src.stat().st_size
            if n > MAX_FILE_MB * 1e6:
                skipped.append(src.name)
                continue
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tmp / rel)
            count, size = count + 1, size + n
        tmp.rename(folder)        # a half copy never looks like a backup
        copies = _copies(dest)
        for old in copies[:-KEEP]:
            shutil.rmtree(old, ignore_errors=True)
        return (f"backup: {count} brain files ({size / 1e6:.1f} MB) to "
                f"{folder}" + (f"; too big, skipped: {', '.join(skipped)}"
                               if skipped else ""))
    except Exception as err:          # never raises (see the docstring)
        return f"backup: failed ({err})"
