"""Noticing that the game has gone. See brain/alive.py, and 2026-09-20."""
from __future__ import annotations

import pytest

from hivemind.brain.alive import GONE_AFTER, WorldGuard


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def tick(self, seconds):
        self.t += seconds


def watch(g, clock, seconds, step=1.0):
    """Look every `step` s for `seconds`; the last answer. The guard counts
    only time it watched (a gap over UNWATCHED_GAP is no evidence) and needs
    MIN_ABSENT_LOOKS looks, so an absence is lived through, not jumped."""
    out = None
    for _ in range(int(round(seconds / step))):
        clock.tick(step)
        out = g.check()
    return out


def guard(frames=lambda: object(), present=lambda f: True, **kw):
    clock = kw.pop("clock", FakeClock())
    stopped = []
    said = []
    g = WorldGuard(frames, present, on_gone=lambda: stopped.append(True),
                   emit=said.append, clock=clock, check_every=0.0, **kw)
    return g, clock, stopped, said


def test_a_hold_asks_unblock_and_a_cleared_box_lets_the_run_go_on():
    """A25: a game Yes/No box hides the HUD while the client beats; the hold
    asks `unblock` on each look, and once it answers the box the HUD is back
    and nothing is stopped (the 11:54 16 Oct rejoin waited it out instead)."""
    here, box, clicks = [False], [True], []

    def unblock(frame):
        if not box[0]:
            return ""
        clicks.append(frame)
        box[0] = False
        here[0] = True                     # the box shut: the pills show again
        return "answered No"

    g, clock, stopped, said = guard(present=lambda f: here[0], client=lambda: True,
                                    unblock=unblock)
    g.check()
    watch(g, clock, GONE_AFTER + 2)
    assert len(clicks) == 1 and g.unblocked == 1
    assert any(getattr(e, "message", "") == "answered No" for e in said)
    assert watch(g, clock, 3) is False
    watch(g, clock, 120)
    assert stopped == [], "a box the run closed itself must not rejoin"


def test_an_unblock_that_throws_keeps_the_old_hold():
    g, clock, stopped, _ = guard(present=lambda f: False, client=lambda: True,
                                 unblock=lambda f: 1 / 0)
    g.check()
    watch(g, clock, 200)
    assert stopped == [True] and g.unblocked == 0


def test_a_live_world_is_never_reported_gone():
    g, clock, stopped, _ = guard()
    for _ in range(50):
        assert g.check() is False
        clock.tick(1.0)
    assert stopped == []


def test_a_brief_absence_is_not_a_dead_game():
    """A death, a respawn, a loading screen. None of them means gone."""
    here = [True]
    g, clock, stopped, _ = guard(present=lambda f: here[0])
    g.check()
    here[0] = False
    for _ in range(int(GONE_AFTER) - 2):
        clock.tick(1.0)
        assert g.check() is False
    assert stopped == []


def test_a_long_absence_is_reported_once():
    g, clock, stopped, said = guard(present=lambda f: False)
    g.check()
    assert watch(g, clock, GONE_AFTER + 1) is True
    watch(g, clock, 100)
    assert stopped == [True], "it announced the same death twice"
    assert sum("off screen" in getattr(e, "message", "") for e in said) == 1


def test_the_clock_starts_when_the_hud_goes_not_when_the_guard_does():
    here = [True]
    g, clock, stopped, _ = guard(present=lambda f: here[0])
    clock.tick(300)             # a long, healthy session
    g.check()
    here[0] = False
    g.check()
    assert watch(g, clock, GONE_AFTER - 1) is False, "it counted time from before the HUD vanished"
    assert watch(g, clock, 2) is True


def test_the_world_coming_back_clears_it():
    here = [True]
    g, clock, stopped, said = guard(present=lambda f: here[0])
    g.check()
    here[0] = False
    clock.tick(GONE_AFTER - 1)
    g.check()
    here[0] = True
    clock.tick(1)
    assert g.check() is False
    assert g.missing_since is None
    clock.tick(GONE_AFTER + 5)
    assert g.check() is False, "an absence that ended still killed the run"
    assert any("back on screen" in getattr(e, "message", "") for e in said)


def test_a_capture_failure_is_not_evidence_of_anything():
    """Not being able to look is not the same as looking and seeing nothing."""
    def angry():
        raise RuntimeError("capture timed out")

    g, clock, stopped, _ = guard(frames=angry)
    for _ in range(50):
        assert g.check() is False
        clock.tick(1.0)
    assert stopped == []


