#!/usr/bin/env python3
"""What is the optical flow actually tracking in game?

The ground-plane calibration fails live (residual 4.8-10.6, inliers 16-41%)
while being exact against the synthetic camera. Simulation has since RULED OUT
camera yaw: 4 degrees of swing per burst still fits at residual 0.09 and 94-100%
inliers, nowhere near the live numbers.

So this stops hypothesising and looks. It walks forward, tracks points, and
reports what the flow field is made of:

  * median dx across the frame      -- a uniform horizontal shift means yaw
  * delta_u spread at the best-fit horizon, and its SHAPE -- bimodal means two
    surfaces, a long tail means independently moving objects
  * where the inliers and outliers actually are, drawn on the frame

A Bee Swarm field contains flowers standing above the ground, the player's own
bees orbiting the character, tokens and particles. None of them are on the
ground plane, and the tracker has no way to know that. This measures how much
of the frame they account for.
"""
import pathlib
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.act import bootstrap                              # noqa: E402
from hivemind.nav.calibrate import fit_horizon, fit_horizon_robust  # noqa: E402
from hivemind.vision.flow import FlowTracker                    # noqa: E402

OUT = pathlib.Path("/tmp/hivemind-diag/flowfield")
CHARACTER_BOX = (680, 420, 520, 580)
BURST_FRAMES = 14


def collect(inp, cap, key):
    """Hold a key; return (pairs, last_frame)."""
    tracker = FlowTracker()
    cx, cy, cw, ch = CHARACTER_BOX
    frames = []
    inp.press(key)
    try:
        for _ in range(BURST_FRAMES):
            frames.append(cap.capture())
            time.sleep(0.03)
    finally:
        inp.release(key)

    collected = []
    for index, frame in enumerate(frames):
        sample = tracker.update(frame)
        if sample is None or sample.pairs is None or index < 3:
            continue
        starts = sample.pairs[:, 0, :]
        on_character = ((starts[:, 0] >= cx) & (starts[:, 0] < cx + cw)
                        & (starts[:, 1] >= cy) & (starts[:, 1] < cy + ch))
        keep = sample.pairs[~on_character]
        if len(keep):
            collected.append(keep)
    time.sleep(0.5)
    pairs = np.concatenate(collected) if collected else np.empty((0, 2, 2))
    return pairs, frames[-1]


def describe(pairs, frame, label):
    print(f"\n  === {label}: {len(pairs)} tracked pairs ===", flush=True)
    if len(pairs) < 40:
        print("      too few to analyse", flush=True)
        return

    dx = pairs[:, 1, 0] - pairs[:, 0, 0]
    dy = pairs[:, 1, 1] - pairs[:, 0, 1]

    # 1. YAW signature: a uniform horizontal shift across the whole frame
    print(f"      dx: median {np.median(dx):+7.2f}  mean {np.mean(dx):+7.2f}"
          f"  IQR {np.percentile(dx, 75) - np.percentile(dx, 25):6.2f}", flush=True)
    print(f"      dy: median {np.median(dy):+7.2f}  mean {np.mean(dy):+7.2f}"
          f"  IQR {np.percentile(dy, 75) - np.percentile(dy, 25):6.2f}", flush=True)

    # 2. does dy at a given row depend on x? pure translation says no
    rows = pairs[:, 0, 1]
    lo, hi = np.percentile(rows, [40, 60])
    band = (rows >= lo) & (rows <= hi)
    if band.sum() > 10:
        corr = np.corrcoef(pairs[band, 0, 0], dy[band])[0, 1]
        print(f"      within rows {lo:.0f}-{hi:.0f} ({band.sum()} pts), "
              f"corr(x, dy) = {corr:+.3f}   (yaw would make this large)", flush=True)

    # 3. the fit, and the SHAPE of what it could not fit
    horizon, residual = fit_horizon(pairs)
    rh, rres, rinl = fit_horizon_robust(pairs)
    print(f"      plain fit : horizon {horizon:8.0f}  residual {residual:.4f}",
          flush=True)
    print(f"      robust fit: horizon {rh:8.0f}  residual {rres:.4f}  "
          f"inliers {rinl:.0%}", flush=True)

    g0 = pairs[:, 0, 1] - rh
    g1 = pairs[:, 1, 1] - rh
    if np.all(g0 > 1e-6) and np.all(g1 > 1e-6):
        delta = 1.0 / g1 - 1.0 / g0
        med = np.median(delta)
        mad = np.median(np.abs(delta - med))
        inlier = np.abs(delta - med) <= 3.0 * mad
        print(f"      delta_u   : median {med:.3e}  MAD {mad:.3e}  "
              f"within 3 MAD: {inlier.mean():.0%}", flush=True)
        for pct in (1, 5, 25, 50, 75, 95, 99):
            print(f"         p{pct:<3d} {np.percentile(delta, pct):+.4e}", flush=True)

        # 4. WHERE are the outliers? draw them
        canvas = frame[:, :, :3].copy()
        for (x0, y0), keep in zip(pairs[:, 0, :], inlier):
            colour = (90, 220, 90) if keep else (60, 60, 240)
            cv2.circle(canvas, (int(x0), int(y0)), 3, colour, -1)
        cv2.line(canvas, (0, int(rh)), (canvas.shape[1], int(rh)), (0, 220, 220), 1)
        cv2.putText(canvas, f"{label}: green=on-plane {inlier.mean():.0%}, red=off-plane",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        path = OUT / f"{label}.png"
        cv2.imwrite(str(path), canvas)
        print(f"      wrote {path}", flush=True)

        # 5. are the outliers CLUSTERED (objects) or scattered (noise)?
        out_rows = pairs[~inlier, 0, 1]
        if len(out_rows) > 5:
            print(f"      outlier rows: p10 {np.percentile(out_rows, 10):.0f}  "
                  f"median {np.median(out_rows):.0f}  "
                  f"p90 {np.percentile(out_rows, 90):.0f}"
                  f"   (frame is {frame.shape[0]} tall)", flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ready = bootstrap.start(private=True)
    if not ready.ok:
        print(f"  bootstrap failed: {ready.reason}")
        ready.close()
        return 1
    inp, cap = ready.input, ready.capture
    try:
        cv2.imwrite(str(OUT / "00_scene.png"), cap.capture()[:, :, :3])

        # a STATIONARY burst first: anything moving while we stand still is a
        # bee, a token or a particle, and is pure contamination
        tracker = FlowTracker()
        frames = [cap.capture() for _ in range(10) if not time.sleep(0.05)]
        still = []
        for index, frame in enumerate(frames):
            s = tracker.update(frame)
            if s is not None and s.pairs is not None and index >= 3:
                still.append(s.pairs)
        if still:
            describe(np.concatenate(still), frames[-1], "01_standing_still")

        forward, frame = collect(inp, cap, "w")
        describe(forward, frame, "02_walking_forward")

        strafe, frame = collect(inp, cap, "d")
        describe(strafe, frame, "03_strafing_right")
    finally:
        held = getattr(ready.input, "held_keys", set())
        ready.close()
        print(f"\n  torn down; keys held: {held or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
