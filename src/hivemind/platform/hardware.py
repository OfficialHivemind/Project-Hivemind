"""This PC's processor, memory and graphics card, measured once (ROADMAP AI-N4).

`probe()` is what world/aimode.pick decides Eco / Standard / Max from. run_farm
calls it at each start (before it sets OpenCV's threads) and the doctor calls
it to show the choice. It costs about a quarter of a second: a few stage-1
passes of the coin finder on a fixed picture, on ONE OpenCV thread (the
thread count is put back after).
"""
from __future__ import annotations

import os
import shutil
import statistics
import subprocess
import time
from pathlib import Path

from ..world.aimode import Hardware
from .current import memory

DRM = Path("/sys/class/drm")
PASSES = 5


def probe_ms(passes: int = PASSES) -> float | None:
    """Median ms of the coin finder's stage 1 on a fixed 1920x1080 picture,
    1 OpenCV thread (world/aimode REFERENCE_PROBE_MS); None without its model."""
    try:
        import cv2
        import numpy as np

        from ..vision import coins
    except ImportError:
        return None
    m = coins.model()
    if m is None:
        return None
    rng = np.random.default_rng(7)
    picture = cv2.GaussianBlur(rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8),
                               (0, 0), 3)
    work = coins.work_image(picture)
    threads = cv2.getNumThreads()
    cv2.setNumThreads(1)
    try:
        coins.candidates(work, m, 1920, 1080)                  # warm-up
        times = []
        for _ in range(passes):
            began = time.perf_counter()
            coins.candidates(work, m, 1920, 1080)
            times.append(1000 * (time.perf_counter() - began))
    finally:
        cv2.setNumThreads(threads)
    return statistics.median(times)


def vram_gb(drm: Path = DRM) -> float | None:
    """Total graphics memory of the biggest card, GB: amdgpu's sysfs files
    AND nvidia-smi, both always asked (a Ryzen's built-in amdgpu, 0.5 GB on
    the owner's PC MEASURED /sys/class/drm/card0, sits beside an NVIDIA card
    on many PCs); None when neither says (Intel, or Windows on AMD).
    ponytail: no Windows AMD/Intel reader; add one (DXGI) when a Windows
    tester needs auto to see the card."""
    sizes = []
    for card in drm.glob("card*"):
        try:
            sizes.append(int((card / "device/mem_info_vram_total").read_text()) / 1024 ** 3)
        except (OSError, ValueError):
            continue                     # a connector (card1-DP-1), or no amdgpu
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=memory.total",
                                  "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=3).stdout
            sizes += [float(line) / 1024 for line in out.split() if line.strip()]
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return max(sizes) if sizes else None


def probe() -> Hardware:
    m = memory.read()
    return Hardware(cpus=os.cpu_count() or 1, probe_ms=probe_ms(),
                    ram_total_gb=m.total_gb, ram_free_gb=m.available_gb,
                    vram_gb=vram_gb())
