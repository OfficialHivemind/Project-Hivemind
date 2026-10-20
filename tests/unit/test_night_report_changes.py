"""ROADMAP S6: the morning report stays one readable page -- the hand-written
var/night/changes.md comes in only when fresh, and only its newest sections.
FAKE notes, never the owner's."""
import importlib.util
import os
from pathlib import Path

import hivemind

REPO = Path(hivemind.__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("night_report_s6", REPO / "scripts" / "night_report.py")
nr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nr)

NOW = 2_000_000_000.0


def notes(tmp_path: Path, n: int, age_s: float = 60.0) -> Path:
    path = tmp_path / "changes.md"
    path.write_text("intro line\n\n" + "".join(f"## note {i}\nbody {i}\n\n" for i in range(n)))
    os.utime(path, (NOW - age_s, NOW - age_s))
    return path


def test_fresh_notes_keep_only_the_newest_sections(tmp_path):
    out = "\n".join(nr.changes_section(notes(tmp_path, 20), NOW))
    assert out.startswith("## What I changed while you slept")
    assert "intro line" in out
    assert "12 older note(s)" in out
    assert "## note 11\n" not in out and "## note 12\n" in out and "## note 19\n" in out


def test_few_notes_all_shown_without_the_older_line(tmp_path):
    out = "\n".join(nr.changes_section(notes(tmp_path, 3), NOW))
    assert "older note" not in out and "## note 0\n" in out


def test_stale_or_missing_notes_are_left_out(tmp_path):
    assert nr.changes_section(notes(tmp_path, 3, age_s=nr.CHANGES_FRESH_S + 1), NOW) == []
    assert nr.changes_section(tmp_path / "missing.md", NOW) == []
