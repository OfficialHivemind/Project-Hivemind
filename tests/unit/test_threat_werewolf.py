"""28 Oct Pumpkin deaths: a Werewolf's red disc with no bar in view was
walked past. Look-only: within WEREWOLF_DISC_S of a Werewolf feed line, a
big disc is a 'would: count' line; small discs and no Werewolf stay ignored."""
import numpy as np

from hivemind.brain import threat
from hivemind.vision import hurt


def _watch(monkeypatch, fraction, clock):
    monkeypatch.setattr(threat.nameplate, "find_all", lambda *a, **k: [])
    monkeypatch.setattr(threat.nameplate, "hurt_bars", lambda *a, **k: [])
    monkeypatch.setattr(hurt, "find", lambda f: hurt.Hurt(900, 500, 400, 400, fraction))
    notes = []
    w = threat.ThreatWatch(lambda: np.zeros((1080, 1920, 3), np.uint8), skip_top=0,
                           clock=lambda: clock[0], on_ignored=notes.append)
    return w, notes


def test_a_big_disc_after_a_werewolf_is_a_would_line(monkeypatch):
    clock = [100.0]
    w, notes = _watch(monkeypatch, 0.17, clock)   # MEASURED 17% at 18:04 on 28 Oct
    w.heard_mob("werewolf")
    clock[0] += 60
    assert w.look() == []                          # look-only: nothing counted yet
    assert w.werewolf_disc_would == 1 and "would: count" in notes[-1]


def test_no_werewolf_or_a_small_disc_stays_ignored(monkeypatch):
    clock = [100.0]
    w, _ = _watch(monkeypatch, 0.17, clock)
    w.look()
    assert w.werewolf_disc_would == 0 and w.discs_ignored == 1
    w2, _ = _watch(monkeypatch, 0.04, clock)       # the bees' own small disc
    w2.heard_mob("werewolf")
    w2.look()
    assert w2.werewolf_disc_would == 0


def test_the_werewolf_window_runs_out(monkeypatch):
    clock = [100.0]
    w, _ = _watch(monkeypatch, 0.17, clock)
    w.heard_mob("Werewolf")
    clock[0] += threat.WEREWOLF_DISC_S + 1
    w.look()
    assert w.werewolf_disc_would == 0
