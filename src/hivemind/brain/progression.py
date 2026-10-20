"""Where the account is in the game, and what to get next, for any account.

THE OWNER, 2026-10-14: it should check what stage of the game the account is
at and what it holds, so it knows what to get next -- and works for anyone at
any stage. So the stage and the
next goals come from what the bot READS in the game, and the owner's typed
lists only add to it:

  * bees, the bee types seen and the gifted ones in the hive -- var/bees.json
    (act/beemenu, the bee menu read);
  * gear -- brain/owned (their word in `goals.owned`, a balance fall they
    confirmed or the bot inferred, var/purchases.json), and every shop window
    the bot has read (brain/sight, var/owned_by_sight.json: "Beekeeper's Boots
    | 15.000.000 Honey | Edguipped" -- an "Equip(ped)" or "Purchased" button
    under the item's own name is an item the account has);
  * badges -- every badge-menu page the bot kept (var/badges/*/page.txt);
  * quests -- the last quest-menu read (var/quests.json): a Bucko Bee quest
    in it means Science Bear's first Translator was spent.

A THING NO READER SEES IS UNKNOWN, NEVER OWNED. There is no reader yet for the
equipped tool, bag, mask, belt, guards, boots, glider or amulets, nor for how
many gifted TYPES were ever discovered (the bee menu's stars are only the
hive's) -- only the shop windows the bot read (brain/sight). When the next
goals hang on a slot no window answered, `questions` builds the card that
used to ask them ("Which boots do you wear?"). Since 2026-10-26 it is never
sent (the owner found the questions too many):
brain/goals.Watch says once that the plan assumes none of them, and the shop
look checks their windows (brain/sight.open_items reads these cards).

The research is data/knowledge/progression/{blue,red,white}.yaml (one file per
hive colour, setting `progression.hive`), each a list of stages, each stage a
list of goals with a cost, requirements, a why and its sources. A goal is done
when it is owned, when a dearer item for the same gear slot is owned, or by
the reading its kind is judged by (a bee count, a badge tier, a quest giver).

brain/goals puts the next goals after the owner's own list, labelled "from
the Blue progression"; the buyer still buys only what its own rules allow
(brain/buyer.bot_buys): a progression goal has no shop of its own, so the bot
never buys one -- it says what is next and why.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

HIVES = ("blue", "red", "white")
DEFAULT_HIVE = "blue"
TIERS = ("junior", "cadet", "hotshot", "ace", "master", "grandmaster")
QUESTION_PREFIX = "progression:"
NONE_YET = "None of these yet"
# how account_from_files labels gear brain/owned has as SEEN (brain/sight)
SEEN_HOW = "seen: "
# Shown in the plan after the owner's own goals: enough that the queue never
# runs dry, few enough that the Goals tab stays their list first.
PLAN_EXTRA = 3
# priority 5 is the research's "optional / skip" (the Spark Staff, the Honey
# Mask for blue): never put forward.
SKIP_PRIORITY = 5
SLOT_ASK = {"tool": "Which tool do you use?", "bag": "Which bag do you use?",
            "hat": "Which mask or hat do you wear?", "belt": "Which belt do you wear?",
            "boots": "Which boots do you wear?",
            "right_guard": "Which right-shoulder guard do you wear?",
            "left_guard": "Which left-shoulder guard do you wear?",
            "glider": "Do you have the Parachute or the Glider?",
            "star_amulet": "Which Star Amulet do you have?",
            "sprinkler": "Which sprinklers do you have?"}


def _slug(text: str) -> str:
    return "_".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


# ---- the research files ---------------------------------------------------
_LOADED: dict = {}


def load(hive: str = DEFAULT_HIVE) -> dict:
    """data/knowledge/progression/<hive>.yaml, or {} when it cannot be read.
    An unknown colour reads the default's. Shared: do not change it."""
    import yaml
    from ..datapaths import data
    hive = hive if hive in HIVES else DEFAULT_HIVE
    path = data("knowledge", "progression", f"{hive}.yaml")
    try:
        stamp = path.stat().st_mtime_ns
        hit = _LOADED.get(hive)
        if hit and hit[0] == stamp:
            return hit[1]
        body = yaml.safe_load(path.read_text()) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    body = body if isinstance(body, dict) else {}
    _LOADED[hive] = (stamp, body)
    return body


