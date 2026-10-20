"""The server the account was last in (platform/lastserver), from Sober's log.

The lines are the shapes MEASURED in the owner's session log of 2026-09-29
20:37, with made-up JobIds: a friend's server joined through the friends'
server list, their private server through its own list.
"""
from __future__ import annotations

import os
import time

from hivemind.platform import lastserver as ls

FRIEND = "0f3c2a1e-9b8d-4c7e-a6f5-1234567890ab"
PRIVATE = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OTHER_GAME = "11111111-2222-4333-8444-555555555555"


def _launch(kind):
    return ('info: Roblox: 2026-09-29T13:20:59.593Z,2606.59,f6e6f4c0,6,Error [FLog::WebView] '
            'Sending command: {"callbackID":"x","functionName":"launchGame","moduleID":"Game",'
            '"params":{"request":{"browserTrackerId":"1","joinAttemptOrigin":"o",'
            f'"requestType":"{kind}"}}}},"webViewId":null}} to WebViewService')


def _join(job, place=ls.BSS_PLACE_ID):
    return (f"info: Roblox: 2026-09-29T13:21:01.205Z,2608.20,fb19a6c0,6 [FLog::Output] "
            f"! Joining game '{job}' place {place} at 10.0.0.1|53640")


def _log(tmp_path, lines, name="2026-09-29_20-37-31.log", age=0.0):
    folder = tmp_path / "sober_logs"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text("\n".join(lines) + "\n")
    when = time.time() - age
    os.utime(path, (when, when))
    return folder


def test_a_friends_server_is_joined_again_by_its_link(tmp_path):
    folder = _log(tmp_path, [_launch("RequestPrivateGame"), _join(PRIVATE),
                             _launch("RequestFollowUser"), _join(FRIEND)])
    found = ls.last_server(folder)
    assert found is not None and not found.private
    assert found.request == "RequestFollowUser"
    assert found.uri() == f"roblox://placeId=1537690962&gameInstanceId={FRIEND}"


def test_his_private_server_is_left_to_the_usual_join(tmp_path):
    folder = _log(tmp_path, [_launch("RequestFollowUser"), _join(FRIEND),
                             _launch("RequestPrivateGame"), _join(PRIVATE)])
    found = ls.last_server(folder)
    assert found.private and found.job == PRIVATE


def test_another_game_is_not_bee_swarm(tmp_path):
    folder = _log(tmp_path, [_launch("RequestFollowUser"), _join(FRIEND),
                             _launch("RequestGame"), _join(OTHER_GAME, place="142823291")])
    found = ls.last_server(folder)
    assert found.job == FRIEND and found.request == "RequestFollowUser"


def test_a_request_belongs_only_to_the_join_after_it(tmp_path):
    # a join with no launch line of its own (a deep link, a teleport)
    folder = _log(tmp_path, [_launch("RequestPrivateGame"), _join(PRIVATE), _join(FRIEND)])
    found = ls.last_server(folder)
    assert found.job == FRIEND and found.request == "" and not found.private


def test_the_newest_log_is_read_and_an_old_one_is_not_believed(tmp_path):
    _log(tmp_path, [_join(PRIVATE)], name="2026-09-29_08-02-41.log", age=7200)
    folder = _log(tmp_path, [_join(FRIEND)], name="2026-09-29_20-37-31.log", age=10)
    assert ls.last_server(folder).job == FRIEND
    stale = _log(tmp_path / "b", [_join(FRIEND)], age=ls.FRESH_S + 60) if (tmp_path / "b").mkdir() is None else None
    assert ls.last_server(stale) is None


def test_no_join_no_server(tmp_path):
    assert ls.last_server(_log(tmp_path, ["nothing"])) is None
    assert ls.last_server(tmp_path / "missing") is None


def test_a_server_that_failed_is_not_tried_again(tmp_path):
    folder = _log(tmp_path, [_join(FRIEND)])
    found = ls.last_server(folder)
    assert not ls.tried_and_failed(found)
    ls.note_result(found, False)
    assert ls.tried_and_failed(found)
    ls.note_result(found, True)
    assert not ls.tried_and_failed(found)


def test_only_the_digest_is_kept(tmp_path):
    found = ls.last_server(_log(tmp_path, [_join(FRIEND)]))
    ls.note_result(found, True)
    kept = ls.RECORD.read_text()
    assert FRIEND not in kept and found.digest in kept and len(found.digest) == 6


def test_a_crash_handler_or_installer_log_is_never_the_newest(tmp_path):
    # MEASURED 2026-10-26 on Windows 11: the client writes a
    # "..._Player_<hex>_CrashHandler_last.log" 2-3 s after its Player log
    # when a session ends, and an update writes a RobloxPlayerInstaller log.
    folder = _log(tmp_path, [_join(FRIEND)], name="0.744.0.1_20261026T0100Z_Player_9A391_last.log", age=30)
    _log(tmp_path, ["[FLog::CrashHandler] started"],
         name="0.744.0.1_20261026T0100Z_Player_274AC_CrashHandler_last.log", age=20)
    _log(tmp_path, ["installer"], name="0.744.0.1_20261026T0100Z_RobloxPlayerInstaller_CAB13.log", age=10)
    assert ls.newest_log(folder).name.endswith("Player_9A391_last.log")
    assert ls.last_server(folder).job == FRIEND
