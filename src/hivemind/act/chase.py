"""Walking to a token that has been seen, and coming straight back.

THE OWNER ASKED FOR IT: "i really want token vission to". Seeing one is
`vision/tokens.py`; this is the half that does something about it, and it is
what finally puts something behind `gather.chase_tokens` and
`gather.token_radius`, dead switches since the first day.

IT STEERS BY THE SCREEN, NOT BY A CALIBRATION, and that was forced by a
measurement. The obvious way to walk to a token is to turn its screen position
into a distance through the ground-plane homography in `data/calib` and hold
the keys for that long. MEASURED 2026-09-21, that homography is not usable:

    screen (960, 900) -> 889 studs forward        a point just in front of the feet
    screen (960, 700) -> 4,183 studs forward
    screen (960, 400) -> 10,330 studs forward

A Bee Swarm field is tens of studs across. The file records
`rms_error_studs: 0.0003`, which is true and misleading: it is a perfect fit to
its own correspondences, and those correspondences were wrong. The sideways
axis is plausible (about +/-39 studs across the screen) and the forward axis is
out by two orders of magnitude. See docs/GAPS.md.

So this does the thing that needs no calibration at all: it takes a short step
towards the token, LOOKS AGAIN, and repeats. That is a closed loop -- the
token's measured screen position corrects the aim on every step, so a wrong
idea about walkspeed, a haste token, a slope or a shove all come out in the
wash. It is also the one place in this project where the design document's
headline claim, that movement should be closed-loop rather than dead-reckoned,
is actually true of the code.

WHERE IT RUNS, AND WHY THAT PLACE. Between two passes of the field pattern,
never during one. A pattern pass is a recorded sequence of timed holds that
only works from a known starting point, so interrupting one would leave the
character somewhere the rest of the pass does not expect.

IT ALWAYS COMES BACK. Every step is recorded, and the detour is walked back by
reversing them in order. Not coming back would be half the walking, but the
field patterns are loops of blind timed holds and a drift of thirty studs per
pass accumulates into a character standing in a wall.

WHAT BOUNDS IT, because an unbounded detour is how a farm bot ends up in the sea:

  * `MAX_STEPS` and `STEP_SECONDS` -- a hard ceiling on one detour.
  * `gather.token_radius` -- the owner's setting, converted into a step budget
    at the configured walkspeed, so a smaller radius really is a shorter walk.
  * It chases ONE token and returns. No hopping from token to token, because
    each hop makes the way home longer and less certain.
  * It presses no keys but movement. Tokens are collected by touching them;
    `e` is the interact key and pressing it in a field is how this project once
    opened a Polar Bear dialogue by accident.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from ..vision import tokens
from . import motion

# One step of the loop: hold the movement keys this long, then look again.
# Short enough that a wrong heading is corrected quickly, long enough that the
# capture and detection cost (about 16 ms) is not most of the work.
STEP_SECONDS = 0.35
# A STEP UNDER A SPEED BUFF IS SHORTER, so it covers about the same ground.
# MEASURED 2026-10-14 (scripts/token_payoff.py, runs 820-999, 4,654 chases):
# under Haste x5+ a chase reached its token 79% at ~310 px against 94%
# without, and 39% against 61% at ~600 px -- a fixed 0.35 s at 2x walks twice
# as far and overshoots a near token, as the route holds did before they were
# divided by the buff bar's factor (act/routes `_hold_seconds`). `speed()` is
# that factor; the step is held for STEP_SECONDS / it.
def _step_seconds(speed) -> float:
    try:
        factor = float(speed() if callable(speed) else (speed or 1.0))
    except Exception:
        factor = 1.0
    return STEP_SECONDS / min(4.0, max(1.0, factor))

# See chase_confidence_from: p 0.9984 on the coin network's scale, above the
# detector's own cut (tokens.CHASE_CONFIDENCE, p 0.99) on purpose.
DEFAULT_CHASE_CONFIDENCE = 0.7

# A hard ceiling on one detour regardless of what the radius allows.
MAX_STEPS = 10

# The character's own position on screen, as a fraction of the frame. It stands
# in the middle, a little below centre -- the same anchor `vision.tokens.nearest`
# measures distance from.
ANCHOR = (0.5, 0.62)

# Close enough to have walked onto it. Tokens are collected by touching them,
# and near the character a token is a large object on screen.
ARRIVED_PIXELS = 110

# Below this there is no direction worth pressing a key for.
DEADZONE_PIXELS = 45

# NO CHASE AT ALL WHILE THE GATHER STANDS STILL (W5, 2026-10-12). A Stationary
# pattern (Natro's patterns/Stationary.ahk, a 10 s pause: Cactus, Clover and
# Stump here) walks nowhere, so nothing brings a detour's leftover back, and
# the leftovers add up until the character is off the field. MEASURED over
# runs 800-915 (scratchpad staypat_trips.py / staypat_chases.py): 21 gathers
# had the pollen counter flat with the feed naming no field (off every field;
# 17 ended there, the gather ended by "the pollen stopped rising" and its walk
# home lost), and 20 of the 21 had chased. Stationary trips that chased: 13 of
# 28 (Cactus 10, Clover 3); that did not: 0 of 4. Corner-snake trips that
# chased: 7 of 128; that did not: 1 of 135 -- the pattern itself does not
# wander. Per chase, the last one before such a flat stretch was on Cactus 10
# of 310, Clover 2 of 81, against 4 of 3,120 on Pine Tree, Blue Flower, Rose
# and Bamboo; 16 of the 21 began <= 30 s after a chase started (27-35% of
# gathering seconds are). Where they end: var/incidents/20261012-013228-stall
# (wedged between the field's wall and a cactus, the flowers beside it),
# -015013- (plain grass by a picket fence), -015942- / -031700- (against a wall).
# Each chase there said "home by sight" within ARRIVED_PIXELS, and the trip's
# summed drift read (-109, -71) px (run-894 01:34:22) -- the flow does not see
# it. Natro never chases in a gather, and turns its own drift check off for
# this pattern (natro_macro.ahk: FDCEnabled := ... FieldPattern !=
# "Stationary"). Clover got the same rule by name on 2026-10-10 (run_farm
# NO_CHASE_FIELDS, 8 of 13 trips stalled); since then its 4 trips: 0 off.
# "on"; "ab" = on in ODD hours (HOME_UNSTICK / HOME_ALIGN's A/B uses the even
# ones, so each arm differs in one thing); "off" = chase as before (Clover by
# its name still does not). On, not "ab": 13 of 28 against 0 of 4 is the
# Clover rule again, and Cactus comes in bursts (20 of its 23 trips in one
# night, a quest's), so an hour split would cost a stall in every second
# chasing trip for weeks. Read it off the logs: "no token chase this trip",
# then "the pollen counter has not risen" on the same trips.
STAND_STILL = "on"
# Steps that move nothing: a pattern made only of these stands still.
STILL_OPS = frozenset({"pause", "camera"})


def stand_still(steps, hour: int | None = None) -> bool:
    """No token chase for a gather whose pattern `steps` (the routine's step
    dicts) walk nowhere, while STAND_STILL is on (now, or at `hour`)."""
    if not steps or any(s.get("op") not in STILL_OPS for s in steps):
        return False
    if STAND_STILL == "ab":
        return (time.localtime().tm_hour if hour is None else hour) % 2 == 1
    return STAND_STILL == "on"


@dataclass
class ChaseResult:
    """What the detour did. `walked` is the only claim that moved anything."""
    saw: int = 0                    # tokens visible when it started
    walked: bool = False
    steps: int = 0
    seconds: float = 0.0
    confidence: float = 0.0
    # "looking" when the odometer walked the detour back to zero by
    # measurement; "reversing the legs" when it had to fall back. See chase().
    returned_by: str = ""
    kind: str = "unknown"           # from the kind table, when it could say
    arrived: bool = False           # the token ended up under the character
    reason: str = ""
    # (keys, seconds) held AND not read as moving nothing (`_record_leg`):
    # what a walk back by reversal undoes
    legs: list = field(default_factory=list)
    # (x, y) of a target that stayed put on screen while the ground moved: not
    # in the world (see STUCK_PX); the caller tells vision/pinned to skip it.
    attached: tuple | None = None
    # The frames the walk DECIDED on -- the first look and each look after a
    # step, LOOKS_KEPT at most -- for a caller keeping a missed chase. Not the
    # frames a hold samples for the odometer: run_farm's loot-miss keeper took
    # the first three frames asked for, and those were the first step's own
    # samples, all three a fraction of a second apart (2026-10-03 04:34).
    looks: list = field(default_factory=list, repr=False)
    # ONE ROW A STEP, for a caller keeping a missed chase: where the target
    # was aimed at, the keys held, where the ground's motion said it should
    # be next, and the sighting re-found there (None: lost). The frames alone
    # do not say which sighting was the target (2026-10-03 09:19).
    trail: list = field(default_factory=list, repr=False)
    anchor: tuple | None = None
    steps_on_prediction: int = 0    # steps walked on a prediction (STEPS_ON_PREDICTION)
    # The look SIGHT_SETTLE_S after arriving (`_sight_after_arrival`): is the
    # target still where the walk stopped? None when no such look was taken.
    sight: dict | None = None

    @property
    def studs(self) -> float:
        """Roughly how far it went, for the cycle's odometer.

        Deliberately approximate and derived from time rather than measured:
        there is no working ground plane to measure against, and a number that
        pretends otherwise would be worse than an obvious estimate.
        """
        return self.steps * STEP_SECONDS * 28.0

    def describe(self) -> str:
        if self.walked:
            end = ("walked onto it" if self.arrived
                   else self.reason or "ran out of steps")
            what = "a token" if self.kind == "unknown" else f"a {self.kind.replace('_', ' ')} token"
            return (f"chased {what} — {self.steps} step(s), {end} "
                    f"(confidence {self.confidence:.2f}, {self.saw} in view)")
        return f"no chase: {self.reason}"


def anchor_of(width: int, height: int) -> tuple[int, int]:
    """Where the character is on screen."""
    return int(width * ANCHOR[0]), int(height * ANCHOR[1])


def keys_towards(dx: float, dy: float) -> str:
    """Which movement keys walk towards a token that far away ON SCREEN.

    `dy` is negative when the token is higher up the screen, which is further
    away, so that is forward. The deadzone stops a token dead ahead from also
    holding a strafe key and crabbing sideways.
    """
    keys = ""
    if dy < -DEADZONE_PIXELS:
        keys += "w"
    elif dy > DEADZONE_PIXELS:
        keys += "s"
    if dx > DEADZONE_PIXELS:
        keys += "d"
    elif dx < -DEADZONE_PIXELS:
        keys += "a"
    return keys


def _reverse(keys: str) -> str:
    """The keys that undo a hold."""
    swap = {"w": "s", "s": "w", "a": "d", "d": "a"}
    return "".join(swap.get(k, k) for k in keys)


def step_budget(radius_studs: float, walkspeed: float) -> int:
    """How many steps the owner's radius setting pays for.

    A step covers roughly `walkspeed * STEP_SECONDS` studs, so a 45-stud radius
    at 28 studs/second buys four steps out. Capped by MAX_STEPS either way.
    """
    per_step = max(1.0, walkspeed) * STEP_SECONDS
    return max(1, min(MAX_STEPS, int(radius_studs / per_step)))


def look(frame) -> list:
    """Every token in this frame. Thin wrapper so callers need one import."""
    return tokens.detect(frame)


def chase_confidence_from(settings, fallback: float = DEFAULT_CHASE_CONFIDENCE) -> float:
    """`gather.chase_confidence` as a fraction: how sure before a walk.

    On the coin detector's scale (vision/coins: the network's log-odds, 0.5
    is p 0.99, 0.7 is p 0.9984). What each cut keeps and costs is measured in
    data/models/coins.json `held_out` -- coins found against boxes that are
    not coins, on frames the model never trained on. Until 2026-09-28 this
    number cut a glyph detector that found bees (the owner watched it
    "chasin bees thinking they are tokens", 2026-09-22); the setting kept
    its meaning, "how sure", and its owner's value. Clamped to 0.3..0.95.
    """
    try:
        pct = float(settings.int("gather.chase_confidence"))
    except Exception:
        return fallback
    if pct <= 0:
        return fallback
    return min(0.95, max(0.3, pct / 100.0))


def chase(frames, *, vin, walkspeed: float = 28.0,
          radius_studs: float = 45.0, sleep=time.sleep,
          stopped=None, on_note=None, ground=None, kinds=None,
          ignore=None,
          min_confidence: float = tokens.CHASE_CONFIDENCE,
          pick=None, tracker=None, odometer=None,
          clock=time.monotonic, on_attached=None, fallback=None,
          carry=None, predict_steps: int | None = None,
          speed=None) -> ChaseResult:
    """Walk towards a token, then walk back.

    `frames()` returns the current frame; it is called on EVERY step, which is
    what makes this closed-loop. `ground` is accepted and ignored -- callers
    used to pass a homography and the parameter is kept so they do not break,
    but see the module docstring for why it is not used.

    `pick(seen, width, height) -> Sighting | None` chooses the target. Without
    it the old rule applies -- the nearest sighting above the gate -- which
    a popular macro's documentation describes exactly: "it picks easy pollen
    and walks past the token that matters". With it, `brain.tokenbrain` does
    the choosing (DESIGN 8y) and this function only does the walking.

    `odometer` is a `vision.flow.Odometer` over the ground: it is zeroed where
    the detour begins and fed a frame every SAMPLE_SECONDS for as long as any
    key is held, so it reads the character's own movement off the ground's
    motion. The way BACK is then walked by looking -- step toward zero
    displacement, look, step -- rather than by reversing the outward legs
    blind. Reversing legs was the drift the owner described ("if somthing
    causes the player to move off cause its a load of wasted time"): a knock,
    a wall, a slope, and the reversal returns to the wrong place with nothing
    to say so. When the odometer has no reading the walk falls back to
    reversal and the result says which happened. (An odometer read off the
    tokens' own screen positions was tried first and MEASURED useless -- see
    `vision.flow.Odometer` -- so the tokens are not asked how far we walked.)

    `fallback`, with `pick`, is the target where the brain's deciding look
    saw it: walked toward when the picker finds nothing in two looks.

    `predict_steps` overrides STEPS_ON_PREDICTION: 0 on a ledge, where a token
    lost after a step has most likely gone below the edge (run_farm
    LEDGE_FIELDS).

    `carry`, a two-item list the caller zeroes when a gather begins, is what
    earlier walks home by looking left over (CARRY): this one aims at where
    the gather was, not at where this detour began, and writes its own
    leftover back.

    `tracker` is a `vision.tracks.Tracker`, the token memory. Every look is
    fed to it, together with how far the ground moved since the previous look
    when the odometer knows, so the tokens it remembers are carried along
    with the ground rather than un-matched by every step.

    WHATEVER CHOSE THE TARGET, THE WALK KEEPS IT. Mid-chase re-acquisition
    used to take the sighting nearest the CHARACTER, so a step toward one
    token could hand the walk to a different token that had drifted closer --
    the same re-aiming-every-look that leaves a field of near-equal tokens
    uncollected. Now each look re-finds the sighting nearest the target's
    LAST position, and only that.
    """
    note = on_note or (lambda text: None)
    result = ChaseResult()

    frame = _grab(frames, note)
    if frame is None:
        result.reason = "no frame to look at"
        return result
    _kept(result, frame)

    height, width = frame.shape[:2]
    ax, ay = anchor_of(width, height)
    result.anchor = (int(ax), int(ay))
    seen = _look(frame, ignore)
    result.saw = len(seen)
    if odometer is not None:
        try:
            odometer.reset()
            odometer.update(frame)          # the first frame primes the flow
        except Exception:
            odometer = None      # a broken odometer means the old return, said below
    if tracker is not None:
        try:
            tracker.observe(seen, clock())
        except Exception:
            tracker = None
    # `kinds` is the token-kind table (data/knowledge/tokens.yaml). With it a
    # kind worth more -- the owner's Tabby Love, once its colour is measured --
    # is chased ahead of a closer ordinary token.
    if callable(pick):
        try:
            target = pick(seen, width, height)
            if target is None:
                # ONE MORE LOOK BEFORE "NONE", as a step's re-find takes one
                # (below): the detector flickers. MEASURED 2026-10-01 on 20 of
                # the day's Pine Tree recordings (scripts/replay_brain.py
                # --in-view): of the chase targets the next frame did not show
                # at the owner's gate, a second frame showed 13 of 86.
                again = _grab(frames, note)
                if again is not None:
                    second = _look(again, ignore)
                    if odometer is not None:
                        try:
                            odometer.update(again)
                        except Exception:
                            odometer = None
                    if tracker is not None:
                        try:
                            tracker.observe(second, clock())
                        except Exception:
                            tracker = None
                    target = pick(second, width, height)
                    if target is None and fallback is not None:
                        # THE BRAIN'S OWN LOOK, a moment old: `fallback` is
                        # the target where the deciding look matched it. A
                        # spinning coin edge-on in both start looks is still
                        # there -- MEASURED 2026-10-07, 33 of 107 chase
                        # decisions in runs 715-734 ended here -- and the
                        # step's own re-find, the stuck test and the walk
                        # home by looking still judge it.
                        target = fallback
                        note(f"not re-seen at the start ({len(seen)} then {len(second)} "
                             f"candidate(s)); walking on the deciding look")
                    if target is None:
                        result.reason = (f"{len(seen)} candidate(s), then {len(second)} "
                                         f"on a second look; the brain chose none")
                        return result
                    seen = second
                    result.saw = max(result.saw, len(second))
        except Exception as exc:
            result.reason = f"the picker failed ({exc}); not walking on a guess"
            return result
        if target is None:
            result.reason = f"{len(seen)} candidate(s); the brain chose none"
            return result
    else:
        target = tokens.nearest(seen, width, height, prefer=kinds,
                                min_confidence=min_confidence)
        if target is None:
            result.reason = (f"{len(seen)} candidate(s), none above the "
                             f"{min_confidence:.2f} confidence needed to "
                             f"walk somewhere")
            return result
    result.confidence = target.confidence
    result.kind = target.kind

    budget = step_budget(radius_studs, walkspeed)
    # Re-found at no stricter a gate than it was chosen at: see REFIND_CONFIDENCE.
    regate = min(float(min_confidence), REFIND_CONFIDENCE, float(target.confidence))
    what = "a token" if target.kind == "unknown" else f"a {target.kind.replace('_', ' ')} token"
    note(f"chasing {what} at ({target.x}, {target.y}), confidence "
         f"{target.confidence:.2f}, up to {budget} step(s)")

    on_prediction = STEPS_ON_PREDICTION if predict_steps is None else max(0, int(predict_steps))
    blind_left = on_prediction
    try:
        for _ in range(budget):
            if stopped is not None and stopped():
                result.reason = "stop requested"
                break
            dx, dy = target.x - ax, target.y - ay
            if abs(dx) <= ARRIVED_PIXELS and abs(dy) <= ARRIVED_PIXELS:
                # ARRIVING IS SOMETHING YOU DO BY WALKING. This used to set
                # `arrived` whatever the step count, so a chase that had not
                # moved at all reported "already standing on the nearest
                # token" -- a claim that a token was collected when nothing
                # happened. MEASURED at the hive, the detector's strongest
                # sighting is usually the player's own bee (see
                # `vision.tokens`, the AVATAR note), and the bee is always
                # within this radius, so the chase declared success on itself
                # and the real token 385 px away was never walked to. The
                # owner watched the result: "all its doing is literally
                # turning by 1 and jumping once if its not getting anything".
                if result.steps == 0:
                    result.reason = (
                        f"the nearest thing it is sure about is already within "
                        f"{ARRIVED_PIXELS} px of the character "
                        f"({target.x}, {target.y}) — nothing to walk to, and "
                        f"nothing was collected by standing still")
                    break
                result.arrived = True
                break
            keys = keys_towards(dx, dy)
            if not keys:
                if result.steps == 0:
                    result.reason = ("the nearest thing it is sure about is "
                                     "dead under the character; no direction "
                                     "to walk")
                    break
                result.arrived = True
                break
            _follow(odometer, target)
            held = _step_seconds(speed)
            hold = _hold(vin, keys, held, sleep, frames, odometer)
            _record_leg(result, keys, hold, held)
            result.steps += 1

            frame = _grab(frames, note)
            if frame is None:
                break
            _kept(result, frame)
            seen = _look(frame, ignore)
            if tracker is not None:
                try:
                    tracker.observe(seen, clock(), scene_shift=_scene_shift(hold))
                except Exception:
                    pass
            # WHERE THE TARGET SHOULD BE NOW, and at the detector's own gate.
            # A ground token slides with the ground, and a 0.35 s step slides
            # it about SAME_TOKEN_PX -- the whole match radius -- so matching
            # against where it WAS lost it on most steps. And the target was
            # often chosen below `min_confidence` (the brain's `pick` had no
            # gate until run_farm's gave it one, DESIGN 8ds), so re-finding
            # it at 0.7 lost it again. MEASURED in the
            # night logs (audit 2026-09-25): 714 of 977 chases starting 270-
            # 359 px out ended "1 step(s), walked onto it", which one step
            # cannot cover. See REFIND_CONFIDENCE.
            shift = _scene_shift(hold)
            near = _carried_to(odometer, hold)
            far_y = ay - FAR_ABOVE_PX
            found = _same_token(seen, target, regate, shift, near, far_y=far_y)
            if found is None:
                # ONE MORE LOOK, NOT A STEP: detector confidence flickers.
                again = _grab(frames, note)
                if again is not None:
                    _kept(result, again)
                    seen = _look(again, ignore)
                    found = _same_token(seen, target, regate, shift, near, far_y=far_y)
            expect = (near if near is not None else
                      (target.x + shift[0], target.y + shift[1]) if shift is not None
                      else (target.x, target.y))
            result.trail.append({
                "aim": [int(target.x), int(target.y)], "keys": keys,
                "expect": [int(expect[0]), int(expect[1])],
                "found": [int(found.x), int(found.y)] if found is not None else None,
                "seen": len(seen)})
            stuck = (_stuck(seen, target, regate, shift, near)
                     if found is None else None)
            if stuck is not None:
                # IT STAYED WHERE IT WAS WHILE THE GROUND MOVED: part of the
                # character or its gear, not a token (STUCK_PX).
                result.attached = (int(target.x), int(target.y))
                result.reason = (f"it stayed at ({stuck.x}, {stuck.y}) on screen while "
                                 f"the ground moved {math.hypot(*shift):.0f} px — it is "
                                 f"not in the world")
                if callable(on_attached):
                    try:
                        on_attached(*result.attached)
                    except Exception:
                        pass
                break
            if found is None:
                # GONE. Under the character if it was within one step of
                # arriving; otherwise simply lost, which is not a collection
                # and must not teach the school "reached it, nothing moved".
                reach = ARRIVED_PIXELS + _step_px(hold)
                if abs(dx) <= reach and abs(dy) <= reach:
                    result.arrived = True
                    break
                if blind_left > 0:
                    # ONE STEP ON TOWARD WHERE IT SHOULD BE (STEPS_ON_PREDICTION).
                    blind_left -= 1
                    result.steps_on_prediction += 1
                    note(f"not re-seen {math.hypot(dx, dy):.0f} px out; one step on "
                         f"toward where it should be ({int(expect[0])}, {int(expect[1])})")
                    target = tokens.Sighting(x=int(expect[0]), y=int(expect[1]),
                                             confidence=float(target.confidence),
                                             kind=getattr(target, "kind", "unknown"))
                    continue
                result.reason = (f"lost sight of it {math.hypot(dx, dy):.0f} px "
                                 f"out, beyond one step ({reach:.0f} px)")
                break
            target = found
            blind_left = on_prediction

        if (result.arrived and SIGHT_CHECK
                and not (stopped is not None and stopped())):
            result.sight = _sight_after_arrival(frames, note, ignore, target, regate,
                                                sleep, result)

        if result.arrived and not (stopped is not None and stopped()):
            nxt = _chain_target(tracker, ax, ay, clock)
            if nxt is not None:
                d_ = math.hypot(nxt.x - ax, nxt.y - ay)
                note(f"chase would: chain to {nxt.kind}#{nxt.id} {d_:.0f} px on "
                     f"rather than walk home -- look-only")

        if stopped is not None and stopped():
            # NO WALK BACK AFTER A STOP OR A TAKE OVER: after a Take Over the
            # keys never reach the game (brain/controls.GuardedInput), so up
            # to RETURN_LOOKS steps would press nothing, and a stop is not an
            # invitation to walk.
            note("not walking back: stop requested or the owner has the controls")
        elif odometer is not None and _walk_home_by_looking(
                result, vin, sleep, note, frames, ignore, tracker, odometer, clock,
                carry, speed):
            result.returned_by = "looking"
        else:
            _walk_back(result, vin, sleep, note)
            result.returned_by = "reversing the legs"
    finally:
        # Belt to the braces of `held()`. No detour ever leaves a key down.
        try:
            vin.release_all()
        except Exception:
            pass

    result.walked = result.steps > 0
    result.seconds = sum(s for _, s in result.legs) * 2
    if not result.walked and not result.reason:
        result.reason = "nothing was walked to"
    return result


# A sighting within this many pixels of where the target was last seen is the
# same token, one step later. Same figure the tracker uses (vision/tracks) and
# for the same reason: a step shifts a token by tens of pixels, and distinct
# tokens sit well over a hundred apart.
SAME_TOKEN_PX = 90.0
# HOW MANY STEPS IN A ROW MAY GO ON THE PREDICTION when a step's two looks
# miss the target beyond one step's reach. MEASURED 2026-10-07 21:12-21:18
# (run-737): 9 of 30 chases ended "lost sight", all after their first step,
# the target 283-782 px out against steps of 118-365 px -- a coin edge-on in
# two looks, or past the re-find, a step or two short. One more step toward
# where the ground carried it, then two more looks.
STEPS_ON_PREDICTION = 1
# THE GATE A TARGET IS RE-FOUND AT, once chosen: the detector's own cut
# (vision/tokens CHASE_CONFIDENCE, 0.5: MEASURED on the labelled frame, 8 of
# 9 real tokens kept and 0 of 19 flowers) -- or the confidence the target was
# chosen at, when that is lower. Never the stricter walk gate: the brain's
# `pick` handed the walk targets below it (0.34-0.59 in the night logs, audit
# 2026-09-25; run_farm's `pick` applies gather.chase_confidence since, DESIGN
# 8ds), and re-finding a target at a stricter standard than it was chosen
# by is what lost it after one step. Not "no gate" either: the
# detector returns 30-40 sightings a frame in a field (run_farm
# perceive_tokens, MEASURED 2026-09-22 21:10), which puts one within
# SAME_TOKEN_PX of a given point about four times in ten (35 x pi x 90^2
# over 1920 x 1080); the chooser's own standard is the one the walk keeps.
REFIND_CONFIDENCE = tokens.CHASE_CONFIDENCE

# ONE LOOK AFTER ARRIVING, FOR THE SCHOOL (2026-10-21, look-only). MEASURED
# 2026-10-21 (tools/analysis/chase_lessons.py, runs 1050-1158): of 1,831
# reached honey tokens the HUD confirmed 157 -- "a trickle of 2,338 in 1.8s
# hides a honey token under 4,676" -- so honey pickups go unlabelled and the
# coin school learns mostly buff tokens. A token touched is a token gone:
# SIGHT_SETTLE_S after the walk stops, one more look (no key held) says
# whether the target is still where the walk left it. brain/school records
# the answer beside the HUD verdict and does not label by it yet
# (school.SIGHT_LABELS). ponytail: 0.25 s is a guess at how long a picked-up
# token takes to leave the frame; the kept look (`looks`) is what measures
# it. Costs the settle once per arrived chase.
SIGHT_CHECK = True
SIGHT_SETTLE_S = 0.25


def _sight_after_arrival(frames, note, ignore, target, regate: float, sleep,
                         result) -> dict:
    """Is the target still there SIGHT_SETTLE_S after the walk stopped?

    `{"verdict": "gone" | "still there" | "no frame", "settle_s", "seen",
    "near_px"}`. "gone": no sighting at the re-find gate within SAME_TOKEN_PX
    of where the target was last seen, nor within ARRIVED_PIXELS of the
    character (a step past it moves it on screen). `near_px` is the nearest
    sighting to the target's last spot, None when nothing was seen. Presses
    nothing; the frame joins `result.looks`.
    """
    try:
        sleep(SIGHT_SETTLE_S)
    except Exception:
        pass
    frame = _grab(frames, note)
    if frame is None:
        return {"verdict": "no frame", "settle_s": SIGHT_SETTLE_S, "seen": 0, "near_px": None}
    _kept(result, frame)
    height, width = frame.shape[:2]
    ax, ay = anchor_of(width, height)
    seen = [s for s in _look(frame, ignore) if s.confidence >= regate]
    near = min((math.hypot(s.x - target.x, s.y - target.y) for s in seen), default=None)
    underfoot = any(abs(s.x - ax) <= ARRIVED_PIXELS and abs(s.y - ay) <= ARRIVED_PIXELS
                    for s in seen)
    still = underfoot or (near is not None and near <= SAME_TOKEN_PX)
    return {"verdict": "still there" if still else "gone", "settle_s": SIGHT_SETTLE_S,
            "seen": len(seen), "near_px": None if near is None else round(near, 1),
            "underfoot": underfoot}


# HOW FAR ABOVE THE CHARACTER A TARGET MUST BE for `_along`: high up the screen
# is far away, where a step moves it little. The gear hanging beside the
# character sits lower (y 443-469 against the anchor's 670 at 1080 px,
# MEASURED, see STUCK_PX) and must not pass for a far token; the far misses
# re-seen on their way were at y 335-426 (MEASURED 2026-10-03).
FAR_ABOVE_PX = 250


def _same_token(seen, target, min_confidence: float, shift=None, near=None,
                far_y: float | None = None):
    """The sighting that is the target we were walking to, or None.

    `shift` is how far the ground slid during the step (+x right, +y down);
    the target is looked for where the ground carried it, the way the token
    memory does (vision/tracks: shift first, then match within MATCH_PX).
    `near`, when the odometer carried the target's own spot with the ground
    beside it (vision/flow.carried), is that place instead: a far token
    slides a fraction of the median (flow.FOLLOW_NEAREST has the numbers)."""
    ox, oy = float(target.x), float(target.y)
    px, py = ox, oy
    if near is not None:
        px, py = float(near[0]), float(near[1])
    elif shift is not None:
        px, py = px + float(shift[0]), py + float(shift[1])
    best, best_d = None, SAME_TOKEN_PX
    for s in seen:
        if s.confidence < min_confidence:
            continue
        d = math.hypot(s.x - px, s.y - py)
        if d <= best_d:
            best, best_d = s, d
    if best is None and far_y is not None and oy <= far_y:
        best = _along(seen, (ox, oy), (px, py), min_confidence)
    elif best is None:
        best = _beyond(seen, (ox, oy), (px, py), min_confidence)
    return best


def _to_segment(x, y, a, b) -> tuple:
    """(distance from (x, y) to the segment a-b, how far along it, 0 to 1)."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    t = 0.0 if span == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / span))
    return math.hypot(x - (ax + t * dx), y - (ay + t * dy)), t


def _along(seen, was, carried, min_confidence: float):
    """A FAR TOKEN SLIDES LESS THAN THE GROUND BESIDE THE CHARACTER. MEASURED
    2026-10-03 on the misses of 08:53 and 11:16 (var/loot_misses): targets
    676-842 px out, near the horizon, were seen again 40-83 px from where they
    WERE after one step, while the prediction -- carried by the ground's
    motion -- had put them hundreds of pixels on. A token lies somewhere
    between the two, so the nearest sighting within SAME_TOKEN_PX of the
    segment from where it was to where the ground would carry it is the
    target -- if it moved the ground's way, and is not within STUCK_PX of
    where it was after a step of STUCK_MIN_SHIFT or more: that is `_stuck`'s,
    as before (the gear hanging beside the character)."""
    moved = math.hypot(carried[0] - was[0], carried[1] - was[1])
    if moved < 1.0:
        return None
    best, best_d = None, SAME_TOKEN_PX
    for s in seen or ():
        if s.confidence < min_confidence:
            continue
        if moved >= STUCK_MIN_SHIFT and math.hypot(s.x - was[0], s.y - was[1]) <= STUCK_PX:
            continue
        d, t = _to_segment(float(s.x), float(s.y), was, carried)
        if t <= 0.0:
            continue                    # not the ground's way at all
        if d <= best_d:
            best, best_d = s, d
    return best


# A NEAR TOKEN SLIDES FURTHER THAN THE GROUND'S MEDIAN, the far one's
# opposite (`_along`). MEASURED 2026-10-07 on the lost chases kept in
# var/loot_misses with their looks: two honey targets 420-430 px up-left of
# the character were in the look after the step at confidence 1.0, grown to
# 300-340 px coins beside it, 1.7x as far along the predicted direction as
# predicted and 4-26 px off its line -- "lost sight" one step from the
# pickup. The one sighting a wider circle would have taken instead was the
# character's own helmet, 137 px off that line.
BEYOND_REACH = 2.0


def _beyond(seen, was, carried, min_confidence: float):
    """The sighting within SAME_TOKEN_PX of the line from the prediction on
    to BEYOND_REACH times the predicted move, or None."""
    vx, vy = carried[0] - was[0], carried[1] - was[1]
    if math.hypot(vx, vy) < 1.0:
        return None
    end = (was[0] + BEYOND_REACH * vx, was[1] + BEYOND_REACH * vy)
    best, best_d = None, SAME_TOKEN_PX
    for s in seen or ():
        if s.confidence < min_confidence:
            continue
        d, _t = _to_segment(float(s.x), float(s.y), carried, end)
        if d <= best_d:
            best, best_d = s, d
    return best


# A TARGET THAT STAYS PUT ON SCREEN WHILE THE GROUND MOVES IS NOT IN THE
# WORLD. MEASURED 2026-10-03: 128 of the token school's last 400 lessons were
# "honey" targets at (402-467, 443-469), every one "the chase never reached
# it" -- their crops are an olive-yellow curved surface with a pale rim
# hanging left of the character (var/school-coins/crops/*-455-455.png), and
# it bobs 20-60 px, past vision/pinned's 4 px tolerance, so it never pinned.
# After a step whose ground motion was measured at STUCK_MIN_SHIFT or more, a
# sighting still within STUCK_PX of where the target WAS (not where the
# ground carried it) is that kind of thing.
STUCK_PX = 40.0
STUCK_MIN_SHIFT = 60.0


def _stuck(seen, target, min_confidence: float, shift, near=None):
    """The sighting that stayed where `target` was although the ground moved
    `shift` -- the target is attached to the view -- or None. With `near`
    (the target's spot carried by the ground beside it) it is THAT ground
    which must have moved: a far token slides little, and is no gear for it."""
    if near is not None:
        shift = (float(near[0]) - float(target.x), float(near[1]) - float(target.y))
    if shift is None or math.hypot(float(shift[0]), float(shift[1])) < STUCK_MIN_SHIFT:
        return None
    best, best_d = None, STUCK_PX
    for s in seen or ():
        if s.confidence < min_confidence:
            continue
        d = math.hypot(s.x - float(target.x), s.y - float(target.y))
        if d <= best_d:
            best, best_d = s, d
    return best


def _step_px(hold) -> float:
    """How far one step moved the ground, regardless of direction: the hold's
    measured travel, or SAME_TOKEN_PX (about 90 px a 0.35 s step, MEASURED in
    runs 237-239, vision/tracks) when it went unmeasured."""
    if hold is None or hold[0] == 0 or len(hold) < 4:
        return SAME_TOKEN_PX
    return max(0.0, float(hold[3]))


def _look(frame, ignore) -> list:
    """Every token in this frame that is really in the world.

    `ignore(x, y)` is `vision.pinned.Pinned.is_pinned`. THIS IS THE FIX FOR
    THE WORST BUG IN THE TOKEN PATH: `tokens.nearest` returns the closest
    sighting it is sure about, and the closest sighting is nearly always the
    player's own bee -- measured, it won 14 of 18 frames of `var/tokens_live`,
    with the real token 385 px away. The bee is also always inside
    ARRIVED_PIXELS, so the chase then reported success without moving.

    A mark that does not move while the view does is not in the world. See
    `vision.pinned` for the 2,380-sample run that established it.
    """
    seen = tokens.detect(frame)
    if not callable(ignore):
        return seen
    try:
        return [s for s in seen if not ignore(s.x, s.y)]
    except Exception:
        return seen


# How many looks the return by odometer may take. A detour is at most
# MAX_STEPS out, so this is the same out and back with a margin for correction.
# A chase walks `2 * steps + 4` of them, its own detour's out and back
# (`_walk_home_by_looking`): MEASURED 2026-10-13 (var/night/run-940..979.log),
# 705 of the 716 walks "home by sight" matched to their chase took no more,
# and each of the 10 that "gave up homing by sight after 24 looks" held 24
# steps (8.4 s) and then 9-10 s of reversed legs after a detour of 1-3 steps
# (where the log says; run-941 01:58:53-01:59:14, run-977 22:08:41-22:09:02).
# RETURN_LOOKS stays
# for a walk with no detour of its own (run_farm `walk_back_the_drift`).
RETURN_LOOKS = MAX_STEPS * 2 + 4
# Two steps in a row that the ground could not measure and the walk home
# stops trusting a displacement it can no longer see change. The caller's
# reversal takes over, and it reverses the homeward legs too. (MEASURED
# 2026-10-13 on the two Pine Tree recordings that hold an unmeasured chase
# step, replayed as 5-frame holds through vision/flow.Odometer: 10 of the 11
# unmeasured holds were the camera inside a pine tree's crown
# (var/incidents/20261013-033431-mob-sighting frames 105-117, 130-149) or a
# Bloom (-042629- frames 041-067), 0-7 points; one was night flowers blurred
# by a morph's speed, frames 031-035. The character walks on under a crown, so
# those legs are walked back.) Two steps in a row that MOVED NOTHING end it
# too (`_record_leg`).
BLIND_STEPS = 2
# THE LEFTOVER IS CARRIED, NOT DROPPED. A walk home by looking stops within
# ARRIVED_PIXELS a side of where its detour began, and the leftovers do not
# cancel: tokens are mostly ahead, so the walk back stops short on the same
# side. MEASURED 2026-10-08, run-775..778: 1,031 walks home by looking, median
# leftover 69 px, and per trip the leftovers summed to a net 526-4,267 px,
# nearly all one way (dy -469 to -4,081) -- against ~760 px for random ones
# over 149 chases. And walks home from a field landed 41 of 53 after trips of
# 0-10 chases, 20 of 46 after more (Pine Tree 12/14 against 4/9, Mountain Top
# 5/7 against 6/15). So each walk back aims past its detour's start by what
# the earlier ones left (`carry`), which keeps the sum within one leftover.
# Clamped, so one bad reading cannot send a detour's walk back far.
CARRY_MAX_PX = 2 * ARRIVED_PIXELS
# CLOSE ENOUGH IS HOME, LOOK-ONLY. MEASURED 2026-10-21 (research over runs
# 1084-1165, 257 trips): a walk home that "gave up homing by sight" ends the
# chasing for the trip (run_farm CHASE_LOSSES_PER_TRIP = 1) -- 182 of 257
# trips, ~54% of all gathering time unchased -- and of its 131 give-ups the
# leftover's median was 172 px, 86 within 200 px, against a 110 px box
# (run-1164 18:16:17: +122, +40). Within CLOSE_ENOUGH_PX it would be taken
# as home, the leftover carried (clamped) like any other; until
# CLOSE_ENOUGH_LIVE it only says so.
# LIVE since 2026-10-22: MEASURED runs 1173-1182 (after the movement sweep):
# 374 homes by sight, 10 give-ups, 5 of those inside this box (-187,-92;
# -151,+1; -212,+19; +216,-5; -195,+2 -- all mostly x, all carried by _keep).
CLOSE_ENOUGH_PX = 2 * ARRIVED_PIXELS
CLOSE_ENOUGH_LIVE = True
# THE LAST STEPS HOME ARE SIZED TO WHAT IS LEFT, LOOK-ONLY. A fixed step can
# be wider than the 2 * ARRIVED_PIXELS box and step across it back and forth.
# MEASURED 2026-10-21 (runs 1086-1167, 124 give-ups paired with their chase):
# 98 were out on x only, 3 on y only; leftover |dx| median 168 px (p25 121,
# p90 259), both signs about equally (66 -, 58 +); steps ("beyond one step")
# median 128 px, p90 227, max 494 -- about 10% wider than the box. So a step
# is held for residual / (last measured travel on that axis per second),
# never under MIN_STEP_FRACTION of a step, and an axis already within
# ARRIVED_PIXELS - DEADZONE_PIXELS presses no key (keys_towards adds one past
# the deadzone even inside the box: (-211, -46) held "sd", knocking y out).
# Until PROPORTIONAL_HOME_LIVE it only says what it would hold.
# ponytail: travel taken as linear in hold time; the per-axis step px now in
# the walk's notes will show whether short holds lose a ramp-up.
PROPORTIONAL_HOME_LIVE = False
MIN_STEP_FRACTION = 0.25

# PHANTOM SPOTS, LOOK-ONLY (brain/school.phantom): a chase whose target sits
# in a cell that the latest lessons almost never reached, and whose detector
# was under school.PHANTOM_CONFIDENCE, is logged "chase would: skip phantom"
# by run_farm; only with this True is it skipped. MEASURED 2026-10-21
# (chase_lessons --phantom replay): no cell qualifies since run 800, so the
# log should stay near silent.
PHANTOM_SUPPRESS_LIVE = False

# CHAIN, DON'T WALK HOME, LOOK-ONLY. After a pickup the walk goes home even
# with the next token a step away, and each walk home risks the one failure
# that ends chasing for the trip (CLOSE_ENOUGH above: 182 of 257 trips).
# CHAIN_PX is brain/tokenbrain CLUSTER_RADIUS_PX, the radius it already calls
# "together"; CHAIN_SEEN_S is about one step and its look (0.44 s a step,
# MEASURED 2026-10-21 over runs 1130-1169), so only what the latest look
# matched counts -- a remembered track is rarely still there (IN_VIEW_S).
# It only logs "chase would: chain to ..."; the live walk (CHAIN_LIVE) is not
# built yet -- build it once those lines are checked against the frames.
CHAIN_PX = 260.0
CHAIN_SEEN_S = 0.5
CHAIN_LIVE = False


# The sampling cadence inside a hold, from act/motion; named here because the
# walk's tests count samples by it.
SAMPLE_SECONDS = motion.SAMPLE_SECONDS


def _hold(vin, keys, seconds: float, sleep, frames, odometer):
    """`act.motion.hold_measuring`, kept under the name the walk uses."""
    return motion.hold_measuring(vin, keys, seconds, sleep, frames, odometer)


LOOKS_KEPT = 4


def _kept(result: ChaseResult, frame) -> None:
    if len(result.looks) < LOOKS_KEPT:
        result.looks.append(frame)


def _follow(odometer, target) -> None:
    """Ask the odometer to carry `target`'s spot through the next hold."""
    follow = getattr(odometer, "follow", None)
    if callable(follow):
        try:
            follow(target.x, target.y)
        except Exception:
            pass


def _carried_to(odometer, hold) -> tuple[float, float] | None:
    """Where the odometer carried the followed spot over `hold`, or None when
    the hold went unmeasured or the odometer carries no spot."""
    if hold is None or hold[0] == 0:
        return None
    point = getattr(odometer, "point", None)
    if not isinstance(point, tuple) or len(point) != 2:
        return None
    return point


def _scene_shift(hold) -> tuple[float, float] | None:
    """The ground's motion over a hold, for the tracker; None if unmeasured."""
    if hold is None or hold[0] == 0:
        return None
    return (hold[1], hold[2])


def _walk_home_by_looking(result: ChaseResult, vin, sleep, note, frames, ignore,
                          tracker, odometer, clock, carry=None, speed=None) -> bool:
    """Walk the odometer back to zero, looking after every step.

    True when the character is back within ARRIVED_PIXELS of where the detour
    began BY MEASUREMENT; False when the odometer could not say (the ground
    gave the flow nothing to track), in which case the caller reverses the
    legs -- these homeward ones included -- and the result says so.
    """
    disp = odometer.displacement()
    if disp is None:
        note("no odometer reading to come home by (the ground gave the flow "
             "nothing to track); reversing the legs instead")
        return False
    # where the gather was, relative to this detour's start (CARRY)
    cx, cy = (float(carry[0]), float(carry[1])) if carry is not None else (0.0, 0.0)
    said_carry = (f", aiming {cx:+.0f}, {cy:+.0f} px past it for what earlier "
                  f"chases left" if (cx or cy) else "")
    disp = (disp[0] + cx, disp[1] + cy)
    blind = pushed = 0
    last = None                 # (keys, seconds, hold) of the last homeward step
    # THE BUDGET COUNTS THE CARRY: a walk aiming past its start by an earlier
    # leftover (up to CARRY_MAX_PX a side) has that much further to go.
    # MEASURED 2026-10-21 (runs 1086-1167): 2,644 of 2,816 walks home carried
    # one, and give-ups fell with detour length (1 step 5.4%, 66/1218; 3 steps
    # 2.1%) -- the shortest detours had the least slack for it.
    looks = (min(RETURN_LOOKS, 2 * result.steps + 4
                 + math.ceil(max(abs(cx), abs(cy)) / SAME_TOKEN_PX))
             if result.steps else RETURN_LOOKS)
    for look in range(looks):
        dx, dy = disp
        if abs(dx) <= ARRIVED_PIXELS and abs(dy) <= ARRIVED_PIXELS:
            note(f"home by sight after {look} step(s): {dx:+.0f}, {dy:+.0f} px "
                 f"from where the detour began{said_carry}{_axis_note(last)}")
            _keep(carry, dx, dy)
            return True
        # displacement is where WE are relative to the anchor; walk the other way
        keys = keys_towards(-dx, -dy)
        if not keys:
            return True
        held = _step_seconds(speed)
        p_keys, p_held = _proportional_step(dx, dy, held, last)
        if p_keys != keys or abs(p_held - held) >= 0.01:
            if PROPORTIONAL_HOME_LIVE:
                keys, held = p_keys, p_held
            elif max(abs(dx), abs(dy)) <= 2 * ARRIVED_PIXELS:
                # only the last steps home, where the sizing matters: further
                # out an axis 45-65 px off drops its key on most steps
                note(f"chase would: hold {p_held:.2f} s '{p_keys}' (residual "
                     f"{abs(dx):.0f}, {abs(dy):.0f} px{_axis_note(last)}) -- look-only")
        hold = _hold(vin, keys, held, sleep, frames, odometer)
        last = (keys, held, hold)
        if _record_leg(result, keys, hold, held):
            pushed = 0
        else:
            pushed += 1
            if pushed >= BLIND_STEPS:
                note(f"{pushed} steps in a row moved nothing, still {dx:+.0f}, "
                     f"{dy:+.0f} px out (pushing against something); reversing "
                     f"the legs that moved instead")
                return False
        if hold is None or hold[0] == 0:
            blind += 1
            note("that step went unmeasured (the ground gave the flow nothing "
                 "to track); looking again")
            if blind >= BLIND_STEPS:
                note(f"{blind} unmeasured steps in a row; reversing the legs instead")
                return False
        else:
            blind = 0
        if tracker is not None:
            frame = _grab(frames, note)
            if frame is not None:
                try:
                    tracker.observe(_look(frame, ignore), clock(),
                                    scene_shift=_scene_shift(hold))
                except Exception:
                    pass
        nxt = odometer.displacement()
        if nxt is None:
            return False
        disp = (nxt[0] + cx, nxt[1] + cy)
    # THE LAST STEP IS CHECKED TOO. The box test above runs before each step,
    # so the result of the final one was never looked at. MEASURED 2026-10-21
    # (runs 1086-1167, 124 give-ups paired with their chase): 22 ended with
    # both axes <= ARRIVED_PIXELS -- home, but counted as a loss that ended
    # the trip's chasing (run_farm CHASE_LOSSES_PER_TRIP).
    if abs(disp[0]) <= ARRIVED_PIXELS and abs(disp[1]) <= ARRIVED_PIXELS:
        note(f"home by sight after {looks} step(s): {disp[0]:+.0f}, {disp[1]:+.0f} px "
             f"from where the detour began{said_carry}{_axis_note(last)}")
        _keep(carry, disp[0], disp[1])
        return True
    if abs(disp[0]) <= CLOSE_ENOUGH_PX and abs(disp[1]) <= CLOSE_ENOUGH_PX:
        if CLOSE_ENOUGH_LIVE:
            note(f"home by sight, close enough after {looks} looks: {disp[0]:+.0f}, "
                 f"{disp[1]:+.0f} px from where the detour began{said_carry}")
            _keep(carry, disp[0], disp[1])
            return True
        note(f"chase would: take {disp[0]:+.0f}, {disp[1]:+.0f} px as home (within "
             f"{CLOSE_ENOUGH_PX} px) and carry it -- look-only")
    note(f"gave up homing by sight after {looks} looks, still "
         f"{disp[0]:+.0f}, {disp[1]:+.0f} px out{_axis_note(last)}")
    # `carry` stands: the caller now reverses every leg, back to the detour's start
    return False


def _axis_px(last, axis: int) -> tuple[float, float] | None:
    """(px, seconds) the last homeward step moved on `axis` (1 = x, 2 = y),
    or None when it pressed no key on that axis or went unmeasured."""
    if last is None:
        return None
    keys, seconds, hold = last
    if hold is None or hold[0] == 0 or not set(keys) & set("ad" if axis == 1 else "ws"):
        return None
    return abs(float(hold[axis])), float(seconds)


def _axis_note(last) -> str:
    """', last step x N, y M px' for the walk's notes; '' with nothing measured."""
    x, y = _axis_px(last, 1), _axis_px(last, 2)
    if x is None and y is None:
        return ""
    xs, ys = ("-" if a is None else f"{a[0]:.0f}" for a in (x, y))
    return f", last step x {xs}, y {ys} px"


# Movement is the same speed in every direction, so a diagonal step moves each
# axis about 1/sqrt(2) as fast as a straight one (reviewer, 2026-10-21).
DIAGONAL_AXIS_SHARE = math.sqrt(0.5)


def _axes(keys: str) -> int:
    return bool(set(keys) & set("ad")) + bool(set(keys) & set("ws"))


def _axis_rate(last, axis: int, keys: str) -> tuple[float, float] | None:
    """`_axis_px` rescaled from the last step's key shape to `keys`': a
    diagonal step's per-axis px is ~0.71 of what a straight step on that axis
    would move, and back."""
    a = _axis_px(last, axis)
    if a is None:
        return None
    scale = ((DIAGONAL_AXIS_SHARE if _axes(keys) == 2 else 1.0)
             / (DIAGONAL_AXIS_SHARE if _axes(last[0]) == 2 else 1.0))
    return a[0] * scale, a[1]


def _proportional(held: float, residual: float, axis) -> float:
    """Seconds to hold for `residual` px when the last step moved `axis` =
    (px, seconds) on that axis: clamped to [MIN_STEP_FRACTION, 1] x `held`."""
    if axis is None or axis[0] <= 0 or axis[1] <= 0:
        return held
    return max(MIN_STEP_FRACTION * held, min(held, residual * axis[1] / axis[0]))


def _proportional_step(dx: float, dy: float, held: float, last) -> tuple[str, float]:
    """The keys and seconds PROPORTIONAL_HOME_LIVE would hold from (dx, dy)."""
    keys = keys_towards(-dx, -dy)
    inside = ARRIVED_PIXELS - DEADZONE_PIXELS
    if abs(dx) <= inside:
        keys = keys.replace("a", "").replace("d", "")
    if abs(dy) <= inside:
        keys = keys.replace("w", "").replace("s", "")
    seconds = []
    if set(keys) & set("ad"):
        seconds.append(_proportional(held, abs(dx), _axis_rate(last, 1, keys)))
    if set(keys) & set("ws"):
        seconds.append(_proportional(held, abs(dy), _axis_rate(last, 2, keys)))
    # the far axis sets the hold: under-walking it costs a look, over-walking
    # the near one is what the dropped key above prevents inside the box
    return keys, max(seconds, default=held)


def _chain_target(tracker, ax: float, ay: float, clock):
    """CHAIN_LIVE's next token: the nearest confirmed track the latest look
    matched, beyond ARRIVED_PIXELS (the one just walked onto) and within
    CHAIN_PX of the character. None when there is none or no tracker.
    Before CHAIN_LIVE is built: this measures from the character only, with
    no odometer or field bound, so chained steps would drift further from
    home each time -- the live walk must also keep the token within the
    chase radius of home."""
    if tracker is None:
        return None
    try:
        now = clock()
        near = [(math.hypot(t.x - ax, t.y - ay), t) for t in tracker.confirmed(now)
                if t.unseen_for(now) <= CHAIN_SEEN_S]
    except Exception:
        return None
    near = [(d, t) for d, t in near if ARRIVED_PIXELS < d <= CHAIN_PX]
    return min(near, key=lambda r: r[0])[1] if near else None


def _record_leg(result: ChaseResult, keys: str, hold, seconds: float = STEP_SECONDS) -> bool:
    """Keep a held step in `result.legs` for a walk back by reversal -- unless
    the ground read it as moving nothing (act/motion.stuck): False then.

    A STEP THAT MOVED NOTHING IS NOT WALKED BACK. Reversed, a step that leaned
    on a wall is not blocked -- nothing stands behind the character -- so it
    becomes a free step AWAY from the wall. MEASURED 2026-10-12 23:52:57
    (var/night/run-937.log; var/incidents/20261012-235307-mob-sighting): the
    walk home "gave up homing by sight after 24 looks, still +16, +174 px
    out", the last of them "w" into a green wall at 1.7, 1.8 and 0.9 px a
    frame on 55-118 tracked points (frames 001-015); the reversal of its 25
    legs then walked freely (15-94 px a frame wherever measured) from frame
    016 to 23:53:06, out of Bamboo into Blue Flower (23:53:09). All 10 walks
    home of runs 940-979 that gave up after 24 looks reversed for 9-10 s;
    after them the character was off the flowers (run-941 01:59:14, the walk
    home then into Cactus and a rejoin), in Cactus (run-967 15:28:20), and
    with the pollen flat from 22:09:19 to the shop counter and a rejoin
    (run-977). A step the flow could not measure is kept: under a pine tree's
    crown it walked."""
    if motion.stuck(hold):
        return False
    # THE SECONDS ACTUALLY HELD (`seconds`), not STEP_SECONDS: under Haste a
    # step is held STEP_SECONDS / factor (`_step_seconds`), and the walk back
    # held each reversed leg the full 0.35 s -- up to 4x the step it undoes
    # (research 2026-10-21: the 199 reversals after a failed walk home).
    result.legs.append((keys, float(seconds)))
    return True


def _keep(carry, dx: float, dy: float) -> None:
    """Write a walk home's leftover into `carry`, clamped (CARRY_MAX_PX)."""
    if carry is not None:
        carry[0] = max(-CARRY_MAX_PX, min(CARRY_MAX_PX, float(dx)))
        carry[1] = max(-CARRY_MAX_PX, min(CARRY_MAX_PX, float(dy)))


def _walk_back(result: ChaseResult, vin, sleep, note) -> None:
    """Undo the detour, last leg first.

    Reversed in order rather than summed into one hold, because two legs of
    `w` and `wd` do not add up to a single straight line back.
    """
    for keys, seconds in reversed(result.legs):
        try:
            with vin.held(*_reverse(keys)):
                sleep(seconds)
        except Exception as exc:
            note(f"could not walk the detour back: {exc}")
            return


def _grab(frames, note):
    try:
        return frames()
    except Exception as exc:
        note(f"capture failed during a chase: {exc}")
        return None


def wanted(settings) -> tuple[bool, float]:
    """Does the owner want tokens chased, and how far? `(on, radius_studs)`.

    Defaults to OFF when the settings cannot be read. Chasing moves the
    character off a recorded pattern, and the safe reading of a broken config
    is the behaviour that does not move.
    """
    if settings is None:
        return False, 45.0
    try:
        return bool(settings.bool("gather.chase_tokens")), \
            float(settings.int("gather.token_radius"))
    except Exception:
        return False, 45.0
