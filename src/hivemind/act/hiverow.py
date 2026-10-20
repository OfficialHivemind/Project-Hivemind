"""Find our own pad along the hive row, the way Natro Macro does.

WHAT WAS WRONG, IN ONE PICTURE. The frames the route runner saves per leg
(var/routes/attempt-296, `natro_home_spider`) show the character standing
on the owner's own pad after leg 09 -- name on the plate, honeycomb wall
ahead, the "Make Honey" prompt matching its template at 0.839 on the next
frame -- and then walking 140 studs right to the ramp corner, because the
transpiled route kept only Natro's `default` branch. Natro never stops
there either: after every walk home it runs `nm_findHiveSlot()`, and this
module is that routine in this project's terms.

NATRO'S ROUTINE (natro_macro.ahk, nm_findHiveSlot, GPLv3, read 2026-09-23):

    if not at the hive:
        hold Left for up to 15 s, polling the hive prompt; release on sight
    up to 10 times:
        wait 0.5 s; if the prompt is showing, convert
        else walk 1.5 tiles Right (the character overran the pad)

No slot arithmetic anywhere. The ramp is a corner, every hive is to the
left of it in spawn heading, and the prompt is the stop signal. That is
what makes it work from the general path's end whatever slot is owned.

WHAT IS OURS. Natro always arrives from the ramp, so Left is always right.
We may also arrive from `case 3` -- already on pad 3 but a stud off -- so
after the leftward hold fails there is a rightward one, twice as long, to
cover having started left of the pad. Both are bounded, both release the
key the instant the prompt shows, and the whole thing is cheaper than the
rejoin it replaces (75 s, and it resets the Wealth Clock streak the owner
wants kept: "rejoining is slow and also it resets wealth clock").

WHAT IT PRESSES: a and d, held; nothing else. The prompt is READ, never
pressed here -- converting is `brain/farm._convert`'s decision.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

# Natro's numbers, cited from nm_findHiveSlot rather than invented.
HOLD_SECONDS = 15.0          # 150,000,000 x 100 ns of holding Left
SETTLE_SECONDS = 0.5         # Sleep 500 before each confirmation look
OVERRUN_TILES = 1.5          # nm_Walk(1.5, RightKey) when the prompt is gone
CONFIRM_TRIES = 10           # Loop 10
STUDS_PER_TILE = 4.0         # lib/Walk.ahk: "4 studs in a tile"
# Ours: the way back, for a start left of the pad. Twice the first hold so
# it can cover the ground the first hold walked and as much again.
BACK_HOLD_SECONDS = 30.0
# How often the prompt is looked for while a key is down. A capture and a
# banded template match cost a few milliseconds; ten looks a second is well
# inside that and stops within a few studs of the prompt appearing.
POLL_SECONDS = 0.1

TOWARD_HIVES = "a"           # left of the ramp, in spawn heading
TOWARD_RAMP = "d"
OPPOSITE = {"a": "d", "d": "a", "w": "s", "s": "w"}
OPPOSITE_NAME = {"a": "left", "d": "right", "w": "forward", "s": "back"}
# FROM THE SPAWN POINT ONTO THE PAD. A respawn lands on the slabs in front
# of the hive row with the owner's pad straight ahead (act/respawn, the frame
# from 19:49:52), and Natro's five tiles forward do not reach the row on
# this account: the route out then walks the slabs to the FOOT of the ramp
# and ten cannon hops find nothing (var/routes/attempt-324, 19:49:57). So
# the pad is walked onto by looking, the way the row is searched: hold
# forward until the prompt shows. The whole hive area is a few tiles deep,
# so eight seconds is a bound and not an estimate.
PAD_AHEAD_SECONDS = 8.0
# W2: each side of a pass along the row from the face, and how much nearer the
# hives the second pass walks (see `search_from_the_face`)
ROW_SIDE_SECONDS = 6.0
ROW_SECOND_PASS_TILES = 1.0
# NATRO'S SEARCH LINE, 4.2 TILES OUT FROM THE HIVE FACES. Natro never walks
# the row pressed against the hives: its walks home press a hive face
# ("walk towards hives"), step back 1.5 tiles "to avoid thicker hives", walk
# right to the ramp along that line, step back 2.7 more to "center with hive
# pads", and only then does nm_findHiveSlot hold Left (the `default` branch
# of wf-mushroom.ahk, wf-spider.ahk, wf-strawberry.ahk and wf-pinetree.ahk;
# the whole of wf-sunflower.ahk's and wf-dandelion.ahk's endings). MEASURED
# why it matters here (DESIGN 8dx): since attempt 340 run_farm's row search
# held forward "to the hive" and then searched from wherever that ended 13
# times (var/night, attempts 347-446), and found the pad once -- run-351 at
# 04:17:30, 9.9 s into the right hold, from the spawn point after a death --
# and never from where a walk home had ended: the sideways hold runs into
# the walls between hive structures (var/homing/attempt-437, looks 04-07: wedged
# against a hive's side at 96,000-112,000 px of wall), and attempt 432's
# walk home from Sunflower, which ended ON hive 1's pad at the ramp corner
# exactly where nm_findHiveSlot starts (`070933-...-10-walk-s10.jpg`), was
# walked forward into the face and searched 15 s left and 30 s right there.
ROW_LINE_TILES = 1.5 + 2.7


@dataclass
class RowResult:
    """What the search did. `ok` means the prompt is showing right now."""
    ok: bool = False
    already: bool = False          # the prompt was up before anything moved
    direction: str = ""            # "left" / "right" / "forward": the hold that saw it
    key: str = ""                  # the key that hold pressed
    seen_after: float = 0.0        # seconds into that hold
    corrections: int = 0           # overrun steps walked back
    reason: str = ""
    notes: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if self.ok and self.already:
            return "on the pad already — the prompt was showing"
        if self.ok:
            fix = (f", then {self.corrections} step(s) back for the overrun"
                   if self.corrections else "")
            return (f"found the pad holding {self.direction} for "
                    f"{self.seen_after:.1f}s{fix}")
        return f"did not find the pad along the row — {self.reason}"


def _keys(key) -> tuple:
    """A hold's key as the keys to press together: "w" or ("w", "a")."""
    return tuple(key) if isinstance(key, (tuple, list)) else (key,)


