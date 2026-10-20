"""The bot's own reasoning, said as a thought: what it wants, what it is doing, why.

THE OWNER, 2026-09-29: it should sound intelligent and talk about what it is
thinking, doing and wanting, rather than only cracking jokes.

EVERY THOUGHT IS ONE OF THE BOT'S OWN LINES, SAID PLAINER. Each rule below reads
one shape of a line run_farm narrates (a telemetry Log, which the stream hears),
in the shapes MEASURED in var/night/run-532..536 (2026-09-28/29), and says only
what that line says -- its goal, the errand it chose and what for, the route it
took and on what record, the booster it judged worth the detour, the buff it is
waiting out. A line of any other shape says nothing: no thought is guessed.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass


def amount(text) -> str:
    """"6,108,098" -> "6.1 million", "55,000" -> "55 thousand", "900" -> "900"."""
    try:
        n = int(str(text).replace(",", "").strip())
    except ValueError:
        return str(text)
    for size, word in ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand")):
        if n >= size:
            value = n / size
            shown = f"{value:.1f}".rstrip("0").rstrip(".") if value < 100 else f"{value:.0f}"
            return f"{shown} {word}"
    return str(n)


def place(text: str) -> str:
    """"pine tree" -> "Pine Tree", "blue_flower" -> "Blue Flower"."""
    return " ".join(w.capitalize() for w in str(text).replace("_", " ").split())


def people(text: str) -> str:
    """"brown bear, panda bear" -> "Brown Bear and Panda Bear"."""
    names = [place(p) for p in str(text).split(",") if p.strip()]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def needs(text: str) -> str:
    """"Oil 44/50, Enzymes 20/25" -> "Oil, 44 of 50, and Enzymes, 20 of 25"."""
    parts = []
    for bit in str(text).split(","):
        m = re.match(r"\s*(.+?)\s+(\d+)/(\d+)\s*$", bit)
        parts.append(f"{m.group(1)}, {m.group(2)} of {m.group(3)}" if m else bit.strip())
    parts = [p for p in parts if p]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + ", and " + parts[-1]


@dataclass
class Thought:
    kind: str          # which rule, for its own pace
    text: str
    decision: bool     # a decision (said promptly) or a detail (said if there is room)
    repeat_s: float    # the same kind is not said again sooner


def _goal_next(m, rng, whole=''):
    goal, short = m["goal"], amount(m["short"])
    n = m["n"].rstrip("0").rstrip(".") if "." in m["n"] else m["n"]
    time_words = (f"{n} minutes" if m["unit"] == "min" else
                  f"{n} hour" + ("" if n == "1" else "s"))
    head = rng.choice([
        f"My next goal is the {goal}. I'm about {short} honey short, around {time_words} of farming.",
        f"Working towards the {goal}: about {short} honey to go, roughly {time_words}.",
    ])
    return head + (f" I still need {needs(m['needs'])} for it." if m["needs"] else "")


def _goal_ready(m, rng, whole=''):
    return (f"I've got the honey for the {m['goal']}! It still needs {needs(m['needs'])}.")


def _bug_run(m, rng, whole=''):
    return rng.choice([
        f"My bag's empty, so it's hunting time. A {m['mob']} should be back in {place(m['field'])}, "
        f"worth about {amount(m['worth'])} honey.",
        f"Bag's empty. Time to hunt: a {m['mob']} is due in {place(m['field'])}.",
    ])


def _errand_use(m, rng, whole=''):
    what = re.split(r" \(| —|, picked", m["what"])[0].strip()
    return rng.choice([
        f"My bag's empty, so I'm heading to the {place(m['place'])}. It's ready again, for {what}.",
        f"Quick errand while the bag's empty: the {place(m['place'])}, for {what}.",
    ])


def _quest_handin(m, rng, whole=''):
    # The line is the errand QUEUE's order, not the walk: a giver with three
    # misses in a row rests for 12 h (run_farm GIVER_MISS_REST_SECONDS) and is
    # skipped while the queue still names it first -- Panda Bear, 2026-09-28
    # 21:04 to 09:06. So it says what is true either way.
    return rng.choice([
        f"I've finished a quest for {people(m['givers'])}. It's waiting to be handed in.",
        f"Quest finished! {people(m['givers'])} has a reward waiting for me.",
    ])


def _route_choice(m, rng, whole=''):
    field = place(m["field"])
    how = "the cannon" if m["how"] == "flying" else "the walk"
    taken = m["f"] if m["how"] == "flying" else m["w"]
    if taken == "never judged yet":
        return (f"Trying {how} to {field} for the first time. I haven't judged that "
                f"route yet, so it gets its chance.")
    walk = (f"{m['wg']} of its last {m['wn']}" if m["wg"] is not None
            else "never been tried")
    fly = (f"{m['fg']} of its last {m['fn']}" if m["fg"] is not None
           else "never been tried")
    if "quarantined" in whole and m["how"] == "flying":
        return (f"Taking the cannon to {field}. The walk there landed only {walk}, "
                f"and the cannon {fly}.")
    if "draw" in whole:
        return (f"{'Flying' if m['how'] == 'flying' else 'Walking'} to {field} this time. "
                f"I pick routes by their track record: the walk has landed {walk}, "
                f"the cannon {fly}.")
    return f"Going to {field} by {how}: the walk has landed {walk}, the cannon {fly}."


def _buff_wait(m, rng, whole=''):
    buff = m["buff"].strip()
    buff = re.sub(r"^an? ", "my ", buff) if re.match(r"^an? ", buff) else f"my {buff}"
    return (f"Waiting about {m['s']} seconds for {buff} to wear off. "
            f"My routes are timed for my normal speed.")


def _booster(m, rng, whole=''):
    if m["verdict"] == "using it":
        return (f"The {place(m['booster'])} boosts {place(m['field'])}, my next field, so I'm "
                f"stopping there first. It's worth about {m['gain']} seconds of gathering "
                f"for a {m['detour']} second detour.")
    return (f"The {place(m['booster'])} could boost {place(m['field'])}, but it isn't worth "
            f"the walk this time.")


def _bug_empty(m, rng, whole=''):
    return rng.choice([f"Nothing to fight in {place(m['field'])} right now. Back to work!",
                       f"{place(m['field'])} is quiet. No bugs to squash yet."])


def _learning(m, rng, whole=''):
    how = "cannon" if m["via"] else "walk"
    where = (f"home from {place(m['target'])}" if m["way"] == "home"
             else f"to {place(m['target'])}")
    if m["outcome"] == "landed":
        return rng.choice([
            f"The {how} {where} worked again. That's {m['g']} of its last {m['n']}. "
            f"I'm learning which routes I can trust.",
            f"Another good landing: the {how} {where} is {m['g']} for {m['n']} lately.",
        ])
    return (f"The {how} {where} didn't get me there. It's landed {m['g']} of its last "
            f"{m['n']} now, so I'll trust it a little less.")


def _respawn(m, rng, whole=''):
    return "Respawning to get home fast. My bag's empty, so it costs me nothing."


# (kind, the line's shape, decision, repeat_s, how it is said)
RULES = [
    ("goal", re.compile(
        r"^goals: next is the (?P<goal>.+?) — (?P<short>[\d,]+) honey short, about "
        r"(?P<n>[\d.]+) (?P<unit>min|h) of farming at [\d,]+/h(?:; also needs (?P<needs>[^;]+))?"),
     True, 900.0, _goal_next),
    ("goal", re.compile(
        r"^goals: the honey for the (?P<goal>.+?) is there \([\d,]+\); still needed: "
        r"(?P<needs>[^;]+)"),
     True, 1800.0, _goal_ready),
    ("errand", re.compile(
        r"^the backpack is empty and we are on our own pad — a bug run: (?P<mob>.+?) due in "
        r"(?P<field>.+?) — drops worth about (?P<worth>[\d,]+) honey"),
     True, 120.0, _bug_run),
    ("errand", re.compile(
        r"^the backpack is empty and we are on our own pad — going to the (?P<place>.+?) to "
        r"use it \(every [^)]+\), about \d+s there, for (?P<what>.+)$"),
     True, 120.0, _errand_use),
    ("handin", re.compile(r"^a finished quest is waiting to be handed in at (?P<givers>.+?) — going there"),
     False, 1800.0, _quest_handin),
    ("route", re.compile(
        r"^(?P<how>flying|walking) to (?P<field>.+?): .*?the walk "
        r"(?P<w>landed (?P<wg>\d+) of its last (?P<wn>\d+)|never judged yet).*?the flight "
        r"(?P<f>landed (?P<fg>\d+) of its last (?P<fn>\d+)|never judged yet)"),
     True, 300.0, _route_choice),
    ("booster", re.compile(
        r"^booster: the next trip goes to (?P<field>.+?) and the (?P<booster>.+?) boosts it — "
        r".*?worth (?P<gain>\d+)s of gathering against a (?P<detour>\d+)s detour, so "
        r"(?P<verdict>using it|not worth the walk)"),
     True, 300.0, _booster),
    ("buff", re.compile(r"^waiting out (?P<buff>.+?) \(about (?P<s>\d+)s\) before "),
     False, 300.0, _buff_wait),
    ("bugrun", re.compile(r"^bug run done in \d+s \((?:walked|flew)\) — (?P<field>.+?): no mob health bar"),
     False, 300.0, _bug_empty),
    ("learning", re.compile(
        r"^skills: natro_(?P<way>out|home)_(?P<target>[a-z_]+?)(?P<via>_via_red_cannon)? "
        r"(?P<outcome>landed|elsewhere|missed) — now landed (?P<g>\d+) of its last (?P<n>\d+)"),
     False, 600.0, _learning),
    ("respawn", re.compile(r"^respawning to get home after the errand"),
     False, 900.0, _respawn),
]


def think(message: str, rng=random) -> Thought | None:
    """The thought one of the bot's lines holds, or None."""
    text = " ".join(str(message or "").split())
    for kind, shape, decision, repeat_s, say in RULES:
        m = shape.search(text)
        if m:
            try:
                return Thought(kind=kind, text=say(m, rng, text), decision=decision,
                               repeat_s=repeat_s)
            except (KeyError, IndexError, TypeError):
                return None
    return None
