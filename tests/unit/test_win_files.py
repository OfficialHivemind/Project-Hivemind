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


# ---- a rename or a read refused while another handle has the file open ------
# MEASURED 2026-10-26 on Windows 11: os.replace onto a file open elsewhere
# raises PermissionError (WinError 5), and so does opening it mid-rename.

def _flaky(times, then):
    calls = {"n": 0}

    def act(*a, **kw):
        calls["n"] += 1
        if calls["n"] <= times:
            raise PermissionError(13, "Access is denied")
        return then(*a, **kw)
    return act, calls


def test_atomic_write_retries_a_refused_rename_on_windows(monkeypatch, tmp_path):
    from hivemind import files
    real = os.replace
    flaky, calls = _flaky(3, real)
    monkeypatch.setattr(files, "WINDOWS", True)
    monkeypatch.setattr(files, "REPLACE_WAIT_S", 0.0)
    monkeypatch.setattr(files.os, "replace", flaky)
    files.atomic_write(tmp_path / "x.yaml", "new\n")
    assert (tmp_path / "x.yaml").read_text() == "new\n" and calls["n"] == 4
    assert [p.name for p in tmp_path.iterdir()] == ["x.yaml"]       # no temp left


def test_a_rename_refused_for_good_still_raises_and_linux_never_retries(monkeypatch, tmp_path):
    from hivemind import files
    flaky, calls = _flaky(10_000, os.replace)
    monkeypatch.setattr(files, "REPLACE_WAIT_S", 0.0)
    monkeypatch.setattr(files.os, "replace", flaky)
    monkeypatch.setattr(files, "WINDOWS", True)
    with pytest.raises(PermissionError):
        files.atomic_write(tmp_path / "x.yaml", "new\n")
    assert calls["n"] == files.REPLACE_TRIES
    assert list(tmp_path.iterdir()) == []                            # the temp removed
    monkeypatch.setattr(files, "WINDOWS", False)
    calls["n"] = 0
    with pytest.raises(PermissionError):
        files.atomic_write(tmp_path / "x.yaml", "new\n")
    assert calls["n"] == 1


def test_read_text_retries_a_refused_open_on_windows(monkeypatch, tmp_path):
    from hivemind import files
    (tmp_path / "s.env").write_text("A=1\n")
    real = files.Path.read_text
    flaky, calls = _flaky(2, real)
    monkeypatch.setattr(files, "WINDOWS", True)
    monkeypatch.setattr(files, "REPLACE_WAIT_S", 0.0)
    monkeypatch.setattr(files.Path, "read_text", flaky)
    assert files.read_text(tmp_path / "s.env") == "A=1\n" and calls["n"] == 3


def test_settings_read_through_the_retrying_reader():
    """A refused read was the defaults (settings) or an empty secrets.env,
    which write_secret then rewrote with one secret."""
    from pathlib import Path

    from hivemind.world import settings
    text = Path(settings.__file__).read_text(encoding="utf-8")
    assert "text = read_text(secrets_path(config))" in text
    assert "stored = yaml.safe_load(read_text(self.path))" in text
    # ...and so do migrate_secrets' read of settings.yaml and the presets'
    assert "stored = yaml.safe_load(read_text(config)) if config.exists()" in text
    assert "loaded = yaml.safe_load(read_text(path))" in text
    assert "Path.read_text" not in text.replace("files.read_text", "")
    assert ".read_text()" not in text


def _refusing_secrets(monkeypatch, tmp_path):
    """settings.yaml holding a secret to move, and a secrets.env with two
    secrets that every read refuses (as a rename that never let go would)."""
    from hivemind.world import settings
    config = tmp_path / "settings.yaml"
    config.write_text("server.link: https://example.invalid/new\ngui.mode: advanced\n",
                      encoding="utf-8")
    secrets = settings.secrets_path(config)
    secrets.write_text("YOUTUBE_API_KEY=kept-1\nSHARE_LINK=kept-2\n", encoding="utf-8")
    real = settings.read_text

    def read_text(path, *a, **kw):
        if os.path.basename(str(path)) == "secrets.env":
            raise PermissionError(13, "Access is denied")
        return real(path, *a, **kw)
    monkeypatch.setattr(settings, "read_text", read_text)
    return settings, config, secrets


def test_write_secret_refuses_to_rewrite_a_secrets_file_it_could_not_read(monkeypatch, tmp_path):
    """A refused read was {} and the rewrite kept one secret of three."""
    settings, config, secrets = _refusing_secrets(monkeypatch, tmp_path)
    with pytest.raises(PermissionError):
        settings.write_secret(config, "server.link", "https://example.invalid/x")
    assert secrets.read_text(encoding="utf-8") == "YOUTUBE_API_KEY=kept-1\nSHARE_LINK=kept-2\n"
    assert settings.read_secrets(config) == {}           # a plain read still says "none"


def test_migrate_secrets_moves_nothing_when_secrets_env_is_unreadable(monkeypatch, tmp_path):
    settings, config, secrets = _refusing_secrets(monkeypatch, tmp_path)
    before = config.read_text(encoding="utf-8")
    assert settings.migrate_secrets(config) == []
    assert secrets.read_text(encoding="utf-8") == "YOUTUBE_API_KEY=kept-1\nSHARE_LINK=kept-2\n"
    assert config.read_text(encoding="utf-8") == before   # the secret stays where it was


def test_a_missing_secrets_env_is_still_written_fresh(tmp_path):
    from hivemind.world import settings
    config = tmp_path / "settings.yaml"
    config.write_text("server.link: https://example.invalid/new\n", encoding="utf-8")
    assert settings.migrate_secrets(config) == ["server.link"]
    assert settings.read_secrets(config) == {"server.link": "https://example.invalid/new"}
    settings.write_secret(config, "stream.youtube_api_key", "k")
    assert settings.read_secrets(config) == {"server.link": "https://example.invalid/new",
                                             "stream.youtube_api_key": "k"}
