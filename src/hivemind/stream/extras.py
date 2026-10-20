"""What makes the stream worth watching for 24 hours, from what is real.

THE OWNER'S ASK: make it entertaining. Everything here is built
from the bot's own words and files -- nothing is invented, nothing is
estimated for show. No Qt, so it is driven offline (gui/stream_extras draws
it):

  COMMENTARY   one friendly line for the header, turned from the bot's own
               decisions: "Next stop: Pine Tree — the best of 7 fields at
               1,257 pollen/s", "Cannon launch! Flying to Pine Tree",
               "Gathering in Spider — backpack 46%", "+2.55M honey banked".
  TODAY        records and streaks from var/trips.jsonl: the best trip today,
               trips in a row without a knock-out, tokens chased, the field
               that paid most. A new best trip and a round-number streak are
               toasts, and clip markers. Knock-outs are the ones the bot
               kept an incident of or the stream saw (`Knockouts`), not the
               ledger's `deaths` alone.
  QUESTS       each open quest step's progress, from var/quests.json.
  RECAP        at midnight (local, or UTC with stream.utc_times), the day
               just ended: honey, trips, the best
               trip, knock-outs, tokens, and what the stream window itself
               counted while it was open (quests handed in, cannon launches,
               boss sightings, chat's best caller).
  CLIPS        a timestamp in var/stream_clips.txt for every big convert,
               new best trip, knock-out, boss sighting, quest hand-in,
               milestone and recap, to find the highlights afterwards (or to
               line up with OBS's replay buffer).

DESIGN 8ec.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..telemetry.events import Considered, Log, TaskUpdate, Thought
from . import privacy
from .show import (BOSS_WORDS, CANNON_WORDS, DEATH_TOAST_GAP_SECONDS, HANDED_IN,
                   Banker, gathered, human)


def title(slug: str) -> str:
    """"pine_tree" -> "Pine Tree"."""
    return " ".join(w[:1].upper() + w[1:] for w in str(slug or "").replace("_", " ").split())


def _score(value: float, unit: str) -> str:
    if unit == "pollen/s":
        return f"{value:,.0f} pollen/s"
    return f"a score of {value:,.0f}"


# ---- the commentary line ----------------------------------------------------------

# HOW LONG A LINE STAYS. A routine line (gathering %, a token chase) gives way
# to the next after ROUTINE_S; an event (a cannon launch, a convert, a
# knock-out) holds EVENT_S against routine lines. A line of 10-14 words reads
# in 2.5-3.5 s at 238 words a minute (Brysbaert 2019, stream/show.READ_WPM),
# so both leave time to read it twice.
ROUTINE_S = 6.0
EVENT_S = 10.0
ROUTINE, EVENT = 1, 2
# The gathering line moves at most once per this much of the backpack: the
# farm loop reports the fill after every pass, and a caption that ticks 1% at
# a time is noise.
FILL_STEP = 0.10
CHASING = re.compile(r"^chasing an? (.+?) token\b")
WHERE_FIELD = re.compile(r"^I am in the (.+?) field\b")


class Commentary:
    """`saw(event)` and `said(toast)`; read `line`."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.line = ""
        self._until = 0.0
        self._priority = 0
        self._field = ""          # where the planner sent this trip
        self._rank = ""           # "the best of 7 fields at 1,257 pollen/s"
        self._landed = ""
        self._landing = False     # the first field fix of a trip is news
        self._fill = -1.0

    def _offer(self, text: str, priority: int) -> bool:
        """An event replaces any line; a routine line waits out the one on
        screen. MEASURED over run-440..445's narration: with routine lines
        replacing each other at once, the line changed 1 s after the last."""
        now = self.clock()
        if now < self._until and (priority < self._priority or priority == ROUTINE):
            return False
        self.line = text
        self._priority = priority
        self._until = now + (EVENT_S if priority >= EVENT else ROUTINE_S)
        return True

    def saw(self, event) -> None:
        if isinstance(event, Considered):
            options = list(event.options or [])
            chosen = str(event.chosen or "")
            if not options or not chosen:
                return
            label = chosen.replace("_", " ")
            index = next((i for i, o in enumerate(options)
                          if str(o.label).replace("_", " ") == label), None)
            if index is None:
                return
            mine = options[index]
            n = len(options)
            self._rank = (f"the best of {n} fields at {_score(mine.score, mine.unit)}"
                          if index == 0 else
                          f"#{index + 1} of {n} fields at {_score(mine.score, mine.unit)}")
            if label != self._field:
                self._field = label
                self._offer(f"Next stop: {title(label)} — {self._rank}", EVENT)
            return
        if isinstance(event, TaskUpdate):
            self._task(event)
            return
        if isinstance(event, Thought):
            text = str(event.text or "")
            if event.topic == "journey" and text.startswith(CANNON_WORDS):
                where = f" to {title(self._field)}" if self._field else ""
                self._offer(f"Cannon launch! Flying{where}", EVENT)
            elif event.topic == "where" and self._landing:
                # THE FIRST FIX OF THE TRIP ONLY. MEASURED in run-444.log
                # 10:17:38-10:18:51, the compass named spider, strawberry and
                # spider again at the edge of the field; a caption each time
                # would flicker.
                landed = WHERE_FIELD.match(text)
                if landed:
                    self._landed, self._landing = landed.group(1), False
                    self._offer(f"Landed in the {title(self._landed)} field", EVENT)
            elif event.topic == "chat" and "trying it next" in text:
                self._offer(text[:1].upper() + text[1:], EVENT)
            return
        if isinstance(event, Log):
            text = str(event.message or "")
            chased = CHASING.match(text)
            if chased:
                self._offer(f"Chasing a {chased.group(1)} token", ROUTINE)

    def _task(self, event: TaskUpdate) -> None:
        where = title(self._landed or self._field)
        if event.name == "travel to the field" and event.status == "running":
            by = " by cannon" if "cannon" in str(event.detail or "") else ""
            self._fill = -1.0
            self._landed, self._landing = "", True
            if self._field:
                rank = f" — {self._rank}" if self._rank else ""
                self._offer(f"Heading to {title(self._field)}{by}{rank}", EVENT)
        elif event.name == "gather" and event.status == "running":
            fill = float(event.progress if event.progress is not None else -1)
            if fill < 0 or not where:
                return
            if self._fill < 0 or abs(fill - self._fill) >= FILL_STEP:
                self._fill = fill
                self._offer(f"Gathering in {where} — backpack {fill:.0%}", ROUTINE)
        elif event.name == "convert" and event.status == "running":
            self._offer("Back at the hive — making honey", ROUTINE)

    def said(self, toast) -> None:
        """A toast the stream just showed, as a caption where it is news."""
        kind, head, body = toast.kind, str(toast.title), str(toast.body or "")
        if kind in ("convert", "record") and not head.startswith("New best"):
            where = re.search(r"from the (.+?) field", body)
            self._offer(f"{head.replace('Converted ', '').replace('Big convert ', '')}"
                        f" honey banked" + (f" from {title(where.group(1))}" if where
                                            else ""), EVENT)
        elif kind == "death":
            self._offer(f"Knocked out! {body}".strip(), EVENT)
        elif kind == "quest":
            self._offer(f"{head} {body}".strip(), EVENT)
        elif kind == "threat" and head.startswith("Boss"):
            self._offer(f"Boss spotted! {body}".strip(), EVENT)
        elif kind == "milestone":
            self._offer(f"Milestone: {head}", EVENT)
        elif kind in ("streak", "best"):
            self._offer(head, EVENT)