def hive_from(settings) -> str:
    """The `progression.hive` setting, the default when unset or unknown."""
    value = str((settings.get("progression.hive") if settings is not None else "")
                or DEFAULT_HIVE).lower()
    return value if value in HIVES else DEFAULT_HIVE


def _goals(data: dict) -> list:
    """[(stage index, goal)] in file order."""
    return [(i, g) for i, st in enumerate(data.get("stages") or [])
            for g in st.get("goals") or [] if isinstance(g, dict)]


def _honey(goal: dict) -> int:
    value = (goal.get("cost") or {}).get("honey")
    return int(value) if isinstance(value, (int, float)) else 0


# ---- what the bot knows of the account ------------------------------------
@dataclass
class Account:
    """Everything the stage is judged on. `None`/empty is not read."""
    bees: int | None = None
    gifted_min: int = 0                 # gifted types known at least
    types: dict = field(default_factory=dict)      # colour -> types seen
    in_hive: set = field(default_factory=set)      # bee types in the hive
    owned: dict = field(default_factory=dict)      # slug -> where it was seen
    badges: dict | None = None          # badge name -> tier index (TIERS)
    quests: str = ""                    # the last quest-menu transcript
    answered: dict = field(default_factory=dict)   # question id -> their answer
    save_diamond: bool = True

    def has(self, goal: dict) -> str:
        """Where the bot saw it owned, or ""."""
        for key in (goal.get("id"), _slug(goal.get("label", ""))):
            if key and key in self.owned:
                return self.owned[key]
        return ""

    def badge_count(self, tier: str = "junior") -> int | None:
        if self.badges is None:
            return None
        least = TIERS.index(tier)
        return sum(1 for t in self.badges.values() if t >= least)

    def badge_tier(self, name: str) -> int | None:
        return None if self.badges is None else self.badges.get(name, -1)


BADGE = re.compile(r"([A-Z][A-Za-z ]+?) Badge - (" + "|".join(t.title() for t in TIERS) + ")")
_BADGES: dict = {}


def badge_tiers(var_root) -> dict | None:
    """{badge name: highest tier index seen} over every badge-menu page the
    bot kept (act/badges), or None when it has none. A tier only ever goes
    up, so the highest reading of each badge is the one believed.
    ponytail: OCR clips a name now and then ("Tree" for "Pine Tree"); a name
    that ends another one is dropped, a misread tier is not caught."""
    root = Path(var_root) / "badges"
    try:
        stamp = root.stat().st_mtime_ns
    except OSError:
        return None
    if _BADGES.get("key") == (str(root), stamp):
        return _BADGES["value"]
    out: dict = {}
    for page in root.glob("*/page.txt"):
        try:
            text = page.read_text(errors="replace")
        except OSError:
            continue
        for name, tier in BADGE.findall(text):
            name = " ".join(name.split()).lower()
            out[name] = max(out.get(name, -1), TIERS.index(tier.lower()))
    out = {n: t for n, t in out.items()
           if not any(o != n and o.endswith(" " + n) for o in out)} or None
    _BADGES.update(key=(str(root), stamp), value=out)
    return out


