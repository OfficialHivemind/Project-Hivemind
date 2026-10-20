"""An ATTACHED session (a deploy that keeps the game, Session.attach) still
finds its own window on the desktop. MEASURED 2026-10-06:
after a kept deploy the game's window was minimized and the bot froze for 3.5
minutes on a capture that never came -- the window guard asked KWin about
`self.proc`'s pid, and an attached session has no proc, only `pid`."""
from __future__ import annotations


def test_an_attached_session_sees_its_window_minimized(monkeypatch):
    from hivemind.platform import session as mod
    s = mod.Session.attach({"socket": "wayland-1", "signature": "sig", "hypr_pid": 4242})
    assert s.proc is None and s.compositor_pid() == 4242

    class Out:
        def __init__(self, text):
            self.stdout = text

    def run(cmd, **k):
        if "/WindowsRunner" in cmd:
            return Out("[{0_{11111111-2222-3333-4444-555555555555}}]")
        return Out("pid: 4242\nminimized: true\nresourceClass: aquamarine\n")
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(mod.subprocess, "run", run)
    assert s.host_window_minimized() is True
