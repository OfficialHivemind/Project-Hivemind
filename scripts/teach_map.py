#!/usr/bin/env python3
"""You walk. It maps. Same map the bot uses.

    ./.venv/bin/python scripts/teach_map.py --minutes 20

WHY THIS IS THE BEST USE OF TWENTY MINUTES. The bot's own exploration wanders
at random two seconds at a time, hoping to bump into a field -- MEASURED, it
found two places in four minutes. The owner knows where the fields are. His
walk maps more of the world, more accurately, in a fraction of the time.

It writes to `var/world_map.json`, which is the SAME file the bot's own
exploration reads and writes, so a walk of his and a wander of the bot's
accumulate into one map rather than two competing ones.

WHAT IT RECORDS. For every place: what it looks like (a colour signature that
survives the camera moving), whether pollen rose while standing there -- which
is what makes a place a FIELD rather than scenery -- and one sentence from the
vision model saying where it thinks this is.

IT PRESSES NOTHING. The explorer's `watch` loop has no keyboard in it, and a
test asserts nothing reaches the keyboard while a person is driving. The game
also drops out of fullscreen before handing over, because fullscreen is what
makes it grab the pointer.

WALKING IS ALL YOU NEED. W/A/S/D works normally. The pointer lock only affects
the mouse, so menus and camera-drag may still misbehave -- that is a known
unsolved problem and it does not stop the mapping.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                              # noqa: E402
from hivemind.act.hive import TRANSCRIBE, sweep_and_claim       # noqa: E402
from hivemind.brain.explore import Explorer                     # noqa: E402
from hivemind.brain.farm import HudReader                       # noqa: E402
from hivemind.brain.vlm import VisionModel                      # noqa: E402
from hivemind.brain.controls import Controls                    # noqa: E402
from hivemind.ipc.bus import EventServer                        # noqa: E402
from hivemind.telemetry.liveview import LiveView                # noqa: E402
from hivemind.vision import banner                              # noqa: E402
from hivemind.vision import screenstate as ss                   # noqa: E402
from hivemind.vision.notice import notice                       # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAP = ROOT / "var" / "world_map.json"

WHERE = ("In one short sentence: where is the player standing in this Bee "
         "Swarm Simulator screenshot, and are there flowers on the ground "
         "around them?")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--claim", action="store_true",
                    help="claim a hive first (do this if pollen should rise)")
    args = ap.parse_args()

    model = VisionModel()
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}", flush=True)
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture

    # THE LIVE VIEW TAKES THE CONTROLS (RL1b step 3): headless there is no
    # game window to walk in, so the owner walks through the GUI's picture.
    # His mouse and keys come back as GameInput and go in through `inp`;
    # nothing of this script's is pressed.
    controls = Controls(vin=inp)
    server = EventServer(on_message=controls.handle).start()
    controls.emit = server.send

    def narrate(event) -> None:
        if hasattr(event, "to_json"):
            server.send(event)

    def read_panel(frame):
        found = banner.find(frame)
        if found is None or not model.available():
            return None
        ok, buf = cv2.imencode(".png", found.crop(frame)[:, :, :3])
        if not ok:
            return None
        answer = model.ask(buf.tobytes(), TRANSCRIBE)
        text = getattr(answer, "text", answer)
        return text if isinstance(text, str) else None

    def describe(frame):
        if not model.available():
            return None
        small = cv2.resize(frame[:, :, :3], (1280, 720),
                           interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", small)
        if not ok:
            return None
        answer = model.ask(buf.tobytes(), WHERE)
        text = getattr(answer, "text", answer)
        return text if isinstance(text, str) else None

    live = None
    try:
        if args.claim:
            print("\n  claiming a hive so pollen can actually rise...",
                  flush=True)
            claimed = sweep_and_claim(inp, cap.capture, read_panel,
                                      on_note=lambda t: print(f"    {t}",
                                                              flush=True))
            print(f"  -> {claimed.describe()}", flush=True)

        # Hand the controls over properly: release every key, and leave
        # fullscreen so the game is less likely to grab the pointer.
        try:
            inp.release_all()
            ready.session.leave_fullscreen()
            time.sleep(1.0)
        except Exception:
            pass
        controls.owner_drives()

        templates = ss.load_templates(ROOT / "data/templates/digits")
        hud = HudReader(cap.capture, templates)
        live = LiveView(cap.capture, narrate, detect=notice,
                        screen_of=lambda f: ss.classify(f).value).start()

        explorer = Explorer(inp, cap.capture, hud.pollen,
                            describe=describe, emit=narrate)
        remembered = explorer.load(MAP)

        print("\n" + "=" * 64, flush=True)
        print("  WALK. It is watching and will not touch your keyboard.",
              flush=True)
        print(f"  Mapping for {args.minutes:.0f} minutes"
              + (f", already knows {remembered} places." if remembered
                 else ", starting from nothing."), flush=True)
        print("  Walk to the fields you actually use — that is what it needs.",
              flush=True)
        print("=" * 64 + "\n", flush=True)

        started = time.monotonic()

        def announce(spot):
            print(f"    {time.monotonic() - started:5.0f}s  {spot.describe()}",
                  flush=True)

        explorer.watch(args.minutes * 60.0, on_place=announce)
    except KeyboardInterrupt:
        print("\n  stopped early", flush=True)
    finally:
        try:
            explorer.save(MAP)
            print(f"\n  {explorer.describe()}", flush=True)
            for spot in explorer.spots:
                print(f"    {spot.describe()}", flush=True)
            print(f"\n  map saved to {MAP}", flush=True)
        except Exception as exc:
            print(f"  could not save the map: {exc}", flush=True)
        try:
            if live is not None:
                live.stop()
            model.unload()
        except Exception:
            pass
        server.stop()
        ready.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
