"""Identical failed starts (audit 2026-10-13 #7, platform/startfails): the
2nd in a row is said and spaced out, the broken document portal of 10-12
22:37-23:17 (14 x "Sober never opened a window") is recognised in sober.log."""
import subprocess

from hivemind.platform import startfails as sf

NO_WINDOW = "Sober never opened a window"


def test_the_streak_counts_identical_failures_only():
    s = sf.note({}, NO_WINDOW, 1000.0)
    assert s["count"] == 1 and sf.backoff_s(s["count"]) == 0
    s = sf.note(s, NO_WINDOW, 1180.0)
    assert s["count"] == sf.ALERT_AT == 2 and s["since"] == 1000.0
    assert sf.note(s, "another reason", 1200.0)["count"] == 1
    assert sf.note(s, NO_WINDOW, 1180.0 + sf.STALE_S + 1)["count"] == 1   # stopped in between


def test_the_back_off_doubles_to_its_cap():
    waits = [sf.backoff_s(n) for n in range(1, 9)]
    assert waits[:3] == [0, sf.BACKOFF_FIRST_S, 2 * sf.BACKOFF_FIRST_S]
    assert max(waits) == sf.BACKOFF_MAX_S and waits == sorted(waits)


def test_the_broken_portal_is_seen_in_sobers_log():
    assert sf.portal_broken("info: x\nbwrap: Can't find source path /run/user/1000/doc: "
                            "No such file or directory\n")
    assert not sf.portal_broken("info: app: lifecycle: app_start\n")


def test_its_commands_and_a_failed_send_never_raise(tmp_path):
    seen = []

    def run(argv, **_):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def broken(argv, **_):
        raise OSError("no such program")

    assert sf.restart_portal(run) == "(nothing, exit 0)"
    assert seen[-1] == ["systemctl", "--user", "restart", "xdg-document-portal.service"]
    assert sf.tell("hi", run) and seen[-1][-2:] == ["--send", "hi"]
    assert seen[-1][1].replace("\\", "/").endswith("scripts/telegram_alerts.py")
    assert not sf.tell("hi", broken) and "could not run" in sf.flatpak_instances(broken)
    path = tmp_path / "start_failures.json"
    sf.save(path, {"count": 2})
    assert sf.load(path) == {"count": 2}
    sf.clear(path)
    assert sf.load(path) == {}


def test_run_farm_keeps_the_failed_launchs_client_log():
    """var/sober.log is truncated per launch; the streak's alert keeps a copy
    (26 Oct: 33 'Crash' starts in a row, no log of one left)."""
    from pathlib import Path

    import hivemind
    src = (Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py").read_text(
        encoding="utf-8")
    assert 'f"sober-startfail-' in src
    assert 'streak["count"] == startfails.ALERT_AT and sober_log' in src


def test_no_internet_is_seen_in_sobers_log_and_waited_out():
    # MEASURED 2026-10-26 (Sober's sober_logs, runs 1211-1243): "stuck on loading"
    log = ("ERROR: download: couldn't download resource from: https://sober.vinegarhq.org/app "
           "(error=Could not resolve hostname)\nFATAL: Crash: Failed to fetch remote "
           "manifest required for operation. Check your internet connection.\n")
    assert sf.offline(log) and not sf.offline("info: app: lifecycle: app_start\n")
    answers = iter([True, True, False])

    def resolve(host, port):
        if next(answers):
            raise OSError("Could not resolve hostname")

    def down(host, port):
        raise OSError("Could not resolve hostname")

    waits = []
    assert sf.wait_online(lambda s: waits.append(s) or False, 600.0, resolve)
    assert waits == [sf.ONLINE_POLL_S] * 2
    waits.clear()
    assert not sf.wait_online(lambda s: waits.append(s) or False, 45.0, down)
    assert sum(waits) == 45.0
    assert not sf.wait_online(lambda s: True, 600.0, down)          # a stop ends it


def test_a_disconnect_sets_the_next_starts_wait():
    """ROADMAP A10: 2 of 2 joins launched ~26 s after a reason-275 shutdown hit
    'Connection Failed (279)', 2 of 2 launched ~103 s after got in; a lost
    connection (277) is 'network' from the first moment."""
    from hivemind.platform.clientlog import ClientLog, parse

    def ended(*lines):
        log = ClientLog("/nonexistent")
        for i, text in enumerate(("[FLog::Network] Replicator created: 0x1",) + lines):
            log._apply(parse(f"2026-10-26T01:04:0{i}.000Z,1,f,6 {text}", 0.0))
        return log

    assert ended("[FLog::Network] Connection lost",
                 "[FLog::Network] Sending disconnect with reason: 277").end_kind() == "network"
    assert ended("[FLog::Network] Connection lost: AckTimeout").end_kind() == "network"
    assert ended("[FLog::Network] Connection lost",
                 "[FLog::Network] Sending disconnect with reason: 275").end_kind() == "shutdown"
    assert ended("[FLog::Network] Time to disconnect replication data: 1",
                 "[FLog::Network] Sending disconnect with reason: 278").end_kind() == "idle"
    assert ClientLog("/nonexistent").end_kind() == ""
    at = 1000.0
    assert sf.loss_wait_s({"kind": "shutdown", "at": at}, at + 28) == sf.SHUTDOWN_REJOIN_S - 28
    assert sf.loss_wait_s({"kind": "shutdown", "at": at}, at + 3600) == 0.0
    assert sf.loss_wait_s({"kind": "network", "at": at}, at) == 0.0
    assert sf.loss_wait_s({}, at) == 0.0

    def down(host, port):
        raise OSError("Could not resolve hostname")
    assert sf.online(lambda host, port: None) and not sf.online(down)


def test_run_farm_answers_a_disconnect_before_the_rejoin():
    from pathlib import Path

    import hivemind
    src = (Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py").read_text(
        encoding="utf-8")
    start = src[src.index("startfails.loss_wait_s(loss"):src.index("ready = bootstrap.start(")]
    assert "startfails.online()" in start and "return 0" in start
    lost = src[src.index("def stop_for_loss"):src.index("WINDOWS (RL6): the client writes")]
    assert "startfails.save(LOSS_FILE" in lost and "client.end_kind()" in lost
    assert "LOSS_EXIT_LIVE = False" in src
