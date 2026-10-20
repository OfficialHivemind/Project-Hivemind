"""Play starts the watchdog; Stop asks everything to stop and then makes sure.
See gui/launcher.

No test here signals a real pid it did not create: the OS calls are injected
and recorded, because a fake pid of 4242 is somebody's process on some machine.
"""
from __future__ import annotations

import os
import pathlib
import signal
import sys
import time

import pytest

from hivemind.gui.launcher import BotProcess, Launch


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakePopen:
    """Records the command; `alive` controls whether poll() returns None."""
    made: list = []

    def __init__(self, argv, **kw):
        self.argv, self.kw = argv, kw
        self.pid = 4242
        self.alive = True
        FakePopen.made.append(self)

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def kill(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


class Signals:
    """Stands in for os.kill / os.killpg / os.getpgid.

    `alive` is the set of pids that exist. SIGTERM to a pid in `honours`
    ends it (and the FakePopen with that pid); SIGKILL ends anything.
    """

    def __init__(self):
        self.alive: set[int] = set()
        self.honours: set[int] = set()
        self.sent: list[tuple[str, int, int]] = []

    def kill(self, pid, sig):
        if pid not in self.alive:
            raise ProcessLookupError(pid)
        if sig == 0:
            return
        self.sent.append(("kill", pid, sig))
        if sig == signal.SIGTERM and pid in self.honours:
            self._end(pid)
        if sig == signal.SIGKILL:
            self._end(pid)

    def killpg(self, pgid, sig):
        if pgid not in self.alive:
            raise ProcessLookupError(pgid)
        self.sent.append(("killpg", pgid, sig))
        if sig == signal.SIGKILL or (sig == signal.SIGTERM and pgid in self.honours):
            self._end(pgid)

    def getpgid(self, pid):
        return pid

    def _end(self, pid):
        self.alive.discard(pid)
        for p in FakePopen.made:
            if p.pid == pid:
                p.alive = False


@pytest.fixture(autouse=True)
def _clear():
    FakePopen.made.clear()


# POSIX LAUNCHER SEMANTICS (RL6, MEASURED 2026-10-21 on Windows): these tests
# drive the Linux path -- a session of its own, signals to a process group,
# a watchdog a terminal started as overnight.sh, SIGKILL. On Windows
# BotProcess launches src/hivemind/watchdog.py and stops it by files and
# Ctrl+Break, so they fail or wait forever there; that path needs tests of its
# own (docs/windows/STATUS.md).
posix_launcher = pytest.mark.skipif(
    os.name == "nt", reason="POSIX launcher semantics; Windows stops by files + Ctrl+Break")

def repo(tmp_path) -> pathlib.Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "var" / "night").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "run_farm.py").write_text("print('hi')\n")
    watchdog = root / "scripts" / "overnight.sh"
    watchdog.write_text("#!/usr/bin/env bash\necho fake watchdog\n")
    watchdog.chmod(0o755)
    # WINDOWS runs the Python watchdog instead (gui/launcher SCRIPT); without
    # it every start here was "watchdog.py is not there" (MEASURED 2026-10-21).
    (root / "src" / "hivemind").mkdir(parents=True, exist_ok=True)
    (root / "src" / "hivemind" / "watchdog.py").write_text("print('fake watchdog')\n")
    return root


def terminal_watchdog(pid=777):
    """A process `identity` (hivemind.files.process_identity) for a watchdog a
    terminal started as `bash ./overnight.sh`: ALIVE IS NOT ENOUGH (DESIGN
    8du), the pid must still be running the script."""
    return lambda p: ("bash ./overnight.sh", "1234") if p == pid else None


def bot(tmp_path, signals: Signals | None = None, **kw):
    root = repo(tmp_path)
    sig = signals or Signals()
    b = BotProcess(root=root, python=sys.executable,
                   log_path=tmp_path / "gui-run.log",
                   popen=FakePopen, clock=Clock(),
                   allow_in_tests=True,
                   kill=sig.kill, killpg=sig.killpg, getpgid=sig.getpgid, **kw)
    return b, sig


