"""run_farm prices a field the planner's way: recent trips, not the lifetime
figure (2026-10-20, Bamboo 3,375/s lifetime against 29,165/s recent)."""
from pathlib import Path

import hivemind

REPO = Path(hivemind.__file__).resolve().parents[2]


def test_every_run_farm_rate_lookup_goes_through_field_rate():
    src = (REPO / "scripts" / "run_farm.py").read_text()
    assert "measured_rate(notes.known(" not in src
    body = src[src.index("        def field_rate(name):"):]
    body = body[:body.index("\n\n")]
    assert "planner._trips_for(name)" in body and "trips=trips" in body

