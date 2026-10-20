"""The Ant Challenge HUD reader and the Giant Ant rounds (ROADMAP Q2)."""
from pathlib import Path

import hivemind
import pytest

from hivemind.vision import antarena

ROOT = Path(hivemind.__file__).resolve().parents[2]


def test_parse_reads_the_tails_the_swarm_leaves():
    # MEASURED reads, var/antchallenge/20261026-185454 (look010, look030, look039)
    hud = antarena.parse("Time: 4:29\nund:5\nore: 19")
    assert (hud.time_left, hud.round, hud.score) == (269, 5, 19)
    hud = antarena.parse("Time: 3:39\noaund:9\nas 33")
    assert (hud.time_left, hud.round, hud.score) == (219, 9, None)
    hud = antarena.parse("HP: 1,227\nk. 'nd:1\nf")
    assert hud.time_left is None and not hud.giant
    assert antarena.parse("Giant Ant (Lvl 5)").giant


def test_tracker_believes_only_steps_forward():
    t = antarena.RoundTracker()
    assert t.see(antarena.Hud(round=2, score=1))
    assert not t.see(antarena.Hud(round=48))       # a misread (MEASURED, one game)
    assert t.see(antarena.Hud(round=3))
    assert not t.see(antarena.Hud(round=1))        # "nd:1" with HP over it
    assert not t.see(antarena.Hud(round=9))
    assert t.round == 3 and t.score == 1


def test_giant_rounds():
    assert [r for r in range(0, 17) if antarena.giant_round(r)] == [5, 6, 10, 11, 15, 16]


def test_side_step_ships_look_only():
    text = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert "\nANT_KITE_LIVE = True\n" in text
    assert "Ant Challenge would: step side to side" in text


def test_reads_a_real_round():
    frame_path = Path.home() / "Hivemind/var/antchallenge/20261026-185454/0100.8-look038.jpg"
    if not frame_path.exists():
        pytest.skip("owner's frames only")
    import cv2
    hud = antarena.read(cv2.imread(str(frame_path)))
    assert hud.round == 10
