"""Telegram commands (scripts/telegram_alerts.py): only the owner's chat can
command, each command reaches the bot's own control, and everything else
still reaches Claude's --listen. No network (the Bot API is patched), no real
~/.config/hivemind, no real bot (a test EventServer on a temp socket)."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
_spec = importlib.util.spec_from_file_location("telegram_alerts_cmds",
                                               ROOT / "scripts" / "telegram_alerts.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)

OWNER, STRANGER = 111, 999


def msg(text, chat=OWNER, age=0.0):
    return {"chat": {"id": chat, "type": "private"}, "text": text,
            "date": time.time() - age}


@pytest.fixture
def bot(tmp_path, monkeypatch):
    """Temp files, a fake Bot API and a fake bot socket; what each saw."""
    env = tmp_path / "telegram.env"
    env.write_text(f"TELEGRAM_TOKEN=1:fake\nTELEGRAM_CHAT={OWNER}\n")
    for name, path in (("ENV", env), ("HANDLED", tmp_path / "telegram.handled"),
                       ("BEAT", tmp_path / "telegram.listening"),
                       ("SETTINGS", tmp_path / "settings.yaml"),
                       ("NIGHT", tmp_path / "night"), ("ROOT", tmp_path),
                       ("LIVE_VIEW", tmp_path / "live.jpg")):
        monkeypatch.setattr(tg, name, path)
    tg.SETTINGS.write_text("telegram.commands: true\n")    # ships off (U15b)
    seen = {"sent": [], "photos": [], "socket": [], "updates": [], "polls": 0}

    def api(method, token=None, wait=70, **params):
        if method == "sendMessage":
            assert str(params["chat_id"]) == str(OWNER)
            seen["sent"].append(params["text"])
            return {"ok": True}
        assert method == "getUpdates"
        seen["polls"] += 1
        if seen["polls"] > 1 and seen.get("stop_after_one"):
            raise KeyboardInterrupt                  # ends --listen's loop
        off = int(params.get("offset") or 0)
        return {"result": [u for u in seen["updates"] if u["update_id"] >= off]}

    def bot_socket(command=None, read_s=0.0):
        seen["socket"].append(command)
        return [{"kind": "status", "running": True, "paused": False, "note": ""},
                {"kind": "metric", "name": "honey", "value": 12_345_678},
                {"kind": "metric", "name": "honey_per_hour", "value": 431_000},
                {"kind": "task", "name": "gather", "status": "running",
                 "detail": "Pine Tree"}]

    monkeypatch.setattr(tg, "api", api)
    monkeypatch.setattr(tg, "bot_socket", bot_socket)
    monkeypatch.setattr(tg, "post_photo", lambda path, caption: seen["photos"].append(caption))
    monkeypatch.setattr(tg, "farm_running", lambda: False)
    return seen


def updates(*messages):
    return [{"update_id": 500 + i, "message": m} for i, m in enumerate(messages)]


def test_only_the_owners_chat_commands(bot):
    bot["updates"] = updates(msg("/stop", chat=STRANGER), msg("/pause", chat=STRANGER),
                             msg("/pause"))
    tg.serve_commands(claude_here=True)
    assert bot["socket"] == ["pause"]                # the stranger's two: nothing
    assert tg.ENV.with_name("telegram.offset").read_text() == "503"


def test_each_command_reaches_its_control(bot, monkeypatch, tmp_path):
    for name in ("pause", "resume"):
        bot["socket"].clear()
        tg.run_command(name, msg("/" + name))
        assert bot["socket"] == [name]
    # /stop: STOP for the watchdog (alive) and the socket's Command STOP --
    # nothing signalled
    from hivemind.gui import launcher
    monkeypatch.setattr(launcher.BotProcess, "watchdog_pid", lambda self: 4242)
    bot["socket"].clear()
    answer = tg.run_command("stop", msg("/stop"))
    assert bot["socket"] == ["stop"] and (tmp_path / "var/night/STOP").exists()
    assert "watchdog will not relaunch" in answer
    # /status: the bot's own replayed state
    assert "12,345,678" in tg.run_command("status", msg("/status"))
    assert "431,000 an hour" in bot["sent"][-1] and "Pine Tree" in bot["sent"][-1]
    # /screenshot: the live view as a photo, only while it is fresh
    tg.run_command("screenshot", msg("/screenshot"))
    assert not bot["photos"] and "No live view" in bot["sent"][-1]
    tg.LIVE_VIEW.write_bytes(b"\xff\xd8jpg")
    tg.run_command("screenshot", msg("/screenshot"))
    assert bot["photos"] and bot["photos"][-1].startswith("🐝 The live view")
    # /report: today's honey/h (benchmark --today, ROADMAP P4) on top of the
    # status, then daily_card's own --send --now
    ran = []
    monkeypatch.setattr(tg.subprocess, "run",
                        lambda argv, **kw: ran.append(argv) or
                        type("R", (), {"returncode": 0, "stderr": "",
                                       "stdout": "Honey/hr today: 98.2M (x)\n"})())
    tg.run_command("report", msg("/report"))
    assert ran[0][1].endswith("benchmark.py") and ran[0][2:] == ["--today"]
    assert ran[1][1].endswith("daily_card.py") and ran[1][2:] == ["--send", "--now"]
    assert bot["sent"][-1].startswith("🐝 Honey/hr today: 98.2M (x)\nThe bot is")


def test_stop_with_no_bot_says_so_and_sets_nothing(bot, monkeypatch, tmp_path):
    from hivemind.gui import launcher
    monkeypatch.setattr(launcher.BotProcess, "watchdog_pid", lambda self: None)
    monkeypatch.setattr(tg, "bot_socket", lambda command=None, read_s=0.0: None)
    assert tg.run_command("stop", msg("/stop")).startswith("Nothing to stop")
    assert not (tmp_path / "var/night/STOP").exists()


def test_an_old_command_is_not_acted_on(bot):
    answer = tg.run_command("pause", msg("/pause", age=tg.COMMAND_MAX_AGE_S + 5))
    assert bot["socket"] == [] and "not acted on" in answer


def test_listen_answers_commands_and_still_prints_the_rest(bot, capsys):
    bot["stop_after_one"] = True
    bot["updates"] = updates(msg("hello claude"), msg("/pause"), msg("/stop", chat=STRANGER),
                             msg("/pause please"))
    with pytest.raises(KeyboardInterrupt):
        tg.listen()
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "telegram from the owner: hello claude"
    assert out[1].startswith("telegram command from the owner: /pause -- answered: Pausing")
    assert out[2] == "telegram from the owner: /pause please"      # not exactly a command
    assert len(out) == 3 and bot["socket"] == ["pause"]


def test_the_switch_off_makes_them_ordinary_messages(bot, capsys):
    tg.SETTINGS.write_text("telegram.commands: false\n")
    bot["stop_after_one"] = True
    bot["updates"] = updates(msg("/pause"))
    with pytest.raises(KeyboardInterrupt):
        tg.listen()
    assert capsys.readouterr().out == "telegram from the owner: /pause\n"
    assert bot["socket"] == []


def test_while_claude_is_away_his_messages_wait_and_a_command_runs_once(bot):
    bot["updates"] = updates(msg("/status"), msg("are you there"), msg("/pause"))
    tg.serve_commands(claude_here=True)
    tg.serve_commands(claude_here=True)              # the next poll: no repeat
    assert bot["socket"].count("pause") == 1
    # the offset stops at his message, for Claude's --listen when it is back
    assert tg.ENV.with_name("telegram.offset").read_text() == "501"
    assert json.loads(tg.HANDLED.read_text()) == [500, 502]


def test_with_no_claude_on_the_machine_the_rest_gets_the_help(bot):
    bot["updates"] = updates(msg("hi"))
    tg.serve_commands(claude_here=False)
    assert bot["sent"] == ["🐝 " + tg.HELP]
    assert tg.ENV.with_name("telegram.offset").read_text() == "501"


@pytest.mark.skipif(os.name == "nt", reason="a Unix socket path; Windows uses loopback TCP")
def test_the_bot_socket_carries_the_guis_command(monkeypatch):
    from hivemind.ipc import bus
    from hivemind.telemetry.events import Action, Command, Metric
    path = str(Path(tempfile.mkdtemp()) / "s.sock")
    got = []
    server = bus.EventServer(path=path, on_message=got.append).start()
    try:
        server.send(Metric(name="honey", value=5.0))
        time.sleep(0.2)
        monkeypatch.setattr(bus, "DEFAULT_SOCKET", path)
        rows = tg.bot_socket("pause", read_s=0.5)
        deadline = time.time() + 3
        while not got and time.time() < deadline:
            time.sleep(0.05)
    finally:
        server.stop()
    assert isinstance(got[0], Command) and got[0].action == Action.PAUSE
    assert any(r.get("name") == "honey" for r in rows)
    monkeypatch.setattr(bus, "DEFAULT_SOCKET", path + ".gone")
    assert tg.bot_socket("pause") is None


def test_the_hourly_self_review_is_laid_out_not_a_blob():
    # OWNER 2026-10-21: "its jsut a blob of text" -- the real 16:12 line, cut down
    line = ("7 trip(s), 6 converted, 75.3M pollen (76.9M/h); what cost me: the walk home x2"
            " -- the one to fix next: the walk home | haste up made 1.2x the rate"
            " | My plan: gather in pine tree; nectar comforting 55% | Learning: press 0.45 is best")
    tg._LAST_RATE[:] = []
    first = tg.review_text(line).splitlines()
    assert first[0] == "🐝 Hourly self-review" and "📊 7 trip(s), 6 converted" in first[1]
    assert "⚠️ Cost me time: the walk home x2" in first and "🔧 Fix next: the walk home" in first
    assert first[first.index("🗺 Plan now:") + 1:first.index("🧪 Testing:")] == [
        "  • gather in pine tree", "  • nectar comforting 55%"]
    assert "  • haste up made 1.2x the rate" in first and not any("vs last" in x for x in first)
    again = tg.review_text(line.replace("76.9M/h", "84.6M/h"))
    assert "📈 vs last hour: +10% pollen/h" in again
