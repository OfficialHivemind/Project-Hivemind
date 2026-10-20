"""vision/sprinkler (the Golden Gusher finder) and act/drift's look-only
sprinkler anchor, on synthetic frames: a tan post is proposed, the HUD rows
are not, and the anchor says which way back without pressing anything."""
import numpy as np

from hivemind.act import drift
from hivemind.vision import coinnet, sprinkler
from hivemind.vision.sprinkler import Sighting

TAN_BGR = (110, 170, 200)       # HSV ~ (22, 116, 200): inside the Gusher gate


def frame_with_post(x, y, w=40, h=110):
    f = np.full((1080, 1920, 3), (40, 140, 40), np.uint8)    # grass
    f[y:y + h, x:x + w] = TAN_BGR
    return f


def test_a_tan_post_is_proposed_and_hud_rows_are_not():
    work, s = sprinkler.to_work(frame_with_post(900, 500))
    assert s == 2.0
    boxes = sprinkler.proposals(work)
    assert len(boxes) == 1
    x, y, w, h = boxes[0]
    assert abs(x - 450) <= 2 and abs(y - 250) <= 2 and h > w
    hud = frame_with_post(900, 40)                     # in the pill row
    assert sprinkler.proposals(sprinkler.to_work(hud)[0]) == []
    assert sprinkler.crop(work, boxes[0]).shape == (32, 32, 3)


def test_find_scores_proposals_with_the_model_shape():
    params = coinnet.fresh(size=sprinkler.CROP)
    out = sprinkler.find(frame_with_post(900, 500), params, cut=0.0)
    assert len(out) == 1 and 0.0 <= out[0].score <= 1.0
    assert out[0].x == 900 and out[0].h >= 100           # back in frame px
    assert sprinkler.find(frame_with_post(900, 500), params, cut=1.01) == []


def test_anchor_looks_only_and_points_at_the_post_foot():
    assert drift.SPRINKLER_ANCHOR_LIVE is False
    frame = np.zeros((1080, 1920, 3), np.uint8)
    # character at (960, 669.6); a post up and to the left of it
    far = drift.sprinkler_anchor(frame, lambda f: [Sighting(500, 200, 60, 150, 0.97)])
    assert far.would == "wa" and far.offset == (-430.0, -319.6)
    assert far.describe().startswith("sprinkler anchor would: hold wa (")
    near = drift.sprinkler_anchor(frame, lambda f: [Sighting(940, 560, 40, 100, 0.9)])
    assert near.would == "" and near.reason.startswith("stay (")
    none = drift.sprinkler_anchor(frame, lambda f: [])
    assert none.would == "" and "no sprinkler in view" in none.describe()
    assert "no frame" in drift.sprinkler_anchor(None, lambda f: []).reason


def test_find_takes_the_live_bgra_capture():
    # MEASURED runs 1254-1259: the BGRA capture raised in the network on
    # every look with a proposal ("size 27 is different from 36")
    params = coinnet.fresh(size=sprinkler.CROP)
    bgr = frame_with_post(900, 500)
    bgra = np.dstack([bgr, np.full(bgr.shape[:2], 255, np.uint8)])
    assert sprinkler.find(bgra, params, cut=0.0) == sprinkler.find(bgr, params, cut=0.0)


def test_standing_on_the_sprinkler_is_a_stay():
    # the measured on-the-sprinkler read: foot ~114 px above the character
    assert drift.SPRINKLER_RETURN_LIVE is False and drift.ANCHOR_BOX_PIXELS == 170
    frame = np.zeros((1080, 1920, 3), np.uint8)
    on = drift.sprinkler_anchor(frame, lambda f: [Sighting(940, 456, 40, 100, 0.99)])
    assert on.would == "" and on.reason.startswith("stay (")
    assert on.describe("sprinkler return").startswith("sprinkler return would: stay")


class _Vin:
    def __init__(self):
        self.held_keys = []

    def held(self, *keys):
        from contextlib import nullcontext
        self.held_keys.append("".join(keys))
        return nullcontext()

    def release_all(self):
        pass


