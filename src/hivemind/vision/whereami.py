"""Where the bot is, answered by the game rather than guessed at.

THE OWNER'S DIAGNOSIS, and everything here follows from it: it looked like it
went to random places, with no clue where it was even when it should know the
map. It never did. docs/DESIGN.md 8b
records the measurement that killed the old answer -- whole-screen colour
signatures scored -0.042 between two views of the SAME place and +0.803 between
DIFFERENT ones, against a threshold of 0.450, so no threshold could ever work.

THE NEW ANSWER IS THE GAME'S OWN TEXT. They found it themselves, saying they
was in Pumpkin while the frame in front of us read:

    +590 Honey (from Pumpkin Patch)

That is not an inference. It is the game naming the field.

WHAT THIS IS HONEST ABOUT. Their next message was the important one: "when i go
over a honey token". The feed fires on PICKUP. MEASURED, 4 of 24 frames named a
field -- an anchor roughly every nine seconds while farming and NOTHING while
walking between fields. So this class reports a fix when it has one and says
`None` when it does not. It never interpolates, never assumes the field has not
changed, and a fix goes stale on a timer.

That is a smaller claim than "I know where I am", and it is the first true one
this project has been able to make.

WHAT IT UNLOCKS FIRST. `arrived()`. Every recorded route so far ends by
assuming it got there, which is why the bot has farmed the red cannon, walked
into the ticket shop and talked to a bear. Reading Natro Macro (8c) showed it
does not confirm arrival either, so this is ahead of the field rather than
catching up.

THE GATE IS NOT OPTIONAL. Asked to transcribe a crop with no pills in it, the
model invented "claim hive" in 11 of 24 frames. `feed.rows` decides whether
there is anything to read, and nothing is sent to a reader unless there is.
"""
from __future__ import annotations

import difflib
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from . import feed

HISTORY_KEPT = 64

# How long a fix is worth believing. The owner walks between fields in well
# under a minute, so a fix older than this may be describing the field before
# last. Deliberately shorter than a typical field-to-field trip.
STALE_AFTER = 45.0

# "(from Pumpkin Patch)" -- the closing bracket matters, because it is what
# separates a source from the rest of the sentence. THE F MAY BE MISSING:
# tesseract (vision/feed.read_text) reads "(from" as "rom" when the bracket
# swallows the f -- 3 of the 4 credits it missed against the vision model on
# 40 strips of 2026-10-01 were "rom Pine Tree Forest)" or "rom Pumpkin
# Patch)". Only a KNOWN field's name is ever accepted (`field_in`).
FROM = re.compile(r"f?rom\s+([A-Za-z][A-Za-z '-]{2,30})\)", re.I)

# Sources the feed names that are not places to stand. Kept as a note rather
# than a filter: the real filter is that a name must be a KNOWN field.
NOT_PLACES = ("puffshroom", "festive gift", "rhino beetle", "gummy bear")

# WHAT A FIELD IS CALLED AT THE END. Not one word, which is what the first
# version of this assumed and why "Pumpkin Patch" resolved to nothing while
# "Mountain Top Field" worked. The game says Field, Patch and Forest, and the
# knowledge base stores none of them -- `pumpkin`, not `pumpkin_patch`.
SUFFIXES = ("field", "patch", "forest", "grove")

# A MOB THAT SHARES A FIELD'S NAME: "+1,418 Honey (from Spider)" is a Spider's
# kill, and was taken for "in the spider field" beside the Bamboo Field
# (MEASURED 2026-10-05 23:50, var/bears/panda_bear-look8-235044.jpg). The game
# names a field with its Field, Patch or Forest, so bare, it is the mob.
BARE_MOBS = ("spider",)


@dataclass(frozen=True)
class Fix:
    """A moment when the game said where we were."""
    field: str
    at: float
    source: str = "feed"
    text: str = ""

    def age(self, now: float) -> float:
        return max(0.0, now - self.at)

    def fresh(self, now: float, stale_after: float = STALE_AFTER) -> bool:
        return self.age(now) < stale_after

    def describe(self, now: float | None = None) -> str:
        pretty = self.field.replace("_", " ")
        if now is None:
            return f"in the {pretty} field ({self.source})"
        return f"in the {pretty} field, {self.age(now):.0f}s ago ({self.source})"


def field_names(world: str | Path) -> dict[str, str]:
    """{spoken name: slug} for every field the knowledge base knows about."""
    import yaml
    try:
        data = yaml.safe_load(Path(world).read_text()) or {}
    except (OSError, ValueError):
        return {}
    return {slug.replace("_", " ").lower(): slug
            for slug in (data.get("fields") or {})}


def field_in(text: str, known: dict[str, str]) -> str | None:
    """The field named in this feed text, or None.

    Only names the knowledge base knows are accepted, which is what keeps
    "from Puffshroom" out without needing a list of everything it is not.
    """
    for raw in FROM.findall(text or ""):
        name = " ".join(str(raw).split()).lower().strip()
        bare = True
        for suffix in SUFFIXES:
            if name.endswith(" " + suffix):
                name = name[: -len(suffix)].strip()
                bare = False
                break
        if bare and name in BARE_MOBS:
            continue
        slug = known.get(name) or _near_field(raw, known)
        if slug:
            return slug
    return None


