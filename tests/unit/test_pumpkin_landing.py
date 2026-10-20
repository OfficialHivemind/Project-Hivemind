"""A-PUMPKIN: the Pumpkin red-cannon flight's landing check (act/routes
`landing_check`) and how an off-field landing is booked (brain/skills
`settle_trip`'s `landing_outcome`)."""
from hivemind.act import routes
from hivemind.brain import skills

EDGE = 0.08          # data/models/fieldsense.json edge.threshold


def test_off_field_names_the_walk_and_stays_look_only():
    assert routes.PUMPKIN_LANDING_LIVE is False
    inside, line = routes.landing_check(routes.PUMPKIN_FLIGHT, 0.0, True, EDGE)
    assert inside is False
    assert line.startswith("pumpkin landing would: take natro_out_pumpkin")
    assert "look-only" in line


def test_in_field_and_unreadable():
    inside, line = routes.landing_check(routes.PUMPKIN_FLIGHT, 0.6, True, EDGE)
    assert inside is True and "in the field" in line
    assert routes.landing_check(routes.PUMPKIN_FLIGHT, 0.0, False, EDGE)[0] is None
    assert routes.landing_check(routes.PUMPKIN_FLIGHT, 0.0, True, None)[0] is None


def _settle(**run):
    out = skills.settle_trip([{"route": routes.PUMPKIN_FLIGHT, "seconds": 20.0, **run}],
                             aim="pumpkin", credited="pumpkin", fields={"pumpkin"},
                             travel_runs=1)
    return out[0]["outcome"]


def test_off_field_landing_is_not_booked_landed():
    assert _settle() == "landed"
    assert _settle(landing_outcome="unknown") == "unknown"
    assert _settle(landing_outcome="elsewhere") == "elsewhere"
