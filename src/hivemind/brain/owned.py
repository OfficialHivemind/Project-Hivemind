"""What the account already owns, rechecked from its own evidence (DESIGN 8ea).

HIS REQUEST: "make it so it checks what i already have cus i got porcelain
dipper and some stuff so it would be saving for nothing so make sure it
rechecks what i have and so it knows what goals". Until now the only way the
bot knew he owned anything was a line he typed into Settings > Goals > "Gear
you already own" (`goals.owned`). This module adds the two things the bot can
see for itself, and keeps them apart from what he said:

  * CONFIRMED -- his word: a name in `goals.owned`, or his "yes" on a
    Decision Inbox card, which the window writes into `goals.owned` too --
    the one store of his yes, so a name he takes back out is not owned
    (`owned`). Nothing the bot measures ever overrides it.
  * INFERRED -- the bot's own evidence, shown as such everywhere (the Goals
    tab, the stream's goal card, the log), with a card asking him to confirm
    or correct it. A "No" on that card is REJECTED and the goal comes back.

THE EVIDENCE IS THE HONEY BALANCE. Honey only goes down when something is
bought. MEASURED over the whole saved record, read by this module's own
`history` (598 dated readings from var/trips.jsonl and var/night/run-*.log,
20 Sep 23:08 to 26 Sep 15:14; scratch account-fix3/record3.py): across 258 of
the bot's own restarts (a gap under 10 minutes) the balance fell once, by
401; within attempts it never fell by more than MATCH_TOLERANCE; and all
seven falls bigger than that lie in stretches where the bot was stopped for
31 minutes or more and he was playing, 55,857,445 -> 21,283,009 on 24 Sep
(841 min) among them. So a fall between two trusted readings is a purchase,
and a fall that equals one price in `gear_prices.yaml` (or goals.yaml, or
the tools in progression.yaml) says what was bought.

WHAT A TRUSTED READING IS. The HUD's honey digits misread grossly or not at
all. MEASURED over 1,812 consecutive readings of the saved route frames of
attempts 400-445 (scratch `account/hudnoise.py`, the real `HudReader`): two
fell, and both were misreads -- "38,3692952", a comma read as a 2, ten times
too big, and a truncated "10" -- while the other 1,810 pairs were equal (1,204)
or rose. Three rules follow. A reading whose digits are not grouped as the
HUD groups them is no reading (GROUPED, which every misread measured fails).
A level is believed only when two readings in a row agree (the second no
lower, and no more than `MATCH_TOLERANCE` higher), the same "twice" rule
`goals.ASK_AFTER_READINGS` uses, and a gap between them breaks the row. And
a level more than CORROBORATE_RATIO from the last one must last a minute
(FAR_LEVEL_*): the "38,3692952" came twice in a row.

WHAT IT NEVER DOES. It never guesses between two explanations. A fall that
matches exactly one price marks that item INFERRED and asks; a fall that
matches none, or several, only asks -- "what did you buy?" -- with his next
goals as the answers. And it never presses anything: everything here is
arithmetic on readings the bot already takes.
"""
from __future__ import annotations

import contextlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

# ---- the states and the cards -------------------------------------------
CONFIRMED = "confirmed"        # his word: goals.owned, or his answer on a card
INFERRED = "inferred"          # the bot's evidence; a card asks him
# THE MATERIALS A PURCHASE USED (observe_materials): a gear goal is inferred
# bought when at least MATERIAL_MIN of its materials each fell by at least
# MATERIAL_SHARE of its recipe between two inventory reads, and none rose.
# MEASURED 2026-10-20: he bought the Cobalt Guard while playing; the balance
# fell 67,544,159 net (his play earned the rest), which no price explains,
# but Blue Extract went 107 -> 8 between the 17:49 and 19:53 reads.
MATERIAL_SHARE = 0.9
MATERIAL_MIN = 2
MATERIALS_FILE = "owned_materials.json"
REJECTED = "rejected"          # he answered "No" to the inference
BOUGHT = "bought"              # the bot bought it itself (var/purchases.json)
SEEN = "seen"                  # a shop window showed it owned (brain/sight, G13)

OWNED_PREFIX = "owned:"        # card asking him to confirm an inferred item
DROP_PREFIX = "drop:"          # card asking what a fall of the balance bought
CARD_PREFIXES = (OWNED_PREFIX, DROP_PREFIX)
YES = "Yes, I bought it"
NO = "No, it was something else"
NONE_OF_THESE = "None of these"
# THE OWNER'S USUAL SPEND (2026-10-14: "i ussualy spend on jellys"): a fall
# that was Royal Jelly rolls, answered in one click. Like NONE_OF_THESE it
# marks no gear owned; it closes the card with the reason on record.
SPENT_ON_JELLY = "I rolled Royal Jelly"
BOUGHT_THE = "I bought the "   # + the item's label, on a fall card

# THE LARGEST RISE OF THE BALANCE BETWEEN TWO READINGS WITH NO CONVERT BETWEEN
# THEM. MEASURED 2026-09-26: 16,229 over the saved route frames of attempts
# 400-445 (a honey token picked up on a walk, 6 s apart; the largest rise in
# any gap of 40 s or less that did not span a convert), and 16,526 between a
# convert's settled balance and the HUD reading the goals line took moments
# later (09-26 07:58, attempt 435). It is used twice, and both are that same
# quantity: two readings are ONE LEVEL when the second is no lower and no
# more than this higher, and a price EXPLAINS a fall when it is no lower than
# the fall and no more than this above it -- the honey that came in between
# the two readings is the only thing that can make a fall smaller than the
# price. A fall no bigger than this is not a purchase at all.
MATCH_TOLERANCE = 16_526

# A READING WITH ITS NEIGHBOUR WITHIN A FACTOR OF TWO IS NOT A GROSS MISREAD.
# Used for the backfill, where most readings are single ones (a session's
# "starting honey"), and live for a new level (FAR_LEVEL_*). The misreads
# measured were ten times too big or several digits short; a trip's honey is
# a few percent of the balance.
CORROBORATE_RATIO = 2.0

# A HUD READING IS PASSED ON ONLY WHEN ITS DIGITS ARE GROUPED AS THE HUD
# GROUPS THEM. MEASURED 2026-09-26 over the OK honey readings of the saved
# route frames of attempts 350-445, in time order (the real HudReader;
# scratch account/hud_400_445.jsonl, review-account/hud_350_399.jsonl,
# account-fix/grouping.py): all 8 gross misreads break the grouping --
# "38,3692952" twice in a row (attempt 418), "10", "25,11", "47,17",
# "47,1792858", "59,2792655", "83,1092861" -- and none of the 5,099 grouped
# ones fell within an attempt (the two falls the file order shows cross
# midnight). goals.hud_honey applies it. A balance under 1,000 would be
# refused too; the lowest trusted one on record is 3,113,848 (21 Sep).
GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+")