def _opposite(key):
    """The key(s) that walk a hold back: "a" -> "d", ("w", "a") -> ("s", "d")."""
    if isinstance(key, (tuple, list)):
        return tuple(OPPOSITE.get(k, k) for k in key)
    return OPPOSITE.get(key, TOWARD_RAMP)


def _name(key) -> str:
    """"left", or "forward and left" for ("w", "a")."""
    return " and ".join(OPPOSITE_NAME.get(k, k) for k in _keys(key))


def find_along_row(vin, frames, at_hive, *, walkspeed: float,
                   hold_seconds: float = HOLD_SECONDS,
                   back_hold_seconds: float = BACK_HOLD_SECONDS,
                   poll: float = POLL_SECONDS,
                   settle: float = SETTLE_SECONDS,
                   overrun_tiles: float = OVERRUN_TILES,
                   tries: int = CONFIRM_TRIES,
                   stopped=None, sleep=time.sleep, clock=time.monotonic,
                   on_note=None, holds=None,
                   overrun: str = "steps") -> RowResult:
    """Walk along the hive row until `at_hive(frame)` says we are on our pad.

    `frames()` captures a frame; `at_hive(frame)` is the cheap prompt test
    (vision/screenstate.make_honey_present). `walkspeed` is studs per
    second, for timing the overrun step. `stopped()` ends the search early
    with the key released.

    `holds` is the sequence of `(key, name, seconds)` to try in order; the
    default is Natro's -- left along the row, then our rightward hold. A
    hold's `key` may be a tuple of keys held together (("w", "a") pushes into
    a wall while sliding along it), or a STEER: a callable given every frame
    looked at that returns the key(s) to hold until the next look, or None to
    end the hold, with its `reason` saying why (act/beacon). The overrun is
    always walked back with the opposite key(s) of the hold that saw the
    prompt -- for a steer, of the keys it was holding.
    """
    note = on_note or (lambda text: None)
    halt = stopped or (lambda: False)
    out = RowResult()

    def showing() -> bool:
        try:
            frame = frames()
        except Exception:
            return False
        if frame is None:
            return False
        try:
            return bool(at_hive(frame))
        except Exception:
            return False

    if showing():
        out.ok = out.already = True
        out.reason = ""
        return out

    def hold_until_seen(key: str, seconds: float) -> float | None:
        """Hold `key`, looking every `poll`; the seconds held when the prompt
        appeared, or None when the time ran out (or a stop was asked for)."""
        began = clock()
        # THE OWNER'S PAUSE AND TAKE OVER reach a 15 s hold here, as they do
        # a route's (brain/controls.GuardedInput.hold_point): the key comes
        # up while they have the controls, and a Take Over ends the search.
        point = getattr(vin, "hold_point", None)
        with vin.held(*_keys(key)):
            while True:
                if halt():
                    out.notes.append("stop requested during the search")
                    return None
                elapsed = clock() - began
                if elapsed >= seconds:
                    return None
                sleep(min(poll, seconds - elapsed))
                held = point() if callable(point) else 0.0
                if held is None:
                    out.notes.append("the owner took the controls during the search")
                    return None
                if isinstance(held, (int, float)) and held > 0:
                    began += held
                    continue
                if showing():
                    return clock() - began

    steered = {"keys": (), "held": 0.0}

    def steer_until_seen(steer, seconds: float) -> float | None:
        """`hold_until_seen` for a steer: one frame per look, given to both
        the prompt test and the steer, and the keys it asks for pressed and
        released as they change. Nothing is held before the first look."""
        began = clock()
        point = getattr(vin, "hold_point", None)
        down: tuple = ()
        steered["keys"], steered["held"] = (), 0.0
        try:
            while True:
                if halt():
                    out.notes.append("stop requested during the search")
                    return None
                elapsed = clock() - began
                steered["held"] = elapsed
                if elapsed >= seconds:
                    return None
                try:
                    frame = frames()
                except Exception:
                    frame = None
                if frame is not None:
                    try:
                        if at_hive(frame):
                            return elapsed
                    except Exception:
                        pass
                want = steer(frame)
                if want is None:
                    return None
                want = _keys(want)
                up = tuple(k for k in down if k not in want)
                new = tuple(k for k in want if k not in down)
                if up:
                    vin.release(*up)
                if new:
                    vin.press(*new)
                down = want
                if want:
                    steered["keys"] = want
                sleep(min(poll, seconds - elapsed))
                held = point() if callable(point) else 0.0
                if held is None:
                    out.notes.append("the owner took the controls during the search")
                    return None
                if isinstance(held, (int, float)) and held > 0:
                    began += held
        finally:
            if down:
                vin.release(*down)

    if holds is None:
        holds = ((TOWARD_HIVES, "left", hold_seconds),
                 (TOWARD_RAMP, "right", back_hold_seconds))
    for key, way, seconds in holds:
        if callable(key):
            seen = steer_until_seen(key, seconds)
            if seen is not None:
                out.direction, out.seen_after = way, seen
                out.key = steered["keys"] or ("w",)
                note(f"the hive prompt appeared after {seen:.1f}s holding {way}")
                break
            why = str(getattr(key, "reason", "") or "the time ran out")
            note(f"held {way} for {steered['held']:.1f}s without the hive "
                 f"prompt — {why}")
            if halt():
                out.reason = "stop requested"
                return out
            continue
        seen = hold_until_seen(key, seconds)
        if seen is not None:
            out.direction, out.seen_after, out.key = way, seen, key
            note(f"the hive prompt appeared after {seen:.1f}s holding {way}")
            break
        note(f"held {way} for {seconds:.0f}s without the hive prompt")
        if halt():
            out.reason = "stop requested"
            return out
    else:
        out.reason = ("held " + " and ".join(f"{way} {seconds:.0f}s" for _, way, seconds in holds)
                      + " without the prompt appearing")
        return out

    # THE OVERRUN. The key comes up a poll after the prompt shows, and the
    # character keeps sliding, so the prompt can be gone again by the time
    # anything looks. Natro steps back 1.5 tiles and looks again, ten times.
    back = _opposite(out.key)
    step_seconds = (overrun_tiles * STUDS_PER_TILE) / max(1e-6, float(walkspeed))
    # `overrun="hold"`: THE WAY BACK IS WATCHED THE WHOLE WAY, as the hold
    # that saw the prompt was, instead of in Natro's 1.5-tile steps with a
    # look between. MEASURED 2026-09-27 03:19 (attempt 485): at the Brown Bear
    # "the prompt showed while holding left but was gone again after 10
    # step(s) back" -- 60 studs of steps that each moved 6 studs blind, past a
    # zone that is only a few studs wide where a line crosses it near its edge.
    # The pad's own row search keeps the steps, which it has closed with.
    if overrun == "hold":
        sleep(settle)
        if showing():
            out.ok = True
            return out
        back_seen = hold_until_seen(back, max(1, int(tries)) * step_seconds)
        out.corrections += 1
        sleep(settle)
        if showing():
            out.ok = True
            return out
        if back_seen is not None:
            # SEEN AGAIN ON THE WAY BACK, and slid past once more: a short
            # nudge the first way, still watched.
            hold_until_seen(out.key, min(0.5, step_seconds))
            out.corrections += 1
            sleep(settle)
            if showing():
                out.ok = True
                return out
        out.reason = (f"the prompt showed while holding {out.direction} but was "
                      f"gone again after holding {_name(back)} "
                      f"back to it, watching the whole way")
        return out
    for _ in range(max(1, int(tries))):
        sleep(settle)
        if showing():
            out.ok = True
            return out
        if halt():
            out.reason = "stop requested while correcting the overrun"
            return out
        with vin.held(*_keys(back)):
            sleep(step_seconds)
        out.corrections += 1
    sleep(settle)
    if showing():
        out.ok = True
        return out
    out.reason = (f"the prompt showed while holding {out.direction} but was gone "
                  f"again after {out.corrections} step(s) back")
    return out


