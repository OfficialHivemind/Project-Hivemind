"""What OpenCV's thread pool costs the bot: the overlay pass on saved frames.

Offline only (it never touches the game). Runs the live view's overlay pass
-- `screenstate.classify`, `tokens.detect`, `notice` -- the way run_farm's
overlay thread does, on saved 1920x1080 incident frames, once per OpenCV
thread count, each in a fresh process so the pool is the only difference.
Prints wall ms and CPU ms (all threads) per pass, and checks every thread
count gives the SAME answers as the first, so a cut is decision-neutral.

    python tools/bench_cvthreads.py [frames_glob] [--threads 16,4,2,1]
        [--pace-ms 216]

`--pace-ms` sleeps between passes like the live overlay clock does, so the
pool's spinning after each call (what `top -H` showed live) is counted too.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time

DEFAULT_GLOB = os.path.expanduser("~/Hivemind/var/incidents/*/0[0-4]0_*.jpg")


def child(paths, threads: int, pace_ms: float) -> dict:
    import cv2
    cv2.setNumThreads(threads)
    from hivemind.vision import screenstate as ss
    from hivemind.vision import tokens
    from hivemind.vision.notice import notice
    frames = [cv2.imread(p) for p in paths]
    frames = [f for f in frames if f is not None and f.shape[:2] == (1080, 1920)]

    def one(frame, tick):
        state = ss.classify(frame)
        in_game = state is ss.Screen.IN_GAME
        seen = tokens.detect(frame, marks=[]) if in_game else None
        boxes = notice(frame, world=in_game, sightings=seen, bars=tick % 2 == 0)
        return [state.value, sorted((b.get("kind"), b.get("x"), b.get("y"))
                                    for b in boxes)]

    one(frames[0], 0)                      # warm-up: imports, template loads
    answers = []
    cpu0, wall0 = time.process_time(), time.monotonic()
    busy = 0.0
    for tick, frame in enumerate(frames):
        began = time.monotonic()
        answers.append(one(frame, tick))
        busy += time.monotonic() - began
        if pace_ms:
            time.sleep(pace_ms / 1000.0)
    cpu = time.process_time() - cpu0
    wall = time.monotonic() - wall0
    n = len(frames)
    return {"threads": threads, "frames": n, "pass_ms": 1000 * busy / n,
            "cpu_ms": 1000 * cpu / n, "cores": cpu / wall,
            "answers": answers}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("glob", nargs="?", default=DEFAULT_GLOB)
    parser.add_argument("--threads", default="16,4,2,1")
    parser.add_argument("--pace-ms", type=float, default=216.0)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--child", type=int, default=None)
    args = parser.parse_args()
    if args.child is not None:
        paths = json.loads(sys.stdin.read())
        print(json.dumps(child(paths, args.child, args.pace_ms)))
        return
    # THE LIST IS FIXED ONCE, here: the live bot keeps saving new incidents,
    # so a glob per child would compare different frames.
    paths = sorted(glob.glob(args.glob))[-args.limit:]
    first = None
    for threads in [int(t) for t in args.threads.split(",")]:
        out = subprocess.run([sys.executable, __file__,
                              "--child", str(threads),
                              "--pace-ms", str(args.pace_ms)],
                             input=json.dumps(paths),
                             capture_output=True, text=True, check=True)
        row = json.loads(out.stdout.strip().splitlines()[-1])
        first = first or row["answers"]
        differ = [i for i, (a, b) in enumerate(zip(first, row["answers"]))
                  if a != b]
        print(f"cv2 threads {row['threads']:>2}: {row['frames']} frames, "
              f"pass {row['pass_ms']:.1f} ms wall, {row['cpu_ms']:.1f} ms CPU, "
              f"{row['cores']:.2f} cores at {args.pace_ms:g} ms pace, "
              f"answers {f'DIFFERENT on {len(differ)}' if differ else 'SAME'}")
        for i in differ[:3]:
            print(f"   frame {i}: {first[i]}\n      vs {row['answers'][i]}")


if __name__ == "__main__":
    main()
