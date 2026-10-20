"""Vic hop, our way (act/vichunt, ROADMAP M5): the walk to a seen spike, its
night gate, the counters, and the wiring -- all look-only."""
from __future__ import annotations

from pathlib import Path

import cv2
import pytest

import hivemind
from hivemind.act import vichunt, vicious
from hivemind.brain import hop
from hivemind.vision import night, vicspike
from hivemind.vision.vicspike import Spike

ROOT = Path(hivemind.__file__).resolve().parents[2]
VAR = Path.home() / "Hivemind" / "var"
W, H = 1920, 1080              # the anchor (act/chase): (960, 669)


def _spike(x, y):
    return Spike(x, y, 50, 0.0, 0.6, 0.5)


def test_look_only_and_said():
    assert vichunt.VIC_HOP_LIVE is False
    line = vichunt.would_line(_spike(1516, 350), W, H, "clover", vicious.MAX_FIGHT_S, 4)
    assert line.startswith("vic hop would: walk 'wd' to the spike at (1516, 350) in the clover")
    assert "16-stud dodge square" in line and "3 min" in line and "level 4" in line
    plan = vichunt.plan_line(["clover", "spider"], True, 4)
    assert plan.startswith("vic hop would: night in this public server")
    assert "clover, spider" in plan


def test_steering_is_the_token_chase_rule():
    from hivemind.act import chase
    assert vichunt.STEPS == chase.MAX_STEPS
    assert vichunt.towards(_spike(927, 337), W, H)[0] == "w"       # dead ahead: no crabbing
    assert vichunt.towards(_spike(279, 337), W, H)[0] == "wa"
    assert vichunt.towards(_spike(960, 900), W, H)[0] == "s"
    assert vichunt.towards(_spike(990, 680), W, H) == ("", pytest.approx(31.9, abs=0.1))


def _world(start, per_step=120, lose_after=None):
    """A spike ahead that comes `per_step` px down the screen every step."""
    at, walked = list(start), []

    def walk(keys):
        walked.append(keys)
        at[1] += per_step

    def look():
        if lose_after is not None and len(walked) >= lose_after:
            return [], (W, H)
        return [_spike(*at), _spike(100, 1000)], (W, H)     # a second blob far off
    return look, walk, walked


def test_the_walk_looks_after_every_step():
    look, walk, walked = _world((960, 300))
    got, steps = vichunt.steer(_spike(960, 300), (W, H), look, walk)
    assert got == "arrived" and steps == len(walked) == 3 and set(walked) == {"w"}
    look, walk, walked = _world((960, 300), lose_after=1)
    assert vichunt.steer(_spike(960, 300), (W, H), look, walk) == ("lost", 2)
    look, walk, walked = _world((960, 100), per_step=10)
    assert vichunt.steer(_spike(960, 100), (W, H), look, walk) == ("steps", vichunt.STEPS)
    assert vichunt.steer(_spike(970, 660), (W, H), look, walk)[0] == "arrived"


def test_the_counters_are_lifetime_and_seeded_from_the_tries():
    old = {"tries": [{"at": 1.0, "result": "absent"}] * 20}
    assert vichunt.summary(old, {}, False).startswith("Vicious Bee: 20 hunts, 0 of them in public")
    st = vicious.record(old, "killed", 100.0, spiked=True, public=True)
    assert st["count"] == {"hunts": 21, "public": 1, "spikes": 1, "fights": 1,
                           "killed": 1, "lost": 0}
    st = vicious.record(st, "died", 200.0)
    st = vicious.record(st, "absent", 300.0)
    for _ in range(25):
        st = vicious.record(st, "absent", 400.0)
    assert len(st["tries"]) == 20 and st["count"]["hunts"] == 48
    assert st["count"]["fights"] == 2 and st["count"]["lost"] == 1
    hs, _ = hop.arrived(hop.arrived({}, "a")[0], "b")
    said = vichunt.summary(st, hs, False)
    assert ("48 hunts, 1 of them in public servers. A spike seen at night in 1. "
            "Fights: 2 (1 won, 1 lost).") in said
    assert "joined: 2 (server hopping is watch only)." in said
    assert said.endswith("Walking to a seen spike is watch only.")
    assert vichunt.summary({}, {}, False) == ""


