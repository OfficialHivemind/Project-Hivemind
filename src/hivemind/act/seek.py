"""Walking until the game's own prompt says we have arrived.

THE PROBLEM THIS SOLVES. A recorded route is a list of timed key holds, and it
lands where it lands: a few studs short, a few studs long, against a wall if
the start pose was off. Until 2026-09-21 the bot then pressed E wherever it had
stopped. `nav/journey` now refuses to do that -- but refusing is not arriving,
and the owner's question stands: "how to get the wherever it wants to go".

THE ANSWER IS ALREADY IN THE GAME. Every place worth pressing E at announces
itself on the top-centre panel when the character is close enough: "Fire the
Red Cannon", "Open Shop", "Make Honey". So arrival can be a SEARCH rather than
a hope: walk a short step, read the panel, and stop the moment it names the
place we want. `act/hive.find_my_hive` has done exactly this for the hive pad
since the first night -- a widening box, a panel read after every step. This
module is that routine made general, for any landmark in
`data/knowledge/landmarks.yaml`.

WHAT IT MEANS FOR THE ROUTES. A route no longer has to be perfect; it has to
be CLOSE. The last few studs are closed by looking, which is the difference
between a recording that works from one exact start pose and one that works
from anywhere within a box of it.

WHAT IT REFUSES TO DO. It presses movement and camera keys only. It never
presses E, because finding a place and using it are different decisions and
the second one belongs to whoever asked for the search. It reports every
panel text it saw along the way, so a search that found "Open Shop" while
looking for the cannon has told you something true about where you are.

It ends 180 degrees from where it started if it walks the whole box (two taps
per leg, six legs), and it SAYS SO in `taps`, because a camera turned and not
counted is the fault this project spent today removing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

# One full turn is 8 taps (MEASURED by closure, act/orient); a quarter is 2.
QUARTER_TURN_TAPS = 2
LOOK_SETTLE = 0.35

# The default box: legs of 1, 2, 3, 4 steps -- ten seconds of walking in all.
# Small on purpose. This closes the last few studs of a route that nearly
# landed; it is not a way of finding a place from the other side of the map.
LEGS = 4
FIRST_LEG = 1
WALK_STEP_SECONDS = 1.0


@dataclass
class Seek:
    """What the search established. `found` is the only claim of arrival."""
    place: str
    found: bool = False
    steps: int = 0
    taps: int = 0                       # net camera taps, right positive
    seen: list = field(default_factory=list)   # every distinct panel text
    prompt: str = ""                    # the text that ended the search
    reason: str = ""

    def describe(self) -> str:
        if self.found:
            return (f"found the {self.place.replace('_', ' ')} after "
                    f"{self.steps} step(s) — panel read {self.prompt!r}")
        seen = f"; saw {', '.join(repr(s) for s in self.seen[:4])}" if self.seen else ""
        return (f"did not find the {self.place.replace('_', ' ')} in "
                f"{self.steps} step(s){seen} — {self.reason}")


def seek(vin, frames, read_panel, table, place: str, *,
         legs: int = LEGS, first_leg: int = FIRST_LEG,
         walk_step_seconds: float = WALK_STEP_SECONDS,
         sleep=time.sleep, on_note=None, stopped=None) -> Seek:
    """Box-search for `place`, reading the panel after every step.

    `table` is a `vision.landmarks.Table`; `read_panel(frame)` returns the
    panel text, "" for none, None if it could not look. Returns as soon as the
    panel names `place`. Presses no key but W and the camera.
    """
    note = on_note or (lambda text: None)
    halt = stopped or (lambda: False)
    out = Seek(place=place)

    def look() -> bool:
        try:
            frame = frames()
        except Exception as exc:
            note(f"capture failed ({exc}); carrying on")
            return False
        if frame is None:
            return False
        try:
            text = read_panel(frame)
        except Exception as exc:
            note(f"could not read the panel ({exc}); carrying on")
            return False
        if text is None:
            return False
        clean = " ".join(str(text).split())
        if clean and clean not in out.seen:
            out.seen.append(clean)
        mark = table.match(clean)
        if mark is not None and mark.place == place:
            out.prompt = clean
            return True
        return False

    # Where we already stand, first. A route that landed should cost nothing.
    if look():
        out.found = True
        note(f"already at the {place.replace('_', ' ')}")
        return out

    try:
        for leg in range(legs):
            for _ in range(first_leg + leg):
                if halt():
                    out.reason = "stop requested"
                    return out
                with vin.held("w"):
                    sleep(walk_step_seconds)
                sleep(0.25)
                out.steps += 1
                if look():
                    out.found = True
                    note(f"found the {place.replace('_', ' ')} after "
                         f"{out.steps} step(s)")
                    return out
            for _ in range(QUARTER_TURN_TAPS):
                vin.tap("period")
                out.taps += 1
                sleep(LOOK_SETTLE)
            note(f"leg {leg + 1}/{legs} done ({out.steps} steps); turning")
    except Exception as exc:                  # a search must never end a run
        out.reason = f"the search stopped early: {exc}"
        return out
    finally:
        try:
            vin.release_all()
        except Exception:
            pass

    out.reason = (f"walked a {legs}-leg box without the panel ever naming it")
    return out
