"""An errand that ends standing at a field's gather spot walks that field's own
route home (nav.journey.errand_home), not the hive area's search. MEASURED
2026-10-14 00:07-00:10 (var/night/run-984.log): a Paper Planter placed in
Bamboo, the respawn refused for the bag, and the hive area's homing ended in a
field's wall and a respawn that lost 554,477 pollen."""
from hivemind.nav.journey import errand_home

HOME = {"bamboo": ["natro_home_bamboo"]}.get
STOOD = ("bamboo", 7, 100.0)          # (field, routes run, monotonic time)


def test_still_where_the_errand_stood_walks_the_fields_route_home():
    field, homeward = errand_home(STOOD, 7, -1e9, HOME)
    assert field == "bamboo"
    assert homeward.routes == ["natro_home_bamboo"] and not homeward.doubtful


def test_moved_since_or_no_route_home_keeps_todays_homing():
    assert errand_home(STOOD, 8, -1e9, HOME) is None        # a route ran since
    assert errand_home(STOOD, 7, 150.0, HOME) is None       # a death after it
    assert errand_home(("clover", 7, 100.0), 7, -1e9, HOME) is None
    assert errand_home(None, 7, -1e9, HOME) is None
