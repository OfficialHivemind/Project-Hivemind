"""Chat asks the bot a question with `!ask`, and the bot answers -- safely.

THE OWNER, 2026-09-28: the AI answering chat could be good, but only with
heavy safeguards so it cannot be abused -- people ask, the AI answers in a PG
way and never responds to profanity.

HOW IT STAYS SAFE, in layers, every one of them before anything is said:

  1. ONLY `!ask <question>`. Nothing else anyone types is ever answered.
  2. THE QUESTION MUST PASS EVERY GATE (`screen`): 2-120 characters of plain
     words (letters, digits, basic punctuation -- emoji and symbols are
     dropped, and a message that is mostly them is refused); no links, no
     @names, no runs of five digits; nothing on the PG list, with leetspeak
     ("fvck", "5h1t"), masks ("f*ck") and spaced letters ("f u c k") undone and every word
     checked on its own, so "class" and "grape" are fine; nothing that tries
     to make the bot SAY something ("say", "repeat", "pretend", "ignore
     your..."); the owner's own stream.blocked_words.
  3. RATIONED: one question per viewer per USER_COOLDOWN_S, one answer every
     ANSWER_GAP_S, at most QUEUE_MOST waiting; the same question twice in
     REPEAT_S is answered once; a moderator's delete or ban drops a waiting
     question with its asker.
  4. THE ANSWER IS NEVER THE QUESTION. Nothing a viewer typed is ever shown
     or spoken -- not their words, not their name. Every answer is one of the
     bot's own sentences, filled only with the bot's own facts: the honey it
     read, the field it chose and why, the quest menu it read. A question it
     does not recognise gets a friendly "ask me about..." -- it never guesses
     and never makes anything up.

No model is asked anything: a fixed table of what viewers ask about (`INTENTS`)
and what the bot can truthfully say to each.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from .banter import BEE_FACTS, JOKES  # noqa: F401  (chat's jokes are the voice's)

# ---- the rations ------------------------------------------------------------------
MIN_CHARS, MAX_CHARS = 2, 120
# THE OWNER, 2026-09-29: drop the !ask cooldown; unanswered questions bore
# viewers. Every one of these was a silence: a viewer's
# second question inside 5 minutes, the same kind of question from anyone inside
# 10, anything past 3 waiting, one answer a 40 s. Now no viewer waits on a
# cooldown -- a new question of theirs takes the place of their own older one
# still waiting, so one person cannot fill the queue -- the same question from
# two people is answered once for both while it waits and again after
# REPEAT_S, and an answer comes every ANSWER_GAP_S.
USER_COOLDOWN_S = 0.0
ANSWER_GAP_S = 8.0
QUEUE_MOST = 6
REPEAT_S = 20.0          # the last answer to this is still on screen
STALE_S = 90.0           # a question not answered in this long is let go
MIN_LETTER_SHARE = 0.6   # of what is left once emoji and symbols are dropped

# ---- the gates --------------------------------------------------------------------
LEET = str.maketrans({"0": "o", "1": "i", "!": "i", "3": "e", "4": "a", "@": "a",
                      "5": "s", "$": "s", "7": "t", "8": "b", "9": "g", "+": "t",
                      "|": "i", "€": "e", "£": "l"})
PLAIN = re.compile(r"[^A-Za-z0-9 ?!.,'\-]")
LINK = re.compile(r"https?|www\.|\.(com|net|org|gg|tv|io|ly|me|xyz|ru)\b|discord|dot\s*com",
                  re.IGNORECASE)
AT_NAME = re.compile(r"@\w")
# A MENTION IS TAKEN OUT, NOT REFUSED: on YouTube a question often starts with
# "@yourchannel", and no answer ever holds a viewer's words, so a name costs
# nothing once it is gone from what is read.
MENTION = re.compile(r"@[\w.-]+")
LONG_NUMBER = re.compile(r"\d{5,}")
# Checked as a SUBSTRING OF ONE WORD (after leetspeak and repeated letters are
# undone): words that do not hide inside ordinary English ones.
PG_STRONG = (
    "fuck", "fuk", "fck", "shit", "sht", "cunt", "nigg", "nigr", "niga", "fagot",
    "faggot", "bitch", "biatch", "whore", "slut", "bastard", "ashole", "asshole",
    "arsehole", "dildo", "porn", "penis", "vagina", "boner", "blowjob", "handjob",
    "wank", "jizz", "semen", "horny", "nude", "naked", "hentai", "rapist", "raping",
    "molest", "pedo", "paedo", "hitler", "nazi", "retard", "suicide", "killyourself",
    "cocaine", "heroin", "twat", "prick", "douche", "motherf", "stfu", "gtfo",
)
# Checked as a WHOLE WORD: short words that hide inside innocent ones ("class",
# "grape", "hello", "peacock").
PG_WORDS = {
    "ass", "asses", "arse", "damn", "dammit", "hell", "crap", "piss", "pissed",
    "dick", "dicks", "cock", "cocks", "pussy", "tit", "tits", "titty", "boob",
    "boobs", "cum", "sex", "sexy", "rape", "raped", "kys", "wtf", "omfg", "meth",
    "weed", "drugs", "fag", "fags", "hoe", "hoes", "thot", "simp", "anal", "balls",
    "butt", "butthole", "kill yourself", "stupid", "idiot", "dumb", "ugly",
    "shut", "loser", "trash", "suck", "sucks",
}
# Trying to make the bot say something: refused, since answers are the bot's own.
PUPPET_WORDS = {"say", "says", "repeat", "spell", "pretend", "ignore", "roleplay",
                "prompt", "instructions", "instruction", "jailbreak", "system"}
PUPPET_PHRASES = ("act as", "you are now", "from now on", "simon says", "read this",
                  "type this", "copy this")


def _norm(text: str) -> str:
    return str(text or "").lower().translate(LEET)


def _collapse(word: str) -> str:
    """"fuuuck" -> "fuck": a run of one letter is one letter."""
    return re.sub(r"(.)\1+", r"\1", word)


def _tokens(text: str) -> list[str]:
    """Each word, and spelled-out words joined ("f u c k" -> "fuck")."""
    words = re.findall(r"[a-z]+", _norm(text))
    out, run = [], []
    for w in words + [""]:
        if len(w) == 1:
            run.append(w)
            continue
        if len(run) >= 3:
            out.append("".join(run))
        run = []
        if w:
            out.append(w)
    return out


# A word with a mask inside it ("f*ck", "sh#t", "b**ch") is an attempt at one.
MASKED = re.compile(r"[a-z][*#%]+[a-z]|[a-z][*#%]{2,}", re.IGNORECASE)


def rude(text: str) -> bool:
    """On the PG list, however it is spelled."""
    if MASKED.search(str(text or "")):
        return True
    tokens = _tokens(text)
    forms = set(tokens) | {_collapse(t) for t in tokens}
    # "fvck": v for u, checked against the strong words only (a v is an
    # ordinary letter everywhere else)
    forms |= {f.replace("v", "u") for f in forms if "v" in f}
    if any(bad in form for form in forms for bad in PG_STRONG):
        return True
    if forms & PG_WORDS:
        return True
    joined = " ".join(tokens)
    return any(" " in bad and bad in joined for bad in PG_WORDS)


def puppeteering(text: str) -> bool:
    low = " ".join(re.findall(r"[a-z]+", str(text or "").lower()))
    words = set(low.split())
    return bool(words & PUPPET_WORDS) or any(p in low for p in PUPPET_PHRASES)


def screen(text: str, blocked=()) -> tuple[bool, str]:
    """(may it be answered, why not). The reason is for the log, never chat."""
    raw = " ".join(MENTION.sub(" ", str(text or "")).split())
    if LINK.search(raw) or AT_NAME.search(raw) or LONG_NUMBER.search(raw):
        return False, "a link, a name or a long number"
    kept = PLAIN.sub("", raw).strip()
    if not kept or len(kept) < MIN_CHARS or len(raw) > MAX_CHARS:
        return False, "too short or too long"
    letters = sum(c.isalpha() for c in kept)
    if letters < MIN_LETTER_SHARE * len(kept.replace(" ", "")):
        return False, "mostly not words"
    if rude(raw):
        return False, "not PG"
    if puppeteering(raw):
        return False, "asks the bot to say something"
    low = raw.lower()
    if any(b and b in low for b in blocked):
        return False, "one of the owner's blocked words"
    return True, ""


# ---- what they ask about, and what the bot can truly say ----------------------------------
@dataclass
class Facts:
    """What the bot really knows, filled by the stream window."""
    honey: float | None = None
    rate: float | None = None
    where: str = ""
    plan: str = ""
    why: str = ""
    goal: str = ""
    trips: int = 0
    deaths: int = 0
    quest: str = ""              # one open step, "Defeat 16 Rhino Beetles, 11 of 16 done"
    field: str = ""              # the field it chose
    thought: str = ""            # the bot's latest thought, said by the voice (stream/thinking)


def _human(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    for limit, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million"), (1e3, "thousand")):
        if abs(v) >= limit:
            return f"{v / limit:.3g} {word}"
    return f"{v:,.0f}"


def _title(slug: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in str(slug or "").replace("_", " ").split())


# The jokes and the facts are the voice's too (stream/banter).
# For a question it cannot answer: said plainly, then something true and fun
# instead (stream/banter), so a question is never met with the same line twice.
UNKNOWN_LEADS = [
    "Hmm, that one's beyond my bee brain!",
    "Good question! I only really know bees and honey.",
    "Ooh, not sure about that one!",
    "I'm a bee bot, so that one's a mystery to me!",
]
UNKNOWN = [
    "Good question! I'm best at bee questions. Ask me where I'm going, why, or how much honey I have.",
    "Hmm, I only know about bees and honey! Try asking what I'm doing or what my quest is.",
]


def _doing(f: Facts) -> str:
    if f.plan:
        return f"Right now I'm on it: {f.plan}."
    if f.where:
        return f"I'm in {f.where}, gathering pollen."
    return "I'm getting ready for my next trip."


INTENTS = [
    # (name, the words that mean it, the lead-in, the answer)
    ("joke", ("joke", "funny"), "A joke? Okay!", lambda f, rng: rng.choice(JOKES)),
    ("fact", ("fun fact", "bee fact", "a fact", "facts"), "A bee fact!",
     lambda f, rng: rng.choice(BEE_FACTS)),
    ("bot", ("are you a bot", "are you ai", "are you an ai", "are you real", "is this ai",
             "is this a bot", "are you human", "is it a bot", "real person", "is this real"),
     "Chat asked if I'm real.",
     lambda f, rng: "Yep, I'm an AI! I read the screen and press the keys myself. No cheats, no hacks."),
    ("made", ("who made you", "who built you", "who created you", "who coded you",
              "who programmed", "your creator", "who owns you"),
     "Chat asked who made me.",
     lambda f, rng: "The Hivemind team built me, one line of code at a time!"),
    ("works", ("how do you work", "how does this work", "how does it work", "how do you see",
               "how do you play", "how do you know"),
     "Chat asked how I work.",
     lambda f, rng: ("I look at the screen like you do: the pollen counter, the fields and "
                     "the tokens. Then I pick the field that makes the most honey.")),
    ("next", ("where are you going", "where next", "next field", "going next", "go next",
              "where to next", "heading"),
     "Chat asked where I'm going.",
     lambda f, rng: (f"Next up: {_title(f.field)}." if f.field else _doing(f))),
    ("why", ("why",),
     "Chat asked why.",
     lambda f, rng: _why(f)),
    ("where", ("where are you", "which field", "what field", "where r you"),
     "Chat asked where I am.",
     lambda f, rng: (f"I'm in {f.where}." if f.where else "I'm between fields right now.")),
    ("honey", ("how much honey", "honey do you have", "how rich", "your honey", "honey count",
               "total honey"),
     "Chat asked about my honey.",
     lambda f, rng: _honey(f)),
    ("rate", ("per hour", "an hour", "how fast", "honey rate"),
     "Chat asked how fast I make honey.",
     lambda f, rng: (f"About {_human(f.rate)} honey an hour right now." if f.rate
                     else "I haven't timed a full hour yet. Ask me again soon!")),
    ("quest", ("quest", "mission", "task"),
     "Chat asked about my quest.",
     lambda f, rng: (f"Quest check: {f.quest}." if f.quest
                     else "No quest step to show right now.")),
    ("goal", ("goal", "saving for", "saving up", "gear", "buy next", "want to buy"),
     "Chat asked about my goal.",
     lambda f, rng: (f"My goal: {f.goal}." if f.goal else "No gear goal to show right now.")),
    ("deaths", ("die", "died", "deaths", "knocked out", "how many times"),
     "Chat asked about knock-outs.",
     lambda f, rng: (f"{f.deaths} knock-out{'s' if f.deaths != 1 else ''} in the last day, "
                     f"over {f.trips} trip{'s' if f.trips != 1 else ''}.")),
    ("trips", ("trips", "how many runs"),
     "Chat asked about my trips.",
     lambda f, rng: f"{f.trips} trip{'s' if f.trips != 1 else ''} in the last day."),
    ("favourite", ("favorite field", "favourite field", "best field", "favorite", "favourite"),
     "Chat asked my favourite.",
     lambda f, rng: (f"Whichever makes the most honey! Right now that's {_title(f.field)}."
                     if f.field else "Whichever makes the most honey!")),
    ("tokens", ("token",),
     "Chat asked about tokens.",
     lambda f, rng: "I chase a token when I'm sure it's a coin. Honey tokens are my favourite!"),
    ("thinking", ("what are you thinking", "thinking", "whats your plan", "what's your plan",
                  "your plan", "the plan", "on your mind", "your brain", "whats next for you"),
     "Chat asked what I'm thinking.",
     lambda f, rng: (f"Right now I'm thinking: {f.thought}" if f.thought else _doing(f))),
    ("doing", ("what are you doing", "wyd", "what you doing", "what are you up to",
               "what u doing", "whatcha doing"),
     "Chat asked what I'm doing.",
     lambda f, rng: _doing(f)),
    ("feel", ("how are you", "hru", "how you doing", "how's it going", "you ok", "you good"),
     "Chat asked how I'm doing.",
     lambda f, rng: rng.choice(["I'm buzzing, thanks for asking!",
                                "Feeling sweet as honey!",
                                "Great! My bees are working hard."])),
    ("hello", ("hi", "hello", "hey", "yo", "sup", "hiya", "howdy", "greetings"),
     "",
     lambda f, rng: rng.choice(["Hey chat! Welcome in!", "Hello hello! Grab a seat and watch the bees.",
                                "Hi there! Thanks for hanging out."])),
]


def _why(f: Facts) -> str:
    from .voice import because_of
    reason = because_of(f.why)
    if reason and f.field:
        return f"I picked {_title(f.field)} because: {reason[:1].lower() + reason[1:]}."
    if f.field:
        return f"{_title(f.field)} is the best field on my list right now."
    return "I'm still deciding. Ask me again in a minute!"


def _honey(f: Facts) -> str:
    if f.honey is None:
        return "I haven't read my honey counter yet. Ask me again soon!"
    rate = f" and I'm making about {_human(f.rate)} an hour" if f.rate else ""
    return f"I've got {_human(f.honey)} honey{rate}."


# Contractions and chat spellings, undone before matching.
SPELLINGS = [(r"\bu\b", "you"), (r"\br\b", "are"), (r"\bur\b", "your"), (r"\bwat\b", "what"),
             (r"\bwut\b", "what"), (r"\bwhats\b", "what is"), (r"\bwhat's\b", "what is"),
             (r"\bim\b", "i am"), (r"\bya\b", "you"), (r"\by\b", "why"), (r"\bpls\b", "please")]


def intent_of(question: str) -> str:
    low = " ".join(re.findall(r"[a-z']+", str(question or "").lower()))
    for pattern, repl in SPELLINGS:
        low = re.sub(pattern, repl, low)
    padded = f" {low} "
    for name, words, _, _ in INTENTS:
        if any(f" {w} " in padded or (" " in w and w in low) for w in words):
            return name
    return "unknown"


def answer_for(intent: str, facts: Facts, rng=random) -> str:
    for name, _, lead, say in INTENTS:
        if name == intent:
            body = say(facts, rng)
            return f"{lead} {body}".strip()
    if rng.random() < 0.5:
        return f"{rng.choice(UNKNOWN_LEADS)} Here's a bee fact instead: {rng.choice(BEE_FACTS)}"
    return f"{rng.choice(UNKNOWN_LEADS)} Here's a joke instead: {rng.choice(JOKES)}"


# ---- the queue ------------------------------------------------------------------------
@dataclass
class Asked:
    user: str
    message_id: str
    intent: str
    at: float


class Asker:
    """`hear(user, text, message_id)` from `!ask`; `moderated(user, id)`;
    `next_answer()` when the stream may show one."""

    def __init__(self, get=lambda key: None, facts=lambda: Facts(), clock=time.time, rng=None):
        self.get = get
        self.facts = facts
        self.clock = clock
        self.rng = rng or random.Random()
        self.waiting: list[Asked] = []
        self.user_at: dict[str, float] = {}
        self.intent_at: dict[str, float] = {}
        self.answered_at: float | None = None
        self.refused: dict[str, int] = {}
        self.heard = 0

    def _blocked(self) -> list[str]:
        return [w.strip().lower() for w in str(self.get("stream.blocked_words") or "").split(",")
                if w.strip()]

    def hear(self, user: str, text: str, message_id: str = "") -> bool:
        """Queue a question; True if it was taken."""
        self.heard += 1
        if not self.get("stream.chat_ask"):
            return False
        now = self.clock()
        ok, why = screen(text, self._blocked())
        if not ok:
            self.refused[why] = self.refused.get(why, 0) + 1
            return False
        last = self.user_at.get(user)
        if USER_COOLDOWN_S and last is not None and now - last < USER_COOLDOWN_S:
            self.refused["asked again too soon"] = self.refused.get("asked again too soon", 0) + 1
            return False
        intent = intent_of(text)
        again = intent not in ("unknown", "joke", "fact", "hello", "feel")
        said = self.intent_at.get(intent)
        if again and said is not None and now - said < REPEAT_S:
            # the answer to exactly this is on screen right now
            return False
        if again and any(a.intent == intent for a in self.waiting):
            # the same question already waiting: its answer is for both
            self.user_at[user] = now
            return True
        # a viewer's newer question takes the place of their own older one
        self.waiting = [a for a in self.waiting if a.user != user]
        self.user_at[user] = now
        self.waiting.append(Asked(user=user, message_id=str(message_id or ""), intent=intent, at=now))
        del self.waiting[:-QUEUE_MOST]
        return True

    def moderated(self, user: str = "", message_id: str = "") -> None:
        """A moderator removed a message or a person: their question goes too."""
        self.waiting = [a for a in self.waiting
                        if not ((user and a.user == user) or (message_id and a.message_id == message_id))]

    def next_answer(self) -> str | None:
        now = self.clock()
        self.waiting = [a for a in self.waiting if now - a.at <= STALE_S]
        if not self.waiting:
            return None
        if self.answered_at is not None and now - self.answered_at < ANSWER_GAP_S:
            return None
        asked = self.waiting.pop(0)
        self.answered_at = now
        self.intent_at[asked.intent] = now
        return answer_for(asked.intent, self.facts(), self.rng)
