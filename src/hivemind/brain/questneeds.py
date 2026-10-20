"""Turning the quest menu's own words into something the planner can use.

THE OWNER ASKED TWICE: "also can the ai just look at whats quests i have", then
"make sure u get questworking". Reading them was the first half and it works --
these are the three it actually holds, transcribed off his screen tonight:

    Optimizing Abilities
      Discover 19 Bee Types. Complete.
      Collect 820,020 Blue Pollen. 142,504/820,020
      Collect 720,020 White Pollen. Complete.
    Skirmish With Scorpions
      Defeat 15 Scorpions. 0/15
    Colorful Craving
      Collect 1,500,000 Red Pollen. 720,047/1,500,000

The second half is doing something about them, and for a bot that gathers
pollen the actionable part is the colour. Two of these want a specific colour
of pollen and between them they are short about 1.5 million of it. Which field
to stand in is exactly the decision the planner makes every cycle, so this
turns "Collect 820,020 Blue Pollen. 142,504/820,020" into "blue: 677,516 still
needed" and lets the ranking weigh it.

WHAT IT REFUSES TO DO. A requirement it cannot parse is dropped, never
guessed at, and a quest with no numbers contributes nothing. A wrong number
here would send the bot to the wrong field for hours, which is worse than
having no opinion -- and the text comes from a vision model that is MEASURED
to invent words when shown something it cannot read (docs/DESIGN.md 8a).

Combat requirements ("Defeat 15 Scorpions") are recognised and deliberately
recorded as UNACTIONABLE. This bot has no reliable way to see a mob, let alone
fight one; pretending otherwise would send it to the Rose Field to be killed
by the scorpions it cannot count.

(Superseded twice: DESIGN 8ce made them a field tilt, and 8do made the six
field mobs a bug run -- `mobs_wanted` is what act/bugrun ranks by.)
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..vision import questmenu

COLOURS = ("blue", "red", "white")

# "Collect 820,020 Blue Pollen" / "Collect 1,500,000 Red Pollen"
# `[\d,.]+` rather than `[\d,]+`: the model spells thousands with a dot
# about as often as with a comma ("Collect 636.363 Pollen"), and a pattern
# that only knows commas silently drops half the real requirements. Whether a
# given spelling IS a count is `number()`'s decision, not the pattern's.
WANTS = re.compile(r"collect\s+([\d,.]+)\s+(blue|red|white)\s+pollen",
                   re.IGNORECASE)
# "142,504/820,020" -- how far along, when the menu shows it
PROGRESS = re.compile(r"([\d,.]+)\s*/\s*([\d,.]+)")
# A COMMA READ AS A SLASH. MEASURED 2026-09-23 19:00, from the account's own
# menu: "2,107/415/6,000,000" for 2,107,415 of 6,000,000 -- the model turned
# the thousands comma into a slash. Three numbers with a three-digit middle
# and a total that matches the target is that, and nothing else in the menu
# has that shape.
CHAIN = re.compile(r"([\d,.]+)\s*/\s*(\d{3})\s*/\s*([\d,.]+)")
# "Complete." / "Complete!"
DONE = re.compile(r"\bcomplete\b", re.IGNORECASE)
# "Complete! Talk to Honey Bee." -- the menu names the giver to hand in to, on
# the requirement line itself or on the verdict line folded onto it by
# `questmenu.merge_progress`. This is the only place the quest MENU says who
# gave a quest; the headings do not.
HAND_IN = re.compile(r"talk\s+to\s+([a-z][a-z ]*?)\s*[.!]?$", re.IGNORECASE)
# THE MENU'S OWN READY BANNER, which is the other way it says a quest is
# finished -- and until now the only one nothing read.
#
# MEASURED 2026-09-23 21:31, from this account's menu (var/quests.json,
# `transcripts`), the last two lines on the screen:
#
#     *Strawberry Field Forever* is ready for Black Bear
#     *Polar Bear: Spooky Stew* is ready to turn in!
#
# Both went to `unread` and were thrown away, so `ready_to_hand_in` returned
# nothing from that reading and the errand chain had no reason to prefer
# either giver. It only ever worked from the OTHER shape, a requirement line
# ending "Complete! Talk to Honey Bee.".
#
# Two shapes, because the game writes it two ways: it names the giver when
# the quest's name does not ("is ready for Black Bear"), and leaves it out
# when the name already carries it ("Polar Bear: Spooky Stew" -> the Polar
# Bear). The asterisks are how the game emphasises the quest name and the
# transcription keeps them unevenly, so they are optional here.
READY_BANNER = re.compile(
    r"^\**\s*(?P<quest>.+?)\s*\**\s+is\s+ready\s+"
    r"(?:for\s+(?P<giver>[a-z][a-z ]*?)|to\s+turn\s+in)\s*[.!]*$",
    re.IGNORECASE)
# WHEN A GIVER'S DIALOGUE WAS LAST READ: the key the hand-in in
# scripts/run_farm writes beside each record in var/bear_dialogues.json, and
# the only thing in that file that says a hand-in happened AFTER a quest was
# seen finished (`carry_ready`, `Needs.waiting`; DESIGN 8dh).
#
# The record itself cannot say it. `act/bearvisit.further_dialogue` keeps the
# OLDER of two readings that got equally far, and MEASURED 2026-09-24 00:40
# the Polar Bear's record is a closed nine-page dialogue from 07:29 the day
# before -- so the next hand-in there, about as long, would leave the record
# untouched. The file's mtime moves on failures too: 06:36:30 "keeping the
# Polar Bear's earlier dialogue -- this attempt got no further" still
# rewrote the file.
DIALOGUE_READ_AT = "dialogue_read_at"
# "Defeat 15 Scorpions"
FIGHT = re.compile(r"defeat\s+([\d,.]+)\s+([a-z ]+)", re.IGNORECASE)
# "Collect 320,020 Pollen from the Sunflower Field"
FROM_FIELD = re.compile(
    r"collect\s+([\d,.]+)\s+pollen\s+from\s+the\s+([a-z ]+?)\s+"
    r"(?:field|patch|forest|grove)", re.IGNORECASE)
# "Collect 6,000,000 Goo from the Bamboo Field" (var/quests.json 2026-10-07,
# Bucko Bee: Medley) -- goo is gathered from flowers a gumdrop has covered,
# so the field is owed both a visit and gumdrops (run_farm throw_a_gumdrop)
GOO = re.compile(
    r"collect\s+([\d,.]+)\s+goo\s+from\s+the\s+([a-z ]+?)\s+"
    r"(?:field|patch|forest|grove)", re.IGNORECASE)
# "Collect 5,000,000 Goo from Red Flowers" (Star Journey 2, read 2026-10-07
# 04:02): goo from a colour's flowers, gathered in any field mostly of it
GOO_COLOUR = re.compile(r"collect\s+([\d,.]+)\s+goo\s+from\s+(red|blue|white)\s+flowers",
                        re.IGNORECASE)
# "Collect 100 Haste Tokens"
TOKENS = re.compile(r"collect\s+([\d,.]+)\s+([a-z ]+?)\s+tokens",
                    re.IGNORECASE)
# "Catch 10 Pink Bloom Petals." (Polar Bear, read 2026-10-19) and the Bucko /
# Riley Petals steps, which may name a field ("... in the Clover Field").
BLOOM = re.compile(r"catch\s+([\d,.]+)\s+([a-z]+)\s+bloom\s+petals"
                   r"(?:\s+(?:in|from)\s+the\s+([a-z ]+?)\s+(?:field|patch|forest|grove))?",
                   re.IGNORECASE)
# "Feed 100 Treats to your Bees." (var/quests.json, 2026-10-05: Search For
# Sunflower Seeds, with "Feed 25 Sunflower Seeds to your Bees.")
FEED = re.compile(r"feed\s+([\d,.]+)\s+([a-z ]+?)\s+to\s+your\s+bees",
                  re.IGNORECASE)


# One reader for counts, shared with the parser, because the model spells a
# thousands separator both ways -- "636,363" and "636.363" -- on the same
# panel. See `vision.questmenu.number`.
_number = questmenu.number


@dataclass
class Need:
    """One outstanding requirement, in units the planner understands."""
    colour: str
    target: int
    done: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.target - self.done)

    def describe(self) -> str:
        return (f"{self.remaining:,} more {self.colour} pollen "
                f"({self.done:,}/{self.target:,})")


@dataclass
class TokenNeed:
    """A quest step asking for N tokens of one kind.

    THIS USED TO BE A STRING ON A LIST OF THINGS THAT COULD NOT BE DONE, and
    the reason it was there is no longer true. The note said "it still cannot
    tell a Focus token from a Haste one -- the detector finds token-shaped
    objects, not their kind". `vision/tokens.Kinds.classify` has named kinds
    since 2026-09-21, off the face colours of the official icons, and the
    night's own logs name them constantly: 81 haste, 33 rain_cloud, 26
    baby_love, **18 honey**. The one thing the quest step needed -- knowing
    which token is which -- exists.

    MEASURED 2026-09-23, from `var/quests.json` read off the account's own
    menu: "Honey Bee's Honey Hunt -- Collect 2,000 Honey Tokens. 1,845/2,000".
    155 tokens from a finished quest, and the bot was picking up whatever was
    nearest.
    """
    kind: str                       # the tokens.yaml key, e.g. "honey"
    target: int
    done: int = 0
    line: str = ""                  # the menu's own words, kept verbatim

    @property
    def remaining(self) -> int:
        return max(0, self.target - self.done)

    def describe(self) -> str:
        return (f"{self.remaining:,} more {self.kind.replace('_', ' ')} "
                f"token(s) ({self.done:,}/{self.target:,})")


@dataclass
class BloomNeed:
    """A quest step asking for N Bloom Petals of one colour, maybe in one field.
    LOOK-ONLY for now (roadmap: Bloom Petals steps): recorded so the plan and
    the reports can say what is owed; nothing chases Blooms yet."""
    colour: str                     # "pink", "green", "blue", ...
    target: int
    done: int = 0
    field: str = ""                 # "clover" when the step names one, else ""
    line: str = ""

    @property
    def remaining(self) -> int:
        return max(0, self.target - self.done)

    def describe(self) -> str:
        where = f" in {self.field.replace('_', ' ')}" if self.field else ""
        return (f"{self.remaining:,} more {self.colour} bloom petal(s){where} "
                f"({self.done:,}/{self.target:,})")


@dataclass
class FeedNeed:
    """A quest step asking for N of an item fed to the bees (act/feed)."""
    item: str                       # the menu's words, lowercased: "sunflower seeds"
    target: int
    done: int = 0
    line: str = ""

    @property
    def remaining(self) -> int:
        return max(0, self.target - self.done)

    def describe(self) -> str:
        return f"{self.remaining:,} more {self.item} to feed ({self.done:,}/{self.target:,})"


@dataclass
class Needs:
    """Everything the quests want, grouped by what can be acted on."""
    pollen: dict = field(default_factory=dict)      # colour -> Need
    fields: dict = field(default_factory=dict)      # field name -> Need
    goo: dict = field(default_factory=dict)         # field name -> Need, of goo
    goo_colour: dict = field(default_factory=dict)  # colour -> Need, of goo
    # field name -> Need, of POLLEN alone: what `fields` falls back to when
    # its goo is dropped (`goo_fields_dropped`)
    field_pollen: dict = field(default_factory=dict)
    tokens: list = field(default_factory=list)      # kind -> TokenNeed
    feeds: list = field(default_factory=list)       # FeedNeed, one per item
    blooms: list = field(default_factory=list)      # BloomNeed (look-only)
    fights: list = field(default_factory=list)      # unactionable, recorded
    # Requirement lines that say "Complete! Talk to <giver>". See
    # `ready_to_hand_in`.
    handed: list = field(default_factory=list)
    unread: list = field(default_factory=list)      # lines nothing understood
    read_at: float = 0.0
    # Giver -> {"quest": title, "at": first read that showed it finished},
    # carried from read to read by `carry_ready` until it is handed in.
    ready_since: dict = field(default_factory=dict)

    def goo_fields_dropped(self) -> "Needs":
        """These needs with no field owed for its goo alone -- run_farm's, when
        the gumdrops are at their keep and a trip there would throw none. A
        field a pollen step also owes keeps that step -- even when the goo
        step owed more (protips rule 7: the pollen steps still count)."""
        for name, need in self.goo.items():
            was = self.fields.get(name)
            if was is not None and (was.target, was.done) == (need.target, need.done):
                del self.fields[name]
                if self.field_pollen.get(name) is not None:
                    self.fields[name] = self.field_pollen[name]
        return self

    def field_remaining(self, name: str) -> int:
        need = self.fields.get(name)
        return need.remaining if need else 0

    def mobs_wanted(self) -> dict:
        """Mob slug -> how many more a quest wants defeated.

        "Defeat 3 Spiders. 1/3" is two more spiders. The slugs are the ones
        data/knowledge/world.yaml lists under each field's `mobs`
        (`rhino_beetle`, `werewolf`), so the planner can ask which field a
        wanted mob lives in. THE OWNER: "fighting bugs" is in the loop he
        asked for, and MEASURED 2026-09-23 the count rises while the bot
        farms the mob's field -- the bees fight, the character gathers.
        """
        out: dict = {}
        for line in self.fights:
            m = FIGHT.search(line)
            if not m:
                continue
            target = _target(line, _number(m.group(1)))
            if not target:
                continue
            left = max(0, target - _progress(line, target))
            if left <= 0:
                continue
            slug = mob_slug(m.group(2))
            if slug:
                out[slug] = out.get(slug, 0) + left
        return out

    def remaining(self, colour: str) -> int:
        need = self.pollen.get(colour)
        return need.remaining if need else 0

    @property
    def ready_to_hand_in(self) -> tuple:
        """Givers with a finished requirement waiting, most first.

        MEASURED 2026-09-23 04:34, from the account's own menu: "Collect
        2,000 Honey Tokens. Complete! Talk to Honey Bee." The bot walks to
        givers cheapest-walk-first, and the Honey Bee is the dearest walk of
        the seven (28 steps) -- so the one giver holding a finished quest was
        last in the queue. This is what lets the caller put it first.

        Names are node names (`honey_bee`, `science_bear`), because that is
        what the route graph and `bearvisit.GIVERS` use.

        AND THE ONES AN EARLIER READ SAW FINISHED, after these (`ready_since`,
        oldest first). MEASURED 2026-09-23: run-327's read said "Polar Bear:
        Spooky Stew ... Complete! Talk to Polar Bear." at 20:13:31, and the
        reads in runs 328 to 333 listed the same quest with no "Complete!"
        and no numbers at all. A finished quest cannot become unfinished, so
        one read that drops the words must not undo one that saw them.
        """
        seen: dict = {}
        for line in self.handed:
            who = _giver_of(line)
            if not who:
                continue
            seen[who] = seen.get(who, 0) + 1
        fresh = tuple(sorted(seen, key=lambda k: -seen[k]))
        kept = sorted((g for g in self.ready_since if g not in seen),
                      key=lambda g: _at(self.ready_since.get(g)))
        return fresh + tuple(kept)

    def waiting(self, dialogues=None) -> tuple:
        """`ready_to_hand_in`, less every giver whose dialogue has been read
        since the quest was seen finished there.

        `dialogues` is var/bear_dialogues.json as a dict. A giver with no
        `ready_since` entry is dated by this read. This is what keeps a
        hand-in from being repeated after a rejoin that skips the menu read
        (DESIGN 8dh): that file still lists the quest as ready.
        """
        out = []
        for giver in self.ready_to_hand_in:
            since = self.ready_since.get(giver)
            at = _at(since) if since else float(self.read_at or 0.0)
            if not answered_since(dialogues, giver, at):
                out.append(giver)
        return tuple(out)

    def merged_with(self, other: "Needs") -> "Needs":
        """This reading and another of the SAME menu, taking the furthest
        progress for each requirement.

        Only sound because the two readings are of one screen a moment apart:
        quest progress cannot go backwards within a sitting, so a lower figure
        is a misread. It is NOT used to merge readings from different
        sittings, where a handed-in and re-issued quest legitimately resets.
        """
        out = Needs(read_at=max(self.read_at, other.read_at))
        for key in set(self.pollen) | set(other.pollen):
            out.pollen[key] = _same_or_owed(self.pollen.get(key),
                                            other.pollen.get(key))
        for key in set(self.fields) | set(other.fields):
            out.fields[key] = _same_or_owed(self.fields.get(key),
                                            other.fields.get(key))
        for key in set(self.goo) | set(other.goo):
            out.goo[key] = _same_or_owed(self.goo.get(key), other.goo.get(key))
        for key in set(self.field_pollen) | set(other.field_pollen):
            out.field_pollen[key] = _same_or_owed(self.field_pollen.get(key),
                                                  other.field_pollen.get(key))
        for key in set(self.goo_colour) | set(other.goo_colour):
            out.goo_colour[key] = _same_or_owed(self.goo_colour.get(key),
                                                other.goo_colour.get(key))
        # ONE REQUIREMENT IS A KIND AND A TARGET, not a kind: two quests can
        # ask for the same token. MEASURED 2026-10-07 (var/quests.json): honey
        # tokens 300/300 and 500/500, finished, beside Honey Bee's "Collect
        # 7,000 Honey Tokens. 3,908/7,000" -- keyed by kind, the furthest
        # reading was a finished one and the open 7,000 vanished from the
        # needs. A target misread by a digit now counts twice; that only
        # orders what is wanted, and feeds the same way.
        by_kind: dict = {}
        for need in list(self.tokens) + list(other.tokens):
            key = (need.kind, need.target)
            by_kind[key] = _furthest(by_kind.get(key), need)
        out.tokens = [by_kind[k] for k in sorted(by_kind)]
        by_item: dict = {}
        for need in list(self.feeds) + list(other.feeds):
            key = (need.item, need.target)
            by_item[key] = _furthest(by_item.get(key), need)
        out.feeds = [by_item[k] for k in sorted(by_item)]
        by_bloom: dict = {}
        for need in list(self.blooms) + list(other.blooms):
            key = (need.colour, need.field, need.target)
            by_bloom[key] = _furthest(by_bloom.get(key), need)
        out.blooms = [by_bloom[k] for k in sorted(by_bloom)]
        # DEDUPE ON THE WORDS, NOT THE PUNCTUATION. Two readings of one menu
        # differ by a full stop -- MEASURED 2026-09-23 04:56, the needs read
        # "2 combat step(s) ... Defeat 3 Spiders. 2/3; Defeat 3 Spiders 2/3",
        # which is one requirement counted twice.
        out.fights = _unique_lines(list(self.fights) + list(other.fights))
        out.handed = _unique_lines(list(self.handed) + list(other.handed))
        out.unread = _unique_lines(list(self.unread) + list(other.unread))
        return out

    @property
    def wanted_token_kinds(self) -> tuple:
        """Token kinds with tokens still outstanding, most needed first.

        Names are `data/knowledge/tokens.yaml` keys, because that is what
        `vision/tokens.Kinds.classify` returns and what the token brain
        weighs. A kind the table does not know is still returned -- the
        caller checks, so that a quest asking for something unrecognised is
        visibly ignored rather than silently dropped here.
        """
        live = [(n.remaining, n.kind) for n in self.tokens if n.remaining > 0]
        return tuple(kind for _, kind in sorted(live, reverse=True))

    @property
    def wanted_colours(self) -> tuple:
        """Colours with pollen still outstanding, most needed first."""
        live = [(n.remaining, c) for c, n in self.pollen.items()
                if n.remaining > 0]
        return tuple(colour for _, colour in sorted(live, reverse=True))

    def describe(self) -> str:
        bits = [n.describe() for n in self.pollen.values() if n.remaining > 0]
        for name, need in self.fields.items():
            if need.remaining > 0 and name not in self.goo:
                bits.append(f"{need.remaining:,} more pollen from "
                            f"{name.replace('_', ' ')}")
        for name, need in self.goo.items():
            if need.remaining > 0:
                bits.append(f"{need.remaining:,} more goo from "
                            f"{name.replace('_', ' ')} (gumdrops)")
        for colour, need in self.goo_colour.items():
            if need.remaining > 0:
                bits.append(f"{need.remaining:,} more goo from {colour} flowers (gumdrops)")
        # TOKEN STEPS ARE ACTIONABLE NOW. Chasing became real on 2026-09-21
        # and `vision/tokens.Kinds.classify` has named kinds since, so a step
        # naming a SPECIFIC token can be sought out rather than only bumped
        # into. `wanted_token_kinds` is what the brain weighs.
        for need in list(self.tokens) + list(self.feeds) + list(self.blooms):
            if need.remaining > 0:
                bits.append(need.describe())
        if self.fights:
            # "CANNOT DO" WAS TOO STRONG, and the menu proved it. MEASURED
            # 2026-09-23: "Defeat 3 Spiders" went 0/3, then 1/3, then 2/3
            # while the bot farmed the Spider Field -- it does not seek
            # combat and runs from what it sees, but the bees fight, and the
            # count rises. Saying "cannot do" about something that is
            # visibly progressing is the same kind of lie as a switch that
            # does nothing.
            # AND SINCE 2026-09-26 THE BOT GOES FOR THE FIELD MOBS among them
            # (act/bugrun, DESIGN 8do): a bug run after a convert, when
            # combat.bug_runs is on, for Ladybugs, Rhino Beetles, Spiders,
            # Mantises, Scorpions and Werewolves. Anything else -- the Ant
            # Challenge's ants, a boss -- is still only the bees' while it
            # gathers.
            bits.append(f"{len(self.fights)} combat step(s): the six field "
                        f"mobs among them get a bug run when combat.bug_runs "
                        f"is on, and the bees fight whatever comes near while "
                        f"it gathers, so the fields those mobs live in get the "
                        f"quest tilt: " + "; ".join(self.fights))
        if not bits:
            return "no quest requirements outstanding that this bot can read"
        return "; ".join(bits)


def mob_slug(name: str) -> str:
    """"Rhino Beetles" -> "rhino_beetle", the way world.yaml spells it.

    The menu says "Defeat 6 Rhino Beetles", "Defeat 2 Mantises", "Defeat 1
    Werewolf", and the field table says `rhino_beetle`, `mantis`, `werewolf`.
    A singular "Mantis" (a "Defeat 1 Mantis" step) keeps its s: a word in
    "-is" is not a plural, and taking the s off made it "manti", which
    act/bugrun's book does not know.
    """
    words = str(name or "").lower().strip().split()
    if not words:
        return ""
    last = words[-1]
    if last.endswith("ves"):                  # werewolves, wolves
        last = last[:-3] + "f"
    elif last.endswith(("ses", "xes", "ches", "shes")):   # mantises
        last = last[:-2]
    elif last.endswith("ies"):                # flies
        last = last[:-3] + "y"
    elif last.endswith("s") and not last.endswith(("ss", "is")):
        last = last[:-1]
    return "_".join(words[:-1] + [last])


def _unique_lines(lines) -> list:
    """Keep the first of each requirement, comparing the WORDS.

    Two readings of one menu differ by a full stop and by spacing, and a list
    keyed on the exact string then holds the same requirement twice.
    """
    out, seen = [], set()
    for line in lines:
        key = re.sub(r"[^a-z0-9/]+", "", str(line).lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _furthest(a, b):
    """Whichever of two readings of one requirement got further.

    A requirement with a bigger TARGET is preferred when the progress ties,
    because a misread target is usually a dropped digit and the larger figure
    is the one the menu drew. Progress wins over target, because progress is
    what the planner subtracts.
    """
    if a is None:
        return b
    if b is None:
        return a
    if b.remaining < a.remaining:
        return b
    if b.remaining == a.remaining and b.target > a.target:
        return b
    return a


def _same_or_owed(a, b):
    """Two readings of one field's (or colour's) need: `_furthest` when they
    are the same requirement (one target), else the one with more left.

    A FIELD IS NOT A REQUIREMENT. Two quests name one field, and a read of the
    first page of the menu holds only the top quests. MEASURED 2026-10-19
    (var/quests.json, 11:34): the whole list read "QR Quest -- Collect
    50,000,000 Pollen from the Bamboo Field. 33,299,774/50,000,000" and
    "Variety Fetcher 2 -- ... Pineapple Patch. 7,369,694/100,000,000", the two
    first-page transcripts only "Meditating On Phenomenon -- Collect 2,000,000
    Pollen from the Bamboo Field. Complete!" (and Pineapple, Strawberry...).
    `_furthest` kept the finished 2,000,000 as the furthest reading of
    "bamboo", so from 18 Oct 18:03 every trip's needs owed Bamboo, Pineapple
    and Strawberry nothing (var/trips.jsonl `context.quests.fields`), and the
    quest retry (brain/decide `_quest_retry`) never fired for Bamboo. Inside
    one read `from_lines` already keeps the larger remainder; this is the
    same rule across reads. ponytail: one target read two ways (a dropped
    digit `_target` cannot fix) now keeps the larger remainder, which errs
    toward a trip, not away from a quest.
    """
    if a is None or b is None or a.target == b.target:
        return _furthest(a, b)
    return a if a.remaining >= b.remaining else b


def from_lines(lines) -> Needs:
    """Read requirement lines. Anything unrecognised is dropped, not guessed.

    The lines are folded first, because the menu draws a requirement's
    progress on the line BELOW it and this used to read every requirement as
    untouched -- so the planner believed 1,816,181 red pollen were still
    wanted when 22,051 were. See `vision.questmenu.merge_progress`.
    """
    needs = Needs()
    for raw in questmenu.merge_progress(lines):
        line = " ".join(str(raw).split())
        if not line:
            continue

        # WHO TO HAND IT IN TO, recorded whatever kind of requirement it is.
        # Kept before the branches below, because a finished requirement is
        # otherwise dropped by every one of them -- a done fight is not added
        # to `fights`, a done token step has nothing remaining -- and the
        # giver's name would go with it.
        if READY_BANNER.match(line):
            # A BANNER IS NOT A REQUIREMENT. It is the menu's summary of a
            # quest that is finished, so it belongs with the hand-ins and
            # nowhere else -- see READY_BANNER and `ready_to_hand_in`.
            needs.handed.append(line)
            continue
        if DONE.search(line) and HAND_IN.search(line):
            needs.handed.append(line)

        if FIGHT.search(line):
            # A FINISHED FIGHT IS NOT SOMETHING IT CANNOT DO. The list is
            # there so a requirement this bot is unable to progress is SAID
            # rather than silently dropped, and a step already complete is
            # not one of those. MEASURED 2026-09-23, after the verdict-folding
            # of `questmenu.merge_progress`: the needs read "3 combat step(s),
            # which this bot cannot do: Defeat 3 Spiders. 1/3; Defeat 6
            # Ladybugs. Complete! Talk to Science Bear; Defeat 10 Scorpions.
            # Complete! ..." -- two of the three were done.
            if not DONE.search(line):
                needs.fights.append(line)
            continue
        bloom = BLOOM.search(line)
        if bloom:
            target = _target(line, _number(bloom.group(1)))
            if target is None:
                needs.unread.append(line)
            elif not DONE.search(line):
                needs.blooms.append(BloomNeed(
                    colour=bloom.group(2).lower(), target=target,
                    done=_progress(line, target),
                    field="_".join((bloom.group(3) or "").lower().split()), line=line))
            continue
        feed = FEED.search(line)
        if feed:
            target = _target(line, _number(feed.group(1)))
            if target is None:
                needs.unread.append(line)
            else:
                needs.feeds.append(FeedNeed(
                    item=" ".join(feed.group(2).lower().split()), target=target,
                    done=_progress(line, target), line=line))
            continue
        tokens = TOKENS.search(line)
        if tokens:
            target = _target(line, _number(tokens.group(1)))
            kind = "_".join(tokens.group(2).lower().split())
            if target is not None and kind:
                needs.tokens.append(TokenNeed(
                    kind=kind, target=target,
                    done=_progress(line, target), line=line))
            else:
                needs.unread.append(line)
            continue

        by_colour = GOO_COLOUR.search(line)
        if by_colour:
            target = _target(line, _number(by_colour.group(1)))
            if target is None:
                needs.unread.append(line)
                continue
            colour = by_colour.group(2).lower()
            need = Need(colour=colour, target=target, done=_progress(line, target))
            was = needs.goo_colour.get(colour)
            if was is None or need.remaining > was.remaining:
                needs.goo_colour[colour] = need
            continue

        goo = GOO.search(line)
        if goo:
            target = _target(line, _number(goo.group(1)))
            if target is None:
                needs.unread.append(line)
                continue
            name = "_".join(goo.group(2).lower().split())
            need = Need(colour=name, target=target, done=_progress(line, target))
            for kind in (needs.goo, needs.fields):
                was = kind.get(name)
                if was is None or need.remaining > was.remaining:
                    kind[name] = need
            continue

        from_field = FROM_FIELD.search(line)
        if from_field:
            target = _target(line, _number(from_field.group(1)))
            if target is not None:
                name = "_".join(from_field.group(2).lower().split())
                need = Need(colour=name, target=target,
                            done=_progress(line, target))
                # TWO QUESTS CAN WANT ONE FIELD, and the later line used to
                # replace the earlier. MEASURED 2026-09-27 13:07 (var/quests
                # .json): "Bamboo Boogie 2 ... Collect 30,000,000 Pollen from
                # the Bamboo Field. 13,720/30,000,000" was replaced by the
                # Polar Bear's "Collect 120,000 Pollen from the Bamboo Field.
                # Complete!", so the needs owed Bamboo nothing. Pollen gathered
                # there counts toward every quest that wants it at once, so
                # the field is owed the larger remainder.
                for kind in (needs.fields, needs.field_pollen):
                    was = kind.get(name)
                    if was is None or need.remaining > was.remaining:
                        kind[name] = need
            continue

        wants = WANTS.search(line)
        if not wants:
            needs.unread.append(line)
            continue
        target = _target(line, _number(wants.group(1)))
        if target is None:
            needs.unread.append(line)
            continue
        colour = wants.group(2).lower()

        existing = needs.pollen.get(colour)
        if existing is None or target > existing.target:
            needs.pollen[colour] = Need(colour=colour, target=target,
                                        done=_progress(line, target))
    return needs


def _target(line: str, stated) -> int | None:
    """The requirement's target, corrected for dropped thousands groups.

    MEASURED 2026-09-23 23:57:07 (run-341): the model transcribed "Collect
    4,750,000 Pollen from the Cactus Field. 0/4,750,000" as "Collect 4,750
    Pollen ... 0/4,750,000", and the Dandelion line the same way. The stated
    figure then became the target, `_progress` refused the pair because its
    total did not match, and `_furthest` -- which keeps whichever reading has
    less left -- let the misread beat the clean read of the same menu: the
    planner was told the quests wanted 4,750 and 1,500 pollen, not millions.

    The correction is deliberately narrow: only when a progress pair on the
    SAME line has a total that is exactly the stated figure times 1,000 or
    1,000,000. A backpack figure run onto the line (see `_progress`) is never
    an exact thousand-multiple of the stated target, so it cannot trigger it.
    """
    if stated is None:
        return None
    for _got, outof in PROGRESS.findall(line):
        total = _number(outof)
        if total and stated and total in (stated * 1000, stated * 1000000):
            return total
    return stated


def _progress(line: str, target: int) -> int:
    """How far along, from "142,504/820,020" or "Complete.".

    The pair is only believed when its total matches the stated target. A real
    transcription ran the backpack HUD onto the end of a quest line --
    "Collect 1,500,000 Red Pollen. 752,395/1,500,000; 526697/948750" -- and
    taking the last pair would have reported the backpack as quest progress.
    """
    for head, group, outof in CHAIN.findall(line):
        if _number(outof) == target:
            got = (_number(head) or 0) * 1000 + int(group)
            if got <= target:
                return got
    for got, outof in PROGRESS.findall(line):
        if _number(outof) == target:
            return _number(got) or 0
    return target if DONE.search(line) else 0



# ---------------------------------------------------------------- one step --
@dataclass
class Step:
    """One requirement line, with its progress pulled out.

    WHY THIS EXISTS. The quest MENU gives a heading and a list of requirement
    lines; it does not name the bear who gave the quest. The GUI's quest panel
    was written around `giver`, and `QuestsPanel.update_quest` dropped any
    event whose giver was empty -- which was every single one, so the Quests
    tab was empty all night while `var/quests.json` sat on disk full of them.
    The owner noticed: "the quests arnt being picked up on".

    So a step carries what the screen actually gives: the quest it belongs to,
    the requirement text, and the numbers when they are there. `done == total`
    only when the line says Complete or the pair says so -- never inferred.
    """
    quest: str = ""
    text: str = ""
    done: int = 0
    total: int = 0
    complete: bool = False

    @property
    def fraction(self) -> float:
        if self.complete:
            return 1.0
        return (self.done / self.total) if self.total else 0.0


def steps_of(quest_name: str, requirements) -> list:
    """Every requirement of one quest as a `Step`, progress parsed.

    Lines with no number at all still become steps -- "Polar Bear: Candied
    Beetles" is a real part of the list and hiding it would make the quest look
    shorter than it is. They simply carry no total.
    """
    out = []
    for line in questmenu.merge_progress(requirements):
        text = " ".join(str(line).split())
        if not text:
            continue
        # THE BACKPACK HUD LEAKS INTO THE TRANSCRIPTION. A real read ended with
        # a bare "868938/948750", which is the pollen pill sitting behind the
        # menu, not a quest requirement. A line with no letters in it is never
        # a step -- `Needs` already routes these to `unread`, and they must not
        # become a 92%-complete quest row in the GUI.
        if not any(c.isalpha() for c in text):
            continue
        # NOR IS THE MENU'S READY BANNER A STEP. It sits at the bottom of the
        # screen under whichever quest happens to be last, so drawn as a
        # requirement it becomes a row of someone else's quest: "Earn 2
        # Bamboo Badges — Polar Bear: Spooky Stew* is ready to turn in!".
        # `Needs` files it as a hand-in, which is what it is.
        if READY_BANNER.match(text):
            continue
        done_flag = bool(DONE.search(text))
        total = 0
        done = 0
        pairs = PROGRESS.findall(text)
        if pairs:
            got, outof = pairs[0]
            done, total = _number(got) or 0, _number(outof) or 0
        else:
            # "Collect 320,020 Pollen ..." with no pair yet: the target is the
            # first number on the line, and nothing has been collected.
            #
            # THE FIRST NUMBER, not the first number a pattern here happens to
            # know. This used to try WANTS and FIGHT only, so every
            # "Collect 150,000 Pollen from the Strawberry Field. Complete!"
            # -- a requirement shape with no colour in it -- came out with no
            # total at all, and the GUI drew a finished step as an empty bar.
            total = questmenu.stated_target(text) or 0
        if done_flag:
            done = total or done
        # The folded "got/total" is carried in `done` and `total`, so it is
        # taken off the end of the words -- the GUI draws the numbers beside
        # the bar and "Collect 6,000,000 Pollen 1,497,207/6,000,000" reads
        # like a mistake. The unedited transcript is kept in var/quests.json
        # and published as a belief, so nothing is lost.
        shown = re.sub(r"\s*[\d][\d,.]*\s*/\s*[\d][\d,.]*\s*$", "", text).strip()
        out.append(Step(quest=quest_name, text=shown or text, done=done,
                        total=total, complete=done_flag))
    return out


# ------------------------------------------------ ready until handed in --
# TWO GIVERS ARE NAMED BY THEIR NPC'S FULL NAME. "Bucko Bee: Scavenge ...
# Complete! Talk to Gifted Bucko Bee." (the whole-list read, 2026-09-30 23:39).
# BSS wiki, Gifted_Bucko_Bee (read 2026-10-01): "This page is for the
# quest-giving NPC ... located on the second floor of the Blue HQ", one of three
# permanent Quest Bees with Gifted Riley Bee and Honey Bee -- the NPC the
# `bucko_bee` route walks to, whose prompt reads "Talk to Gifted Bucko Bee"
# (var/bear_panels.json). Under the full name the hand-in had no route, and the
# finished quest waited from 23:39 to morning.
GIVER_ALIASES = {"gifted_bucko_bee": "bucko_bee", "gifted_riley_bee": "riley_bee"}
# A NAME CUT OFF AT THE PANEL'S EDGE IS ITS GIVER'S. MEASURED 2026-10-14 (var/
# quests.json): "Liquid Motivation" read "Complete! Talk to Dapper Bear." on four
# requirements and "Complete! Talk to Dapper" on the fifth, and the hand-in queue
# carried the one quest twice, as `dapper_bear` (23:29) and `dapper` (02:11).
# The quest givers' node names (wiki Quest_Givers; data/knowledge/quests.yaml):
# a name that is the first word(s) of exactly one of them is that one.
QUEST_GIVERS = ("black_bear", "brown_bear", "polar_bear", "panda_bear", "science_bear",
                "mother_bear", "spirit_bear", "dapper_bear", "honey_bee",
                "gifted_bucko_bee", "gifted_riley_bee", "bucko_bee", "riley_bee", "onett")


def giver_name(name) -> str:
    """`name` ("dapper", "Gifted Bucko Bee", "black_bear") as the node name the
    routes and the hand-in queue use: a cut-off name completed (QUEST_GIVERS),
    then GIVER_ALIASES."""
    name = "_".join(str(name or "").lower().replace("_", " ").split())
    if name and name not in QUEST_GIVERS:
        whole = [g for g in QUEST_GIVERS if g.startswith(name + "_")]
        if len(whole) == 1:
            name = whole[0]
    return GIVER_ALIASES.get(name, name)


def _giver_of(line: str) -> str:
    """The node name of the giver a hand-in line names, or ''.

    Only for lines already known to be hand-ins: a ready banner, or a
    "Complete! Talk to <giver>" requirement (see `from_lines`).
    """
    banner = READY_BANNER.match(line)
    if banner:
        # "is ready for Black Bear" names the giver outright. "is ready to
        # turn in!" does not, and does not need to: the quest's own name is
        # "Polar Bear: Spooky Stew", and the part before the colon is who gave
        # it. A name with no colon and no giver is recorded and skipped rather
        # than guessed at -- "Strawberry Field Forever" says nothing about who
        # wants it.
        who = banner.group("giver") or ""
        if not who:
            quest = banner.group("quest") or ""
            who = quest.split(":", 1)[0] if ":" in quest else ""
    else:
        m = HAND_IN.search(line)
        who = m.group(1) if m else ""
    return giver_name(who)


def title_key(text) -> str:
    """A quest title reduced to lowercase letters and digits, for comparing
    two readings of it.

    MEASURED 2026-09-23 in consecutive reads of one unchanged menu:
    "Earn 2 Bamboo Badges." then "Earn 2 Bamboo Badges", and "Collect 2,500
    Honey Tokens." then "Collect 2500 Honey Tokens." (run-334.log:36 and 38,
    run-335.log:37 and 39). The ready banner keeps the game's asterisks unevenly:
    "Strawberry Field Forever* is ready for Black Bear" (run-335.log:39).
    """
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _at(entry) -> float:
    try:
        return float((entry or {}).get("at") or 0.0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def answered_since(dialogues, giver: str, at: float) -> bool:
    """Was a dialogue read at `giver` after `at`? See DIALOGUE_READ_AT."""
    record = (dialogues or {}).get(giver) if isinstance(dialogues, dict) else None
    if not isinstance(record, dict):
        return False
    try:
        return float(record.get(DIALOGUE_READ_AT) or 0.0) > float(at or 0.0)
    except (TypeError, ValueError):
        return False


def _entries(raw) -> dict:
    """A `ready_since` mapping off disk, with anything malformed dropped."""
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for giver, entry in raw.items():
        if not isinstance(entry, dict) or not title_key(entry.get("quest")):
            continue
        # under the name the route knows (`giver_name`); a file written
        # before the alias may hold both, and the earlier wait is the true one
        key = giver_name(giver)
        at = _at(entry)
        if key in out and _at(out[key]) <= at:
            continue
        out[key] = {"quest": str(entry.get("quest")), "at": at}
    return out


def _part(quest, key: str):
    """A field of a quest from `questmenu.parse` or from var/quests.json."""
    if isinstance(quest, dict):
        return quest.get(key)
    return getattr(quest, key, None)


def ready_titles(quests) -> dict:
    """Giver -> the title of the quest the menu shows finished for them.

    The same two shapes `from_lines` files under `handed`: the ready banner,
    whose own words carry the title, and "Complete! Talk to <giver>" on a
    requirement, whose title is the heading it sits under. A giver with no
    title is left out: nothing could later say whether its quest is still
    listed.
    """
    out: dict = {}
    for quest in quests or ():
        name = " ".join(str(_part(quest, "name") or "").split())
        lines = [name] + list(questmenu.merge_progress(
            list(_part(quest, "requirements") or ())))
        for raw in lines:
            line = " ".join(str(raw).split())
            if not line:
                continue
            banner = READY_BANNER.match(line)
            if banner:
                title = banner.group("quest") or ""
            elif DONE.search(line) and HAND_IN.search(line):
                title = name
            else:
                continue
            title = title.strip(" *\"'")
            who = _giver_of(line)
            if who and title_key(title) and who not in out:
                out[who] = title
    return out


def _visibly_unfinished(quests, title: str) -> bool:
    """Does this read show `title` with a requirement short of its target?

    A progress pair counts only when its total is the line's own stated
    target, so a backpack HUD run onto the line (see `_progress`) cannot
    count. MEASURED 2026-09-23: "Honey Bee's Honey Hunt" was finished at
    04:34 ("Collect 2,000 Honey Tokens. Complete! Talk to Honey Bee.") and
    was back under the same title at 19:53 as "Collect 2,500 Honey Tokens.
    715/2,500" (run-325.log:35). A title that is still listed is not proof
    the SAME quest is still waiting.
    """
    key = title_key(title)
    for quest in quests or ():
        if title_key(_part(quest, "name")) != key:
            continue
        for raw in questmenu.merge_progress(
                list(_part(quest, "requirements") or ())):
            line = " ".join(str(raw).split())
            if not line or DONE.search(line):
                continue
            target = questmenu.stated_target(line)
            for got, outof in PROGRESS.findall(line):
                have, total = _number(got), _number(outof)
                if (target and total == target and have is not None
                        and have < total):
                    return True
    return False


def carry_ready(previous, quests, transcripts, dialogues, now: float,
                whole: bool | None = None):
    """`ready_since` for the quest file this read is about to write, and one
    note per giver saying why it is in or out. DESIGN 8dh.

    `previous` is the file being replaced (a dict; {} when there is none),
    `quests` what this read parsed, `transcripts` every transcription of the
    open menu, `dialogues` var/bear_dialogues.json as a dict.

    A giver this read shows finished is in, dated by the first read that
    showed the same title finished. A giver only an earlier read showed
    finished stays in while one of this read's transcriptions still lists
    the title (`title_key`), until a dialogue is read there after its date
    (`answered_since`) or this read shows the title short of a target
    (`_visibly_unfinished`). Only a read that parsed at least one quest gets
    here -- the caller writes the file on no other -- so a menu that did not
    open cannot clear anything. Nor can a read that stopped short of the
    list's end (`whole` False, act/quests QuestRead.whole) clear a title by
    not listing it.
    """
    previous = previous if isinstance(previous, dict) else {}
    was: dict = {}
    # A file written before `ready_since` existed: its own finished quests,
    # dated by its read.
    try:
        read_then = float(previous.get("read_at") or 0.0)
    except (TypeError, ValueError):
        read_then = 0.0
    for giver, title in ready_titles(previous.get("quests") or ()).items():
        was[giver] = {"quest": title, "at": read_then}
    was.update(_entries(previous.get("ready_since")))

    parsed = list(quests or ())
    for text in transcripts or ():
        try:
            parsed.extend(questmenu.parse(str(text)))
        except Exception:
            continue
    fresh = ready_titles(parsed)
    listed = title_key(" ".join(
        [str(t) for t in transcripts or ()]
        + [str(_part(q, "name") or "") for q in parsed]))

    def clock(at: float) -> str:
        return time.strftime("%H:%M", time.localtime(at)) if at else "an unknown time"

    out: dict = {}
    notes: list = []
    for giver, title in fresh.items():
        old = was.get(giver)
        pretty = giver.replace("_", " ")
        if (old and title_key(old["quest"]) == title_key(title)
                and not answered_since(dialogues, giver, old["at"])):
            out[giver] = old
            notes.append(f"{pretty}: '{title}' still shows finished — "
                         f"waiting since {clock(old['at'])}")
        else:
            out[giver] = {"quest": title, "at": float(now)}
            notes.append(f"{pretty}: '{title}' shows finished — first seen "
                         f"on this read")
    for giver, old in was.items():
        if giver in out:
            continue
        pretty = giver.replace("_", " ")
        if answered_since(dialogues, giver, old["at"]):
            notes.append(f"{pretty}: '{old['quest']}' dropped — a dialogue "
                         f"was read there after {clock(old['at'])}")
            continue
        if title_key(old["quest"]) not in listed:
            # MEASURED 2026-10-06 10:12 (run-680): the list's scroll stopped
            # after 4 pages ("a page matched the one before it only 0.86"), 7 of
            # the 10 quests were read, and "Fire Fighter" -- finished, waiting
            # for the Panda since 06:58 -- was dropped, which also stopped his
            # ladder survey (run_farm, the early step).
            if whole is False:
                out[giver] = old
                notes.append(f"{pretty}: '{old['quest']}' kept — this read stopped "
                             f"short of the list's end, so its not listing it says "
                             f"nothing (waiting since {clock(old['at'])})")
                continue
            notes.append(f"{pretty}: '{old['quest']}' dropped — this read "
                         f"no longer lists it")
            continue
        if _visibly_unfinished(parsed, old["quest"]):
            notes.append(f"{pretty}: '{old['quest']}' dropped — this read "
                         f"shows it short of a target, so it was handed in "
                         f"and issued again, or never finished")
            continue
        out[giver] = old
        notes.append(f"{pretty}: '{old['quest']}' kept — still listed and "
                     f"not handed in, though this read shows no 'Complete!' "
                     f"for it (waiting since {clock(old['at'])})")
    return out, notes


def load(path) -> Needs:
    """Read the quests the bot last saw. Missing or broken file -> no needs.

    EVERY TRANSCRIPTION OF THE SAME MENU IS USED, and merged by taking the
    FURTHEST progress for each requirement. `act/quests` transcribes the open
    menu twice (`READS`); the quest state cannot change between two frames a
    moment apart, so a difference between them is a transcription miss and the
    better reading is the true one.

    MEASURED 2026-09-23: one read wrote "Collect 3,000,000 White Pollen" with
    no verdict where an earlier read of the same quest had "...  Complete!".
    A single read decides the whole session, and a requirement whose
    "Complete!" is missed reads as entirely outstanding, which pulls the
    planner toward fields for pollen it does not need.
    """
    path = Path(path)
    if not path.exists():
        return Needs()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return Needs()
    lines = []
    for quest in data.get("quests") or []:
        lines.extend(quest.get("requirements") or [])
    needs = from_lines(lines)
    for extra in data.get("transcripts") or ():
        needs = needs.merged_with(from_lines(str(extra).splitlines()))
    needs.read_at = float(data.get("read_at", 0.0) or 0.0)
    # What earlier reads saw finished and nothing has handed in yet. Written
    # by `carry_ready`; a file from before it simply has none.
    needs.ready_since = _entries(data.get("ready_since"))
    return needs


# THE QUESTS THAT COME FIRST AMONG THE QUESTS. The owner's guide (data/knowledge/
# guides/blue_hive_guide.md, "Polar Power"): every Polar Bear quest completed is
# 1.05x max bee energy for good, with no limit -- "start macroing polar now",
# 1,500 the minimum goal. So a field a Polar Bear quest names goes ahead of the
# other quest fields (brain/decide Planner.priority_needs).
PRIORITY_GIVERS = ("Polar Bear",)


def load_priority(path, givers=PRIORITY_GIVERS) -> Needs:
    """The needs of only the quests whose name starts with one of `givers`
    ("Polar Bear: Ladybug Poppers"). Missing or broken file -> no needs."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return Needs()
    lines = [line for quest in data.get("quests") or [] if isinstance(quest, dict)
             and str(quest.get("name") or "").strip().startswith(tuple(givers))
             for line in quest.get("requirements") or []]
    return from_lines(lines)