# A NEW LEVEL MORE THAN CORROBORATE_RATIO FROM THE LAST TRUSTED ONE MUST
# LAST: FAR_LEVEL_READINGS agreeing readings over FAR_LEVEL_SECONDS before it
# is believed. The longest misread episode measured is attempt 418's: the
# "38,3692952" pair 6 s apart, inside 11 s of unreadable "38,369?952"s
# (033543-033554) -- a well-grouped misread twice in a row would pass the
# "two in a row" rule on its own. A heartbeat reads every 20 s, so this is
# a minute of the same far level: over five times that episode. A real fall
# that big (55.8M -> 21.3M on 24 Sep) is believed a minute late, no more.
FAR_LEVEL_READINGS = 3
FAR_LEVEL_SECONDS = 60.0

# HOW LONG A NEW CAPACITY MUST LAST BEFORE IT IS A NEW BAG. MEASURED on the
# session-start readings (var/night/run-*.log "starting pollen"): 1,324,350 at
# 21:43 and 22:04 on 24 Sep, and 1,215,000 again at 23:23 with the bot
# running, which no purchase can do -- a temporary x1.09 that lasted between
# 21 and 99 minutes. Two hours outlasts the only temporary level on record.
CAPACITY_PERSIST_SECONDS = 2 * 3600.0

# THE ACCOUNT RESEARCH'S CAPACITY MODEL (salvage account_research.json,
# "capacity decomposition", marked a hypothesis there): capacity = static x
# 1.5 (the Quest Hotshot badge on his 20 Sep screenshot) x (1 + p), p 0.10
# then 0.20. With those, every session-start capacity from 20 to 24 Sep came
# out a whole multiple of 25,000 of static. A bag is inferred from a jump only
# when exactly one of these multipliers makes BOTH sides whole multiples of
# `STATIC_STEP` and the difference is one bag's and no other single item's.
CAPACITY_MULTIPLIERS = (1.5 * 1.1, 1.5 * 1.2)
# Every `add` of 5,000 or more in gear_prices.yaml and goals.yaml is a whole
# multiple of 5,000, and so are the badges' flat +25,000s (account.yaml).
STATIC_STEP = 5_000

# How many of his goals a card about a fall NO price explains offers as
# answers: the same three the stream's goal card shows
# (gui/stream._GoalsCard.ROWS), in his order. A TIE is not cut to this: every
# tied item is an answer (`Purchases._judge`), or the fourth guard at 300,000
# could only be answered "None of these".
ASK_OPTIONS = 3

SETTLED = re.compile(r"honey settled at ([\d,]+)")
_START = re.compile(r"starting honey:\s+([\d,]+)")
_CAPACITY = re.compile(r"starting pollen:\s+[\d,]+/([\d,]+)")
_GOALS = re.compile(r"goals: .*honey ([\d,]+) \(the HUD, (\d+ \w+ \d\d:\d\d)\)")
_STAMP = re.compile(r"^\s+(\d\d):(\d\d):(\d\d)\s")
_ATTEMPT = re.compile(r"attempt (\d+) starting "
                      r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) -> (\S+)")


def _slug(text: str) -> str:
    return "_".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def _when(at: float | None) -> str:
    return time.strftime("%d %b %H:%M", time.localtime(at)) if at else "?"


# ---- the price table -----------------------------------------------------
@dataclass(frozen=True)
class Item:
    key: str
    label: str
    honey: int
    slot: str = ""
    shop: str = ""
    add: int = 0                 # capacity added to the static sum
    times: float = 1.0           # capacity multiplier
    goal: bool = False
    aliases: tuple = ()
    # False for a price that is never inferred owned (gear_prices.yaml's
    # hive slots and Star Amulets): it only makes a fall at its price a tie.
    infer: bool = True
    # ((material, count), ...): gear_prices.yaml `materials`, or a tool's
    # `also_costs` ("5 Soft Waxes") as written -- the Gear plan's goals
    materials: tuple = ()


def _yaml(path: Path) -> dict:
    import yaml
    try:
        body = yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return body if isinstance(body, dict) else {}


_TABLE: dict = {}


def _costs(body: dict) -> tuple:
    mats = dict(body.get("materials") or {})
    for text in body.get("also_costs") or ():
        found = re.match(r"\s*([\d,]+)\s+(.+)", str(text))
        if found:
            mats[_slug(found.group(2))] = int(found.group(1).replace(",", ""))
    return tuple(mats.items())


def prices(goals_data: dict | None = None) -> dict:
    """{key: Item}: the gear goals, the tools and every other piece of gear.

    Three files, none copied into another: goals.yaml for the six goals,
    progression.yaml `tools.known` for the tools, gear_prices.yaml for the
    rest. A key in more than one keeps the first (goals.yaml), so a goal's
    price is only ever the one the planner uses.
    """
    from ..datapaths import data
    paths = (data("knowledge", "goals.yaml"), data("knowledge", "progression.yaml"),
             data("knowledge", "gear_prices.yaml"))
    try:
        stamp = tuple(p.stat().st_mtime_ns for p in paths)
    except OSError:
        stamp = None
    if goals_data is None and stamp is not None and _TABLE.get("stamp") == stamp:
        return _TABLE["items"]
    if goals_data is None:
        from . import goals as goals_plan
        goals_data = goals_plan.load()
    out: dict = {}

    def put(key, body, goal=False, label=None):
        body = body or {}
        honey = body.get("honey")
        if key in out or not isinstance(honey, (int, float)) or honey <= 0:
            return
        cap = body.get("capacity") or {}
        out[key] = Item(key=key, label=str(body.get("label") or label
                                           or key.replace("_", " ").title()),
                        honey=int(honey), slot=str(body.get("slot") or ""),
                        shop=str(body.get("shop") or ""),
                        add=int(cap.get("add") or 0),
                        times=float(cap.get("times") or 1.0), goal=goal,
                        aliases=tuple(str(a) for a in body.get("aliases") or ()),
                        infer=body.get("infer") is not False, materials=_costs(body))

    for key, body in (goals_data.get("goals") or {}).items():
        put(str(key), body, goal=True)
    tools = (_yaml(paths[1]).get("tools") or {}).get("known") or {}
    for key, body in tools.items():
        put(str(key), dict(body or {}, slot="tool"))
    for key, body in (_yaml(paths[2]).get("gear") or {}).items():
        put(str(key), body)
    if stamp is not None:
        _TABLE.update(stamp=stamp, items=out)
    return out


def item_key(name: str, table: dict) -> str | None:
    """A table key from whatever he typed: a key, a label or an alias."""
    wanted = _slug(name)
    if not wanted:
        return None
    for key, item in table.items():
        if wanted in {_slug(s) for s in (key, item.label) + tuple(item.aliases)}:
            return key
    return None


def _names(text) -> list[str]:
    return [p.strip() for p in re.split(r"[,;\n]+", str(text or "")) if p.strip()]


