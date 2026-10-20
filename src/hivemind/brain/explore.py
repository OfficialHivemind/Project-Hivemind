"""Going out, looking around, and writing down what is where.

    ############################################################
    ##  SUPERSEDED. THE PLACE MODEL IN THIS FILE DOES NOT WORK.
    ############################################################

MEASURED 2026-09-20, against 82 frames the GAME labelled itself, across 12
fields and 3,321 pairs: the colour signature this class identifies places with
scored a worst same-field correlation of **+0.108** and a best different-field
correlation of **+0.972**. The two distributions overlap completely, so NO
threshold separates them -- including the 0.45 used below. A twenty-minute
session driven by the owner produced thirteen "places" whose notes all read
"standing on a hive pad", for fields that were Pumpkin, Bamboo and Mountain Top.

It also degrades as it runs: each Spot keeps up to eight signatures and matches
on the best of them, so every place grows to cover more of the space with every
visit until they all overlap.

USE INSTEAD:
    vision/whereami.Locator   where am I, from the game's own reward feed
    brain/fieldnotes          per-field records under the field's REAL name

This file is kept because `scripts/teach_map.py` still runs it and its walking
and pollen-tracking are sound. NOTHING NEW SHOULD IDENTIFY A PLACE WITH IT.
See docs/DESIGN.md 8b for the full measurement and what replaced it.


THE OWNER'S DIAGNOSIS, and it is the correct one: "honestly it just looks like
its going to random places, it doesnt feel like it has a clue where it is ever
even when it should know the map, it feels lit has no goals and doesnt
understand the game".

It has never known where it is. Not "loses track sometimes" -- there has never
been a moment when this bot could answer "where am I". Everything built so far
is a way of not needing to know:

    recorded routes   walk blind for N seconds and hope
    probe search      wander until a number moves
    the navigator     ask a model that cannot remember its last answer
    the knowledge base  what EXISTS, with nothing to attach it to

Knowing the map does not help when you cannot find yourself on it.

WHAT THIS FILE USED TO CLAIM, AND WHY IT WAS WRONG. It said `observe.signature`
"separates places cleanly: +0.99, +0.94 and +0.87 correlation between views of
the SAME place against +0.17 and +0.20 between different ones". Those numbers
were real and the conclusion was not: they came from a handful of frames where
the camera happened to point the same way. Measured properly -- see the banner
at the top -- same-place views fall to +0.108 and different-place views reach
+0.972. The descriptor encodes where the CAMERA is looking, not where the
player is standing.

The walking below is still sound, and so is crediting pollen to where it was
gathered. Only the identification of a place is broken.

SO THIS EXPLORES. It walks, it looks, it recognises places it has seen before,
and -- the part that matters -- it records WHETHER POLLEN ROSE while it stood
there. A place where pollen rises is a field. That is a fact the bot
established itself, about this account and this server, and it is worth more
than any route transpiled from someone else's recording.

THE RULES IT PLAYS BY

  * It never resets. A reset is a death and death empties the backpack.
  * It presses movement and camera keys only -- w, a, s, d, space, comma,
    period. Not `e`, not `escape`, not `enter`, not `r`. So no amount of
    wandering can open a menu, leave the server, or start a conversation with
    a bear.
  * It gives up on a direction rather than grinding into a wall: if the view
    stops changing, that is a wall, and the answer is to turn.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..telemetry.events import Thought
from .observe import SAME_PLACE, likeness, signature

# Movement only. This set is the safety boundary.
WALK_KEYS = ("w", "a", "d", "s")
TURN_KEY = "period"

STEP_SECONDS = 2.0        # far enough to change the view, short enough to undo
SETTLE = 0.45             # let the camera catch up before looking
STUCK_LIKENESS = 0.97     # the view did not change -> a wall
JUMP_EVERY = 3            # steps; clears low ledges the walk cannot

# How often to sample while someone else is driving. MEASURED: a signature
# costs 1.07 ms and a HUD read 22.8 ms, so five samples a second is about a
# tenth of one core and misses nothing a walking player passes.
WATCH_INTERVAL = 0.2


@dataclass
class Spot:
    """A place the bot found, and what it learned standing there."""
    name: str
    signatures: list = field(default_factory=list)
    visits: int = 0
    pollen_gained: int = 0
    seconds_spent: float = 0.0
    notes: list[str] = field(default_factory=list)

    def score(self, sig) -> float:
        return max((likeness(sig, known) for known in self.signatures),
                   default=-1.0)

    @property
    def pays(self) -> bool:
        """Did pollen actually rise here? The only test that matters."""
        return self.pollen_gained > 0

    @property
    def rate(self) -> float:
        return self.pollen_gained / self.seconds_spent if self.seconds_spent else 0.0

    def describe(self) -> str:
        what = (f"{self.pollen_gained:,} pollen in {self.seconds_spent:.0f}s "
                f"({self.rate:.0f}/s)" if self.pays else "nothing grows here")
        note = f" — {self.notes[0]}" if self.notes else ""
        return f"{self.name}: {what}{note}"


class Explorer:
    """Walks the world and builds a map of places that pay.

    Everything is injected: `frames()` for the screen, `pollen()` for the HUD,
    `describe(frame)` for an optional sentence from the vision model.
    """

    def __init__(self, vin, frames, pollen, describe=None, emit=None,
                 step_seconds: float = STEP_SECONDS, sleep=time.sleep,
                 clock=time.monotonic, rng=None):
        import random
        self.vin = vin
        self.frames = frames
        self.pollen = pollen
        self.describe_frame = describe
        self.emit = emit or (lambda event: None)
        self.step_seconds = float(step_seconds)
        self.sleep = sleep
        self.clock = clock
        self.rng = rng or random.Random()
        self.spots: list[Spot] = []
        self.steps = 0
        self.walls = 0
        self._last_sig = None

    # ---- places -----------------------------------------------------------
    def spot_for(self, sig) -> Spot:
        best, best_score = None, SAME_PLACE
        for spot in self.spots:
            score = spot.score(sig)
            if score >= best_score:
                best, best_score = spot, score
        if best is not None:
            if best.score(sig) < 0.85 and len(best.signatures) < 8:
                best.signatures.append(sig)
            return best
        spot = Spot(name=f"spot_{len(self.spots) + 1}")
        spot.signatures.append(sig)
        self.spots.append(spot)
        return spot

    def _reading(self) -> int | None:
        try:
            reading = self.pollen()
        except Exception:
            return None
        value = getattr(reading, "value", None)
        return int(value) if value is not None else None

    # ---- moving -----------------------------------------------------------
    def _look(self):
        frame = self.frames()
        return (None, None) if frame is None else (frame, signature(frame))

    def step(self, key: str) -> bool:
        """Walk one step and record what is there. False if it hit a wall."""
        with self.vin.held(key):
            self.sleep(self.step_seconds)
        self.sleep(SETTLE)
        self.steps += 1
        if self.steps % JUMP_EVERY == 0:
            self.vin.tap("space")
            self.sleep(0.35)

        before = self._reading()
        frame, sig = self._look()
        if sig is None:
            return True                  # cannot see; not a wall

        if self._last_sig is not None and likeness(sig, self._last_sig) > STUCK_LIKENESS:
            self.walls += 1
            self._last_sig = sig
            return False                 # the view did not change: a wall
        self._last_sig = sig

        spot = self.spot_for(sig)
        spot.visits += 1

        # Stand still long enough to find out whether anything grows here.
        # This is the whole point of the walk: a place where pollen rises is
        # a field, and that is a fact about THIS account and THIS server.
        started = self.clock()
        self.sleep(self.step_seconds)
        after = self._reading()
        spot.seconds_spent += self.clock() - started
        if before is not None and after is not None and after > before:
            spot.pollen_gained += after - before

        if self.describe_frame is not None and not spot.notes and frame is not None:
            try:
                said = self.describe_frame(frame)
                if said:
                    spot.notes.append(" ".join(str(said).split())[:160])
            except Exception:
                pass
        return True

    def turn(self) -> None:
        self.vin.tap(TURN_KEY)
        self.sleep(0.4)

    def watch(self, seconds: float, on_place=None) -> list[Spot]:
        """Map WITHOUT driving: someone else is moving the character.

        THE OWNER ASKED WHETHER HIS WALKING WOULD HELP. It is worth far more
        than the bot's: this class wanders at random two seconds at a time,
        hoping to bump into something, while he knows where the fields are.
        Twenty minutes of a person walking maps more of the world than an
        hour of that.

        The only difference from `explore` is that nothing here presses a
        key. Places are recognised the same way, "does pollen rise here" is
        answered the same way, and the map it writes is the same map -- so a
        walk of his and a wander of the bot's accumulate into one thing.
        """
        until = self.clock() + seconds
        last_spot = None
        last_pollen = None
        last_at = self.clock()
        while self.clock() < until:
            frame, sig = self._look()
            if sig is None:
                self.sleep(WATCH_INTERVAL)
                continue
            now = self.clock()
            reading = self._reading()
            spot = self.spot_for(sig)
            spot.visits += 1

            # POLLEN IS TRACKED ACROSS SAMPLES, NOT BY STANDING STILL.
            #
            # The first version read pollen, slept a whole second, read it
            # again, and credited the difference. MEASURED, that sleep was
            # 97% of the loop -- `signature()` costs 1.07 ms and a HUD read
            # 22.8 ms -- so the mapper spent nearly all its time waiting on
            # purpose while the owner walked past things it never sampled.
            #
            # Comparing against the PREVIOUS sample measures exactly the same
            # thing, credits it to the place the player was actually in at
            # the time, and leaves no gaps between samples.
            if (last_spot is not None and last_pollen is not None
                    and reading is not None and reading > last_pollen):
                last_spot.pollen_gained += reading - last_pollen
            if last_spot is not None:
                last_spot.seconds_spent += now - last_at

            # The model's sentence is worth having and costs seconds, so it
            # happens off the loop. A description arriving late is fine; a
            # mapper that stops scanning to wait for one is not.
            if (self.describe_frame is not None and not spot.notes
                    and frame is not None):
                self._describe_later(spot, frame)

            if spot is not last_spot:
                if on_place is not None:
                    on_place(spot)
                self.emit(Thought(topic="explore",
                                  text=f"{spot.name}: {spot.describe()}"))
            last_spot, last_pollen, last_at = spot, reading, now
            self.sleep(WATCH_INTERVAL)
        return self.paying()

    def _describe_later(self, spot, frame) -> None:
        """Ask the model what this place is, without blocking the scan."""
        import threading
        spot.notes.append("...")          # claim the slot so it is asked once

        def work():
            try:
                said = self.describe_frame(frame)
            except Exception:
                said = None
            if said:
                spot.notes[0] = " ".join(str(said).split())[:160]
            elif spot.notes and spot.notes[0] == "...":
                spot.notes.clear()        # let a later sample try again
        threading.Thread(target=work, daemon=True,
                         name="hivemind-describe").start()

    def explore(self, steps: int = 40) -> list[Spot]:
        """Wander for a while and come back with a map."""
        try:
            for _ in range(max(1, steps)):
                key = self.rng.choice(WALK_KEYS)
                if not self.step(key):
                    self.turn()          # walled in: look somewhere else
                    continue
                spot = self.spots[-1] if self.spots else None
                if spot is not None and spot.visits == 1:
                    self.emit(Thought(topic="explore",
                                      text=f"found {spot.name}",
                                      detail=spot.notes[0] if spot.notes else ""))
        finally:
            self.vin.release_all()
        return self.paying()

    def paying(self) -> list[Spot]:
        """Places where pollen actually rose, best first."""
        return sorted((s for s in self.spots if s.pays),
                      key=lambda s: -s.rate)

    # ---- remembering across sessions --------------------------------------
    def save(self, path) -> object:
        """Write the map out. Learning that does not survive is not learning.

        THE OWNER'S POINT: "like its gotta learn". A bot that explores, finds
        a field, and forgets it when the process ends has not learned
        anything -- it has had an experience. The signatures are what make a
        place recognisable next time, so they are what gets saved.
        """
        import json
        from pathlib import Path
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "spots": [
                {"name": s.name, "visits": s.visits,
                 "pollen_gained": s.pollen_gained,
                 "seconds_spent": round(s.seconds_spent, 1),
                 "notes": s.notes,
                 "signatures": [[round(float(v), 5) for v in sig]
                                for sig in s.signatures]}
                for s in self.spots
            ],
            "steps": self.steps,
            "walls": self.walls,
        }, indent=1))
        return path

    def load(self, path) -> int:
        """Read a map back. Returns how many places were remembered.

        A place remembered from a previous session is worth more than one
        found again from scratch: it already carries whether pollen rose
        there, which costs twenty seconds of standing still to establish.
        """
        import json
        import numpy as np
        from pathlib import Path
        path = Path(path)
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return 0
        before = len(self.spots)
        for entry in data.get("spots", []):
            spot = Spot(name=entry.get("name", f"spot_{len(self.spots) + 1}"),
                        visits=int(entry.get("visits", 0)),
                        pollen_gained=int(entry.get("pollen_gained", 0)),
                        seconds_spent=float(entry.get("seconds_spent", 0.0)),
                        notes=list(entry.get("notes", [])))
            spot.signatures = [np.asarray(sig, dtype="float32")
                               for sig in entry.get("signatures", [])]
            if spot.signatures:
                self.spots.append(spot)
        return len(self.spots) - before

    def recognise(self, frame):
        """Which known place is this? None when it is somewhere new.

        This is the thing the bot has never had: an answer to "where am I".
        """
        if frame is None:
            return None
        try:
            sig = signature(frame)
        except Exception:
            return None
        best, best_score = None, SAME_PLACE
        for spot in self.spots:
            score = spot.score(sig)
            if score >= best_score:
                best, best_score = spot, score
        return best

    def describe(self) -> str:
        pays = self.paying()
        return (f"{len(self.spots)} places over {self.steps} steps, "
                f"{len(pays)} of them paying"
                + (f"; best {pays[0].describe()}" if pays else "")
                + (f", {self.walls} walls" if self.walls else ""))
