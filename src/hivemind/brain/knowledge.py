"""What the bot knows about the game, in a form a small model can use.

The owner's ask: "like pathfinding and knowlage and info to grow our bss ai's
brain", and before that "it needs to understand the whole game like BSS wiki
and metas and redit pages and progression guides".

THE CONSTRAINT THAT SHAPES ALL OF THIS. The local model runs with a 4096-token
context and an image already fills a large part of it. A wiki dump is not an
option, and neither is "everything we know" -- what fits is a few hundred
tokens of the facts that change the decision being made RIGHT NOW. So this
does not expose the knowledge base; it renders small briefings from it, one
per kind of question.

WHY THIS IS NOT THE MODEL'S OWN KNOWLEDGE. qwen2.5vl:7b has read the internet
and will happily answer questions about Bee Swarm Simulator. MEASURED, though:
asked what it could see on a real frame with no context it said "a screenshot
from a video game... possibly a beekeeping simulation". Its game knowledge is
vague where this needs to be exact, and a plausible-sounding wrong fact is
worse here than no fact -- it would be acted on. Everything in `data/knowledge`
is quoted from the wiki with a URL, so a briefing is a citation rather than a
recollection.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

from ..datapaths import data


@lru_cache(maxsize=4)
def _load(name: str) -> dict:
    path = Path(data("knowledge", name))
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def world() -> dict:
    return _load("world.yaml")


def learned() -> list[dict]:
    """Facts this bot established by playing, newest last."""
    return list(_load("learned.yaml").get("learned", []))


def remember(fact: str, evidence: str, confidence: str = "measured",
             when: str | None = None) -> bool:
    """Write a new fact into the bot's own knowledge. True if it was added.

    THIS IS THE POINT OF THE WHOLE MODULE. A bot that discovers something and
    writes it into a code comment has not learned anything -- the model that
    needs it never reads code. Appending it here puts it in the next briefing.

    `evidence` is required and is not decoration: an entry without it is a
    rumour, and a rumour in a decision prompt is worse than a gap, because it
    gets acted on. Duplicates are refused so a loop cannot fill the file.
    """
    import datetime
    fact = " ".join(str(fact).split())
    evidence = " ".join(str(evidence).split())
    if not fact or not evidence:
        return False
    if any(" ".join(str(e.get("fact", "")).split()) == fact for e in learned()):
        return False
    path = Path(data("knowledge", "learned.yaml"))
    entry = {
        "fact": fact,
        "evidence": evidence,
        "when": when or datetime.date.today().isoformat(),
        "confidence": confidence,
    }
    try:
        current = _load("learned.yaml") or {}
        current.setdefault("learned", []).append(entry)
        path.write_text(yaml.safe_dump(current, sort_keys=False,
                                       allow_unicode=True, width=88))
    except (OSError, yaml.YAMLError):
        return False
    _load.cache_clear()
    return True


def for_playing() -> str:
    """Everything the bot has learned for itself, as a briefing.

    Measured facts only. An entry marked anything else is kept in the file
    for a human to read but is not put in front of the model, because the
    model cannot weigh confidence and will treat every line as true.
    """
    lines: list[str] = []
    facts = [e for e in learned() if e.get("confidence") == "measured"]
    if facts:
        lines.append("WHAT YOU HAVE LEARNED PLAYING THIS GAME:")
        lines += [f"- {e['fact']}" for e in facts]
    if RULES:
        if lines:
            lines.append("")
        lines.append("RULES OF THIS GAME THAT CHANGE WHAT YOU SHOULD DO:")
        lines += [f"- {r}" for r in RULES]
    return "\n".join(lines)


def progression() -> dict:
    return _load("progression.yaml")


def economy() -> dict:
    return _load("economy.yaml")


def quests() -> dict:
    return _load("quests.yaml")


def machines() -> dict:
    return _load("machines.yaml")


def items() -> dict:
    return _load("items.yaml")


def tickets() -> dict:
    return _load("tickets.yaml")


def beequips() -> dict:
    """Beequip facts + per-hive-colour rankings (brain/beequips reads it)."""
    return _load("beequips.yaml")


def blue_hive_plan() -> dict:
    """The target blue hive and the order to build it in."""
    return _load("blue_hive_plan.yaml")


# THE PLAYBOOK (data/knowledge/playbook.yaml): how a strong player plays, as
# rules the bot either FOLLOWS (code named in `followed_by`) or only KNOWS.
TAUGHT = ("followed", "known", "needs_a_look")


def playbook(topic: str | None = None, taught: str | None = None) -> list[dict]:
    """The playbook's rules, optionally one topic's or one `taught` kind's."""
    rules = [r for r in (_load("playbook.yaml").get("rules") or [])
             if isinstance(r, dict)]
    return [r for r in rules
            if (topic is None or r.get("topic") == topic)
            and (taught is None or r.get("taught") == taught)]