def with_owned(text, key: str, table: dict | None = None) -> str:
    """`goals.owned` with `key` added under its label, unless it is there."""
    table = prices() if table is None else table
    names = _names(text)
    if any(item_key(n, table) == key for n in names):
        return ", ".join(names)
    item = table.get(key)
    return ", ".join(names + [item.label if item else key])


# ---- var/owned.json: the evidence and his answers --------------------------
def _path(var_root) -> Path:
    return Path(var_root) / "owned.json"


def load_state(var_root) -> dict:
    try:
        body = json.loads(_path(var_root).read_text())
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


@contextlib.contextmanager
def _locked(var_root):
    """Read-modify-write of var/owned.json under a lock: the bot writes the
    evidence and the window writes his answers, so neither may clobber the
    other's with a copy it read earlier."""
    from ..files import atomic_write, locked
    lock = Path(var_root) / ".owned.json.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as handle, locked(handle):
        state = load_state(var_root)
        yield state
        atomic_write(_path(var_root), json.dumps(state, indent=1))


@dataclass
class Owned:
    key: str
    label: str
    how: str                      # CONFIRMED or INFERRED
    why: str = ""
    at: float | None = None


def owned(typed, var_root, table: dict | None = None) -> dict:
    """{key: Owned} for everything owned: his word first, then the evidence.

    `typed` is `goals.owned`. A name there that is not in the table is not an
    item this can price, and is left for the planner to report.

    GOALS.OWNED IS THE ONE STORE OF HIS YES. A card's "yes" is written both
    there (by the window) and into var/owned.json as CONFIRMED; the second is
    the record of the answer, not a second vote. So an item he takes back out
    of Settings is not owned, whatever the file says -- the Settings help
    promises that goals.owned "is your word and always wins" -- and, like a
    "No", the same evidence does not infer it again (`Purchases._infer`)."""
    table = prices() if table is None else table
    items = load_state(var_root).get("items") or {}
    items = items if isinstance(items, dict) else {}
    out: dict = {}
    for name in _names(typed):
        key = item_key(name, table)
        if key:
            body = items.get(key)
            carded = isinstance(body, dict) and body.get("state") == CONFIRMED
            out[key] = Owned(key, table[key].label, CONFIRMED,
                             "you said yes on a card, which put it in "
                             "Settings > Goals" if carded else
                             "you said so in Settings > Goals")
    # SEEN OWNED IN A SHOP'S WINDOW (brain/sight, ROADMAP G13, the owner
    # 2026-10-19: "instead of asking that it will check"): an "Equip(ped)" or
    # "Purchased" button under the item's own name. Before the inferences:
    # the window is the game's own word, the balance only arithmetic.
    from . import sight
    for key, rec in sight.seen_owned(var_root, table).items():
        if key not in out and key in table:
            out[key] = Owned(key, table[key].label, SEEN,
                             sight.checked_line(table[key].label, rec), rec.get("at"))
    for key, body in items.items():
        if key in out or key not in table or not isinstance(body, dict):
            continue
        if body.get("state") == INFERRED:
            out[key] = Owned(key, table[key].label, INFERRED,
                             str(body.get("why") or ""), body.get("at"))
    # WHAT THE BOT BOUGHT ITSELF, an ok row of var/purchases.json, is owned
    # from then on. MEASURED 2026-10-07: the Bubble Mask crafted at 02:46,
    # and the plan at 03:09 still "next is the Bubble Mask", buying it again
    # -- the fall it made was only kept from becoming a question.
    try:
        rows = json.loads((Path(var_root) / "purchases.json").read_text())
    except (OSError, ValueError):
        rows = []
    for row in rows if isinstance(rows, list) else []:
        key = item_key(str(row.get("item") or ""), table) \
            if isinstance(row, dict) and row.get("ok") else None
        if key and key not in out:
            out[key] = Owned(key, table[key].label, BOUGHT,
                             f"the bot bought it at the {str(row.get('shop')).replace('_', ' ')}, "
                             f"{_when(row.get('at'))}", row.get("at"))
    return out


# THE HONEY MADE WHILE IT BOUGHT. MEASURED 2026-10-03 06:01-06:03: the 35th
# slot cost 209,117,953 and the balance fell 209,093,953 between the two
# readings around it -- 24,000 less, honey still coming in -- past the
# MATCH_TOLERANCE a fall of the owner's is matched to. A fall that is the
# bot's own purchase can only come in under its price, by what was made in
# between: up to BOUGHT_EARNED_SHARE of the price.
BOUGHT_EARNED_SHARE = 0.02


def bot_purchase(var_root, fall) -> dict | None:
    """The bot's own honey purchase (var/purchases.json) that `fall` is: one
    made between the fall's two readings, the fall no more than its price
    (MATCH_TOLERANCE over) and no less than BOUGHT_EARNED_SHARE under -- or
    None."""
    try:
        rows = json.loads((Path(var_root) / "purchases.json").read_text())
    except (OSError, ValueError):
        return None
    for row in rows if isinstance(rows, list) else []:
        try:
            honey = (str(row.get("currency") or "").lower() == "honey"
                     or row.get("shop") == "mountain_top_shop")
            if (row.get("ok") and honey
                    and float(fall.before_at) - 60 <= float(row["at"]) <= float(fall.after_at) + 60
                    and int(row["price"]) * (1 - BOUGHT_EARNED_SHARE)
                    <= int(fall.amount) <= int(row["price"]) + MATCH_TOLERANCE):
                return row
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return None


def card_key(qid: str, choice: str, table: dict | None = None) -> str | None:
    """The item a card answer says he owns, or None. What the window writes
    into `goals.owned` (his word, so CONFIRMED from then on)."""
    table = prices() if table is None else table
    qid = str(qid or "")
    if qid.startswith(OWNED_PREFIX) and choice == YES:
        key = qid[len(OWNED_PREFIX):]
        return key if key in table else None
    if qid.startswith(DROP_PREFIX) and str(choice).startswith(BOUGHT_THE):
        key = item_key(str(choice)[len(BOUGHT_THE):], table)
        # A hive slot or a Star Amulet (`infer: false`) is not gear he owns
        # for the plan: the answer is recorded on the fall, and nothing goes
        # into goals.owned.
        return key if key and table[key].infer else None
    return None


def record_answer(var_root, qid: str, choice: str, clock=time.time) -> str | None:
    """His answer on an owned/drop card, into var/owned.json. Called by the
    window (which may be the only one running) and by the bot (which hears it
    on the socket); the second call changes nothing. Returns the item it
    confirmed, if any."""
    qid, choice = str(qid or ""), str(choice or "")
    if not qid.startswith(CARD_PREFIXES):
        return None
    table = prices()
    confirmed = card_key(qid, choice, table)
    with _locked(var_root) as state:
        items = state.setdefault("items", {})
        if qid.startswith(OWNED_PREFIX):
            key = qid[len(OWNED_PREFIX):]
            body = items.setdefault(key, {})
            if body.get("answered") == choice:
                return confirmed
            body.update(answered=choice, answered_at=clock(),
                        state=CONFIRMED if choice == YES else REJECTED)
        else:
            drop_id = qid[len(DROP_PREFIX):]
            for drop in state.setdefault("drops", []):
                if str(drop.get("id")) == drop_id:
                    drop.update(answered=choice, answered_at=clock())
            if confirmed:
                items[confirmed] = dict(
                    items.get(confirmed) or {}, state=CONFIRMED, at=clock(),
                    why=f"you answered the card for the fall of {_when(float(drop_id)) if drop_id.isdigit() else drop_id}")
    return confirmed


