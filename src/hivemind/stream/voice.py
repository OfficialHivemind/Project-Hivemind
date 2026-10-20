"""The stream's voice: what the bot really does, said out loud with some life in it.

THE OWNER'S ASK, 2026-09-28: text to speech, saying where the AI is going and
what it is thinking; and then more entertainment for viewers -- something that
grabs their attention, keeps them watching and gets them to subscribe.

THE RULE IS THE STREAM'S (stream/extras): every line is built from something
the bot did or decided -- the same gated events the commentary line and the
toasts read, after stream/privacy -- and the personality is in how it is
said, never in what. "Next stop, Pine Tree!" only after the planner chose Pine
Tree; "3.4 million honey, cha-ching!" only for a convert the stream saw; a
call to chat only names what the stream really answers (stream/show `_help`).

WHAT IT SAYS AND WHEN:

  events     the trip's field and the planner's reason, a cannon launch, the
             landing, the bag nearly full, the honey banked, a token chase, a
             mob the reward feed says went down, a boss, a knock-out, a
             quest handed in, a record, a streak, an errand -- as they
             happen, each in one of several phrasings, never the same one
             twice running;
  the room   when it has been quiet for QUIET_S and ENGAGE_EVERY_S has passed
             since the last: a welcome, what chat can do, a like, a subscribe.

A line waits at least GAP_S after the last one started, and the player only
asks for the next when the last has finished; a newer event beats an older
routine line; nothing older than its STALE_S is said at all -- a voice a
minute behind the picture is worse than silence. No Qt: gui/stream_voice
speaks what `next_line` hands it.
"""
from __future__ import annotations

import collections
import random
import re
import time
from dataclasses import dataclass

from ..telemetry.events import Considered, Log, TaskUpdate, Thought
from . import thinking
from .banter import BEE_FACTS, JOKES, QUIPS, Deck
from .show import CANNON_WORDS

