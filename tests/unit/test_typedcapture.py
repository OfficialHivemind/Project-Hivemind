"""The typed capture hook (brain/typedcapture) and its labeller (scripts/label_typed.py):
it keeps crops only when a chase paid, never a whole frame, stays under its caps,
and labels only one reached token with one change."""
from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import cv2
import numpy as np

import hivemind
from hivemind.brain import typedcapture as tc
from hivemind.stream import privacy
from hivemind.telemetry.incidents import IncidentRecorder

ROOT = Path(hivemind.__file__).resolve().parents[2]


def frame(value: int = 90):
    """A 1920x1080 frame whose chat is shut: the badge on the chat icon is blue."""
    f = np.full((1080, 1920, 3), value, np.uint8)
    x, y, w, h = privacy.TOPBAR_PILL
    f[y:y + h, x:x + w] = 20
    x, y, w, h = privacy.CHAT_BADGE
    f[y:y + h, x:x + w] = (245, 90, 55)          # BGR of the blue badge
    return f


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def hook(tmp_path, **kw):
    clock = Clock()
    ring = IncidentRecorder(tmp_path / "ring", window=20, clock=clock)
    cap = tc.TypedCapture(tmp_path / "typed", ring=ring, clock=clock,
                          allowed=lambda p: True, **kw)
    return cap, ring, clock


def chase(cap, ring, clock, *, outcome="collected", arrived=True, seen=()):
    base = clock.t
    for i in range(10):                            # 0.5 s of black box before
        clock.t = base + 0.1 * i
        ring.push(frame(80 + i))
    cap.begin(frame(), clock.t, 900, 600, box=(860, 560, 80, 80), kind="honey",
              seen=seen, anchor=(960, 540), attempt=7, detector=0.9)
    clock.t += 2.0
    return cap.finish(frame(), arrived=arrived, outcome=outcome, evidence="x")


def test_a_paying_chase_keeps_crops_never_a_whole_frame(tmp_path):
    cap, ring, clock = hook(tmp_path)
    out = chase(cap, ring, clock)
    assert out is not None
    meta = json.loads((out / "meta.json").read_text())
    assert meta["box"] == [860, 560, 80, 80] and meta["point"] == [900, 600]
    assert meta["why"] == "hud" and meta["attempt"] == 7
    side = meta["crop"][2]
    assert side == 200, "2.5 coin sides round an 80 px coin"
    for jpg in out.glob("*.jpg"):
        assert cv2.imread(str(jpg)).shape[:2] == (side, side), "a whole frame was written"
    assert 4 <= len(meta["frames"]) <= 6, "the black box's 0.5 s before the chase"
    assert all(-tc.WINDOW_S <= dt <= 0 for _f, dt in meta["frames"])
    assert cv2.imread(str(out / "bar_before.png")).shape[:2] == (42, tc.BAR_WIDTH)


def test_nothing_is_written_when_nothing_paid_or_it_never_arrived(tmp_path):
    cap, ring, clock = hook(tmp_path)
    assert chase(cap, ring, clock, outcome="unknown") is None
    assert chase(cap, ring, clock, arrived=False) is None
    assert not (tmp_path / "typed").exists() or not any((tmp_path / "typed").iterdir())


def test_a_frame_with_the_chat_maybe_open_is_never_used(tmp_path):
    cap, ring, clock = hook(tmp_path)
    assert cap.begin(np.zeros((1080, 1920, 3), np.uint8), 1.0, 900, 600) is False
    assert cap.finish(frame(), arrived=True, outcome="collected") is None


def test_a_late_feed_credit_writes_the_capture_that_waited(tmp_path):
    cap, ring, clock = hook(tmp_path)
    cap.heard("+12 Honey (from Pine Tree Forest)")          # before: not this chase's
    assert chase(cap, ring, clock, outcome="unknown") is None
    clock.t += 3.0
    cap.heard("Bubble Bee is out of energy!")               # no credit: still waiting
    assert not list((tmp_path / "typed").glob("*/meta.json"))
    cap.heard("+12 Honey (from Pine Tree Forest) +340 Honey (from Pine Tree Forest)")
    metas = list((tmp_path / "typed").glob("*/meta.json"))
    assert len(metas) == 1
    meta = json.loads(metas[0].read_text())
    assert meta["why"] == "feed"
    assert meta["feed_before"].startswith("+12 Honey")
    assert meta["feed"][-1][1].endswith("+340 Honey (from Pine Tree Forest)")