# ---- the inventory's counts, for the goal materials -----------------------
def inventory(var_root) -> tuple[dict, str]:
    """({material: count}, where from) from var/inventory.json, written by
    the inventory errand (act/inventory). A material it did not see is not
    in the dict: unknown, never zero."""
    try:
        body = json.loads((Path(var_root) / "inventory.json").read_text())
    except (OSError, ValueError):
        return {}, ""
    if not isinstance(body, dict):
        return {}, ""
    counts = {str(k): int(v["count"]) for k, v in (body.get("items") or {}).items()
              if isinstance(v, dict) and isinstance(v.get("count"), int)}
    return counts, f"the inventory, read {_when(body.get('read_at'))}"


# ---- readings, levels and falls --------------------------------------------
@dataclass
class Fall:
    """The balance went down between two trusted readings."""
    before_at: float
    before: int
    after_at: float
    after: int
    stopped: bool = True          # the bot was not running in between

    @property
    def id(self) -> str:
        return str(int(self.after_at))

    @property
    def amount(self) -> int:
        return self.before - self.after

    @property
    def hours(self) -> float:
        return max(0.0, self.after_at - self.before_at) / 3600.0

    def describe(self) -> str:
        return (f"honey fell {self.amount:,} ({self.before:,} -> {self.after:,}) "
                f"between {_when(self.before_at)} and {_when(self.after_at)}"
                + (" while the bot was stopped" if self.stopped else ""))


def explains(fall: Fall, table: dict, exclude=()) -> list:
    """The items whose price the fall IS: no lower than the fall, and no more
    than MATCH_TOLERANCE above it (see there). Owned items are left out --
    gear is bought once."""
    return sorted((item for key, item in table.items() if key not in exclude
                   and 0 <= item.honey - fall.amount <= MATCH_TOLERANCE),
                  key=lambda i: i.honey)


def nearest(fall: Fall, table: dict, exclude=(), n: int = 2) -> list:
    """The prices nearest a fall no single one explains, AT OR ABOVE it
    first: honey that came in between can make a fall smaller than what was
    bought, never bigger, so a price below the fall (the 5M Elite Guards for
    a 5,432,611 fall) is only ever part of it. Those come after, nearest
    first, for a fall above every price."""
    return sorted((i for k, i in table.items() if k not in exclude),
                  key=lambda i: (i.honey < fall.amount,
                                 abs(i.honey - fall.amount)))[:n]