# ---- today, from the ledger -------------------------------------------------------

def local_midnight(at: float) -> float:
    """The midnight at or before `at`, on the clock the stream shows (local,
    or UTC with stream.utc_times: stream/privacy.day_start)."""
    return privacy.day_start(at)


@dataclass
class Trip:
    at: float
    honey: float
    field: str          # the field the reward feed credited, or ""


@dataclass
class Day:
    """One day of the ledger. Honey is the ledger's own sum over the day's
    rows (carry-in converts included), as the numbers card counts it;
    `trips` are the rows that gathered (stream/show.gathered); `deaths` are
    the day's knock-outs (`Knockouts`), or the ledger's own count if that is
    more."""
    start: float
    end: float
    trips: int = 0
    honey: float = 0.0
    deaths: int = 0
    tokens: int = 0
    best: Trip | None = None
    by_field: dict = field(default_factory=dict)    # credited -> (trips, honey)
    banked: list = field(default_factory=list)      # Trip, oldest first

    def top_field(self):
        """(field, trips, honey) of the credited field that banked most."""
        if not self.by_field:
            return None
        name = max(self.by_field, key=lambda k: (self.by_field[k][1], self.by_field[k][0]))
        return (name, *self.by_field[name])


# A DAY'S TRIPS NEED A LITTLE OF THE DAY BEFORE: a trip's honey can be the
# carry-in convert after a rejoin (show.Banker), and the Banker has to have
# seen the trip first. Its state resets at every gathering row, so a day of
# lead-in is far more than it needs and keeps the work bounded as the ledger
# grows (it is never trimmed).
LEAD_IN_S = 86400.0


