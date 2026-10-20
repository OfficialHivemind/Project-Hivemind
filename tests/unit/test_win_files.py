"""RL6 phase 3: win/files with psutil and msvcrt faked (runs on Linux)."""
from __future__ import annotations

import os
import sys
import types

import pytest

from hivemind.platform.win import files as wf


class Error(Exception):
    pass


class AccessDenied(Error):
    pass


class FakeProc:
    table = {}

    def __init__(self, pid):
        if pid not in self.table:
            raise Error("no such process")
        self.pid = pid
        self.name_, self.cmd, self.start, self.parent = self.table[pid]

    def name(self):
        return self.name_

    def create_time(self):
        return self.start

    def ppid(self):
        return self.parent

    def cmdline(self):
        if self.name_.lower() == wf.ROBLOX:
            raise AssertionError("a Roblox process's command line was read")
        if self.cmd is None:
            raise AccessDenied()
        return self.cmd


@pytest.fixture(autouse=True)
def fake_psutil(monkeypatch):
    FakeProc.table = {
        10: ("python.exe", ["python", "scripts/run_farm.py"], 1700000000.25, 4),
        11: ("RobloxPlayerBeta.exe", ["never read"], 1700000100.5, 10),
        12: ("svchost.exe", None, 1600000000.0, 4),
        os.getpid(): ("python.exe", ["python", "-m", "pytest"], 1700000200.0, 1),
    }
    monkeypatch.setattr(wf, "psutil", types.SimpleNamespace(
        Process=FakeProc, Error=Error, AccessDenied=AccessDenied, ZombieProcess=Error))


def test_identity_is_cmdline_and_create_time():
    assert wf.process_identity(10) == ("python scripts/run_farm.py", "1700000000.250")
    assert wf.process_identity(999) is None
    assert wf.process_identity("not a pid") is None


def test_windows_paths_match_the_forward_slash_names(tmp_path):
    """RL6i: an installed watchdog runs C:\\...\\scripts\\run_farm.py; the GUI
    asks for "scripts/run_farm.py"."""
    FakeProc.table[13] = ("python.exe", [r"C:\App\python\python.exe",
                                         r"C:\App\scripts\run_farm.py"], 1700000300.0, 4)
    assert wf.process_identity(13)[0] == "C:/App/python/python.exe C:/App/scripts/run_farm.py"
    pidfile = tmp_path / "run_farm.pid"
    pidfile.write_text("13\n")
    assert wf.pid_running(pidfile, "scripts/run_farm.py") == 13


def test_roblox_gives_its_name_only():
    assert wf.process_identity(11) == ("RobloxPlayerBeta.exe", "1700000100.500")


def test_another_users_process_gives_its_name():
    assert wf.process_identity(12)[0] == "svchost.exe"


def test_parent():
    assert wf.process_parent(11) == 10 and wf.process_parent(999) is None


def test_pid_running_is_the_shared_rule(tmp_path):
    pidfile = tmp_path / "farm.pid"
    pidfile.write_text("10 1700000000.250\n")
    assert wf.pid_running(pidfile, "run_farm.py") == 10
    pidfile.write_text("10 1700000000.999\n")               # pid reused
    assert wf.pid_running(pidfile, "run_farm.py") is None
    pidfile.write_text("11\n")                               # the game, after a wrap
    assert wf.pid_running(pidfile, "run_farm.py") is None


class FakeMsvcrt(types.ModuleType):
    LK_NBLCK = 2
    held: dict = {}

    def __init__(self):
        super().__init__("msvcrt")

    def locking(self, fd, mode, n):
        assert mode == self.LK_NBLCK and n == 1
        where = (os.fstat(fd).st_ino, os.lseek(fd, 0, os.SEEK_CUR))
        assert where[1] == wf.LOCK_OFFSET
        if where in self.held:
            raise OSError("locked by another process")
        self.held[where] = fd


def test_take_lock_writes_the_pid_and_refuses_a_second(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt())
    lock = tmp_path / "night" / "farm.lock"
    first = wf.take_lock(lock)
    assert first is not None
    assert lock.read_text() == f"{os.getpid()} 1700000200.000\n"
    assert os.path.getsize(lock) < wf.LOCK_OFFSET            # the lock byte is past EOF
    lock.write_text(lock.read_text())                        # still readable by others
    assert wf.take_lock(lock) is None
    assert lock.read_text().startswith(str(os.getpid()))    # a refusal wipes nothing
    first.close()