def account_from_files(var_root, settings=None) -> Account:
    """The Account from the bot's own reads. Read-only, never raises."""
    from . import owned as owned_mod
    var_root = Path(var_root)
    acct = Account()
    # THE HIVE (act/beemenu): the header's count, the types and gifted stars
    try:
        bees = json.loads((var_root / "bees.json").read_text())
    except (OSError, ValueError):
        bees = {}
    if isinstance(bees, dict):
        if bees.get("total"):
            acct.bees = int(bees["total"])
        acct.in_hive = {k for k, v in (bees.get("bees") or {}).items() if v}
        seen = set(bees.get("bees") or {}) | set(bees.get("unsure") or {})
        try:
            from .knowledge import _load
            kinds = (_load("bee_types.yaml").get("types") or {})
        except Exception:
            kinds = {}
        for bee in seen:
            colour = (kinds.get(bee) or {}).get("colour")
            if colour:
                acct.types[colour] = acct.types.get(colour, 0) + 1
        acct.gifted_min = len(bees.get("gifted") or [])
    if acct.bees is None:
        try:
            from .knowledge import standing
            acct.bees = standing().bees
        except Exception:
            pass
    # GEAR: their word, the balance's evidence, the bot's purchases, shop windows
    typed = (settings.get("goals.owned") if settings is not None else "") or ""
    for name in re.split(r"[,;\n]+", str(typed)):
        if name.strip():
            acct.owned[_slug(name)] = "you said so in Settings > Goals"
    try:
        for key, item in owned_mod.owned(typed, var_root).items():
            acct.owned.setdefault(key, f"{item.how}: {item.why}")
    except Exception:
        pass
    try:
        rows = json.loads((var_root / "purchases.json").read_text())
    except (OSError, ValueError):
        rows = []
    for row in rows if isinstance(rows, list) else []:
        key = _slug(row.get("item")) if isinstance(row, dict) and row.get("ok") else ""
        # not gear: a hive slot, an egg, "300 Gumdrops"
        if key and not re.search(r"^(hive_slot|\d)|_egg$", key):
            acct.owned.setdefault(key, "the bot bought it")
    acct.badges = badge_tiers(var_root)
    try:
        acct.quests = str(json.loads((var_root / "quests.json").read_text()).get("transcript") or "")
    except (OSError, ValueError, AttributeError):
        pass
    try:
        asked = json.loads((var_root / "goals.json").read_text()).get("asked") or {}
        acct.answered = {k: v.get("answered") for k, v in asked.items()
                         if k.startswith(QUESTION_PREFIX) and isinstance(v, dict)
                         and v.get("answered")}
    except (OSError, ValueError, AttributeError):
        pass
    # THE OWNER SAVES DIAMOND EGGS FOR RECIPES. `eggs.save_diamond` comes from
    # another branch; absent, they are saved.
    if settings is not None and settings.get("eggs.save_diamond") is False:
        acct.save_diamond = False
    return acct


# ---- judging a goal --------------------------------------------------------
def _slot_ladder(data: dict, slot: str) -> list:
    """Every priced item for `slot` in all three hives' files, cheapest first:
    Hiking Boots are white's, and a blue player can still be wearing them."""
    out = {}
    for body in [data] + [load(h) for h in HIVES]:
        for _i, g in _goals(body):
            if g.get("slot") == slot and _honey(g):
                out.setdefault(g.get("id"), g)
    return sorted(out.values(), key=_honey)


# A goal judged by a reading rather than by ownership: {id: (acct -> why or "")}.
def _quest_giver(word):
    return lambda a: f"{word} quests are in the quest menu" if word in a.quests.lower() else ""


DONE_BY = {
    "basic_eggs_to_25": lambda a: f"{a.bees} bees" if (a.bees or 0) >= 25 else "",
    "basic_egg": lambda a: f"{a.bees} bees" if (a.bees or 0) >= 25 else "",
    "science_translator_1": lambda a: _quest_giver("bucko bee")(a) or _quest_giver("riley bee")(a),
    "riley_translator": _quest_giver("riley bee"),
    "discover_4_red_types": lambda a: "4 red types seen" if a.types.get("red", 0) >= 4 else "",
    "badges_15": lambda a: "15 badges read" if (a.badge_count() or 0) >= 15 else "",
    "goo_hotshot": lambda a: "Goo badge read" if (a.badge_tier("goo") or -1) >= 2 else "",
    "honey_badge_ace": lambda a: "Honey badge read" if (a.badge_tier("honey") or -1) >= 3 else "",
}