def day_of(rows, start: float, end: float, knockouts=()) -> Day:
    """The day [start, end) from ledger rows (oldest first). A trip's honey
    is its own convert or the carry-in after its rejoin (show.Banker), and
    counts on the day the trip was filed."""
    day = Day(start=start, end=end)
    banker = Banker()
    booked = 0
    for r in rows:
        at = float(r.get("at") or 0.0)
        if at < start - LEAD_IN_S:
            continue
        said = banker.row(r)
        inside = start <= at < end
        if inside:
            if gathered(r):
                day.trips += 1
            if r.get("honey") is not None:
                day.honey += float(r.get("honey") or 0)
            booked += int(r.get("deaths") or 0)
            day.tokens += int(r.get("tokens") or 0)
        if said and said[0] == "banked" and said[1] is not None:
            trip = said[1]
            trip_at = float(trip.get("at") or 0.0)
            if start <= trip_at < end:
                where = str(trip.get("credited") or "")
                item = Trip(at=trip_at, honey=float(said[2]), field=where)
                day.banked.append(item)
                if day.best is None or item.honey > day.best.honey:
                    day.best = item
                if where:
                    n, h = day.by_field.get(where, (0, 0.0))
                    day.by_field[where] = (n + 1, h + item.honey)
    day.deaths = max(booked, sum(1 for k in knockouts if start <= k < end))
    return day


# ---- knock-outs ---------------------------------------------------------------------
#
# THE LEDGER'S `deaths` MISSES KNOCK-OUTS. MEASURED over the ledger's span
# (22-26 September): the bot narrated 9 ("died: ..." lines), every one has
# its own var/incidents/*-death folder, and the ledger booked 4 (Tue 15:43,
# Wed 00:44, Wed 03:44, Thu 04:19). Today's 11:44:44 knock-out was filed with
# deaths 0 by the row written that second (attempt 447, cycle 4), so the
# stream toasted "Knocked out" beside "0 knock-outs today". Two of the nine
# were Conversion Links the death watch misread (brain/fieldnotes
# FALSE_DEATHS: 231125/231129 and 20260924-055153), which the bot now vetoes.
# So a knock-out is an incident folder that is not one of those, a death the
# stream toasted, or a ledger row that booked one with neither near it.

INCIDENT = re.compile(r"^(?:(\d{8})-)?(\d{6})-death$")
# THE KNOCK-OUT'S OWN TRIP is the next row filed. MEASURED: the row after
# each incident was filed 0 to 195 s after it (Thu 04:16:15 -> 04:19:30).
OWN_ROW_S = 300.0


def incident_time(path: Path) -> float | None:
    """When an incident folder's death happened, from its name: the older
    names carry the time only ("183123-death"), the newer the date too
    ("20260926-114444-death"); a time-only name is on its folder's day."""
    m = INCIDENT.match(path.name)
    if not m:
        return None
    date, hms = m.groups()
    try:
        if date:
            return dt.datetime.strptime(date + hms, "%Y%m%d%H%M%S").timestamp()
        mtime = path.stat().st_mtime
        when = dt.datetime.fromtimestamp(mtime).replace(
            hour=int(hms[:2]), minute=int(hms[2:4]), second=int(hms[4:]),
            microsecond=0)
    except (OSError, ValueError):
        return None
    if when.timestamp() > mtime + 60:
        when -= dt.timedelta(days=1)
    return when.timestamp()


def merged(times, gap: float = DEATH_TOAST_GAP_SECONDS) -> list:
    """One time per knock-out: a death is told two to four times and can
    leave two folders three seconds apart (154239 and 154242)."""
    out: list = []
    for t in sorted(times):
        if not out or t - out[-1] > gap:
            out.append(t)
    return out


