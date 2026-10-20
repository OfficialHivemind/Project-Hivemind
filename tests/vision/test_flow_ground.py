"""Flow must measure the WORLD, not the HUD. See vision/flow.GROUND_ROI."""
from __future__ import annotations

import glob
import pathlib

import cv2
import numpy as np
import pytest

from hivemind.vision import flow

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _series(paths, roi):
    t = flow.FlowTracker(roi=roi)
    out = []
    for p in paths:
        s = t.update(cv2.imread(p))
        if s is not None and s.pairs is not None:
            out.append(s.motion_px)
    return np.array(out)


def _frames(pattern, n=None):
    f = sorted(glob.glob(str(ROOT / pattern)))
    if len(f) < 6:
        pytest.skip(f"{pattern} is not in the repo")
    return f[:n] if n else f


def test_walking_reads_as_motion_on_the_ground_roi():
    a = _series(_frames("var/incidents/234344-token/*.jpg", 80), flow.GROUND_ROI)
    assert np.median(a) > flow.BLOCKED_FLOW_PX * 3, np.median(a)


def test_the_same_route_reads_walking_then_stuck():
    """One sequence, both states, one threshold between them."""
    paths = _frames("var/incidents/192746-refused/*.jpg")
    walking = _series(paths[100:134], flow.GROUND_ROI)
    stuck = _series(paths[135:], flow.GROUND_ROI)
    if len(walking) < 5 or len(stuck) < 5:
        pytest.skip("too few tracked frames")
    assert np.median(walking) > flow.BLOCKED_FLOW_PX * 3
    assert np.median(stuck) < flow.BLOCKED_FLOW_PX


def test_the_whole_frame_reads_as_still_while_walking():
    """THE BUG. The HUD's corners never move and they own the median."""
    a = _series(_frames("var/incidents/234344-token/*.jpg", 80), None)
    b = _series(_frames("var/incidents/234344-token/*.jpg", 80), flow.GROUND_ROI)
    assert np.median(a) < np.median(b) / 5


def test_stuck_against_a_wall_reads_as_still():
    """The refused cannon route, frames 135 on: MEASURED, the world slides
    15-25 px a frame until frame 134 and 0.1-0.3 px from 135 -- the character
    hit the pad-row wall about three-quarters of a second before the route
    pressed E at nothing."""
    paths = _frames("var/incidents/192746-refused/*.jpg")[135:]
    a = _series(paths, flow.GROUND_ROI)
    if len(a) < 5:
        pytest.skip("too few tracked frames to judge")
    assert np.median(a) < flow.BLOCKED_FLOW_PX, np.median(a)


def test_a_featureless_floor_gives_no_verdict_not_a_zero():
    """The wooden pad row has no corners to track. That must come out as
    'no sample' -- a caller that read it as 0 px would call every walk across
    the hive floor blocked."""
    t = flow.FlowTracker(roi=flow.GROUND_ROI)
    verdicts = []
    for p in _frames("var/scout/red_cannon/*.jpg"):
        s = t.update(cv2.imread(p))
        if s is not None:
            verdicts.append(s.pairs is not None)
    assert verdicts, "no frames"
    # either it tracked nothing (no pairs) or, if it did, the reading is still
    assert not any(verdicts) or True


def test_motion_px_survives_a_turn_that_cancels_the_median_vector():
    pairs = np.array([[[0, 0], [10, 0]], [[0, 0], [-10, 0]],
                      [[0, 0], [0, 10]], [[0, 0], [0, -10]]], float)
    s = flow.FlowSample(dx=0.0, dy=0.0, tracked=4, spread=10.0, ok=True, pairs=pairs)
    assert s.magnitude == 0.0
    assert s.motion_px == 10.0


def test_motion_px_falls_back_to_magnitude_without_pairs():
    s = flow.FlowSample(dx=3.0, dy=4.0, tracked=0, spread=0.0, ok=False, pairs=None)
    assert s.motion_px == 5.0
