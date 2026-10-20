"""An errand's copy of a natro_out_* route is a walk out too (brain/threat
OUTBOUND_PREFIX): MEASURED 2026-10-13 20:39 and 23:24, two Blender walks cut
by far bars."""
import numpy as np

from hivemind.brain.threat import ThreatWatch


def _far_bar_frame():
    far = np.zeros((1080, 1920, 3), np.uint8)
    far[220:234, 160:240] = (60, 230, 60)            # a mob bar ~870 px off centre
    for gx in range(186, 206, 6):
        far[223:231, gx:gx + 2] = (245, 245, 245)
    return far


def test_a_far_bar_does_not_cut_the_errands_copied_walks_out():
    far = _far_bar_frame()
    for route in ("to_the_blender", "to_the_pro_shop", "commando_via", "natro_out_spider"):
        watch = ThreatWatch(lambda: far, skip_top=0, clock=lambda: 0.0,
                            route_name=lambda r=route: r, bag_is_empty=lambda: True)
        assert watch() is False and watch.far_bars_ignored == 1, route
    home = ThreatWatch(lambda: far, skip_top=0, clock=lambda: 0.0,
                       route_name=lambda: "natro_home_spider", bag_is_empty=lambda: True)
    assert home() is True, "the walk home still counts every bar"
