"""What the stream shows and what chat can play, without any Qt in it.

Two jobs, both pure so they can be driven offline with invented chat and
recorded bot lines:

  THE FEED. The bot narrates about 18.8 lines a minute (MEASURED over run-393
  to run-432, 606 minutes, dashboard notes and compass fixes left out) --
  faster than a viewer reads, and much of it the same shape again: "buff bar:
  no haste" over and over. `Feed` sorts each line into a category the stream
  can colour, and folds a line whose shape (digits blanked) was shown in the
  last two minutes into a repeat count. MEASURED on the same logs: that leaves
  8.9 new lines a minute, one every seven seconds, which a viewer can follow.

  THE GAMES. `Show` is chat's side: the field vote the bot published a ballot
  for, a prediction on every trip, a leaderboard of who called it right,
  chat-named honey milestones, and answers to !stats !why !where !goal. Every
  answer is drawn ON THE STREAM; nothing is ever sent to chat or to the game.
  The one thing that reaches the bot is a finished field vote, as a
  `ChatVote`, and the bot's `stream/gate` decides what happens to it.

DESIGN 8dv.
"""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..telemetry.events import ChatBallot, ChatVote, Log, Thought
from .chat import Moderation
from .gate import VOTE_TTL_SECONDS

# ---- the feed ---------------------------------------------------------------

# A line whose shape was shown this recently becomes a repeat count instead of
# a new row. MEASURED (see the module docstring): 120 s takes the feed from
# 18.8 to 8.9 lines a minute over 606 minutes of real narration.
REPEAT_SECONDS = 120.0

# THE LONGEST LINE SHOWN WHOLE. MEASURED over the 5,416 lines the feed kept
# from those logs: median 91 characters, 90th percentile 148, 99th 341,
# longest 726. Cut at 220 with an ellipsis, 97% are shown whole and none can
# fill the panel.
TEXT_MAX = 220

# Thought topics and Log sources, to the category the stream colours them by.
# Topics and sources are the ones the bot actually emits (grep of
# `topic="..."` and `source="..."` over src/ and scripts/run_farm.py).
TOPIC_CATEGORY = {
    "plan": "decision", "chat": "chat", "goals": "goal",
    "navigate": "travel", "journey": "travel", "arrival": "travel",
    "explore": "travel", "farm": "farm", "watching": "vision",
}
SOURCE_CATEGORY = {
    "threat": "threat", "quests": "quest", "errands": "errand",
    "chase": "token", "school": "token", "homing": "travel",
    "journey": "travel", "walk": "travel", "gather": "farm", "farm": "farm",
    "goals": "goal", "alive": "health", "session": "health",
    "supervisor": "vision",
}
# Not narration at all: the compass is shown as the "where" line, and a gap
# note explains an empty dashboard panel the stream does not have.
QUIET_TOPICS = {"where", "gap"}
# Nor is the live view's report on its own frame rate (telemetry/liveview,
# DESIGN 8eb), a minute into each run and then every half hour: a debug line
# with a runtime path in it, for the run log and the main window, not the
# broadcast.
QUIET_SOURCES = {"liveview"}

DIGITS = re.compile(r"[\d][\d,.]*")


def shape(text: str) -> str:
    return DIGITS.sub("#", str(text or ""))[:60]


# THE BROADCAST READS AS ENGLISH (the owner, 2026-10-14: a TikTok showcase,
# "make it look highly proffessional"). The run log's own names are for the
# log: route and pattern ids, CONSTANT notes with their module paths, snake_case
# fields and raw seconds. Viewers get the place and the time. Bot narration
# only -- never a chat name, where an underscore is part of the name.
_ROUTE_NAMES = (
    (re.compile(r"\bnatro_pattern_(\w+?)_as_natro\b"), r"the \1 pattern"),
    (re.compile(r"\bnatro_out_(\w+?)(?:_via_\w+)?\b"), r"the walk to \1"),
    (re.compile(r"\bnatro_home_(\w+)\b"), r"the walk home from \1"),
    (re.compile(r"\bto_the_(\w+)\b"), r"the walk to the \1"),
)
_CODE_NOTE = re.compile(r"\s*\((?:[^()]*?\b[a-z_]+/[a-z_]+\b|[^()]*?\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b"
                        r"|[^()]*?\b[a-z]+\.[a-z_]+\b|\[hidden\])[^()]*\)")
# A bracketed aside with ": " in it is a diagnostic ("(pushed against
# something for 2s: the walk home from pine tree: w for 124 studs: ...)");
# a clock time ("13:56") has no space after its colon and stays.
_DETAIL = re.compile(r"\s*\([^()]*: [^()]*\)")
_SNAKE = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
_SECONDS = re.compile(r"\b(\d[\d,]{2,})s\b")


def _span(seconds: float) -> str:
    if seconds >= 5400:
        return f"{seconds / 3600:.0f} h"
    if seconds >= 90:
        return f"{seconds / 60:.0f} min"
    return f"{seconds:.0f}s"


def plain(text: str) -> str:
    """The bot's words with its code names taken out (see _ROUTE_NAMES)."""
    text = str(text or "")
    for pattern, words in _ROUTE_NAMES:
        text = pattern.sub(words, text)
    text = _CODE_NOTE.sub("", text)
    while True:                     # an aside inside an aside: inner first
        shorter = _DETAIL.sub("", text)
        if shorter == text:
            break
        text = shorter
    text = _SNAKE.sub(lambda m: m.group(0).replace("_", " "), text)
    return _SECONDS.sub(lambda m: _span(float(m.group(1).replace(",", ""))), text)


def clip(text: str, limit: int = TEXT_MAX) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


# WHAT A VIEWER WATCHES FOR, BY THE BOT'S OWN WORDS (the owner, 2026-10-05: "i
# wanna see it tryna think about buying and stuff"). The bot's purchases, eggs,
# slots and jelly come from several sources, so they are known by what they say,
# ahead of the source; the second-by-second pose, buff and look lines are the
# run log's, not the broadcast's.
NOISE_PREFIXES = ("I am in ", "I am on ", "I am at ", "I am nowhere", "buff bar:",
                  "token brain: hold", "threat eye:", "row:", "live view:", "school:",
                  "skills:", "pace:", "own body:", "blind:", "the walk home from",
                  "whirligig home:", "running this as hive slot")
SHOP_WORDS = ("buying", "bought it", "goals:", "Basic Egg", "Hive Slot", "Mountain Top Shop",
              "royal jelly", "Royal Jelly", "jelly (", "Ticket Tent")
