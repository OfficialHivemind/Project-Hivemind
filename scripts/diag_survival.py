#!/usr/bin/env python3
"""Does the game stay up when we do NOTHING? The A/B for a 45-second death.

    ./.venv/bin/python scripts/diag_survival.py --minutes 3

MEASURED 2026-09-20: two farm runs in a row ended with Sober exiting about 45
seconds after launch -- 48 s and 43 s -- both within seconds of the first
synthetic keypress, and both leaving a log that stops mid-line with no error,
no OOM and no GPU fault. A `teach_map` session earlier the same afternoon ran
for twenty minutes on the same machine.

So there are two candidates and they need separating before anything is fixed:
the input we send, or the environment. This presses NOTHING, runs NO vision
model and starts NO farm loop. It boots the game exactly as the bot does, then
watches the HUD once a second and reports when it goes away.

If the game dies at ~45 s here, the bot is not causing it. If it survives, the
cause is something the bot does, and the next run adds one piece back at a time.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                       # noqa: E402
from hivemind.vision import screenstate as ss            # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=3.0)
    args = ap.parse_args()

    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}", flush=True)
        ready.close()
        return 1

    print(f"\n  pressing nothing for {args.minutes:.0f} minutes.", flush=True)
    started = time.monotonic()
    until = started + args.minutes * 60.0
    gone_since = None
    last_state = None
    try:
        while time.monotonic() < until:
            age = time.monotonic() - started
            try:
                frame = ready.capture.capture()
                here = frame is not None and ss.hud_present(frame)
            except Exception as exc:
                print(f"    {age:5.0f}s  could not capture: {exc}", flush=True)
                time.sleep(1.0)
                continue

            if here != last_state:
                print(f"    {age:5.0f}s  HUD {'present' if here else 'GONE'}",
                      flush=True)
                last_state = here
            if not here and gone_since is None:
                gone_since = age
            elif here:
                gone_since = None
            if gone_since is not None and age - gone_since > 20:
                print(f"\n  the world has been gone since {gone_since:.0f}s "
                      f"and did not come back. NOTHING WAS PRESSED.", flush=True)
                break
            time.sleep(1.0)
        else:
            print(f"\n  survived the full {args.minutes:.0f} minutes with no "
                  "input at all.", flush=True)
    except KeyboardInterrupt:
        print("\n  stopped early", flush=True)
    finally:
        ready.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
