"""The vocabulary the bot uses to tell the GUI what it is doing.

Every event is a plain dataclass that serialises to one line of JSON. That choice
is deliberate and has three payoffs:

  * the GUI can be developed and tested with no bot running -- replay a recorded
    file of these lines and the interface behaves exactly as it would live
  * a session is a flight recorder. When something goes wrong at hour six, the
    reasoning that led there is on disk, not lost with the process
  * `telemetry` has no dependency on Qt, Wayland or the game, so the GUI and the
    bot can be different processes, which they must be: the bot lives inside the
    nested compositor it drives, and the GUI must not

The owner asked to "see the Ai think", and to be able to switch between the bot
asking which path to take and it deciding alone. Those are not two features --
they are the same event stream read at two levels of interruption. A `Considered`
event carries the options and their scores whether or not anyone is asked; the
autonomy mode only decides whether a `Question` follows it.
"""
from __future__ import annotations

import json
import time
import dataclasses
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Level(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class Autonomy(str, Enum):
    """How much the bot is allowed to decide by itself."""
    AUTOPILOT = "autopilot"          # decides everything, never interrupts
    ASK_STRATEGY = "ask_strategy"    # asks on build/spend decisions only
    ASK_NOTABLE = "ask_notable"      # asks on anything irreversible or costly


@dataclass
class Event:
    """Base for everything on the wire."""
    kind: str = field(init=False, default="event")
    at: float = field(default_factory=time.time)

    def to_json(self) -> str:
        data = asdict(self)
        data["kind"] = self.kind
        return json.dumps(data, separators=(",", ":"), default=str)


@dataclass
class Log(Event):
    kind = "log"
    message: str = ""
    level: Level = Level.INFO
    source: str = ""


@dataclass
class Thought(Event):
    """One step of reasoning, shown live in the GUI's think pane.

    `detail` is for the long form the user can expand; `text` should stand alone
    in a single line, because that is all a scrolling pane can show.
    """
    kind = "thought"
    text: str = ""
    detail: str = ""
    topic: str = ""            # groups related thoughts, e.g. "planter"


@dataclass
class Option:
    """One candidate the bot weighed, with the number that decided it."""
    label: str
    score: float
    why: str = ""
    unit: str = ""             # what `score` is measured in, e.g. "honey/hr"


@dataclass
class Considered(Event):
    """A decision point, with everything that was weighed and what won.

    This is emitted whether or not the user is asked. In autopilot it is the
    explanation; in ask mode it is the question's body. Keeping one event for
    both is what stops the two modes drifting apart.
    """
    kind = "considered"
    question: str = ""
    options: list[Option] = field(default_factory=list)
    chosen: str = ""
    rationale: str = ""
    reversible: bool = True
    horizon_hours: float = 0.0     # how far ahead this choice commits us


@dataclass
class Question(Event):
    """A decision handed to the user, because autonomy mode requires it."""
    kind = "question"
    id: str = ""
    question: str = ""
    options: list[Option] = field(default_factory=list)
    default: str = ""
    expires_at: float = 0.0        # 0 means it waits indefinitely
    context: str = ""


@dataclass
class Answer(Event):
    """The user's reply, travelling GUI -> bot."""
    kind = "answer"
    id: str = ""
    choice: str = ""


class Action(str, Enum):
    """What the run-control buttons ask the bot to do."""
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    # HANDOVER. The owner asked for these by name: "it should be so i can
    # have a button in hivemind to takover and from that point it watches me
    # play and learns intill i press pass back button".
    #
    # TAKE_OVER is not PAUSE. Pause stops the bot and leaves the game sitting
    # there; take-over hands the controls to a person and starts LEARNING from
    # what they do. The difference matters in the log too: a paused run did
    # nothing, a handed-over run produced a map.
    TAKE_OVER = "take_over"
    PASS_BACK = "pass_back"


@dataclass
class Command(Event):
    """A run-control instruction, travelling GUI -> bot.

    Deliberately NOT a StatusUpdate. StatusUpdate is the bot REPORTING what it
    is doing; this is the user ASKING for something. Conflating a request with
    a report makes "who decided this?" unanswerable in the event log, which is
    the one question an audit of an autonomous agent needs to answer.
    """
    kind = "command"
    action: Action = Action.START
    reason: str = "requested from the GUI"


@dataclass
class GameInput(Event):
    """The owner's own mouse or key, from the live view, for the game (RL1b
    step 3: "Take control" when the game has no window a person can click).

    GUI -> bot, like Command. The bot applies it through ITS input layer
    (brain/controls.Controls.handle -> the session's VirtualInput), and only
    while the owner has the controls: there is no second way into the game.

    `op`: move (x, y), down / up (button), key_down / key_up (key), scroll
    (steps, positive is down) or release_all. `x`, `y` are pixels of the game
    (1920x1080), already scaled from the live view. `key` is a name in
    platform/wl/vkeyboard.KEYS; a name the bot does not know is dropped there.
    """
    kind = "game_input"
    op: str = "move"
    x: float = 0.0
    y: float = 0.0
    button: str = "left"
    key: str = ""
    steps: int = 0


@dataclass
class Belief(Event):
    """A fact the bot holds, with how much it trusts it.

    Staleness is shown in the GUI so the user can see the difference between
    "you have 3 Gifted Bees" and "you had 3 Gifted Bees forty minutes ago".
    """
    kind = "belief"
    name: str = ""
    value: Any = None
    confidence: float = 1.0
    observed_at: float = 0.0
    source: str = ""


@dataclass
class TaskUpdate(Event):
    kind = "task"
    name: str = ""
    status: str = ""               # running | done | failed | preempted
    progress: float = 0.0          # 0..1, negative means indeterminate
    detail: str = ""


@dataclass
class Metric(Event):
    """A number worth charting: honey/hour, tokens/minute, capture fps."""
    kind = "metric"
    name: str = ""
    value: float = 0.0
    unit: str = ""


@dataclass
class Frame(Event):
    """A live view frame, referenced by file rather than embedded.

    JPEG bytes inline would make every event line megabytes and would couple the
    GUI's frame rate to the socket. The bot writes the latest frame to a fixed
    path and sends only the path plus what it detected in it.
    """
    kind = "frame"
    path: str = ""
    width: int = 0
    height: int = 0
    detections: list[dict] = field(default_factory=list)
    screen: str = ""               # the vision.screenstate.Screen value


@dataclass
class StatusUpdate(Event):
    """Coarse bot state, for the header bar."""
    kind = "status"
    running: bool = False
    paused: bool = False
    # NONE UNLESS SOMETHING DECIDES IT (DESIGN 8du). It defaulted to AUTOPILOT,
    # so every status the bot sent -- none of which ever set it -- snapped the
    # GUI's autonomy selector back to Autopilot within 20 s of the owner
    # changing it. Nothing in the farm loop reads a mode (brain/autonomy's
    # Arbiter is not wired in), so the honest value is "not reported".
    autonomy: Autonomy | None = None
    uptime_s: float = 0.0
    note: str = ""
    # WHO IS DRIVING. The owner asked for a button that takes the controls off
    # the bot and gives them back: "it should be so i can have a button in
    # hivemind to takover and from that point it watches me play and learns
    # intill i press pass back button". The GUI asks; this is the bot SAYING
    # it has actually let go, which is the only version worth believing.
    #
    # LET GO MEANS PARKED, not "the command arrived" (DESIGN 8du). The keys
    # come up the instant TAKE_OVER lands, but the step in progress runs on
    # until the loop next asks `Controls.check()`, so `handed_over` is True
    # only once the loop is blocked there. In between, `handing_over` is True
    # and the GUI says the bot is finishing its step instead of claiming the
    # owner has the keyboard.
    handed_over: bool = False
    handing_over: bool = False
    # Is the loop actually blocked at a step boundary? `paused` is what was
    # ASKED for (the Pause/Resume button follows it, so a pending pause can
    # still be cancelled); this is what has HAPPENED, and the header's
    # "paused" follows it. None from a bot that predates it: the GUI then
    # reads `paused` as it always did.
    parked: bool | None = None


@dataclass
class Planter(Event):
    """A planted seed and the decision the planner has reached about it.

    `field_health` is carried because field degradation -- yield falling with
    repeated harvesting of the same field -- would change when harvesting is
    correct. That mechanic is UNVERIFIED (docs/DESIGN.md 8a), so the engine
    currently ignores it and waits for 100%, which is right either way. The
    number is still reported so the experiment has data to work with.
    """
    kind = "planter"
    id: str = ""
    seed: str = ""                 # Paper, Ticket, Festive, Petal, Planter Of Plenty...
    field: str = ""
    growth: float = 0.0            # 0..1
    ready_at: float = 0.0
    field_health: float = 1.0      # 0..1, lower means degraded
    nectar: str = ""               # which nectar it is filling
    yield_estimate: float = 0.0    # honey
    # The harvest call and its reasoning come from tasks.planters.decide(), not
    # from the GUI. A panel that recomputes a verdict is a second implementation
    # that can disagree with the one actually driving the bot.
    harvest_now: bool = False
    verdict: str = ""


@dataclass
class Expiry(Event):
    """Something that will be LOST if nothing happens before `at_risk_at`.

    One subsystem owns every decaying resource, because these are all the same
    failure: a silent loss with no in-game warning. The 48-hour beequip inbox
    destroys items outright; nectar above the 12-hour mark cannot be condensed
    into a vial and is simply wasted.
    """
    kind = "expiry"
    id: str = ""
    what: str = ""
    detail: str = ""
    at_risk_at: float = 0.0
    severity: str = "warn"         # info | warn | critical
    value: float = 0.0             # what losing it costs, in honey


@dataclass
class ShadowPrice(Event):
    """What one unit of a resource is worth to you RIGHT NOW, in honey.

    This single table is the objective function, the explanation, the planter
    scorer and the spend oracle at once. It is also the thing a human player
    simply does not have -- nobody knows what a Glitter is worth this afternoon.
    """
    kind = "shadow_price"
    resource: str = ""
    honey_value: float = 0.0
    trend: float = 0.0             # change over the last hour, as a fraction
    basis: str = ""                # why it is priced there
    # False when the bot has observed no path from this resource to honey. The
    # panel then shows "unknown" rather than a number. A valuation that always
    # produces a figure looks authoritative while inventing money.
    known: bool = True
    confidence: float = 1.0        # decays with the age of the observation


@dataclass
class FieldStatus(Event):
    kind = "field"
    name: str = ""
    # HEALTH IS UNKNOWN UNTIL SOMETHING MEASURES IT, and -1 says so. It
    # defaulted to 1.0, nothing ever set it, and the Fields tab drew every
    # field as a full green bar -- four cards of invented good news. Field
    # degradation is still unverified (docs/GAPS.md); when `economy/
    # degradation` can answer, this is where the answer goes.
    health: float = -1.0
    # Tokens on the ground in a field: also unmeasured. Nothing counts tokens
    # per field, so this stays at -1 rather than reporting a confident zero.
    tokens: int = -1
    mobs: int = 0
    last_visited: float = 0.0
    recommended: bool = False
    note: str = ""
    # WHAT THE BOT HAS ACTUALLY EARNED HERE. These are the numbers it really
    # has, from `brain.fieldnotes`, and none of them were being sent -- so the
    # tab showed a fake health bar and a fake "0 tokens" while the measured
    # record sat in memory. `rate` is pollen per second and 0.0 means never
    # measured, which is not the same as slow.
    rate: float = 0.0
    pollen: int = 0
    visits: int = 0
    seconds: float = 0.0
    deaths: int = 0


@dataclass
class Timer(Event):
    """A recurring in-game deadline: boss respawn, shrine, clock, event.

    Times are UTC. Every hardcoded boss clock in every existing macro drifts by
    an hour twice a year because it was written in local time.
    """
    kind = "timer"
    id: str = ""
    name: str = ""
    ready_at: float = 0.0
    category: str = ""             # boss | machine | event | shrine
    persistent_hp: bool = False    # Stump Snail saves damage; Coconut Crab resets
    note: str = ""


@dataclass
class QuestStep(Event):
    kind = "quest"
    giver: str = ""                # Science Bear, Spirit Bear, Polar Bear...
    step: str = ""
    done: float = 0.0
    total: float = 0.0
    reward: str = ""
    eta_s: float = 0.0
    # THE MENU SAYS "Complete!" ON STEPS THAT HAVE NO COUNT AT ALL, and
    # completeness was inferred from done/total alone -- so a finished step
    # with no numbers was drawn as an empty bar. Carried explicitly because
    # the screen states it explicitly.
    complete: bool = False


@dataclass
class ChatBallot(Event):
    """The fields stream chat may vote between for the NEXT trip, bot -> GUI.

    Built by `stream/gate.ChatGate.ballot` from the planner's own ranking, so
    the only fields a vote can ever name are ones the bot would have gone to
    itself (DESIGN 8dv). Empty `options` with a `reason` means no vote now,
    and why -- a cooldown, the setting off, too few fields.
    """
    kind = "chat_ballot"
    options: list[dict] = field(default_factory=list)   # {field, label, share}
    pick: str = ""                 # the planner's own choice this trip
    reason: str = ""               # why a field is left off, or why no vote
    trip: str = ""                 # the decision this ballot came from


@dataclass
class ChatVote(Event):
    """What stream chat voted for, travelling GUI -> bot.

    A REQUEST, like `Command`, never an order: `stream/gate.ChatGate` checks it
    against the owner's settings, its cooldown and the planner's ranking at
    the moment it would be used, and says on stream what it decided.
    """
    kind = "chat_vote"
    what: str = "field"            # the only kind the gate acts on
    choice: str = ""               # a field slug from the last ChatBallot
    votes: int = 0
    voters: int = 0
    poll: str = ""
    platform: str = ""             # twitch | file


@dataclass
class ChatJump(Event):
    """Stream chat typed "jump", travelling GUI -> bot (DESIGN 8ef).

    A REQUEST, like `ChatVote`: stream/jump.ChatJumps holds it until the
    gather pattern ends a leg, and the character jumps only there, only if
    the owner allows it and has no Pause or Take Over on, and at most once
    every stream/jump.JUMP_EVERY seconds. `asks` is how many "jump"s the GUI
    folded into this one, from `askers` different chatters.
    """
    kind = "chat_jump"
    asks: int = 1
    askers: int = 1
    platform: str = ""             # twitch | youtube | file


@dataclass
class GameMenu(Event):
    """The bot is about to open Roblox's own menu (`up`), or has shut it.

    Sent by act/routes._reset before its Escape and after its last key, so
    the stream window can cover the menu's panel before a frame shows it:
    the menu opens on People, which lists every player by display name and
    @username, the owner's included (DESIGN 8ec). Nothing else reads it.
    """
    kind = "game_menu"
    up: bool = True
    why: str = ""                  # "respawn"


_TYPES: dict[str, type] = {}


def _register() -> None:
    """Register every Event subclass defined here, automatically.

    This was a hand-written tuple and it drifted within a day: six new event
    types were added and none of them were registered, so `from_json` returned
    None for all of them and the GUI silently ignored a third of the protocol.
    Walking the module means adding a class is the only step there is.
    """
    for value in list(globals().values()):
        if (isinstance(value, type) and issubclass(value, Event)
                and value is not Event):
            kind = getattr(value, "kind", "")
            if isinstance(kind, str) and kind:
                _TYPES[kind] = value


_register()


def from_json(line: str) -> Event | None:
    """Rebuild an event, or None if the line is unparseable or unknown.

    Returning None rather than raising is deliberate: a malformed line on a
    telemetry socket must never take down the GUI that is displaying it.
    """
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    # Valid JSON is not necessarily an event: "[]" and "3" both parse fine and
    # then blow up on .pop(). A telemetry socket carries whatever anyone writes
    # to it, so the type check is not paranoia.
    if not isinstance(data, dict):
        return None
    cls = _TYPES.get(data.pop("kind", ""))
    if cls is None:
        return None
    if cls in (Considered, Question) and "options" in data:
        data["options"] = [Option(**o) if isinstance(o, dict) else o
                           for o in data["options"]]
    # A FIELD THE READER HAS NEVER HEARD OF IS NOT A REASON TO BIN THE EVENT.
    #
    # `cls(**data)` raised TypeError on any unknown key and this returned None,
    # so the moment the bot gained a field the GUI did not have, every event of
    # that type vanished on the way in -- silently, because None is also what a
    # malformed line returns. It happened for real on 2026-09-21: `QuestStep`
    # gained `complete` and the GUI that was already running dropped every
    # quest the bot read, which looks exactly like the quest reader being
    # broken. The bot and the GUI are separate processes and only one of them
    # gets restarted when the code changes, so this will keep happening.
    #
    # Unknown keys are dropped and named in `_dropped` for anyone counting;
    # a MISSING field still falls back to the dataclass default, so an older
    # bot talking to a newer GUI works too.
    known = {f.name for f in dataclasses.fields(cls)}
    extra = [k for k in data if k not in known]
    for key in extra:
        data.pop(key)
    try:
        event = cls(**data)
    except TypeError:
        return None
    if extra:
        _dropped.update(extra)
    return event


# Field names seen on the wire that this build has no home for. Read by the
# doctor, so a version mismatch between the bot and the GUI is visible rather
# than silent.
_dropped: set[str] = set()


def unknown_fields() -> list[str]:
    """Event fields this build received and could not store. See `from_json`."""
    return sorted(_dropped)
