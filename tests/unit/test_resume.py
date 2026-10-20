"""ROADMAP S14: var/resume.json, what a restart would otherwise forget (brain/resume)."""
import json
import re
from pathlib import Path

import hivemind
from hivemind.brain import resume as r
from hivemind.brain.questclock import QuestClock

ROOT = Path(hivemind.__file__).resolve().parents[2]
NOW = 1_800_000_000.0
HERE = {"server": "8eff09", "account": "ExamplePlayer"}


def write(tmp_path, **parts):
    path = tmp_path / "resume.json"
    r.save(path, now=NOW - 600, **HERE, **parts)
    return path


def test_round_trip_keeps_every_part(tmp_path):
    path = write(tmp_path, quests={"last_at": NOW - 900, "due_at": NOW + 3000, "why": "slow"},
                 balloon={"at": NOW - 700, "empty": 2}, ant={"at": NOW - 800})
    got, said = r.load(path, now=NOW, **HERE)
    assert got == {"quests": {"last_at": NOW - 900, "due_at": NOW + 3000, "why": "slow"},
                   "balloon": {"at": NOW - 700, "empty": 2}, "ant": {"at": NOW - 800}}
    assert "same server" in said and "10 min ago" in said
    assert not list(tmp_path.glob(".resume.json.*"))     # atomic: no temp file left


def test_stale_and_future_files_are_ignored(tmp_path):
    path = write(tmp_path, ant={"at": NOW})
    assert r.load(path, now=NOW + r.MAX_AGE_S, **HERE)[0] == {}
    got, said = r.load(path, now=NOW - 3600, **HERE)        # saved "in the future"
    assert got == {} and "ignored" in said


def test_corrupt_files_never_raise(tmp_path):
    path = tmp_path / "resume.json"
    assert r.load(path, now=NOW, **HERE) == ({}, "no resume file (a first start)")
    for text in ("{not json", "[]", "null", json.dumps({"version": 99, "saved_at": NOW}),
                 json.dumps({"version": r.VERSION, "saved_at": "soon"}),
                 json.dumps({"version": r.VERSION}), "\x00\xff"):
        path.write_text(text)
        got, said = r.load(path, now=NOW, **HERE)
        assert got == {} and "ignored" in said, text
    # one bad part drops only itself
    path.write_text(json.dumps({"version": r.VERSION, "saved_at": NOW, **HERE,
                                "quests": {"last_at": "x", "due_at": None},
                                "balloon": {"at": True, "empty": 0}, "ant": {"at": NOW - 5}}))
    got, said = r.load(path, now=NOW, **HERE)
    assert got == {"ant": {"at": NOW - 5}}
    assert "quest clock was malformed" in said and "balloon was malformed" in said


def test_another_account_or_server(tmp_path):
    path = write(tmp_path, balloon={"at": NOW - 60, "empty": 0}, ant={"at": NOW - 60})
    assert r.load(path, now=NOW, server="8eff09", account="ExampleAlt")[0] == {}
    got, said = r.load(path, now=NOW, server="abc123", account="ExamplePlayer")
    assert got == {"ant": {"at": NOW - 60}} and "new server" in said
    assert "balloon" not in r.load(path, now=NOW, server="", account="ExamplePlayer")[0]


def test_quest_clock_survives_a_restart(tmp_path):
    """The old process's clock, saved and read back, lets the new one wait."""
    old = QuestClock(base=1200, cap=7200, clock=lambda: NOW - 900)
    old.last_at, old.due_at, old.why = NOW - 900, NOW + 3000, "nothing moved"
    path = write(tmp_path, quests={"last_at": old.last_at, "due_at": old.due_at, "why": old.why})
    part = r.load(path, now=NOW, **HERE)[0]["quests"]
    assert r.quest_skip(part, file_read_at=NOW - 900, now=NOW)
    assert not r.quest_skip(part, file_read_at=NOW - 60, now=NOW)       # a newer read on file
    assert not r.quest_skip(part, file_read_at=0.0, now=NOW)            # no read on file
    assert not r.quest_skip(part, file_read_at=NOW - 900, now=NOW + 3001)  # due already
    assert not r.quest_skip(None, file_read_at=NOW - 900, now=NOW)
    due_now = dict(part, due_at=0.0)                  # at_next_convert: read at once
    assert not r.quest_skip(due_now, file_read_at=NOW - 900, now=NOW)


def test_run_farm_reads_and_writes_it():
    farm = (ROOT / "scripts" / "run_farm.py").read_text()
    assert "from hivemind.brain import resume as resume_mod" in farm
    assert 'RESUME_FILE = ROOT / "var" / "resume.json"' in farm
    # written at the trip's safe point: after the post-convert errand
    hook = farm[farm.index("def _resources_timed_errand"):]
    hook = hook[:hook.index("\n        def ", 10)]
    assert re.search(r"finally:.*save_resume\(\)", hook, re.S)
    # read once, before the start-up quest read, which consults it
    start = farm.index('read_the_quests("the run is starting", skip_recent=True)')
    assert farm.rindex("resume_mod.load(RESUME_FILE", 0, start) > start - 1500
    assert "resume_mod.quest_skip(resumed, last, now)" in farm
    # never the position or the bag
    save = farm[farm.index("def save_resume"):farm.index("def _resources_timed_errand")]
    assert "pollen" not in save and "pose" not in save
