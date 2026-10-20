"""The client log re-picked while a run goes on (Windows, RL6 follow-up of
docs/pending/windows-platform-check.md, Fixes 2 "still open"): Roblox's tray
process writes Player logs too, so the newest log at the start of a run can
be the tray's, and a relaunch inside one run starts a new log. Temp files and
a fake clock only; nothing is launched."""
from __future__ import annotations

import os

from hivemind import datapaths as dp
from hivemind.platform.clientlog import ClientLog, REPICK_SECONDS

NOW = 1_800_000_000.0
JOIN = ("2026-10-26T01:00:00.000Z,0.1,1,6 [FLog::Output] ! Joining game "
        "'0f0e0d0c-0000-0000-0000-000000000001' place 1537690962 at 10.0.0.1|1\n")
BEAT = "2026-10-26T01:00:20.000Z,0.1,1,6 [FLog::Network] onSessionHeartbeat\n"
TRAY = ("2026-10-26T01:00:00.000Z,0.1,1,6 [FLog::Output] AppState/TrayMode\n"
        "2026-10-26T01:00:00.100Z,0.1,1,6 [FLog::Output] Systray initialized\n")


def _log(path, text, age):
    path.write_text(text, encoding="utf-8")
    os.utime(path, (NOW - age, NOW - age))
    return path


def _reader(path, logs, clock):
    said = []
    return ClientLog(path, candidates=lambda: list(logs), clock=lambda: clock[0],
                     emit=said.append), said


def test_the_tray_log_picked_first_gives_way_to_the_game_log(tmp_path):
    tray = _log(tmp_path / "a_Player_T_last.log", TRAY, age=1)        # written at that moment
    game = _log(tmp_path / "b_Player_G_last.log", JOIN + BEAT, age=3)
    clock = [NOW]
    reader, said = _reader(tray, [tray, game], clock)
    reader.poll()
    assert reader.path == tray and reader.joined is None            # the game's log is older
    with game.open("a", encoding="utf-8") as fh:                     # its next heartbeat
        fh.write(BEAT)
    os.utime(game, (NOW + 2, NOW + 2))
    clock[0] = NOW + 2                                               # not time to look yet
    reader.poll()
    assert reader.path == tray
    clock[0] = NOW + REPICK_SECONDS
    reader.poll()
    assert reader.path == game and reader.joined is not None and reader.heartbeats == 2
    assert reader.repicks == 1 and any("newer game session" in s for s in said)


def test_a_newer_tray_log_never_takes_the_place_of_a_game_that_went_quiet(tmp_path):
    game = _log(tmp_path / "a_Player_G_last.log", JOIN + BEAT, age=120)
    tray = _log(tmp_path / "b_Player_T_last.log", TRAY, age=1)
    reader, _ = _reader(game, [game, tray], [NOW])
    reader.poll()
    assert reader.path == game and reader.joined is not None and reader.repicks == 0


def test_a_relaunch_is_followed_at_once_and_never_flapped_back(tmp_path):
    first = _log(tmp_path / "a_Player_A_last.log", JOIN + BEAT, age=2)
    clock = [NOW]
    logs = [first]
    reader, _ = _reader(first, logs, clock)
    reader.poll()
    second = _log(tmp_path / "b_Player_B_last.log", JOIN, age=0)      # a relaunch's log
    logs.append(second)
    clock[0] += REPICK_SECONDS
    reader.poll()
    assert reader.path == second                                     # new, so at once
    os.utime(first, (NOW + 1, NOW + 1))                              # the old one written again
    clock[0] += REPICK_SECONDS
    reader.poll()
    assert reader.path == second                                     # known and ours is not quiet
    clock[0] += 60                                                    # ours went quiet
    reader.poll()
    assert reader.path == first and reader.repicks == 2


def test_a_log_that_holds_no_session_yet_is_judged_again_as_it_grows(tmp_path):
    first = _log(tmp_path / "a_Player_A_last.log", JOIN + BEAT, age=5)
    opening = _log(tmp_path / "b_Player_B_last.log", "starting\n", age=0)
    clock = [NOW]
    reader, _ = _reader(first, [first, opening], clock)
    reader.poll()
    assert reader.path == first
    with opening.open("a", encoding="utf-8") as fh:
        fh.write(JOIN)
    os.utime(opening, (NOW + 1, NOW + 1))
    clock[0] += REPICK_SECONDS
    reader.poll()
    assert reader.path == opening and reader.joined is not None


def test_no_candidates_keeps_the_one_log_and_linux_lists_none(tmp_path, monkeypatch):
    log = _log(tmp_path / "sober.log", JOIN, age=0)
    reader = ClientLog(log)
    reader.poll()
    assert reader.path == log and reader.repicks == 0
    monkeypatch.setattr(dp, "WINDOWS", False)
    assert dp.client_logs() == []


def test_windows_candidates_are_the_player_logs_only(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "WINDOWS", True)
    monkeypatch.setattr(dp, "session_logs_dir", lambda: tmp_path)
    for name in ("0.744_Player_9A391_last.log", "0.744_Player_274AC_CrashHandler_last.log",
                 "0.744_RobloxPlayerInstaller_CAB13.log"):
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    assert [p.name for p in dp.client_logs()] == ["0.744_Player_9A391_last.log"]
    monkeypatch.setattr(dp, "session_logs_dir", lambda: tmp_path / "missing")
    assert dp.client_logs() == []
