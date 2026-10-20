"""A planter seek that died on the way stops (run_farm `seek_the_planter`):
the signs it reads, on the real frames of 2026-10-13 09:32 (a Werewolf at
the Pine Tree's Paper Planter)."""
import shutil
from pathlib import Path

import cv2
import pytest

from hivemind.vision import feed as feed_mod
from hivemind.vision import screenstate as ss

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "planter"


def died(frame) -> bool:
    strip = feed_mod.strip(frame)
    fed = feed_mod.read_text(strip) if strip is not None else ""
    return bool(ss.make_honey_present(frame) or "youdi" in "".join(str(fed).lower().split()))


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="reads through tesseract; none on PATH")
def test_the_respawn_after_a_death_at_the_planter_is_seen():
    # THE FEED'S WORDS, NOT THE PIXELS. MEASURED 2026-10-21 (Linux, tesseract
    # 5, OpenCV 5.0.0): make_honey_present is False on this frame, and the
    # death is seen only because the feed strip (89x345) reads "... You died!
    # Your bees must recover at the hive." Red on the Windows PC with no
    # tesseract; the installer bundles it.
    assert died(cv2.imread(str(FIX / "seek-died-push1.jpg")))


def test_a_live_seek_beside_the_mobs_is_not_a_death():
    assert not died(cv2.imread(str(FIX / "seek-alive-turn6.jpg")))
