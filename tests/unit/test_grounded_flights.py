"""A field in GROUNDED_FLIGHTS walks: its flight is never a candidate."""
from pathlib import Path

import hivemind

REPO = Path(hivemind.__file__).resolve().parents[2]


def test_strawberry_is_walked_and_choose_out_drops_its_flight():
    src = (REPO / "scripts" / "run_farm.py").read_text()
    assert 'GROUNDED_FLIGHTS = {"strawberry"}' in src
    body = src[src.index("        def choose_out("):]
    body = body[:body.index("candidates.append((flight.name, flight.studs))")]
    assert "if field in GROUNDED_FLIGHTS:\n                flight = None" in body
    paths = (REPO / "data" / "world" / "natro_paths.yaml").read_text()
    assert "- name: natro_out_strawberry\n" in paths   # the walk it falls back to


def test_the_bamboo_flight_waits_out_speed_buffs_like_an_errand():
    """2026-10-20: missed Bamboo flights launched under a bear morph and glided
    low into a ledge; the flight now waits like an errand's (wait_out_the_morph)."""
    src = (REPO / "scripts" / "run_farm.py").read_text()
    assert 'BUFF_WAIT_FLIGHTS = {"natro_out_bamboo_via_red_cannon"}' in src
    body = src[src.index("        def wait_out_the_morph("):]
    body = body[:body.index("\n        def ")]
    assert "flight_waits = name in BUFF_WAIT_FLIGHTS" in body
    assert "if not (home or errand_walk or flight_waits):" in body
    assert "wait_out_the_morph(name)" in src            # before_route calls it for every route