HIVE_WORDS = ("egg hatch", "the hive:", "bee menu", "bee card", "new-type card")
FIGHT_WORDS = ("reward feed:", "loot:", "bug run")


def category_of(event) -> str | None:
    """The stream's category for a Thought or Log, or None to leave it out."""
    if isinstance(event, Thought):
        if event.topic in QUIET_TOPICS:
            return None
        return TOPIC_CATEGORY.get(event.topic, "think")
    if isinstance(event, Log):
        if event.source in QUIET_SOURCES:
            return None
        text = str(event.message or "")
        if text.startswith(NOISE_PREFIXES):
            return None
        if text.startswith("died:"):
            return "death"
        if any(w in text for w in SHOP_WORDS):
            return "shop"
        if any(w in text for w in HIVE_WORDS):
            return "hive"
        if text.startswith(FIGHT_WORDS):
            return "fight"
        if text.startswith("items:"):
            return "item"
        if text.startswith("token brain:") or text.startswith("chasing a token"):
            return "token"
        if event.source == "farm" and text.startswith("convert"):
            return "convert"
        return SOURCE_CATEGORY.get(event.source, "farm")
    return None


@dataclass
class Item:
    """One row of the feed."""
    category: str
    text: str
    at: float
    warn: bool = False
    count: int = 1
    key: str = ""


class Feed:
    """Categorise, clip and fold repeats. `add` returns (item, is_new)."""

    def __init__(self, repeat_seconds: float = REPEAT_SECONDS, keep: int = 80):
        self.repeat_seconds = repeat_seconds
        self.keep = keep
        self.items: list[Item] = []
        self._seen: dict[str, tuple[float, Item]] = {}

    def add(self, event):
        category = category_of(event)
        if category is None:
            return None, False
        text = event.text if isinstance(event, Thought) else event.message
        text = clip(plain(text))
        if not text:
            return None, False
        at = float(getattr(event, "at", 0.0) or time.time())
        key = f"{category}|{shape(text)}"
        seen = self._seen.get(key)
        if seen is not None and at - seen[0] < self.repeat_seconds:
            item = seen[1]
            item.count += 1
            item.at = at
            self._seen[key] = (at, item)
            return item, False
        warn = isinstance(event, Log) and str(getattr(event.level, "value",
                                                      event.level)) in ("warn", "error")
        item = Item(category=category, text=text, at=at, warn=warn, key=key)
        self._seen[key] = (at, item)
        self.items.append(item)
        if len(self.items) > self.keep:
            self.items = self.items[-self.keep:]
        if len(self._seen) > 4 * self.keep:
            cutoff = at - self.repeat_seconds
            self._seen = {k: v for k, v in self._seen.items() if v[0] >= cutoff}
        return item, True


def where_from(text: str) -> str:
    """'I am in the strawberry field (95% sure, feed, 0s ago) · facing ...'
    -> 'in the strawberry field · 95% sure'."""
    head = str(text or "").split(" · ", 1)[0]
    head = re.sub(r"^I am\s+", "", head).strip()
    sure = re.search(r"\((\d+)% sure", head)
    place = re.sub(r"\s*\(.*\)\s*$", "", head).strip()
    return f"{place} · {sure.group(1)}% sure" if sure else place


# ---- highlights, from what the bot says --------------------------------------

# THE WORDS THAT MARK AN EVENT WORTH A TOAST, each the bot's own:
#   death:   scripts/run_farm.on_death, Log(source="farm")
#            "died: N pollen lost, backpack now N", and brain/alive and
#            brain/farm's "died: pollen fell A -> B" -- one toast a death,
#            `Spotter.first_death_line`
#   errand:  act/errands.Outcome.describe "treat_dispenser: used it ..."
#   cannon:  nav/journey, Thought(topic="journey") "pressing E at the red
#            cannon (panel: 'fire the red cannon')" (run-427.log 06:13:15)
#   hand-in: scripts/run_farm, Log(source="quests") "a dialogue was read at
#            the brown bear, so it leaves the hand-in queue ..." -- said only
#            for a giver the quest menu showed holding a finished quest
#   mob:     the compass, Thought(topic="where") "... · THREAT: mob health bar
#            93x14 at (1267, 289)" (run-432.log 06:49:34)
#   boss:    brain/threat on feat/boss, Log(source="threat") "a boss-class mob
#            is on screen: ..." -- that detector is not in this build yet, and
#            the toast fires once it is merged; until then a boss is a mob.
BOSS_WORDS = "boss-class mob is on screen"
USED = re.compile(r"^([a-z_]+): used it")
CANNON_WORDS = "pressing E at the red cannon"
HANDED_IN = re.compile(r"^a dialogue was read at the (.+?), so it leaves the "
                       r"hand-in queue")
# A RUN LOG LINE: "    HH:MM:SS  the words".
LOG_LINE = re.compile(r"^\s*(\d\d):(\d\d):(\d\d)  (.*)$")


def handed_in_24h(night, now: float | None = None) -> int:
    """Quests handed in over the last 24 h, by the run logs' HANDED_IN lines
    -- the numbers card's tile, which read 0 on every fresh window when it
    counted only "since" the window opened (a video would always show 0).
    A line carries a time, not a date: it is dated by its log's last write,
    a day back when it is later in the day than that (a run is hours)."""
    from datetime import datetime, timedelta
    from pathlib import Path
    now = time.time() if now is None else now
    since = now - 86400
    count = 0
    for log in Path(night).glob("run-*.log"):
        try:
            mtime = log.stat().st_mtime
            if mtime < since:
                continue
            end = datetime.fromtimestamp(mtime)
            for line in log.read_text(errors="ignore").splitlines():
                m = LOG_LINE.match(line)
                if not m or not HANDED_IN.match(m.group(4)):
                    continue
                at = end.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                                 second=int(m.group(3)), microsecond=0)
                if at > end:
                    at -= timedelta(days=1)
                if at.timestamp() >= since:
                    count += 1
        except (OSError, ValueError):
            continue
    return count


# THE FEATURES, EACH WITH ITS MOMENT ON SCREEN (the owner, 2026-10-14: the
# showcase must "show each feature working with proof"). The bot's own result
# lines, as the run logs print them (var/night/run-9xx.log).
CAPTURED = re.compile(r"^Commando Chick: CAPTURED after ([\d.]+) min")
CRAFTED = re.compile(r"^the Blender: collected the finished (\d+) (.+?)\s*$")
HARVESTED = re.compile(r"^planter: harvested the (.+?) in the (.+?) —")
PLANTED = re.compile(r"^planter: the (.+?) in the (.+?) — used one")
BOUGHT = re.compile(r"^buying [^:]+: bought it — '([^|']+)")
ROLLED = re.compile(r"^royal jelly: ([1-9]\d*) rolled .*it now holds the (.+? Bee)")
DEFEATED = re.compile(r"^reward feed: an? (.+?) was defeated")


