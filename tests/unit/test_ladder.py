"""The Panda Bear's ladder found by sight (vision/ladder), on saved frames:
face-on from the nook one and two camera taps right (2026-10-06 03:09), and
not in the nook's own view, a fence, or the hive."""
from __future__ import annotations

from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
FIX = Path(__file__).resolve().parents[1] / "fixtures/ladder"


def _find(name):
    from hivemind.vision.ladder import find_ladder
    frame = cv2.imread(str(FIX / name))
    assert frame is not None, name
    return find_ladder(frame)


def test_the_ladder_is_found_face_on_from_the_nook():
    two = _find("nook-2taps.jpg")
    assert two is not None and 740 <= two.x <= 830 and 90 <= two.width <= 130
    # the one-tap view (at an angle) is not needed: the survey looks from two


@pytest.mark.parametrize("name", ["nook-no-ladder.jpg", "fence-not-ladder.jpg",
                                  "hive-not-ladder.jpg"])
def test_no_ladder_where_there_is_none(name):
    assert _find(name) is None


def test_the_aim_strafes_to_centre_then_steps_in_then_stops_at_its_foot():
    from hivemind.vision.ladder import Ladder, aim
    kw = dict(centre_px=70, ladder_studs=4.0, strafe_most=4.0, step_in=3.0, close_px=320)
    # the 03:09 view: 177 px left of the middle, 111 px wide -> left, ~6.4 studs, capped
    assert aim(Ladder(x=783, top=150, bottom=314, width=111), 1920, **kw) == ("a", 4.0)
    assert aim(Ladder(x=1100, top=150, bottom=314, width=111), 1920, **kw) == ("d", 4.0)
    assert aim(Ladder(x=1000, top=150, bottom=314, width=111), 1920, **kw) == ("w", 3.0)
    assert aim(Ladder(x=1060, top=100, bottom=900, width=320), 1920, **kw) is None
    assert aim(Ladder(x=1000, top=150, bottom=314, width=200), 1920, **kw) == ("w", 3.0)
    assert aim(Ladder(x=1050, top=150, bottom=314, width=400), 1920, **kw) is None
    assert aim(Ladder(x=1050, top=150, bottom=314, width=300), 1920, **kw) == ("d", 1.2)


def test_his_mark_steers_only_once_it_holds_its_place():
    from hivemind.vision.ladder import Ladder, climb_keys
    kw = dict(mark_px=120, hold_px=150, centre_px=70)
    # 03:08: one frame's "!" at the ladder's foot (no saved frame shows it) --
    # the push stays on the centred ladder
    centred = Ladder(x=967, top=74, bottom=382, width=186)
    assert climb_keys(500, None, centred, 1920, **kw) == ("w", False)
    assert climb_keys(500, 1530, centred, 1920, **kw) == ("w", False)
    # 23:46: his "!" at x 1540, 1528, 1539 as the climb rose -- held: in and
    # toward him (06:04: D alone walked into the wall beside the block's top)
    assert climb_keys(1528, 1540, None, 1920, **kw) == ("wd", True)
    assert climb_keys(1539, 1528, None, 1920, **kw) == ("wd", True)
    assert climb_keys(1539, 1528, None, 1920, side_px=400, **kw) == ("d", True)
    # nearer the middle: in, and toward him
    assert climb_keys(1200, 1180, None, 1920, **kw) == ("wd", True)
    assert climb_keys(1000, 990, None, 1920, **kw) == ("w", True)
    # no "!" and no ladder: straight
    assert climb_keys(None, 1539, None, 1920, **kw) == ("w", False)



def test_his_mark_is_found_close_up():
    # MEASURED 04:32: on top of his block his "!" grew past the far-view sizes
    import glob
    import cv2
    import pytest
    from hivemind.vision import questmarker
    frames = sorted(glob.glob(str(Path.home() / "Hivemind/var/shoplook/20261007-043*248794-leg7-climb1[13]-w.jpg")))
    if len(frames) < 2:
        pytest.skip("the 04:32 climb frames are not here")
    for f, x in zip(frames, (1554, 1750)):
        found = questmarker.find(cv2.imread(f))
        assert any(abs(m.x - x) <= 10 for m in found), (f, found)
