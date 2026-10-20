"""Settings from Telegram (ROADMAP tgset): /settings, /set, /preset, /logs.
The deny-list, the one-setting writer and the preset loader
(world/remote_settings) on a temp config; the Telegram side with the Bot API
and the bot socket faked (no network, no real ~/.config/hivemind)."""
from __future__ import annotations

import getpass
import importlib.util
import os
import tempfile
import time
from pathlib import Path

import pytest
import yaml

from hivemind.telemetry.events import Action, Command, from_json
from hivemind.world import remote_settings as rs
from hivemind.world.settings import LOCKED, NOT_IN_PRESETS, SECRET, defaults

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
_spec = importlib.util.spec_from_file_location("telegram_alerts_settings",
                                               ROOT / "scripts" / "telegram_alerts.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)

OWNER, STRANGER = 111, 999


def msg(text, chat=OWNER):
    return {"chat": {"id": chat, "type": "private"}, "text": text, "date": time.time()}


def test_the_phone_never_reaches_secrets_account_pc_or_safety():
    for key in [*SECRET, *LOCKED, *NOT_IN_PRESETS, "account.username", "server.join",
                "telegram.commands", "guard.enabled", "safety.panic_key", "perf.vlm",
                "stream.private_words", "autonomy.max_spend", "eggs.save_diamond",
                "move.hive_slot", "move.walkspeed", "plan.goal", "x.robux_buy"]:
        assert rs.denied(key), key
    for key in ("gather.convert_at", "gather.field", "economy.buy", "quests.enabled"):
        assert rs.denied(key) == "", key
    # the schema's keys the phone may change: none of them a secret
    open_keys = [k for k in defaults() if not rs.denied(k)]
    assert open_keys and not set(open_keys) & (set(SECRET) | set(LOCKED) | NOT_IN_PRESETS)


def test_set_one_writes_one_checked_value(tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text("gather.convert_at: 95\naccount.username: someone\n")
    said = rs.set_one("gather.convert_at", "90", cfg)
    assert said.startswith("Set: ") and "95 -> 90" in said and "/set gather.convert_at 95" in said
    stored = yaml.safe_load(cfg.read_text())
    assert stored == {"gather.convert_at": 90, "account.username": "someone"}
    assert "already 90" in rs.set_one("gather.convert_at", "90", cfg)
    assert "-> on" in rs.set_one("economy.buy", "ON", cfg)
    assert "-> Pine Tree" in rs.set_one("gather.field", "pine tree", cfg)
    assert "outside" in rs.set_one("gather.convert_at", "500", cfg)     # settled to 100
    assert yaml.safe_load(cfg.read_text())["gather.convert_at"] == 100
    before = cfg.read_bytes()
    for key, value in (("account.username", "x"), ("server.link", "https://x"),
                       ("telegram.commands", "off"), ("gather.convert_at", "lots"),
                       ("gather.field", "Moon"), ("economy.buy", "maybe"),
                       ("macro.fields", "[]"), ("gather.convert_att", "90"),
                       ("gather.convert_at", "nan"), ("move.glide_scale", "inf")):
        assert "Nothing was changed" in rs.set_one(key, value, cfg), key
    assert cfg.read_bytes() == before
    assert "Closest: gather.convert_at" in rs.set_one("gather.convert_att", "90", cfg)


def test_a_preset_loads_without_the_denied_keys(tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text("gather.convert_at: 95\ntelegram.commands: true\n")
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "Night Farm.yaml").write_text(yaml.safe_dump({
        "gather.convert_at": 80, "economy.buy": True, "telegram.commands": False,
        "account.username": "someone", "server.link": "https://www.roblox.com/share?code=1",
        "guard.enabled": False, "not.a.key": 1}))
    said = rs.apply_preset("night  farm", cfg)
    assert said.startswith("Preset Night Farm loaded: 2 setting(s) changed"), said
    stored = yaml.safe_load(cfg.read_text())
    assert stored == {"gather.convert_at": 80, "economy.buy": True, "telegram.commands": True}
    assert not (tmp_path / "secrets.env").exists()
    assert "Presets: Night Farm" in rs.apply_preset("day", cfg)


def test_settings_text_hides_denied_values(tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text("account.username: SecretPlayer\ngather.convert_at: 90\n")
    found = rs.find("username", cfg)
    assert "SecretPlayer" not in found and "account.username = (not from Telegram)" in found
    assert "gather.convert_at = 90" in rs.find("convert", cfg)
    text = rs.overview(cfg)
    assert "convert at 90%" in text and "Gathering:" in text and "/set" in text
    assert len(text) < 4000


@pytest.fixture
def phone(tmp_path, monkeypatch):
    env = tmp_path / "telegram.env"
    env.write_text(f"TELEGRAM_TOKEN=1:fake\nTELEGRAM_CHAT={OWNER}\n")
    for name, path in (("ENV", env), ("HANDLED", tmp_path / "telegram.handled"),
                       ("SETTINGS", tmp_path / "settings.yaml"), ("NIGHT", tmp_path / "night")):
        monkeypatch.setattr(tg, name, path)
    tg.SETTINGS.write_text("telegram.commands: true\naccount.username: SecretPlayer\n")
    seen = {"sent": [], "socket": []}

    def api(method, token=None, wait=70, **params):
        seen["sent"].append(params.get("text"))
        return {"ok": True}

    def bot_socket(command=None, read_s=0.0, **fields):
        seen["socket"].append((command, fields))
        return [{"kind": "log", "source": "remote", "at": time.time(), "message": "Set: done."}]
    monkeypatch.setattr(tg, "api", api)
    monkeypatch.setattr(tg, "bot_socket", bot_socket)
    return seen


def test_set_and_preset_go_to_the_bot_only(phone, monkeypatch):
    before = tg.SETTINGS.read_bytes()
    assert tg.command_in(msg("/set gather.convert_at 90")) == "set"
    assert tg.command_in(msg("/logs please")) is None           # /logs takes no words
    assert tg.run_command("set", msg("/set gather.convert_at  90")) == "Set: done."
    assert tg.run_command("preset", msg("/preset Night Farm")) == "Set: done."
    assert phone["socket"] == [("set_setting", {"key": "gather.convert_at", "value": "90"}),
                               ("set_preset", {"value": "Night Farm"})]
    assert tg.run_command("set", msg("/set gather.convert_at")).startswith("Use: /set")
    assert tg.change_setting("set", "economy.buy on", msg("/set", chat=STRANGER)) \
        .startswith("Only the owner")
    assert len(phone["socket"]) == 2
    monkeypatch.setattr(tg, "bot_socket", lambda command=None, read_s=0.0, **f: None)
    assert "not running" in tg.run_command("set", msg("/set economy.buy on"))
    assert tg.SETTINGS.read_bytes() == before                   # this script wrote nothing
    src = (ROOT / "scripts" / "telegram_alerts.py").read_text(encoding="utf-8")
    assert "take_values" not in src and "set_one(" not in src


def test_settings_command_reads_through_the_schema(phone):
    reply = tg.run_command("settings", msg("/settings username"))
    assert "account.username = (not from Telegram)" in reply and "SecretPlayer" not in reply
    assert "Gathering:" in tg.settings_text("")


def test_logs_are_scrubbed(phone):
    night = tg.NIGHT
    night.mkdir()
    home = Path.home()
    lines = [f"    12:00:0{i}  gathering Pine Tree, honey 104,608,004" for i in range(40)]
    lines += [f"    12:01:00  frames in {home}/Hivemind/var/incidents/x",
              "    12:01:01  joining https://www.roblox.com/share?code=0123456789abcdef0123456789abcdef&type=Server",
              "    12:01:02  SecretPlayer is at the hive",
              f"    12:01:03  hello from {getpass.getuser()}",
              "    12:01:04  only 8.9 GB free, unloaded the vision model"]
    (night / "run-0007.log").write_text("\n".join(lines) + "\n")
    out = tg.run_command("logs", msg("/logs"))
    assert out.startswith("run-0007, last 30 lines (1 system-detail lines left out):")
    assert len(out.splitlines()) == 30                       # the header + 29 kept
    for private in (str(home), "roblox.com", "0123456789abcdef", "SecretPlayer",
                    getpass.getuser(), "8.9 GB"):
        assert private not in out, private
    assert "honey 104,608,004" in out
    assert phone["sent"][-1] == "🐝 " + out


def test_logs_with_no_run_log(phone):
    assert tg.logs_text() == "No run log yet."


def test_the_commands_carry_key_and_value_over_json():
    for event in (Command(action=Action.SET_SETTING, key="gather.convert_at", value="90"),
                  Command(action=Action.SET_PRESET, value="Night Farm")):
        back = from_json(event.to_json())
        assert (back.action, back.key, back.value) == (event.action, event.key, event.value)


def test_the_bot_writes_them_behind_the_telegram_switch():
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    at = src.index("event.action in (Action.SET_SETTING")
    body = src[at:at + 1500]
    assert body.index('settings.get("telegram.commands")') < body.index("remote_settings.set_one(")
    assert 'source="remote"' in body and "settings.reload()" in body