def feature_toast(text: str) -> Toast | None:
    """The toast for a feature's result line, else None (see CAPTURED)."""
    if m := CAPTURED.match(text):
        return toast("fight", "Commando Chick captured!", f"after {m.group(1)} min of fighting")
    if m := CRAFTED.match(text):
        return toast("craft", "Blender crafted", f"{m.group(1)} {m.group(2)}")
    if m := HARVESTED.match(text):
        return toast("planter", f"Harvested the {m.group(1)}", f"in the {m.group(2)} field")
    if m := PLANTED.match(text):
        return toast("planter", f"Planted a {m.group(1)}", f"in the {m.group(2)} field")
    if m := BOUGHT.match(text):
        return toast("shop", "Bought it", m.group(1).strip())
    if m := ROLLED.match(text):
        wanted = "wanted" in text
        return toast("hive", f"Royal Jelly: {m.group(2)}" + ("!" if wanted else ""),
                     f"{m.group(1)} rolled" + (" — the one it wanted" if wanted else ""))
    if m := DEFEATED.match(text):
        return toast("fight", f"Defeated a {m.group(1)}")
    return None


THREAT_MARK = " · THREAT: "
# ONE MOB TOAST PER ENCOUNTER. MEASURED over run-393 to run-432 (586 minutes):
# 147 compass lines carried a THREAT; taking a gap of over 60 s as a new
# encounter gives 67 of them, 6.9 an hour (30 s gives 68 and 120 s 58, so the
# count hardly depends on the cut).
MOB_TOAST_GAP_SECONDS = 60.0
# ONE KNOCK-OUT TOAST PER DEATH. A death is told two to four times: "died:
# pollen fell A -> B" from brain/alive or brain/farm, then "died: N pollen
# lost, backpack now N" from run_farm.on_death. MEASURED over every
# var/night/run-*.log: 9 deaths, each 2 to 4 "died:" lines spanning 26 s at
# most, and no run holds two deaths (a 30, 60 or 120 s cut gives the same 9).
DEATH_TOAST_GAP_SECONDS = 60.0


@dataclass
class Toast:
    kind: str                      # a feed category, or milestone/record/poll
    title: str
    body: str = ""
    seconds: float = 6.0
    at: float = field(default_factory=time.time)


# HOW LONG A TOAST STAYS UP: long enough to read, and within the 4 to 10 s
# Material Design gives a snackbar. Reading speed is 238 words a minute for
# adults reading non-fiction silently (Brysbaert 2019, J. Mem. Lang. 109,
# 104047, a meta-analysis of 190 studies).
READ_WPM = 238.0
TOAST_MIN_S = 4.0
TOAST_MAX_S = 10.0


def toast_seconds(title: str, body: str = "") -> float:
    words = len(f"{title} {body}".split())
    return min(TOAST_MAX_S, max(TOAST_MIN_S, words / READ_WPM * 60.0))


def toast(kind: str, title: str, body: str = "") -> Toast:
    # The bot's words in plain English (`plain`); chat's own words as typed.
    body = body if kind == "chat" else plain(body)
    return Toast(kind=kind, title=title, body=body,
                 seconds=toast_seconds(title, body))


def highlight_of(event, trip: str = "") -> Toast | None:
    """A toast for a bot line that is an event, else None. `trip` is the
    field the trip in hand is going to, when the caller knows it. The mob
    sighting needs memory, so it is `Spotter`'s."""
    if isinstance(event, Log):
        text = str(event.message or "")
        if BOSS_WORDS in text:
            return toast("threat", "Boss spotted",
                         clip(text.split(":", 1)[-1].split(" — ")[0], 120))
        if text.startswith("died:"):
            return toast("death", "Knocked out", clip(text[5:].strip(), 120))
        used = USED.match(text)
        if used and event.source == "errands":
            return toast("errand", f"Used the {used.group(1).replace('_', ' ')}")
        handed = HANDED_IN.match(text)
        if handed and event.source == "quests":
            return toast("quest", "Quest handed in",
                         f"at the {handed.group(1)}")
        feature = feature_toast(text)
        if feature is not None:
            return feature
    if isinstance(event, Thought):
        text = str(event.text or "")
        if event.topic == "journey" and text.startswith(CANNON_WORDS):
            return toast("travel", "Cannon launch",
                         f"flying to {trip}" if trip else "the red cannon")
        if event.topic == "chat" and ("trying it next" in text
                                      or "not used" in text):
            return toast("chat", "Chat's pick", clip(text, 140))
    return None


class Spotter:
    """The toasts that need memory: the compass line gaining a THREAT, once
    an encounter, and the knock-out, once a death."""

    def __init__(self, gap: float = MOB_TOAST_GAP_SECONDS,
                 death_gap: float = DEATH_TOAST_GAP_SECONDS):
        self.gap = gap
        self.death_gap = death_gap
        self._last: float | None = None
        self._died: float | None = None

    def first_death_line(self, event) -> bool:
        """False for the second and later "died:" lines of one death."""
        at = float(getattr(event, "at", 0.0) or time.time())
        fresh = self._died is None or at - self._died > self.death_gap
        self._died = at
        return fresh

    def seen(self, event) -> Toast | None:
        if not (isinstance(event, Thought) and event.topic == "where"):
            return None
        text = str(event.text or "")
        if THREAT_MARK not in text:
            return None
        at = float(getattr(event, "at", 0.0) or time.time())
        fresh = self._last is None or at - self._last > self.gap
        self._last = at
        if not fresh:
            return None
        what = text.split(THREAT_MARK, 1)[1].split(" · ")[0]
        return toast("threat", "Mob on screen", clip(what, 90))


# ---- numbers ---------------------------------------------------------------

def human(value) -> str:
    """1223209 -> '1.22M', 1200000 -> '1.2M'. Two decimals under 10, one
    under 100, and no trailing zeros -- a line of "1.20M" reads as fussy."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= limit:
            scaled = value / limit
            places = 2 if abs(scaled) < 10 else 1 if abs(scaled) < 100 else 0
            text = f"{scaled:.{places}f}"
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            return text + suffix
    return f"{value:,.0f}"


def two_figures(value: float) -> float:
    """1,194,383 -> 1,200,000: the prediction's line is a number people say."""
    if value <= 0:
        return 0.0
    digits = int(math.floor(math.log10(value)))
    step = 10 ** max(0, digits - 1)
    return float(round(value / step) * step)


