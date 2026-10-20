"""What each open quest step is worth, in honey (ROADMAP B20, step 2).

WHY. The owner, 2026-10-21: "we need the ai to be really smart". The errand
after a convert ran in a fixed order and every quest counted the same; the
wiki's rewards (data/knowledge/quest_rewards.yaml, read 2026-10-21) say they
are not: a Polar Bear quest pays 85,000-260,000 honey -- seconds of gathering
at the bot's ~177M/h -- while Spirit Bear's pay 25M to 10B and Black Bear's
Variety Fetcher 2 pays 125M. This module prices them so a planner can choose.

HOW. A quest's reward is priced in honey (honey 1, a ticket and a Royal Jelly
at brain/value / brain/buyer's prices); anything else it pays (eggs, extracts,
Star Jelly, treats...) is LISTED, not priced, so the honey is a lower bound.
Each unfinished step gets the reward times its share of the work left: a step
half done in a quest with two such steps carries a third of the reward. The
last step of a nearly done quest is worth the most -- finish what is almost
done. The steps' own progress is read the way questneeds reads it (the same
`_target` / `_progress`, so an OCR slip is corrected the same way).

READ-ONLY: nothing here walks, clicks or chooses. ponytail: the work-left
share treats every step's remaining fraction as equal effort; a measured
seconds-per-unit per step kind is the upgrade.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import questneeds

# HONEY A UNIT. A ticket as brain/value.PRICES; a Royal Jelly at the Royal
# Jelly Shop's planned cap (brain/buyer.JELLY_PRICE_PLANNED). Nothing else is
# priced here: a guess would steer the bot.
PRICES = {"honey": 1.0, "tickets": 100_000.0, "royal_jelly": 1_000_000.0}
NUMBER = re.compile(r"\d[\d,]*")
# A PERMANENT STAT REWARD IS PRICED, NOT RANKED FIRST. Polar Power: +5% max
# bee energy a stack, permanent, no cap (wiki Polar Bear rev 447913; Buffs &
# Debuffs). Ranked first whatever its honey (2026-10-21 17:10, after the owner's
# "polar power is really good"), a ~150k quest beat Black Bear's 125M -- too
# strong (research 2026-10-21 21:20). Each stack is worth less than the last:
# ~+0.56% honey/h at 0 stacks, +0.16% at 100, +0.07% at 200 (the research's
# model: bees awake A/(A+30) s, A0 ~200 s; players report ~50 stacks mid-game,
# 100-200 late). ESTIMATE, not measured: at ~230M honey/h over a 24 bot-hour
# horizon that is ~9M a stack at 100, ~4M at 200; ITEM_PRICES takes 5M.
# ponytail: one flat price; read the stack count off the buff icon and price
# by 1.5*A0/(A0(1+0.05n)+30)^2 once the count is read.
ITEM_PRICES = {"Polar Power": 5_000_000.0}


@dataclass
class StepValue:
    line: str
    left: float                     # 0..1 of this step still to do
    honey: float                    # its share of the quest's priced reward


@dataclass
class QuestValue:
    name: str                       # as the menu reads it, "Polar Bear: Scorpion Salad"
    giver: str
    honey: float | None             # the priced reward (a lower bound); None: not on file
    unpriced: list = field(default_factory=list)     # "1 Star Jelly", "10000 Treat"
    steps: list = field(default_factory=list)        # unfinished StepValue rows

    def describe(self) -> str:
        if self.honey is None:
            return f"{self.name}: reward not on file"
        extra = f" + {', '.join(self.unpriced[:3])}" if self.unpriced else ""
        return f"{self.name}: ≥{_short(self.honey)} honey{extra}"


def _short(n: float) -> str:
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= size:
            return f"{n / size:.3g}{unit}"
    return f"{n:,.0f}"


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def load(path: Path | None = None) -> dict:
    """{name key: (giver, rewards dict)} from quest_rewards.yaml; {} unread."""
    import yaml
    from ..datapaths import data
    try:
        body = yaml.safe_load((path or data("knowledge", "quest_rewards.yaml")).read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}
    out = {}
    for giver, block in body.items():
        for q in (block or {}).get("quests") or []:
            if isinstance(q, dict) and q.get("name"):
                for part in str(q["name"]).split(" / "):        # "A / B" alternative names
                    out.setdefault(_key(part), (giver, q.get("rewards") or {}))
    return out


def priced(rewards: dict) -> tuple[float, list]:
    """(honey lower bound, the unpriced goods as text)."""
    honey, unpriced = 0.0, []
    for k, v in (rewards or {}).items():
        if k == "items":
            for item, n in (v or {}).items():
                if "on accept" in item:                 # paid when taken, not at hand-in
                    continue
                if item in ITEM_PRICES:
                    honey += ITEM_PRICES[item] * float(n or 0)
                else:
                    unpriced.append(f"{n} {item}")
        elif k in PRICES:
            honey += PRICES[k] * float(v or 0)
        elif v:
            unpriced.append(f"{v} {k.replace('_', ' ').title()}")
    return honey, unpriced


def step_left(line: str) -> float:
    """How much of a requirement line is still to do, 0..1 (0: complete)."""
    m = NUMBER.search(line)
    stated = questneeds._number(m.group(0)) if m else None
    target = questneeds._target(line, stated)
    if not target:
        return 0.0 if questneeds.DONE.search(line) else 1.0
    done = questneeds._progress(line, target)
    return max(0.0, min(1.0, 1.0 - done / float(target)))


def value(quest: dict, table: dict) -> QuestValue:
    """One menu quest ({"name", "requirements"}) priced."""
    name = str(quest.get("name") or "")
    bare = name.split(":", 1)[-1]                   # "Polar Bear: Scorpion Salad" -> "Scorpion Salad"
    hit = table.get(_key(bare)) or table.get(_key(name))
    lines = [str(r) for r in quest.get("requirements") or []]
    lefts = [(ln, step_left(ln)) for ln in lines]
    open_steps = [(ln, f) for ln, f in lefts if f > 0]
    total = sum(f for _ln, f in open_steps)
    if hit is None:
        return QuestValue(name, "", None, [],
                          [StepValue(ln, f, 0.0) for ln, f in open_steps])
    giver, rewards = hit
    honey, unpriced = priced(rewards)
    steps = [StepValue(ln, f, honey * f / total if total else 0.0) for ln, f in open_steps]
    return QuestValue(name, giver, honey, unpriced, steps)


def ranked(quests: list, table: dict | None = None) -> list:
    """Every menu quest priced, the most honey per unit of work left first
    (unpriced last, in menu order); permanent rewards are priced (ITEM_PRICES)."""
    table = load() if table is None else table
    rows = [value(q, table) for q in quests or [] if isinstance(q, dict)]

    def per_work(r: QuestValue) -> float:
        left = sum(s.left for s in r.steps)
        return (r.honey or 0.0) / left if left else (r.honey or 0.0)
    known = sorted((r for r in rows if r.honey is not None), key=per_work, reverse=True)
    return known + [r for r in rows if r.honey is None]


# B20 STEP 3 (SHADOW): FIELDS BY HONEY PLUS QUEST VALUE. A trip ends with the
# bag full whatever the field, so it collects about one bag of pollen; a field
# a quest wants pollen from also earns that step's honey for the pollen it
# counts. Ranked a second: score x honey-per-pollen (gathering) + the quest
# honey for min(bag, owed) over the trip's gathering seconds (bag / rate).
def field_bonus(rows: list) -> dict:
    """{field: (quest honey per pollen, pollen still owed)} from the priced
    steps "Collect N Pollen from the X Field/Patch"."""
    out: dict = {}
    for r in rows:
        for st in r.steps:
            m = questneeds.FROM_FIELD.search(st.line)
            if not m or st.honey <= 0:
                continue
            field = "_".join(m.group(2).lower().split())
            target = questneeds._target(st.line, questneeds._number(m.group(1)))
            owed = max(0, (target or 0) - questneeds._progress(st.line, target or 0))
            if owed <= 0:
                continue
            hpp, was = out.get(field, (0.0, 0))
            out[field] = (hpp + st.honey / owed, max(was, owed))
    return out


def honey_per_pollen(path, last: int = 30, default: float = 1.5) -> float:
    """The median honey a pollen made over the last converted trips
    (var/trips.jsonl), `default` with none."""
    import json
    import statistics
    try:
        lines = Path(path).read_text().splitlines()[-400:]
    except OSError:
        return default
    ratios = []
    for ln in reversed(lines):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("converted") and (d.get("pollen") or 0) > 0 and (d.get("honey") or 0) > 0:
            ratios.append(d["honey"] / d["pollen"])
        if len(ratios) >= last:
            break
    return statistics.median(ratios) if ratios else default


def shadow_rank(alts, bonus: dict, capacity: float, hpp: float) -> list:
    """[(field, honey a second, of which quest)] for the reachable candidates
    (decide.Planner alternatives: .field .score .rate .reachable), best first."""
    out = []
    for a in alts or []:
        rate, score = float(getattr(a, "rate", 0) or 0), float(getattr(a, "score", 0) or 0)
        if not getattr(a, "reachable", False) or rate <= 0 or score <= 0:
            continue
        quest = 0.0
        if a.field in bonus and capacity > 0:
            q_hpp, owed = bonus[a.field]
            quest = min(capacity, owed) * q_hpp / (capacity / rate)
        out.append((a.field, score * hpp + quest, quest))
    return sorted(out, key=lambda t: t[1], reverse=True)


if __name__ == "__main__":                      # a look at the live menu read
    import json
    import sys
    path = (Path(sys.argv[1]) if len(sys.argv) > 1
            else Path(__file__).resolve().parents[3] / "var" / "quests.json")
    for r in ranked(json.loads(path.read_text()).get("quests") or []):
        print(r.describe())
        for s in r.steps:
            print(f"    {_short(s.honey):>8}  {s.left:4.0%} left  {s.line[:70]}")
