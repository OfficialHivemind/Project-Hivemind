"""The goal graph: what the bot wants, what blocks it, and in what order.

THE OWNER ASKED TO SEE IT: "also i want its goals in the gui in a beautifull
looking way mapped out in detal", "the ais brain thoughts in a kinda web and
goals mapped", "and prioritys".

WHERE THE GOALS COME FROM, AND WHY THAT CHANGED ON 2026-09-21. They come from
`data/knowledge/blue_hive_plan.yaml`, which now carries the stage checklists of
the owner's own guide, quoted. Nothing else is drawn as a goal.

That is a correction. This module used to draw TWO plans side by side: a
hand-written paraphrase of the guide down the middle, and a ladder built from
the Bee Swarm wiki off to the right. The wiki ladder proposed the Porcelain
Dipper at 150,000,000 honey, a Basic Egg at "1,000 honey", a hive slot and the
Coconut Field -- and not one of those four appears anywhere in the guide. The
owner looked at it and said "the goals seem weird ... the goals should be this
guide". He was right. A goal web that answers a question nobody asked is worse
than no goal web, because it is confidently wrong in a place he is looking.

So the ladder is still here, and it is still useful, but it has been demoted to
what it is actually good at: PRICES AND MECHANISMS. "48 Bees" is the guide's
goal; "a Basic Egg is how bee count goes up, and it costs from 1,000 honey
climbing to 10,000,000" is the ladder's contribution, and it now hangs UNDER
the guide's goal instead of competing with it. A ladder goal that serves no
guide goal is not drawn at all.

QUESTS ARE GOALS TOO, and the owner asked for that directly: "the quests arnt
being picked up on, it should read what quests i have and it should read and
see what i have so it knows what goals to set next". The quest menu reader
already works. What was missing was anywhere for its answer to go. Outstanding
quest requirements are now drawn as their own goals, marked with whether the
bot can actually act on each one -- a pollen requirement in a field it can
reach is actionable; "Defeat 15 Scorpions" is not, and says so.

STATES, and they are deliberately few:

    doing      the decision the bot would take right now
    ready      the bot can work on this today
    blocked    something must happen first, and the node says what
    unknown    we cannot even check this -- the node says why
    done       already true of this account
    skip       a deliberate warning: do NOT do this, and why

PRIORITY is position in the guide, not a score. A number invented to sort goals
would look authoritative and mean nothing.

WHAT IT REFUSES TO DO. It never states a price it is not sure of as though it
were sure. `Node.money` renders a floor as a floor: the Basic Egg used to be
drawn as "1,000 honey" in green, next to the word "ready", which reads as an
instruction to go and buy one -- when 1,000 is merely the bottom of a curve
that climbs to 10,000,000 and the price of the NEXT egg can only be read in the
shop. The knowledge base always knew that; this module was throwing it away.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field

DOING, READY, BLOCKED, UNKNOWN, DONE, SKIP = (
    "doing", "ready", "blocked", "unknown", "done", "skip")


@dataclass
class Node:
    """One thing the bot wants, and where it stands."""
    key: str
    label: str
    state: str = BLOCKED
    kind: str = "goal"            # goal | mechanism | quest | target | warning
    detail: str = ""
    why: str = ""
    cost: int | None = None
    cost_to: int | None = None    # set when `cost` is only the FLOOR of a range
    shortfall: int | None = None
    progress: str = ""            # "26 / 48", straight from the game where known
    priority: int = 99

    @property
    def money(self) -> str:
        """The price, said only as precisely as it is actually known.

        A range is never collapsed to its floor. See the module docstring for
        the Basic Egg, which is the reason this property exists at all.
        """
        if self.cost is None:
            return ""
        if self.cost_to is not None and self.cost_to != self.cost:
            return f"from {self.cost:,} honey, up to {self.cost_to:,}"
        if self.shortfall:
            return f"{self.cost:,} honey — short {self.shortfall:,}"
        return f"{self.cost:,} honey"


@dataclass
class Edge:
    """`before` has to happen before `after`, and the reason is kept."""
    before: str
    after: str
    why: str = ""


@dataclass
class GoalMap:
    nodes: list[Node] = dc_field(default_factory=list)
    edges: list[Edge] = dc_field(default_factory=list)
    headline: str = ""
    stage: str = ""

    def node(self, key: str) -> Node | None:
        return next((n for n in self.nodes if n.key == key), None)

    def ordered(self) -> list[Node]:
        return sorted(self.nodes, key=lambda n: (n.priority, n.label))

    def describe(self) -> str:
        lines = [self.headline] if self.headline else []
        if self.stage:
            lines.append(self.stage)
        for n in self.ordered():
            lines.append(f"  [{n.state:<7}] {n.label}"
                         + (f" — {n.progress}" if n.progress else "")
                         + (f" — {n.money}" if n.money else "")
                         + (f" — {n.why}" if n.why else ""))
        return "\n".join(lines)


def _slug(text: str, limit: int = 40) -> str:
    keep = [c if c.isalnum() else "_" for c in str(text).strip().lower()]
    return "".join(keep).strip("_")[:limit] or "goal"


def current_stage(plan: dict, standing) -> dict:
    """Which stage of the guide this account is in.

    Decided by BEE COUNT, because it is the only stage gate the bot can read
    for itself -- level, gifting and amulet rolls are all invisible to it. A
    stage can therefore be ruled OUT by bee count but never confirmed complete,
    so this returns the earliest stage whose bee gate is not yet met. With no
    bee count at all it falls back to the stage recorded in the plan.
    """
    stages = plan.get("stages") or []
    if not stages:
        return {}
    bees = getattr(standing, "bees", None)
    if bees is None:
        recorded = int(((plan.get("standing") or {}).get("stage")) or 1)
        for stage in stages:
            if int(stage.get("id", 0)) == recorded:
                return stage
        return stages[0]
    for stage in stages:
        for item in stage.get("progression") or []:
            if item.get("needs") == "bees" and bees < int(item.get("target", 0)):
                return stage
    return stages[-1]


def build(ladder, standing, plan: dict | None = None, decision=None,
          quests=None) -> GoalMap:
    """Assemble the graph from the guide, the ladder and the live readings.

    `quests` is a `brain.questneeds.Needs`, or None when the quest menu has not
    been read. It is optional because a goal web that cannot be drawn without a
    successful quest read would vanish exactly when something went wrong.
    """
    plan = plan or {}
    out = GoalMap()
    seen: set[str] = set()

    def add(key, label, **kw):
        if key in seen:
            return out.node(key)
        seen.add(key)
        node = Node(key=key, label=label, **kw)
        out.nodes.append(node)
        return node

    # ---- what the bot would do this second --------------------------------
    if decision is not None:
        action = getattr(decision, "action", "")
        field = getattr(decision, "field", None)
        label = (f"gather in {str(field).replace('_', ' ')}" if field
                 else str(action))
        add("now", label, kind="goal", state=DOING, priority=-1,
            why=" ".join(str(getattr(decision, "why", "")).split())[:180])
        out.headline = f"right now: {label}"

    # ---- the guide's current stage, which IS the plan ----------------------
    stage = current_stage(plan, standing)
    ladder_goals = {g.name: g for g in (ladder.goals(standing) if ladder else [])}
    used_mechanisms: set[str] = set()

    if stage:
        out.stage = f"{stage.get('name', '')} — {stage.get('comp', '')}".strip(" —")
        add("stage", str(stage.get("name", "this stage")), kind="target",
            state=BLOCKED, priority=0,
            why=" ".join(str(stage.get("say", "")).split())[:180],
            detail=f"target comp: {stage.get('comp') or stage.get('comp_standard') or ''}")

    previous = "stage" if stage else None
    for i, item in enumerate(stage.get("progression") or [], start=1):
        say = str(item.get("say", "")).strip()
        if not say:
            continue
        key = _slug(say)
        state, progress, why = _check(item, standing)
        node = add(key, say, kind="goal", priority=i, state=state,
                   progress=progress, why=why,
                   detail=" ".join(str(item.get("note", "")).split()))
        if previous and node:
            out.edges.append(Edge(previous, key, "comes first"))
        previous = key

        # THE LADDER, DEMOTED TO WHAT IT IS GOOD AT. Only the mechanisms this
        # guide goal actually names, hung underneath it.
        for name in item.get("serves") or []:
            goal = ladder_goals.get(name)
            if goal is None or name in used_mechanisms:
                continue
            used_mechanisms.add(name)
            mech = add(f"how_{name}", goal.name.replace("_", " "),
                       kind="mechanism", priority=i,
                       cost=goal.cost, cost_to=getattr(goal, "cost_to", None),
                       why=" ".join(str(goal.why).split())[:150],
                       detail=str(goal.blocked_by))
            if mech is not None:
                mech.state = _mechanism_state(goal)
                if (mech.state == READY and goal.shortfall is not None):
                    mech.shortfall = goal.shortfall
                out.edges.append(Edge(f"how_{name}", key, "is how"))

    # ---- the tools the guide names, which are not shop purchases ----------
    tools = plan.get("tools") or {}
    named = tools.get("named_by_the_guide") or []
    if named:
        add("tools", "endgame tools: " + ", ".join(
                str(t).replace("_", "-").title() for t in named),
            kind="goal", priority=40, state=UNKNOWN,
            why=" ".join(str(tools.get("say_overall", "")).split())[:170],
            detail="the guide gets these from Bucko and Riley quests and "
                   "material grinding, not from a honey shop — none of them is "
                   "priced here, and the progression itself is an image in the "
                   "document that did not survive the text conversion")

    # ---- where we knowingly disagree with the guide ------------------------
    for name, row in (plan.get("our_disagreements") or {}).items():
        add(f"skip_{name}", name.replace("_", " "), kind="warning",
            priority=45, state=SKIP,
            why=" ".join(str(row.get("verdict", "")).split())[:170],
            detail="guide says: "
                   + " ".join(str(row.get("guide_says", "")).split())[:200])

    # ---- the hive it is all for -------------------------------------------
    base = plan.get("baseline") or {}
    if base.get("comp"):
        add("target", str(base["comp"]), kind="target", state=BLOCKED,
            priority=50, why="the hive this is all for",
            detail=" ".join(str(base.get("say", "")).split())[:200])
        if previous:
            out.edges.append(Edge(previous, "target", "completes the hive"))

    # ---- the quests, which the owner asked to be picked up ----------------
    _add_quests(out, add, quests, standing)
    return out


def _check(item: dict, standing) -> tuple[str, str, str]:
    """Is this checklist item done? Returns (state, progress, why).

    THE HONEST ANSWER IS OFTEN "I CANNOT TELL". Only bee count is readable
    today, so everything else returns UNKNOWN with the reason -- which is very
    different from BLOCKED, and the difference matters: blocked means something
    is in the way, unknown means nobody has looked.
    """
    needs = item.get("needs")
    target = item.get("target")
    if not needs:
        return UNKNOWN, "", "the bot cannot check this for itself"
    have = getattr(standing, str(needs), None)
    if have is None:
        return (UNKNOWN, "",
                f"the bot cannot read your {needs} from any screen yet")
    try:
        have_n, target_n = int(have), int(target)
    except (TypeError, ValueError):
        return UNKNOWN, "", f"no target recorded for {needs}"
    progress = f"{have_n:,} / {target_n:,}"
    if have_n >= target_n:
        return DONE, progress, ""
    return READY, progress, f"{target_n - have_n:,} more {needs} to go"


def _mechanism_state(goal) -> str:
    """A mechanism whose price is a RANGE is never drawn as affordable.

    This is the Basic Egg rule. `cost` is 1,000 and `cost_to` is 10,000,000,
    and the account holds far more than 1,000 -- so the old code called it
    READY and coloured it green. What the account can actually afford depends
    on a price only the shop knows, so the honest state is UNKNOWN and the card
    carries the range.
    """
    if goal.cost is None:
        return UNKNOWN
    if getattr(goal, "cost_to", None) not in (None, goal.cost):
        return UNKNOWN
    if goal.shortfall is None:
        return UNKNOWN
    return READY if goal.shortfall == 0 else BLOCKED


def _add_quests(out: GoalMap, add, quests, standing) -> None:
    """Outstanding quest requirements, as goals, with honest actionability.

    Every requirement is drawn, including the ones the bot cannot do. A quest
    step it cannot touch is exactly the thing the owner needs to see, because
    it is the thing he might do himself -- and hiding it would make the quest
    list look shorter than it is.
    """
    if quests is None:
        return
    proven = set(getattr(standing, "fields_proven", ()) or ())

    for slug, need in (getattr(quests, "fields", {}) or {}).items():
        remaining = max(0, int(need.target) - int(need.done))
        if remaining <= 0:
            continue
        reachable = slug in proven
        add(f"quest_field_{slug}", f"quest: pollen from {slug.replace('_', ' ')}",
            kind="quest", priority=20,
            state=READY if reachable else BLOCKED,
            progress=f"{int(need.done):,} / {int(need.target):,}",
            why=("the bot can reach this field, so it can finish this"
                 if reachable else
                 "NO RECORDED ROUTE to this field — this step cannot move "
                 "until one is walked"),
            detail=f"{remaining:,} more pollen needed")

    for colour, need in (getattr(quests, "pollen", {}) or {}).items():
        remaining = max(0, int(need.target) - int(need.done))
        if remaining <= 0:
            continue
        add(f"quest_colour_{colour}", f"quest: {colour} pollen",
            kind="quest", priority=21, state=READY,
            progress=f"{int(need.done):,} / {int(need.target):,}",
            why="gathering anywhere with that colour on the ground moves this",
            detail=f"{remaining:,} more {colour} pollen needed")

    for i, line in enumerate(getattr(quests, "fights", []) or []):
        if "complete" in str(line).lower():
            continue
        add(f"quest_fight_{i}", f"quest: {line}", kind="quest", priority=22,
            state=BLOCKED,
            why="the bot cannot fight — it cannot see a mob on this client, "
                "and nothing reads the player's own health")

    # TokenNeed objects, not strings (brain/questneeds): `str()` of one was
    # its dataclass repr, and "no token detector" stopped being true when the
    # chase started preferring the kinds a quest wants (run_farm, Kinds.want).
    for i, need in enumerate(getattr(quests, "tokens", []) or []):
        if int(getattr(need, "remaining", 1) or 0) <= 0:
            continue
        label = need.describe() if hasattr(need, "describe") else str(need)
        add(f"quest_token_{i}", f"quest: {label}", kind="quest", priority=23,
            state=READY,
            why="the token chase goes for this kind first while a quest wants "
                "it, if data/knowledge/tokens.yaml knows the kind (the run "
                "log says so at startup)")

    # FINISHED QUESTS ARE FILED UNDER `handed` NOW, not `unread`, and the
    # bot walks to the giver and hands them in (run_farm `hand_in`).
    for i, giver in enumerate(getattr(quests, "ready_to_hand_in", ()) or ()):
        pretty = str(giver).replace("_", " ")
        add(f"quest_turnin_{i}", f"quest: hand in to the {pretty}",
            kind="quest", priority=19, state=READY,
            why="finished and unclaimed — the errand after a convert walks "
                "to the giver and hands it in")
