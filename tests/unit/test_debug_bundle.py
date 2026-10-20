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


def test_the_server_name_the_friend_and_a_short_chat_id_are_blanked(tmp_path):
    """FOUND 2026-10-26 (the tester guide's review): server.name and
    account.follow_user stayed in the bundle's settings, and a Telegram chat
    id (under 12 characters) stayed in the logs. A 2-digit id still does not
    count: it would blank every '42' in every log."""
    chat, server, friend = "5551234567", "Fake_Player42's server", "987654321"
    config, var = tmp_path / "cfg", tmp_path / "var"
    config.mkdir()
    (config / "telegram.env").write_text(f"TELEGRAM_TOKEN={TOKEN}\nTELEGRAM_CHAT={chat}\n")
    (config / "settings.yaml").write_text(
        f"server.name: \"{server}\"\naccount.follow_user: '{friend}'\n", encoding="utf-8")
    (var / "night").mkdir(parents=True)
    (var / "night" / "run-001.log").write_text(
        f"telegram: sent to {chat}\njoining {server}\nfollowing {friend}\n42 trips\n",
        encoding="utf-8")
    out, _ = db.build(tmp_path / "b.zip", var, config, runs=1, about_text="")
    with zipfile.ZipFile(out) as z:
        blob = b"\n".join(z.read(n) for n in z.namelist())
        settings = z.read("settings.yaml").decode()
    for secret in (chat, server, friend):
        assert secret.encode() not in blob, secret
    assert "server.name: '[blanked]'" in settings
    assert "account.follow_user: '[blanked]'" in settings
    assert b"42 trips" in blob


def test_a_two_digit_chat_id_is_not_a_secret(tmp_path):
    config, _ = machine(tmp_path)                 # TELEGRAM_CHAT=42
    assert "42" not in db.secret_values(config)


def test_no_login_name_or_timezone_gets_in(tmp_path, monkeypatch):
    """FOUND 2026-10-26 (the usability review): about.txt held the python path
    (/home/<login>/...) and the UTC offset, and logs hold home paths."""
    import sys
    import time
    home = tmp_path / "emma.johnson"
    home.mkdir()
    config, var = machine(home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("TZ", "America/Chicago")
    # time.tzset is POSIX only; on Windows the PC's own offset is checked
    tzset = getattr(time, "tzset", lambda: None)
    tzset()
    try:
        offset = time.strftime("%z")
        monkeypatch.setattr(sys, "executable", str(home / ".venv/bin/python"))
        monkeypatch.setattr(db.selftest, "run",
                            lambda checks, say: say(f"data files: ok ({home}/Hivemind/data)"))
        (var / "night" / "run-005.log").write_text(f"saved {home}/Hivemind/var/x.jpg\n")
        out, _ = db.build(tmp_path / "b.zip", var, config, runs=1)
    finally:
        monkeypatch.undo()
        tzset()
    with zipfile.ZipFile(out) as z:
        blob = b"\n".join(z.read(n) for n in z.namelist())
        about = z.read("about.txt").decode()
    assert b"emma" not in blob.lower()
    # either separator: Windows writes the path with backslashes
    assert offset not in about and "~/.venv/bin/python" in about.replace("\\", "/")
    assert b"saved ~/Hivemind/var/x.jpg" in blob


def test_links_cookies_and_machine_names_not_in_the_config_are_hidden(tmp_path, monkeypatch):
    """FOUND 2026-10-27 (the usability review): only the values set up right
    now were hidden, so an old or friend's link, a cookie, and the login or
    host name in a path outside HOME went into the bundle."""
    code = "11122233344455566677788899900011"
    friend = f"https://www.roblox.com/games/1537690962?privateServerLinkCode={code}"
    share = "https://www.roblox.com/share?code=0123456789abcdef0123456789abcdef&type=Server"
    cookie = ".ROBLOSECURITY=_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow|_FAKECOOKIE99"
    login, host = "zoefakelogin", "zoes-fake-pc"
    monkeypatch.setenv("LOGNAME", login)
    monkeypatch.setattr(db.privacy.socket, "gethostname", lambda: host)
    config, var = tmp_path / "cfg", tmp_path / "var"
    config.mkdir()
    (var / "night").mkdir(parents=True)
    (var / "night" / "run-001.log").write_text(
        f"old link {friend}\nfriend sent {share}\ncookie {cookie}\n"
        f"frames in /mnt/data/{login}/frames on {host}\nmade 300 trips\n", encoding="utf-8")
    out, _ = db.build(tmp_path / "b.zip", var, config, runs=1, about_text="")
    with zipfile.ZipFile(out) as z:
        log = z.read("var/night/run-001.log").decode()
    for secret in (code, "roblox.com", "0123456789abcdef", "ROBLOSECURITY", "FAKECOOKIE99",
                   login, host):
        assert secret.lower() not in log.lower(), secret
    assert "made 300 trips" in log


def test_the_newest_runs_are_picked_by_number(tmp_path):
    """MEASURED 2026-10-27: a name sort put run-999 after run-1256, so the
    bundle sent runs 997-999 of 14 Oct, not the one running."""
    night = tmp_path / "night"
    night.mkdir()
    for n in (998, 999, 1000, 1256):
        (night / f"run-{n:03d}.log").write_text("x")
    assert [p.name for p in db.pick(tmp_path, 2)] == ["run-1000.log", "run-1256.log"]


def test_a_saved_moment_goes_in_beside_the_newest_incident(tmp_path):
    """58 incidents were saved on 26 Oct: a moment saved by hand is rarely
    still the newest when the report is made."""
    import os
    inc = tmp_path / "incidents"
    for name, when in (("20261027-090000-manual", 10), ("20261027-090100-mob-sighting", 20),
                       ("20261027-080000-manual-2", 5), ("20261027-090200-stall", 30)):
        (inc / name).mkdir(parents=True)
        (inc / name / "000.jpg").write_bytes(b"\xff\xd8")
        os.utime(inc / name, (when, when))
    folders = {p.parent.name for p in db.pick(tmp_path, 0)}
    assert folders == {"20261027-090000-manual", "20261027-090200-stall"}


def test_frames_are_thinned_evenly_to_fit_a_dm_keeping_each_moment():
    members = [("about.txt", b"t" * 5000)]
    for folder in ("a-manual", "b-stall"):
        members += [(f"var/incidents/{folder}/{i:03d}.jpg", b"\xff" * 1000) for i in range(10)]
    kept, gone = db.thin(members, 7000)                       # 20 kB of frames, 7 kB allowed
    names = [n for n, _ in kept]
    assert "about.txt" in names                               # text is never thinned
    assert gone == 12 and len(names) == 1 + 8
    for folder in ("a-manual", "b-stall"):                    # the moment itself stays,
        assert f"var/incidents/{folder}/009.jpg" in names     # then every 3rd back
        assert f"var/incidents/{folder}/006.jpg" in names
        assert f"var/incidents/{folder}/008.jpg" not in names
    assert db.thin(members, 0) == (members, 0)                # 0: keep them all


def test_a_thinned_bundle_says_so(tmp_path):
    config, var = machine(tmp_path)
    (var / "incidents" / "1000-new" / "002.jpg").write_bytes(b"\xff\xd8" + b"x" * 3000)
    out, _ = db.build(tmp_path / "b.zip", var, config, runs=1, about_text="",
                      frames_mb=0.001)
    with zipfile.ZipFile(out) as z:
        assert "frames left out to keep the zip small" in z.read("left-out.txt").decode()
