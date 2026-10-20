"""Phantom spots (brain/school.phantom) and the detector's confidence in the
token brain's trace and the school's lessons (2026-10-21)."""
import json
import pathlib
import types

import hivemind
from hivemind.act import chase
from hivemind.brain import school as sch
from hivemind.brain.tokenbrain import TokenBrain

ROOT = pathlib.Path(hivemind.__file__).resolve().parents[2]


def _write(tmp_path, rows):
    tmp_path.mkdir(parents=True, exist_ok=True)
    with (tmp_path / "lessons.jsonl").open("w", encoding="utf-8") as fh:
        for i, (x, y, conf, reached) in enumerate(rows):
            fh.write(json.dumps({"id": str(i), "at": float(i), "kind": "honey",
                                 "confidence": conf, "x": x, "y": y,
                                 "outcome": "nothing" if reached else "unknown",
                                 "evidence": "reached it" if reached else sch.NEVER}) + "\n")
    return sch.School(tmp_path)


def test_sixty_misses_flag_the_cell_fortynine_do_not(tmp_path):
    s = _write(tmp_path / "a", [(1170, 610, 1.0, False)] * 60)
    assert s.phantom(1199, 639) == (60, 0.0)
    assert s.phantom(1240, 610) is None            # the next cell
    assert _write(tmp_path / "b", [(1170, 610, 1.0, False)] * 49).phantom(1170, 610) is None


def test_reached_often_enough_is_not_a_phantom(tmp_path):
    rows = [(10, 10, 1.0, False)] * 50 + [(10, 10, 1.0, True)] * 10    # 17% reached
    assert _write(tmp_path, rows).phantom(10, 10) is None


def test_seen_once_and_old_lessons_do_not_count(tmp_path):
    assert _write(tmp_path / "a", [(10, 10, 0.5, False)] * 80).phantom(10, 10) is None
    old = [(10, 10, 1.0, False)] * 60 + [(500, 500, 1.0, True)] * sch.PHANTOM_WINDOW
    assert _write(tmp_path / "b", old).phantom(10, 10) is None


def test_finish_updates_the_cells(tmp_path):
    s = _write(tmp_path, [(10, 10, 1.0, False)] * 49)
    assert s.phantom(10, 10) is None
    s._append(sch.Lesson(id="x", at=0.0, kind="honey", confidence=1.0, x=10, y=10,
                         evidence=sch.NEVER))
    assert s.phantom(10, 10) == (50, 0.0)


def test_trace_carries_the_detector_and_the_lesson_keeps_it(tmp_path):
    t = types.SimpleNamespace(id=1, kind="honey", matches=2, x=900, y=500,
                              detector_confidence=0.8123)
    c = next(c for c in TokenBrain().score([t], (960, 669), (960, 669), 0.0) if c.track_id == 1)
    assert c.trace["detector"] == 0.812
    lesson = sch.Lesson(id="1", at=0.0, kind="honey", confidence=1.0, x=1, y=1,
                        detector_confidence=0.812)
    assert json.loads(json.dumps(lesson.__dict__))["detector_confidence"] == 0.812


def test_a_sure_detector_is_exempt(tmp_path):
    s = _write(tmp_path, [(10, 10, 1.0, False)] * 60)
    assert s.phantom(10, 10, 0.96) is None
    assert s.phantom(10, 10, 0.6) == (60, 0.0)


def test_look_only_wiring():
    assert chase.PHANTOM_SUPPRESS_LIVE is False
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    i = src.index("ghost = school.phantom(tx, ty, det)")
    block = src[i:i + 600]
    assert "chase would: skip phantom" in block
    assert block.index("chase would") < block.index("if chase.PHANTOM_SUPPRESS_LIVE")
    assert 'detector_confidence=decision.target.trace.get("detector")' in src


def test_a_lesson_that_cannot_say_whether_it_got_there_does_not_hide_a_phantom(tmp_path):
    # 60 misses and 40 owner takeovers (`drop`: "unknown", not NEVER)
    s = _write(tmp_path, [(10, 10, 1.0, False)] * 60)
    for i in range(40):
        s.drop(sch.Lesson(id=f"t{i}", at=0.0, kind="honey", confidence=1.0, x=10, y=10),
               "the owner took the controls")
    assert s.phantom(10, 10) == (60, 0.0)