def nice_step(per_hour: float) -> float:
    """The smallest 1-2-5 x 10^n at least `per_hour`, so that a honey
    milestone comes round about once an hour at the measured rate."""
    if per_hour <= 0:
        return 0.0
    power = 10 ** math.floor(math.log10(per_hour))
    for m in (1, 2, 5, 10):
        if m * power >= per_hour:
            return float(m * power)
    return float(10 * power)


# WHAT A TRIP BANKED. A trip that walks home converts its own bag; most do
# not. MEASURED over var/trips.jsonl (2026-09-22 04:51 to 09-26 07:11): 39 of
# 235 gathering trips converted in their own row, and the bag of most of the
# rest was banked by the NEXT row, which gathered nothing -- the rejoin put the
# character on its pad and the claim converted what it carried (brain/ledger,
# "honey is banked on the cycle AFTER"). So a trip's honey is its own convert,
# or else the first row after it that converts without gathering; a row that
# neither gathers nor converts (a stop, a failed claim) is waited past, and
# anything else ends it unbanked. By that rule 117 trips banked (39 on their
# own, 78 after the rejoin), and over the last 24 hours 26 of 31.
#
# THE PREDICTION'S LINE: the median of the last 40 trips' honey by that rule,
# to two figures. MEASURED: 1,194,383 over all 117 -- the "1.2M" of the
# owner's own example -- and 1,550,968 over the last 40 (so "1.6M" today).
LINE_TRIPS = 40
# A median needs a middle: with fewer than three trips there is no fair line.
LINE_MIN_TRIPS = 3
# A "big" convert is one in the top tenth of those same trips (2,709,749 over
# the last 40 today). With fewer than ten there is no top tenth.
BIG_MIN_TRIPS = 10

# THE HONEY HUD IS READ BY OCR and can misread; `Reporter` sends only what it
# read, and a single bad read must not fire a milestone. Two readings in a row
# at or over the mark, the same rule brain/goals uses before it raises a card
# (ASK_AFTER_READINGS = 2, feat/goals).
MILESTONE_READINGS = 2

# A VOTE HAS TO CLOSE BEFORE THE NEXT FIELD IS CHOSEN. MEASURED: a quarter of
# the gaps between one gathering trip and the next are under 447 s
# (var/trips.jsonl, 234 of them; stream/gate.TRIP_SECONDS). So a poll is cut
# to end that long after its ballot, whatever stream.poll_seconds says, and a
# ballot too old for even Twitch's shortest poll gets none -- which only
# happens to one replayed to a window opened mid-trip, or held while no chat
# was connected. A call on the trip is cut the same way: a quarter of trips
# are over by then, and a call still open near the end is a call on a
# backpack bar the stream is showing.
TRIP_P25_SECONDS = 447.0
POLL_MIN_SECONDS = 15.0          # Twitch's own polls run 15 to 1,800 s

COMPLETE_WORD = re.compile(r"\s*complete!?\s*$", re.IGNORECASE)
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '!?.\-]{0,24}$")
BOARD_LIMIT = 5000               # users kept on the board; the least active go
# Message ids remembered, so a moderator deleting ONE message (CLEARMSG)
# takes back exactly what it did. Chat is read at a few lines a second at
# most on a stream this size; 500 is minutes of it.
MESSAGES_KEPT = 500


def gathered(row: dict) -> bool:
    return float(row.get("gather_seconds") or 0.0) > 0


def banked(row: dict) -> bool:
    return bool(row.get("converted")) and row.get("honey") is not None


class Banker:
    """The rule above as a state machine over ledger rows, oldest first.

    `row(r)` returns ("banked", trip, honey, how), ("void", trip, why),
    ("carrying", trip, "") or None. `trip` is the gathering row the honey
    belongs to; for a carry-in with no trip seen before it, it is None.
    """

    def __init__(self):
        self.carrying: dict | None = None

    def row(self, r: dict):
        if gathered(r):
            self.carrying = None
            if banked(r):
                return ("banked", r, float(r["honey"]), "converted at the hive")
            if r.get("pollen"):
                self.carrying = r
                return ("carrying", r, "")
            return ("void", r, str(r.get("reason") or r.get("gather_ended")
                                   or "it gathered nothing"))
        if banked(r):
            trip, self.carrying = self.carrying, None
            return ("banked", trip, float(r["honey"]), "banked after the rejoin")
        if self.carrying is not None and not r.get("converted"):
            return None                        # a stop or a failed claim: wait
        if self.carrying is not None:
            trip, self.carrying = self.carrying, None
            return ("void", trip, str(r.get("reason")
                                      or "the convert's honey was not read"))
        return None


def trip_honey(rows) -> list[float]:
    """Each trip's honey by the rule above, oldest first."""
    banker, out = Banker(), []
    for r in rows:
        said = banker.row(r)
        if said and said[0] == "banked" and said[1] is not None:
            out.append(said[2])
    return out


# ---- what chat is shown -------------------------------------------------------

@dataclass
class Facts:
    """What the bot has said, for !stats and friends. Filled by the window."""
    honey: float | None = None
    rate: float | None = None
    trips: int = 0
    deaths: int = 0
    plan: str = ""
    why: str = ""
    where: str = ""
    goal: str = ""


@dataclass
class Poll:
    id: str
    options: list
    opened_at: float
    ends_at: float
    votes: dict = field(default_factory=dict)       # user -> option index
    closed: bool = False

    def counts(self) -> list[int]:
        out = [0] * len(self.options)
        for index in self.votes.values():
            if 0 <= index < len(out):
                out[index] += 1
        return out


@dataclass
class Prediction:
    id: str
    line: float
    opened_at: float
    ends_at: float
    calls: dict = field(default_factory=dict)       # user -> True (over)/False
    carrying: bool = False       # its trip is over, its bag not yet banked


