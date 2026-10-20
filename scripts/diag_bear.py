#!/usr/bin/env python3
"""What does a bear's dialogue actually look like?

THE OWNER ASKED FOR IT: "i wan it to start completing my quests and learning
how to speak to the bear and turn them in". Handing a quest in needs three
things the bot can already do -- walk to the bear, press the interact key,
read the screen -- and one it cannot: know what the dialogue looks like, where
its buttons are, and what closes it.

Nobody has ever photographed it. docs/GAPS.md #6 has said "it cannot talk to a
bear" since the first review, and the one time a bear dialogue appeared it was
an accident: the convert step pressed E where it believed the hive was and
"opened a Polar Bear quest dialogue" (see scripts/diag_hive_panel.py). No
frames were kept.

So this goes and looks, and does nothing else. It presses E, which is the same
interact key the hive claim already uses and understands, photographs whatever
appears, and walks BACKWARDS to leave. It never presses Enter, never clicks,
and never accepts or declines anything -- the standing rule is that a Roblox
menu carries Log Out and Leave as activatable tiles, so nothing is pressed
blind. Building the hand-in from a guess is exactly what this avoids.

    ./scripts/diag_bear.py [black_bear|brown_bear|riley_bee|...]
"""
from __future__ import annotations

import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                              # noqa: E402
from hivemind.act.hive import TRANSCRIBE, sweep_and_claim       # noqa: E402
from hivemind.act.routes import RouteRunner, walkspeed_from     # noqa: E402
from hivemind.brain.vlm import VisionModel                      # noqa: E402
from hivemind.nav.router import Router                          # noqa: E402
from hivemind.world.settings import Settings                    # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "var" / "bear"
ASK = ("Describe this Roblox Bee Swarm Simulator screen. Is a dialogue or "
       "speech box open? If so, quote every word of it exactly, and list any "
       "buttons and where they are on the screen. If no dialogue is open, say "
       "so and describe what is in front of the character.")


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "black_bear"
    OUT.mkdir(parents=True, exist_ok=True)
    model = VisionModel()
    settings = Settings()
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    shots = 0

    def shot(tag: str, describe: bool = False) -> None:
        nonlocal shots
        frame = cap.capture()
        if frame is None:
            print(f"  {tag}: no frame")
            return
        path = OUT / f"{shots:03d}-{tag}.png"
        cv2.imwrite(str(path), frame[:, :, :3])
        shots += 1
        print(f"  saved {path.name}", flush=True)
        if describe and model.available():
            try:
                said = model.ask(frame, ASK)
                print(f"    model: {said}", flush=True)
                (OUT / f"{shots - 1:03d}-{tag}.txt").write_text(said or "")
            except Exception as exc:
                print(f"    model failed: {exc}")

    try:
        # Claim a hive first, exactly as a farming run does, so the walk
        # starts from the same place the recorded route was written for.
        claimed = sweep_and_claim(
            inp, cap.capture,
            lambda f: model.ask(f, TRANSCRIBE) if model.available() else "",
            on_note=lambda t: print(f"    {t}", flush=True))
        print(f"  hive: {getattr(claimed, 'describe', lambda: claimed)()}",
              flush=True)

        router = Router()
        runner = RouteRunner(inp, router, walkspeed=walkspeed_from(settings))
        name = f"natro_out_{which}"
        if not any(e.name == name for e in router.edges):
            print(f"  no route called {name}")
            return 2
        print(f"  walking {name}", flush=True)
        result = runner.run(name)
        print(f"  {result.describe()}", flush=True)

        shot("arrived", describe=True)
        print("  pressing E (the interact key — nothing else)", flush=True)
        inp.tap("e")
        for wait in (0.4, 1.0, 2.0):
            time.sleep(wait)
            shot(f"after-e-{wait}", describe=(wait == 2.0))

        # LEAVE BY WALKING, NOT BY PRESSING. A Roblox menu carries Log Out and
        # Leave as activatable tiles; walking backwards cannot press anything.
        print("  walking backwards to leave", flush=True)
        with inp.held("s"):
            time.sleep(2.0)
        shot("left", describe=True)
    finally:
        inp.release_all()
        ready.close()
    print(f"\n  {shots} frames in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
