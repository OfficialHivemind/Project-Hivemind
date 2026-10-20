"""The loot capture hook (brain/lootcapture) and its labeller: it keeps crops
round the character when the feed names a mob's drop, never a whole frame,
stays under its caps, and names a coin only for one credit and one coin gone."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

import hivemind
from hivemind.brain import lootcapture as lc
from hivemind.stream import privacy
from hivemind.telemetry.incidents import IncidentRecorder
from hivemind.world.settings import defaults

ROOT = Path(hivemind.__file__).resolve().parents[2]


def frame(value: int = 90):
    """A 1920x1080 frame whose chat is shut (tests/unit/test_typedcapture)."""
    f = np.full((1080, 1920, 3), value, np.uint8)
    x, y, w, h = privacy.TOPBAR_PILL
    f[y:y + h, x:x + w] = 20
    x, y, w, h = privacy.CHAT_BADGE
    f[y:y + h, x:x + w] = (245, 90, 55)
    return f


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def hook(tmp_path, **kw):
    clock = Clock()
    ring = IncidentRecorder(tmp_path / "ring", window=80, clock=clock)
    for i in range(60):                        # 6 s of black box, 0.1 s apart
        clock.t = 100.0 + 0.1 * i
        ring.push(frame(80 + i % 20))
    cap = lc.LootCapture(tmp_path / "loot", ring=ring, clock=clock,
                         allowed=lambda p: True, **kw)
    return cap, clock


def test_a_drop_keeps_crops_round_the_character_never_a_whole_frame(tmp_path):
    cap, clock = hook(tmp_path)
    cap.heard("+40 Honey (from Pine Tree Forest)")
    cap.heard("+1 Treat (from Ladybug) +200 Bond (from Ladybug)")
    assert cap.dropped("ladybug", "bond", 200) is None, "bond is given, not picked up"
    out = cap.dropped("ladybug", "treat", 1, attempt=7, field="pine_tree")
    assert out is not None
    assert cap.dropped("ladybug", "blueberry", 1) == out, "one capture a read"
    meta = json.loads((out / "meta.json").read_text())
    assert meta["drops"] == [["ladybug", "treat", 1], ["ladybug", "blueberry", 1]]
    assert meta["feed_before"] == "+40 Honey (from Pine Tree Forest)" and meta["attempt"] == 7
    assert meta["anchor"] == [960, 669] and meta["crop"] == [704, 413, 512]
    for jpg in out.glob("*.jpg"):
        assert cv2.imread(str(jpg)).shape[:2] == (512, 512), "a whole frame was written"
    dts = [dt for _f, dt in meta["frames"]]
    assert all(-lc.LOOKBACK_S <= dt <= 0 for dt in dts) and 12 <= len(dts) <= 17
    assert min(b - a for a, b in zip(dts, dts[1:])) >= lc.PITCH_S - 1e-3
    assert (out / "bar_first.png").is_file() and (out / "bar_last.png").is_file()
    # a new read is a new capture; honey from a mob keeps nothing
    clock.t += 3.0
    cap.heard("+1 Ticket (from Ladybug)")
    assert cap.dropped("ladybug", "honey", 300) is None
    assert cap.dropped("ladybug", "honex", 300) is None, "a misread names nothing"
    assert cap.dropped("ladybug", "ticket", 1) not in (None, out)


def test_bounded_and_never_raises(tmp_path):
    cap, clock = hook(tmp_path, max_captures=2)
    for i in range(4):
        for _k in range(30):
            clock.t += 0.1
            cap.ring.push(frame())
        cap.heard(f"+1 Treat (from Ladybug) {i}")
        cap.dropped("ladybug", "treat", 1)
    assert len(list((tmp_path / "loot").iterdir())) == 2 and cap.rotated == 2
    assert lc.LootCapture(tmp_path / "x").dropped("ladybug", "treat", 1) is None   # no ring
    shut = lc.LootCapture(tmp_path / "y", ring=cap.ring, clock=clock, allowed=lambda p: False)
    shut.heard("+1 Treat (from Ladybug)")
    assert shut.dropped("ladybug", "treat", 1) is None, "storage said no"


META = {"crop": [704, 414, 512], "anchor": [960, 670], "feed_before": "",
        "feed": "+1 Treat (from Ladybug) +200 Bond (from Ladybug)",
        "drops": [["ladybug", "treat", 1]]}
BAR = np.full((42, 456, 3), 90, np.uint8)
GONE = [("f00.jpg", -1.0, [(300, 280, 90, 0.9)]), ("f01.jpg", -0.75, [(290, 270, 96, 0.95)]),
        ("f02.jpg", -0.5, []), ("f03.jpg", -0.25, [(30, 30, 60, 0.99)])]
KNOWN = lc.known_items()


def test_one_credit_one_coin_gone_names_it():
    name, why, (frame_name, box) = lc.label(META, GONE, KNOWN, BAR, BAR)
    assert (name, frame_name, box) == ("item_treat", "f01.jpg", [242, 222, 338, 318]), why


def test_anything_doubtful_names_nothing():
    two = dict(META, feed="+1 Treat (from Ladybug) +90 Honey (from Pine Tree Forest)")
    assert lc.label(two, GONE, KNOWN, BAR, BAR)[0] is None, "a second pickup in the read"
    old = dict(META, feed_before=META["feed"])
    assert lc.label(old, GONE, KNOWN, BAR, BAR)[1] == "the read shows no new drop"
    odd = dict(META, feed="+1 Glorp (from Ladybug)", drops=[["ladybug", "glorp", 1]])
    assert lc.label(odd, GONE, KNOWN, BAR, BAR)[1] == "an item the drop table does not name"
    assert lc.label(META, GONE, KNOWN, None, BAR)[1] == "no buff bar before and after"
    once = [GONE[0][:2] + ([],), GONE[1], GONE[2], GONE[3]]
    assert "one look only" in lc.label(META, once, KNOWN, BAR, BAR)[1]
    late = GONE[:3] + [("f03.jpg", -0.25, [(260, 300, 90, 0.9)])]
    assert lc.label(META, late, KNOWN, BAR, BAR)[1] == "the coin beside the character did not go"
    unsure = [(n, dt, [(x, y, s, 0.5) for x, y, s, _c in seen]) for n, dt, seen in GONE]
    assert lc.label(META, unsure, KNOWN, BAR, BAR)[1] == "no coin beside the character"


def test_known_items_are_the_mob_tables_drops():
    assert {"treat", "blueberry", "royal jelly", "ticket"} <= KNOWN and "honex" not in KNOWN


def test_wired_into_the_feed_and_off_by_default():
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    feed = src[src.index("def on_feed_text"):]
    assert "loot_capture.heard(text)" in feed[:400]
    drops = src[src.index("def drops_heard"):src.index("def bugrun_heard")]
    assert "settings.bool(lootcapture.SETTING)" in drops and "loot_capture.dropped(" in drops
    assert defaults()[lc.SETTING] is False