class Show:
    """Chat's games. Call `hear`, `tick`, `on_ballot`, `on_trips`, `on_quests`,
    `on_honey`; read `outbox` for toasts and the attributes for the panel.

    `get(key)` reads a setting; `send(event) -> bool` sends to the bot;
    `facts()` returns a Facts.
    """

    def __init__(self, get, send=None, facts=None, board_path=None,
                 clock=time.time):
        self.get = get
        self.send = send or (lambda event: False)
        self.facts = facts or Facts
        self.board_path = Path(board_path) if board_path else None
        self.clock = clock
        self.outbox: list[Toast] = []
        self.ticker: list[tuple[str, str]] = []      # (user, text)
        self.poll: Poll | None = None
        self.poll_note = ""
        self._unheard: ChatBallot | None = None     # came while no chat was in
        self.pending = ""          # what happened to chat's last field vote
        self._pending_ballots = 0  # ballots (gathering trips) since it was set
        self.outgoing: ChatVote | None = None       # sent, not yet answered
        self.prediction: Prediction | None = None
        self.last_result = ""
        self.board: dict = {}
        self.names: dict = {}      # key -> {"text", "backers": set, "at", "by"}
        self.milestone: float | None = None
        self._over = 0
        self.quest_steps_done = 0
        self.handed_in = 0
        self._quest_state: dict | None = None
        self._quest_counted: set = set()
        self._rows_seen_at: float | None = None
        self._honeys: list[float] = []
        self._banker = Banker()
        self._answered: dict = {}
        self._messages: dict = {}  # message id -> (what, user, key)
        self.heard = 0
        self.handled = 0
        # CHAT'S QUESTIONS (stream/ask, `!ask`): screened, rationed, and answered
        # only in the bot's own words from its own facts. `ask_extra()` is the
        # window's: the chosen field and an open quest step.
        from .ask import Asker
        self.ask_extra = lambda: {}
        self.asker = Asker(get=get, facts=self._ask_facts, clock=clock)
        # Set by the window (`set_listening`) while a chat reader is actually
        # connected: joined to its Twitch channel, or its file there to read.
        # With no chat nobody can vote, and a poll nobody can answer is
        # decoration.
        self.listening = False
        self._load_board()

    # ---- settings ----------------------------------------------------------
    def _on(self, key: str) -> bool:
        return bool(self.get(key))

    def poll_seconds(self) -> float:
        try:
            value = float(self.get("stream.poll_seconds") or 120)
        except (TypeError, ValueError):
            value = 120.0
        return min(1800.0, max(POLL_MIN_SECONDS, value))   # Twitch's range

    def _blocked(self, *texts: str) -> bool:
        words = [w.strip().lower() for w in str(self.get("stream.blocked_words")
                                                or "").split(",") if w.strip()]
        low = " ".join(str(t or "") for t in texts).lower()
        return any(w in low for w in words)

    def _ask_facts(self):
        from .ask import Facts as AskFacts
        f = self.facts()
        extra = {}
        try:
            extra = dict(self.ask_extra() or {})
        except Exception:
            extra = {}
        return AskFacts(honey=f.honey, rate=f.rate, where=f.where, plan=f.plan, why=f.why,
                        goal=f.goal, trips=f.trips, deaths=f.deaths,
                        quest=str(extra.get("quest") or ""), field=str(extra.get("field") or ""),
                        thought=str(extra.get("thought") or ""))

    def _say(self, kind: str, title: str, body: str = "") -> None:
        self.outbox.append(toast(kind, title, body))

    def _tick(self, user: str, text: str) -> None:
        self.ticker = (self.ticker + [(user, clip(text, 70))])[-4:]

    def _remember(self, message_id: str, what: str, user: str, key="") -> None:
        if not message_id:
            return
        self._messages[message_id] = (what, user, key)
        if len(self._messages) > MESSAGES_KEPT:
            for old in list(self._messages)[:len(self._messages) - MESSAGES_KEPT]:
                del self._messages[old]

    # ---- chat in ---------------------------------------------------------------
    def hear(self, line) -> None:
        """One ChatLine or Moderation from `stream/chat`."""
        if isinstance(line, Moderation):
            self._moderate(line)
            return
        self.heard += 1
        text = str(getattr(line, "text", "") or "").strip()
        user = str(line.user)
        name = str(getattr(line, "name", "") or user)
        # A YouTube identity is "yt:" and a random channel id, which a short
        # blocked word would match by chance: only its words and name count.
        if not text.startswith("!") or self._blocked(
                text, "" if user.startswith("yt:") else user, name):
            return
        word, _, rest = text[1:].partition(" ")
        word = word.lower().rstrip("?!.,:")          # "!ask?" and "!Ask:" are !ask
        rest = rest.strip()
        message_id = str(getattr(line, "id", "") or "")
        games = self._on("stream.chat_games")
        if word.isdigit() or word == "vote":
            if not self._vote(user, name, word if word.isdigit() else rest):
                return
            self._remember(message_id, "vote", user)
        elif word in ("yes", "no", "predict") and games:
            if not self._call(user, name, word if word != "predict" else rest.lower()):
                return
            self._remember(message_id, "call", user)
        elif word == "name" and self._on("stream.chat_names"):
            key = self._name(user, name, rest)
            if key is None:
                return
            self._remember(message_id, "name", user, key)
        elif word == "ask" and self._on("stream.chat_ask"):
            if not self.asker.hear(user, rest, message_id):
                return
        elif games and word in ("help", "commands"):
            self._answer("help", "Chat commands", self._help())
        elif games and word == "stats":
            self._answer("stats", "Stats", self._stats())
        elif games and word == "why":
            facts = self.facts()
            self._answer("why", "Why", clip(facts.why or facts.plan
                                           or "no decision yet", 180))
        elif games and word == "where":
            self._answer("where", "Where", self.facts().where or "not sure yet")
        elif games and word == "goal":
            self._answer("goal", "Goal", clip(self.facts().goal or
                                              "no gear goal to show", 160))
        elif games and word == "points":
            row = self.board.get(user)
            self._answer(f"points:{user}", f"{name}",
                         f"{row['right']} right of {row['calls']} "
                         f"call{'' if row['calls'] == 1 else 's'}"
                         if row and row["calls"] else "no calls yet — try !yes or !no")
        elif games and word == "top":
            self._answer("top", "Top callers", self._top_text())
        elif self._vote(user, name, text[1:]):
            # "!cactus" or "!pine tree" while a vote is open, the way chat
            # actually types it; `_vote` matches the ballot's own names only.
            self._remember(message_id, "vote", user)
        else:
            return
        self.handled += 1

    def _answer(self, key: str, title: str, body: str) -> None:
        """THE COMMAND COOLDOWN: one answer per command while the last is
        still on screen, so a chat spamming !stats gets one toast, not a
        queue of them (the toast's own reading time, `toast_seconds`)."""
        now = self.clock()
        if now < self._answered.get(key, 0.0):
            return
        item = toast("answer", title, body)
        self._answered[key] = now + item.seconds
        self.outbox.append(item)

    def _help(self) -> str:
        parts = []
        if self.poll is not None and not self.poll.closed:
            parts.append(f"!1-!{len(self.poll.options)} vote the next field")
        parts += ["!yes / !no call the trip", "!stats", "!why", "!where",
                  "!goal", "!points", "!top"]
        if self._on("stream.chat_ask"):
            parts.append("!ask <question>")
        if self._on("stream.chat_names"):
            parts.append("!name <words>")
        return " · ".join(parts)

    def _stats(self) -> str:
        f = self.facts()
        bits = []
        if f.honey is not None:
            bits.append(f"{human(f.honey)} honey")
        if f.rate:
            bits.append(f"{human(f.rate)}/h")
        bits.append(f"{f.trips} trips, {f.deaths} knocked out in 24h")
        if self.handed_in or self.quest_steps_done:
            bits.append(f"{self.handed_in} quests handed in, "
                        f"{self.quest_steps_done} steps done this stream")
        return " · ".join(bits)

    def _moderate(self, mod) -> None:
        """Twitch's moderators reach the overlay too (stream/chat).

        CLEARMSG (one message deleted) takes back exactly what that message
        did: its vote, its call or its name. CLEARCHAT for one user (a
        timeout or a ban) takes back everything of theirs on screen -- votes,
        calls, names, ticker lines -- and a BAN, which has no duration, also
        takes them off the leaderboard. CLEARCHAT for nobody (/clear) wipes
        every chat-written word on screen: the names and the ticker.
        """
        self.asker.moderated(user=mod.user or "", message_id=mod.id or "")
        if mod.id:
            what, user, key = self._messages.pop(mod.id, ("", mod.user, ""))
            if what == "vote" and self.poll is not None and not self.poll.closed:
                self.poll.votes.pop(user, None)
            elif what == "call" and self.prediction is not None:
                self.prediction.calls.pop(user, None)
            elif what == "name" and key in self.names:
                del self.names[key]
            self.ticker = [t for t in self.ticker if t[0] != user] if what else self.ticker
            return
        if not mod.user:
            self.names = {}
            self.ticker = []
            return
        user = mod.user
        for key, entry in list(self.names.items()):
            entry["backers"].discard(user)
            if not entry["backers"] or entry.get("user") == user:
                del self.names[key]
        self.ticker = [t for t in self.ticker if t[0] != user]
        if self.poll is not None and not self.poll.closed:
            self.poll.votes.pop(user, None)
        if self.prediction is not None:
            self.prediction.calls.pop(user, None)
        if getattr(mod, "ban", False) and self.board.pop(user, None) is not None:
            self._save_board()

    # ---- the field vote ------------------------------------------------------
    def on_ballot(self, ballot: ChatBallot) -> None:
        """The bot published who chat may vote between for the next trip."""
        # WHAT HAPPENED TO CHAT'S LAST VOTE is news for one trip, then it is
        # stale: "chat voted cactus — trying it next" must not stay up through
        # the hour's cooldown while the planner chooses on its own. The gate
        # publishes one ballot at every gathering plan, after it has said
        # what it did with the vote (run_farm `plan`), so the first ballot
        # after `pending` was set is that trip's and the second is the next's.
        self._pending_ballots += 1
        if self._pending_ballots >= 2:
            self.pending = ""
        self._unheard = None
        if not self._on("stream.chat_may_pick_fields"):
            self.poll = None
            self.poll_note = ""
            return
        if not self.listening:
            self.poll = None
            self.poll_note = "no chat is connected, so there is no vote"
            self._unheard = ballot      # offered again once a chat joins
            return
        self._open(ballot)

    def set_listening(self, on: bool) -> None:
        """A chat reader joined its chat, or lost it. A ballot that came while
        nobody could vote is offered once somebody can -- the window opened
        mid-trip, or the second a Twitch JOIN takes -- if it is still young
        enough to vote on."""
        was, self.listening = self.listening, bool(on)
        ballot = self._unheard
        if self.listening and not was and ballot is not None:
            self._unheard = None
            if self._on("stream.chat_may_pick_fields"):
                self._open(ballot)
            else:
                self.poll_note = ""

    def _open(self, ballot: ChatBallot) -> None:
        now = self.clock()
        if self.poll is not None and not self.poll.closed:
            self._tick("", "the trip ended before the vote closed — new vote")
        self.poll = None
        options = [o for o in (ballot.options or []) if isinstance(o, dict)
                   and o.get("field")][:5]
        if len(options) < 2:
            self.poll_note = ballot.reason or "no field vote this trip"
            return
        # Cut to close TRIP_P25_SECONDS after the ballot, before the next
        # field choice, however long stream.poll_seconds asks for.
        age = max(0.0, now - float(ballot.at or now))
        length = min(self.poll_seconds(), TRIP_P25_SECONDS - age)
        if length < POLL_MIN_SECONDS:
            self.poll_note = "this trip's ballot is too old to vote on"
            return
        self.poll = Poll(id=f"{int(now)}", options=options, opened_at=now,
                         ends_at=now + length)
        self.poll_note = ballot.reason
        self._say("poll", "Vote the next field",
                  " · ".join(f"!{i + 1} {o['label']}" for i, o in enumerate(options)))

    def _vote(self, user: str, name: str, what: str) -> bool:
        poll = self.poll
        if poll is None or poll.closed:
            return False
        what = str(what or "").strip().lower()
        index = None
        if what.isdigit():
            index = int(what) - 1
        else:
            # The ballot's own names, or three letters or more of one ("!cac");
            # "!s" could be strawberry or spider, and counts for neither.
            matches = [i for i, option in enumerate(poll.options)
                       if what and (what in (option["field"], option["label"])
                                    or (len(what) >= 3
                                        and option["label"].startswith(what)))]
            if len(matches) == 1:
                index = matches[0]
        if index is None or not 0 <= index < len(poll.options):
            return False
        poll.votes[user] = index
        self._touch(user, name)["votes"] += 1
        self._tick(user, f"{name} voted {poll.options[index]['label']}")
        return True

    def _close_poll(self, now: float) -> None:
        poll = self.poll
        poll.closed = True
        counts = poll.counts()
        voters = sum(counts)
        self._pending_ballots = 0
        if not voters:
            self.pending = "nobody voted — the bot chooses the next field itself"
            return
        # A tie goes to the option the planner ranked higher: the ballot is
        # best first, and max() keeps the first of equals.
        best = max(range(len(counts)), key=lambda i: counts[i])
        option = poll.options[best]
        # Stamped NOW, as the poll closes: the gate ages a vote from when chat
        # cast it, however late it arrives (stream/gate.offer).
        vote = ChatVote(what="field", choice=option["field"],
                        votes=counts[best], voters=voters, poll=poll.id,
                        platform="chat", at=now)
        self.outgoing = vote
        if self.send(vote):
            self.pending = (f"chat picked {option['label']} "
                            f"({counts[best]} of {voters}) — sent to the bot "
                            "for the next trip")
        else:
            self.pending = (f"chat picked {option['label']} "
                            f"({counts[best]} of {voters}) — the bot is between "
                            "runs; it is sent when it is back")
        self._say("poll", f"Chat picked {option['label']}",
                  f"{counts[best]} of {voters} votes · the bot checks it at "
                  "the next field choice")
        self._save_board()

    def resend(self) -> bool:
        """The bot is back (a new process after a rejoin): send chat's vote
        again if the gate has not answered it and it is young enough to use.
        The gate ignores a poll it has already settled, so this is safe to
        repeat."""
        vote = self.outgoing
        if vote is None:
            return False
        if self.clock() - float(vote.at or 0.0) > VOTE_TTL_SECONDS:
            self.outgoing = None
            return False
        return bool(self.send(vote))

    def on_bot_said(self, event, count: bool = True) -> None:
        """The gate's answer ends the vote's story on the panel; a hand-in
        is counted for !stats and the numbers card -- not one replayed from
        before the window opened (`count` False), since the card says
        "since" the time it opened."""
        if (count and isinstance(event, Log) and event.source == "quests"
                and HANDED_IN.match(str(event.message or ""))):
            self.handed_in += 1
        if isinstance(event, Thought) and event.topic == "chat":
            self.pending = clip(event.text, 140)
            self._pending_ballots = 0          # news until the trip after it
            text = str(event.text or "")
            if ("trying it next" in text or "not used" in text
                    or text.startswith("got chat's vote")):
                self.outgoing = None     # the gate has it, or is done with it

    # ---- predictions -------------------------------------------------------
    def set_rows(self, rows: list) -> None:
        """Seed from the ledger once, so its history is not replayed."""
        self._honeys = trip_honey(rows)[-LINE_TRIPS:]
        self._banker = Banker()
        for r in rows:
            self._banker.row(r)     # so a bag carried at the seam is followed
        self._rows_seen_at = max((float(r.get("at") or 0.0) for r in rows),
                                 default=0.0)

    def line(self) -> float | None:
        honey = sorted(self._honeys)
        if len(honey) < LINE_MIN_TRIPS:
            return None
        return two_figures(honey[len(honey) // 2])

    def trip_started(self) -> None:
        """A trip left the hive: open a prediction on what it will bank.

        The caller reads the ledger first (StreamWindow._task). The bot files
        a trip's row before the next trip plans, the carry-in convert's too
        (run_farm `_finished`; MEASURED: 102 of the 105 trips that followed a
        banking row started under 5 s after it, median 0.03 s), so by now the
        last call is settled -- unless no row will ever settle it.
        """
        p = self.prediction
        if p is not None:
            # THE LAST CALL IS STILL OPEN AS THE NEXT TRIP LEAVES: its bag
            # went out again unbanked, or its trip never filed a row (the run
            # was killed mid-trip). MEASURED over var/trips.jsonl: 63 carrying
            # trips were followed straight by another gathering trip, the next
            # process's first, with no carry-in convert between. Left open,
            # that next trip's convert would settle this call.
            self.prediction = None
            self.last_result = ("prediction void — its bag went out again "
                                "before it was banked" if p.carrying else
                                "prediction void — the trip never reported back")
        if not self._on("stream.chat_games") or not self.listening:
            return
        line = self.line()
        if line is None:
            return
        now = self.clock()
        self.prediction = Prediction(id=f"{int(now)}", line=line,
                                     opened_at=now,
                                     ends_at=now + min(self.poll_seconds(),
                                                       TRIP_P25_SECONDS))
        self._say("poll", f"Will this trip bank over {human(line)} honey?",
                  "!yes or !no")

    def _call(self, user: str, name: str, what: str) -> bool:
        p = self.prediction
        if p is None or self.clock() > p.ends_at or what not in ("yes", "no"):
            return False
        p.calls[user] = (what == "yes")
        self._tick(user, f"{name} says {what}")
        self._touch(user, name)
        return True

    def on_trips(self, rows: list) -> None:
        """Every ledger row; only the ones newer than the last look count."""
        if self._rows_seen_at is None:
            self.set_rows(rows)
            return
        fresh = [r for r in rows if float(r.get("at") or 0.0) > self._rows_seen_at]
        if not fresh:
            return
        self._rows_seen_at = max(float(r.get("at") or 0.0) for r in fresh)
        for row in fresh:
            self._row(row)

    def _row(self, row: dict) -> None:
        said = self._banker.row(row)
        p = self.prediction
        if said is None:
            # A row after the call opened that neither gathered nor converted,
            # with no bag being carried: the trip it was about never
            # happened (a stop, a travel that failed, a death on the way).
            if (p is not None and not p.carrying
                    and float(row.get("at") or 0.0) > p.opened_at):
                why = str(row.get("reason") or row.get("gather_ended")
                          or "the trip did not gather")
                self.prediction = None
                self.last_result = f"prediction void — {clip(why, 80)}"
                self._say("poll", "Prediction void", clip(why, 100))
            return
        kind, trip = said[0], said[1]
        mine = (p is not None and trip is not None
                and float(trip.get("at") or 0.0) > p.opened_at)
        if kind == "carrying":
            if mine:
                p.carrying = True
                self.last_result = ("the trip is over; its bag is banked after "
                                    "the rejoin, and that settles the call")
            return
        if kind == "void":
            if mine:
                self.prediction = None
                self.last_result = f"prediction void — {clip(said[2], 80)}"
                self._say("poll", "Prediction void", clip(said[2], 100))
            return
        honey, how = said[2], said[3]
        if trip is not None:
            history = sorted(self._honeys)
            big = (len(history) >= BIG_MIN_TRIPS
                   and honey >= history[int(0.9 * (len(history) - 1))])
            where = str(trip.get("credited") or "")
            body = [f"from the {where.replace('_', ' ')} field" if where
                    else "the field unconfirmed", how]
            if big:
                body.append("top tenth of recent trips")
            self._say("record" if big else "convert",
                      ("Big convert " if big else "Converted ") + f"+{human(honey)}",
                      " · ".join(body))
            self._honeys = (self._honeys + [honey])[-LINE_TRIPS:]
        if not mine:
            return
        self.prediction = None
        over = honey > p.line
        right = [u for u, said_yes in p.calls.items() if said_yes == over]
        for user, said_yes in p.calls.items():
            row_b = self.board.get(user)
            if row_b is not None:
                row_b["calls"] += 1
                row_b["right"] += int(said_yes == over)
        self.last_result = (f"{human(honey)} — {'over' if over else 'under'} "
                            f"{human(p.line)}; {len(right)} of {len(p.calls)} "
                            "called it")
        self._say("poll", f"{'Over' if over else 'Under'}! +{human(honey)}",
                  f"{len(right)} of {len(p.calls)} called it" if p.calls else
                  "nobody called this one")
        self._save_board()

    # ---- the leaderboard ------------------------------------------------------
    def _touch(self, user: str, name: str) -> dict:
        row = self.board.get(user)
        if row is None:
            row = self.board[user] = {"name": clip(name, 25), "right": 0,
                                      "calls": 0, "votes": 0}
        row["name"] = clip(name, 25)
        return row

    def top(self, n: int = 5) -> list:
        ranked = sorted(self.board.items(),
                        key=lambda kv: (-kv[1]["right"], -kv[1]["calls"],
                                        -kv[1]["votes"], kv[0]))
        return [(v["name"], v["right"], v["calls"]) for _, v in ranked
                if v["calls"]][:n]

    def _top_text(self) -> str:
        rows = self.top()
        return (" · ".join(f"{i + 1}. {n} {r}/{c}" for i, (n, r, c) in enumerate(rows))
                if rows else "nobody yet — !yes or !no on the next trip")

    def _load_board(self) -> None:
        if self.board_path is None:
            return
        try:
            body = json.loads(self.board_path.read_text())
            users = body.get("users") if isinstance(body, dict) else None
            if isinstance(users, dict):
                for user, row in users.items():
                    if isinstance(row, dict):
                        self.board[str(user)] = {
                            "name": clip(row.get("name") or user, 25),
                            "right": int(row.get("right") or 0),
                            "calls": int(row.get("calls") or 0),
                            "votes": int(row.get("votes") or 0)}
        except (OSError, ValueError, TypeError):
            pass

    def _save_board(self) -> None:
        if self.board_path is None:
            return
        if len(self.board) > BOARD_LIMIT:
            keep = sorted(self.board.items(),
                          key=lambda kv: (-kv[1]["right"], -kv[1]["calls"],
                                          -kv[1]["votes"]))[:BOARD_LIMIT]
            self.board = dict(keep)
        try:
            from ..files import atomic_write
            atomic_write(self.board_path, json.dumps(
                {"format": 1, "users": self.board}, indent=1, sort_keys=True))
        except OSError:
            pass

    # ---- milestones -----------------------------------------------------------
    def on_honey(self, honey: float, per_hour: float | None) -> None:
        """A honey reading. Fires the milestone after two readings over it."""
        if honey is None or honey <= 0:
            return
        if self.milestone is None:
            # No rate measured yet means no step: the milestone waits for one
            # rather than inventing how far apart they should be.
            step = nice_step(per_hour or 0.0)
            if step:
                self.milestone = (math.floor(honey / step) + 1) * step
            return
        if honey < self.milestone:
            self._over = 0
            return
        self._over += 1
        if self._over < MILESTONE_READINGS:
            return
        reached = self.milestone
        named = self.leading_name()
        self._say("milestone", f"{human(reached)} honey",
                  (f"named “{named[0]}” by {named[1]}" if named else
                   "a milestone"))
        self.names = {}
        self._over = 0
        self.milestone = None            # the next reading sets the next one

    def _name(self, user: str, name: str, words: str):
        """Back a name for the next milestone; the key, or None if refused."""
        words = " ".join(str(words or "").split())
        if not NAME_OK.match(words) or self._blocked(words):
            return None
        key = words.lower()
        for entry in self.names.values():
            entry["backers"].discard(user)
        entry = self.names.setdefault(key, {"text": words, "backers": set(),
                                            "at": self.clock(), "by": name,
                                            "user": user})
        entry["backers"].add(user)
        self.names = {k: v for k, v in self.names.items() if v["backers"]}
        self._tick(user, f"{name} named it “{words}”")
        return key

    def leading_name(self):
        if not self.names:
            return None
        key = min(self.names, key=lambda k: (-len(self.names[k]["backers"]),
                                            self.names[k]["at"]))
        entry = self.names[key]
        return entry["text"], entry["by"], len(entry["backers"])

    # ---- quests -----------------------------------------------------------------
    def on_quests(self, body: dict) -> None:
        """A new reading of var/quests.json: toast steps newly Complete."""
        try:
            from ..brain.questneeds import steps_of
            state = {}
            for quest in body.get("quests") or ():
                name = str(quest.get("name") or "")
                for step in steps_of(name, list(quest.get("requirements") or ())):
                    # The same step, read before and after it finished: the
                    # menu's "20,630/160,000" becomes "Complete!", and
                    # steps_of strips the first but keeps the second.
                    key = COMPLETE_WORD.sub("", step.text).strip()
                    state[(name, key)] = bool(step.complete)
        except Exception:
            return
        before, self._quest_state = self._quest_state, state
        if before is None:
            return
        # Each step counts once a stream: a menu read by OCR can drop a
        # "Complete!" for one reading and bring it back on the next, and that
        # must not count the same step twice.
        done = [k for k, complete in state.items()
                if complete and before.get(k) is False
                and k not in self._quest_counted]
        self._quest_counted.update(done)
        self.quest_steps_done += len(done)
        for quest, text in done[:3]:
            self._say("quest", "Quest step done", clip(f"{quest}: {text}", 120))

    # ---- the clock ---------------------------------------------------------------
    def tick(self) -> None:
        now = self.clock()
        if self.poll is not None and not self.poll.closed and now >= self.poll.ends_at:
            self._close_poll(now)
        if (self.poll is not None and self.poll.closed
                and now > self.poll.ends_at + TOAST_MAX_S):
            self.poll = None
        # A trip that never reports back (the run was killed mid-trip) must
        # not hold the prediction open for ever: void it after two trips, the
        # same age at which the bot's gate drops a stale vote.
        p = self.prediction
        if p is not None and now - p.opened_at > VOTE_TTL_SECONDS:
            self.prediction = None
            self.last_result = "prediction void — the trip never reported back"
        answer = self.asker.next_answer()
        if answer:
            self._say("ask", "Chat asked", answer)

    def drain(self) -> list[Toast]:
        out, self.outbox = self.outbox, []
        return out
