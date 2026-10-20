"""A held Alt let go of inside the nested compositor (platform/session
release_alt): both Alts sent up to the game's window by Hyprland's own
key-state dispatcher, never a key down."""
from __future__ import annotations


def test_both_alts_are_sent_up_to_the_game(monkeypatch):
    from hivemind.platform import session as mod
    s = mod.Session.__new__(mod.Session)
    s.signature = "sig_1"
    calls = []

    class Done:
        stdout = "ok\n"

    def run(cmd, env=None, **k):
        calls.append((cmd, env.get("HYPRLAND_INSTANCE_SIGNATURE")))
        return Done()
    monkeypatch.setattr(mod.subprocess, "run", run)
    said = s.release_alt()
    assert said == "Alt_L up: ok, Alt_R up: ok"
    assert [c[1] for c in calls] == ["sig_1", "sig_1"]
    for cmd, _sig in calls:
        assert cmd[:2] == ["hyprctl", "dispatch"]
        assert 'state = "up"' in cmd[2] and "org.vinegarhq.Sober" in cmd[2]
        assert '"down"' not in cmd[2]


def test_no_compositor_no_call(monkeypatch):
    from hivemind.platform import session as mod
    s = mod.Session.__new__(mod.Session)
    s.signature = None
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert s.release_alt() == "no compositor to ask"
