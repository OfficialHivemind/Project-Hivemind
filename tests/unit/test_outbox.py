"""The outbox (scripts/telegram_alerts.py): a send that fails for the network
is kept in var/outbox.jsonl and sent again later, with back-off, once per
message, at most OUTBOX_MAX and a day old; a refusal is not kept. And the
hourly stats card's switch (scripts/daily_card.py --hourly). No network: the
Bot API and curl are patched; nothing touches the real var/ or ~/.config."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tg = _load("telegram_alerts_outbox", "telegram_alerts.py")
OFFLINE = urllib.error.URLError(OSError(-2, "Name or service not known"))


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A temp outbox and env; `net` decides whether the fake Bot API answers."""
    env = tmp_path / "telegram.env"
    env.write_text("TELEGRAM_TOKEN=1:fake\nTELEGRAM_CHAT=111\n")
    monkeypatch.setattr(tg, "ENV", env)
    monkeypatch.setattr(tg, "DISCORD_ENV", tmp_path / "discord.env")
    monkeypatch.setattr(tg, "OUTBOX", tmp_path / "outbox.jsonl")
    monkeypatch.setattr(tg, "honey_line", lambda: "")
    net = {"up": False, "sent": []}

    def api(method, token=None, wait=70, **params):
        if not net["up"]:
            raise net.get("error", OFFLINE)
        net["sent"].append(params["text"])
        return {"ok": True}
    monkeypatch.setattr(tg, "api", api)
    return net


def rows():
    return tg._outbox_rows()


def test_a_failed_send_is_kept_retried_with_back_off_and_sent_late(box):
    tg.send("Knocked out: 1,502 pollen lost.")
    [row] = rows()
    assert row["channel"] == "telegram" and row["tries"] == 0
    at = row["at"]
    assert tg.outbox_flush(now=at + 30) == 0 and rows()[0]["tries"] == 0      # not due yet
    assert tg.outbox_flush(now=at + 61) == 0                                  # still offline
    assert rows()[0]["tries"] == 1 and rows()[0]["next"] == pytest.approx(at + 61 + 120)
    assert tg.outbox_flush(now=at + 62) == 0 and rows()[0]["tries"] == 1      # waits
    box["up"] = True
    assert tg.outbox_flush(now=at + 182) == 1 and rows() == []
    [said] = box["sent"]
    assert said.startswith("🐝 ⏳ from ") and said.endswith("Knocked out: 1,502 pollen lost.")


def test_once_per_message_at_most_fifty_and_a_day(box):
    tg.send("same")
    tg.send("same")
    assert len(rows()) == 1
    for i in range(tg.OUTBOX_MAX + 5):
        tg.send(f"alert {i}")
    texts = [r["text"] for r in rows()]
    assert len(texts) == tg.OUTBOX_MAX and texts[-1] == f"alert {tg.OUTBOX_MAX + 4}"
    assert "same" not in texts                                               # the oldest went
    box["up"] = True
    assert tg.outbox_flush(now=rows()[-1]["at"] + tg.OUTBOX_AGE_S + 1) == 0  # a day old: dropped
    assert rows() == [] and box["sent"] == []


def test_back_off_stops_at_an_hour_and_one_failure_ends_the_round(box):
    tg.send("a")
    tg.send("b")
    first = rows()[0]["at"]
    now = first
    for _ in range(10):
        now = rows()[0]["next"]
        tg.outbox_flush(now=now)
    a, b = rows()
    assert a["tries"] == 10 and a["next"] - now == tg.OUTBOX_LONGEST_S
    assert b["tries"] == 0                       # never tried: the network was down


def test_a_refusal_or_no_setup_is_not_kept(box):
    box["error"] = urllib.error.HTTPError("u", 400, "Bad Request: chat not found", {}, None)
    tg.send("x")
    box["error"] = RuntimeError("no bot token saved yet (Hivemind's Telegram tab)")
    tg.send("y")
    assert rows() == []
    box["error"] = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
    tg.send("z")
    assert [r["text"] for r in rows()] == ["z"]


def _curl(code=0, out="", seen=None):
    def run(cmd, **kw):
        if seen is not None:
            seen.append(cmd)
        return subprocess.CompletedProcess(cmd, code, out, "")
    return run