# A FIELD NAME OCR SPLIT OR MISSPELT. MEASURED 2026-10-22 over 700 saved
# tesseract reads of natro_pattern_* frames (bamboo, pine tree, blue flower):
# "Bamboo F ield" x6 and "Fine Iree Forest" x2 named no field, 8 of the 112
# lines that named one. Spaces are dropped and the whole name, suffix and all,
# must be this close (difflib ratio) to one known field's: "fineireeforest"
# against "pinetreeforest" is 0.857, while the nearest mob line ("rhinobeetle")
# and a bare "spider" against "spiderfield" (0.71) stay out.
NEAR_FIELD = 0.85


def _near_field(raw: str, known: dict[str, str]) -> str | None:
    compact = "".join(str(raw).split()).lower()
    names = {name.replace(" ", "") + suffix: slug
             for name, slug in known.items() for suffix in SUFFIXES}
    best = difflib.get_close_matches(compact, names, n=1, cutoff=NEAR_FIELD)
    return names[best[0]] if best else None


# A FIELD BOOST, AS THE GAME ANNOUNCES IT. MEASURED 2026-10-02 over the frames
# kept after 104 booster presses (var/places/*-pressed-*.jpg): the reward feed
# says 'Activated "Blue Flower Field Boost" x 3', 'Activated "Pine Tree Forest
# Boost"' (one stack, no count), 'Activated "Pineapple Patch Boost" x 2' -- in
# straight or curly quotes, and tesseract once ran "Pine TreeForest" together.
BOOST = re.compile(r"activated\s*[\"\u201c\u201d']?\s*([A-Za-z][A-Za-z '-]{2,40}?)\s*boost"
                   r"\s*[\"\u201c\u201d']*\s*(?:x\s*(\d+))?", re.I)


def boost_in(text: str, known: dict[str, str]) -> tuple[str, int] | None:
    """(field, stacks) for a boost this feed text announces, or None. Only a
    field the knowledge base knows is accepted, as for `field_in`."""
    for match in BOOST.finditer(text or ""):
        name = " ".join(match.group(1).split()).lower().strip()
        for suffix in SUFFIXES:
            if name.endswith(" " + suffix):
                name = name[: -len(suffix)].strip()
                break
            if name.endswith(suffix) and name[: -len(suffix)].strip() in known:
                name = name[: -len(suffix)].strip()       # "pine treeforest"
                break
        slug = known.get(name)
        if slug:
            return slug, int(match.group(2) or 1)
    return None


class Locator:
    """Answers "where am I" when the game has said so, and None when it has not.

    `read_text(image) -> str` transcribes a crop. Anything can supply it -- the
    vision model today, a template matcher once names have been harvested -- and
    it is only ever called when `feed.rows` has already found pills.
    """

    def __init__(self, read_text, known: dict[str, str] | None = None,
                 world: str | Path | None = None, emit=None,
                 clock=time.monotonic, stale_after: float = STALE_AFTER,
                 on_text=None):
        self.read_text = read_text
        # EVERY FEED READ, RAW, FOR WHOEVER WANTS IT. The feed only appears
        # when the game credits something -- the owner named the trigger
        # themselves: going over a honey token -- so each read is a
        # timestamped fact that a token was just collected. That makes the
        # frames immediately BEFORE it labelled positives for a token
        # detector, which is the one thing this project has never had: 8a
        # records four separate attempts at finding tokens by colour and
        # shape, all of which returned flowers.
        #
        # This hook is how those labels get collected. It carries the text
        # whether or not a field name was found in it, because "+590 Honey"
        # with no field is still a token pickup.
        self.on_text = on_text or (lambda text: None)
        self.known = dict(known or ({} if world is None else field_names(world)))
        self.emit = emit or (lambda event: None)
        self.clock = clock
        self.stale_after = float(stale_after)
        self.last: Fix | None = None
        self.reads = 0
        self.skipped = 0
        # The newest fixes only: a list of every fix grew all night. `fixes`
        # is the count the description reports.
        self.history: deque = deque(maxlen=HISTORY_KEPT)
        self.fixes = 0

    # ---- looking ----------------------------------------------------------
    def look(self, frame) -> Fix | None:
        """Read the feed if there is one. Returns a NEW fix, or None.

        None means "the game did not say", not "somewhere else". Callers that
        want the last known position ask `where()`.
        """
        strip = feed.strip(frame) if frame is not None else None
        if strip is None:
            self.skipped += 1
            return None                     # the gate; see the module docstring
        self.reads += 1
        try:
            text = self.read_text(strip)
        except Exception:
            return None
        if text:
            try:
                self.on_text(text)
            except Exception:
                pass          # a dataset collector must never break the bot
        slug = field_in(text or "", self.known)
        if slug is None:
            return None
        fix = Fix(field=slug, at=self.clock(), source="feed",
                  text=" ".join(str(text).split())[:120])
        moved = self.last is None or self.last.field != slug
        self.last = fix
        self.history.append(fix)
        self.fixes += 1
        if moved:
            self._say(fix)
        return fix

    def where(self) -> Fix | None:
        """The last fix, if it is still worth believing."""
        if self.last is None:
            return None
        return self.last if self.last.fresh(self.clock(), self.stale_after) else None

    def arrived(self, expected: str, frame=None) -> bool:
        """Did we actually get to `expected`? The question routes never asked.

        False when the game has not said -- an unconfirmed arrival is not an
        arrival, and treating "no evidence" as "yes" is how the bot ended up
        farming the red cannon.
        """
        if frame is not None:
            self.look(frame)
        fix = self.where()
        return fix is not None and fix.field == expected

    def looks_like(self, look, trust: float) -> Fix | None:
        """WHICH FIELD AM I IN, BY SIGHT, when the game has not said.

        `look` is a vision/fieldsense Look of the current frame. Asked before
        the vision model's open "where is the player?" at the end of a walk
        out (nav/journey `sight`), because the model was MEASURED at 44% on
        which field (DESIGN 8b) and a look at 76 of 81 on walk-end frames of
        nights it had never seen, at the trust the trainer chose (DESIGN
        8dz). A fix with source "sight" -- never "feed" -- and only for a
        field the knowledge base knows: the hive and the landmarks are the
        panel's to name. None when the look is not that sure."""
        if look is None or trust is None:
            return None
        place = getattr(look, "field", None)
        if place not in set(self.known.values()):
            return None
        if not look.names(place, trust):
            return None
        return Fix(field=place, at=self.clock(), source="sight",
                   text=look.describe()[:120])

    def _say(self, fix: Fix) -> None:
        from ..telemetry.events import Thought
        self.emit(Thought(topic="where", text=f"I am {fix.describe()}",
                          detail=fix.text))

    def describe(self) -> str:
        fix = self.where()
        if fix is None:
            seen = f", {self.fixes} fixes so far" if self.history else ""
            return f"I do not know where I am{seen}"
        return f"I am {fix.describe(self.clock())}"


