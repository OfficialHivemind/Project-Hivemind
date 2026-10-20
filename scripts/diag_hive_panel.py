#!/usr/bin/env python3
"""What does the notification panel say while standing at your OWN hive?

The claim prompt is known -- "Claim Hive" -- because a live run read it. The
steady-state prompt at a hive the account already owns has never been
photographed, and that is the text the convert step needs before it is willing
to press E. Pressing it unseen opened a Polar Bear quest dialogue.

Claims a hive, then stands there reading the panel, then steps off and back on
so both the present and absent cases are recorded.
"""
from __future__ import annotations

import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                              # noqa: E402
from hivemind.act.hive import TRANSCRIBE, sweep_and_claim       # noqa: E402
from hivemind.brain.vlm import VisionModel                      # noqa: E402
from hivemind.vision import banner                              # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "var" / "hivepanel"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    model = VisionModel()
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture

    def read(tag: str) -> str | None:
        frame = cap.capture()
        cv2.imwrite(str(OUT / f"{tag}.png"), frame[:, :, :3])
        panel = banner.find(frame)
        if panel is None:
            return None
        ok, buf = cv2.imencode(".png", panel.crop(frame)[:, :, :3])
        if not ok or not model.available():
            return None
        answer = model.ask(buf.tobytes(), TRANSCRIBE)
        text = getattr(answer, "text", answer)
        return text if isinstance(text, str) else None

    try:
        print("\n  claiming...", flush=True)
        result = sweep_and_claim(inp, cap.capture, read,
                                 on_note=lambda t: print(f"    {t}", flush=True))
        print(f"  -> {result.describe()}\n", flush=True)
        if not result.ok:
            return 2

        print("  standing on the hive, reading the panel:", flush=True)
        for i in range(6):
            time.sleep(3.0)
            text = read(f"stand_{i}")
            print(f"    +{i * 3:2d}s  {text!r}", flush=True)

        print("\n  stepping OFF the hive:", flush=True)
        with inp.held("s"):
            time.sleep(2.0)
        time.sleep(1.0)
        print(f"    off  {read('off')!r}", flush=True)

        print("\n  stepping back ON:", flush=True)
        with inp.held("w"):
            time.sleep(2.0)
        time.sleep(1.0)
        for i in range(3):
            print(f"    on_{i}  {read(f'on_{i}')!r}", flush=True)
            time.sleep(2.0)
        return 0
    finally:
        try:
            model.unload()
        except Exception:
            pass
        ready.close()
        print(f"\n  frames in {OUT}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
