"""Q10, the Red Portal (run_farm RED_PORTAL_*): a look-only survey from inside
the Red HQ on the booster walk -- it reads after each leg and stops on the
portal's own words; nothing is pressed (E a stud off the pad opens the shop)."""
from __future__ import annotations

import pathlib
import re

import hivemind

FARM = (pathlib.Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py").read_text()


def test_the_portal_survey_is_read_only_and_must_read_the_portal():
    call = FARM[FARM.index("(RED_PORTAL_SURVEY, red_portal_survey"):]
    call = call[:call.index("),\n") + 2]
    assert "survey_by_walk(" in call and "must_read=True" in call
    assert re.search(r'stop_on=\("portal", "teleport"\)', call)
    assert 'RED_PORTAL_VIA = "natro_out_red_field_booster"' in FARM
    assert "RED_PORTAL_UPTO = 23" in FARM