def test_a_missing_frame_counts_as_missing_world():
    g, clock, stopped, _ = guard(frames=lambda: None)
    g.check()
    assert watch(g, clock, GONE_AFTER + 1) is True


def test_it_does_not_look_more_often_than_asked():
    looks = []
    clock = FakeClock()
    g = WorldGuard(lambda: looks.append(1) or object(), lambda f: True,
                   clock=clock, check_every=0.5)
    for _ in range(10):
        g.check()               # ten calls at the same instant
    assert len(looks) == 1
    clock.tick(0.6)
    g.check()
    assert len(looks) == 2


def test_it_explains_itself_at_each_stage():
    here = [True]
    g, clock, _, _ = guard(present=lambda f: here[0])
    g.check()
    assert "on screen" in g.describe()
    here[0] = False
    g.check()
    assert "waiting" in g.describe()
    watch(g, clock, GONE_AFTER + 1)
    assert "game is gone" in g.describe()


# ---- DeathWatch: catching a death while the cause is still on screen ------
from hivemind.brain.alive import DEATH_MIN_POLLEN, DeathWatch      # noqa: E402


class Pill:
    def __init__(self, value):
        self.value = value


def watcher(values, **kw):
    clock = FakeClock()
    seen = []
    it = iter(values)
    w = DeathWatch(lambda: Pill(next(it)), on_death=lambda lost, v: seen.append(lost),
                   clock=clock, check_every=0.0, **kw)
    return w, clock, seen


def test_rising_pollen_is_never_a_death():
    w, clock, seen = watcher([100, 5_000, 50_000, 300_000])
    for _ in range(4):
        assert w.check() is False
        clock.tick(1)
    assert seen == []


def test_a_big_drop_is_a_death_and_says_how_much_was_lost():
    """REGRESSION for 2026-09-20: 362,313 -> 874, and the frames showed the
    hive because the drop was not noticed until a pattern pass later.

    The drop is confirmed by a SECOND low read, because a single one is also
    what a misread looks like -- the pill really was read as 60,053, 1,259,
    66,153, 1,259 inside two seconds. A death persists; a misread does not.
    """
    w, clock, seen = watcher([362_313, 874, 874])
    w.check(); clock.tick(1)
    assert w.check() is False          # one low read: not yet evidence
    clock.tick(1)
    assert w.check() is True           # it stayed empty, so it is real
    assert seen == [361_439]


def test_a_single_low_read_that_recovers_is_not_a_death():
    """MEASURED: 60,053 -> 1,259 -> 66,153. The counter cannot recover 65,000
    pollen in a second, so the low read was wrong and nobody died."""
    w, clock, seen = watcher([60_053, 1_259, 66_153, 66_153])
    for _ in range(4):
        w.check()
        clock.tick(1)
    assert seen == []


def test_a_small_dip_is_not_a_death():
    w, clock, seen = watcher([100_000, 80_000])
    w.check(); clock.tick(1)
    assert w.check() is False
    assert seen == []


def test_an_unreadable_pill_is_not_an_empty_backpack():
    clock = FakeClock()
    seen = []
    w = DeathWatch(lambda: Pill(None), on_death=lambda lost, v: seen.append(lost),
                   clock=clock, check_every=0.0)
    for _ in range(5):
        assert w.check() is False
        clock.tick(1)
    assert seen == []


def test_converting_is_not_a_death():
    w, clock, seen = watcher([500_000, 0])
    w.check()
    w.converted()
    clock.tick(1)
    assert w.check() is False
    assert seen == []


def test_too_little_at_stake_is_not_worth_calling_a_death():
    w, clock, seen = watcher([DEATH_MIN_POLLEN - 1, 0])
    w.check(); clock.tick(1)
    assert w.check() is False


def test_a_reader_that_throws_is_survived():
    def angry():
        raise RuntimeError("HUD gone")
    w = DeathWatch(angry, clock=FakeClock(), check_every=0.0)
    for _ in range(5):
        assert w.check() is False


def test_it_does_not_read_more_often_than_asked():
    reads = []
    clock = FakeClock()
    w = DeathWatch(lambda: reads.append(1) or Pill(10), clock=clock,
                   check_every=1.0)
    for _ in range(10):
        w.check()
    assert len(reads) == 1
    clock.tick(1.1)
    w.check()
    assert len(reads) == 2


