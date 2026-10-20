"""Walking to a quest giver and writing down what its panel says. Presses
nothing.

WHY THIS IS THE NEXT STEP FOR QUESTS. The owner asked for it directly -- "i
wan it to start completing my quests and learning how to speak to the bear and
turn them in" -- and the bot already does two of the three things that needs:
it reads the quest menu (var/quests.json) and it can walk to every giver
(`natro_out_<giver>`, transpiled from Natro Macro). The missing third is
knowing what a giver's prompt says, because `act/errands` and `nav/journey`
both refuse to press `e` at a panel they cannot match, and nothing has ever
photographed one. docs/GAPS.md #6 has said so since the first review.

So this walks there, reads the panel, SAVES THE WORDS AND THE FRAME, and walks
back the recorded way. It presses no key but movement keys. That is enough to
fill in the giver's prompt honestly, which is what the hand-in will be built
against -- rather than typing in what a wiki says the prompt "should" be.

WHY IT IS ONCE PER GIVER. The record is a file (`var/bear_panels.json`), so a
giver whose prompt has been read is never walked to again for this. A session
that has them all costs nothing.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

# The givers this knows how to reach, in the order worth learning: the two
# bears whose quests the account is actually carrying come first.
GIVERS = ("polar_bear", "black_bear", "brown_bear", "honey_bee",
          "bucko_bee", "riley_bee",
          # The Panda Bear, last: his route (`natro_out_panda_bear`, DESIGN
          # 8dm) is cut from Natro's treat-dispenser walk and stops at the
          # foot of his block, so his prompt has never been read. He holds
          # "The REAL Final Showdown" (var/quests.json, 2026-09-25), whose
          # reward is a Gold Egg.
          "panda_bear",
          # Mother Bear: the feeding quests (Search For Sunflower Seeds), at
          # the far end of the Sunflower Field by the Treat Shop (run_farm
          # MOTHER_SURVEY_SHOP, 2026-10-05).
          "mother_bear",
          # Spirit Bear: her questline, required for progression and automated
          # by nobody else; on a ledge above the Coconut walk, which her route
          # is cut from (transpile_natro DERIVED_ROUTES, 2026-10-06).
          "spirit_bear")

# WHICH SETTING SWITCHES WHICH GIVER OFF.
#
# The eight `quests.<bear>` toggles sat in `world/settings.NOT_WIRED` under
# the note "reading quests works; TALKING to a bear does not". That stopped
# being true on 2026-09-23: the Black Bear's dialogue was read and clicked
# through, and the errand now covers every giver Natro has a path to. So the
# six toggles for THOSE givers are real controls and are read here, in the
# library, rather than in whichever script happens to need them.
#
# The Science Bear's and the Spirit Bear's switches are deliberately absent
# from this map. There is no recorded route to either giver, so neither could
# change anything, and pretending otherwise is the thing the owner ruled out.
# They stay in `world/settings.NOT_WIRED` with a note saying which half is
# missing -- and their keys are not written out here, because
# `tests/unit/test_settings.py` scans this source for the names of unwired
# settings and a mention in a comment is enough to trip it, which is exactly
# the guard working.
GIVER_SETTINGS = {
    "black_bear": "quests.black_bear",
    "brown_bear": "quests.brown_bear",
    "polar_bear": "quests.polar",
    "honey_bee": "quests.honey",
    "bucko_bee": "quests.bucko",
    "riley_bee": "quests.riley",
    "panda_bear": "quests.panda",
    "mother_bear": "quests.mother",
    "spirit_bear": "quests.spirit",
}


def wanted_givers(settings, names) -> tuple:
    """The givers among `names` the owner has not switched off.

    A name with no toggle -- `blue_hq` is a shop, not a giver -- is kept: this
    filters what the owner said no to, and says nothing about anything else.
    Unreadable settings keep everything, because an errand not running is a
    quieter failure than a control that silently cancels it.
    """
    out = []
    for name in names or ():
        key = GIVER_SETTINGS.get(str(name))
        if key is None:
            out.append(name)
            continue
        try:
            if settings.bool(key):
                out.append(name)
        except Exception:
            out.append(name)
    return tuple(out)
SETTLE_SECONDS = 1.5


@dataclass
class Visit:
    """What one visit established. `panel` empty means nothing was on screen."""
    giver: str
    walked: bool = False
    panel: str = ""
    came_back: bool = False
    frame_path: str = ""
    reason: str = ""
    # How many times the panel was read before something was on it. See
    # LOOK_TRIES.
    looks: int = 0
    # How many 45-degree camera taps the search used. They are all undone
    # before this returns; the number is kept so the log can say the camera
    # was borrowed.
    turns: int = 0
    # What the walk-and-watch search did when looking and turning found
    # nothing. Empty when it never had to run. See `visit`'s `hunt`.
    hunted: str = ""

    def describe(self) -> str:
        if not self.walked:
            return f"{self.giver}: the route did not run — {self.reason}"
        seen = f"the panel read {self.panel!r}" if self.panel else "nothing on the panel"
        home = "walked back" if self.came_back else "did NOT get back"
        return f"{self.giver}: {seen}; {home}"


def further_dialogue(was: dict, fresh: dict) -> dict:
    """Whichever of two readings of one giver's dialogue got further.

    A FAILURE MUST NOT ERASE AN ANSWER. MEASURED 2026-09-23 04:58:
    `var/bear_dialogues.json` held the Black Bear's real dialogue -- "You
    know, when you think about it. finding anything rare is probably lucky.",
    read at 03:29 -- and by 04:58 the same file read `dialogue=""`,
    `closed=false`, `pages=[]`, because a later attempt that never reached the
    bear was written over the top. The store was written unconditionally, so
    every retry of a giver whose record is incomplete could destroy what the
    last attempt learned.

    Closed beats open, because an open box means the pages after it were never
    seen. Otherwise more pages wins, then any dialogue over none. A TIE KEEPS
    THE OLDER ONE, so a retry that learned nothing changes nothing.

    The rule is the one `brain.questneeds._furthest` applies to two readings
    of a quest menu, for the same reason.
    """
    def rank(d):
        d = d or {}
        # 'NONE' is the model saying there was no box (DIALOGUE_QUESTION),
        # so a record holding it has no dialogue to protect.
        said = str(d.get("dialogue") or "").strip()
        return (1 if d.get("closed") else 0,
                len(d.get("pages") or []),
                1 if said and said.upper() != "NONE" else 0)
    return fresh if rank(fresh) > rank(was) else was


# WHAT A PROMPT LOOKS LIKE, so a panel read can be refused as one. The
# top-centre panel is the game's shared notification area, and the banner
# detector can also land on the HUD: MEASURED 2026-09-23 18:17, the Bucko Bee
# recon recorded 'Honey 20,750,759 (+13/sec) Pollen 1,958/1,113,750 (+69/sec)'
# as the bear's prompt, and the hand-in would then have waited for a panel
# that can never read that -- or pressed E at one that did. The real prompts
# are short and carry no digits ("Talk to Black Bear", "Make Honey", "Open
# Shop"); the same rule run_farm's `_learn_prompt` applies to what it keeps.
PROMPT_MAX_CHARS = 40
PRICE = re.compile(r"\bspend\s+\d[\d.,]*\s+", re.IGNORECASE)


def prompt_shaped(text) -> bool:
    """Is this the kind of thing the game writes on a prompt?

    A MACHINE'S COUNTDOWN IS PART OF ITS PROMPT, not a sign of the HUD. The
    digit rule exists for the HUD leak ("Honey 20,750,759 (+13/sec)"), and
    it also threw out "Use the Wealth Clock (57:22)" -- MEASURED 2026-09-23
    22:48:35, when `Learned.load` dropped the clock's recorded prompt and
    wrote the file back without it, so the errand had nothing to confirm the
    clock by. The countdown is taken off before the rule is applied; the
    rest of the words still have to look like a prompt.

    A MACHINE'S PRICE IS PART OF ITS PROMPT TOO: "Spend 25,000,000 Honey to
    Play Extreme Memory Match" (var/places/extreme_memory_match-123903.jpg)
    failed both the digit and the length rule, so every Memory Match landing
    was booked a miss (15 Normal, 15 Mega, 3 Extreme in giver_misses.json by
    2026-10-12). "Spend <amount>" is taken off like the countdown; the HUD
    never says "Spend".
    """
    from .errands import COUNTDOWN               # local: keeps act/ acyclic
    clean = " ".join(PRICE.sub("", COUNTDOWN.sub("", str(text or ""))).split())
    return bool(clean) and len(clean) <= PROMPT_MAX_CHARS and not any(
        c.isdigit() for c in clean)


# A GIVER'S PROMPT HAS TO NAME THE GIVER (DESIGN 8dm).
#
# `prompt_shaped` keeps the HUD out and nothing else. The recon wrote down
# whatever short panel it stopped at, and the hand-in then pressed E whenever
# the panel said those words again -- with no check that they named the giver
# and none against `act/errands.NEVER_PRESS`, which the place errands and the
# route presses (`act/routes._interact_when`) both have. Routes named after
# one thing have stopped at another: var/place_panels.json holds 'Open Shop'
# under honey_dispenser and 'Claim Hive' under strawberry_dispenser, and a
# Black Bear walk read 'Use the Honey Dispenser'. The Gumdrop Shop stands
# beside the Panda Bear's block, so a Panda recon that stopped there would
# have taught the hand-in to press E at a shop.
#
# Every word of the node name, as a whole word: all five prompts read so far
# pass (var/bear_panels.json: 'Talk to Black Bear', 'Talk to Brown Bear',
# 'Talk to Gifted Bucko Bee', 'Talk to Honey Bee', 'Talk to Polar Bear'),
# and 'Use the Honey Dispenser' does not pass for the Honey Bee.
def never_press_word(text) -> str:
    """The first of `act/errands.NEVER_PRESS` that `text` carries, or ''.
    The same substring test `_interact_when` applies."""
    from .errands import NEVER_PRESS             # local: keeps act/ acyclic
    words = " ".join(str(text or "").lower().split())
    return next((bad for bad in NEVER_PRESS if bad in words), "")


def names_giver(giver, text) -> bool:
    """Does `text` carry every word of `giver`'s node name as a whole word --
    or the name run together, for a read that split its words? MEASURED
    2026-10-06 02:43: at the Mother Bear the floating numbers over the prompt
    read it as 'ta lkitê m other bear' ("motherbear" run together, never
    "mother" alone); 'Use the Honey Dispenser' still names no Honey Bee."""
    low = str(text or "").lower()
    said = set(re.findall(r"[a-z]+", low))
    wanted = [w for w in str(giver or "").lower().split("_") if w]
    return bool(wanted) and (all(w in said for w in wanted)
                             or "".join(wanted) in re.sub(r"[^a-z]+", "", low))


def giver_prompt_refusal(giver, text) -> str:
    """'' when `text` may be kept as `giver`'s prompt and pressed at, else why
    not -- in words for the log."""
    if not prompt_shaped(text):
        return "it is the HUD or nothing, not a prompt"
    bad = never_press_word(text)
    if bad:
        return f"it says {bad!r}, which this bot never presses at"
    if not names_giver(giver, text):
        return f"it does not name the {str(giver).replace('_', ' ')}"
    return ""


@dataclass
class Learned:
    """The prompts read so far, kept on disk."""
    path: object
    prompts: dict = field(default_factory=dict)
    # Entries the file held that were not prompts, dropped on load and
    # reported so the log says what was thrown away and why.
    rejected: dict = field(default_factory=dict)

    def load(self) -> "Learned":
        try:
            body = json.loads(self.path.read_text())
            if isinstance(body, dict):
                kept = {str(k): str(v) for k, v in body.items()}

                # A GIVER'S ENTRY MUST NAME IT (see giver_prompt_refusal).
                # Only the givers': var/place_panels.json is loaded through
                # this too, and its 'Open Shop' is an observation that
                # `errands.expect_from_panel` already refuses to press on.
                def junk(k, v) -> bool:
                    if k in GIVERS:
                        return bool(giver_prompt_refusal(k, v))
                    return not prompt_shaped(v)
                self.rejected = {k: v for k, v in kept.items() if junk(k, v)}
                self.prompts = {k: v for k, v in kept.items() if not junk(k, v)}
        except (OSError, ValueError):
            pass
        if self.rejected:
            # Written back without the junk, so it is reported once and not
            # at the start of every attempt until something else saves.
            self.save()
        return self

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.prompts, indent=1, sort_keys=True))
        except OSError:
            pass

    def unknown(self, givers=GIVERS) -> list[str]:
        return [g for g in givers if not self.prompts.get(g)]


# The interact key, the same one the hive claim presses and the only key this
# module will ever send besides movement. Never Return, never Escape: a Roblox
# menu carries Log Out and Leave as ordinary activatable tiles.
INTERACT_KEY = "e"

# HOW MANY TIMES TO LOOK FOR A GIVER'S PROMPT before deciding it is not
# there. The panel is the game's shared notification area, so a prompt that
# IS showing can be covered by a receipt or a level-up at the moment of the
# read; the hive claim looks twenty-four times at the same panel for the same
# reason. Eight looks a `SETTLE_SECONDS` apart is twelve seconds, spent only
# on an errand that has already walked 162 studs to get there.
LOOK_TRIES = 8

# HOW MANY TIMES TO LOOK AGAIN AFTER THE SEARCH. Three: the search itself
# only stops when it has seen the prompt, so this is confirming what it just
# saw, not hunting again. See `talk`'s `hunt`.
HUNT_CONFIRM_LOOKS = 3

# HOW MANY CAMERA TAPS MAKE A FULL TURN. `act/homing` measured the same
# number for the same key (`.` is RotRight, sc034 in natro_macro.ahk): eight
# taps of 45 degrees. A recon that has looked all the way round and seen
# nothing has answered the question.
TAPS_PER_FULL_TURN = 8
# What the dialogue is asked, once it is on screen. One question, answered
# from the frame, and the answer is stored verbatim rather than parsed --
# nothing is built on a guess about the wording until a real one is in hand.
DIALOGUE_QUESTION = (
    "This is a Roblox Bee Swarm Simulator screen. A quest-giver dialogue box "
    "may be open. Transcribe EXACTLY the text of any dialogue box, including "
    "the names of any buttons in it. If there is no dialogue box on screen, "
    "answer with the single word NONE.")


@dataclass
class Talk:
    """What pressing E at a giver showed, and whether we got away afterwards."""
    giver: str
    pressed: bool = False
    dialogue: str = ""
    after_leaving: str = ""
    frames: list = field(default_factory=list)
    reason: str = ""
    # How many times the panel was read before the prompt showed, or before
    # it was given up on. Kept so a failure says whether it looked once or
    # eight times -- see LOOK_TRIES.
    looks: int = 0
    # Every page of the dialogue, in order, and how it ended. `closed` is the
    # one that matters operationally: a dialogue still open has the character
    # frozen, because it eats the movement keys (measured -- see `talk`).
    pages: list = field(default_factory=list)
    clicks: int = 0
    closed: bool = False
    # WHAT THE SEARCH DID when the prompt was not showing where the route
    # stopped. Empty when it never had to run. See `talk`'s `hunt`.
    hunted: str = ""

    @property
    def opened(self) -> bool:
        return bool(self.dialogue) and self.dialogue.strip().upper() != "NONE"

    def describe(self) -> str:
        if not self.pressed:
            return f"{self.giver}: pressed nothing — {self.reason}"
        if self.hunted:
            return (f"{self.giver}: {self.hunted}, then the dialogue says "
                    f"{self.dialogue[:60]!r}" if self.opened else
                    f"{self.giver}: {self.hunted} and pressed E, no dialogue read")
        if not self.opened:
            return f"{self.giver}: pressed E and no dialogue was read"
        left = ("and walking away closed it" if self.after_leaving.strip().upper() == "NONE"
                else "and it was still there after walking away"
                if self.after_leaving else "and what closes it is unknown")
        return f"{self.giver}: dialogue says {self.dialogue[:80]!r} {left}"


def talk(giver: str, *, expect: str, read_panel, frames, ask, vin,
         walk_away=None, sleep=time.sleep, settle: float = SETTLE_SECONDS,
         save_dir=None, on_note=None, tries: int = LOOK_TRIES,
         click=None, hunt=None, turn=None,
         full_turn: int = TAPS_PER_FULL_TURN) -> Talk:
    """Press E at a giver whose panel already says what it should, read the
    dialogue, and leave by walking.

    `expect` is the prompt learned by `visit` -- "Talk to Black Bear". The
    press happens ONLY when the panel says that now, so the key is never sent
    at a screen this cannot read. `ask(png, question)` is the vision model.
    `walk_away()` is the caller's way of stepping back, movement keys only.

    Nothing is pressed to dismiss the dialogue. What closes it is exactly what
    this is finding out, and guessing at Return or Escape is how an
    unattended bot logs the owner out.
    """
    note = on_note or (lambda text: None)
    out = Talk(giver=giver)

    # THE WORDS PRESSED AGAINST MUST THEMSELVES BE THE GIVER'S (DESIGN 8dm).
    # `Learned.load` already drops anything else from the store; this holds
    # for any caller, so the press below cannot be pointed at a shop by a
    # record written before that check existed.
    bad_expect = giver_prompt_refusal(giver, expect)
    if bad_expect:
        out.reason = (f"the prompt to press at, {expect!r}, is not the "
                      f"{giver.replace('_', ' ')}'s: {bad_expect} — nothing "
                      f"was pressed")
        note(out.describe())
        return out

    def look():
        try:
            return frames()
        except Exception:
            return None

    def keep(frame, tag):
        if frame is None or save_dir is None:
            return
        try:
            import cv2
            save_dir.mkdir(parents=True, exist_ok=True)
            path = save_dir / f"{giver}-{tag}-{time.strftime('%H%M%S')}.jpg"
            cv2.imwrite(str(path), frame[:, :, :3], [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            out.frames.append(str(path))
        except Exception:
            pass

    def transcribe(frame) -> str:
        if frame is None:
            return ""
        try:
            import cv2
            ok, buf = cv2.imencode(".png", frame[:, :, :3])
            if not ok:
                return ""
            answer = ask(buf.tobytes(), DIALOGUE_QUESTION)
            return " ".join(str(getattr(answer, "text", answer) or "").split())[:400]
        except Exception as exc:
            note(f"{giver}: could not read the dialogue ({exc})")
            return ""

    # LOOK MORE THAN ONCE. MEASURED 2026-09-23: the errand walked the 162
    # studs to the Black Bear, read the panel exactly once, got "" and wrote
    # itself off -- `var/bear_dialogues.json` held `reason: the panel says
    # '', not 'Talk to Black Bear'`. The top-centre panel is the game's
    # SHARED notification area: quest text, honey receipts and level-ups all
    # pass through it, so any single read can miss a standing prompt that is
    # there. Every other routine in this codebase that waits on that panel
    # looks repeatedly -- the hive claim looks twenty-four times -- and this
    # one did not. Looking cannot press anything, so the only cost is time.
    last = {"panel": None, "broken": "", "refused": ""}
    # TURN WHILE LOOKING, as the recon does. MEASURED 2026-09-24: both walks
    # to the Honey Bee (attempts 353 and 355) ended with "Talk to Honey Bee"
    # plainly on screen, and `vision/banner` found no panel in either frame --
    # the panel is part see-through and there it sits on a light-blue sky
    # (panel H 107 S 169 V 208, sky H 105 S 163 V 195), so the two fuse into
    # one 1550x220 blob that fails the shape rules. The recon found the same
    # prompt after three looks because it turns the camera between them and
    # the background behind the panel changes. The camera is put back
    # afterwards whatever happens: every recorded route steers by it.
    turned = {"n": 0}

    def showing(rounds: int) -> bool:
        """Read the panel up to `rounds` times; True when it says `expect`."""
        for attempt in range(1, max(1, int(rounds)) + 1):
            frame = look()
            try:
                panel = read_panel(frame) if frame is not None else None
            except Exception as exc:
                last["broken"] = f"could not read the panel ({exc})"
                return False
            last["panel"] = panel
            out.looks += 1
            words = " ".join(str(panel or "").split()).lower()
            # A NEVER-PRESS PANEL IS NEVER A MATCH, whatever else it says,
            # and neither is one that does not name the giver -- the same
            # refusal `act/routes._interact_when` makes. Looking on costs
            # nothing; the press below needs a fresh read that passes.
            bad = never_press_word(words)
            if bad and last["refused"] != words:
                last["refused"] = words
                note(f"{giver}: the panel says {words!r} — {bad!r} is never "
                     f"pressed at; still looking for {expect!r}")
            if (words and not bad and expect.strip().lower() in words
                    and names_giver(giver, words)):
                return True
            if (not words and turn is not None
                    and turned["n"] < max(1, int(full_turn))):
                try:
                    turn(1)
                    turned["n"] += 1
                except Exception:
                    pass
            if attempt < max(1, int(rounds)):
                sleep(settle)
        return False

    def turn_back() -> None:
        if turn is not None and turned["n"]:
            try:
                turn(-turned["n"])
            except Exception:
                note(f"{giver}: could not turn the camera back {turned['n']} "
                     f"tap(s) — the next route steers by it")
            turned["n"] = 0

    found = showing(tries)
    if last["broken"]:
        turn_back()
        out.reason = last["broken"]
        return out

    # STANDING STILL AND LOOKING HARDER DOES NOT FIND A BEAR THAT IS TEN
    # STUDS AWAY.
    #
    # MEASURED, in `var/bear_dialogues.json` and the run logs: five errands
    # walked to the Black Bear and read `''` eight times over; three did the
    # same at the Polar Bear; and one Black Bear errand read `'Use the Honey
    # Dispenser'`, which is a different landmark altogether. The prompt only
    # shows within a few studs of the giver, so a route that stops short
    # reads an empty panel however many times it looks -- and a finished
    # quest then sits unclaimed, which is the owner's "it literally doesnt do
    # quests".
    #
    # This is the same problem the hive pad had, and it has the same answer:
    # hold a key and watch the panel, releasing on sight (`act/hiverow`,
    # Natro's nm_findHiveSlot). `hunt()` is the caller's search -- it is
    # given the words to look for and returns a description of what it did.
    # Nothing is pressed by it, and the press below still happens only while
    # the panel is saying `expect` on a fresh read.
    if not found and hunt is not None:
        turn_back()                   # the search walks by the camera's heading
        try:
            out.hunted = str(hunt() or "")
        except Exception as exc:
            out.hunted = f"the search itself failed ({exc})"
        if out.hunted:
            note(f"{giver}: {out.hunted}")
        found = showing(HUNT_CONFIRM_LOOKS)
        if last["broken"]:
            turn_back()
            out.reason = last["broken"]
            return out

    if not found:
        turn_back()
        out.reason = (f"looked {out.looks} times and the panel never said "
                      f"{expect!r} (last read {last['panel']!r}) — either the "
                      f"walk did not arrive or the "
                      f"{giver.replace('_', ' ')} is not there"
                      + (f"; the search {out.hunted}" if out.hunted else "")
                      + (f"; refused {last['refused']!r}, a never-press panel"
                         if last["refused"] else ""))
        return out

    if vin.tap(INTERACT_KEY) is False:
        # HELD BACK BY THE OWNER'S PAUSE OR TAKE OVER (brain/controls
        # STALE_AFTER_A_WAIT): the panel was read before it, so the E is not
        # sent, and it is not recorded as pressed.
        out.reason = "the E was held back by the owner's Pause/Take Over"
        turn_back()
        return out
    out.pressed = True
    sleep(settle)
    opened = look()
    keep(opened, "dialogue")
    out.dialogue = transcribe(opened)
    note(out.describe())

    # READ THE WHOLE THING, AND CLOSE IT BY CLICKING THE BOX.
    #
    # MEASURED 2026-09-23 03:29: this routine pressed E, read one page, ran
    # `natro_back_black_bear` to leave -- and the frame taken afterwards is
    # pixel-for-pixel the same scene: the bear in the same place, the camera
    # identical, the dialogue box on the same 489x117 rectangle. The character
    # NEVER MOVED. An open dialogue swallows the movement keys, so walking
    # away is not a way out of one, and before this the only way out was the
    # rejoin.
    #
    # The box itself says what does work, in small type in its bottom right:
    # "Click to continue". So the pages are turned with a click into the box
    # -- see act/dialogue, which will not click unless it has just seen a box
    # on the very frame it is clicking at.
    if click is not None:
        from . import dialogue as _dialogue
        read = _dialogue.advance(
            frames=frames, click=click, transcribe=transcribe, sleep=sleep,
            on_note=note,
            on_frame=lambda frame, page: keep(frame, f"page{page}"))
        out.pages = list(read.pages)
        out.clicks = read.clicks
        out.closed = read.closed
        if read.pages:
            # The first page came from the press above; `advance` re-reads it
            # and then turns it, so the full text is what it collected.
            out.dialogue = " | ".join(read.pages)
        note(f"{giver}: {read.describe()}")

    # NO BOX, NO DIALOGUE. DIALOGUE_QUESTION asks the model for 'NONE' on a
    # frame with no box, and DESIGN 8a records it inventing text on empty
    # crops ('claim hive' for 11 of 24 frames); run_farm counts any words
    # here as the hand-in. So words only stand when a box was seen.
    from . import dialogue as _dialogue
    if out.dialogue and not out.pages and _dialogue.find(opened) is None \
            and not (click is not None and read.saw_box):
        note(f"{giver}: no dialogue box was on screen, so {out.dialogue[:60]!r} "
             f"is not a dialogue")
        out.dialogue = ""

    # THE CAMERA COMES BACK BEFORE ANY WALK, when no box is up to swallow
    # the taps: the look-round may have turned it up to a full turn, and
    # the walk-away route steers by it (the deferral below is for a box).
    now_frame = look()
    if (now_frame is not None and _dialogue.find(now_frame) is None
            and not _dialogue.find_options(now_frame)):   # a menu eats taps too
        turn_back()

    # WALKING AWAY IS THE FALLBACK, NOT THE PLAN. It is kept for the case
    # where the box would not close, because being out of position is
    # recoverable (the next trip walks to the hive first, and the rejoin is
    # behind that) and being stuck in a dialogue is not.
    if walk_away is not None and not out.closed:
        try:
            walk_away()
        except Exception:
            pass
        sleep(settle)
        after = look()
        keep(after, "after-leaving")
        out.after_leaving = transcribe(after)
    # AFTER THE DIALOGUE, not straight after the press: with a box open the
    # keys may be swallowed (it eats the movement keys -- see above), and a
    # turn the compass counted but the camera never made would send the next
    # route off rotated.
    turn_back()
    return out


def visit(giver: str, *, walk, back, read_panel, frames=None, save_dir=None,
          sleep=time.sleep, settle: float = SETTLE_SECONDS, on_note=None,
          tries: int = LOOK_TRIES, turn=None,
          full_turn: int = TAPS_PER_FULL_TURN, hunt=None,
          keep_looks: bool = False, marker=None, at_place=None) -> Visit:
    """Walk to `giver`, read its panel, walk back. `walk()` and `back()` run the
    recorded routes and return truthy when they completed.

    A visit that cannot get there reads no panel and says so; a visit that
    cannot get BACK still reports the panel it read, because the words are the
    point and the caller's own walk home can recover the position.

    `keep_looks` saves the frame of every look, not just the last, as
    `<giver>-look<n>-HHMMSS.jpg` in `save_dir`. The look-round turns the
    camera 45 degrees between looks, so that is the view in every direction
    from where the route stopped -- the evidence a route whose last stretch
    has never been seen needs (the Panda Bear's; DESIGN 8dm).

    `marker(frame)`, truthy when a quest giver's "!" is on screen
    (vision/questmarker.find): the first look of the round that shows one is
    the way the hunt starts facing, and the camera is put back after it.

    `at_place(panel)` runs at the place, after a non-empty read and before the
    walk back; the caller judges the panel (run_farm's Sticker Stack peek).
    """
    note = on_note or (lambda text: None)
    out = Visit(giver=giver)
    try:
        out.walked = bool(walk())
    except Exception as exc:
        out.reason = f"the route raised {exc}"
        return out
    if not out.walked:
        out.reason = "the route out did not complete"
        return out

    # LOOK UNTIL THERE IS SOMETHING TO READ, AND TURN ROUND WHILE LOOKING.
    #
    # Two separate reasons, both measured. The first is in `talk`: the
    # top-centre panel is the game's shared notification area, so one read can
    # land on a receipt or on nothing at all.
    #
    # The second is that a prompt only shows when the thing is IN FRONT of the
    # character. MEASURED 2026-09-23 04:09: `natro_out_bucko_bee` was run
    # from the pad straight after a confirmed convert, and the frame it saved
    # (`var/bears/bucko_bee-040928.jpg`) shows the character in the blue
    # headquarters area looking at a flat cyan wall. It had arrived; it was
    # facing the wrong way. Eight more looks at the same wall cannot help.
    #
    # So an empty panel turns the camera 45 degrees and looks again, up to one
    # full turn -- and then turns back exactly as far, because every
    # recorded route steers by the camera and a recon that quietly leaves it
    # 180 degrees out would break the next walk. `turn(n)` is the caller's
    # camera; recon presses no other key.
    text = None
    frame = None
    turned = 0
    seen_at = None              # the tap at which a "!" first showed
    for attempt in range(1, max(1, int(tries)) + 1):
        sleep(settle)
        frame = None
        if frames is not None:
            try:
                frame = frames()
            except Exception:
                frame = None
        try:
            text = read_panel(frame) if frame is not None else read_panel()
        except Exception as exc:
            text = None
            out.reason = f"could not read the panel ({exc})"
            break
        out.looks = attempt
        if keep_looks and frame is not None and save_dir is not None:
            try:
                import cv2
                save_dir.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(save_dir / f"{giver}-look{attempt}-"
                                           f"{time.strftime('%H%M%S')}.jpg"),
                            frame[:, :, :3], [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            except Exception:
                pass
        if " ".join(str(text or "").split()):
            break
        if marker is not None and frame is not None and seen_at is None:
            try:
                if marker(frame):
                    seen_at = turned
            except Exception:
                pass
        if turn is not None and turned < max(1, int(full_turn)):
            try:
                turn(1)
                turned += 1
                out.turns = turned
            except Exception:
                turn = None
    # ...FACING A "!" THE ROUND SAW, FOR THE HUNT. MEASURED 2026-10-06: the
    # Spirit Bear's route (the Coconut walk to its step 35) ended in four
    # different places in four runs -- one of them with her "!" up and to the
    # right (var/shoplook/20261006-134729-spirit_bear_survey_coconut-arrived.
    # jpg) -- and the hunt's first hold walks toward a "!" only when it is on
    # screen at the start (act/beacon). So the camera stops at the first look
    # that showed one, and goes the rest of the way back after the hunt.
    facing = 0
    if (seen_at and hunt is not None and turn is not None
            and not " ".join(str(text or "").split())):
        facing = seen_at
        note(f"{giver}: a quest marker showed {seen_at} tap(s) round — the "
             f"search starts facing it")
    if turn is not None and turned:
        # PUT THE CAMERA BACK. Unconditionally, on success as well as
        # failure: the heading is shared state and this borrowed it.
        try:
            turn(facing - turned)
        except Exception:
            facing = 0
            note(f"{giver}: could not turn the camera back {turned} tap(s) — "
                 f"the next route steers by it")
    # AND THEN WALK, because turning on the spot does not reach a prompt ten
    # studs away. MEASURED 2026-09-23 23:33:23: the recon of the blueberry
    # dispenser ended inside the blue headquarters with the machine at the
    # right edge of the frame (var/places/blueberry_dispenser-233323.jpg),
    # read nothing eight times, and turned a full circle -- standing still.
    # `hunt()` is the same bounded hold-and-watch the quest givers get
    # (`talk`), and it presses nothing: what it stops on is read below and
    # judged by the caller like any other reading.
    if not " ".join(str(text or "").split()) and hunt is not None:
        try:
            out.hunted = str(hunt() or "")
        except Exception as exc:
            out.hunted = f"the search itself failed ({exc})"
        if out.hunted:
            note(f"{giver}: {out.hunted}")
        for _ in range(HUNT_CONFIRM_LOOKS):
            sleep(settle)
            frame = None
            if frames is not None:
                try:
                    frame = frames()
                except Exception:
                    frame = None
            try:
                text = read_panel(frame) if frame is not None else read_panel()
            except Exception:
                text = None
            out.looks += 1
            if " ".join(str(text or "").split()):
                break
    if facing and turn is not None:
        try:
            turn(-facing)
        except Exception:
            note(f"{giver}: could not turn the camera back {facing} tap(s) after "
                 f"the search — the next route steers by it")
    out.panel = " ".join(str(text or "").split())[:120]
    if frame is not None and save_dir is not None:
        try:
            import cv2
            save_dir = save_dir
            save_dir.mkdir(parents=True, exist_ok=True)
            path = save_dir / f"{giver}-{time.strftime('%H%M%S')}.jpg"
            cv2.imwrite(str(path), frame[:, :, :3], [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            out.frame_path = str(path)
        except Exception:
            pass
    note(out.describe())
    if at_place is not None and out.panel:
        try:
            at_place(out.panel)
        except Exception as exc:
            note(f"{giver}: at the place, {exc}")
    try:
        out.came_back = bool(back())
    except Exception:
        out.came_back = False
    return out
