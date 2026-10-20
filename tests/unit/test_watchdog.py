"""RL6 phase 3: the Python watchdog (hivemind/watchdog) keeps overnight.sh's
rules, and stops a run by BREAK file -> Ctrl+Break (Windows) -- all on a fake
Popen, nothing launched. Linux still runs overnight.sh."""
from __future__ import annotations

import signal
import subprocess
import threading
import types

import pytest

from hivemind import watchdog as wd


class Child:
    """A run_farm that exits with `code` once `done` is set (at once by default)."""

    def __init__(self, code=0, done=True):
        self.code, self.pid, self.signals = code, 4321, []
        self.done = threading.Event()
        if done:
            self.done.set()

    def wait(self, timeout=None):
        if not self.done.wait(timeout):
            raise subprocess.TimeoutExpired("run_farm", timeout)
        return self.code

    def poll(self):
        return self.code if self.done.is_set() else None

    def send_signal(self, sig):
        self.signals.append(sig)
        self.done.set()


@pytest.fixture
def night(monkeypatch, tmp_path):
    monkeypatch.setattr(wd.datapaths, "VAR_ROOT", tmp_path)
    monkeypatch.setattr(wd.files, "pid_running", lambda *a, **k: None)
    monkeypatch.setattr(wd.files, "process_identity", lambda pid: ("python watchdog.py", "7.000"))
    monkeypatch.setenv("HIVEMIND_SESSION_STARTED", "1")
    (tmp_path / "night").mkdir()
    return tmp_path / "night"


def dog(codes, args=(), game="", memory=(True, "memory: fine"), naps=None, children=None):
    launched = []
    children = children if children is not None else [Child(c) for c in codes]

    def popen(argv, **kw):
        launched.append((argv, kw))
        return children[len(launched) - 1]
    d = wd.Watchdog(list(args), python="py", popen=popen, gate_game=lambda: game,
                    gate_memory=lambda: memory, report=lambda: None)
    d.nap = (lambda s: naps.append(s)) if naps is not None else (lambda s: None)
    return d, launched


def ledger(night):
    return (night / "attempts.log").read_text()


def test_a_bounded_run_ends_on_exit_0_and_continues_the_numbering(night):
    (night / "run-1000.log").write_text("")
    (night / "run-999.log").write_text("")
    d, launched = dog([0], args=["--cycles", "2"])
    assert d.run() == 0
    (argv, kw), = launched
    assert argv[0] == "py" and argv[1].endswith("run_farm.py") and argv[2:] == ["--cycles", "2"]
    assert kw["env"]["HIVEMIND_ATTEMPT"] == "1001" and (night / "run-1001.log").exists()
    assert "finished the cycles it was asked for" in ledger(night)
    assert not (night / "watchdog.pid").exists()           # removed on the way out


def test_exit_0_unbounded_relaunches_and_3_ends(night):
    naps = []
    d, launched = dog([0, 3], naps=naps)
    d.run()
    assert len(launched) == 2 and naps == [wd.GAP]
    assert "restarting" in ledger(night) and "session limit" in ledger(night)


def test_the_owners_game_at_the_gate_stops_it(night):
    d, launched = dog([], game="Minecraft")
    d.run()
    assert launched == [] and (night / "STOP").exists()
    assert "you're playing Minecraft" in ledger(night)


def test_exit_5_sets_stop(night):
    d, launched = dog([5])
    d.run()
    assert len(launched) == 1 and (night / "STOP").exists()


def test_three_fast_deaths_take_the_long_gap(night, monkeypatch):
    naps = []
    d, launched = dog([1, 1, 1, 3], naps=naps)
    d.run()
    assert naps == [wd.GAP, wd.GAP, wd.LONG_GAP]


def test_waits_for_memory_then_goes(night):
    looks = iter([(False, "6.0 GB free"), (True, "9.0 GB free")])
    naps = []
    d, launched = dog([3], naps=naps)
    d.gate_memory = lambda: next(looks)
    d.run()
    assert naps == [wd.MEMORY_NAP_S] and len(launched) == 1
    assert "waiting for memory" in ledger(night)


