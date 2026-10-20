"""platform/gameguard (A14) against fake /proc trees, and the start refusal."""
import os
import sys
from pathlib import Path

from hivemind.platform import gameguard

UID = os.getuid()
NESTED = "/home/x/.config/hivemind/nested.lua"


def proc(tmp_path, *procs):
    """procs: (pid, argv list, comm, env dict[, uid[, ppid]])."""
    for pid, argv, comm, env, *rest in procs:
        uid = rest[0] if rest else UID
        ppid = rest[1] if len(rest) > 1 else 1
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (d / "comm").write_text(comm + "\n")
        (d / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in env.items()))
        (d / "status").write_text(f"Name:\t{comm}\nUid:\t{uid}\t0\t0\t0\nPPid:\t{ppid}\n")
    (tmp_path / "self").mkdir()
    return tmp_path


OBS = (10, ["obs"], "obs", {"FLATPAK_ID": "com.obsproject.Studio"})
STEAM = (11, ["/home/user/.local/share/Steam/ubuntu12_32/steam", "-no-cef-sandbox"], "steam", {})
WEBHELPER = (12, ["./steamwebhelper", "-steampid=96"], "steamwebhelper", {})


def look(tmp_path, *procs, games=()):
    return gameguard.playing(games, proc=proc(tmp_path, *procs), nested_config=NESTED, uid=UID)


def test_steam_game_detected_by_reaper(tmp_path):
    reaper = (20, ["/s/ubuntu12_32/reaper", "SteamLaunch", "AppId=1145360", "--",
                   "/s/steamapps/common/Hades/Hades.x86_64"], "reaper", {})
    assert look(tmp_path, OBS, STEAM, WEBHELPER, reaper) == "Hades"


def test_steam_game_detected_by_env(tmp_path):
    game = (21, ["/games/thing.exe"], "thing.exe", {"SteamAppId": "620"})
    assert look(tmp_path, STEAM, game) == "a Steam game (app 620)"


def test_minecraft_detected(tmp_path):
    java = (30, ["/usr/lib/jvm/java-21/bin/java", "-Dminecraft.launcher.brand=PrismLauncher",
                 "org.prismlauncher.EntryPoint"], "java", {})
    assert look(tmp_path, OBS, java) == "Minecraft"


def test_obs_and_steam_client_alone_are_not_a_game(tmp_path):
    assert look(tmp_path, OBS, STEAM, WEBHELPER) is None


def test_the_bots_own_sober_is_not_detected(tmp_path):
    hypr = (40, ["Hyprland", "-c", NESTED], "Hyprland", {})
    launcher = (39, ["sh", "-c", '"$@"; exit $?', "hivemind-game", "flatpak", "run"], "sh", {})
    outer = (41, ["bwrap", "--args", "40", "--", "sober", "roblox://x"], "bwrap", {}, UID, 39)
    inner = (42, ["sober", "roblox://x"], "sober", {}, UID, 41)
    assert look(tmp_path, OBS, hypr, launcher, outer, inner) is None


def test_his_sober_beside_the_bots_kept_game_is_detected(tmp_path):
    """MEASURED 2026-10-20 18:18:50: he opened Roblox (parent systemd --user)
    while the bot's game was up; the bot then launched its own Sober over it."""
    hypr = (40, ["Hyprland", "-c", NESTED], "Hyprland", {})
    launcher = (39, ["sh", "-c", '"$@"; exit $?', "hivemind-game", "flatpak", "run"], "sh", {})
    ours = (41, ["bwrap", "--args", "40", "--", "sober"], "bwrap", {}, UID, 39)
    systemd = (30, ["/usr/lib/systemd/systemd", "--user"], "systemd", {})
    his = (45, ["bwrap", "--args", "78", "--", "sober", "--"], "bwrap", {}, UID, 30)
    assert look(tmp_path, OBS, hypr, launcher, ours, systemd, his) == "Roblox (your own Sober)"


def test_the_owners_sober_is_detected(tmp_path):
    outer = (41, ["bwrap", "--args", "40", "--", "sober"], "bwrap", {})
    assert look(tmp_path, OBS, outer) == "Roblox (your own Sober)"
    other = tmp_path / "b"
    other.mkdir()
    grep = (43, ["pgrep", "sober"], "pgrep", {})
    assert look(other, grep) is None                 # a command that names it is not it


def test_the_alts_sober_is_not_his(tmp_path):
    alt = (50, ["sober"], "sober", {}, UID + 4242)
    assert look(tmp_path, alt) is None


def test_configured_games(tmp_path):
    mc = (60, ["/opt/mcpelauncher/bin/mcpelauncher-client", "-dg", "x"], "mcpelauncher-cl", {})
    assert look(tmp_path, OBS, mc, games=gameguard.games_of("mcpelauncher-client, foo")) \
        == "mcpelauncher-client"


def test_pause_called_once_and_never_resumed():
    seen = iter(["Minecraft", "Minecraft", "Minecraft", "Minecraft", None, "Hades", "Hades"])
    paused = []
    watch = gameguard.Watch(lambda: next(seen), paused.append)
    for _ in range(7):
        watch.tick()
    assert paused == ["Minecraft", "Hades"]          # once per game, after two looks


def test_off_switch():
    class S(dict):
        def bool(self, k):
            return bool(self[k])
    assert gameguard.check(S({"guard.enabled": False, "guard.games": "obs"})) is None


def test_start_refused(monkeypatch, capsys):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import run_farm
    monkeypatch.setattr(run_farm, "migrate_secrets", lambda: [])
    monkeypatch.setattr(run_farm.gameguard, "check", lambda settings: "Minecraft")
    monkeypatch.setattr(sys, "argv", ["run_farm"])
    lock = Path(run_farm.SHELL_FARM_LOCK)
    held = lock.exists()
    monkeypatch.setattr("hivemind.files.take_lock", lambda path: object())
    monkeypatch.setattr(run_farm.SessionCap, "from_env",
                        classmethod(lambda cls, s: type("C", (), {"expired": lambda self: False})()))
    assert run_farm.main() == run_farm.GAME_GUARD_EXIT
    assert "you're playing Minecraft — not starting" in capsys.readouterr().out
    assert lock.exists() == held                     # the real lock was never taken