def started(tmp_path, honours=True):
    """A bot launched from the window: FakePopen pid 4242, alive."""
    b, sig = bot(tmp_path)
    sig.alive.add(4242)
    if honours:
        sig.honours.add(4242)
    launch = b.start()
    assert launch.ok, launch.reason
    return b, sig


# ------------------------------------------------------------------ starting --
@posix_launcher
def test_it_launches_the_watchdog_a_terminal_would(tmp_path):
    """Not a bare run_farm: that dies at its first rejoin. The watchdog
    relaunches the farm from disk, so a button press always gets the
    current code and survives crashes -- what the owner asked for."""
    b, sig = bot(tmp_path)
    sig.alive.add(4242)
    launch = b.start()
    assert launch.ok and launch.pid == 4242
    argv = FakePopen.made[0].argv
    assert argv[0].endswith("scripts/overnight.sh"), argv
    assert launch.log.endswith("var/night/attempts.log")
    assert "watchdog" in launch.describe() and "relaunches" in launch.describe()


@posix_launcher
def test_a_python_script_still_runs_under_this_venv(tmp_path):
    b, sig = bot(tmp_path, script="scripts/run_farm.py")
    sig.alive.add(4242)
    assert b.start().ok
    argv = FakePopen.made[0].argv
    assert argv[0] == sys.executable and argv[1].endswith("scripts/run_farm.py")


@posix_launcher
def test_it_gives_the_bot_its_own_session(tmp_path):
    """Otherwise a crash in the window signals the bot mid-walk with keys
    held, and the nested compositor is orphaned instead of torn down."""
    started(tmp_path)
    assert FakePopen.made[0].kw.get("start_new_session") is True


def test_the_output_goes_somewhere_findable(tmp_path):
    b, sig = bot(tmp_path)
    sig.alive.add(4242)
    b.start()
    log = tmp_path / "gui-run.log"
    assert log.exists()
    assert "started from the GUI" in log.read_text()


def test_a_leftover_stop_file_is_cleared_so_the_new_watchdog_runs(tmp_path):
    """The watchdog reads STOP at the top of its loop; a file left by the
    last Stop would end the new one at once."""
    b, sig = bot(tmp_path)
    sig.alive.add(4242)
    b.stop_file.write_text("")
    assert b.start().ok
    assert not b.stop_file.exists()
    assert "removed a leftover STOP" in (tmp_path / "gui-run.log").read_text()


def test_it_refuses_to_start_a_second_bot(tmp_path):
    """Two farm loops on one account would fight for the keyboard."""
    b, sig = started(tmp_path)
    again = b.start()
    assert not again.ok and "already running" in again.reason
    assert len(FakePopen.made) == 1


@posix_launcher
def test_it_refuses_when_a_watchdog_started_elsewhere_is_alive(tmp_path):
    """THE HAZARD THE FIRST VERSION HAD: it knew only its own child, so a
    press while the terminal's watchdog ran would have started a second
    farm. The watchdog's pidfile is how it knows."""
    b, sig = bot(tmp_path, identity=terminal_watchdog())
    sig.alive.add(777)
    b.pidfile.write_text("777\n")
    launch = b.start()
    assert not launch.ok and "already running" in launch.reason
    assert "777" in launch.reason and "terminal" in launch.reason
    assert FakePopen.made == []
    assert b.running() and b.pid == 777


def test_a_stale_pidfile_is_ignored_not_trusted(tmp_path):
    b, sig = bot(tmp_path)
    b.pidfile.write_text("777\n")            # 777 is not in sig.alive
    assert b.watchdog_pid() is None
    assert not b.running()
    sig.alive.add(4242)
    assert b.start().ok, "a dead pid must not block a start"


@posix_launcher
def test_a_missing_script_is_reported_not_raised(tmp_path):
    b, _ = bot(tmp_path)
    (b.root / "scripts" / "overnight.sh").unlink()
    launch = b.start()
    assert not launch.ok and "is not there" in launch.reason


