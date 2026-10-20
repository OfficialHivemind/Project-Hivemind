"""RL6 phase 3: win/memory on a faked psutil. The policy is Linux's; only
the readers are tested here."""
from __future__ import annotations

import types

import pytest

from hivemind.platform import memory as linux
from hivemind.platform.win import memory as wm

GB = 1024 ** 3


class FakePsutil:
    Error = type("Error", (Exception,), {})

    def __init__(self, avail=16, total=32, swap_used=1, swap_total=8, procs=(), rss=0.3):
        self.vm = types.SimpleNamespace(available=avail * GB, total=total * GB)
        self.sw = types.SimpleNamespace(used=swap_used * GB, total=swap_total * GB)
        self.procs, self.rss = procs, rss

    def virtual_memory(self):
        return self.vm

    def swap_memory(self):
        return self.sw

    def process_iter(self, attrs):
        assert set(attrs) <= {"name", "memory_info"}     # names and sizes only
        return [types.SimpleNamespace(info={"name": n, "memory_info": types.SimpleNamespace(rss=g * GB)})
                for n, g in self.procs]

    def Process(self):
        return types.SimpleNamespace(memory_info=lambda: types.SimpleNamespace(rss=self.rss * GB))


@pytest.fixture
def fake(monkeypatch):
    def use(**kw):
        ps = FakePsutil(**kw)
        monkeypatch.setattr(wm, "psutil", ps)
        return ps
    return use


def test_read_fills_the_shared_record_without_psi(fake):
    fake(avail=12.5, total=32, swap_used=2, swap_total=8)
    m = wm.read()
    assert isinstance(m, linux.Memory)
    assert (m.available_gb, m.total_gb, m.swap_used_gb, m.swap_total_gb) == (12.5, 32, 2, 8)
    assert m.stall_pct is None and m.stall_now_pct is None
    assert wm.read_stall() == (None, None) and wm.vram_free_gb() is None


def test_check_uses_the_windows_floor(fake):
    # Windows runs no Sober, compositor or vision model: the floor is the
    # game's own size (2026-10-19, the owner's 16 GB PC refused at 0.7 GB).
    fake(avail=wm.WIN_SAFE_TO_START_GB + 0.5)
    ok, why = wm.check("the game")
    assert ok and "GB available" in why
    fake(avail=wm.WIN_SAFE_TO_START_GB - 0.5)
    ok, why = wm.check("the game")
    assert not ok and "not enough memory to start the game" in why
    assert "browser" in why                      # Windows advice, not the vision model
    # a kept game asks for a quarter
    assert wm.check("the game", kept=True)[0]


def test_unreadable_memory_proceeds(fake, monkeypatch):
    ps = fake()
    ps.virtual_memory = lambda: (_ for _ in ()).throw(OSError("no"))
    assert wm.read().total_gb == 0.0
    assert wm.check()[0] is True


def test_model_rss_is_the_largest_llama_server(fake):
    fake(procs=[("llama-server.exe", 1.5), ("LLAMA-SERVER.EXE", 2.5), ("chrome.exe", 9)])
    assert wm.model_rss_gb() == 2.5
    fake(procs=[("chrome.exe", 9)])
    assert wm.model_rss_gb() is None


def test_selfwatch_reads_this_process_through_psutil(fake):
    ps = fake(rss=0.5)
    watch = wm.SelfWatch(ceiling_gb=1.0)
    assert watch.start_gb == 0.5 and watch.check("start") is None
    ps.rss = 1.2
    assert "grown to 1.2 GB" in watch.check("cycle 9")
    assert watch.grown_gb == pytest.approx(0.7)
