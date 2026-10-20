#!/usr/bin/env python3
"""Press E on our own pad and WATCH what the HUD does, half-second by half-second.

WHY. Three live cycles on 2026-09-21 reported "pressed E ... +0 honey" two
seconds apart, and the backpack has read 88,322 pollen before and after every
one of them. The dwell in brain/farm ends the moment the pollen pill reads 0;
the suspicion is that the pill reads 0 (or unreadably) the instant conversion
STARTS, so the loop declares victory, the next cycle walks off the pad, and
stepping off stops the conversion. This script does not fix anything. It
records what the two counters actually read for 25 seconds after E, so the
dwell can be rewritten against a measurement instead of a theory.

It presses exactly what a farm cycle presses to reach this point -- the hive
sweep's E to claim, then one E to convert -- and nothing else.

    ./.venv/bin/python scripts/diag_convert.py
"""
from __future__ import annotations

import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                      # noqa: E402
from hivemind.act.hive import TRANSCRIBE, sweep_and_claim  # noqa: E402
from hivemind.brain.farm import HudReader               # noqa: E402
from hivemind.brain.vlm import VisionModel              # noqa: E402
from hivemind.platform.current import memory                    # noqa: E402
from hivemind.vision import banner                      # noqa: E402
from hivemind.vision import screenstate as ss           # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "var" / "diag_convert"
WATCH_SECONDS = 25.0
EVERY = 0.5


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    safe, note = memory.check("the game")
    print(f"  memory: {note}", flush=True)
    if not safe:
        return 2
    VisionModel().unload()
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  FAILED: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    print(f"  in game in {ready.seconds:.0f}s", flush=True)
    model = VisionModel()

    def read_panel(frame):
        panel = banner.find(frame)
        if panel is None or not model.available():
            return "" if panel is None else None
        ok, buf = cv2.imencode(".png", panel.crop(frame)[:, :, :3])
        if not ok:
            return None
        answer = model.ask(buf.tobytes(), TRANSCRIBE)
        text = getattr(answer, "text", answer)
        return text if isinstance(text, str) else None

    try:
        templates = ss.load_templates(ROOT / "data/templates/digits")
        hud = HudReader(cap.capture, templates)
        claim = sweep_and_claim(inp, cap.capture, read_panel,
                                on_note=lambda t: print(f"    {t}", flush=True))
        print(f"  claim: {claim.describe()}", flush=True)
        if not claim.ok:
            print("  not on our pad — nothing to measure")
            return 3
        before_p, before_h = hud.pollen(), hud.honey()
        print(f"  before E: pollen {before_p.describe()} | honey {before_h.describe()}")
        if before_p.ok and (before_p.value or 0) == 0:
            print("  the backpack is empty; convert cannot be observed. Gather first.")
            return 4

        inp.tap("e")
        t0 = time.monotonic()
        print(f"  pressed E. watching for {WATCH_SECONDS:.0f}s:", flush=True)
        print(f"  {'t':>5}  {'pollen':>26}  {'honey':>14}  panel")
        i = 0
        last_panel = None
        while time.monotonic() - t0 < WATCH_SECONDS:
            frame = cap.capture()
            p, h = hud.pollen(), hud.honey()
            panel_txt = ""
            if frame is not None:
                if i % 4 == 0:                       # the model is slow; every 2s
                    try:
                        last_panel = read_panel(frame)
                    except Exception:
                        last_panel = None
                cv2.imwrite(str(OUT / f"{i:03d}.jpg"), frame)
            panel_txt = (last_panel or "").strip()[:30]
            print(f"  {time.monotonic() - t0:5.1f}  {p.describe():>26}  "
                  f"{h.describe():>14}  {panel_txt!r}", flush=True)
            i += 1
            time.sleep(EVERY)
        after_p, after_h = hud.pollen(), hud.honey()
        print(f"\n  after: pollen {after_p.describe()} | honey {after_h.describe()}")
        if before_h.ok and after_h.ok:
            print(f"  honey delta: {after_h.value - before_h.value:+,}")
        print(f"  {i} frames in {OUT}")
    finally:
        try:
            inp.release_all()
        except Exception:
            pass
        ready.close()
        print("  torn down", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
