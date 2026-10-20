"""A bee's card left open is not a mob (brain/threat._off_a_bee_card).
MEASURED 2026-10-06 05:05: a Commander Bee card over the pad, its green Energy
bar read as "mob health bar 124x25 at (965, 503)", every walk cut short."""
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
FIX = Path(__file__).resolve().parents[1] / "fixtures" / "threat" / "bee-card-open.jpg"


def test_the_open_cards_energy_bar_is_no_threat():
    # the bar where the live run saw it (the saved JPEG's colours no longer
    # make it); the card's red X is read off the frame itself
    from hivemind.brain import threat
    from hivemind.vision.nameplate import Nameplate
    frame = cv2.imread(str(FIX))
    energy = Nameplate(x=903, y=491, w=124, h=25)          # centre (965, 503)
    afield = Nameplate(x=1440, y=290, w=124, h=25)         # a real mob, off the card
    kept = threat._off_a_bee_card([energy, afield], frame)
    assert kept == [afield]
    blank = frame.copy()
    blank[:] = 0                                           # no card: nothing dropped
    assert threat._off_a_bee_card([energy, afield], blank) == [energy, afield]