def done(acct: Account, goal: dict, data: dict) -> str:
    """Why the goal needs nothing more, or "" when it is still open."""
    gid = str(goal.get("id") or "")
    where = acct.has(goal)
    if where:
        return f"owned ({where})"
    m = re.fullmatch(r"hive_slot(?:<=(\d+))?", gid)
    if m:
        top = int(m.group(1) or 50)
        return f"{acct.bees} bees" if (acct.bees or 0) >= top else ""
    if gid in DONE_BY:
        return DONE_BY[gid](acct)
    if goal.get("slot"):
        for other in _slot_ladder(data, goal["slot"]):
            if _honey(other) > _honey(goal) and acct.has(other):
                return f"the {other.get('label')} replaces it"
    if goal.get("kind") == "bee" and gid.endswith("_bee") and gid[:-4] in acct.in_hive:
        return "in the hive"
    if goal.get("kind") == "field_unlock":
        states = [requirement(acct, r, data)[0] for r in goal.get("requires") or []]
        return "the zone is open" if states and all(s is True for s in states) else ""
    return ""


def requirement(acct: Account, text, data: dict) -> tuple:
    """(True met / False not met / None not known, why) for one `requires`."""
    text = str(text or "")
    low = text.lower()
    ids = {str(g.get("id")): g for _i, g in _goals(data)}
    if text in ids:
        why = done(acct, ids[text], data)
        return (True, why) if why else (False, f"{ids[text].get('label')} first")
    m = re.search(r"bees?\s*>=\s*(\d+)", low) or re.match(r"^(\d+) bees\b", low)
    if m:
        need = int(m.group(1))
        if acct.bees is None:
            return None, f"{need} bees (bee count not read)"
        return acct.bees >= need, f"{need} bees, you have {acct.bees}"
    m = re.search(r"(\d+) gifted (?:bee )?types|gifted_types\s*>=\s*(\d+)", low)
    if m:
        need = int(m.group(1) or m.group(2))
        # the bee menu shows the hive's gifted only: a lower bound
        return (True, f"{need} gifted types") if acct.gifted_min >= need else \
            (None, f"{need} gifted types discovered (not read; {acct.gifted_min} gifted in the hive)")
    m = re.search(r"(\d+) (red|blue) (?:bee )?types", low)
    if m:
        need, colour = int(m.group(1)), m.group(2)
        return (True, f"{need} {colour} types") if acct.types.get(colour, 0) >= need else \
            (None, f"{need} {colour} types (seen {acct.types.get(colour, 0)})")
    m = (re.search(r"(\d+) (cadet|hotshot|ace|master|grandmaster) badges?", low)
         or re.search(r"(cadet|hotshot|ace|master|grandmaster)_badges\s*>=\s*(\d+)", low))
    if m:
        need, tier = ((int(m.group(1)), m.group(2)) if m.group(1).isdigit()
                      else (int(m.group(2)), m.group(1)))
        have = acct.badge_count(tier)
        if have is None:
            return None, f"{need} {tier.title()} badges (badge menu not read)"
        return have >= need, f"{need} {tier.title()} badges, {have} read"
    m = re.match(r"^(\d+) badges", low)
    if m:
        have = acct.badge_count()
        if have is None:
            return None, f"{m.group(1)} badges (badge menu not read)"
        return have >= int(m.group(1)), f"{m.group(1)} badges, {have} read"
    words = _slug(text)
    if any(key and len(key) > 5 and key in words for key in acct.owned):
        return True, text
    return None, text


# ---- the stage and the next goals ------------------------------------------
@dataclass
class Stage:
    hive: str
    id: str
    name: str
    index: int
    behind: list = field(default_factory=list)   # the stage before's must-dos still open
    previous: str = ""

    @property
    def boundary(self) -> bool:
        return bool(self.behind)

    @property
    def label(self) -> str:
        """"Blue late (mid not finished)"."""
        return (f"{self.hive.title()} {self.id}"
                + (f" ({self.previous} not finished)" if self.behind else ""))


