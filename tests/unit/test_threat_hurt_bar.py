"""brain/threat.ThreatWatch.look: a mob near death, its bar almost all red,
is seen by nameplate.hurt_bars, not find_all -- and counted only when
HURT_BARS_LIVE (look-only until its logs are checked)."""
from pathlib import Path

import cv2

import hivemind
from hivemind.brain import threat

# var/incidents/20261015-234204-mob-sighting/149_t+10.8s.jpg rows 60-330,
# cols 1080-1560: "Rhino Beetle (Lvl 3)" over "HP: 1"
FRAME = (Path(hivemind.__file__).resolve().parents[2] / "tests" / "fixtures" / "threat"
         / "hurt-rhino-hp1.png")


def test_a_nearly_dead_mobs_bar_is_only_noted_while_look_only():
    frame = cv2.imread(str(FRAME))
    notes = []
    watch = threat.ThreatWatch(lambda: frame, on_ignored=notes.append)
    assert threat.HURT_BARS_LIVE is False
    assert watch.look() == []
    assert watch.hurt_bars_would == 1
    assert notes and notes[0].startswith("would: count hurt bar")


def test_live_it_counts(monkeypatch):
    frame = cv2.imread(str(FRAME))
    monkeypatch.setattr(threat, "HURT_BARS_LIVE", True)
    seen = threat.ThreatWatch(lambda: frame).look()
    assert [(p.x, p.y, p.w, p.h, p.kind) for p in seen] == [(92, 156, 300, 44, "mob")]
