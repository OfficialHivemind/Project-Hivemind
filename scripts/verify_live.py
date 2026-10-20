#!/usr/bin/env python3
"""End-to-end live verification: does every subsystem actually work in the game?

Runs in the owner's private server and checks each layer in dependency order, so
a failure at the bottom explains the failures above it rather than producing a
wall of unrelated errors.

    1  bootstrap      compositor up, Sober launched, private server joined
    2  panic key      armed and watching real keyboards
    3  capture        frames arriving, correct size
    4  screen state   classified as IN_GAME
    5  HUD            honey and pollen read, at full confidence
    6  input          keys actually move the character
    7  calibration    ground plane fitted from a forward and a strafe burst
    8  odometry       measured displacement is consistent
    9  closed loop    walk a set distance and land within tolerance
    10 safety         no key left held after everything

Every step reports PASS/FAIL with the number behind it. The script releases all
keys and tears down whatever happens, including on an exception.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import cv2
import numpy as np

from hivemind.act import bootstrap
from hivemind.nav.calibrate import UnusableScene, calibrate
from hivemind.nav.odometry import WorldOdometer
from hivemind.nav.walker import Stuck, walk_studs
from hivemind.vision import digits
from hivemind.vision import screenstate as ss
from hivemind.vision.flow import FlowTracker

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path("/tmp/hivemind-diag/verify")
CALIB = ROOT / "data/calib/homography.yaml"

BURST_FRAMES = 16
CHARACTER_BOX = (680, 420, 520, 580)   # zero flow lives here; exclude it

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:22s} {detail}", flush=True)
    return ok


def flow_of(pairs: np.ndarray) -> float:
    """Median per-point displacement, in pixels. 0 when nothing is tracked."""
    if len(pairs) == 0:
        return 0.0
    return float(np.median(np.linalg.norm(pairs[:, 1, :] - pairs[:, 0, :], axis=1)))


def probe_directions(inp, cap) -> dict[str, float]:
    """How far does the scene actually move for each key?

    MEASURED, and the reason this exists: the bot spawns on the hive platform
    FACING THE HONEYCOMB WALL, so `w` is blocked. Per-frame median flow at
    spawn was w 0.22 px, s 4.51, a 10.88, d 9.78 -- forward blocked by 20-50x.
    Every earlier calibration attempt was fitting a forward burst that
    contained no forward motion.

    A frame-difference test does NOT catch this: `w` still changed 70% of the
    frame at spawn, because the hive's beams and sparkles animate whether or
    not the character moves. Only tracked displacement distinguishes them.
    """
    found: dict[str, float] = {}
    for key in ("w", "s", "a", "d"):
        pairs = burst_pairs(inp, cap, key, frames=6)
        found[key] = flow_of(pairs)
        opposite = {"w": "s", "s": "w", "a": "d", "d": "a"}[key]
        with inp.held(opposite):             # return roughly to the start
            time.sleep(0.35)
        time.sleep(0.4)
    return found


def burst_pairs(inp, cap, key: str, frames: int = BURST_FRAMES) -> np.ndarray:
    """Hold a key, capture continuously, return consecutive-frame point pairs.

    Consecutive frames rather than first-vs-last: a long hold moves near-field
    features hundreds of pixels and the tracker loses them. Every pair here
    spans one frame interval, so they all share the same displacement -- which
    is exactly what the calibration needs.
    """
    tracker = FlowTracker()
    collected: list[np.ndarray] = []
    cx, cy, cw, ch = CHARACTER_BOX

    captured = []
    try:
        inp.press(key)
        for _ in range(frames):
            captured.append(cap.capture())
            time.sleep(0.03)
    finally:
        inp.release(key)

    for index, frame in enumerate(captured):
        sample = tracker.update(frame)
        if sample is None or sample.pairs is None or index < 3:
            continue
        starts = sample.pairs[:, 0, :]
        on_character = ((starts[:, 0] >= cx) & (starts[:, 0] < cx + cw)
                        & (starts[:, 1] >= cy) & (starts[:, 1] < cy + ch))
        keep = sample.pairs[~on_character]
        if len(keep):
            collected.append(keep)
    time.sleep(0.6)
    return np.concatenate(collected) if collected else np.empty((0, 2, 2))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    templates = ss.load_templates(ROOT / "data/templates/digits")

    print("\n  === 1-2  bootstrap and safety ===", flush=True)
    ready = bootstrap.start(private=True)
    if not check("bootstrap", ready.ok, f"{ready.reason} in {ready.seconds:.0f}s"):
        ready.close()
        return 1
    check("panic key", bool(ready.panic and ready.panic.available),
          ready.panic.reason if ready.panic else "not armed")

    inp, cap = ready.input, ready.capture
    try:
        print("\n  === 3-5  perception ===", flush=True)
        frame = cap.capture()
        check("capture", frame is not None and frame.shape[0] == 1080,
              f"{frame.shape[1]}x{frame.shape[0]}")
        cv2.imwrite(str(OUT / "00_in_game.png"), frame[:, :, :3])

        state = ss.classify(frame, templates)
        check("screen state", state is ss.Screen.IN_GAME, state.value)

        x, y, w, h = ss.HONEY_REGION
        honey, honey_conf = digits.read(frame[y:y + h, x:x + w], templates)
        check("honey", digits.to_int(honey) is not None,
              f"{honey!r} confidence {honey_conf:.3f}")
        x, y, w, h = ss.POLLEN_REGION
        pollen, pollen_conf = digits.read(frame[y:y + h, x:x + w], templates)
        parsed = digits.parse_fraction(pollen)
        check("pollen", parsed is not None,
              f"{pollen!r} -> {parsed} confidence {pollen_conf:.3f}")

        print("\n  === 6  input moves the character ===", flush=True)
        # Tracked displacement, NOT a frame difference. At spawn a blocked `w`
        # still changes 70% of the frame, because the hive animates by itself.
        moves = probe_directions(inp, cap)
        summary = "  ".join(f"{k}={v:.1f}px" for k, v in moves.items())
        check("input", max(moves.values()) > 1.5, summary)
        blocked = [k for k, v in moves.items() if v < 1.0]
        if blocked:
            print(f"        blocked directions: {', '.join(blocked)}"
                  " (walls, or the hive)", flush=True)

        print("\n  === 7  ground-plane calibration ===", flush=True)
        # Pick the axial direction that is NOT blocked. `w` is blocked at spawn
        # by the hive wall, and backward is just as good a depth burst: it is
        # still pure translation along the view axis, so only the sign of
        # delta_u flips and a burst_distance of -1 recovers the same model.
        # (Verified against the synthetic camera, horizon to within 0.5 px.)
        axial = "w" if moves["w"] >= moves["s"] else "s"
        lateral = "d" if moves["d"] >= moves["a"] else "a"
        sign = 1.0 if axial == "w" else -1.0
        print(f"        depth burst '{axial}' ({moves[axial]:.1f} px), "
              f"lateral burst '{lateral}' ({moves[lateral]:.1f} px)", flush=True)

        plane, cal, best, why = None, None, None, ""
        for attempt in range(5):
            if attempt:
                # relocate: step along whichever lateral direction moves, then
                # back off, so each attempt sees genuinely different ground
                with inp.held(lateral if attempt % 2 else
                              ("a" if lateral == "d" else "d")):
                    time.sleep(1.6)
                time.sleep(0.5)

            depth = burst_pairs(inp, cap, axial)
            side = burst_pairs(inp, cap, lateral)
            cv2.imwrite(str(OUT / f"calib_{attempt}.png"), cap.capture()[:, :, :3])
            try:
                candidate = calibrate(depth, side, (1920, 1080),
                                      burst_distance=sign)
            except UnusableScene as exc:
                why = str(exc)
                print(f"        attempt {attempt}: {exc}", flush=True)
                continue
            except ValueError as exc:
                why = str(exc)
                print(f"        attempt {attempt}: {exc}", flush=True)
                continue
            print(f"        attempt {attempt}: horizon y={candidate.horizon_row:8.0f} "
                  f"residual={candidate.residual:.4f} inliers={candidate.inlier_fraction:.0%}"
                  f"  {'OK' if candidate.trustworthy else 'rejected'}", flush=True)
            if best is None or candidate.residual < best.residual:
                best = candidate
            if candidate.trustworthy:
                cal = candidate
                break

        check("flow pairs", best is not None, "at least one usable burst")
        if cal is not None:
            check("calibration", True,
                  f"horizon y={cal.horizon_row:.0f} residual={cal.residual:.4f} "
                  f"inliers={cal.inlier_fraction:.0%} from {cal.points} pairs")
            plane = cal.ground_plane((1920, 1080))
            check("homography", plane.rms_error < 1.0,
                  f"RMS {plane.rms_error:.4f} units")
            CALIB.parent.mkdir(parents=True, exist_ok=True)
            plane.save(CALIB)
            print(f"        saved {CALIB}", flush=True)
        else:
            detail = (f"best residual {best.residual:.3f} at "
                      f"{best.inlier_fraction:.0%} inliers — no open ground found"
                      if best else (why or "no usable burst"))
            check("calibration", False, detail)
            check("homography", False, "no trustworthy calibration")

        print("\n  === 8-9  odometry and the closed loop ===", flush=True)
        if plane is not None:
            odo = WorldOdometer(plane)
            odo.reset()
            odo.update(cap.capture())
            with inp.held("w"):
                for _ in range(10):
                    odo.update(cap.capture())
                    time.sleep(0.04)
            travelled = odo.displacement
            check("odometry", travelled > 0.05,
                  f"measured {travelled:.2f} units over ~10 frames")

            target = max(2.0, travelled * 1.5)
            try:
                odo2 = WorldOdometer(plane)
                result = walk_studs(target, "w", vin=inp,
                                    frames=cap.capture, odo=odo2, timeout=20.0)
                error = abs(result.travelled - target) / target
                check("closed loop", error < 0.35,
                      f"asked {target:.2f}, walked {result.travelled:.2f} "
                      f"({error:.1%} error, {result.ticks} ticks)")
            except Stuck as exc:
                check("closed loop", False, f"stuck: {exc}")
        else:
            check("odometry", False, "no calibration")
            check("closed loop", False, "no calibration")

        cv2.imwrite(str(OUT / "99_final.png"), cap.capture()[:, :, :3])

        print("\n  === 10  safety ===", flush=True)
        check("no key held", inp.held_keys == set(), str(inp.held_keys or "none"))
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held at teardown: {held or 'none'}", flush=True)

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n  === {passed}/{len(results)} checks passed ===")
    for name, ok, detail in results:
        if not ok:
            print(f"      FAILED: {name} — {detail}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