def test_walk_to_sprinkler_steps_until_it_is_under_the_character():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    looks = iter([[Sighting(500, 200, 60, 150, 0.97)],      # up-left: wa
                  [Sighting(800, 400, 60, 150, 0.97)],      # closer: wa
                  [Sighting(940, 456, 40, 100, 0.99)]])     # on it: stay
    vin = _Vin()
    out = drift.walk_to_sprinkler(lambda: frame, lambda f: next(looks), vin=vin,
                                  sleep=lambda s: None)
    assert out.arrived and out.steps == 2 and vin.held_keys == ["wa", "wa"]
    assert "2 step(s) (wa)" in out.describe()


def test_walk_to_sprinkler_never_walks_on_a_guess():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    vin = _Vin()
    none = drift.walk_to_sprinkler(lambda: frame, lambda f: [], vin=vin, sleep=lambda s: None)
    assert not none.walked and vin.held_keys == [] and "no sprinkler in view" in none.reason
    looks = iter([[Sighting(500, 200, 60, 150, 0.97)], []])
    lost = drift.walk_to_sprinkler(lambda: frame, lambda f: next(looks), vin=vin,
                                   sleep=lambda s: None)
    assert lost.steps == 1 and not lost.arrived and "lost from view" in lost.reason
    far = drift.walk_to_sprinkler(lambda: frame, lambda f: [Sighting(500, 200, 60, 150, 0.97)],
                                  vin=_Vin(), sleep=lambda s: None, max_steps=3)
    assert far.steps == 3 and "walked the 3 steps" in far.reason


def test_search_looks_round_and_always_gives_the_heading_back():
    assert drift.SPRINKLER_SEARCH_LIVE is False
    assert drift.search_taps(drift.SEARCH_PASS_HEADINGS) == 4     # +1, -2, +1
    assert drift.search_taps(drift.SEARCH_END_HEADINGS) == 8      # once round
    frame = np.zeros((1080, 1920, 3), np.uint8)
    post = [Sighting(500, 200, 60, 150, 0.97)]

    def run(seen_at, **kw):
        turns, at = [], [0]

        def turn(n):
            turns.append(n)
            at[0] += n
        out = drift.search_sprinkler(lambda: frame,
                                     lambda f: post if seen_at is not None
                                     and at[0] % 8 == seen_at % 8 else [],
                                     turn=turn, sleep=lambda s: None, **kw)
        return out, turns, at[0]

    out, turns, at = run(-1)                       # found at the second look
    assert out.found_at == -1 and out.anchor.would == "wa" and turns == [1, -2, 1]
    assert at == 0 and out.turned == 0 and out.taps == 4
    assert "found at -45°" in out.describe()
    out, turns, at = run(None, headings=drift.SEARCH_END_HEADINGS)   # never seen
    assert out.found_at is None and at == 8 and out.taps == 8         # once round
    assert out.looked == [1, 2, 3, 4, 5, 6, 7] and "not found" in out.describe()
    out, turns, at = run(3, headings=drift.SEARCH_END_HEADINGS, stay=True)
    assert out.found_at == 3 and out.turned == 3 and at == 3       # left facing it
    out, turns, at = run(None, stopped=iter([False, True]).__next__)  # stopped part way
    assert out.found_at is None and at == 0 and out.looked == [1]
    off = drift.Search(headings=drift.SEARCH_PASS_HEADINGS).describe("sprinkler anchor search")
    assert off.startswith("sprinkler anchor search would: look at +45°, -45° (4 taps, ~1.2s)")


# ---- ours, not another player's (act/drift `ours`, docs/pending/ownsprinkler.md)
ON_IT = Sighting(940, 456, 40, 100, 0.90)       # foot (0, -114): where ours reads placed
OTHER = Sighting(150, 390, 40, 100, 0.99)       # foot ~790 px off, the measured case
SHAPE = (1080, 1920, 3)