# ---- the history, for the backfill ----------------------------------------
def history(var_root) -> tuple[list, list]:
    """(honey readings, capacity readings) from the saved record, oldest
    first. Readings are (at, value, kind, attempt); kind is "settled" (a
    convert's two identical reads), "start" (a session's first HUD read) or
    "goals" (the HUD read the goals line took after a trip). Read-only."""
    import datetime as dt
    var_root = Path(var_root)
    readings, capacity = [], []
    by_path: dict = {}
    try:
        lines = (var_root / "night" / "attempts.log").read_text(
            errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        found = _ATTEMPT.search(line)
        if found:
            by_path.setdefault(found.group(3), []).append(
                (dt.datetime.strptime(found.group(2), "%Y-%m-%d %H:%M:%S"),
                 int(found.group(1))))
    for path, starts in by_path.items():
        # The log sits where the watchdog was told to write it; read it
        # under this var root, so a copy of var reads its own logs.
        log = var_root / "night" / Path(path).name
        try:
            text = log.read_text(errors="replace")
            mtime = log.stat().st_mtime
        except OSError:
            continue
        starts = sorted(s for s in starts if s[0].timestamp() <= mtime + 60)
        # AN ATTEMPT NUMBER REUSED ON A LATER NIGHT APPENDS TO THE SAME FILE
        # (run-011.log holds 20 Sep 23:07 and 21 Sep 00:49), so segment k of
        # the file is start k of the ones that could have written it.
        segments = [s for s in text.split("=== bootstrap ===")]
        if segments and not segments[0].strip():
            segments = segments[1:]
        for (t0, attempt), segment in zip(starts[-len(segments):] if segments
                                          else [], segments):
            day, last, pending = t0, t0, None
            for raw in segment.splitlines():
                stamp = _STAMP.match(raw)
                if stamp:
                    t = day.replace(hour=int(stamp.group(1)),
                                    minute=int(stamp.group(2)),
                                    second=int(stamp.group(3)))
                    if t < last - dt.timedelta(hours=12):     # past midnight
                        t += dt.timedelta(days=1)
                        day += dt.timedelta(days=1)
                    last = t
                    if pending is not None:
                        readings.append((t.timestamp(), pending, "start", attempt))
                        pending = None
                found = _CAPACITY.search(raw)
                if found:
                    capacity.append((t0.timestamp(),
                                     int(found.group(1).replace(",", "")), attempt))
                found = _START.search(raw)
                if found:
                    pending = int(found.group(1).replace(",", ""))
                # THE GOALS LINE'S HONEY IS THE HEARTBEAT'S LAST READING, and
                # the line says when it was taken, to the minute: at 07:31:19
                # on 26 Sep (run-433.log:879) it carried 72,152,058 "(the HUD,
                # 26 Sep 07:29)", read before the convert whose settled
                # 74,510,193 the ledger stamps 07:31:19 -- dated by the log
                # line, that was a false fall of 2,358,135.
                found = _GOALS.search(raw)
                if found:
                    try:
                        when = dt.datetime.strptime(
                            f"{t0.year} {found.group(2)}", "%Y %d %b %H:%M")
                    except ValueError:
                        when = None
                    if when is not None:
                        readings.append((when.timestamp(),
                                         int(found.group(1).replace(",", "")),
                                         "goals", attempt))
            if pending is not None:
                readings.append((last.timestamp(), pending, "start", attempt))
    try:
        trips = (var_root / "trips.jsonl").read_text(errors="replace").splitlines()
    except OSError:
        trips = []
    for line in trips:
        try:
            row = json.loads(line)
            found = SETTLED.search(str(row.get("convert_note") or ""))
            if found:
                readings.append((float(row["at"]),
                                 int(found.group(1).replace(",", "")),
                                 "settled", row.get("attempt")))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    # THE SAME SECOND, IN THE ORDER THEY WERE READ. A trip's `at` is a float
    # and the goals line after it is stamped to the second, so the goals
    # line (read AFTER the settle, a few hundred honey higher) sorted first
    # and made a false fall of up to 16,526. Floored, settled goes first.
    rank = {"settled": 0, "goals": 1, "start": 2}
    readings.sort(key=lambda r: (int(r[0]), rank.get(r[2], 3)))
    capacity.sort()
    return readings, capacity


def _trusted(readings: list) -> list:
    """The readings that the one before or after backs up (see
    CORROBORATE_RATIO); a settled convert backs itself up. The neighbour may
    be the next session's: before the goals line (26 Sep) most sessions left
    one reading, their "starting honey", and the restart after it is the
    only other reading near it."""
    out = []
    for i, (at, value, kind, attempt) in enumerate(readings):
        if value <= 0:
            continue
        ok = kind == "settled"
        for j in (i - 1, i + 1):
            if ok or not 0 <= j < len(readings):
                continue
            other = readings[j]
            if other[1] > 0 and \
                    1 / CORROBORATE_RATIO <= other[1] / value <= CORROBORATE_RATIO:
                ok = True
        if ok:
            out.append(readings[i])
    return out


def falls_in(readings: list) -> list:
    """Every fall of more than MATCH_TOLERANCE between trusted readings."""
    good = _trusted(readings)
    out = []
    for a, b in zip(good, good[1:]):
        if a[1] - b[1] > MATCH_TOLERANCE:
            out.append(Fall(a[0], a[1], b[0], b[1], stopped=a[3] != b[3]))
    return out


# ---- the bag, from the capacity -------------------------------------------
@dataclass
class Step:
    before_at: float
    before: int
    after_at: float
    after: int
    lasted: float                 # seconds the new level was seen over


def capacity_steps(readings: list) -> list:
    """Session-start capacities that changed and then HELD for
    CAPACITY_PERSIST_SECONDS (see there). `readings` are (at, capacity, ...)."""
    levels = []                   # [value, first_at, last_at]
    for at, value, *_ in readings:
        if levels and levels[-1][0] == value:
            levels[-1][2] = at
        else:
            levels.append([value, at, at])
    out, held = [], None
    for level in levels:
        if level[2] - level[1] < CAPACITY_PERSIST_SECONDS:
            continue                                  # temporary, or too new
        if held is not None and level[0] != held[0]:
            out.append(Step(held[2], held[0], level[1], level[0],
                            level[2] - level[1]))
        held = level
    return out


def bag_from_step(step: Step, table: dict, bag: str | None) -> tuple:
    """(the bag Item, why) when the jump is one bag's and nothing else's under
    the account research's model; else (None, why)."""
    fits = []
    for m in CAPACITY_MULTIPLIERS:
        s0, s1 = step.before / m, step.after / m
        if all(abs(s - round(s / STATIC_STEP) * STATIC_STEP) < 1.0 for s in (s0, s1)):
            fits.append((m, round(s1 - s0)))
    if len(fits) != 1:
        return None, (f"capacity {step.before:,} -> {step.after:,}: the model "
                      f"(static x {' or x'.join(f'{m:.2f}' for m in CAPACITY_MULTIPLIERS)}) "
                      + ("fits neither side whole, so a multiplier changed too"
                         if not fits else "fits both ways"))
    m, delta = fits[0]
    held = table.get(bag) if bag else None
    bags = [i for i in table.values() if i.slot == "bag" and held is not None
            and i.add - held.add == delta]
    # Anything else that could add the same: a guard or belt over one of the
    # lower ones in its slot (which one is worn is not known), or over none.
    other = []
    for item in table.values():
        if item.slot in ("bag", "tool", "") or not item.add:
            continue
        lower = {0} | {i.add for i in table.values()
                       if i.slot == item.slot and i.add < item.add}
        if any(item.add - low == delta for low in lower):
            other.append(item.label)
    # OR A MULTIPLIER, which can land on the same `after` at the same
    # multiplier: at a static of 800,000 the Honey Mask's x1.25 is +200,000 of
    # static, exactly a Blue -> Porcelain Port-O-Hive swap. Over each cheaper
    # item in its slot (its own add and times undone) or none, and either
    # CAPACITY_MULTIPLIERS: after/m = (before/(m x t0) - add0 + add) x times.
    for item in table.values():
        if item.times == 1.0 or item.slot in ("bag", "tool", "") or \
                item.label in other:
            continue
        lower = [(0, 1.0)] + [(i.add, i.times) for i in table.values()
                              if i.slot == item.slot and i.key != item.key
                              and i.honey < item.honey]
        if any(abs(step.after / mm - (step.before / (mm * t0) - add0
                                      + item.add) * item.times) < 1.0
               for mm in CAPACITY_MULTIPLIERS for add0, t0 in lower):
            other.append(item.label)
    why = (f"capacity {step.before:,} -> {step.after:,} is +{delta:,} static at "
           f"x{m:.2f}")
    if held is None:
        return None, why + "; the bag worn before it is not known"
    if len(bags) == 1 and not other:
        return bags[0], why + f", exactly a {held.label} -> {bags[0].label} swap"
    return None, why + (f"; it fits {', '.join(b.label for b in bags)}"
                        if bags else "; no bag swap from the "
                        f"{held.label} adds that") + (
        f", and also {', '.join(other[:4])}" if other else "")


# ---- the bot's end ---------------------------------------------------------
class Purchases:
    """Watches the balance for purchases, and asks about them.

    Driven by `goals.Watch` on every honey reading (the heartbeat's, every
    20 s, and the session's first). Every entry point is the caller's to
    guard -- `goals.Watch.tick` swallows everything, so this can raise.
    """

    def __init__(self, var_root, emit=None, say=None, clock=time.time,
                 typed=None):
        self.var_root = Path(var_root)
        self.emit = emit or (lambda event: None)
        self.say = say or (lambda text: None)
        self.clock = clock
        # `goals.owned` as he last saved it, read fresh (he edits it live).
        self.typed = typed or (lambda: "")
        self._last: tuple | None = None       # the last reading (at, honey)
        self._run: list = []                  # the readings agreeing with it
        self._level: tuple | None = None      # the last trusted level
        self._saved = self._load_balance()    # the level the last process left
        self._withdrawn: set = set()
        self._raised: set = set()

    # ---- the balance the last process saw -------------------------------
    def _balance_path(self) -> Path:
        return self.var_root / "balance.json"

    def _load_balance(self) -> tuple | None:
        try:
            body = json.loads(self._balance_path().read_text())
            return float(body["at"]), int(body["honey"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save_balance(self, at: float, honey: int) -> None:
        from ..files import atomic_write
        with contextlib.suppress(OSError):
            atomic_write(self._balance_path(),
                         json.dumps({"at": at, "honey": honey}))

    # ---- the materials a purchase used -----------------------------------
    def observe_materials(self) -> list:
        """Gear goals the last two inventory reads say were bought (their
        materials used up), each marked INFERRED with its evidence. Runs once
        per new inventory read (var/inventory.json read_at)."""
        try:
            body = json.loads((self.var_root / "inventory.json").read_text())
        except (OSError, ValueError):
            return []
        read_at = float(body.get("read_at") or 0.0) if isinstance(body, dict) else 0.0
        now, _src = inventory(self.var_root)
        if not read_at or not now:
            return []
        path = self.var_root / MATERIALS_FILE
        try:
            prev = json.loads(path.read_text())
        except (OSError, ValueError):
            prev = {}
        from ..files import atomic_write
        if float(prev.get("at") or 0.0) >= read_at:
            return []
        with contextlib.suppress(OSError):
            atomic_write(path, json.dumps({"at": read_at, "counts": now}))
        before = prev.get("counts") or {}
        if not before:
            return []
        from . import goals as goals_plan
        table = prices()
        found = []
        with _locked(self.var_root) as state:
            owned_now = self._owned_keys(state)
            for key, goal in ((goals_plan.load() or {}).get("goals") or {}).items():
                mats = (goal or {}).get("materials") or {}
                item = table.get(str(key))
                if item is None or item.key in owned_now or not mats:
                    continue
                seen = {m: (before[m], now[m]) for m in mats if m in before and m in now}
                if any(after > was for was, after in seen.values()):
                    continue
                used = {m: was - after for m, (was, after) in seen.items()
                        if was - after >= MATERIAL_SHARE * float(mats[m])}
                if len(used) < MATERIAL_MIN:
                    continue
                why = ("its materials were used: " + ", ".join(
                    f"{m.replace('_', ' ')} {seen[m][0]:,} -> {seen[m][1]:,} (it takes {mats[m]:,})"
                    for m in used) + f", between {_when(prev.get('at'))} and {_when(read_at)}")
                self._infer(state, item, why, read_at)
                found.append(item.key)
                self.say(f"owned: the {item.label} looks bought — {why}")
        return found

    # ---- the backfill -----------------------------------------------------
    def backfill(self, plan=None, rate=None) -> list:
        """Once: every fall and capacity step in the saved record, into
        var/owned.json, and the newest unexplained fall asked about. Returns
        report lines. A later call does nothing."""
        if "backfill" in load_state(self.var_root):
            return []
        readings, capacity = history(self.var_root)
        falls = falls_in(readings)
        lines = [f"owned: read the saved record for purchases — {len(readings)} "
                 f"balance readings from var/trips.jsonl and the run logs, "
                 f"{len(falls)} fall(s) of more than {MATCH_TOLERANCE:,}"]
        with _locked(self.var_root) as state:
            state["backfill"] = {"at": self.clock(), "readings": len(readings),
                                 "falls": len(falls)}
            # ONLY THE NEWEST OLD FALL IS ASKED ABOUT. Each is kept as
            # evidence, but six cards about purchases days old would bury
            # the one that matters: the newest, after which nothing else has
            # been learned about what he bought.
            newest = falls[-1].id if falls else None
            for fall in falls:
                lines.append("owned: " + self._judge(state, fall, plan, rate,
                                                     ask=fall.id == newest,
                                                     backfill=True))
            state["capacity_readings"] = [[at, cap] for at, cap, _a in capacity]
            lines += [f"owned: {line}" for line in self._judge_steps(state)]
        return lines

    # ---- the bag, from the session-start capacity ------------------------
    def _judge_steps(self, state) -> list:
        """Every lasting capacity step not judged before, judged."""
        done = {round(float(d.get("at") or 0)) for d in
                state.get("capacity_steps") or []}
        out = []
        bag = self._bag(state)
        steps = capacity_steps(state.get("capacity_readings") or [])
        for step in steps:
            if round(step.after_at) in done:
                continue
            item, why = bag_from_step(step, prices(), bag)
            state.setdefault("capacity_steps", []).append(
                {"before": step.before, "after": step.after,
                 "at": step.after_at, "lasted_h": round(step.lasted / 3600, 1),
                 "why": why, "bag": item.key if item else None})
            if item is not None:
                self._infer(state, item, why, step.after_at)
                bag = item.key
            out.append(why + (f" — the {item.label} is inferred, and a card "
                              f"asks you" if item else " — nothing inferred"))
        return out

    def observe_capacity(self, capacity: int | None,
                         at: float | None = None) -> bool:
        """A SESSION-START capacity (read at the hive: in a field it is a
        field's multiple of it -- x1.075 in Strawberry, account research).
        True when it inferred a bag."""
        if not capacity:
            return False
        at = self.clock() if at is None else at
        with _locked(self.var_root) as state:
            readings = state.setdefault("capacity_readings", [])
            readings.append([at, int(capacity)])
            del readings[:-200]
            lines = self._judge_steps(state)
        for line in lines:
            self.say(f"owned: {line}")
        return any("inferred" in line and "nothing inferred" not in line
                   for line in lines)

    def _bag(self, state) -> str | None:
        """The bag worn now: the biggest one owned (his word in goals.owned,
        or inferred), else the account record's."""
        from . import knowledge
        table = prices()
        mine = self._typed_keys() | {
            k for k, b in (state.get("items") or {}).items()
            if isinstance(b, dict) and b.get("state") == INFERRED}
        bags = [table[k] for k in mine if k in table and table[k].slot == "bag"]
        if bags:
            return max(bags, key=lambda i: i.add).key
        return ((knowledge.account() or {}).get("bag") or {}).get("holding")

    # ---- a fall, judged ---------------------------------------------------
    def _typed_keys(self) -> set:
        """His word: the items `goals.owned` names (see `owned`)."""
        try:
            typed = self.typed() or ""
        except Exception:
            typed = ""
        table = prices()
        return {k for k in (item_key(n, table) for n in _names(typed)) if k}

    def _owned_keys(self, state) -> set:
        """What a fall is not asked about: his word, what is inferred, and
        the tool the account record says he holds (account.yaml, his word)."""
        from . import knowledge
        keys = self._typed_keys()
        keys |= {k for k, b in (state.get("items") or {}).items()
                 if isinstance(b, dict) and b.get("state") == INFERRED}
        tool = ((knowledge.account() or {}).get("tools") or {}).get("holding")
        # and what a shop's window showed owned (brain/sight, G13): a fall at
        # its price is "already yours", not a question
        from . import sight
        keys |= set(sight.seen_owned(self.var_root))
        return keys | ({str(tool)} if tool else set())

    @staticmethod
    def _held_keys() -> set:
        """GEAR NO FALL IN THE RECORD CAN HAVE BOUGHT, left out of what
        explains a fall and of the nearest prices: what the account record
        says he held when the record began -- account.yaml `tools.was` (the
        Golden Rake: owned at the project's start, DESIGN 1, and in his hand
        until at least 24 Sep 04:16) and `bag.holding` (the Blue
        Port-O-Hive, seen from 20 Sep 19:00) -- and
        the rungs below them, which would be downgrades: the tools before it
        in progression.yaml `order`, and the bags that add less. Not
        `tools.holding`, the Dipper: that was bought inside the record (it is
        his word, in `_owned_keys`), and neither is the Spark Staff between
        the two, which was never seen."""
        from . import knowledge
        account = knowledge.account() or {}
        table = prices()
        out = set()
        was = ((account.get("tools") or {}).get("was"))
        order = [str(k) for k in ((knowledge.progression() or {}).get("tools")
                                  or {}).get("order") or []]
        if was and str(was) in order:
            out |= set(order[:order.index(str(was)) + 1])
        elif was:
            out.add(str(was))
        bag = table.get(str((account.get("bag") or {}).get("holding") or ""))
        if bag is not None:
            out |= {bag.key} | {k for k, i in table.items()
                                if i.slot == "bag" and i.add < bag.add}
        return out

    def _infer(self, state, item: Item, why: str, at: float) -> None:
        body = (state.setdefault("items", {})).get(item.key) or {}
        # His word is never overwritten by evidence, and a "No" stands for
        # the evidence he said it to -- as does a "yes" he took back out of
        # Settings (`owned`: goals.owned is the one store of his yes).
        was = body.get("state")
        if was == CONFIRMED and item.key in self._typed_keys():
            return
        if was in (REJECTED, CONFIRMED) and body.get("why") == why:
            return
        state["items"][item.key] = {"state": INFERRED, "at": at, "why": why,
                                    "honey": item.honey}

    def _judge(self, state, fall: Fall, plan, rate, ask: bool = True,
               backfill: bool = False) -> str:
        table = prices()
        owned_now = self._owned_keys(state)
        held = self._held_keys()
        every = explains(fall, table, held)
        hits = [i for i in every if i.key not in owned_now]
        record = {"id": fall.id, "before_at": fall.before_at, "before": fall.before,
                  "after_at": fall.after_at, "after": fall.after,
                  "amount": fall.amount, "stopped": fall.stopped,
                  "explains": [i.key for i in every], "backfill": backfill}
        drops = state.setdefault("drops", [])
        if any(str(d.get("id")) == fall.id for d in drops):
            return f"{fall.describe()} — already on record"
        mine = bot_purchase(self.var_root, fall)
        if mine is not None:
            # THE BOT'S OWN PURCHASE (scripts/run_farm, var/purchases.json):
            # the owner let it spend honey (2026-10-02), and a fall it caused
            # is no question for him -- the 35th hive slot's 209,117,953 is in
            # no price table, so it would have been asked about as "no match".
            record["verdict"] = "the bot's own purchase"
            drops.append(record)
            return (f"{fall.describe()} — the bot's own purchase of the "
                    f"{mine.get('item')} ({int(mine.get('price') or 0):,} honey, "
                    f"var/purchases.json), nothing to ask")
        if len(every) == 1 and not hits:
            # EXACTLY SOMETHING HE ALREADY SAID HE OWNS: nothing to ask.
            record["verdict"] = "exact, already yours"
            drops.append(record)
            return (f"{fall.describe()}, which is the {every[0].label}'s price "
                    f"— already yours, nothing to ask")
        if hits and not any(i.infer for i in hits):
            # ONLY A HIVE SLOT OR A STAR AMULET IS LEFT (`infer: false`), once
            # what he owns is set aside: not gear the plan saves for, so
            # there is nothing to infer, and a card whose answer changes
            # nothing is not sent.
            record["verdict"] = "exact, never inferred"
            drops.append(record)
            return (f"{fall.describe()}, which is the price of the "
                    f"{', the '.join(i.label for i in hits)} to within "
                    f"{MATCH_TOLERANCE:,}" + ("" if len(every) == len(hits) else
                                              " or of gear already yours")
                    + " — not gear the plan saves for, so nothing is inferred "
                      "and nothing asked")
        if len(hits) == 1 and len(every) == 1:
            item = hits[0]
            why = (f"{fall.describe()}, which is the {item.label}'s price "
                   f"({item.honey:,}) to within {MATCH_TOLERANCE:,}")
            self._infer(state, item, why, fall.after_at)
            record["verdict"] = "exact"
            drops.append(record)
            return f"{why} — the {item.label} is inferred owned; a card asks you"
        record["verdict"] = "ambiguous" if hits else "no match"
        # A TIE IS ASKED ABOUT BY NAME, EVERY TIED ITEM: 100,000,000 is the
        # Honey, Bubble and Fire Mask alike, and 300,000 four guards, so
        # those are the answers, not his goals (ASK_OPTIONS is for those).
        record["could_be"] = ([i.key for i in hits] if hits
                              else self._could_be(fall, plan, rate, owned_now))
        record["asked"] = bool(ask and record["could_be"])
        drops.append(record)
        near = ", ".join(f"{i.label} {i.honey:,}"
                         for i in (hits or nearest(fall, table, owned_now | held)))
        return (f"{fall.describe()} — "
                + (f"it fits {len(hits)} prices ({near})" if hits else
                   f"no single price explains it (nearest: {near})")
                + ("; a card asks what it bought" if record["asked"] else
                   "; kept as evidence, not asked (an older fall)" if
                   record["could_be"] else "; none of your open goals could be it"))

    def _could_be(self, fall: Fall, plan, rate, owned_now) -> list:
        """His open goals, in his order, that the fall could include: priced
        no higher than the fall plus what the bot's own measured honey rate
        would have earned in the time between (he may have been farming)."""
        if plan is None:
            return []
        room = None if rate is None else fall.amount + rate.per_hour * fall.hours
        out = []
        for row in plan.rows:
            if row.owned or row.key in owned_now:
                continue
            if room is None or row.cost <= room:
                out.append(row.key)
        return out[:ASK_OPTIONS]

    # ---- every reading ----------------------------------------------------
    def observe(self, honey: int | None, at: float | None = None,
                plan=None, rate=None) -> bool:
        """One HUD reading (goals.hud_honey's: None for an unreadable or
        misgrouped one). True when it changed what is owned."""
        # A NEW INVENTORY READ is checked for used materials first: the
        # balance cannot say what was bought when play earned honey too.
        with contextlib.suppress(Exception):
            if self.observe_materials():
                return True
        if honey is None:
            # A GAP BREAKS "TWO IN A ROW": misread, unreadable, misread is
            # not two readings agreeing.
            self._last, self._run = None, []
            return False
        at = self.clock() if at is None else at
        honey = int(honey)
        last, self._last = self._last, (at, honey)
        if last is None or not 0 <= honey - last[1] <= MATCH_TOLERANCE:
            self._run = [(at, honey)]
            return False                          # not a level yet
        self._run.append((at, honey))
        # A LEVEL: `last` and this agree. The fall, if any, is from the
        # previous level (this process's, or the one the last process
        # saved) to the first reading of this one.
        before = self._level or self._saved
        far = before is not None and not (
            before[1] > 0 and 1 / CORROBORATE_RATIO <= honey / before[1]
            <= CORROBORATE_RATIO)
        if far and (len(self._run) < FAR_LEVEL_READINGS
                    or self._run[-1][0] - self._run[0][0] < FAR_LEVEL_SECONDS):
            return False                          # a far level must last
        start = self._run[0] if far else last
        # From the level the LAST process saved, the bot was not running in
        # between (a restart, or a stop while he played); from this
        # process's own, it was -- he had taken the controls.
        stopped = self._level is None
        self._level, self._saved = (at, honey), None
        self._save_balance(at, honey)
        if before is None or before[1] - start[1] <= MATCH_TOLERANCE:
            return False
        fall = Fall(before[0], before[1], start[0], start[1], stopped=stopped)
        with _locked(self.var_root) as state:
            line = self._judge(state, fall, plan, rate)
        self.say(f"owned: {line}")
        return True

    # ---- the cards --------------------------------------------------------
    def _raise(self, qid: str) -> None:
        """The card's state as a Belief, once a process (goals.RAISED)."""
        from ..telemetry.events import Belief
        from .goals import RAISED
        if qid not in self._raised:
            self._raised.add(qid)
            self._withdrawn.discard(qid)
            self.emit(Belief(name=qid, value=RAISED, source="owned"))

    def _checked_drop(self, drop: dict, could: list, table: dict) -> list:
        """A fall card's answers, CHECKED against what the shop windows
        showed (brain/sight, ROADMAP G13) -- the owner, 2026-10-19: "instead
        of asking that it will check". An answer seen owned BEFORE the fall
        was owned already, and one seen with a price AFTER it was not
        bought by it: both leave the card. ONE seen owned after the fall
        began answers it. No answer left: the card is settled -- the fall
        was something else. Returns the answers still open ([] = settled)."""
        from . import sight
        items = sight.load(self.var_root, table)
        before, after = float(drop.get("before_at") or 0), float(drop.get("after_at") or 0)
        left, bought = [], []
        for key in could:
            body = items.get(key) or {}
            yes, no = body.get(sight.OWNED), body.get(sight.NOT_OWNED)
            if yes and float(yes.get("at") or 0) < before:
                continue                           # owned before the fall
            if no and float(no.get("at") or 0) >= after and not (
                    yes and float(yes.get("at") or 0) > float(no.get("at") or 0)):
                continue                           # still for sale after it
            left.append(key)
            if yes:
                bought.append(key)
        if len(bought) == 1:
            line = sight.checked_line(table[bought[0]].label, items[bought[0]][sight.OWNED])
            answer = f"{BOUGHT_THE}{table[bought[0]].label} ({line})"
        elif not left:
            answer = (f"{NONE_OF_THESE} (checked: a shop window showed each of "
                      f"{', '.join(table[k].label for k in could)} owned before the fall "
                      f"or still for sale after it)")
        else:
            return left
        with _locked(self.var_root) as state:
            for row in state.get("drops") or []:
                if str(row.get("id")) == str(drop.get("id")) and not row.get("answered"):
                    row.update(answered=answer, answered_at=self.clock(), checked=True)
        drop["answered"] = answer
        self.say(f"owned: the fall of {_when(after)} -- {answer} -- not asking")
        return []

    def cards(self, plan=None) -> None:
        """Send every unanswered card again (the socket does not replay a
        question, and the window may have been closed when it was first sent
        -- the same rule goals.Watch follows), and take down any whose
        question has been settled some other way."""
        from ..telemetry.events import Belief, Option, Question
        from .goals import WITHDRAWN
        from . import sight
        state = load_state(self.var_root)
        table = prices()
        typed = self._typed_keys()                 # his word only
        seen = sight.seen_owned(self.var_root, table)
        for key, body in (state.get("items") or {}).items():
            item = table.get(key)
            if item is None or not isinstance(body, dict):
                continue
            qid = f"{OWNED_PREFIX}{key}"
            if body.get("state") != INFERRED or key in typed or key in seen:
                # Only an item that was inferred (`honey` is set by _infer)
                # ever had this card; one confirmed on a fall card did not.
                if qid not in self._withdrawn and "honey" in body:
                    self._withdrawn.add(qid)
                    self.emit(Belief(name=qid, value=WITHDRAWN, source="owned"))
                    # CHECKED, NOT ASKED (G13): a shop's window showed it owned
                    if key in seen and key not in typed and body.get("state") == INFERRED:
                        self.say(f"owned: {sight.checked_line(item.label, seen[key])}")
                continue
            self._raise(qid)
            self.emit(Question(
                id=qid, question=f"Did you buy the {item.label}?",
                context=(f"The bot thinks so: {body.get('why')}. Until you "
                         f"answer, the goal list treats it as owned and shows "
                         f"it as inferred. {sight.ask_note(self.var_root, [key], table)}"),
                default=YES,
                options=[Option(label=YES, score=float(item.honey), unit="honey",
                                why="it counts as yours for good"),
                         Option(label=NO, score=0.0, unit="honey",
                                why="the goal comes back, and the bot saves "
                                    "for it again")]))
        labels = {r.key: r.label for r in (plan.rows if plan else [])}
        for drop in state.get("drops") or []:
            qid = f"{DROP_PREFIX}{drop.get('id')}"
            if not drop.get("asked"):
                continue
            could = [k for k in drop.get("could_be") or [] if k not in typed
                     and k in table]
            if not drop.get("answered") and could:
                could = self._checked_drop(drop, could, table)
            if drop.get("answered") or not could:
                if qid not in self._withdrawn:
                    self._withdrawn.add(qid)
                    self.emit(Belief(name=qid, value=WITHDRAWN, source="owned"))
                continue
            fall = Fall(drop["before_at"], drop["before"], drop["after_at"],
                        drop["after"], bool(drop.get("stopped")))
            said = sorted(table[k].label for k in typed)
            ties = [table[k].label for k in drop.get("explains") or []
                    if k in table]
            why = (f"It is exactly the price of the {', the '.join(ties)}, so "
                   f"the bot cannot tell which." if len(ties) > 1 else
                   "No single price explains it, and you may have farmed some "
                   "in that time too.")
            why += f" {sight.ask_note(self.var_root, could, table)}"
            self._raise(qid)
            self.emit(Question(
                id=qid, question=(f"Your honey fell {fall.amount:,} between "
                                  f"{_when(fall.before_at)} and "
                                  f"{_when(fall.after_at)} — did you buy one "
                                  f"of these?"),
                context=(f"{fall.describe()[0].upper()}{fall.describe()[1:]}, "
                         f"and honey only goes down when something is bought. "
                         f"{why}"
                         + (f" You have told the bot you own: {', '.join(said)}."
                            if said else "")),
                default=NONE_OF_THESE,
                options=[Option(label=f"{BOUGHT_THE}{labels.get(k, table[k].label)}",
                                score=float(table[k].honey), unit="honey",
                                why="it counts as yours, and the plan moves on")
                         for k in could]
                + [Option(label=SPENT_ON_JELLY, score=0.0, unit="honey",
                          why="no gear changes hands; the fall was jelly")]
                + [Option(label=NONE_OF_THESE, score=0.0, unit="honey",
                          why="nothing changes")]))