# ---- the rhythm -----------------------------------------------------------------
GAP_S = 6.0                 # from the start of one line to the next
QUIET_S = 18.0              # this long with nothing said, and the room gets a line
ENGAGE_EVERY_S = 480.0      # at most one line for the room this often
FIRST_ENGAGE_S = 45.0       # the welcome, this long after the window opens
REPEAT_S = 90.0             # the same words are not said again within this
# ONCE IN A WHILE, NOT EVERY TIME. THE OWNER, 2026-10-06: it kept repeating
# itself. MEASURED in var/stream_voice.txt over 16 minutes: "Quest check: Defeat
# 100 Fire Ants, 73 of 100 done." four times and the Red Field Booster's three --
# a status line is a "room" line, which REPEAT_S never held -- and a token line
# for nearly every chase, eight in sixteen minutes. So a status line's same words
# wait STATUS_REPEAT_S, and the chases are said at most once a TOKEN_EVERY_S
# (the 5th, 10th... still are, `token_count`).
STATUS_REPEAT_S = 1200.0
TOKEN_EVERY_S = 300.0
TOKEN_KINDS = ("token", "token_any")
EVENT, ROUTINE, ROOM = 3, 2, 1
# CHAT'S ANSWERS FIRST: a viewer who asked is waiting to hear it (the owner:
# unanswered questions bore viewers).
ASK = 4
STALE_S = {ASK: 30.0, EVENT: 20.0, ROUTINE: 10.0, ROOM: 30.0}
MOST_WAITING = 6
# THE BANTER (stream/banter; the owner asked for an entertaining AI): a joke, a
# quip or a bee fact when it has been
# quiet for QUIET_S, at most this often, while the bot is really playing.
# THE OWNER, 2026-09-29: less joking, more about what it is doing and wants.
# So a quiet
# stretch is filled first with what the bot is doing and wants (STATUS_EVERY_S,
# `_status`) and its reasoning as it happens (stream/thinking), and a joke only
# now and then.
BANTER_EVERY_S = 600.0
FIRST_BANTER_S = 300.0
STATUS_EVERY_S = 60.0
FIRST_STATUS_S = 30.0
# AND EVERY HALF HOUR, A LOOK BACK: the honey the converts banked (the stream's
# own "Converted +3.6M" toasts), the trips, the bugs the reward feed named and
# the tokens chased since the last one -- said only when a trip was banked.
SUMMARY_EVERY_S = 1800.0
UNITS = {"": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
# STUCK (world/bearings: "· pushing against something for Ns" on the compass
# line): a quip once the push has lasted this long, one more past the second,
# and at most one such episode said this often.
STUCK_QUIP_S = 15
STUCK_LONG_S = 60
STUCK_EVERY_S = 240.0
PUSHING = re.compile(r"pushing against something for (\d+)s")
# A running count, said at these: the mobs the reward feed says went down
# (one count per kind of mob) and the token chases since the window opened.
KILL_COUNTS = (3, 5, 10, 20, 30, 50, 75, 100)
CHASE_COUNTS = (5, 10, 25, 50, 100)

# act/chase: "chasing a token at ..." or "chasing a baby love token at ..."
CHASING = re.compile(r"^chasing (?:an? (.+?) token|a token)\b")
WHERE_FIELD = re.compile(r"^I am in the (.+?) field\b")
# the reward feed's own word that a mob went down (run_farm's feed reader)
DEFEATED = re.compile(r"^reward feed: an? (.+?) was defeated\b")
AMOUNT = re.compile(r"\+?([\d.]+)\s*([KMBT]?)\b")
SUFFIX = {"": "", "K": " thousand", "M": " million", "B": " billion", "T": " trillion"}

# ---- what it says -----------------------------------------------------------------
# Several ways to say each thing; `{...}` are facts from the event. Short: a
# line of 6-12 words is 2-4 s of speech, and the next event is rarely further
# off than that while travelling.
SAY = {
    "next": ["Next stop, {field}!",
             "Plotting a course for {field}.",
             "{field}, here I come!",
             "{field}, you're next! Get ready.",
             "Pack your bags, bees. We're going to {field}."],
    "next_why": ["Next stop, {field}, {why}.",
                 "Alright, {field} it is, {why}.",
                 "{field}, here I come, {why}."],
    # `because` is a whole sentence from the planner's own reason (`because_of`)
    "next_because": ["Next stop, {field}! {because}.",
                     "Heading for {field}. {because}.",
                     "{field} it is. {because}."],
    "cannon": ["Cannon launch! Wheee!",
               "Into the cannon we go!",
               "Firing myself out of a cannon. Totally normal bee stuff.",
               "Hold on to your antennae, cannon time!",
               "Three, two, one, yeet!",
               "Bee cannonball, coming through!",
               "I'm flying! Well, falling with style."],
    "walk": ["Off to {field}. Bees, follow me!",
             "Walking to {field}. Great day for it.",
             "On my way to {field}.",
             "Walking to {field}. My legs are small, but my dreams are big.",
             "To {field}! Bees, try to keep up."],
    "landed": ["Touchdown in {field}!",
               "Made it to {field}. Time to gather!",
               "{field}, we have arrived.",
               "Landed in {field}. Let's get that pollen.",
               "{field}! Nailed the landing. Probably.",
               "Hello, {field}! Did you miss me?"],
    "half": ["Backpack's half full.",
             "Halfway there!",
             "Half a bag already. Keep it coming, bees.",
             "Half full. Not half empty. I'm an optimist."],
    "nearly": ["Almost full! One more lap.",
               "Bag's nearly stuffed.",
               "Ninety percent! Nearly time for honey.",
               "This backpack is getting heavy. Good heavy."],
    "convert": ["Bag's full! Back to the hive to make honey.",
                "Heading home to turn this pollen into honey.",
                "Full backpack. Honey time!",
                "Honey time! My favourite time of the day. Every time."],
    "banked": ["{amount} honey banked! Cha-ching!",
               "Ka-ching! {amount} honey in the bank.",
               "Another {amount} honey. Not bad, not bad.",
               "{amount} honey from that trip. Let's go!",
               "{amount} honey! Put it on my tab.",
               "{amount} honey! The bees want a raise."],
    "big": ["Whoa, a big one! {amount} honey!",
            "{amount} honey! That's one of my best trips lately!"],
    "best": ["New best trip of the day! {amount} honey!",
             "Personal best today! {amount} honey!"],
    "streak": ["{what}. I'm on a roll!",
               "{what}. Nobody can stop me!"],
    "token": ["Ooh, a {kind} token! Mine!",
              "Shiny {kind} token, coming right up.",
              "I see a {kind} token. Grabbing it!"],
    "token_any": ["Ooh, a token! Mine!",
                  "Token spotted! Going for it.",
                  "Shiny token over there. Grabbing it!",
                  "Is that a token? It's a token! Finders keepers!"],
    "boss": ["Whoa, a {boss}! Everybody stay calm.",
             "Boss alert! {boss} spotted!",
             "Uh oh. That's a {boss}.",
             "A {boss}! This is fine. Everything is fine."],
    "death": ["Ouch! Knocked out. I'll be back.",
              "Down I go! Back to the hive.",
              "That one got me. Respawning!",
              "I'm okay! Mostly. Respawning.",
              "That wasn't a knock-out. That was a nap."],
    "quest": ["Quest handed in{where}! On to the next one.",
              "Quest complete{where}! The bears will be pleased."],
    "errand": ["Quick stop at the {place}.",
               "Grabbing freebies from the {place}.",
               "{place}, don't mind if I do."],
    "milestone": ["Milestone! {what}!",
                  "We did it! {what}!"],
    "rejoin": ["Rejoining the server. Back in a moment!",
               "Quick rejoin, don't go anywhere!",
               "Rejoining. The server and I need a little chat."],
    "kill": ["Take that, {mob}!",
             "{mob} defeated! Bees for the win.",
             "Bye bye, {mob}!",
             "Another {mob} down!",
             "{mob}, you have been bee-feated!"],
    "kill_count": ["That's {count} {mobs} down! They never learn.",
                   "{count} {mobs} this stream! Somebody warn the others.",
                   "{mobs} defeated: {count}. The bees are unstoppable!"],
    "token_count": ["Token number {count} this stream! Mine, all mine!",
                    "That's {count} tokens I've gone after. I have a problem. A shiny problem."],
    # world/bearings says it is pushing against something (see STUCK_QUIP_S)
    "stuck": ["This wall and I are having a little disagreement.",
              "I'm not stuck. I'm just very determined.",
              "Ah yes, the classic walk-into-a-wall strategy.",
              "Wall one, me zero. Rematch!"],
    "stuck_long": ["Still pushing. Persistence is key!",
                   "This wall is really testing me today.",
                   "Okay wall, you win this round."],
    "ants": ["Ant Challenge time! Let's squash some ants.",
             "Into the Ant Challenge. Ants, beware!"],
    # YouTube's own count going up (stream/subs): nobody is named -- the
    # count says someone subscribed, not who
    "subs": ["Someone just subscribed! Welcome to the hive! That's {count}, only {left} to go to {goal}!",
             "New subscriber! Thank you so much! {count} down, {left} to go!",
             "Another bee joins the swarm! {count} subscribers, {left} more to {goal}!"],
    "subs_many": ["{new} new subscribers! Thank you! That's {count}, only {left} to go to {goal}!"],
    "subs_goal": ["We just hit {reached} subscribers! Thank you all so much! Next stop, {goal}!",
                  "{reached} subscribers! We did it! Thank you! Now, on to {goal}!"],
}
# The room's "subscribe" line once YouTube has said a count: the real number,
# and how close the goal is.
SUBSCRIBE_WITH_COUNT = ("We're at {count} subscribers, only {left} away from {goal}! "
                        "If you're enjoying a bee bot grinding honey, hit subscribe!")
# The room: the welcome first, then the rest in turn. `needs` names the
# setting that must be on for the line to be true (the stream answers it), and
# the words are the ones the stream reads: "!stats", "!why", "!yes"/"!no"
# (stream/show `_help`), a bare "jump" (stream/jump), a "W" (stream/wrain).
ROOM_LINES = [
    ("welcome", "", "Welcome in! I'm an AI playing Bee Swarm Simulator all by myself. Nobody is touching the controls."),
    # the words are made from the quest menu as last read (`quest_file`)
    ("quest", "", ""),
    ("predict", "stream.chat_games", "Think this trip will beat the last one? Type exclamation mark yes, or no, in chat, and climb the leaderboard."),
    ("subscribe", "", "If you're enjoying a bee bot grinding honey, hit subscribe. It really helps!"),
    ("why", "stream.chat_games", "Type exclamation mark why in chat, and I'll tell you why I picked this field."),
    ("jump", "stream.chat_may_jump", "Type jump in chat, and I'll jump. I'm serious."),
    ("like", "", "Drop a like if you think I'll hit a billion honey!"),
    ("rain", "stream.chat_w_rain", "Spam W in chat for a W rain!"),
    ("stats", "stream.chat_games", "Type exclamation mark stats in chat to see how much honey I've made."),
    ("ask", "stream.chat_ask", "Got a question? Type exclamation mark ask, then your question, and I'll answer it!"),
    ("quest", "", ""),
]


# THE PLANNER'S OWN REASON, said as a sentence. Its `why` is clauses joined
# by ";" -- MEASURED over run-500..529, nine kinds: the measured rate, the
# colour share, a quest's mobs that live there, a quest's pollen from there, a
# quest's red pollen, the route's landings, the guards, the knock-outs there,
# quests.first. The first of these that is present is the one said: a quest
# is the story, the rate is the fact, the colour is the fallback.
RED_REASON_AT = 40          # percent red before the red quest is the reason
REASONS = [
    (re.compile(r"a quest wants ([\d,]+) more (.+?) defeated and they live here"),
     lambda m: f"A quest wants {m.group(1)} more {_plural(m.group(2))} defeated, and they live there"),
    (re.compile(r"a quest needs only ([\d,]+) more pollen from here — about \d+ min, one trip finishes it"),
     lambda m: f"A quest needs only {_amount(m.group(1))} more pollen from there, so one trip finishes it"),
    (re.compile(r"a quest wants ([\d,]+) more pollen from here"),
     lambda m: f"A quest wants {_amount(m.group(1))} more pollen from there"),
    # said only of a field that is mostly red: the planner names the red quest
    # for every field (a bonus by share), and "2 percent red" is not a reason
    (re.compile(r"(\d+)% of its flowers are red, and the quests still want ([\d,]+) red pollen"),
     lambda m: (f"It's {m.group(1)} percent red, and my quests still want "
                f"{_amount(m.group(2))} red pollen") if int(m.group(1)) >= RED_REASON_AT else ""),
    (re.compile(r"measured ([\d,]+) pollen/s"),
     lambda m: f"It made about {_amount(m.group(1), rate=True)} pollen a second last time"),
    (re.compile(r"(\d+)% of its pollen is a colour these bees are good at"),
     lambda m: f"{m.group(1)} percent of its pollen is my bees' favourite colour"),
]


def _plural(mobs: str) -> str:
    # the planner's own plural is naive ("mantiss"): the word as a voice says it
    return re.sub(r"\bmantiss\b", "mantises", str(mobs).replace("_", " "))


def _amount(digits: str, rate: bool = False) -> str:
    """"15,200,000" -> "15.2 million"; a rate to two figures ("3,173" ->
    "3,200"), because "three thousand one hundred and seventy-three" is not
    something anyone listens to."""
    try:
        value = float(str(digits).replace(",", ""))
    except ValueError:
        return str(digits)
    if value >= 1e6:
        return spoken_amount(f"{value / 1e6:.3g}M")
    if rate and value >= 100:
        value = float(f"{value:.2g}")
    return f"{value:,.0f}"


def _count(n: int) -> str:
    """A quest's count as it is said: 4,000,000 -> "4 million", 886,637 ->
    "887 thousand", 15 -> "15"."""
    if n >= 1_000_000:
        return spoken_amount(f"{n / 1e6:.3g}M")
    if n >= 10_000:
        return f"{n / 1000:.0f} thousand"
    return f"{n:,}"


def because_of(rationale: str) -> str:
    """The planner's reason as one sentence, or "" when none is said."""
    text = str(rationale or "")
    for pattern, say in REASONS:
        m = pattern.search(text)
        if m and say(m):
            return say(m)
    return ""


def title(slug: str) -> str:
    """"pine_tree" -> "Pine Tree"."""
    return " ".join(w[:1].upper() + w[1:] for w in str(slug or "").replace("_", " ").split())


def plural(name: str) -> str:
    """"Spider" -> "Spiders", "Werewolf" -> "Werewolves", "Mantis" -> "Mantises"."""
    name = str(name or "").strip()
    if not name:
        return name
    if name.endswith("f"):
        return name[:-1] + "ves"
    if name.endswith(("s", "x", "ch", "sh")):
        return name + "es"
    return name + "s"


def spoken_amount(text: str) -> str:
    """"+2.55M" -> "2.55 million", "+850K" -> "850 thousand"; the text as it
    came when it holds no amount."""
    m = AMOUNT.search(str(text or ""))
    if not m:
        return str(text or "")
    number = m.group(1).rstrip(".")
    return f"{number}{SUFFIX.get(m.group(2), '')}"


@dataclass
class Line:
    text: str
    priority: int
    at: float
    kind: str


class Announcer:
    """`hear(event)` and `toasted(toast)` after the privacy gate; ask
    `next_line(now)` when the voice is free."""

    def __init__(self, get=lambda key: None, clock=time.time, rng=None,
                 chat_live=lambda: False, playing=lambda: True):
        self.get = get
        # A call to chat is only made while the stream is reading chat: a
        # line inviting "type jump" with nobody listening is a false promise.
        self.chat_live = chat_live
        # And the room is only talked to while the bot is really playing:
        # "nobody is touching the controls" said while the owner plays by hand
        # (or with the bot paused) would be a lie on their stream.
        self.playing = playing
        self.clock = clock
        self.rng = rng or random.Random()
        self.opened = clock()
        self.waiting: list[Line] = []
        self.last_at: float | None = None       # when the last line was handed out
        self.said: dict[str, float] = {}         # words -> when
        self.last_template: dict[str, str] = {}
        self.token_said_at: float | None = None  # TOKEN_EVERY_S
        self.room_at: float | None = None
        self.room_next = 0
        self._field = ""
        self._why = ""
        self._landing = False
        self._fill_said = set()
        self.quests: list = []                   # stream/extras QuestBar, closest first
        self._quest_i = 0
        self.banter = Deck(JOKES, QUIPS, BEE_FACTS, rng=self.rng)
        self.banter_at: float | None = None
        self._stuck_said = 0                     # 0, 1 (the quip) or 2 (the long one)
        self._stuck_at: float | None = None      # when a stuck episode was last said
        self.kills: collections.Counter = collections.Counter()
        self.chases = 0
        # THE BOT'S OWN REASONING (stream/thinking) and what it is doing now
        self.thought_at: dict[str, float] = {}
        self.last_thought = ""                  # for chat's "what are you thinking"
        self.goal: tuple | None = None          # (goal, honey short) from its goals line
        self._gathering = False
        self._fill: float | None = None
        self.status_at: float | None = None
        self._status_i = 0
        # the half hour's tally for the look back (`_summary`)
        self.summary_at = self.opened
        self.window = {"honey": 0.0, "trips": 0, "kills": 0, "chases": 0}
        self.subs: tuple | None = None           # (count, goal) from YouTube, stream/subs

    # ---- what happened ------------------------------------------------------------
    def _add(self, say: str, priority: int, **facts) -> None:
        """Queue one of SAY[say]'s phrasings, filled with `facts`."""
        options = SAY.get(say, [])
        if not options:
            return
        if say in TOKEN_KINDS:
            now = self.clock()
            if self.token_said_at is not None and now - self.token_said_at < TOKEN_EVERY_S:
                return
            self.token_said_at = now
        last = self.last_template.get(say)
        fresh = [o for o in options if o != last] or options
        template = self.rng.choice(fresh)
        try:
            text = template.format(**facts)
        except (KeyError, IndexError):
            return
        text = re.sub(r"\s+([.,!?])", r"\1", text).strip()
        self.last_template[say] = template
        self.waiting.append(Line(text, priority, self.clock(), say))
        del self.waiting[:-MOST_WAITING]

    def hear(self, event) -> None:
        if isinstance(event, Considered):
            chosen = str(event.chosen or "")
            if not chosen:
                return
            options = list(event.options or [])
            index = next((i for i, o in enumerate(options)
                          if str(o.label).replace("_", " ") == chosen.replace("_", " ")), None)
            self._why = ("the best field on my list right now" if index == 0 else
                         f"number {index + 1} of {len(options)} on my list" if index is not None
                         else "")
            if chosen != self._field:
                self._field = chosen
                because = because_of(event.rationale)
                if because:
                    self._add("next_because", EVENT, field=title(chosen), because=because)
                elif self._why:
                    self._add("next_why", EVENT, field=title(chosen), why=self._why)
                else:
                    self._add("next", EVENT, field=title(chosen))
            return
        if isinstance(event, TaskUpdate):
            self._task(event)
            return
        if isinstance(event, Thought):
            text = str(event.text or "")
            if event.topic == "journey" and text.startswith(CANNON_WORDS):
                self._add("cannon", EVENT, field=title(self._field))
            elif event.topic == "where":
                self._pushing(text)
                landed = WHERE_FIELD.match(text) if self._landing else None
                if landed:
                    self._landing = False
                    self._add("landed", EVENT, field=title(landed.group(1)))
            return
        if isinstance(event, Log):
            text = str(event.message or "")
            thought = thinking.think(text, self.rng)
            if thought is not None:
                self._think(thought, text)
            chased = CHASING.match(text)
            if chased:
                self.chases += 1
                self.window["chases"] += 1
                kind = (chased.group(1) or "").replace("_", " ")
                if self.chases in CHASE_COUNTS:
                    self._add("token_count", ROUTINE, count=self.chases)
                elif kind and kind != "unknown":
                    self._add("token", ROUTINE, kind=kind)
                else:
                    self._add("token_any", ROUTINE)
            elif text.startswith("asking for a rejoin") or "asking for a rejoin" in text:
                self._add("rejoin", EVENT)
            elif event.source == "errands" and "Ant Challenge" in text and "pressing E" in text:
                self._add("ants", EVENT)
            else:
                defeated = DEFEATED.match(text)
                if defeated:
                    mob = title(defeated.group(1))
                    self.kills[mob] += 1
                    self.window["kills"] += 1
                    if self.kills[mob] in KILL_COUNTS:
                        self._add("kill_count", ROUTINE, count=self.kills[mob], mobs=plural(mob))
                    else:
                        self._add("kill", ROUTINE, mob=mob)

    def _pushing(self, text: str) -> None:
        """The compass says the character has been pushing against something
        for N s: a quip past STUCK_QUIP_S, another past STUCK_LONG_S, once
        each an episode, and an episode said at most every STUCK_EVERY_S."""
        push = PUSHING.search(text)
        if push is None:
            self._stuck_said = 0
            return
        seconds = int(push.group(1))
        now = self.clock()
        if self._stuck_said == 0 and seconds >= STUCK_QUIP_S:
            if self._stuck_at is not None and now - self._stuck_at < STUCK_EVERY_S:
                self._stuck_said = 2        # this episode goes unsaid
                return
            self._stuck_said = 1
            self._stuck_at = now
            self._add("stuck", ROUTINE)
        elif self._stuck_said == 1 and seconds >= STUCK_LONG_S:
            self._stuck_said = 2
            self._add("stuck_long", ROUTINE)

    def _think(self, thought, text: str) -> None:
        """One of the bot's own reasoning lines, said as a thought (stream/thinking),
        each kind at most every `repeat_s`."""
        now = self.clock()
        if thought.kind == "goal":
            m = re.search(r"next is the (.+?) — ([\d,]+) honey short", text)
            self.goal = (m.group(1), thinking.amount(m.group(2))) if m else self.goal
        said = self.thought_at.get(thought.kind)
        if said is not None and now - said < thought.repeat_s:
            return
        self.thought_at[thought.kind] = now
        self.last_thought = thought.text
        self.waiting.append(Line(thought.text, EVENT if thought.decision else ROUTINE,
                                 now, "thought"))
        del self.waiting[:-MOST_WAITING]

    def _task(self, event: TaskUpdate) -> None:
        self._gathering = event.name == "gather" and event.status == "running"
        if self._gathering and event.progress is not None:
            self._fill = float(event.progress)
        if event.name == "travel to the field" and event.status == "running":
            self._landing = True
            self._fill_said = set()
            if self._field and "cannon" not in str(event.detail or ""):
                self._add("walk", ROUTINE, field=title(self._field))
        elif event.name == "gather" and event.status == "running":
            fill = event.progress if event.progress is not None else -1.0
            if fill >= 0.9 and "nearly" not in self._fill_said:
                self._fill_said |= {"half", "nearly"}
                self._add("nearly", ROUTINE)
            elif fill >= 0.5 and "half" not in self._fill_said:
                self._fill_said.add("half")
                self._add("half", ROUTINE)
        elif event.name == "convert" and event.status == "running":
            self._add("convert", ROUTINE)

    def toasted(self, toast) -> None:
        """A toast the stream just showed: most are the news worth saying."""
        kind = str(getattr(toast, "kind", ""))
        head = str(getattr(toast, "title", ""))
        body = str(getattr(toast, "body", "") or "")
        if kind in ("convert", "record") and head.startswith(("Big convert", "Converted")):
            banked = AMOUNT.search(head)
            if banked:
                try:
                    self.window["honey"] += float(banked.group(1)) * UNITS.get(banked.group(2), 1.0)
                    self.window["trips"] += 1
                except ValueError:
                    pass
        if kind in ("convert", "record"):
            if head.startswith("Big convert"):
                self._add("big", EVENT, amount=spoken_amount(head))
            elif head.startswith("Converted"):
                self._add("banked", EVENT, amount=spoken_amount(head))
        elif kind == "best":
            self._add("best", EVENT, amount=spoken_amount(head))
        elif kind == "streak":
            self._add("streak", EVENT, what=head)
        elif kind == "threat" and head.startswith("Boss"):
            self._add("boss", EVENT, boss=body.split(" — ")[0][:40] or "boss")
        elif kind == "death":
            self._add("death", EVENT)
        elif kind == "quest":
            where = re.sub(r"^at the ", "", body).strip()
            self._add("quest", EVENT, where=f" at {title(where)}" if where else "")
        elif kind == "errand" and head.startswith("Used the "):
            self._add("errand", ROUTINE, place=title(head[len("Used the "):]))
        elif kind == "milestone":
            self._add("milestone", EVENT, what=head)
        elif kind == "ask" and body:
            # chat's question, answered in the bot's own words (stream/ask)
            self.waiting.append(Line(body, ASK, self.clock(), "ask"))
            del self.waiting[:-MOST_WAITING]

    def subscribers(self, count: int, goal: int, change=None) -> None:
        """YouTube's count (stream/subs), and a Change when it went up."""
        self.subs = (int(count), int(goal))
        if change is None or change.new <= 0:
            return
        left = max(0, change.goal - change.count)
        if change.reached:
            self._add("subs_goal", EVENT, reached=f"{change.reached:,}", goal=f"{change.goal:,}")
        elif change.new > 1:
            self._add("subs_many", EVENT, new=change.new, count=f"{change.count:,}",
                      left=left, goal=f"{change.goal:,}")
        else:
            self._add("subs", EVENT, count=f"{change.count:,}", left=left,
                      goal=f"{change.goal:,}")

    def quest_file(self, body: dict) -> None:
        """var/quests.json as the stream read it (after the gate): the open
        steps the room lines check in on."""
        from .extras import quest_bars
        self.quests = quest_bars(body, limit=6)[0]   # six to take turns, not three

    def _quest_line(self) -> str:
        if not self.quests:
            return ""
        bar = self.quests[self._quest_i % len(self.quests)]
        self._quest_i += 1
        return (f"Quest check: {bar.text}, {_count(bar.done)} of {_count(bar.total)} done."
                if bar.text else "")

    # ---- what to say now ------------------------------------------------------------
    def _room(self, now: float) -> Line | None:
        if not self.get("stream.voice_room") or not self.playing():
            return None
        due = (self.opened + FIRST_ENGAGE_S if self.room_at is None
               else self.room_at + ENGAGE_EVERY_S)
        if now < due:
            return None
        if self.last_at is not None and now - self.last_at < QUIET_S:
            return None
        for step in range(len(ROOM_LINES)):
            i = (self.room_next + step) % len(ROOM_LINES)
            key, needs, text = ROOM_LINES[i]
            if needs and not (self.get(needs) and self.chat_live()):
                continue
            if key == "quest":
                text = self._quest_line()
                if not text:
                    continue
            if key == "subscribe" and self.subs is not None:
                count, goal = self.subs
                text = SUBSCRIBE_WITH_COUNT.format(count=f"{count:,}", left=max(0, goal - count),
                                                   goal=f"{goal:,}")
            self.room_next = i + 1
            self.room_at = now
            return Line(text, ROOM, now, "room")
        return None

    def _summary(self, now: float) -> Line | None:
        """The last half hour, looked back on: honey banked, trips, bugs, tokens."""
        if not self.playing() or now - self.summary_at < SUMMARY_EVERY_S:
            return None
        if self.last_at is not None and now - self.last_at < QUIET_S:
            return None
        w = self.window
        self.summary_at = now
        self.window = {"honey": 0.0, "trips": 0, "kills": 0, "chases": 0}
        if not w["trips"]:
            return None
        text = (f"Quick look back: in the last half hour I made "
                f"{thinking.amount(int(w['honey']))} honey from {w['trips']} "
                f"trip{'s' if w['trips'] != 1 else ''}")
        extra = []
        if w["kills"]:
            extra.append(f"beat {w['kills']} bug{'s' if w['kills'] != 1 else ''}")
        if w["chases"]:
            extra.append(f"chased {w['chases']} token{'s' if w['chases'] != 1 else ''}")
        if extra:
            text += ", " + " and ".join(extra)
        return Line(text + ".", ROOM, now, "room")

    def _status(self, now: float) -> Line | None:
        """What the bot is doing and wants, for a quiet stretch: the field and the
        bag while gathering, the goal it is working towards, the nearest quest --
        each from what it has said, taken in turn."""
        if not self.playing():
            return None
        due = (self.opened + FIRST_STATUS_S if self.status_at is None
               else self.status_at + STATUS_EVERY_S)
        if now < due or (self.last_at is not None and now - self.last_at < QUIET_S):
            return None
        options = []
        if self._gathering and self._field and self._fill is not None:
            try:
                at = int(self.get("gather.convert_at") or 95)
            except (TypeError, ValueError):
                at = 95
            options.append(
                f"I'm gathering in {title(self._field)}. My bag is {self._fill:.0%} full; "
                f"at {at}% I'll take it home and make honey.")
        if self.goal is not None:
            options.append(f"Still working towards the {self.goal[0]}: "
                           f"about {self.goal[1]} honey to go.")
        quest = self._quest_line()
        if quest:
            options.append(quest)
        if not options:
            return None
        self.status_at = now
        for k in range(len(options)):
            text = options[(self._status_i + k) % len(options)]
            said = self.said.get(text)
            if said is None or now - said >= STATUS_REPEAT_S:
                self._status_i += k + 1
                return Line(text, ROOM, now, "status")
        return None                 # nothing new to say: the next slot, or a joke

    def _banter(self, now: float) -> Line | None:
        """A joke, a quip or a bee fact (stream/banter) for a quiet stretch."""
        if not self.get("stream.voice_banter") or not self.playing():
            return None
        due = (self.opened + FIRST_BANTER_S if self.banter_at is None
               else self.banter_at + BANTER_EVERY_S)
        if now < due:
            return None
        if self.last_at is not None and now - self.last_at < QUIET_S:
            return None
        text = self.banter.next()
        if not text:
            return None
        self.banter_at = now
        return Line(text, ROOM, now, "room")

    def next_line(self, now: float | None = None) -> str | None:
        """The line to say now, or None. Call when the voice is free."""
        now = self.clock() if now is None else now
        self.waiting = [ln for ln in self.waiting if now - ln.at <= STALE_S[ln.priority]]
        if self.last_at is not None and now - self.last_at < GAP_S:
            return None
        line = None
        if self.waiting:
            best = max(self.waiting, key=lambda ln: (ln.priority, ln.at))
            self.waiting.remove(best)
            line = best
        else:
            line = (self._summary(now) or self._room(now) or self._status(now)
                    or self._banter(now))
        if line is None:
            return None
        said_at = self.said.get(line.text)
        if said_at is not None and now - said_at < REPEAT_S and line.kind not in ("room", "ask"):
            return None
        self.said[line.text] = now
        self.last_at = now
        return line.text