def test_the_counters_stay_light():
    """Telegram /report reads them in a long-lived process: no numpy, no cv2."""
    import subprocess
    import sys
    got = subprocess.run([sys.executable, "-c", "import sys; import hivemind.act.vichunt; "
                          "print('cv2' in sys.modules or 'numpy' in sys.modules)"],
                         capture_output=True, text=True, timeout=60,
                         env={"PYTHONPATH": str(ROOT / "src")})
    assert got.stdout.strip() == "False", got.stderr


def test_summary_of_reads_the_files(tmp_path):
    vicious.save(tmp_path / "vicious.json", vicious.record({}, "absent", 1.0, spiked=True))
    hop.save(tmp_path / "hop.json", hop.arrived({}, "x")[0])
    assert "1 hunts" in vichunt.summary_of(tmp_path) and "joined: 1 " in vichunt.summary_of(tmp_path)
    assert vichunt.summary_of(tmp_path / "none") == ""


def test_the_loop_is_wired_look_only():
    farm = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    hunt = farm[farm.index("def hunt_the_vicious"):farm.index("def play_ant_challenge")]
    assert "hits and night_mod.is_night(frame)" in hunt and "def to_the_spike" in hunt
    assert "if not vichunt_mod.VIC_HOP_LIVE:" in hunt and "vichunt_mod.would_line(" in hunt
    assert "vichunt_mod.steer(" in hunt and "vichunt_mod.plan_line(" in hunt
    assert "spiked=spot[\"seen\"]" in hunt and "result = to_the_spike()" in hunt
    shell = (ROOT / "src/hivemind/gui/shell.py").read_text(encoding="utf-8")
    assert "CardPage(MACRO_BUGS, card, bottom=(self.vic_note,))" in shell
    assert "vichunt.summary_of(" in shell
    tg = (ROOT / "scripts" / "telegram_alerts.py").read_text(encoding="utf-8")
    assert "vichunt.summary_of(var())" in tg


# THE REPLAY on our own kept hunt frames (MEASURED 2026-10-27, the owner's
# machine only): every frame of the 37 hunts in which vision/vicspike finds a
# spike -- 15 hunts, 2 of them real (scripts/score_vicspike.py SPIKES). The
# loop walks only where the frame itself is night: the 2 real hunts on their
# arrival frame, and 2 false ones (a player's name, a 16 px glint).
HITS = {
    "20261013-131658/0155.7-spider-arrived": False, "20261013-141911/0105.1-check": True,
    "20261013-192332/0172.7-check": False, "20261015-045645/0124.8-check": False,
    "20261015-070531/0027.7-clover-arrived": True, "20261015-070531/0029.2-check": True,
    "20261015-163838/0070.8-check": False, "20261015-163838/0073.7-check": False,
    "20261018-063140/0114.8-check": False, "20261019-035117/0049.7-check": False,
    "20261019-035117/0053.9-check": False, "20261019-035117/0093.8-spider-arrived": False,
    "20261019-061652/0110.6-check": False, "20261019-061652/0117.6-check": False,
    "20261020-150756/0043.5-check": False, "20261021-153447/0046.8-check": False,
    "20261021-153447/0088.7-check": False, "20261021-153447/0092.7-check": False,
    "20261022-133808/0030.9-check": False, "20261022-133808/0040.8-check": False,
    "20261022-133808/0049.2-check": False, "20261023-170818/0080.3-check": False,
    "20261023-181405/0027.0-clover-arrived": True, "20261023-181405/0045.6-check": False,
    "20261023-204232/0029.1-clover-arrived": True, "20261023-204232/0030.5-check": False,
    "20261023-204232/0048.8-check": False,
}
REAL = {"20261015-070531", "20261023-204232"}


def test_replay_on_our_hunt_frames():
    paths = {k: VAR / "vicious" / f"{k}.jpg" for k in HITS}
    if not all(p.exists() for p in paths.values()):
        pytest.skip("owner's frames only")
    walked = set()
    for key, path in paths.items():
        frame = cv2.imread(str(path))
        assert vicspike.find(frame), key
        gate = night.is_night(frame)
        assert gate == HITS[key], key
        if gate:
            walked.add(key.split("/")[0])
    assert len({k.split("/")[0] for k in HITS}) == 15
    assert REAL <= walked and len(walked - REAL) == 2
    # the real arrivals: the walk heads at the spike
    arrive = cv2.imread(str(paths["20261023-204232/0029.1-clover-arrived"]))
    s = vicspike.find(arrive)[0]
    assert vichunt.towards(s, arrive.shape[1], arrive.shape[0])[0] == "wd"