def test_a_card_not_sent_for_dns_is_kept_with_its_own_copy(box, tmp_path, monkeypatch):
    card = tmp_path / "daily_card.png"
    card.write_bytes(b"png")
    monkeypatch.setattr(tg.subprocess, "run", _curl(6))                     # curl: no DNS
    with pytest.raises(tg.Offline, match="curl exit 6 -- kept in the outbox"):
        tg.post_photo(card, "🐝 Hivemind's last 4 hours")
    [row] = rows()
    kept = Path(row["image"])
    assert row["text"] == "Hivemind's last 4 hours" and kept.read_bytes() == b"png"
    card.write_bytes(b"the next card")                                      # overwritten
    seen = []
    monkeypatch.setattr(tg.subprocess, "run", _curl(0, json.dumps({"ok": True}), seen))
    assert tg.outbox_flush(now=row["next"]) == 1
    assert f"photo=@{kept}" in seen[0] and not kept.exists() and rows() == []
    # Telegram's own refusal is a RuntimeError, not kept
    monkeypatch.setattr(tg.subprocess, "run", _curl(0, json.dumps(
        {"ok": False, "error_code": 400, "description": "Bad Request: wrong file"})))
    with pytest.raises(RuntimeError) as err:
        tg.post_photo(card, "x")
    assert not isinstance(err.value, tg.Offline) and rows() == []


def test_discord_keeps_a_network_failure_not_a_dead_webhook(box, monkeypatch):
    tg.DISCORD_ENV.write_text("DISCORD_WEBHOOK=https://discord.com/api/webhooks/1/x\n")
    monkeypatch.setattr(tg.subprocess, "run", _curl(0, "404"))
    assert not tg.discord_send("x") and rows() == []
    monkeypatch.setattr(tg.subprocess, "run", _curl(7, "000"))
    assert not tg.discord_send("The bot hit an error", ping=True)
    [row] = rows()
    assert row["channel"] == "discord" and row["ping"] is True
    assert "discord.com" not in tg.OUTBOX.read_text(encoding="utf-8")    # never the secret
    seen = []
    monkeypatch.setattr(tg.subprocess, "run", _curl(0, "204", seen))
    assert tg.outbox_flush(now=row["next"]) == 1 and rows() == []
    assert "⏳ from" in json.loads(seen[0][seen[0].index("-d") + 1])["content"]


def test_discord_still_down_does_not_hold_back_telegram(box, monkeypatch):
    tg.DISCORD_ENV.write_text("DISCORD_WEBHOOK=https://discord.com/api/webhooks/1/x\n")
    monkeypatch.setattr(tg.subprocess, "run", _curl(7, "000"))           # Discord unreachable
    assert not tg.discord_send("older, on Discord")
    tg.send("newer, on Telegram")
    d, t = rows()
    box["up"] = True                                                    # Telegram is back
    assert tg.outbox_flush(now=t["next"]) == 1
    [left] = rows()
    assert left["channel"] == "discord" and left["tries"] == 1
    tg.DISCORD_ENV.unlink()                                             # webhook removed: dropped
    assert tg.outbox_flush(now=left["next"]) == 1 and rows() == []


# ---- the hourly card -------------------------------------------------------------
def test_the_hourly_card_follows_its_switch(monkeypatch, tmp_path):
    dc = _load("daily_card_hourly", "daily_card.py")
    on = {"telegram.hourly_card": True, "telegram.stats_cards": "every 4 hours + daily"}
    assert [h for h in range(24) if not dc.hourly_due(on, h)] == [9, 13, 17, 21]
    assert not any(dc.hourly_due({**on, "telegram.hourly_card": False}, h) for h in range(24))
    drawn = []
    monkeypatch.setattr(dc, "render", lambda s, out, day: drawn.append(out) or out)
    monkeypatch.setattr(dc, "stats", lambda hours: {"hours": hours})
    monkeypatch.setattr(dc.tg, "post_photo", lambda path, caption: drawn.append(caption))
    monkeypatch.setattr(dc.time, "localtime", lambda *a: dc.time.struct_time(
        (2026, 10, 27, 10, 0, 0, 1, 300, 0)))
    monkeypatch.setattr(dc.tg, "toggles", lambda: {**on, "telegram.hourly_card": False})
    monkeypatch.setattr(sys, "argv", ["daily_card.py", "--hours", "1", "--send", "--hourly"])
    dc.main()
    assert drawn == []                                    # off by default: nothing drawn
    monkeypatch.setattr(dc.tg, "toggles", lambda: on)
    dc.main()
    assert drawn[0].name == "hourly_card.png" and "last hour" in drawn[1]
    # the service starts it only with the switch on
    started = []
    monkeypatch.setattr(tg, "toggles", lambda: {"telegram.hourly_card": False})
    monkeypatch.setattr(tg.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    assert tg.hourly_card(None) is None and started == []
    monkeypatch.setattr(tg, "toggles", lambda: {"telegram.hourly_card": True})
    tg.hourly_card(None)
    assert started[0][2:] == ["--hours", "1", "--send", "--hourly"]
