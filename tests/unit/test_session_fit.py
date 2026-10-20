"""The nested session's host window is sized to the output (2026-10-21: a
relaunch's window opened 1280x720 and the HUD reader found nothing)."""
from pathlib import Path

import hivemind
from hivemind.platform import session

REPO = Path(hivemind.__file__).resolve().parents[2]


def test_the_size_script_sets_the_session_size():
    body = session.SIZE_SCRIPT % {"pid": 42, "cls": "aquamarine", "tag": "T",
                                  "width": 1920, "height": 1080}
    assert "w.pid == 42" in body and 'resourceClass == "aquamarine"' in body
    assert "width: 1920, height: 1080" in body


def test_bootstrap_fits_the_window_after_handing_back_focus():
    src = (REPO / "src" / "hivemind" / "act" / "bootstrap.py").read_text()
    assert src.index("session.give_back_focus()") < src.index('getattr(session, "fit_host_window"')
