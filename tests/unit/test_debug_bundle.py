"""scripts/debug_bundle.py: the zip a tester sends. NO SECRET MAY GET IN."""
from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import hivemind

ROOT = Path(hivemind.__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("debug_bundle", ROOT / "scripts" / "debug_bundle.py")
db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db)

TOKEN = "123456789:AAFakeTelegramTokenForTheTest_xyz"
HOOK = "https://discord.com/api/webhooks/1/FakeHookForTheTest"
CODE = "73612345678901234567890123456789"
LINK = f"https://www.roblox.com/games/1537690962?privateServerLinkCode={CODE}"
YT = "AIzaFakeYoutubeKeyForTheTest"
USER = "Fake_Player42"


def machine(tmp_path):
    config, var = tmp_path / "config", tmp_path / "var"
    config.mkdir()
    (config / "telegram.env").write_text(f"TELEGRAM_TOKEN={TOKEN}\nTELEGRAM_CHAT=42\n")
    (config / "discord.env").write_text(f'DISCORD_WEBHOOK="{HOOK}"\n')
    (config / "secrets.env").write_text(f"YOUTUBE_API_KEY={YT}\n")
    (config / "server.yaml").write_text(f"private_link: {LINK}\n")
    (config / "settings.yaml").write_text(
        f"account.username: {USER}\nserver.link: {LINK}\ngather.chase_tokens: true\n")
    night = var / "night"
    night.mkdir(parents=True)
    for n in range(1, 6):
        (night / f"run-{n:03d}.log").write_text(f"attempt {n}\n")
    (night / "run-005.log").write_text(
        f"joined as {USER.lower()} with token {TOKEN}\nlink {LINK}\nhook {HOOK}\nkey {YT}\n")
    (night / "attempts.log").write_text("[watchdog] attempt 5 starting\n")
    old, new = var / "incidents" / "0900-old", var / "incidents" / "1000-new"
    old.mkdir(parents=True)
    (old / "a.jpg").write_bytes(b"\xff\xd8old")
    new.mkdir()
    (new / "000.jpg").write_bytes(b"\xff\xd8clean frame")
    (new / "001.jpg").write_bytes(b"\xff\xd8" + CODE.encode())   # a secret inside a frame
    (new / "note.json").write_text('{"why": "mob sighting"}')
    import os
    os.utime(old, (1, 1))
    return config, var


def test_no_secret_gets_into_the_bundle(tmp_path):
    config, var = machine(tmp_path)
    out, left_out = db.build(tmp_path / "b.zip", var, config, runs=2, about_text="about\n")
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        blob = b"\n".join(z.read(n) for n in names).lower()
    for secret in (TOKEN, HOOK, CODE, LINK, YT, USER):
        assert secret.lower().encode() not in blob, secret
    assert left_out == ["var/incidents/1000-new/001.jpg"]   # a frame can't be scrubbed: left out
    assert names == {"about.txt", "settings.yaml", "left-out.txt", "var/night/attempts.log",
                     "var/night/run-004.log", "var/night/run-005.log",
                     "var/incidents/1000-new/000.jpg", "var/incidents/1000-new/note.json"}


def test_the_logs_keep_their_words_with_the_secret_hidden(tmp_path):
    config, var = machine(tmp_path)
    out, _ = db.build(tmp_path / "b.zip", var, config, runs=1, about_text="")
    with zipfile.ZipFile(out) as z:
        log = z.read("var/night/run-005.log").decode()
        settings = z.read("settings.yaml").decode()
    assert "joined as [secret] with token [secret]" in log
    assert "account.username: '[blanked]'" in settings and "gather.chase_tokens: true" in settings


def test_every_settings_secret_is_blanked():
    from hivemind.world import settings
    assert set(settings.SECRET) <= set(db.PRIVATE_KEYS)


def test_a_machine_with_nothing_still_bundles(tmp_path):
    out, left_out = db.build(tmp_path / "b.zip", tmp_path / "var", tmp_path / "cfg",
                             about_text="x")
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == {"about.txt", "settings.yaml"} and left_out == []


def test_the_share_link_and_its_code_are_blanked(tmp_path):
    """account.share_link is a private server's way in (AGENTS.md rule 6) and
    a plain settings.yaml value; the bot logs its code inside a roblox:// URI."""
    code = "Zx9Kq2Lm7Rt4Vw8Bn3Cd"
    link = f"https://www.roblox.com/share?code={code}&type=Server"
    config, var = tmp_path / "cfg", tmp_path / "var"
    config.mkdir()
    (config / "settings.yaml").write_text(f"account.share_link: {link}\n", encoding="utf-8")
    (var / "night").mkdir(parents=True)
    (var / "night" / "run-001.log").write_text(
        f"opening roblox://navigation/share_links?code={code}&type=Server\n", encoding="utf-8")
    out, _ = db.build(tmp_path / "b.zip", var, config, runs=1, about_text="")
    with zipfile.ZipFile(out) as z:
        blob = b"\n".join(z.read(n) for n in z.namelist())
        settings = z.read("settings.yaml").decode()
    assert code.encode() not in blob
    assert "account.share_link: '[blanked]'" in settings