def test_a_launch_failure_is_reported_not_raised(tmp_path):
    def explode(*a, **k):
        raise OSError("no such interpreter")
    b, _ = bot(tmp_path)
    b._popen = explode
    launch = b.start()
    assert not launch.ok and "no such interpreter" in launch.reason
    assert "could not start" in launch.describe()


def test_after_a_launch_it_waits_for_the_socket_then_gives_up(tmp_path):
    b, _ = started(tmp_path)
    assert b.waiting_to_connect() is True
    b.clock.t = 1000.0
    assert b.waiting_to_connect() is False


def test_nothing_is_waiting_before_a_launch(tmp_path):
    b, _ = bot(tmp_path)
    assert b.waiting_to_connect() is False
    assert b.running() is False and b.pid is None
    assert "nothing is running" in b.describe_state()


@posix_launcher
def test_the_state_line_says_who_started_the_watchdog(tmp_path):
    b, sig = started(tmp_path)
    assert "started from here" in b.describe_state()
    c, sig2 = bot(tmp_path, identity=terminal_watchdog())
    sig2.alive.add(777)
    c.pidfile.write_text("777")
    assert "terminal" in c.describe_state() and "777" in c.describe_state()


# ------------------------------------------------------------------ stopping --
@posix_launcher
def test_stop_sets_the_stop_file_and_asks_before_it_kills(tmp_path):
    """SIGTERM is the CLEAN path: the watchdog's trap forwards it and
    run_farm's handler releases every held key. STOP goes first so the
    watchdog does not relaunch the farm the moment it exits."""
    b, sig = started(tmp_path)
    outcome = b.stop(sleep=lambda s: None)
    assert b.stop_file.exists()
    assert sig.sent == [("kill", 4242, signal.SIGTERM)], sig.sent
    assert "stopped cleanly" in outcome and "released" in outcome
    assert "STOP is set" in outcome
    assert not b.running()


@posix_launcher
def test_a_bot_that_ignores_the_request_is_killed_and_the_risk_is_stated(tmp_path):
    b, sig = started(tmp_path, honours=False)

    def sleep(_):
        b.clock.t += 1.0
    outcome = b.stop(grace=5.0, sleep=sleep)
    assert ("killpg", 4242, signal.SIGKILL) in sig.sent
    assert "ignored the stop request" in outcome
    assert "key held" in outcome and "F12" in outcome
    assert not b.running()


@posix_launcher
def test_stop_reaches_a_watchdog_started_from_a_terminal(tmp_path):
    """The owner starts the bot from a terminal and stops it from the window
    -- or the other way round. The pidfile makes either work."""
    b, sig = bot(tmp_path, identity=terminal_watchdog())
    sig.alive.add(777)
    sig.honours.add(777)
    b.pidfile.write_text("777")
    outcome = b.stop(sleep=lambda s: None)
    assert sig.sent == [("kill", 777, signal.SIGTERM)]
    assert b.stop_file.exists()
    assert "stopped cleanly" in outcome
    assert not b.running()


def test_stopping_nothing_says_so(tmp_path):
    b, _ = bot(tmp_path)
    assert "no bot is running" in b.stop()


def test_stopping_an_already_dead_bot_reports_its_code(tmp_path):
    b, sig = started(tmp_path)
    sig._end(4242)
    assert "already exited" in b.stop()


# --------------------------------------------------- against the real thing --
@pytest.mark.parametrize("ignores", [False, True])
@posix_launcher
def test_it_really_signals_a_real_process(tmp_path, ignores):
    """The fakes above cannot prove a signal reaches a real child. This one
    starts a real watchdog stand-in -- a shell script that execs a python
    which either handles SIGTERM or ignores it.

    It waits for a `ready` file first. Without that the signal can arrive
    during interpreter start-up, before the child has installed its handler,
    and the "ignores it" case dies of SIGTERM anyway -- which is a race in the
    test, not behaviour worth asserting.
    """
    ready = tmp_path / "ready"
    body = ("import signal, time, pathlib\n"
            + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignores else "")
            + f"pathlib.Path({str(ready)!r}).write_text('up')\n"
            + "time.sleep(60)\n")
    root = repo(tmp_path)
    (root / "scripts" / "run_farm.py").write_text(body)
    watchdog = root / "scripts" / "overnight.sh"
    watchdog.write_text(f"#!/usr/bin/env bash\nexec {sys.executable} scripts/run_farm.py\n")
    watchdog.chmod(0o755)

    b = BotProcess(root=root, python=sys.executable,
                   log_path=tmp_path / "log.txt", allow_in_tests=True)
    launch = b.start()
    assert launch.ok, launch.reason
    deadline = time.monotonic() + 20.0
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert ready.exists(), "the child never started"

    outcome = b.stop(grace=2.0 if ignores else 15.0)
    assert not b.running(), outcome
    assert b.stop_file.exists()
    if ignores:
        assert "ignored the stop request" in outcome
        assert "F12" in outcome, "it must say a key may still be held"
    else:
        assert "stopped cleanly" in outcome


