"""ROADMAP A28 (a death the feed has since contradicted) and A25 (frames of a
minute without the HUD)."""
import functools
from types import SimpleNamespace

import numpy as np

from hivemind.brain import alive, farm
from hivemind.telemetry.incidents import IncidentRecorder


class Notes:
    def __init__(self, field, seen_at):
        self.field, self.seen_at, self.asked = field, seen_at, None

    def field_since(self, when):
        self.asked = when
        return self.field if self.seen_at >= when else None


def test_feed_naming_a_field_well_after_the_death_overrules_it():
    # run-1025: death read at 06:04:38, feed named Pine Tree from 06:04:50.
    assert alive.field_after_death(Notes("pine_tree", 112.0), 100.0) == "pine_tree"


def test_feed_lines_still_fading_from_before_the_death_do_not():
    notes = Notes("pine_tree", 103.0)
    assert alive.field_after_death(notes, 100.0) is None
    assert notes.asked == 100.0 + alive.FEED_AFTER_DEATH_SECONDS


def test_no_field_since_means_the_death_stands():
    assert alive.field_after_death(Notes(None, 0.0), 100.0) is None


def _recorder(tmp_path):
    rec = IncidentRecorder(tmp_path)
    rec.push(np.zeros((8, 8, 3), np.uint8))
    return rec


def test_keep_newest_writes_one_folder(tmp_path):
    rec = _recorder(tmp_path)
    assert rec.keep_newest("x-hud-missing", "t+00s", note="why")
    rec.keep_newest("x-hud-missing", "t+10s", note="ignored")
    out = tmp_path / "x-hud-missing"
    assert sorted(p.name for p in out.iterdir()) == ["reason.txt", "t+00s.jpg", "t+10s.jpg"]
    assert (out / "reason.txt").read_text() == "why\n"


def _waiter(tmp_path, hud_back_at=None):
    now = [0.0]
    gone = farm.Reading(state=farm.Read.NO_HUD)
    back = farm.Reading(state=farm.Read.OK, value=1)
    stub = SimpleNamespace(
        clock=lambda: now[0],
        sleep=lambda s: now.__setitem__(0, now[0] + s),
        poll_seconds=1.0, hud_wait_seconds=60.0,
        _stopped=lambda: False, _emit=lambda e: None,
        incidents=_recorder(tmp_path),
        hud=SimpleNamespace(pollen=lambda: back if hud_back_at is not None
                            and now[0] >= hud_back_at else gone))
    stub._keep_hud_frame = functools.partial(farm.FarmLoop._keep_hud_frame, stub)
    return stub


def _kept(tmp_path):
    return sorted(p.name for d in tmp_path.iterdir() for p in d.glob("*.jpg"))


def test_a_minute_without_the_hud_keeps_a_frame_at_each_mark(tmp_path):
    stub = _waiter(tmp_path)
    assert farm.FarmLoop._wait_for_hud(stub, farm.Report()) is False
    assert _kept(tmp_path) == ["t+00s.jpg", "t+10s.jpg", "t+30s.jpg", "t+55s.jpg"]


def test_hud_back_early_stops_keeping_frames(tmp_path):
    stub = _waiter(tmp_path, hud_back_at=12.0)
    assert farm.FarmLoop._wait_for_hud(stub, farm.Report()) is True
    assert _kept(tmp_path) == ["t+00s.jpg", "t+10s.jpg"]
