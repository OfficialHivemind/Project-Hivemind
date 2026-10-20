#!/usr/bin/env python3
"""Which part of the vision stack grows without bound?

WHY. Three processes were killed by the kernel OOM killer on 2026-09-20, and
the kernel named the same victim every time: a single `python` holding
16-25 GB.

    Out of memory: Killed process 230442 (python) anon-rss:23481892kB
    Out of memory: Killed process 210523 (python) anon-rss:25210976kB
    Out of memory: Killed process 227158 (python) anon-rss:16140436kB

The machine has 30 GB and was otherwise using about 9, so this is not a tight
machine -- it is one process eating everything. Reading the code did not find
it: the screencopy pool is reused and its buffers destroyed in a `finally`,
FlowTracker keeps only `_prev`, and the farm loop's per-cycle append is a few
hundred bytes every several minutes.

So measure instead of reading. This feeds synthetic frames through each layer
in isolation and reports RSS growth per thousand iterations. Nothing here
touches the game, the compositor or the network.

SAFETY. Run it capped, so a probe that finds the leak cannot repeat the
accident it is investigating:

    systemd-run --user --scope -p MemoryMax=1500M -p MemorySwapMax=0 -- \
        ./.venv/bin/python scripts/diag_leak.py
"""
import gc
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

W, H = 1920, 1080
ITERS = 300


def rss_mb() -> float:
    for line in pathlib.Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024
    return 0.0


def frame(i: int) -> np.ndarray:
    """A frame with real texture that MOVES, so flow has something to track."""
    rng = np.random.default_rng(i)
    img = rng.integers(0, 255, (H, W, 4), dtype=np.uint8)
    return img


def probe(name: str, fn, iters: int = ITERS) -> None:
    gc.collect()
    before = rss_mb()
    for i in range(iters):
        fn(i)
    gc.collect()
    after = rss_mb()
    grew = after - before
    verdict = "LEAK" if grew > 50 else "ok"
    print(f"  {name:28s} {before:7.0f} -> {after:7.0f} MB  "
          f"({grew:+.0f} MB over {iters})  {verdict}", flush=True)


def main() -> int:
    print(f"\n  baseline RSS {rss_mb():.0f} MB, {ITERS} iterations per probe\n",
          flush=True)

    # 1. allocating frames at all -- the control. If this grows, the probe
    #    itself is wrong and nothing below it can be trusted.
    probe("make a frame (control)", lambda i: frame(i))

    from hivemind.vision.flow import FlowTracker
    tracker = FlowTracker()
    probe("FlowTracker.update", lambda i: tracker.update(frame(i)))

    from hivemind.vision import templates as T
    tpl = frame(0)[100:140, 100:180, :3].copy()
    probe("templates.find", lambda i: T.find(frame(i)[:, :, :3], tpl))

    from hivemind.vision import blobs
    from hivemind.vision.color import Band
    band = Band("probe", (0, 0, 0), (180, 255, 255))
    probe("blobs.find on a mask",
          lambda i: blobs.find(band.mask(frame(i)[:, :, :3]), min_area=800))

    try:
        from hivemind.vision.hud import HudReader
        from hivemind.vision.digits import TemplateSet
        ts = TemplateSet()
        hud = HudReader(lambda: frame(0), ts)
        probe("HudReader.pollen", lambda i: hud.pollen())
    except Exception as exc:
        print(f"  HudReader                    skipped: "
              f"{type(exc).__name__}: {exc}", flush=True)

    print(f"\n  final RSS {rss_mb():.0f} MB\n", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
