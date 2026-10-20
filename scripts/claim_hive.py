#!/usr/bin/env python3
"""Claim a hive. This is the step the whole project has been blocked on.

WHY THIS RUN EXISTS

Bees only exist once a hive is claimed, and a hive must be claimed on every
join. Until that happens the bot walks perfectly good routes to perfectly good
fields and collects nothing, which is exactly what five minutes of standing
still measured: 0 pollen, 0 bees visible, no reset involved.

WHAT IS DIFFERENT THIS TIME

Two earlier attempts looked for a "Claim Hive [C]" prompt near the BOTTOM of
the screen and found nothing. They were looking in the wrong half: on the
Android build -- which is what Sober runs -- the claim affordance is a large
button at the TOP of the screen. `vision.banner.find` now locates that panel,
measured 12/12 on real frames with no false positive on five other screens,
and the local vision model transcribes it exactly.

So this run does not hunt for a template. It watches the top-centre panel and
reads whatever it says.

WHAT IT WILL AND WILL NOT PRESS

Presses: `w`/`a`/`s`/`d` to walk, `space` to jump, `comma`/`period` to turn the
camera, and `e` ONLY at a slot whose panel says "claim". Never `escape`, never
`enter` -- those belong to the in-game menu that carries Leave, and nothing
here needs them.

**It never resets.** A reset is a death, and death sends every bee home to
rest. The loop that used reset as a free teleport is what kept the swarm down
all night. This run walks.

Every frame is saved, so a failed run still produces the data the next one
needs.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                              # noqa: E402
from hivemind.act.hive import (CLAIM_WORDS, MINE_WORDS,         # noqa: E402
                               NOT_A_PROMPT, TRANSCRIBE)
from hivemind.brain.vlm import VisionModel                      # noqa: E402
from hivemind.platform.current import memory                            # noqa: E402
from hivemind.vision import banner                              # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "var" / "claim"
TURN_STEPS = 8            # MEASURED: 8 camera taps is one full turn
WALK_STEP_SECONDS = 1.0
MAX_WALK_STEPS = 14


def red_bearing(frame: np.ndarray) -> tuple[int, int]:
    """(pixels right of centre, how many red pixels) for the free-pad beam.

    The game marks unclaimed pads with a red beam. Red is rare in this scene
    (~0.3% of a frame), so the centroid of red pixels is a usable bearing --
    but it is a HINT and is treated as one: the red billboard over the
    character and a pink decorative fan are also red, and in the reference
    frames they outweigh the beam four to one. The banner is the truth; this
    only decides which way to look first.
    """
    hsv = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2HSV)
    mask = cv2.bitwise_or(
        cv2.inRange(hsv, np.array([0, 150, 150]), np.array([8, 255, 255])),
        cv2.inRange(hsv, np.array([172, 150, 150]), np.array([180, 255, 255])))
    mask[:170, :] = 0        # HUD and the notification band
    mask[900:, :] = 0        # hotbar and buff icons
    ys, xs = np.nonzero(mask)
    if len(xs) < 300:
        return 0, int(len(xs))
    return int(np.median(xs)) - frame.shape[1] // 2, int(len(xs))


def read_panel(model, frame, tag: str) -> str | None:
    """Transcribe the top-centre panel, or None if there is none."""
    panel = banner.find(frame)
    if panel is None:
        return None
    crop = panel.crop(frame)[:, :, :3]
    cv2.imwrite(str(OUT / f"panel_{tag}.png"), crop)
    ok, buf = cv2.imencode(".png", crop)
    if not ok:
        return None
    answer = model.ask(buf.tobytes(), TRANSCRIBE)
    text = getattr(answer, "text", answer)
    return text if isinstance(text, str) else None


def classify(text: str) -> str:
    low = " ".join(text.lower().split())
    if any(p in low for p in NOT_A_PROMPT):
        return "join receipt (not a prompt)"
    if any(p in low for p in MINE_WORDS):
        return "MINE"
    if any(p in low for p in CLAIM_WORDS):
        return "EMPTY"
    return "unrecognised"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--look-only", action="store_true",
                    help="photograph and read, but never press the claim key")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    safe, why = memory.check("a live claim run")
    print(f"\n  memory: {why}", flush=True)
    if not safe:
        return 2

    # The model is 6 GB and the game plus compositor is another 4. Drop the
    # weights before launching and load them again only when a panel appears.
    model = VisionModel()
    if model.available():
        print(f"  unloading the vision model first: {model.unload()}", flush=True)

    print("\n  starting the game and joining the private server...", flush=True)
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}", flush=True)
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    seen: list[str] = []
    try:
        frame = cap.capture()
        cv2.imwrite(str(OUT / "00_spawn.png"), frame[:, :, :3])
        off, red = red_bearing(frame)
        print(f"  spawned. red beam bearing {off:+d} px ({red} px of red)",
              flush=True)

        # ---- look around, one full turn, photographing each step ----
        print("\n  turning a full circle to find a free pad...", flush=True)
        bearings = []
        for step in range(TURN_STEPS):
            f = cap.capture()
            cv2.imwrite(str(OUT / f"look_{step}.png"), f[:, :, :3])
            off, red = red_bearing(f)
            has = banner.find(f) is not None
            bearings.append((red, step, off))
            print(f"    {step * 45:3d}°  red {red:6d} px, bearing {off:+5d}"
                  f"{'   PANEL ON SCREEN' if has else ''}", flush=True)
            inp.tap("period")               # camera right, 45° per tap
            time.sleep(0.35)

        best_red, best_step, _ = max(bearings)
        print(f"\n  most red at {best_step * 45}° ({best_red} px) — facing that way",
              flush=True)
        for _ in range(best_step):
            inp.tap("period")
            time.sleep(0.35)
        time.sleep(0.6)

        # ---- walk toward it, checking the panel every step ----------------
        print("\n  walking toward it, reading the panel each step...", flush=True)
        for step in range(1, MAX_WALK_STEPS + 1):
            with inp.held("w"):
                time.sleep(WALK_STEP_SECONDS)
            time.sleep(0.4)
            f = cap.capture()
            cv2.imwrite(str(OUT / f"walk_{step:02d}.png"), f[:, :, :3])
            panel = banner.find(f)
            off, red = red_bearing(f)
            print(f"    step {step:2d}  red {red:6d} px, bearing {off:+5d}"
                  f"{'   PANEL' if panel else ''}", flush=True)
            if panel is None:
                continue

            if not model.available():
                print("      a panel appeared but the model is unavailable: "
                      f"{getattr(model, 'reason', '')}", flush=True)
                continue
            text = read_panel(model, f, f"walk{step:02d}")
            if not text:
                continue
            verdict = classify(text)
            seen.append(f"step {step}: {text!r} -> {verdict}")
            print(f"      panel says {text!r}  ->  {verdict}", flush=True)

            if verdict == "MINE":
                print("\n  this slot is already ours — nothing to claim.",
                      flush=True)
                return 0
            if verdict == "EMPTY":
                if args.look_only:
                    print("\n  FOUND THE CLAIM PROMPT (look-only, not pressing)",
                          flush=True)
                    return 0
                print("\n  claim prompt found — pressing E", flush=True)
                inp.tap("e")
                for poll in range(10):
                    time.sleep(0.5)
                    after = cap.capture()
                    cv2.imwrite(str(OUT / f"after_claim_{poll}.png"),
                                after[:, :, :3])
                    later = read_panel(model, after, f"after{poll}")
                    if later and classify(later) == "MINE":
                        print(f"  CLAIMED — the panel now says {later!r}",
                              flush=True)
                        return 0
                print("  pressed E but the panel never said Make Honey; "
                      "not reporting a claim that was not seen", flush=True)
                return 3

        print("\n  walked the whole budget without a panel appearing.",
              flush=True)
        return 4
    finally:
        held = getattr(inp, "held_keys", set())
        try:
            model.unload()
        except Exception:
            pass
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
        print(f"  frames in {OUT}", flush=True)
        if seen:
            print("  panels read:", flush=True)
            for line in seen:
                print(f"    {line}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
