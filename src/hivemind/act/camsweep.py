"""THE CAMERA SWEEP FOR BUBBLES, between gather passes (gather.rotate_camera).

WHAT OTHER MACROS DO AND WHY. A popular macro's default blue profile ships "Oscillate camera
after return": once the character is back at the sprinkler it sweeps the
camera back and forth, because "your dipper will constantly be sending out
waves or petals that pop bubbles where your player is facing"
(its public docs, read 2026-10-14).

WHAT THE WIKI SAYS POPS A BUBBLE (bee-swarm-simulator.fandom.com/wiki/Bubble,
wikitext read 2026-10-14): a player touching it, "petal shurikens" (Petal
Wand), coconuts, tornadoes, Star Saw, Fuzz Bombs, the Dark Scythe's trail,
Puppy Bee's Fetch and "the Tide Popper's waves". Bubbles last 4 s and each
pops 29 flowers' pollen. So the waves and petals that macro means are the
Tide Popper's and the Petal Wand's -- the facing-dependent poppers.

AND THIS ACCOUNT'S TOOL IS NEITHER. var/purchases.json (2026-10-14) reads the
Porcelain Dipper as "Equipped": wiki/Porcelain_Dipper, pattern "Surround", 49
patches around the player, and it is on no list of bubble poppers. Its pops
are the character walking through them, which a camera turn standing still
does not do. So the sweep ships OFF ("never"): it is built and counted for
the day a Tide Popper or Petal Wand is equipped, and "every other trip (A/B)"
measures it then. GUESS, unverified in game: that a camera turn while
standing turns the character at all -- Roblox's default camera does not
without shift-lock. The first live A/B answers both.

THE HEADING IS SACRED. A walk home undoes its field's walk out from the
counted heading (run_farm "the camera as its own route out", world/bearings,
8 taps = 360 degrees), and WASD is camera-relative, so the pattern itself
needs the heading it began with. The sweep turns ONE TAP AT A TIME through
the caller's counted `turn`, so the taps it owes are exact whatever stops
it, and gives every one back in a `finally`. Net taps: always 0.
"""
from __future__ import annotations

import time

# taps each side of the start heading; 1 tap = 45 degrees (8 a full turn).
# ponytail: Another macro calls its range "a Tuning setting" and publishes no
# default; 1 each way is the smallest sweep there is. Widen it if the A/B
# shows the sweep pays and a wider one might pay more.
SWEEP_TAPS = 1
# held at each end, so a swinging tool gets a swing or two that way (the
# Porcelain Dipper swings every 0.7 s, wiki; the Tide Popper's wave is every
# 3rd swing). ponytail: unmeasured, tune with the A/B.
DWELL_S = 0.8

NEVER, ALWAYS, AB = "never", "every pass", "every other trip (A/B)"
MODES = (NEVER, ALWAYS, AB)


def mode_of(value) -> str:
    """The setting's value as one of MODES; anything else -- an old file's
    `true` from when this key was a dead bool, a typo -- is NEVER."""
    return value if value in MODES else NEVER


def wanted(value, trip: int) -> bool:
    """Is the sweep on for trip number `trip` under setting `value`? The A/B
    arm is the trip's parity (odd trips sweep), not the hour's: the even
    hours already carry HASTE_GAIN and HOME_ALIGN's arms (vision/buffs,
    act/home_align), and an hour split here would share their confounds."""
    mode = mode_of(value)
    return mode == ALWAYS or (mode == AB and int(trip) % 2 == 1)


def plan(taps: int = SWEEP_TAPS) -> list[int]:
    """The sweep as signed single taps (+ right, - left): out left, across
    to the right, back to the middle. Sums to 0."""
    return [-1] * taps + [1] * (2 * taps) + [-1] * taps


def sweep(turn, *, at_anchor: bool, stopped=lambda: False,
          taps: int = SWEEP_TAPS, dwell: float = DWELL_S, sleep=time.sleep) -> int:
    """One sweep through `turn(taps)` (run_farm's counted `turn_camera`).
    Returns the taps turned out (0 = no sweep). NEVER OFF THE ANCHOR: the
    caller says whether the character stands at the gather's anchor between
    passes; anywhere else -- a walk, a chase -- this turns nothing. Whatever
    `stopped` or an exception cuts short, the heading is given back."""
    if not at_anchor or taps <= 0:
        return 0
    net = turned = 0
    try:
        steps = plan(taps)
        for i, step in enumerate(steps):
            if stopped():
                break
            turn(step)
            net += step
            turned += 1
            ends = i + 1 < len(steps) and steps[i + 1] != step
            if ends and net:            # at an end of the arc, not the middle
                sleep(dwell)
    finally:
        if net:
            turn(-net)
    return turned
