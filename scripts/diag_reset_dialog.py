#!/usr/bin/env python3
"""What does the Roblox reset dialog look like, so it can be confirmed safely?

BeeTuxMacro resets with Escape, R, Return, and 4 of the transpiled routes
contain a reset. A reset fixes both position and heading, which is what makes
open-loop routes repeatable, so the bot needs it.

But Return pressed at the wrong moment is not recoverable. Roblox's in-game
menu carries **Log Out** and **Leave** as ordinary activatable tiles, so a
Return that lands while the menu is on the wrong page can log the owner out of
their account or quit the game.

This captures the frames WITHOUT ever pressing Return, so the confirmation
check can be built against what is really on screen rather than an assumption.
It presses Escape (opens the menu) and R (opens the reset confirmation), saves
both, and then presses Escape again to back out.
"""
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                  # noqa: E402
from hivemind.vision import screenstate as ss       # noqa: E402

OUT = pathlib.Path("/tmp/hivemind-diag/resetdlg")


def snap(cap, name):
    frame = cap.capture()
    cv2.imwrite(str(OUT / f"{name}.png"), frame[:, :, :3])
    modal = ss.find_modal(frame)
    state = ss.classify(frame)
    print(f"  {name:<16} state={state.value:<10} modal="
          f"{'yes' if modal else 'no':<4}", end="", flush=True)
    if modal:
        print(f" at ({modal.x},{modal.y}) {modal.w}x{modal.h}, "
              f"{len(modal.buttons)} buttons", flush=True)
    else:
        print(flush=True)
    return frame, modal


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    try:
        print("\n  NOTE: this never presses Return.\n", flush=True)
        snap(cap, "0_in_game")

        inp.tap("escape")
        time.sleep(0.8)
        snap(cap, "1_after_escape")

        inp.tap("r")
        time.sleep(0.8)
        snap(cap, "2_after_r")

        # back out without confirming anything
        inp.tap("escape")
        time.sleep(0.8)
        snap(cap, "3_backed_out")
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