class Knockouts:
    """Every knock-out the stream can know of, oldest first: `times(rows)`.
    `folder` is var/incidents, read again at each call (a listdir of about
    twenty names); `seen(at)` is a death the stream toasted."""

    def __init__(self, folder=None, false=None):
        self.folder = Path(folder) if folder else None
        if false is None:
            try:
                from ..brain.fieldnotes import FALSE_DEATHS
                false = set(FALSE_DEATHS)
            except Exception:
                false = set()
        self.false = set(false)
        self._seen: list = []

    def seen(self, at: float) -> None:
        self._seen.append(float(at))

    def folders(self) -> list:
        if self.folder is None:
            return []
        try:
            names = list(self.folder.iterdir())
        except OSError:
            return []
        out = []
        for p in names:
            if p.name in self.false:
                continue
            at = incident_time(p)
            if at is not None:
                out.append(at)
        return out

    def times(self, rows=()) -> list:
        known = merged(self.folders() + self._seen)
        extra = []
        for r in rows:
            booked = int(r.get("deaths") or 0)
            if not booked:
                continue
            at = float(r.get("at") or 0.0)
            # ITS OWN KNOCK-OUT came up to OWN_ROW_S before the row
            near = sum(1 for k in known if at - OWN_ROW_S <= k <= at + 10)
            extra += [at] * max(0, booked - near)
        return sorted(known + extra)


def streak(rows, knockouts=()) -> int:
    """Gathering trips since the last knock-out, not counting that
    knock-out's own trip (the first row filed within OWN_ROW_S of it)."""
    rows = list(rows)
    last = max(knockouts) if knockouts else None
    if last is None:
        return sum(1 for r in rows if gathered(r))
    after = [r for r in rows if float(r.get("at") or 0.0) >= last - 10]
    if after and float(after[0].get("at") or 0.0) <= last + OWN_ROW_S:
        after = after[1:]
    return sum(1 for r in after if gathered(r))


def last_knockout(knockouts) -> float | None:
    return max(knockouts) if knockouts else None


# Streak toasts at round numbers only: a toast every trip is noise.
STREAK_MARKS = (10, 25, 50, 100, 150, 200, 300, 500)
# A best trip is news once the day has a few trips to beat: MEASURED, 26 of
# the last 24 hours' 31 gathering trips banked (stream/show), so by the
# fourth banked trip of a day there are three to beat.
RECORD_AFTER = 3
# ...and when it beats the day's best by a margin a viewer can see. MEASURED
# over var/trips.jsonl replayed row by row (2026-09-22 to 09-26): with no
# margin, 25 September alone had five "new best" toasts, four of them under
# 2% ("+1.56M, beats 1.55M"). With the 5% margin, and the toast only for the
# trip just banked, there are 3 in the 4.3 days, each with the day's true
# previous best: 1.29M beats 1.19M, 1.7M beats 1.33M, 2.94M beats 2.77M.
RECORD_MARGIN = 1.05


