"""R4 (act/home_align): the aligned walk home is the SAME route with its
first legs leaned -- never an extra walk before it -- and is swapped in
only while the A/B switch is on."""
from hivemind.act import home_align
from hivemind.nav.router import Router


def test_aligned_route_is_the_route_with_leaned_first_legs():
    router = Router()
    home_align.register(router)
    for route, first in home_align.ALIGN_FIRST.items():
        edge = next(e for e in router.edges if e.name == route)
        steps = router.routines[f"{route}_aligned"].steps
        assert len(steps) == len(edge.steps)                       # nothing walked twice
        assert [s.get("keys") for s in steps] == [s.get("keys") for s in edge.steps]
        assert all(s.get("lean") for s in steps[:first] if s.get("op") == "walk")
        assert steps[first:] == edge.steps[first:]
        assert not edge.steps[0].get("lean")                       # the original untouched


def test_swap_only_when_on():
    router = Router()
    home_align.register(router)
    routes = ["natro_home_cactus", "natro_home_bamboo"]
    old = home_align.HOME_ALIGN
    try:
        home_align.HOME_ALIGN = "on"
        assert home_align.swap(routes, router) == ["natro_home_cactus_aligned", "natro_home_bamboo"]
        home_align.HOME_ALIGN = "off"
        assert home_align.swap(routes, router) == routes
    finally:
        home_align.HOME_ALIGN = old
