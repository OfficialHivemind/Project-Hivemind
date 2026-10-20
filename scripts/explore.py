#!/usr/bin/env python3
"""Go out, look around, and come back knowing where things are.

    ./.venv/bin/python scripts/explore.py --steps 60

THIS IS THE THING THAT WAS MISSING. The owner put it plainly: the bot never
seemed to know where it was, even where it should know the map, and seemed to
have no goals or understanding of the game. It never did have a clue.
Recorded routes walk blind for a measured number of seconds; the probe search
wanders until a number moves; the knowledge base says what EXISTS but nothing
said where the bot was standing.

So it explores. It walks, recognises places by their colour signature, stands
still long enough to find out whether pollen rises, and writes the map down.
A place where pollen rose is a field -- established by this bot, on this
account, in this server, rather than transpiled from somebody else's
recording.

The map persists in `var/world_map.json` and is loaded on the next run, so the
second session starts knowing what the first one learned.

SAFETY. It presses movement and camera keys only -- w/a/s/d, space, comma,
period. Never `e`, `escape`, `enter` or `r`, so no amount of wandering can
open a menu, leave the server, or talk to a bear. It never resets, because a
reset is a death and a death empties the backpack.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                              # noqa: E402
from hivemind.act.clicker import Clicker                        # noqa: E402
from hivemind.act.hive import TRANSCRIBE, sweep_and_claim       # noqa: E402
from hivemind.brain.explore import Explorer                     # noqa: E402
from hivemind.brain.farm import HudReader                       # noqa: E402
from hivemind.brain.vlm import VisionModel                      # noqa: E402
from hivemind.ipc.bus import EventServer                        # noqa: E402
from hivemind.platform.current import memory                            # noqa: E402
from hivemind.telemetry.events import Thought                   # noqa: E402
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
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--no-claim", action="store_true")
    args = ap.parse_args()

    safe, note = memory.check("an exploration run")
    print(f"  memory: {note}", flush=True)
    if not safe:
        return 2

    model = VisionModel()
    model.unload()
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}", flush=True)
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture

    server = EventServer().start()
    print(f"  GUI socket: {server.path}", flush=True)

    def narrate(event) -> None:
        if hasattr(event, "to_json"):
            server.send(event)
        text = getattr(event, "text", "")
        if text:
            print(f"    {time.strftime('%H:%M:%S')}  {text}", flush=True)

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

    clicker = live = None
    try:
        if not args.no_claim:
            print("\n  claiming a hive (no bees without one)...", flush=True)
            claimed = sweep_and_claim(inp, cap.capture, read_panel,
                                      on_note=lambda t: print(f"    {t}",
                                                              flush=True))
            print(f"  -> {claimed.describe()}", flush=True)
            if not claimed.ok:
                return 3

        templates = ss.load_templates(ROOT / "data/templates/digits")
        hud = HudReader(cap.capture, templates)

        # Swing the tool while wandering: it is worth roughly 2.8x the bees
        # alone, and it makes "does pollen rise here" answerable faster.
        clicker = Clicker(inp, can_click=lambda: ss.hud_present(cap.capture()))
        clicker.start()
        live = LiveView(cap.capture, narrate, detect=notice,
                        screen_of=lambda f: ss.classify(f).value).start()

        explorer = Explorer(inp, cap.capture, hud.pollen,
                            describe=describe, emit=narrate)
        remembered = explorer.load(MAP)
        if remembered:
            print(f"  remembered {remembered} places from a previous run",
                  flush=True)

        print(f"\n  === exploring for {args.steps} steps ===", flush=True)
        explorer.explore(steps=args.steps)

        explorer.save(MAP)
        print("\n  === what it learned ===", flush=True)
        print(f"  {explorer.describe()}", flush=True)
        for spot in explorer.spots:
            print(f"    {spot.describe()}", flush=True)
        print(f"\n  map saved to {MAP}", flush=True)
        narrate(Thought(topic="explore", text=explorer.describe()))
        return 0
    finally:
        for thing, label in ((clicker, "clicker"), (live, "live view")):
            try:
                if thing is not None:
                    thing.stop()
                    print(f"  {label}: {thing.describe()}", flush=True)
            except Exception:
                pass
        try:
            model.unload()
        except Exception:
            pass
        server.stop()
        held = getattr(inp, "held_keys", set())
        ready.close()
        print(f"  torn down; keys held: {held or 'none'}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