def test_the_disk_is_capped_oldest_first(tmp_path):
    cap, ring, clock = hook(tmp_path, max_captures=2)
    kept = [chase(cap, ring, clock) for _ in range(3)]
    left = sorted(p.name for p in (tmp_path / "typed").iterdir())
    assert left == sorted(p.name for p in kept[1:])
    assert cap.rotated == 1


def test_the_ring_hands_back_a_time_window():
    clock = Clock()
    ring = IncidentRecorder("/nonexistent", window=10, clock=clock)
    for i in range(10):
        clock.t = float(i)
        ring.push(np.full((8, 8, 3), i * 20, np.uint8))
    assert [t for t, _d in ring.between(3.0, 5.0)] == [3.0, 4.0, 5.0]


def test_other_tokens_near_the_walk():
    s = types.SimpleNamespace
    seen = [s(x=900, y=600, confidence=0.9),       # the target itself
            s(x=930, y=575, confidence=0.8),       # on the way
            s(x=400, y=200, confidence=0.9)]       # far off
    near = tc.on_path(seen, (960, 540), (900, 600))
    assert [p[:2] for p in near] == [[930, 575]]


# ---- labelling -------------------------------------------------------------------
def test_feed_credits_parse_through_ocr_noise():
    got = tc.credits("+395'Honey (from Blue Flower Field) t3 Blueberries rom Cub Buddy)")
    assert got == [("395", "honey", "blue flower field"), ("3", "blueberry", "cub buddy")]
    assert tc.new_credits("+5 Honey (from Pine Tree Forest)",
                          ["+5 Honey (from Pine Tree Forest) +1 Treat (from Pine Tree Forest)"]) \
        == [("treat", "pine tree forest")]
    assert tc.unreadable("Defeated Mantis! (+5 Battle Points)") == 0
    assert tc.unreadable("+5|6,97'g Hon (fr Coin") == 1


ICON = 38


def icon(seed: int):
    """A square with its own glyph: a bar at its own angle."""
    t = np.full((ICON, ICON, 3), 30 + 40 * seed, np.uint8)
    a = np.deg2rad(seed * 47)
    c, d = int(14 * np.cos(a)), int(14 * np.sin(a))
    cv2.line(t, (19 - c, 19 - d), (19 + c, 19 + d), (255, 255, 255), 6)
    return t


def strip(seeds):
    s = np.full((42, tc.BAR_WIDTH, 3), 128, np.uint8)       # flat scenery
    for i, k in enumerate(seeds):
        s[tc.BAR_PAD:tc.BAR_PAD + ICON, i * ICON:(i + 1) * ICON] = icon(k)
    return s


def test_the_bar_says_which_icon_came():
    assert len(tc.occupied(strip([1, 2, 3]))) == 3
    changes, clear = tc.bar_changes(strip([1, 2, 3]), strip([1, 3, 4]))
    assert clear and changes == [("appeared", 2, "buff_unnamed")], "2 went, 4 came"
    changes, clear = tc.bar_changes(strip([1, 2]), strip([1, 2]))
    assert clear and changes == []


def meta(**kw):
    m = {"arrived": True, "on_path": [], "feed_before": "", "feed": [], "evidence": ""}
    m.update(kw)
    return m