def walk_onto_pad(vin, frames, at_hive, *, walkspeed: float,
                  seconds: float = PAD_AHEAD_SECONDS, **kw) -> RowResult:
    """From the spawn point, hold forward until the pad's prompt shows.

    The same closed loop as the row search with one hold, forward, because
    that is where a respawn puts the pad (act/respawn). Everything else --
    the release on sight, the overrun correction, the bound -- is
    `find_along_row`'s."""
    return find_along_row(vin, frames, at_hive, walkspeed=walkspeed,
                          holds=(("w", "forward", float(seconds)),), **kw)


def search_from_the_face(vin, frames, at_hive, *, walkspeed: float,
                         ahead_seconds: float = PAD_AHEAD_SECONDS,
                         line_tiles: float = ROW_LINE_TILES,
                         **kw) -> RowResult:
    """With a hive row ahead: onto its face, back to Natro's search line, then
    along the row (ROW_LINE_TILES).

    Three holds, each released the instant the prompt shows: forward for up
    to `ahead_seconds` (our own pad may be on the way, and a hive face stops
    the rest of it -- the face is the lean that fixes how far out we stand),
    back `line_tiles`, then `find_along_row`'s left-then-right. The result
    is the last hold's, with every hold's notes."""
    notes: list[str] = []
    ahead = walk_onto_pad(vin, frames, at_hive, walkspeed=walkspeed,
                          seconds=ahead_seconds, **kw)
    notes += ahead.notes
    if ahead.ok:
        return ahead
    halt = kw.get("stopped") or (lambda: False)
    if halt():
        ahead.reason = ahead.reason or "stop requested"
        return ahead
    back_seconds = (float(line_tiles) * STUDS_PER_TILE) / max(1e-6, float(walkspeed))
    back = find_along_row(vin, frames, at_hive, walkspeed=walkspeed,
                          holds=(("s", "back to the search line", back_seconds),),
                          **kw)
    notes += back.notes
    if back.ok or halt():
        back.notes = notes
        return back
    # TWO NARROW PASSES, NOT NATRO'S WHOLE ROW (W2). MEASURED over runs
    # 84x-87x: from the face the pad was found 30 of 40 times, 27 after ~2 s
    # left and every one within 5.x s; all 10 misses held left the full 15 s
    # and right 30 s and walked off the hives (2026-10-11 09:16 a rejoin). A
    # pass that misses within a few seconds of the face is at the wrong depth,
    # so the second pass is a tile nearer the hives, not further along.
    side = ROW_SIDE_SECONDS
    sweep = ((TOWARD_HIVES, "left", side), (TOWARD_RAMP, "right", 2 * side))
    row = find_along_row(vin, frames, at_hive, walkspeed=walkspeed, holds=sweep, **kw)
    notes += row.notes
    if not row.ok and not halt():
        tile_s = (ROW_SECOND_PASS_TILES * STUDS_PER_TILE) / max(1e-6, float(walkspeed))
        for holds in (((TOWARD_HIVES, "back to the face's line", side),),
                      (("w", "a tile nearer the hives", tile_s),), sweep):
            row = find_along_row(vin, frames, at_hive, walkspeed=walkspeed, holds=holds, **kw)
            notes += row.notes
            if row.ok or halt():
                break
    row.notes = notes
    if not row.ok:
        row.reason = (f"forward {ahead_seconds:.0f}s, back {line_tiles:g} tiles to "
                      f"Natro's search line, then two passes of {side:g} s each way "
                      f"a tile apart: {row.reason}")
    return row