def test_describe_reads_as_a_sentence():
    assert "could not start the bot: nope" == Launch(reason="nope").describe()
    assert "started the watchdog (pid 7)" in Launch(ok=True, pid=7, log="/l").describe()


def test_it_refuses_to_launch_from_a_test_run_unless_asked(tmp_path):
    """REGRESSION, and a real one. Wiring Play to the launcher made the
    run-control tests start a real bot against the owner's live account."""
    root = repo(tmp_path)
    guarded = BotProcess(root=root, python=sys.executable,
                         log_path=tmp_path / "log.txt", popen=FakePopen)
    launch = guarded.start()
    assert not launch.ok
    assert "refusing to launch the bot from a test run" in launch.reason
    assert FakePopen.made == [], "it started something anyway"
    assert os.environ.get("PYTEST_CURRENT_TEST"), "this guard relies on pytest's marker"


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="no SIGUSR1 on Windows")
def test_stop_keep_game_sends_the_farm_sigusr1_like_deploy_keep(tmp_path):
    """RL6 phase 2 step 7: Watchdog.stop(keep_game=True) is deploy_keep.sh's
    SIGUSR1, to the FARM (the watchdog's trap knows only INT and TERM), with
    STOP set first so the watchdog exits instead of relaunching."""
    ids = {777: ("bash ./overnight.sh", "1234"), 888: ("python scripts/run_farm.py", "99")}
    b, sig = bot(tmp_path, identity=ids.get)
    sig.alive |= {777, 888}
    b.pidfile.write_text("777")
    (b.night / "run_farm.pid").write_text("888")
    plain_kill = sig.kill

    def kill(pid, s):
        plain_kill(pid, s)
        if s == signal.SIGUSR1 and pid == 888:      # the farm detaches; the watchdog sees STOP
            sig.alive -= {777, 888}
    b._kill = kill
    outcome = b.stop(sleep=lambda s: None, keep_game=True)
    assert sig.sent == [("kill", 888, signal.SIGUSR1)], sig.sent
    assert b.stop_file.exists()
    assert "stopped cleanly" in outcome and "kept" in outcome


@posix_launcher
def test_stop_keep_game_with_no_farm_is_the_plain_stop(tmp_path):
    b, sig = started(tmp_path)
    outcome = b.stop(sleep=lambda s: None, keep_game=True)
    assert sig.sent == [("kill", 4242, signal.SIGTERM)]
    assert "stopped cleanly" in outcome and "kept" not in outcome


# ---- the Windows path (RL6): files + Ctrl+Break, never a signal from here -----
# Driven on any OS by pinning launcher.WINDOWS and faking psutil. The kill-
# after-grace case (and keep_game) is test_watchdog's
# test_launcher_on_windows_asks_by_files_and_never_signals.
WIN_SCRIPT = "src/hivemind/watchdog.py"


@pytest.fixture
def windows(monkeypatch):
    import types
    from hivemind.gui import launcher
    monkeypatch.setattr(launcher, "WINDOWS", True)
    killed: list[int] = []

    class P:
        def __init__(self, pid):
            self.pid = pid

        def name(self):
            return "python.exe"

        def children(self, recursive=False):
            return []

        def kill(self):
            killed.append(self.pid)
    alive: set[int] = set()
    fake = types.SimpleNamespace(pid_exists=lambda pid: pid in alive and pid not in killed,
                                 Process=P, Error=Exception)
    monkeypatch.setitem(sys.modules, "psutil", fake)
    return types.SimpleNamespace(alive=alive, killed=killed)


