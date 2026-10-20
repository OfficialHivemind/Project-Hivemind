"""The one gate every chat influence on the bot passes through.

THE OWNER'S ASK: a stream mode that is "interesting for the chat", with chat
able to interact with the macro. The danger in that is obvious -- a stream chat
is strangers -- so chat gets exactly ONE lever, and this file is the only place
that lever is pulled:

    chat may choose which field the NEXT trip goes to,
    from fields the planner itself ranks near its own best.

Nothing else. No chat vote can make the bot convert, buy, spend, rejoin, reset,
fight, type in chat or walk anywhere the planner would not have gone, because
nothing here can do any of those things: the only output is a field slug that
`scripts/run_farm.plan` puts on a decision whose action is already "gather".

EVERY RULE IS CHECKED WHEN THE VOTE IS USED, not when it is cast. The GUI's
ballot is a copy of the bot's ranking from the start of the last trip; by the
time the next trip is chosen the backpack, the quests and the owner's settings
can all have moved. So the settings are read FRESH from the file at each use --
the owner's switch counts at once, with no restart -- and the ranking is the
one the planner has just produced.

    stream.chat_may_pick_fields  off (the default) -> no ballot, no vote used
    stream.chat_cooldown_min     minutes between two chat-picked trips
    stream.chat_field_floor      a field's score as a share of the best, %

What it decided is always SAID, as a `Thought(topic="chat")` the stream window
shows and the run log prints: "chat voted Clover -- trying it next", or why not.

THE VOTE OUTLIVES THE PROCESS. MEASURED over var/trips.jsonl (2026-09-22 04:51
to 09-26 07:11): of 231 pairs of consecutive gathering trips whose attempt is
known, 37 ran in the same bot process -- the other 194 had a rejoin, and so a
new `scripts/run_farm` process, between them. A vote held only in this
object's memory was therefore lost before the next field choice five times in
six. So the pending vote, the cooldown's clock and the polls already settled
are kept in var/stream_gate.json (`state_path`), and the GUI sends a closed
vote again when the bot comes back (stream/show); a poll this gate has
already used or refused is not used twice. DESIGN 8dv.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from ..brain.decide import ROUTER_ALIASES
from ..telemetry.events import ChatBallot, ChatVote, Thought

# NEVER A FIELD A BOSS LIVES IN. The owner's rule for chat is "never anything
# that ... fights bosses", and a field whose boss is up is a fight whether or
# not the bot means one. From the knowledge base: data/knowledge/world.yaml
# gives mountain_top `mobs: [mondo_chick]` ("The Mondo Chick protects this
# field") and coconut `mobs: [coconut_crab]` ("home to and protected by the
# Coconut Crab"); data/knowledge/tickets.yaml:45 lists stump_snail, whose field
# is the Stump Field (bee-swarm-simulator.fandom.com/wiki/Stump_Snail).
BOSS_FIELDS = {
    "mountain_top": "the Mondo Chick",
    "coconut": "the Coconut Crab",
    "stump": "the Stump Snail",
}

# THE BALLOT'S SIZE: Twitch's own polls take 2 to 5 choices
# (dev.twitch.tv/docs/api/polls, "Create Poll"). Fewer than two is not a vote.
BALLOT_MIN = 2
BALLOT_MAX = 5

# A VOTE NOT USED WITHIN TWO TRIPS IS STALE. MEASURED: the median time from
# one gathering trip's end to the next's is 843 s (var/trips.jsonl, 234
# intervals between consecutive gathering trips, 2026-09-22 04:51 to 09-26
# 07:11; the quartiles are 447 s and 1,256 s). A vote is cast for "the next
# trip"; one still waiting after two of them was cast about a situation that
# has gone.
TRIP_SECONDS = 843.0
VOTE_TTL_SECONDS = 2 * TRIP_SECONDS

# Polls already used or refused, remembered so a vote the GUI sends again
# after a rejoin is not used a second time. A vote lives two trips and one
# closes every trip at most, so the last few are all that can come back.
SETTLED_KEEP = 16

# The settings' own defaults are the fallback, so this file and the schema
# cannot disagree (world/settings.SECTIONS, "Stream").
KEY_ON = "stream.chat_may_pick_fields"
KEY_COOLDOWN = "stream.chat_cooldown_min"
KEY_FLOOR = "stream.chat_field_floor"


def _pretty(field: str) -> str:
    return str(field or "").replace("_", " ")


class ChatGate:
    """Bot side. `offer` takes chat's vote off the socket; `field_for` uses it.

    `emit(event)` is the bot's narrate. Every method swallows its own errors:
    a stream feature must never be the reason a trip is not taken.
    """

    def __init__(self, emit=None, settings_path: str | Path | None = None,
                 clock=time.time, state_path: str | Path | None = None):
        self.emit = emit or (lambda event: None)
        self.settings_path = settings_path
        self.clock = clock
        self.state_path = Path(state_path) if state_path else None
        self._lock = threading.Lock()
        self._pending: ChatVote | None = None
        self._last_applied: float | None = None
        self._settled: list[str] = []
        self._load()

    # ---- what survives a rejoin (see the module docstring) -----------------
    def _load(self) -> None:
        if self.state_path is None:
            return
        try:
            body = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(body, dict):
            return
        try:
            last = body.get("last_applied")
            self._last_applied = float(last) if last is not None else None
            self._settled = [str(p) for p in body.get("settled") or ()][-SETTLED_KEEP:]
            vote = body.get("pending")
            if isinstance(vote, dict) and vote.get("choice"):
                self._pending = ChatVote(
                    what="field", choice=str(vote["choice"])[:40],
                    votes=int(vote.get("votes") or 0),
                    voters=int(vote.get("voters") or 0),
                    poll=str(vote.get("poll") or "")[:40],
                    platform=str(vote.get("platform") or "")[:20])
                self._pending.at = float(vote.get("at") or 0.0)
        except (TypeError, ValueError):
            self._pending = None

    def _save(self) -> None:
        """Called with the lock held."""
        if self.state_path is None:
            return
        vote = self._pending
        body = {"format": 1, "last_applied": self._last_applied,
                "settled": self._settled[-SETTLED_KEEP:],
                "pending": None if vote is None else {
                    "choice": vote.choice, "votes": vote.votes,
                    "voters": vote.voters, "poll": vote.poll,
                    "platform": vote.platform, "at": vote.at}}
        try:
            from ..files import atomic_write
            atomic_write(self.state_path, json.dumps(body, indent=1))
        except OSError:
            pass

    def _settle(self, vote: ChatVote) -> None:
        """Called with the lock held: this vote is done with, used or not."""
        if self._pending is vote:
            self._pending = None
        if vote.poll and vote.poll not in self._settled:
            self._settled = (self._settled + [vote.poll])[-SETTLED_KEEP:]
        self._save()

    def pending_choice(self) -> str | None:
        """The field a vote still waiting names, None when none is. The next
        gather choice may be chat's then (`field_for`), so a caller that
        prepares for the next trip's field -- run_farm's booster step --
        asks before it acts on the planner's pick."""
        try:
            with self._lock:
                vote = self._pending
            return str(vote.choice) if vote is not None else None
        except Exception:
            return None

    # ---- the owner's settings, read fresh --------------------------------
    def _settings(self):
        from ..world.settings import CONFIG, Settings
        return Settings(self.settings_path or CONFIG)

    def rules(self) -> tuple[bool, float, float]:
        """(chat may pick, cooldown seconds, floor as 0..1), clamped."""
        s = self._settings()
        on = bool(s.bool(KEY_ON))
        cooldown = max(0.0, float(s.int(KEY_COOLDOWN))) * 60.0
        floor = min(100.0, max(0.0, float(s.int(KEY_FLOOR)))) / 100.0
        return on, cooldown, floor

    def _say(self, text: str, detail: str = "") -> None:
        try:
            self.emit(Thought(topic="chat", text=text, detail=detail))
        except Exception:
            pass

    # ---- which fields a vote may name ------------------------------------
    def eligible(self, decision, walk_home=None, floor: float = 0.0):
        """(options, left_off) from the planner's ranking on `decision`.

        `options` is best first: {field, label, share}. `left_off` says, in
        words, why each near-best field is not on it -- chat sees that too.
        """
        ranked = [s for s in (getattr(decision, "alternatives", None) or ())
                  if getattr(s, "field", None)]
        best = max((float(s.score) for s in ranked), default=0.0)
        options, left_off = [], []
        if best <= 0:
            return options, left_off
        for item in ranked:
            score = float(item.score)
            share = score / best
            if score <= 0 or not getattr(item, "reachable", True):
                continue
            if share < floor:
                continue
            name = str(item.field)
            if name in BOSS_FIELDS:
                left_off.append(f"{_pretty(name)} ({BOSS_FIELDS[name]} lives there)")
                continue
            if walk_home is not None and ROUTER_ALIASES.get(name, name) not in walk_home:
                left_off.append(f"{_pretty(name)} (no walk home — it would end in a rejoin)")
                continue
            if len(options) < BALLOT_MAX:
                options.append({"field": name, "label": _pretty(name),
                                "share": round(share, 3)})
        return options, left_off

    def _why_not(self, decision, name: str, walk_home, floor: float) -> str:
        """Why `name` is not on this trip's ballot, in words for chat."""
        if name in BOSS_FIELDS:
            return f"{BOSS_FIELDS[name]} lives there"
        ranked = [s for s in (getattr(decision, "alternatives", None) or ())
                  if getattr(s, "field", None)]
        item = next((s for s in ranked if s.field == name), None)
        if item is None:
            return "it is not a field the planner ranks"
        best = max((float(s.score) for s in ranked), default=0.0)
        if float(item.score) <= 0 or not getattr(item, "reachable", True):
            return "the planner rules it out this trip"
        if walk_home is not None and ROUTER_ALIASES.get(name, name) not in walk_home:
            return "there is no walk home from it — it would end in a rejoin"
        share = float(item.score) / best if best > 0 else 0.0
        if share < floor:
            return (f"it scores {share:.0%} of the planner's best now, under "
                    f"the {floor:.0%} floor")
        return f"only the best {BALLOT_MAX} fields are on the ballot"

    # ---- publishing the next ballot --------------------------------------
    def ballot(self, decision, walk_home=None) -> ChatBallot | None:
        """Publish what chat may vote between for the next trip.

        Sent whether or not there is a vote, so the stream can say WHY there
        is none -- a cooldown and a switched-off setting look identical from
        the outside otherwise.
        """
        try:
            on, cooldown, floor = self.rules()
            pick = str(getattr(decision, "field", "") or "")
            trip = str(getattr(decision, "why", "") or "")[:200]
            if not on:
                event = ChatBallot(reason="chat may not pick fields "
                                          "(Settings › Stream)", pick=pick,
                                   trip=trip)
            else:
                wait = self._cooldown_left(cooldown)
                options, left_off = self.eligible(decision, walk_home, floor)
                if wait > 0:
                    event = ChatBallot(reason=f"chat picked a trip — the next "
                                              f"vote opens in {wait / 60:.0f}m",
                                       pick=pick, trip=trip)
                elif len(options) < BALLOT_MIN:
                    event = ChatBallot(
                        reason=("only one field is within "
                                f"{floor:.0%} of the best" if options
                                else "no field is on the ballot")
                        + (" — left off: " + "; ".join(left_off) if left_off
                           else ""),
                        pick=pick, trip=trip)
                else:
                    event = ChatBallot(options=options, pick=pick, trip=trip,
                                       reason=("left off: " + "; ".join(left_off))
                                       if left_off else "")
            self.emit(event)
            return event
        except Exception:
            return None

    def _cooldown_left(self, cooldown: float) -> float:
        with self._lock:
            last = self._last_applied
        if last is None:
            return 0.0
        return max(0.0, cooldown - (self.clock() - last))

    # ---- chat's vote arriving --------------------------------------------
    def offer(self, event) -> None:
        """Called on the socket's reader thread for EVERY inbound event."""
        if not isinstance(event, ChatVote):
            return
        try:
            if event.what != "field" or not str(event.choice or "").strip():
                return
            vote = ChatVote(what="field",
                            choice=str(event.choice).strip().lower()
                            .replace(" ", "_")[:40],
                            votes=int(event.votes or 0),
                            voters=int(event.voters or 0),
                            poll=str(event.poll or "")[:40],
                            platform=str(event.platform or "")[:20])
            # WHEN CHAT VOTED, not when it got here: the GUI stamps the event
            # as the poll closes, and sends it again after a rejoin, so the
            # arrival time would make an old vote look new. The same machine
            # stamps both ends; a stamp from the future is taken as now.
            now = self.clock()
            try:
                cast = float(event.at)
            except (TypeError, ValueError):
                cast = now
            vote.at = cast if 0 < cast <= now else now
            with self._lock:
                pending = self._pending
                if vote.poll and (vote.poll in self._settled
                                  or (pending is not None
                                      and pending.poll == vote.poll)):
                    return                   # sent again after a rejoin
                if pending is not None and pending.poll:
                    # a newer poll's result replaces one still waiting
                    self._settled = (self._settled + [pending.poll])[-SETTLED_KEEP:]
                self._pending = vote
                self._save()
            self._say(f"got chat's vote for {_pretty(vote.choice)} "
                      f"({vote.votes} of {vote.voters}) — it goes to the next "
                      f"field choice, if it is still on the ballot then")
        except Exception:
            pass

    # ---- using it -----------------------------------------------------------
    def field_for(self, decision, forced=None, walk_home=None, hold: str = ""):
        """(field, why) when chat's vote decides this trip, else None.

        Called from the farm's `plan` with the decision the planner has just
        made. A vote waits through a convert decision, and through a trip
        `hold` names (the pinned field's walk-home probe, which only a trip
        there can make); everything else that stops it drops it, and says so.
        """
        try:
            with self._lock:
                vote = self._pending
            if vote is None:
                return None
            if getattr(decision, "action", "") != "gather":
                return None                  # waits for the next gather choice
            now = self.clock()
            label = _pretty(vote.choice)

            def refuse(why: str):
                with self._lock:
                    self._settle(vote)
                self._say(f"chat voted {label} — not used: {why}")
                return None

            if now - float(vote.at or 0.0) > VOTE_TTL_SECONDS:
                return refuse(f"the vote is {(now - vote.at) / 60:.0f} minutes "
                              "old, older than two trips")
            on, cooldown, floor = self.rules()
            if not on:
                return refuse("Settings › Stream › chat may pick the next "
                              "field is off")
            if hold:
                self._say(f"chat voted {label} — it waits a trip: {hold}")
                return None
            wait = self._cooldown_left(cooldown)
            if wait > 0:
                return refuse(f"chat picked a trip less than "
                              f"{cooldown / 60:.0f} minutes ago")
            options, _left_off = self.eligible(decision, walk_home, floor)
            chosen = next((o for o in options if o["field"] == vote.choice), None)
            if chosen is None:
                return refuse(self._why_not(decision, vote.choice, walk_home, floor))
            pick = str(getattr(decision, "field", "") or "")
            with self._lock:
                self._last_applied = now
                self._settle(vote)
            why = (f"chat voted {label} ({vote.votes} of {vote.voters} votes)"
                   + (f", over the pinned {_pretty(forced)}"
                      if forced and forced != vote.choice else "")
                   + (f"; the planner's own pick was {_pretty(pick)} and "
                      f"{label} scores {chosen['share']:.0%} of its best"
                      if pick and pick != vote.choice else
                      "; the planner agreed"))
            self._say(f"chat voted {label} — trying it next", detail=why)
            return vote.choice, why
        except Exception:
            return None