class Records:
    """Today from the ledger, and the toasts it earns. `on_rows(rows,
    knockouts)` with the whole ledger each time it changes; read `today`,
    `streak`; drain `news` for (kind, title, body) toasts."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.today: Day | None = None
        self.streak = 0
        self.news: list[tuple[str, str, str]] = []
        self._seen_best: float | None = None
        self._seen_streak: int | None = None
        self._day_start: float | None = None

    def on_rows(self, rows, knockouts=()) -> None:
        now = self.clock()
        start = local_midnight(now)
        day = day_of(rows, start, start + 86400, knockouts)
        run = streak(rows, knockouts)
        if self._day_start != start:
            # a new day (or the first look): nothing to announce yet
            self._day_start = start
            self._seen_best = day.best.honey if day.best else None
        elif day.best is not None:
            # ONLY THE TRIP JUST BANKED, against the best before it. MEASURED
            # (review/best_drive.py): announcing whatever the day's best was
            # when the day reached its fourth banked trip gave 4 wrong
            # figures in 6 -- a record set an hour earlier, or "beats" a
            # figure under the day's real previous best -- because the best
            # set by the 2nd or 3rd trip was never taken in.
            newest = day.banked[-1] if day.banked else None
            if (self._seen_best is not None and newest is day.best
                    and len(day.banked) > RECORD_AFTER
                    and day.best.honey >= self._seen_best * RECORD_MARGIN):
                where = (f"from {title(day.best.field)}" if day.best.field
                         else "the field unconfirmed")
                self.news.append(("best", f"New best trip today! +{human(day.best.honey)}",
                                  f"{where} · beats {human(self._seen_best)}"))
            if self._seen_best is None or day.best.honey > self._seen_best:
                self._seen_best = day.best.honey
        if self._seen_streak is not None and run > self._seen_streak:
            passed = [m for m in STREAK_MARKS if self._seen_streak < m <= run]
            if passed:
                last = last_knockout(knockouts)
                self.news.append(("streak", f"{passed[-1]} trips in a row without a "
                                            "knock-out",
                                  "the last one was "
                                  + privacy.clock_text(last, "%a %H:%M", zone=True)
                                  if last else "none on record"))
        self._seen_streak = run
        self.today, self.streak = day, run

    def drain(self) -> list:
        out, self.news = self.news, []
        return out


# ---- what only the stream window counts ------------------------------------------

@dataclass
class Tally:
    """Counts the ledger does not keep, from the bot's words, per day while
    the window is open."""
    day: float = 0.0
    handed_in: int = 0
    cannon: int = 0
    bosses: int = 0
    deaths_seen: int = 0


class Counter:
    """`saw(event)`; `tally` is today's, `yesterday` the day before's."""

    def __init__(self, clock=time.time, opened_at: float | None = None):
        self.clock = clock
        self.opened_at = clock() if opened_at is None else opened_at
        self.tally = Tally(day=local_midnight(self.opened_at))
        self.yesterday: Tally | None = None

    def _roll(self) -> None:
        start = local_midnight(self.clock())
        if start != self.tally.day:
            self.yesterday, self.tally = self.tally, Tally(day=start)

    def saw(self, event) -> None:
        self._roll()
        if isinstance(event, Log):
            text = str(event.message or "")
            if event.source == "quests" and HANDED_IN.match(text):
                self.tally.handed_in += 1
            if BOSS_WORDS in text:
                self.tally.bosses += 1
        elif isinstance(event, Thought):
            if event.topic == "journey" and str(event.text or "").startswith(CANNON_WORDS):
                self.tally.cannon += 1


# ---- the recap at midnight ----------------------------------------------------------

@dataclass
class Recap:
    date: str
    lines: list          # (label, value, note)


def recap(rows, day_start: float, tally: Tally | None = None,
          board_delta: dict | None = None, opened_at: float | None = None,
          knockouts=()) -> Recap | None:
    """The day that began at `day_start`, from the ledger and what the window
    counted. None if the ledger has nothing that day."""
    day = day_of(rows, day_start, day_start + 86400, knockouts)
    if not day.trips and not day.honey:
        return None
    lines = [("HONEY BANKED", human(day.honey), f"over {day.trips} trip"
              f"{'' if day.trips == 1 else 's'}")]
    if day.best is not None:
        when = privacy.clock_text(day.best.at, "%H:%M")
        lines.append(("BEST TRIP", f"+{human(day.best.honey)}",
                      f"{title(day.best.field) if day.best.field else 'field unconfirmed'}"
                      f" · {when}"))
    top = day.top_field()
    if top is not None:
        lines.append(("TOP FIELD", title(top[0]),
                      f"{top[1]} trip{'' if top[1] == 1 else 's'} · {human(top[2])}"))
    lines.append(("KNOCKED OUT", f"{day.deaths}",
                  "not once" if not day.deaths else
                  f"{day.deaths} time{'' if day.deaths == 1 else 's'}"))
    lines.append(("TOKENS CHASED", f"{day.tokens:,}", ""))
    partial = opened_at is not None and opened_at > day_start
    since = (f"since {privacy.clock_text(opened_at, '%H:%M')}"
             if partial else "all day")
    if tally is not None and tally.day == day_start:
        # A count the window kept for part of the day is shown when it has
        # something in it; "0 seen since 23:59" says nothing.
        for label, value in (("QUESTS HANDED IN", tally.handed_in),
                             ("CANNON LAUNCHES", tally.cannon),
                             ("BOSS SIGHTINGS", tally.bosses)):
            if value or (not partial and label != "BOSS SIGHTINGS"):
                lines.append((label, f"{value}", f"seen {since}"))
    if board_delta:
        name, right = max(board_delta.items(), key=lambda kv: kv[1])
        if right > 0:
            lines.append(("CHAT'S BEST CALLER", name,
                          f"{right} call{'' if right == 1 else 's'} right"))
    date = privacy.date_text(day_start, "%A %-d %B") + (
        " (UTC)" if privacy.utc_shown() else "")
    return Recap(date=date, lines=lines)


def board_delta(before: dict, after: dict) -> dict:
    """name -> right calls gained between two leaderboard readings
    (stream/show.Show.board rows)."""
    out = {}
    for user, row in after.items():
        gained = int(row.get("right") or 0) - int((before.get(user) or {}).get("right") or 0)
        if gained > 0:
            out[str(row.get("name") or user)] = gained
    return out


# ---- quests ---------------------------------------------------------------------------

@dataclass
class QuestBar:
    quest: str
    text: str
    done: int
    total: int

    @property
    def fraction(self) -> float:
        return min(1.0, self.done / self.total) if self.total else 0.0


QUEST_STEP_WORDS = re.compile(r"\s*(?:Complete!?|Talk to .*)$", re.IGNORECASE)
COLLECT = re.compile(r"^Collect [\d,]+ ", re.IGNORECASE)


def short_step(text: str) -> str:
    """"Collect 4,000,000 Pollen from the Clover Field. 886,637/4,000,000"
    -> "Pollen from the Clover Field": the numbers go on the bar's own count,
    and the first render cut the whole line at "from t"."""
    text = re.sub(r"\s*[\d,]+/[\d,]+\s*$", "", str(text or ""))
    text = QUEST_STEP_WORDS.sub("", text).strip()
    text = COLLECT.sub("", text).rstrip(". ")
    return text[:1].upper() + text[1:]


def quest_bars(body: dict, limit: int = 4) -> tuple[list, list]:
    """(open steps with a total, closest to done first; quests ready to hand
    in) from var/quests.json."""
    try:
        from ..brain.questneeds import steps_of
    except Exception:
        return [], []
    bars = []
    for quest in (body or {}).get("quests") or ():
        name = str(quest.get("name") or "")
        try:
            steps = steps_of(name, list(quest.get("requirements") or ()))
        except Exception:
            continue
        for step in steps:
            if step.complete or not step.total:
                continue
            text = short_step(step.text)
            bars.append(QuestBar(quest=name, text=text, done=int(step.done),
                                 total=int(step.total)))
    bars.sort(key=lambda b: -b.fraction)
    ready = []
    for giver, item in ((body or {}).get("ready_since") or {}).items():
        quest = str((item or {}).get("quest") or "") if isinstance(item, dict) else ""
        ready.append(quest or title(giver))
    return bars[:limit], ready


# ---- clip markers ----------------------------------------------------------------------

CLIP_KINDS = {"record": "BIG CONVERT", "best": "BEST TRIP", "death": "KNOCKED OUT",
              "boss": "BOSS", "quest": "QUEST", "milestone": "MILESTONE",
              "streak": "STREAK", "recap": "RECAP"}
# One marker per kind this close together: a death is told two to four times
# (stream/show.DEATH_TOAST_GAP_SECONDS), and one mark finds the moment.
CLIP_GAP_S = 30.0


class Clips:
    """Appends "date time  +h:mm:ss  KIND  what" lines. The +h:mm:ss is from
    when the stream window opened, which is what a recording made of it
    counts from."""

    def __init__(self, path, clock=time.time, opened_at: float | None = None,
                 enabled=lambda: True):
        self.path = Path(path) if path else None
        self.clock = clock
        self.opened_at = clock() if opened_at is None else opened_at
        self.enabled = enabled
        self._last: dict = {}
        self.written = 0

    def mark(self, kind: str, what: str) -> bool:
        if self.path is None or not self.enabled():
            return False
        now = self.clock()
        if now - self._last.get(kind, -1e9) < CLIP_GAP_S:
            return False
        self._last[kind] = now
        since = max(0, int(now - self.opened_at))
        line = (f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}  "
                f"+{since // 3600}:{since // 60 % 60:02d}:{since % 60:02d}  "
                f"{CLIP_KINDS.get(kind, kind.upper()):12s}{' '.join(str(what).split())}\n")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            return False
        self.written += 1
        return True

    def from_toast(self, toast) -> bool:
        """The toasts worth a marker, by kind."""
        kind, head, body = toast.kind, str(toast.title), str(toast.body or "")
        what = f"{head} — {body}" if body else head
        if kind == "best":
            return self.mark("best", what)
        if kind == "record":
            return self.mark("record", what)
        if kind == "death":
            return self.mark("death", what)
        if kind == "threat" and head.startswith("Boss"):
            return self.mark("boss", what)
        if kind == "quest" and head.startswith("Quest handed in"):
            return self.mark("quest", what)
        if kind in ("milestone", "streak"):
            return self.mark(kind, what)
        return False