def playbook_rule(rule_id: str) -> dict:
    """One rule by its id, or {}."""
    return next((r for r in playbook() if r.get("id") == rule_id), {})


def playbook_briefing(topic: str, limit: int = 4) -> str:
    """A few of one topic's rules, for the model's small context: the ones
    the bot follows first, each one line."""
    rules = sorted(playbook(topic), key=lambda r: TAUGHT.index(r.get("taught"))
                   if r.get("taught") in TAUGHT else len(TAUGHT))[:limit]
    return "\n".join(f"- {' '.join(str(r.get('says', '')).split())}" for r in rules)


def mistakes() -> dict:
    """Actions that cannot be undone. See data/knowledge/mistakes.yaml."""
    return _load("mistakes.yaml")


def irreversible() -> list[str]:
    """The short list of things the bot must never do on its own."""
    return [str(e.get("action", "")) for e in
            (mistakes().get("never_without_a_person") or [])]


# THE ALT READS ITS OWN ACCOUNT FILE (HIVEMIND_ROLE=alt, tools/alt). MEASURED
# 2026-10-13 19:15-19:25: /opt/hivemind-alt shipped the main's account.yaml (34
# bees, 422 tickets, the main's badges), `account()` read it, and the alt's
# MORNING.md said "next is the Porcelain Dipper" -- which the alt owns (the
# owner, 2026-10-13). The main's file and name are unchanged.
ACCOUNT_FILE = ("account_alt.yaml" if os.environ.get("HIVEMIND_ROLE") == "alt"
                else "account.yaml")


def account_path() -> Path:
    """THIS PLAYER's account file. OWNER 2026-10-20 ("dont ship my progress"):
    the copy in data/knowledge ships to every install and the public repo as a
    blank new-player template; a player's real one lives in their config dir
    (~/.config/hivemind, %LOCALAPPDATA%\\Hivemind) and wins when present."""
    from ..datapaths import config_dir
    own = config_dir() / ACCOUNT_FILE
    return own if own.exists() else Path(data("knowledge", ACCOUNT_FILE))


@lru_cache(maxsize=2)
def _load_account(path: str) -> dict:
    try:
        return yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def account() -> dict:
    """What is true of this account, as opposed to the game."""
    return _load_account(str(account_path()))


def standing():
    """The account as a `brain.progress.Standing`, so the ladder does not have
    to be handed literals every time it is asked a question."""
    from .progress import Standing
    data = account()
    hive = data.get("hive") or {}
    tools = data.get("tools") or {}
    # `bees` is the real count read off the bees menu; `bees_proved_by_
    # measurement` is the floor the bot inferred from the reward feed. Prefer
    # the real one, fall back to the inference, and never invent a number.
    bees = hive.get("bees")
    if not isinstance(bees, int):
        bees = hive.get("bees_proved_by_measurement")
    return Standing(honey=None,
                    bees=int(bees) if isinstance(bees, int) else None,
                    tool=tools.get("holding"),
                    colour=hive.get("colour"))


def bees() -> dict:
    return _load("bees.yaml")


