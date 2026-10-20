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