def _entered(acct: Account, enter: dict, data: dict) -> bool:
    """Bees and gear. NOT THE BALANCE: `enter_when.honey` is the research's
    rough wealth at that point, and a player who just spent 5B on the
    Diamond Mask is no less far on (a 10M HUD reading would put an example
    40-bee account with the Porcelain gear back in "mid")."""
    if (acct.bees or 0) < int(enter.get("bees") or 0):
        return False
    ids = {str(g.get("id")): g for _i, g in _goals(data)}
    return all(done(acct, ids.get(k) or {"id": k, "label": k}, data)
               for k in enter.get("gear") or [])


def current_stage(acct: Account, data: dict, hive: str = "") -> Stage:
    """The furthest stage the account has entered: its `enter_when` met, or a
    must-do (priority 1) gear or amulet of that stage owned outright."""
    stages = data.get("stages") or []
    at = 0
    for i, st in enumerate(stages):
        if _entered(acct, st.get("enter_when") or {}, data):
            at = i
    for i, goal in _goals(data):
        if (i > at and goal.get("priority") == 1 and goal.get("kind") in ("gear", "amulet")
                and acct.has(goal)):
            at = i
    if not stages:
        return Stage(hive or str(data.get("hive") or ""), "", "", 0)
    st = stages[at]
    stage = Stage(hive or str(data.get("hive") or ""), str(st.get("id")),
                  str(st.get("name") or ""), at)
    if at:
        prev = stages[at - 1]
        stage.previous = str(prev.get("id"))
        # a quest no reader can see done (Black Bear's egg chains) would hold
        # every later account "not finished" for ever: only what is judged
        stage.behind = [g for g in prev.get("goals") or []
                        if g.get("priority") == 1 and _open(acct, g, data)
                        and (g.get("kind") != "quest" or g.get("id") in DONE_BY)]
    return stage


def _open(acct: Account, goal: dict, data: dict) -> bool:
    """Not done, not a skip, and no requirement known to be unmet."""
    if int(goal.get("priority") or 9) >= SKIP_PRIORITY or done(acct, goal, data):
        return False
    return all(requirement(acct, r, data)[0] is not False for r in goal.get("requires") or [])


@dataclass
class Next:
    goal: dict
    stage: str
    checks: list = field(default_factory=list)   # requirements nobody has read

    @property
    def id(self) -> str:
        return str(self.goal.get("id"))

    @property
    def label(self) -> str:
        return str(self.goal.get("label") or self.id)

    @property
    def honey(self) -> int:
        return _honey(self.goal)

    @property
    def items(self) -> dict:
        return dict((self.goal.get("cost") or {}).get("items") or {})

    @property
    def why(self) -> str:
        return " ".join(str(self.goal.get("why") or "").split())

    @property
    def source(self) -> str:
        return ", ".join(str(s) for s in self.goal.get("source") or [])

    def describe(self) -> str:
        cost = f"{self.honey:,} honey" if self.honey else "no honey cost"
        return (f"{self.label} ({self.stage}; {cost}) — {self.why}"
                + (f" [check: {'; '.join(self.checks)}]" if self.checks else ""))


def next_goals(acct: Account, n: int = 3, data: dict | None = None,
               stage: Stage | None = None) -> list:
    """The next `n` goals: the stage before's must-dos still open, then this
    stage's by priority, then the next stage's. Owned or done, a skip, or a
    requirement known unmet, and it is left out; a requirement no reader has
    seen is kept and named in `checks`."""
    data = load() if data is None else data
    stage = stage or current_stage(acct, data)
    stages = data.get("stages") or []
    pool = [(stage.previous, g) for g in stage.behind]
    for i in (stage.index, stage.index + 1):
        if i < len(stages):
            goals = sorted(stages[i].get("goals") or [],
                           key=lambda g: int(g.get("priority") or 9))
            pool += [(str(stages[i].get("id")), g) for g in goals]
    out, seen = [], set()
    for st_id, goal in pool:
        if goal.get("id") in seen or not _open(acct, goal, data):
            continue
        seen.add(goal.get("id"))
        checks = [why for ok, why in (requirement(acct, r, data)
                                      for r in goal.get("requires") or []) if ok is None]
        out.append(Next(goal, st_id, checks))
        if len(out) >= n:
            break
    return out


