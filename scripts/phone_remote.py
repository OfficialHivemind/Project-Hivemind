#!/usr/bin/env python3
"""Phone remote on the home network (ROADMAP WIN-4): no cloud, no account.

  phone_remote.py [--port N]    serve; prints the address to open on the phone

A small web page on this PC: the bot's status line (telegram_alerts.status_text,
the same words as Telegram's /status), the live view picture, and Play/Stop
buttons. Pure stdlib, so it runs on the system python like telegram_alerts.

A SECRET KEY in the address: made once (secrets.token_urlsafe), kept in
<config>/phone_remote.env (0600); any request without it gets 403 and nothing
else. Plain HTTP: the key is readable on the home network, so do not run this
on a shared or public Wi-Fi. Delete the file for a new key.

LOOK-ONLY: Play/Stop from another device on the network is a new way to start
the character moving or lift its keys, so with PHONE_REMOTE_LIVE off they only
answer "would: ...". Live, they call the SAME telegram_alerts.ask_play (the
window's start-on-boot gates, itself look-only while autostart.PHONE_START_LIVE
is off) and stop_bot (Hivemind's clean Stop).
"""
import hmac
import html
import importlib.util
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("telegram_alerts", HERE / "telegram_alerts.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)
from hivemind.datapaths import config_dir  # noqa: E402  (telegram_alerts put src on the path)

PHONE_REMOTE_LIVE = False
PORT = 8765                      # any free port; --port changes it
KEY_FILE = "phone_remote.env"


def key(path: Path | None = None) -> str:
    """The secret in the address: read, or made once (0600)."""
    path = path or config_dir() / KEY_FILE
    try:
        found = path.read_text().strip().partition("PHONE_KEY=")[2]
        if found:
            return found
    except OSError:
        pass
    new = secrets.token_urlsafe(18)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"PHONE_KEY={new}\n")
    return new


def act(what: str) -> str:
    """Play or Stop, look-only while PHONE_REMOTE_LIVE is off."""
    if not PHONE_REMOTE_LIVE:
        return f"would: {'ask Hivemind to start farming' if what == 'play' else 'stop the bot'}" \
               " (the phone remote is look-only for now)."
    return tg.ask_play() if what == "play" else tg.stop_bot()


def page(k: str, note: str = "") -> str:
    k = html.escape(k)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Hivemind</title>
<style>body{{font-family:sans-serif;margin:16px;background:#111;color:#eee}}
img{{width:100%;border-radius:8px}}button{{font-size:1.2em;padding:12px 24px;margin:4px}}</style>
</head><body><h2>Hivemind</h2>
<p>{html.escape(note)}</p><p>{html.escape(tg.status_text())}</p>
<img src="/{k}/live.jpg" alt="live view (none yet)">
<form method="post"><button formaction="/{k}/play">Play</button>
<button formaction="/{k}/stop">Stop</button></form>
<p><a href="/{k}/" style="color:#9cf">Refresh</a></p></body></html>"""


class Handler(BaseHTTPRequestHandler):
    KEY = ""

    def _route(self):
        """The path after a right key, or None (403 already sent)."""
        _, k, rest = (self.path.split("?")[0] + "/").split("/", 2)
        if not self.KEY or not hmac.compare_digest(k.encode(), self.KEY.encode()):
            self.send_error(403)
            return None
        return rest.strip("/")

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = self._route()
        if route is None:
            return
        if route == "live.jpg":
            try:
                return self._send(tg.LIVE_VIEW.read_bytes(), "image/jpeg")
            except OSError:
                return self.send_error(404)
        if route:
            return self.send_error(404)
        self._send(page(self.KEY).encode(), "text/html; charset=utf-8")

    def do_POST(self):
        route = self._route()
        if route is None:
            return
        if route not in ("play", "stop"):
            return self.send_error(404)
        note = act(route)
        print(f"phone remote: {route}: {note}", flush=True)
        self._send(page(self.KEY, note).encode(), "text/html; charset=utf-8")

    def log_message(self, *_):            # the key is in every path: never logged
        pass


def main(argv: list) -> None:
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else PORT
    Handler.KEY = key()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Phone remote on port {port}: open http://<this PC's address>:{port}/<key>/ "
          f"on a phone on the same network; the key is in {config_dir() / KEY_FILE}.",
          flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