class Tracker:
    """Reads the feed from frames SOMEBODY ELSE ALREADY CAPTURED.

    THIS COST THE OWNER THEIR GAME, TWICE, AND IT IS WHY THE DESIGN CHANGED.

    The first version captured on its own thread every three seconds. MEASURED
    2026-09-20: two farm runs in a row ended with Sober exiting 48 s and 43 s
    after launch, each within seconds of the bot starting to act, each leaving
    a log that stops mid-line with no error, no OOM and no GPU fault -- and
    each showing Sober's exit screen, which is what a graceful shutdown looks
    like. A do-nothing control run survived three minutes untouched, and a farm
    run with this class switched off has now run well past the point both
    others died.

    A Wayland client whose compositor connection is dropped exits gracefully.
    That is the shape of the evidence, and the cause was this: a FOURTH
    concurrent screencopy client on the nested compositor. `teach_map`, which
    ran for twenty minutes without trouble the same afternoon, had two.

    So nothing here captures. `offer(frame)` is handed a frame the live view
    has already taken -- twenty a second, at no extra cost to anyone -- and
    throttles to one read every few seconds. The read itself still goes on a
    worker, because it costs about 1.7 s through the vision model and the live
    view must not wait for it.

    DEFAULT_EVERY is 3 s because a fix arrives roughly every 9 s while farming
    (MEASURED, 4 frames in 24) -- faster spends model time on feeds that have
    not changed, slower starts missing them.
    """

    DEFAULT_EVERY = 3.0

    def __init__(self, locator: "Locator", every: float = DEFAULT_EVERY,
                 on_fix=None, clock=time.monotonic):
        self.locator = locator
        self.every = max(0.5, float(every))
        self.on_fix = on_fix or (lambda fix, frame: None)
        self.clock = clock
        self.looks = 0
        self.offered = 0
        self.busy = False
        # None, not 0.0 -- with 0.0 the first offer computes `now - 0.0` and
        # is only ever taken because `time.monotonic()` happens to be large.
        # `brain/alive.WorldGuard` had the identical bug and a test caught it
        # there too, so this is a shape to watch for, not a one-off slip.
        self._last: float | None = None
        self._stop = False

    def offer(self, frame) -> bool:
        """Give it a frame. True if it took one. Cheap, and never blocks.

        Called from the live view's frame hook, 13.8 times a second
        (telemetry/liveview.TAP_FPS), so almost every call must do nothing at
        all: a clock comparison and a return.
        """
        self.offered += 1
        if self._stop or frame is None or self.busy:
            return False
        now = self.clock()
        if self._last is not None and now - self._last < self.every:
            return False
        self._last = now
        self.busy = True
        import threading
        threading.Thread(target=self._read, args=(frame,), daemon=True,
                         name="hivemind-whereami").start()
        return True

    def _read(self, frame) -> None:
        try:
            fix = self.locator.look(frame)
            self.looks += 1
            if fix is not None:
                self.on_fix(fix, frame)
        except Exception:
            pass              # looking around must never end the session
        finally:
            self.busy = False

    def stop(self) -> None:
        self._stop = True

    @property
    def where(self):
        return self.locator.where()