def plan_entry(nxt: Next, hive: str, acct: Account | None = None) -> dict:
    """A goals.yaml-shaped goal for brain/goals' queue. No `shop`: the bot
    buys nothing new on the progression's say-so (brain/buyer.bot_buys)."""
    what = nxt.why
    if acct is not None and acct.save_diamond and nxt.items.get("diamond_egg"):
        what += f" Its {nxt.items['diamond_egg']} Diamond Eggs are saved for it, never hatched."
    return {"label": nxt.label, "honey": nxt.honey, "materials": nxt.items,
            "slot": nxt.goal.get("slot", ""), "what": what,
            "origin": f"from the {hive.title()} progression",
            "source": f"data/knowledge/progression/{hive}.yaml ({nxt.source})"}


def facts(data: dict, stage_id: str) -> dict:
    """What the planner can use beside the goals: the stage's best fields,
    quest chains, bee priorities and tips."""
    for st in data.get("stages") or []:
        if st.get("id") == stage_id:
            return {"fields": [f.get("field") for f in st.get("fields") or []],
                    "quests": [(q.get("giver"), q.get("chain")) for q in st.get("quests") or []],
                    "bees": sorted((b.get("gifted_priority", 9), b.get("bee"))
                                   for b in st.get("bees") or []),
                    "tips": list(st.get("tips") or [])}
    return {}


# ---- asking the player what no reader sees ---------------------------------
def slot_checked(acct: Account, data: dict, slot: str) -> str:
    """The log line when only a shop's window (brain/sight) answers `slot`'s
    question -- the worn item's "Equipped" first -- else "" (their own word,
    or nothing, answers it)."""
    have = [acct.has(g) for g in _slot_ladder(data, slot) if acct.has(g)]
    seen = [w[len(SEEN_HOW):] for w in have if w.startswith(SEEN_HOW)]
    if not seen or len(seen) != len(have) or slot not in SLOT_ASK:
        return ""
    worn = [w for w in seen if " shows Equipped " in w]
    return f"progression: {SLOT_ASK[slot]} -- {(worn or seen)[-1]}"


def questions(acct: Account, data: dict, nxt: list, var_root=None,
              checked: list | None = None) -> list:
    """Decision Inbox cards, one per gear slot that a next goal sits in and
    that no reader has seen anything in (and they have not answered). Answering
    with an item puts it into `goals.owned` (gui/window); "None of these yet"
    says the slot is empty.

    CHECK, DON'T ASK (ROADMAP G13, the owner 2026-10-19). A slot a shop's
    window answered (brain/sight: the worn item's "Equipped", or any of its
    items owned) gets no card, and `checked` is given the line saying what
    was seen; a card still asked says in its context what was checked and
    when (`var_root`)."""
    from ..telemetry.events import Option, Question
    from . import owned as owned_mod
    from . import sight
    out = []
    for item in nxt:
        slot = item.goal.get("slot")
        qid = f"{QUESTION_PREFIX}slot:{slot}"
        if not slot or slot not in SLOT_ASK or qid in acct.answered or \
                any(q.id == qid for q in out):
            continue
        ladder = [g for g in _slot_ladder(data, slot) if not str(g.get("id")).endswith("_early")]
        if any(acct.has(g) for g in ladder):
            line = slot_checked(acct, data, slot)
            if line and checked is not None:
                checked.append(line)
            continue
        note = ""
        if var_root is not None:
            table = owned_mod.prices()
            keys = [k for k in (owned_mod.item_key(str(g.get("label")), table)
                                for g in ladder) if k]
            note = " " + sight.ask_note(var_root, keys, table)
        out.append(Question(
            id=qid, question=SLOT_ASK[slot],
            context=(f"The {item.label} is one of the next goals of the "
                     f"{str(data.get('hive') or '').title()} progression, and no "
                     f"shop window the bot read showed what you have for this.{note} "
                     f"Your answer goes into Settings > Goals > Gear you already own, "
                     f"and the plan skips what it replaces."),
            default=NONE_YET,
            options=[Option(label=str(g.get("label")), score=float(_honey(g)), unit="honey",
                            why="you have it, so the plan skips it and everything cheaper")
                     for g in ladder]
            + [Option(label=NONE_YET, score=0.0, unit="honey",
                      why="the plan keeps the cheapest of them as a goal")]))
    return out


