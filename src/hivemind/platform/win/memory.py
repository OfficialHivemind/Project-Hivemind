"""The machine's memory on Windows (platform/api Memory), read with psutil.

Only the READERS are here, and two Windows lines. The policy -- the Memory
record and its lines (under_pressure, short_for, step_aside_reason), the
thresholds, SelfWatch -- is platform/memory's, imported as it is, except the
start floor (`check`, WIN_SAFE_TO_START_GB) and the step-aside line
(WinMemory, STEP_ASIDE_GB), which are Windows' own: no Sober, compositor or
model to make room for.

What Windows has not got:
  * PSI (/proc/pressure/memory). The stall figures are None, which the
    policy already reads as "use the old doubled floor" for a full swap.
  * amdgpu's VRAM files. vram_free_gb is None; only the alt reads it, and
    the alt is Linux-only.
Swap is the pagefile (psutil swap_memory) [MEASURED 2026-10-26: psutil's
total/used matched Win32_PageFileUsage's AllocatedBaseSize/CurrentUsage].
"""
from __future__ import annotations

from dataclasses import dataclass

import psutil

from ..memory import (ESSENTIAL_LOAD_GB, GAME_GB, MODEL_DROP_GB, MODEL_LOAD_COST_GB,
                      MODEL_LOAD_GB, MODEL_RSS_CAP_GB, SAFE_TO_START_GB, SELF_CEILING_GB,
                      Memory)
from ..memory import SelfWatch as _SelfWatch

# The policy's names callers read off the module (run_farm, brain/vlm), so
# this module stands in for platform/memory wherever current.memory is used.
__all__ = ["ESSENTIAL_LOAD_GB", "GAME_GB", "MODEL_DROP_GB", "MODEL_LOAD_COST_GB",
           "MODEL_LOAD_GB", "MODEL_RSS_CAP_GB", "SAFE_TO_START_GB", "SELF_CEILING_GB",
           "STEP_ASIDE_GB", "Memory", "WinMemory", "SelfWatch", "MODEL_PROCESS", "read", "read_stall",
           "vram_free_gb", "rss_gb", "model_rss_gb", "check"]

GB = 1024 ** 3
# The local model server's process [assumed: ollama's Windows build runs
# llama-server.exe like the Linux one runs llama-server].
MODEL_PROCESS = "llama-server.exe"


def read() -> Memory:
    """Current memory; zeros if it cannot be read (as on Linux)."""
    try:
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    except (OSError, RuntimeError, psutil.Error):
        return WinMemory(0.0, 0.0, 0.0, 0.0)
    return WinMemory(available_gb=vm.available / GB, total_gb=vm.total / GB,
                     swap_used_gb=sw.used / GB, swap_total_gb=sw.total / GB,
                     stall_pct=None, stall_now_pct=None)


def read_stall() -> tuple[float | None, float | None]:
    return None, None                      # no PSI on Windows


def vram_free_gb() -> float | None:
    return None


def rss_gb() -> float:
    """This process's resident memory (working set). 0.0 if unreadable."""
    try:
        return psutil.Process().memory_info().rss / GB
    except (OSError, psutil.Error):
        return 0.0


def model_rss_gb() -> float | None:
    """The model server's resident memory, the largest when several run,
    None when none does. Names and memory_info only: nothing is opened for
    reading inside another process (plan: no access to the game process, screen and input only)."""
    largest = None
    for p in psutil.process_iter(["name", "memory_info"]):
        info = p.info
        if (info.get("name") or "").lower() != MODEL_PROCESS or not info.get("memory_info"):
            continue
        gb = info["memory_info"].rss / GB
        largest = gb if largest is None else max(largest, gb)
    return largest


# WINDOWS HAS NO SOBER, NO NESTED COMPOSITOR AND NO VISION MODEL: the Linux
# 6 GB floor (platform/memory SAFE_TO_START_GB) refused every start on the
# a 16 GB test PC (2026-10-19, 0.6-0.7 GB available). Roblox's client
# needs about 1.5-2 GB [assumed: commonly reported, not measured here], and
# Windows pages to its pagefile rather than stalling, so the Windows floor is
# the game's own size. ponytail: a fixed floor; measure the Windows client's
# footprint on the first real runs and tune it.
WIN_SAFE_TO_START_GB = 2.0

# AND THE LINE A RUNNING BOT STEPS ASIDE AT (run_farm step_aside_if_short).
# Linux's is its start floor less the game (platform/memory STEP_ASIDE_GB =
# 6 - 4 = 2 GB). Taken as it was, it equalled the Windows START floor, so a
# start at 2-4 GB available launched Roblox (~1.5-2 GB) and the next two
# readings stepped aside: a rejoin loop. MEASURED 2026-10-26 on a
# Windows 11 PC with no game of ours open (the Windows platform check):
# 0.9-1.8 GB available, step_aside_reason "only 0.9 GB of memory left (the
# line is 2 GB)". So Windows uses its own floor less the game, as Linux
# does: a quarter of it, the same room a kept game is asked for.
# ponytail: 0.5 GB is not measured against a real run; Windows pages to its
# pagefile before it fails an allocation.
STEP_ASIDE_GB = WIN_SAFE_TO_START_GB / 4


@dataclass(frozen=True)
class WinMemory(Memory):
    """platform/memory's record with the Windows step-aside line. No PSI on
    Windows, so the stall test of Linux's never applies."""

    def step_aside_reason(self) -> str | None:
        if self.total_gb == 0.0:
            return None
        if self.available_gb < STEP_ASIDE_GB:
            return (f"only {self.available_gb:.1f} GB of memory left "
                    f"(the line is {STEP_ASIDE_GB:.1f} GB)")
        return None


def check(what: str = "this", kept: bool = False) -> tuple[bool, str]:
    """Enough memory to start `what` on Windows: WIN_SAFE_TO_START_GB
    available (a quarter of it to attach to a kept game)."""
    memory = read()
    if memory.total_gb == 0.0:
        return True, "could not read the memory figures — proceeding"
    need = WIN_SAFE_TO_START_GB / 4 if kept else WIN_SAFE_TO_START_GB
    said = f"{memory.available_gb:.1f} GB available of {memory.total_gb:.0f}"
    if memory.available_gb < need:
        return False, (f"not enough memory to start {what}: {said}, it wants "
                       f"{need:.1f} GB. Close something large first (a browser "
                       f"with many tabs, another game, OBS) and press Play again")
    return True, said


class SelfWatch(_SelfWatch):
    """platform/memory.SelfWatch reading this process through psutil."""

    def __init__(self, ceiling_gb: float = SELF_CEILING_GB, keep: int = 240):
        super().__init__(ceiling_gb, keep)
        self.start_gb = rss_gb()

    def sample(self, note: str = "") -> float:
        now = rss_gb()
        self.samples.append((note, now))
        return now

    @property
    def grown_gb(self) -> float:
        return max(0.0, rss_gb() - self.start_gb)