def test_a_post_far_from_where_we_placed_it_is_not_ours():
    assert drift.ours([OTHER, ON_IT], SHAPE, (0.0, 0.0)) == [ON_IT]
    frame = np.zeros(SHAPE, np.uint8)
    # the best score is the other player's: without `walked` it is followed
    assert drift.sprinkler_anchor(frame, lambda f: [OTHER, ON_IT]).seen is OTHER
    look = drift.sprinkler_anchor(frame, lambda f: [OTHER, ON_IT], walked=(0.0, 0.0))
    assert look.seen is ON_IT and look.others == [OTHER] and look.would == ""
    assert "1 not ours" in look.reason
    alone = drift.sprinkler_anchor(frame, lambda f: [OTHER], walked=(0.0, 0.0))
    assert alone.seen is None and alone.offset is None and alone.would == ""
    assert "where ours can be" in alone.reason and alone.others == [OTHER]


def test_ours_moves_with_our_own_walk():
    # 16 studs left ('a'): ours slides right on screen, 2100 * 16 / 50 = 672 px
    assert drift.placed_at(-16.0, 0.0) == (672.0, -114.0)
    right_of = Sighting(1612, 456, 40, 100, 0.9)        # foot (+672, -114)
    left_of = Sighting(268, 456, 40, 100, 0.9)          # foot (-672, -114)
    assert drift.ours([left_of, right_of], SHAPE, (-16.0, 0.0)) == [right_of]
    # a wall that stopped the walk early leaves ours anywhere between
    assert drift.ours([ON_IT], SHAPE, (-16.0, 0.0)) == [ON_IT]
    # walking forward leaves it behind, nearer the camera: lower on the screen
    assert drift.placed_at(0.0, 10.0)[1] > drift.placed_at(0.0, 0.0)[1]


def test_a_post_cut_by_the_screen_edge_is_judged_by_its_side():
    cut = Sighting(0, 400, 30, 150, 0.9)                # foot past the left edge
    assert drift.ours([cut], SHAPE, (30.0, 0.0)) == [cut]   # ours walked off that way
    assert drift.ours([cut], SHAPE, (0.0, 0.0)) == []       # ours is under us


def test_walk_to_sprinkler_never_walks_to_another_players():
    frame = np.zeros(SHAPE, np.uint8)
    vin = _Vin()
    out = drift.walk_to_sprinkler(lambda: frame, lambda f: [OTHER], vin=vin,
                                  sleep=lambda s: None, walked=(0.0, 0.0))
    assert not out.walked and vin.held_keys == [] and "where ours can be" in out.reason
    # its own steps count as walk: a post it walks towards stays ours
    looks = iter([[Sighting(1500, 456, 40, 100, 0.9)], [ON_IT]])
    went = drift.walk_to_sprinkler(lambda: frame, lambda f: next(looks), vin=_Vin(),
                                   sleep=lambda s: None, walked=(-16.0, 0.0))
    assert went.steps == 1 and went.arrived


def test_the_runner_keeps_our_walk_and_the_farm_reads_it():
    from pathlib import Path
    import hivemind
    root = Path(hivemind.__file__).resolve().parents[2]
    routes = (root / "src/hivemind/act/routes.py").read_text(encoding="utf-8")
    assert "self.walked[0] += right" in routes
    farm = (root / "scripts/run_farm.py").read_text(encoding="utf-8")
    assert 'sprinkler["at"] = tuple(runner.walked)' in farm
    assert "sprinkler_anchor(frame, sprinkler_vision.find, walked=walked)" in farm
    # the walks the runner does not walk (bed steers, the anchor's own) count too
    assert farm.count("walked_outside_the_runner(") == 4
    assert "walked_outside_the_runner(steered.keys)" in farm
    assert "walked_outside_the_runner(drifted.keys)" in farm


def test_steps_walked_is_the_chase_steps_as_planned():
    assert drift.steps_walked([], 28.0) == (0.0, 0.0)
    r, f = drift.steps_walked(["w", "a", "a"], 20.0, 0.5)
    assert (r, f) == (-20.0, 10.0)