# ---- the whole thing, for brain/goals and the GUI ---------------------------
@dataclass
class Progress:
    hive: str = DEFAULT_HIVE
    stage: Stage | None = None
    next: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    account: Account | None = None
    checked: list = field(default_factory=list)   # slots a shop window answered (G13)

    def line(self) -> str:
        """"Blue late (mid not finished) · next: Glider, Beekeeper's Boots, ..."."""
        if self.stage is None or not self.stage.id:
            return ""
        return (f"{self.stage.label} · next: " + ", ".join(n.label for n in self.next[:3])
                if self.next else self.stage.label)


# ---- YOUR OWN ROUTE (ROADMAP G10, a community idea, 22 Oct) ------------------
# "The blue/red/white plans editable (reorder, add, remove goals) and saved as
# your own plan; shareable as a preset." A route is a small YAML file in
# <config>/progression/ (beside settings.yaml), picked by `progression.plan`:
#
#   name: My blue route
#   base: blue                  # the researched route it changes
#   first: [glider, diamond_mask]   # put forward first, in this order
#   skip: [honey_mask]          # never put forward
#   add:                        # goals of your own
#     - {id: guild_alt_bees, label: 30 bees on the alt, stage: mid, why: ...}
#
# Sharing it is sharing the file. The researched files are never changed.
ROUTE_DIR = "progression"


def route_path(name: str):
    """<config>/progression/<name>.yaml, the name made file-safe."""
    from ..datapaths import config_dir
    return config_dir() / ROUTE_DIR / f"{_slug(name) or 'route'}.yaml"


def load_route(name: str) -> dict:
    """The route file `name`, or {} when there is none or it cannot be read."""
    return read_route(route_path(name))


def read_route(path) -> dict:
    """The route file at `path` (any file name), or {} when it cannot be read."""
    import yaml
    from pathlib import Path
    try:
        body = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return body if isinstance(body, dict) else {}


def route_ids(route: dict, key: str) -> list:
    """The goal ids under `key` ("first" / "skip"). A lone id is read as a
    list of one -- `first: glider` is a common hand-written slip, and read
    letter by letter it became ['g', 'l', 'i', ...] (review 2026-10-26).
    true/false are not ids."""
    value = route.get(key) if isinstance(route, dict) else None
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(x) for x in value
            if isinstance(x, (str, int)) and not isinstance(x, bool) and str(x).strip()]