def test_a_label_only_for_one_token_and_one_change():
    bar = strip([1, 2])
    one = [[0.5, "+340 Honey (from Pine Tree Forest)"]]
    assert tc.label(meta(feed=one), bar, bar)[0] == "honey"
    assert tc.label(meta(feed=[[0.5, "+2 Treats (from Pine Tree Forest)"]]), bar, bar)[0] \
        == "item_treat"
    assert tc.label(meta(feed=one), bar, strip([1, 2, 3]))[0] is None, "a buff came too"
    assert tc.label(meta(feed=[], evidence="honey rose 900 in 2s"), bar, strip([1, 2, 3]))[0] is None
    assert tc.label(meta(), bar, strip([1, 2, 3]))[0] == "buff_unnamed"
    assert tc.label(meta(feed=one, arrived=False), bar, bar)[0] is None
    assert tc.label(meta(feed=one, on_path=[[1, 2, 0.9]]), bar, bar)[0] is None
    assert tc.label(meta(feed=one), None, None)[0] is None, "no bar: a buff could hide"
    assert tc.label(meta(feed=[[0.5, "+11,050 Honey (from Token Link)"]]), bar, bar)[0] is None
    assert tc.label(meta(feed=[[0.5, "+5|6,97'g Hon (fr Coin"]]), bar, bar)[0] is None


def test_label_typed_writes_a_manifest_row(tmp_path):
    cap, ring, clock = hook(tmp_path)
    cap.heard("nothing yet")
    out = chase(cap, ring, clock)
    clock.t += 1.0
    cap.heard("+340 Honey (from Pine Tree Forest)")
    spec = importlib.util.spec_from_file_location("label_typed", ROOT / "scripts/label_typed.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--captures", str(tmp_path / "typed"), "--out", str(tmp_path / "ds")]) == 0
    rows = [json.loads(line) for line in (tmp_path / "ds/manifest.jsonl").read_text().splitlines()]
    assert rows and {r["label"] for r in rows} == {"honey"}
    assert rows[0]["capture"] == out.name and rows[0]["src"].endswith("decide.jpg")
    assert rows[0]["split"] == mod.split_of("attempt-7")


# ---- review (rp/capturehook-review) ------------------------------------------------
def test_a_feed_pill_inside_the_world_box_is_blacked_out():
    f = frame(90)
    blue = cv2.cvtColor(np.uint8([[[108, 200, 220]]]), cv2.COLOR_HSV2BGR)[0, 0]
    f[900:920, 1400:1904] = blue                   # a pill, in the world box up to x 1785
    out = tc.world_crop(f, 1600, 800, 192)
    assert not out[100:120, 0:180].any(), "the pill (its label text) never reaches a crop"
    assert out[20:80, 0:180].any(), "the world round it is kept"


def test_only_a_field_credit_names_the_chased_token():
    bar = strip([1, 2])
    assert tc.label(meta(feed=[[0.5, "+1 Treat (from Cub Buddy)"]]), bar, bar)[0] is None
    assert tc.label(meta(feed=[[0.5, "+3 Blueberries (from Leaves)"]]), bar, bar)[0] is None
    assert tc.label(meta(feed=[[0.5, "+1 Treat (from Pine Tree Forest)"]]), bar, bar)[0] \
        == "item_treat"


def test_a_credit_another_chase_may_have_earned_labels_nothing():
    bar = strip([1, 2])
    one = [[0.5, "+340 Honey (from Pine Tree Forest)"]]
    assert tc.label(meta(feed=one, prev_s=2.0), bar, bar)[0] is None, "the chase before's line"
    assert tc.label(meta(feed=one, prev_s=12.0), bar, bar)[0] == "honey"
    assert tc.label(meta(feed=one, feed_prior=[one[0][1]]), bar, bar)[0] is None, "read before"
    late = [[3.0, "+340 Honey (from Pine Tree Forest)"]]
    assert tc.label(meta(feed=late, next_dt=2.5), bar, bar)[0] is None, "the next chase's"


def test_the_hook_records_the_chases_round_it(tmp_path):
    cap, ring, clock = hook(tmp_path)
    first = chase(cap, ring, clock)
    second = chase(cap, ring, clock)
    m1 = json.loads((first / "meta.json").read_text())
    m2 = json.loads((second / "meta.json").read_text())
    assert m1["prev_s"] is None and 0 < m2["prev_s"] < tc.FEED_GRACE_S
    clock.t += 1.0
    cap.heard("+340 Honey (from Pine Tree Forest)")            # joins the second, not the first
    assert json.loads((second / "meta.json").read_text())["feed"]