def win_bot(tmp_path, **kw):
    kw.setdefault("python", "C:/Hivemind/python/pythonw.exe")   # "/" parses on both OSes
    return BotProcess(root=repo(tmp_path), script=WIN_SCRIPT,
                      log_path=tmp_path / "gui-run.log", popen=FakePopen,
                      clock=Clock(), allow_in_tests=True,
                      kill=lambda *a: pytest.fail(f"signalled {a}"),
                      killpg=lambda *a: pytest.fail(f"signalled {a}"), **kw)


def test_windows_start_runs_the_python_watchdog_in_a_console_group_of_its_own(tmp_path, windows):
    b = win_bot(tmp_path)
    for name in ("STOP", "BREAK", "KEEP"):           # the last Stop's requests
        (b.night / name).write_text("")
    launch = b.start()
    assert launch.ok, launch.reason
    made = FakePopen.made[0]
    # pythonw has no console, and Ctrl+Break needs one (gui/launcher _argv)
    assert made.argv[0].endswith("python.exe") and made.argv[0] != b.python
    assert pathlib.Path(made.argv[1]).as_posix().endswith(WIN_SCRIPT)
    assert made.kw["creationflags"] == 0x00000200 | 0x08000000
    assert "start_new_session" not in made.kw
    assert made.kw["env"]["PYTHONUTF8"] == "1"
    assert not any((b.night / n).exists() for n in ("STOP", "BREAK", "KEEP"))


def test_windows_clean_stop_asks_by_files_and_kills_nothing(tmp_path, windows):
    b = win_bot(tmp_path)
    assert b.start().ok

    def sleep(_):                                     # the watchdog saw BREAK; the farm let go
        assert (b.night / "BREAK").exists() and b.stop_file.exists()
        FakePopen.made[0].alive = False
    said = b.stop(grace=5, sleep=sleep)
    assert "stopped cleanly" in said and "kept" not in said, said
    assert not (b.night / "KEEP").exists()
    assert windows.killed == []


def test_windows_finds_a_terminal_watchdog_by_its_pidfile_and_stops_it(tmp_path, windows):
    windows.alive.add(777)
    b = win_bot(tmp_path, identity=lambda p: (
        "C:/Hivemind/python/python.exe C:/Hivemind/src/hivemind/watchdog.py", "9.500")
        if p == 777 and p in windows.alive else None)
    (b.night / "watchdog.pid").write_text("777\n")
    (b.night / "watchdog.start").write_text("9.500\n")
    assert b.watchdog_pid() == 777 and not b.start().ok   # never a second one

    def sleep(_):
        windows.alive.discard(777)
    said = b.stop(grace=5, sleep=sleep, keep_game=True)
    assert "stopped cleanly" in said and "kept" in said, said
    assert {p.name for p in b.night.iterdir()} >= {"STOP", "BREAK", "KEEP"}
    assert windows.killed == []


def test_windows_a_lone_farm_gets_no_stop_file_and_is_killed_after_grace(tmp_path, windows):
    windows.alive.add(9)
    b = win_bot(tmp_path, identity=lambda p: (
        "C:/Hivemind/python/python.exe C:/Hivemind/scripts/run_farm.py", "3.000")
        if p == 9 else None, parent=lambda p: 1)
    (b.night / "farm.lock").write_text("9 3.000\n")
    assert b.watchdog_pid() is None and b.farm_pid() == 9
    said = b.stop(grace=1, sleep=lambda s: setattr(b.clock, "t", b.clock.t + s), keep_game=True)
    # no watchdog would read them, and a stale KEEP would keep a later game
    assert not any((b.night / n).exists() for n in ("STOP", "BREAK", "KEEP"))
    assert windows.killed == [9]
    assert "no watchdog" in said and "killed" in said, said