def _is_priority(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def customise(data: dict, route: dict) -> tuple[dict, list]:
    """`data` (a researched route) changed by `route`, and a line for each part
    of the route that could not be used. `data` itself is not changed."""
    import copy
    out = copy.deepcopy(data)
    stages = out.get("stages") or []
    notes: list = []
    ids = {str(g.get("id")) for _i, g in _goals(out)}
    ids_of = lambda key: route_ids(route, key)

    for gid in ids_of("skip"):
        if gid not in ids:
            notes.append(f"skip: no goal {gid!r} in the {out.get('hive')} route")
    for gid in ids_of("first"):
        if gid not in ids:
            notes.append(f"first: no goal {gid!r} in the {out.get('hive')} route")
    for goal in route.get("add") or []:
        if not isinstance(goal, dict) or not goal.get("id") or not goal.get("label"):
            notes.append(f"add: a goal needs an id and a label ({goal!r})")
            continue
        gid = str(goal["id"])
        if gid in ids:
            notes.append(f"add: {gid!r} is already a goal")
            continue
        new = {"kind": "custom", "priority": 2, "why": "your own goal", **goal,
               "id": gid, "source": ["your route"]}
        if not _is_priority(new["priority"]):
            # `priority: high` from a shared file broke every sort by
            # `int(priority)` -- the editor would not start (review 2026-10-26)
            notes.append(f"add: {gid!r} priority {new['priority']!r} is not a number; it uses 2")
            new["priority"] = 2
        where = None
        if goal.get("after") is not None:
            where = next(((st, k) for st in stages
                          for k, g in enumerate(st.get("goals") or [])
                          if str(g.get("id")) == str(goal["after"])), None)
            if where is None:
                notes.append(f"add: no goal {goal['after']!r} to put {gid!r} after")
        if where is None:
            st = next((s for s in stages if str(s.get("id")) == str(goal.get("stage"))),
                      stages[-1] if stages else None)
            if st is None:
                notes.append(f"add: the route has no stages to put {gid!r} in")
                continue
            if goal.get("stage") is not None and str(st.get("id")) != str(goal["stage"]):
                notes.append(f"add: no stage {goal['stage']!r}; {gid!r} went in the last one")
            st.setdefault("goals", []).append(new)
        else:
            st, k = where
            # THE PRIORITY OF THE GOAL IT FOLLOWS, when the route gave none:
            # goals sort by priority, so a 2 after a 1 lands nowhere near it.
            # Never a skip's (a goal of your own after an optional one must
            # still be put forward). It was a setdefault that never fired:
            # `new` always had the default 2 (found reviewing G10, 2026-10-26).
            if goal.get("priority") is None:
                theirs = st["goals"][k].get("priority")
                theirs = int(theirs) if _is_priority(theirs) else 2
                new["priority"] = theirs if theirs < SKIP_PRIORITY else 2
            st["goals"].insert(k + 1, new)
        new.pop("after", None)
        new.pop("stage", None)
        ids.add(gid)

    skip, first = set(ids_of("skip")), ids_of("first")
    for st in stages:
        goals = st.get("goals") or []
        for g in goals:
            if str(g.get("id")) in skip:
                g["priority"] = SKIP_PRIORITY
        # FIRST, IN THEIR ORDER: the research's top priority (1), and listed
        # first so the stable sort in next_goals keeps them ahead of the other
        # 1s, in their order. NOT 0: `priority or 9` reads 0 as unset, a skip.
        picked = [g for gid in first for g in goals
                  if str(g.get("id")) == gid and gid not in skip]
        for g in picked:
            g["priority"] = 1
        st["goals"] = picked + [g for g in goals if g not in picked]
    if route.get("name"):
        out["route"] = str(route["name"])
    return out, notes


def progress(var_root, settings=None, n: int = 6) -> Progress:
    hive = hive_from(settings)
    data = load(hive)
    # YOUR OWN ROUTE, when one is picked (G10): its base colour, then its changes
    name = str((settings.get("progression.plan") if settings is not None else "") or "")
    route = load_route(name) if name.strip() else {}
    if route:
        base = str(route.get("base") or hive).lower()
        hive = base if base in HIVES else hive
        data, _notes = customise(load(hive), route)
    acct = account_from_files(var_root, settings)
    stage = current_stage(acct, data, hive)
    nxt = next_goals(acct, n, data, stage)
    checked: list = []
    asked = questions(acct, data, nxt[:3], var_root, checked)
    return Progress(hive, stage, nxt, asked, acct, checked)
