"""Phone remote on the home network (ROADMAP WIN-4): the secret key gates
every request, Play/Stop are look-only while PHONE_REMOTE_LIVE is off. A real
server on 127.0.0.1 and a free port; temp files only, nothing reaches the bot."""
from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("phone_remote", ROOT / "scripts" / "phone_remote.py")
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)


def test_ships_look_only():
    assert pr.PHONE_REMOTE_LIVE is False
    assert pr.act("play").startswith("would: ask Hivemind to start")
    assert pr.act("stop").startswith("would: stop the bot")


def test_key_is_made_once_and_private(tmp_path):
    path = tmp_path / "phone_remote.env"
    k = pr.key(path)
    assert len(k) >= 20 and pr.key(path) == k
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_server_needs_the_key(tmp_path, monkeypatch):
    monkeypatch.setattr(pr.tg, "status_text", lambda: "The bot is running.")
    monkeypatch.setattr(pr.tg, "LIVE_VIEW", tmp_path / "live.jpg")
    (tmp_path / "live.jpg").write_bytes(b"\xff\xd8jpeg")
    called = []
    monkeypatch.setattr(pr.tg, "stop_bot", lambda: called.append("stop"))
    monkeypatch.setattr(pr.Handler, "KEY", "s3cret")
    server = pr.ThreadingHTTPServer(("127.0.0.1", 0), pr.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def get(path, data=None):
        try:
            with urllib.request.urlopen(base + path, data=data, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""
    try:
        for bad in ("/", "/wrong/", "/wrong/live.jpg", "//live.jpg"):
            assert get(bad)[0] == 403
        assert get("/wrong/stop", b"")[0] == 403
        code, body = get("/s3cret/")
        assert code == 200 and b"The bot is running." in body
        assert get("/s3cret/live.jpg") == (200, b"\xff\xd8jpeg")
        code, body = get("/s3cret/stop", b"")
        assert code == 200 and b"would: stop the bot" in body and not called
        assert get("/s3cret/nope", b"")[0] == 404
    finally:
        server.shutdown()
