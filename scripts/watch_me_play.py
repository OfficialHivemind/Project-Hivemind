#!/usr/bin/env python3
"""Learn the map by watching the owner play. Sends nothing.

    ./.venv/bin/python scripts/watch_me_play.py --minutes 10

It brings the game up in the nested window and joins the private server, then
STOPS TOUCHING IT. Click into that window and play normally; every couple of
seconds it takes a look, works out whether this is a place it has seen before,
and records which places lead to which.

The owner's idea, and the reason it is worth having: a mode that learns how
they play -- not copying their moves exactly, but mapping them out as nodes. The bot's own routes are blind timed walks
that fail whenever the world moves. A path a person actually walked is a path
that worked.

IT CANNOT PRESS ANYTHING. `brain/observe.py` has no keyboard and no pointer in
it, and a test asserts none is ever added. The only input object created here
is the one bootstrap needs to reach the server browser, and it is released
before the watching starts.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                              # noqa: E402
from hivemind.act.hive import TRANSCRIBE                        # noqa: E402
from hivemind.brain.farm import HudReader                       # noqa: E402
from hivemind.brain.observe import PlayObserver                 # noqa: E402
from hivemind.brain.vlm import VisionModel                      # noqa: E402
from hivemind.vision import banner                              # noqa: E402
from hivemind.vision import screenstate as ss                   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "var" / "maps"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--name", default="session")
    ap.add_argument("--fullscreen", action="store_true",
                    help="stay fullscreen; the pointer will be grabbed")
    ap.add_argument("--no-labels", action="store_true",
                    help="skip asking the vision model to name places")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    cap = ready.capture

    # Release the keyboard before handing the game over. Nothing below needs
    # it, and the person playing should not be sharing input with anything.
    try:
        ready.input.release_all()
    except Exception:
        pass

    # AND DROP OUT OF FULLSCREEN, so the game does not grab the pointer.
    # Fullscreen is what traps the cursor in a nested compositor; the join
    # above needed it because every coordinate in the server browser is
    # measured against a full 1920x1080 output, and nothing after this point
    # does. See Session.leave_fullscreen.
    if not args.fullscreen:
        try:
            ready.session.leave_fullscreen()
            time.sleep(1.0)
            print("  dropped out of fullscreen so your mouse stays free",
                  flush=True)
        except Exception as exc:
            print(f"  could not leave fullscreen ({exc}) — if your cursor "
                  f"gets stuck, press SUPER+M to close the window", flush=True)

    model = VisionModel()

    def read_panel(frame):
        if args.no_labels:
            return None
        found = banner.find(frame)
        if found is None or not model.available():
            return None
        ok, buf = cv2.imencode(".png", found.crop(frame)[:, :, :3])
        if not ok:
            return None
        answer = model.ask(buf.tobytes(), TRANSCRIBE)
        text = getattr(answer, "text", answer)
        return text if isinstance(text, str) else None

    templates = ss.load_templates(ROOT / "data/templates/digits")
    hud = HudReader(cap.capture, templates)
    # THE NOTES. The owner asked for these directly: notes on everything
    # they do -- not an exact copy, in case they make a mistake, but a map
    # it can learn from. They also said they would be doing quests, so the question asks
    # about dialogue and NPCs specifically -- a quest board or a bear
    # conversation is exactly the kind of thing the bot has no idea exists.
    NOTE = (
        "Describe what the player is doing in this Bee Swarm Simulator "
        "screenshot, in one sentence. Mention where they are, and if a "
        "dialogue box, quest, NPC or shop menu is open, say what it is and "
        "quote its title."
    )

    def take_note(frame):
        if args.no_labels or not model.available():
            return None
        small = cv2.resize(frame[:, :, :3], (1280, 720),
                           interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", small)
        if not ok:
            return None
        answer = model.ask(buf.tobytes(), NOTE)
        text = getattr(answer, "text", answer)
        return text if isinstance(text, str) else None

    observer = PlayObserver(cap.capture, read_hud=hud.pollen,
                            read_panel=read_panel, take_note=take_note)

    print("\n" + "=" * 62, flush=True)
    print("  THE GAME IS YOURS. Click into the window and play normally.",
          flush=True)
    print(f"  Watching for {args.minutes:.0f} minutes and mapping where you go.",
          flush=True)
    print("  Nothing will touch your keyboard or mouse.", flush=True)
    print("  If the cursor ever gets stuck: SUPER+M closes the window.",
          flush=True)
    print("=" * 62 + "\n", flush=True)

    started = time.monotonic()
    try:
        def announce(place):
            where = f" [{place.labels[0]}]" if place.labels else ""
            print(f"    {time.monotonic() - started:5.0f}s  "
                  f"{place.name}{where} "
                  f"({len(observer.places)} places so far)", flush=True)
            if place.notes:
                print(f"           note: {place.notes[-1]}", flush=True)

        observer.watch(args.minutes * 60.0, on_place=announce)
    except KeyboardInterrupt:
        print("\n  stopped early", flush=True)
    finally:
        stamp = time.strftime("%H%M%S")
        path = observer.save(OUT / f"{args.name}-{stamp}.json")
        print(f"\n  {observer.describe()}", flush=True)
        print(f"  map written to {path}", flush=True)
        try:
            model.unload()
        except Exception:
            pass
        ready.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