# ---- converting is not dying ---------------------------------------------
# These pin the fix for a MEASURED false alarm: a real run converted 532,850
# pollen into 498,423 honey and the log reported two deaths inside two
# seconds. A false death is not cosmetic -- it cuts the current walk short and
# it saves an incident window, so genuine evidence gets buried under converts.
def _watch(values):
    """A DeathWatch reading a scripted list of pollen values."""
    from hivemind.brain.alive import DeathWatch

    class Reading:
        def __init__(self, value):
            self.value = value

    seen = iter(values)
    ticks = {"at": 0.0}

    def clock():
        ticks["at"] += 10.0
        return ticks["at"]

    deaths = []
    watch = DeathWatch(lambda: Reading(next(seen, None)),
                       on_death=lambda lost, value: deaths.append(lost),
                       clock=clock)
    return watch, deaths


def test_a_convert_is_not_reported_as_a_death():
    watch, deaths = _watch([500_000, 500_000, 250_000, 1_259, 1_259])
    watch.check()                 # peak recorded
    watch.suspend()               # the loop presses E
    watch.check()
    watch.check()
    watch.check()
    watch.resume()                # the dwell ends
    watch.check()
    assert deaths == []


def test_a_real_death_after_a_convert_is_still_reported():
    watch, deaths = _watch([1_000, 400_000, 400_000, 1_200, 1_200])
    watch.check()
    watch.suspend()
    watch.resume()                # backpack emptied on purpose, peak cleared
    watch.check()                 # 400,000 gathered since
    watch.check()
    watch.check()                 # and lost -- one low read, not yet evidence
    assert deaths == []
    watch.check()                 # still empty, so it really is a death
    assert deaths == [398_800]


def test_suspending_twice_needs_resuming_twice():
    watch, _ = _watch([100, 100, 100])
    watch.suspend()
    watch.suspend()
    watch.resume()
    assert watch.suspended is True
    watch.resume()
    assert watch.suspended is False


def test_nothing_is_reported_while_suspended():
    watch, deaths = _watch([900_000, 1_000])
    watch.check()
    watch.suspend()
    assert watch.check() is False
    assert deaths == []


def test_a_fall_that_leaves_a_well_filled_bag_is_a_link_not_a_death():
    # MEASURED 2026-10-06 01:34: a Link in Mushroom left 673,182 of 2,823,706,
    # and the watch filed it as a death there
    w, clock, seen = watcher([2_823_706, 673_182, 673_182])
    w.check(); clock.tick(1)
    w.check(); clock.tick(1)
    assert w.check() is False
    assert seen == [] and w.conversions == 1 and w.deaths == 0


def test_a_death_read_before_its_counter_settles_is_still_a_death():
    # MEASURED 2026-10-05 15:20 (run-654): 2,089,866 -> 13,421, the compass at
    # the hive a second later
    w, clock, seen = watcher([2_089_866, 13_421, 13_421])
    w.check(); clock.tick(1)
    w.check(); clock.tick(1)
    assert w.check() is True
    assert seen == [2_076_445]


def test_a_bag_converted_where_it_stands_is_not_a_death():
    """MEASURED 2026-10-06 22:47:15: 1,521,984 -> 1,076 in the Mushroom Field,
    the feed reading Coin Scatter and Conversion Link honey, and no death."""
    feed = "+273,957 Honey (from Coin Scatter) ⇄8,946 Honey (from Conversion Link)"
    w, clock, seen = watcher([1_521_984, 1_076, 1_076], feed=lambda: feed)
    w.check(); clock.tick(1)
    w.check(); clock.tick(1)
    assert w.check() is False and seen == [] and w.conversions == 1


def test_a_death_with_the_feed_saying_so_is_still_a_death():
    feed = "You died! Your bees must recover at the hive. +5 Honey (from Conversion Link)"
    w, clock, seen = watcher([1_521_984, 1_076, 1_076], feed=lambda: feed)
    w.check(); clock.tick(1)
    w.check(); clock.tick(1)
    assert w.check() is True and seen == [1_520_908]


def test_a_feed_reader_that_throws_leaves_the_death_watch_as_it_was():
    def broken():
        raise RuntimeError("no frame")
    w, clock, seen = watcher([362_313, 874, 874], feed=broken)
    w.check(); clock.tick(1)
    w.check(); clock.tick(1)
    assert w.check() is True and seen == [361_439]