def test_a_second_watchdog_refuses(night, monkeypatch):
    monkeypatch.setattr(wd.files, "pid_running", lambda *a, **k: 999999)
    d, launched = dog([0])
    assert d.run() == 1 and launched == []
    assert "another watchdog (pid 999999)" in ledger(night)


def test_break_stops_the_running_attempt_with_ctrl_break_on_windows(night, monkeypatch):
    sent = []
    monkeypatch.setattr(wd, "WINDOWS", True)
    monkeypatch.setattr(signal, "CTRL_BREAK_EVENT", 1, raising=False)
    child = Child(code=0, done=False)
    monkeypatch.setattr(wd.os, "kill", lambda pid, sig: sent.append((pid, sig)) or child.done.set())
    monkeypatch.setattr(wd, "POLL_S", 0.01)
    d, launched = dog([], children=[child])
    threading.Timer(0.05, (night / "BREAK").touch).start()
    d.run()
    assert sent == [(4321, signal.CTRL_BREAK_EVENT)]
    assert launched[0][1]["creationflags"] == wd.CREATE_NEW_PROCESS_GROUP
    env = launched[0][1]["env"]                    # the run log in UTF-8 (run 5: cp1252)
    assert env["PYTHONUTF8"] == "1" and env["PYTHONIOENCODING"] == "utf-8"
    assert (night / "STOP").exists() and not (night / "BREAK").exists()


def test_a_signal_to_the_watchdog_stops_the_run_off_windows(night, monkeypatch):
    monkeypatch.setattr(wd, "WINDOWS", False)
    monkeypatch.setattr(wd, "POLL_S", 0.01)
    child = Child(code=0, done=False)
    d, launched = dog([], children=[child])
    threading.Timer(0.05, d.on_signal).start()
    d.run()
    assert child.signals == [signal.SIGTERM] and (night / "STOP").exists()
    assert "creationflags" not in launched[0][1]
    assert launched[0][1]["env"].get("PYTHONUTF8") == wd.os.environ.get("PYTHONUTF8")   # Linux as it was


def test_a_stale_break_asks_nothing_of_a_new_run(night):
    (night / "BREAK").touch()
    d, launched = dog([3])
    d.run()
    assert len(launched) == 1 and not (night / "STOP").exists()


def test_run_farm_takes_ctrl_break_and_keep():
    import pathlib
    src = (pathlib.Path(wd.__file__).resolve().parents[2] / "scripts/run_farm.py").read_text()
    assert 'if hasattr(signal, "SIGBREAK"):' in src
    assert '(ROOT / "var" / "night" / "KEEP").unlink()' in src
    assert wd.KEEP == "KEEP" and wd.BREAK == "BREAK"


# ---- the GUI's end on Windows (gui/launcher.BotProcess) --------------------------------------
def test_launcher_on_windows_asks_by_files_and_never_signals(monkeypatch, tmp_path):
    from hivemind.gui import launcher
    monkeypatch.setattr(launcher, "WINDOWS", True)
    killed = []

    class P:
        def __init__(self, pid, name="python.exe"):
            self.pid, self._name = pid, name

        def name(self):
            return self._name

        def children(self, recursive=False):
            return [P(2, "python.exe"), P(3, "RobloxPlayerBeta.exe")]

        def kill(self):
            killed.append(self.pid)
    fake = types.SimpleNamespace(pid_exists=lambda pid: pid == 1 and not killed,
                                 Process=lambda pid: P(pid), Error=Exception)
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake)
    bot = launcher.BotProcess(root=tmp_path, kill=lambda *a: pytest.fail("signalled"),
                              identity=lambda pid: ("python src/hivemind/watchdog.py", "5.0"))
    monkeypatch.setattr(bot, "watchdog_pid", lambda: 1)
    clock = iter(range(0, 1000))
    bot.clock = lambda: next(clock)
    said = bot.stop(grace=3, sleep=lambda s: None, keep_game=True)
    night = tmp_path / "var" / "night"
    assert {p.name for p in night.iterdir()} == {"STOP", "BREAK", "KEEP"}
    assert killed == [1, 2]                        # the tree, never the Roblox in it
    assert "killed" in said
