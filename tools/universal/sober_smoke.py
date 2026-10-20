"""RL1b step 2: Sober itself in the headless labwc, measured. OWNER PRESENT,
THE BOT STOPPED, no game of his open (docs/pending/universal-linux.md, step 2).

Forces the labwc session for THIS run only (platform/current), so settings.yaml
is never touched and nothing needs rolling back. Joins his private server the
bot's normal way (act/bootstrap.start), then, standing still in the world:
  * HUD: the Honey and Pollen pills (vision/screenstate.hud_present)
  * fps: how many captures in 3 s differ from the one before while W is held
  * movement: the mean frame change after 0.4 s of each of W, A, S, D
  * pointer: a click in the world, then W again -- does input still arrive?
Frames go to var/rl1b-smoke/. Ends Sober and labwc on exit (ready.close).

  HIVEMIND_LABWC=<labwc> ./.venv/bin/python tools/universal/sober_smoke.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import cv2                                                  # noqa: E402
import numpy as np                                          # noqa: E402

from hivemind.act import bootstrap                          # noqa: E402
from hivemind.platform import current                       # noqa: E402
from hivemind.platform.wlr_session import WlrSession, find_labwc   # noqa: E402
from hivemind.vision import screenstate as ss               # noqa: E402

OUT = ROOT / "var" / "rl1b-smoke"


def diff(a, b) -> float:
    return float(np.abs(a[:, :, :3].astype(np.int16) - b[:, :, :3]).mean())


def main() -> int:
    if find_labwc() is None:
        print("no labwc: set HIVEMIND_LABWC (tools/universal/fetch_compositor.sh)")
        return 2
    current._session_class = lambda: WlrSession            # this run only
    OUT.mkdir(parents=True, exist_ok=True)
    ready = bootstrap.start(private=True)
    try:
        s = ready.session
        print(f"JOIN: ok={ready.ok} in {ready.seconds:.0f}s ({ready.reason})")
        print(f"WINDOWS:\n{s.describe_windows()}")
        cap, inp = ready.capture, ready.input
        frame = cap.capture()
        cv2.imwrite(str(OUT / "joined.png"), frame[:, :, :3])
        print(f"FRAME: {frame.shape[1]}x{frame.shape[0]}  HUD: {ss.hud_present(frame)}")
        if not ready.ok:
            return 1
        with inp.held("w"):
            prev, changed, n, t0 = cap.capture(), 0, 0, time.monotonic()
            while time.monotonic() - t0 < 3.0:
                f = cap.capture()
                changed += diff(f, prev) > 0.5
                n, prev = n + 1, f
        print(f"FPS (frames that changed, W held): {changed / 3.0:.1f}/s of {n / 3.0:.1f} captures/s")
        for key in ("w", "a", "s", "d"):
            before = cap.capture()
            with inp.held(key):
                time.sleep(0.4)
            after = cap.capture()
            cv2.imwrite(str(OUT / f"after_{key}.png"), after[:, :, :3])
            print(f"MOVE {key.upper()}: mean change {diff(after, before):.1f}")
        inp.click(960, 700)
        time.sleep(0.5)
        before = cap.capture()
        with inp.held("w"):
            time.sleep(0.4)
        print(f"AFTER A CLICK, W: mean change {diff(cap.capture(), before):.1f} "
              f"HUD: {ss.hud_present(cap.capture())}")
        return 0
    finally:
        ready.close()


if __name__ == "__main__":
    sys.exit(main())