def test_the_real_micro_converter_box_is_seen_as_a_dialog():
    """The frame the 11:54 16 Oct hold looked at (A25) is a Yes/No box the
    world guard's unblock answers; its No button shows red there."""
    from pathlib import Path

    import cv2
    import hivemind
    from hivemind.act import inventory
    root = Path(hivemind.__file__).resolve().parents[2]
    f = cv2.imread(str(root / "tests/fixtures/dialogs/micro_converter_hud_hold.jpg"))
    assert f is not None and inventory.dialog_open(f)
    clicks = []

    class Vin:
        def click(self, x, y):
            clicks.append((x, y))

    assert inventory.answer(Vin(), f, yes=False)
    x0, y0, x1, y1 = inventory.DIALOG_NO
    assert clicks == [((x0 + x1) // 2, (y0 + y1) // 2)]


def test_a_refused_kept_session_says_why(tmp_path):
    from hivemind.platform import session as S
    assert S.kept_session_why(tmp_path / "none.json", "x") == (None, "no kept-session record")
    p = tmp_path / "k.json"
    p.write_text('{"socket": "wayland-zz-gone", "signature": "s", "hypr_pid": 1}')
    rec, why = S.kept_session_why(p, "x")
    assert rec is None and "socket wayland-zz-gone is gone" in why


# ---- death_proof: a fall is a death only with proof (AREA deaths) ---------
class Frames:
    """A fake capture: the frame `own_health` reads as `hp` (None: no bar)."""
    def __init__(self):
        self.hp = None

    def __call__(self):
        return self


def proofed(values, monkeypatch, live, hp):
    from hivemind.brain import alive
    from hivemind.vision import hurt
    monkeypatch.setattr(alive, "DEATH_PROOF_LIVE", live)
    monkeypatch.setattr(hurt, "own_health", lambda f: f.hp)
    monkeypatch.setattr(alive, "death_proof",
                        lambda said, low, frame, row=None: "" if low is None or low > 0.05 else "hp")
    frames = Frames()
    logs = []
    w, clock, seen = watcher(values, frame=frames, emit=logs.append)
    for h in hp:
        frames.hp = h
        w.check()
        clock.tick(1)
    return w, seen, " ".join(getattr(e, "message", "") for e in logs)


def test_a_fall_with_no_proof_is_not_filed_when_live(monkeypatch):
    w, seen, said = proofed([300_000, 900, 900], monkeypatch, True, [None] * 3)
    assert seen == [] and w.unproven == 1 and "not a death" in said


def test_a_fall_with_no_proof_is_only_logged_while_look_only(monkeypatch):
    w, seen, said = proofed([300_000, 900, 900], monkeypatch, False, [None] * 3)
    assert seen == [299_100] and "death proof would: veto" in said


def test_a_health_bar_at_zero_proves_the_death(monkeypatch):
    w, seen, said = proofed([300_000, 900, 900], monkeypatch, True, [0.4, 0.0, None])
    assert seen == [299_100]


def test_a_fall_with_no_frame_at_the_death_is_filed_even_when_live(monkeypatch):
    # the real death_proof, not a stub: a capture that fails must not veto
    from hivemind.brain import alive
    monkeypatch.setattr(alive, "DEATH_PROOF_LIVE", True)
    w, clock, seen = watcher([300_000, 900, 900], frame=lambda: None)
    for _ in range(3):
        w.check()
        clock.tick(1)
    assert seen == [299_100] and w.unproven == 0


def test_the_hive_row_proves_a_teleport_not_a_walk(monkeypatch):
    from hivemind.act import hive
    from hivemind.brain.alive import death_proof
    from hivemind.brain.alive import row_jump
    monkeypatch.setattr(hive, "hive_bearing", lambda f: (0, 120_000))
    teleport = [(0, 191_499), (1, 0), (2, 193_868)]                  # 055507
    walk = [(0, 21_889), (1, 38_786), (2, 63_211), (3, 168_848)]     # 023032
    assert death_proof("", None, object(), row_jump(teleport))
    assert not death_proof("", None, object(), row_jump(walk))
    assert not death_proof("", None, object(), None)

    def boom(f):
        raise ValueError("bad frame")
    monkeypatch.setattr(hive, "hive_bearing", boom)
    assert "filed" in death_proof("", None, object())


def test_the_incidents_of_20_21_oct_keep_the_5_deaths_and_veto_the_9_links():
    """REPLAY of var/incidents (owner's PC only): the last frame of each, and
    the health bar and the hive row about once a second over the last 10 s,
    as DeathWatch samples them (the row's jump, alive.row_jump).
    023032 was a walk home beside the hive, not a death (run-1101 02:30:42
    converted 320,377). The feed is not read here (tesseract); none needs it."""
    import re
    from pathlib import Path
    import cv2
    import pytest
    import hivemind
    from hivemind.act.hive import hive_bearing
    from hivemind.brain.alive import death_proof, row_jump
    from hivemind.vision.hurt import own_health
    base = Path(hivemind.__file__).resolve().parents[2] / "var" / "incidents"
    real = "20261020-020156 20261020-055507 20261020-071805 20261020-235620 20261021-060404"
    false = ("20261020-023021 20261021-095515 20261021-111040 20261021-111538 "
             "20261021-143237 20261021-180055 20261021-210935 20261021-213947 "
             "20261020-023032")
    if not (base / "20261021-060404-death").is_dir():
        pytest.skip("the incident frames live only on the owner's PC")

    def proof(name):
        frames = sorted((base / f"{name}-death").glob("*.jpg"))
        when = [float(re.search(r"t\+([\d.]+)s", f.name).group(1)) for f in frames]
        hp = [own_health(cv2.imread(str(f))) for f, t in zip(frames[::5], when[::5])
              if when[-1] - t <= 10.0]
        hp = [h for h in hp if h is not None]
        rows = [(t, hive_bearing(cv2.imread(str(f)))[1])
                for f, t in zip(frames[::5], when[::5]) if when[-1] - t <= 10.0]
        return death_proof("", min(hp) if hp else None, cv2.imread(str(frames[-1])),
                           row_jump(rows))
    assert all(proof(n) for n in real.split()), [n for n in real.split() if not proof(n)]
    assert not any(proof(n) for n in false.split()), [n for n in false.split() if proof(n)]


def test_a_falling_health_bar_with_a_big_bag_says_retreat_would(monkeypatch):
    """060404: 0.6 -> 0.4 -> 0 with 1,045,384 in the bag (RETREAT_HEALTH)."""
    w, seen, said = proofed([1_045_384, 1_045_384, 1_045_384, 1_045_384],
                            monkeypatch, False, [0.9, 0.4, 0.2, 0.0])
    assert said.count("retreat would:") == 1          # once per 10 s
    assert "reads 0.40 then 0.20" in said
    w, seen, said = proofed([30_000, 30_000], monkeypatch, False, [0.4, 0.2])
    assert "retreat would:" not in said               # too little at stake
    w, seen, said = proofed([1_045_384, None], monkeypatch, False, [0.5, 0.25])
    assert "reads 0.50 then 0.25" in said             # an unreadable pill


def test_retreat_needs_two_reads_in_a_row_and_no_flash():
    """docs/pending/retreat.md: one read is not enough, an exact 0.0 is the
    reader's flash, and a gap (an unread tick) breaks the pair."""
    from hivemind.brain.alive import retreat_due
    assert retreat_due([(0, 0.41), (1, 0.22)])             # 060404-like fall
    assert retreat_due([(0, 0.25), (1, 0.27)])             # low and refilling
    assert not retreat_due([(1, 0.22)])                    # one read
    assert not retreat_due([(0, 0.9), (1, 0.2)])           # older read not low
    assert not retreat_due([(0, 0.5), (1, 0.35)])          # newer not under 0.3
    assert not retreat_due([(0, 0.0), (1, 0.0)])           # 20261006-050424 flash
    assert not retreat_due([(0, 0.32), (1, 0.0)])
    assert not retreat_due([(0, 0.4), (3, 0.2)])           # not one tick apart


def test_the_saved_windows_retreat_before_the_deaths_and_not_on_flashes():
    """REPLAY of var/incidents (owner's PC only), 1 Hz as DeathWatch reads:
    the real falls say leave before the bar empties, the quiet flashes don't."""
    import re
    from pathlib import Path
    import cv2
    import pytest
    import hivemind
    from hivemind.brain.alive import retreat_due
    from hivemind.vision.hurt import own_health
    base = Path(hivemind.__file__).resolve().parents[2] / "var" / "incidents"
    if not (base / "20261021-060404-death").is_dir():
        pytest.skip("the incident frames live only on the owner's PC")

    def first_due(name, stop_at_empty=True):
        drawn, nxt = [], 0.0
        for f in sorted((base / name).glob("*.jpg")):
            t = float(re.search(r"t\+([\d.]+)s", f.name).group(1))
            if t < nxt:
                continue
            nxt = t + 1.0
            h = own_health(cv2.imread(str(f)))
            if h is None:
                continue
            drawn.append((t, h))
            if h <= 0.05 and stop_at_empty:
                return None                     # the bar emptied first
            if retreat_due(drawn):
                return t
        return None
    for name in ("20261021-060404-death", "20261020-020156-death",
                 "20261020-071805-death", "20261016-055717-death"):
        assert first_due(name) is not None, name
    for name in ("20261006-050424-mob-sighting", "20261005-031410-mob-sighting",
                 "20261010-045921-mob-sighting"):
        assert first_due(name, stop_at_empty=False) is None, name