# THE RULES THAT CHANGE A DECISION, as opposed to the tables that inform one.
#
# `for_playing` goes into EVERY prompt and the model runs on a 4,096-token
# context, so this is deliberately short. A table of twenty tool prices would
# crowd out the screenshot; a rule that stops the bot destroying a Legendary
# bee is worth its twenty tokens every single time.
#
# Each line is sourced from data/knowledge/*.yaml, which carry the citations.
RULES = (
    "Royal Jelly is a REROLL, not an upgrade: the odds ignore what the bee "
    "already was, so never use it on anything above Rare.",
    "An empty hive slot is worth more than a better bee in a full one. Buy "
    "eggs to fill slots before rerolling anything.",
    "A red or blue bee gets +50% pollen from a flower of its own colour, so a "
    "colour-committed hive should camp fields leaning that way.",
    "Harvesting a planter degrades its field, always by at least an hour and "
    "up to a 48-hour cap, which slows everything planted there afterwards.",
    "Most dispensers grant haste, and haste makes a blind timed walk overshoot. "
    "Do not use one immediately before walking a recorded route.",
    "A death empties the whole backpack. Convert before travelling anywhere "
    "guarded while carrying pollen worth keeping.",
    "Science Bear's Translator line and Spirit Bear's line are the only "
    "questlines actually required to progress.",
    "A blue hive runs on bubbles and balloons: Tadpoles make bubbles, Buoyants "
    "make balloons that STORE pollen, and the Pop Star amulet passive scales "
    "with bubbles popped. That is why those three go together.",
    "The bee that scales a blue hive is the DIAMOND, not a blue bee: +50% "
    "Honey at Hive each when converting. Never run Shy, Lion, Frosty or "
    "Cobalt — a Diamond beats them in that slot.",
    "Polar Bear quests give 1.05x max bee energy each with no cap. Below 500 "
    "completions is 'really bad' and 1500 is the minimum useful total, so "
    "grinding them is the single most valuable repeatable job there is.",
    "Never do anything irreversible on your own -- jellying a non-Basic bee, "
    "spending a first Spirit Petal, rerolling an amulet. Recommend it and let "
    "the owner decide.",
)


def rules() -> list[str]:
    """The short list of things that change what the bot should do."""
    return list(RULES)


def safe_fields() -> list[str]:
    """Fields with nothing in them that attacks a player who cannot fight.

    This is the single most valuable fact the knowledge base holds. A death
    empties the entire backpack, so for this bot expected honey is not
    pollen-per-hour, it is pollen-per-hour times the chance of getting home
    with it.
    """
    fields = world().get("fields", {})
    # `is True` on purpose. `safe: null` means the field's page simply does
    # not mention a guard, which is not the same as saying there is none --
    # two pages say "There are no mobs that protect this field" outright, so
    # silence elsewhere is unverified. Truthiness would quietly promote
    # "nobody checked" to "safe", and this bot dies for that mistake.
    return sorted(name for name, f in fields.items() if f.get("safe") is True)


def dangers(field: str) -> list[str]:
    return list(world().get("fields", {}).get(field, {}).get("mobs", []))


def for_navigation(goal: str) -> str:
    """A briefing for "which way should I walk?".

    Only the landmarks, because that is the whole question: the model is
    looking at one frame and deciding a direction, and what helps is knowing
    what its destination LOOKS like.
    """
    marks = world().get("landmarks", {})
    if not marks:
        return ""
    lines = ["WHAT THE PLACES LOOK LIKE:"]
    for name, mark in marks.items():
        look = " ".join(str(mark.get("look_for", "")).split())
        if look:
            lines.append(f"- {name.replace('_', ' ')}: {look}")
        warning = " ".join(str(mark.get("warning", "")).split())
        if warning:
            lines.append(f"  CAUTION: {warning}")
    return "\n".join(lines)


def for_field_choice() -> str:
    """A briefing for "where should I farm?"."""
    fields = world().get("fields", {})
    if not fields:
        return ""
    lines = ["FIELDS, and whether anything there attacks you:"]
    for name, f in sorted(fields.items(),
                          key=lambda kv: (kv[1].get("safe") is not True,
                                          kv[0])):
        safe = f.get("safe")
        mobs = ", ".join(f.get("mobs", [])) or (
            "nothing" if safe is True else "unrecorded")
        mark = ("  <- SAFE" if safe is True
                else "  <- UNVERIFIED" if safe is None else "")
        lines.append(f"- {name}: {f.get('flowers', '?')} flowers, "
                     f"needs {f.get('bees_required', '?')} bees, "
                     f"guarded by {mobs}{mark}")
    lines.append("Dying empties the whole backpack, so a safe field that "
                 "banks its pollen beats a rich one that loses it.")
    return "\n".join(lines)


def describe() -> str:
    """One line for a human, about what the bot actually knows."""
    fields = world().get("fields", {})
    if not fields:
        return "no knowledge loaded"
    return (f"{len(fields)} fields, {len(world().get('landmarks', {}))} "
            f"landmarks, safe fields: {', '.join(safe_fields()) or 'none'}")
