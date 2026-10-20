"""The mob policy: it cuts a walk short and does nothing else."""
from __future__ import annotations

import numpy as np

from hivemind.brain.threat import ThreatWatch
from hivemind.vision.nameplate import Nameplate


def with_mob():
    """A health bar as this client draws it: UI green with white text inside."""
    frame = np.zeros((400, 600, 3), np.uint8)
    frame[200:214, 300:380] = (60, 230, 60)
    for gx in range(326, 346, 6):
        frame[203:211, gx:gx + 2] = (245, 245, 245)
    return frame


def with_disc():
    """The red attack disc over the character, and no bar at all."""
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[:] = (60, 140, 60)
    import cv2
    cv2.circle(frame, (960, 600), 350, (40, 40, 230), -1)
    return frame


def empty():
    return np.zeros((400, 600, 3), np.uint8)


def test_an_empty_field_never_interrupts_a_walk():
    watch = ThreatWatch(empty, skip_top=0)
    assert [watch() for _ in range(20)] == [False] * 20
    assert watch.reactions == 0


def test_a_mob_on_screen_cuts_the_walk_short():
    seen = []
    watch = ThreatWatch(with_mob, on_sighting=lambda p, n: seen.append(n),
                        skip_top=0, clock=lambda: 0.0)
    assert watch() is True
    assert watch.reactions == 1
    assert seen and "health bar" in seen[0]


def test_it_will_not_interrupt_every_slice_while_a_mob_lingers():
    """Otherwise one insect stops the bot gathering at all."""
    clock = [0.0]
    watch = ThreatWatch(with_mob, skip_top=0, clock=lambda: clock[0],
                        cooldown=8.0)
    assert watch() is True
    for step in range(1, 8):
        clock[0] = float(step)
        assert watch() is False, f"interrupted again after {step}s"
    clock[0] = 9.0
    assert watch() is True
    assert watch.reactions == 2
    assert watch.sightings == 9        # every look still counted


def test_a_broken_capture_is_not_a_mob():
    def boom():
        raise RuntimeError("capture failed")
    assert ThreatWatch(boom, skip_top=0)() is False
    assert ThreatWatch(lambda: None, skip_top=0)() is False


def test_a_reporting_failure_does_not_stop_the_reaction():
    def bad(plates, note):
        raise RuntimeError("the incident writer is broken")
    watch = ThreatWatch(with_mob, on_sighting=bad, skip_top=0,
                        clock=lambda: 0.0)
    assert watch() is True, "the walk must still be cut short"


def test_it_reports_what_it_saw():
    got = {}
    watch = ThreatWatch(with_mob,
                        on_sighting=lambda p, n: got.update(plates=p, note=n),
                        skip_top=0, clock=lambda: 0.0)
    watch()
    assert isinstance(got["plates"][0], Nameplate)
    assert "cutting this walk short" in got["note"]


def test_a_disc_alone_is_not_a_threat():
    """DESIGN 8di: 1 of 363 disc-only reactions in attempts 300-344 had a
    hostile bar in its last 5 s; the rest were the bees' own gathering."""
    seen, ignored = [], []
    watch = ThreatWatch(with_disc, on_sighting=lambda p, n: seen.append(n),
                        on_ignored=ignored.append, skip_top=0,
                        clock=lambda: 0.0)
    assert watch() is False
    assert not seen and watch.discs_ignored == 1
    assert ignored and "no mob health bar" in ignored[0]


def test_the_attack_disc_counts_just_after_a_bar():
    clock = [0.0]
    frame = [with_mob()]
    watch = ThreatWatch(lambda: frame[0], skip_top=0, clock=lambda: clock[0])
    assert watch() is True                     # the bar
    frame[0] = with_disc()
    clock[0] = 4.0
    assert any(hasattr(p, "fraction") for p in watch.look())
    clock[0] = 5.5
    assert watch.look() == []


def test_a_far_bar_does_not_cut_a_walk_out_with_an_empty_bag():
    """DESIGN 8di: natro_out_spider was cut by bars 809-837 px away."""
    route, empty = ["natro_out_spider"], [True]
    watch = ThreatWatch(with_mob, skip_top=0, clock=lambda: 0.0,
                        route_name=lambda: route[0],
                        bag_is_empty=lambda: empty[0])
    # with_mob's bar is at (340, 207) on a 600x400 frame: 41 px from centre.
    assert watch() is True
    far = np.zeros((1080, 1920, 3), np.uint8)
    far[220:234, 160:240] = (60, 230, 60)
    for gx in range(186, 206, 6):
        far[223:231, gx:gx + 2] = (245, 245, 245)

    def fresh():
        return ThreatWatch(lambda: far, skip_top=0, clock=lambda: 0.0,
                           route_name=lambda: route[0],
                           bag_is_empty=lambda: empty[0])
    watch = fresh()
    assert watch() is False and watch.far_bars_ignored == 1
    empty[0] = False
    assert fresh()() is True, "a bag that is not known empty keeps every bar"
    empty[0], route[0] = True, "natro_home_spider"
    assert fresh()() is True, "only the walk out drops far bars"


def test_a_bloom_is_said_but_never_cuts_the_walk():
    """Q8 step 3, look-only: a Bloom's bar is counted and noted, not a threat."""
    def with_bloom():
        frame = np.zeros((400, 600, 3), np.uint8)
        frame[200:214, 300:380] = (60, 230, 60)
        for gx in range(326, 346, 6):
            frame[203:211, gx:gx + 2] = (245, 245, 245)
        frame[203:211, 304:311] = (200, 120, 235)     # the flower icon
        return frame
    notes = []
    watch = ThreatWatch(with_bloom, on_ignored=notes.append, skip_top=0, clock=lambda: 0.0)
    assert watch() is False and watch.reactions == 0
    assert watch.blooms_seen == 1
    assert notes and notes[0].startswith("BLOOM seen") and "look-only" in notes[0]
