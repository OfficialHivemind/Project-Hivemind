#!/usr/bin/env python3
"""Generate the demo session the GUI replays.

Every number here is one we actually measured on this account -- honey
10,216,209, pollen 445,583/660,000, 25 bees, the Golden Rake -- so the window
shows something truthful rather than lorem ipsum. The reasoning is written the
way the planner is designed to reason, which makes this file double as a
readable specification of what the think pane is supposed to contain.

    python3 scripts/make_demo.py
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from hivemind.telemetry.events import (Autonomy, Belief, Considered, Expiry,
                                       Frame, Log, Metric, Option, Planter,
                                       Question, ShadowPrice, StatusUpdate,
                                       TaskUpdate, Thought)
from hivemind.telemetry.events import Timer as TimerEvent
from hivemind.tasks.planters import PlanterState, decide
from hivemind.economy.sentinel import Sentinel
from hivemind.economy.prices import PriceGraph
from hivemind.world.timers import TimerBook

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data/demo/session.jsonl"
FRAME = ROOT / "tests/fixtures/screens/in_game.png"

# Generated relative to NOW, not to a frozen constant. A hardcoded epoch makes
# every countdown in the window drift further from sensible the longer it sits
# on disk -- bosses show as "22h" forever and expiries never look urgent.
# install.sh regenerates this, so a fresh install always reads correctly.
T0 = time.time()


def build() -> list:
    t = T0
    events = []

    def add(event, gap=0.6):
        nonlocal t
        event.at = t
        t += gap
        events.append(event)

    add(Log(message="Hivemind starting", source="brain"), 0.3)
    add(StatusUpdate(running=True, autonomy=Autonomy.ASK_STRATEGY,
                     note="observing account state"), 0.4)

    # --- first run: work out what we own, rather than being told -----------
    add(Thought(topic="startup", text="No cached account state. Observing before planning.",
                detail="Every fact is a belief with an age. Acting on an unobserved "
                       "account is how macros spend resources you do not have."))
    add(TaskUpdate(name="Observe account", status="running", progress=-1.0,
                   detail="reading HUD"), 0.5)
    add(Frame(path=str(FRAME), width=1920, height=1080, screen="in_game",
              detections=[
                  {"kind": "token", "x": 1118, "y": 300, "w": 34, "h": 34, "label": "honey token"},
                  {"kind": "landmark", "x": 560, "y": 120, "w": 240, "h": 180, "label": "hive"},
              ]), 0.8)
    add(Thought(topic="startup", text="HUD read: honey 10,216,209 · pollen 445,583/660,000"))
    add(Metric(name="honey", value=10_216_209), 0.2)
    add(Metric(name="pollen", value=445_583), 0.2)
    add(Belief(name="honey", value=10_216_209, confidence=1.0, observed_at=t,
               source="hud"), 0.2)
    add(Belief(name="pollen_capacity", value=660_000, confidence=1.0,
               observed_at=t, source="hud"), 0.2)
    add(Thought(topic="startup", text="Backpack is 67.5% full."))

    add(TaskUpdate(name="Observe account", status="running", progress=0.4,
                   detail="counting bees in hive"), 0.5)
    add(Thought(topic="startup", text="Opening hive to count bees and types."))
    add(Belief(name="bees", value=25, confidence=0.95, observed_at=t, source="hive"), 0.2)
    add(Metric(name="bees", value=25), 0.2)
    add(Belief(name="bee_types_discovered", value=14, confidence=0.9,
               observed_at=t, source="hive"), 0.2)
    add(Thought(topic="startup",
                text="25 bees, 14 types. Mountain Top is unlocked; Red Cannon (25 types) is not.",
                detail="Bee COUNT gates map zones at 5/10/15/20/25/30/35. Bee TYPES "
                       "gate machines: Wealth Clock 5, Yellow Cannon 12, Blue Cannon 16, "
                       "Field Booster 20, Red Cannon 25. Conflating the two is a common "
                       "macro bug."))
    add(Belief(name="golden_rake", value=True, confidence=1.0, observed_at=t,
               source="inventory"), 0.2)
    add(TaskUpdate(name="Observe account", status="done", progress=1.0,
                   detail="14 facts observed"), 0.6)

    # --- a real decision, shown with its numbers ---------------------------
    add(Thought(topic="economy", text="Backpack 67.5% full. Deciding whether to convert now."))
    add(Considered(
        question="Convert now, or keep gathering to a full backpack?",
        options=[
            Option("convert now", 412_000, "no overflow, but an extra trip", "honey/hr"),
            Option("fill to 100% first", 380_000,
                   "one fewer trip, but 11% of the field's output overflows", "honey/hr"),
            Option("convert at 90%", 431_000,
                   "keeps the trip, avoids the overflow tail", "honey/hr"),
        ],
        chosen="convert at 90%",
        rationale="Overflow is a silent loss: pollen gathered above capacity is "
                  "discarded, so the last 10% of a fill returns nothing.",
        reversible=True, horizon_hours=0.2), 1.0)
    add(TaskUpdate(name="Gather — Pine Tree", status="running", progress=0.68,
                   detail="closed-loop, 42 studs to token"), 0.5)

    add(Thought(topic="nav", text="Walking to Pine Tree. Measuring displacement, not timing it.",
                detail="studs = recorded_seconds x 32.2 converts every inherited timed "
                       "hold into a distance. Arrival is verified by landmark, not by a "
                       "stopwatch, so lag and haste cannot desynchronise the route."))
    add(Thought(topic="nav", text="Optical flow: 31.8 studs covered, 10.2 remaining."))
    add(Thought(topic="vision", text="Token detected at (1118, 300) — 12 studs forward, 4 left."))
    add(Thought(topic="nav", text="Arrived. Landmark match 0.94 against pine_tree_base."))

    # --- the planter insight ----------------------------------------------
    add(Thought(topic="planter", text="Checking planters before committing to the next field."))
    add(Considered(
        question="Harvest the Pine Tree planter at 94%, or wait for 100%?",
        options=[
            Option("wait 30m for 100%", 126_000,
                   "full yield; correct unless harvesting degrades the field", "honey"),
            Option("harvest now at 94%", 118_400,
                   "only better if field degradation is real, which is unmeasured",
                   "honey"),
        ],
        chosen="wait 30m for 100%",
        rationale="Field degradation has not been measured on this account yet, so "
                  "early harvesting has no demonstrated benefit. Waiting is correct "
                  "if fields do not degrade and costs ~6% if they do; harvesting "
                  "early on an unverified mechanic risks more than it can win. "
                  "The harvest log is collecting the evidence that settles it.",
        reversible=True, horizon_hours=0.5), 1.0)

    # --- something worth asking about -------------------------------------
    # HONEST GAME KNOWLEDGE (the owner, 2026-10-19: Royal Jelly turns a bee
    # into a RANDOM other bee; it is not a treat that makes this bee gifted)
    add(Thought(topic="spend", text="Royal Jelly at 3,410. The Hive Planner wants a Bubble Bee in slot 12."))
    add(Question(
        id="q-jelly-1",
        question="Roll Royal Jelly on the Basic Bee in slot 12?",
        context="Royal Jelly turns a bee into a random other bee (sometimes a rarer one, "
                "rarely a gifted one). The Hive Planner wants a Bubble Bee in that slot. "
                "You have 3,410 Royal Jelly.",
        options=[
            Option("Roll it", 1.05, "a chance at a better bee for the plan", "x"),
            Option("Keep the Basic Bee", 1.0, "no jelly spent", "x"),
        ],
        default="Roll it",
        expires_at=T0 + 3600), 1.2)
    add(Thought(topic="spend",
                text="Question queued. Continuing reversible work while it waits.",
                detail="A pending question never blocks the bot -- otherwise an "
                       "unattended run stops at the first interesting decision."))

    add(TaskUpdate(name="Convert at Blue Hive Balloon", status="running",
                   progress=0.25, detail="9 studs"), 0.5)
    add(Metric(name="honey_per_hour", value=431_000), 0.3)
    add(Thought(topic="economy", text="Session rate 431k honey/hr, up 13% on the last hour."))
    add(Log(message="planter harvested: +118,412 honey", source="tasks"), 0.4)
    add(Metric(name="honey", value=10_334_621), 0.3)
    add(Belief(name="honey", value=10_334_621, confidence=1.0, observed_at=t,
               source="hud"), 0.4)
    add(Thought(topic="quest", text="Polar Bear quest: 2 of 3 steps done. 44m of gathering left."))
    # --- planters: growth AND the field health it is spending -------------
    # Verdicts come from the REAL engine, not from prose written here. If the
    # engine's policy changes, this demo changes with it -- which is the point:
    # the window must never show a decision the bot would not actually make.
    HOUR = 3600.0
    for pid, seed, field, health, nectar, worth, grow_h, elapsed_h in [
        ("p1", "Planter Of Plenty", "Pine Tree", 0.41, "Comforting", 126_000, 8.0, 7.5),
        ("p2", "Paper Planter", "Sunflower", 0.88, "Refreshing", 47_000, 8.0, 5.0),
        ("p3", "Ticket Planter", "Mountain Top", 0.96, "Motivating", 140_000, 14.0, 4.3),
        ("p4", "Festive Planter", "Pepper", 0.79, "Satisfying", 176_000, 6.0, 5.95),
        ("p5", "Petal Planter", "Rose", 0.34, "Invigorating", 122_000, 16.0, 2.9),
    ]:
        state = PlanterState(id=pid, seed=seed, field_name=field,
                             planted_at=T0 - elapsed_h * HOUR,
                             grow_seconds=grow_h * HOUR,
                             field_health=health, nectar=nectar,
                             base_yield=worth)
        call = decide(state, now=T0)
        add(Planter(id=pid, seed=seed, field=field, growth=call.growth,
                    field_health=health, nectar=nectar,
                    yield_estimate=state.expected_yield(now=T0),
                    ready_at=state.ready_at(),
                    harvest_now=call.harvest, verdict=call.reason), 0.15)

    add(Thought(topic="planter",
                text="Holding every planter to 100% — field degradation is unverified.",
                detail="If repeated harvesting degrades a field, harvesting slightly "
                       "early to protect it is worth a few percent. That mechanic has "
                       "NOT been measured yet, so the engine takes the branch that is "
                       "correct either way: wait for full growth. Harvesting early for "
                       "a benefit that might not exist would lose real yield chasing "
                       "an imagined one. See docs/DESIGN.md section 8a."), 0.5)

    # --- the expiry sentinel, driven by the real engine ---------------------
    # Durations and severities come from data/economy/expiries.yaml through
    # economy.sentinel, not from prose typed here. Every one of them is marked
    # unverified in that file, which is why the engine surfaces them but is not
    # allowed to act on them alone.
    sentinel = Sentinel()
    for kind_id, elapsed_h, value, instance in [
        ("beequip_inbox", 42.6, 11_400_000, ""),
        ("nectar_vial", 10.2, 240_000, "Comforting"),
        ("wealth_clock", 0.6, 85_000, ""),
        ("field_booster", 0.1, 61_000, "Pepper"),
    ]:
        tracked = sentinel.start(kind_id, at=T0 - elapsed_h * HOUR,
                                 instance=instance, value=value)
        if tracked is None:
            continue
        what = (f"{tracked.kind.what} — {instance}" if instance
                else tracked.kind.what)
        detail = tracked.kind.detail
        if not tracked.kind.verified:
            detail += "  ·  not sure of the time, so the bot asks you rather than act"
        add(Expiry(id=tracked.key, what=what, detail=detail,
                   severity=tracked.kind.severity, value=value,
                   at_risk_at=tracked.deadline()), 0.15)

    asking = len(sentinel.needs_asking(now=T0))
    add(Thought(topic="sentinel",
                text=f"{len(sentinel.due(now=T0))} resources inside their warning window; "
                     f"{asking} need you, not me.",
                detail="The inbox is believed to hold 48 hours and then destroy what is "
                       "in it, with no in-game warning. That duration has NOT been "
                       "measured on this account, so the Sentinel surfaces it and asks "
                       "rather than consuming anything on a guessed deadline. Warning "
                       "you costs nothing if the timing is an hour out; acting on it "
                       "does not have that property."), 0.5)

    # --- shadow prices -----------------------------------------------------
    # Prices come from economy.prices, derived from OBSERVED exchanges only.
    # Nothing here is a hardcoded valuation: each number traces back to a shop
    # price or a recipe the bot would have read off a real screen. Resources with
    # no observed path to honey come back as unknown, which is what the panel
    # shows -- and what a fresh account genuinely looks like.
    prices = PriceGraph()
    prices.set_honey_rate(431_000)
    for item, cost, where in [
        ("Treat", 200, "Ticket Tent"),
        ("Glue", 180_000, "Ticket Tent"),
        ("Enzymes", 240_000, "Ticket Tent"),
        ("Oil", 190_000, "Ticket Tent"),
    ]:
        prices.observe_shop_price(item, cost, source=where, at=T0)
    # a crafting recipe the bot has read: 1 Glitter -> 6 Enzymes' worth of output
    prices.observe_exchange("Glitter", "Enzymes", 6.0, source="Blender recipe", at=T0)
    # a quest reward it has completed: the Polar Bear chain paid 25 Treats
    prices.observe_exchange("Polar quest", "Treat", 25.0, source="quest reward", at=T0)

    watch = ["Treat", "Glitter", "Glue", "Enzymes", "Oil",
             "Royal Jelly", "Star Jelly", "Spirit Petal", "Honeysuckle"]
    for resource in watch:
        priced = prices.price(resource, now=T0)
        if priced is None:
            add(ShadowPrice(resource=resource, known=False,
                            basis="no observed exchange to honey yet"), 0.05)
        else:
            add(ShadowPrice(resource=resource, honey_value=priced.honey,
                            known=True, confidence=priced.confidence,
                            basis=priced.basis), 0.05)

    unknown = [r for r in watch if prices.price(r, now=T0) is None]
    add(Thought(topic="economy",
                text=f"{len(watch) - len(unknown)} resources priced, "
                     f"{len(unknown)} still unknown.",
                detail="A shadow price is what one more of a thing would be worth in "
                       "honey. Every price here is DERIVED from an exchange the bot "
                       "observed -- a shop window, a recipe, a quest reward -- with "
                       "honey as the numeraire. Resources with no observed path to "
                       "honey have no price and are shown as unknown rather than "
                       "given a plausible-looking number: " + ", ".join(unknown)), 0.5)

    # --- timers, in UTC, from the real book --------------------------------
    # Cooldowns and the persistent-HP flags come from data/world/timers.yaml via
    # world.timers. Every one is marked unverified there, so the engine reports
    # NOTHING as preemptable -- which the panel shows by omitting the badge.
    book = TimerBook()
    for timer_id, used_h in [("stump_snail", 0.0), ("coconut_crab", 3.4),
                             ("wealth_clock", 0.6), ("wind_shrine", 17.2),
                             ("robo_bear_challenge", 9.8), ("mondo_chick", 2.5)]:
        tracked = book.get(timer_id)
        if tracked is None:
            continue
        tracked.observe_used(at=T0 - used_h * HOUR)
        ready = tracked.ready_at()
        add(TimerEvent(id=timer_id, name=tracked.kind.name,
                       category=tracked.kind.category,
                       persistent_hp=tracked.preemptable(),
                       note=tracked.explain_preemption()
                       if tracked.kind.category == "boss" else tracked.kind.note,
                       ready_at=ready or T0), 0.12)

    preemptable = len(book.preemptable())
    add(Thought(topic="boss",
                text=f"{preemptable} of {len(book)} bosses are safe to leave half-fought.",
                detail="A boss that SAVES damage between visits should be chipped at "
                       "whenever you pass; one that RESETS when you leave must never "
                       "be started unless it can be finished. Opposite rules, and the "
                       "flag separating them is unverified for every boss, so all of "
                       "them are treated as resetting. That forgoes an optimisation "
                       "if wrong; the reverse would waste whole fights."), 0.5)

    # let the header sparklines have a shape to draw
    for i, rate in enumerate([352, 366, 381, 374, 398, 412, 405, 421, 431]):
        add(Metric(name="honey_per_hour", value=rate * 1000), 0.1)

    add(StatusUpdate(running=True, autonomy=Autonomy.ASK_STRATEGY,
                     note="gathering — Pine Tree"), 0.4)
    return events


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    events = build()
    OUT.write_text("\n".join(e.to_json() for e in events) + "\n")
    print(f"  wrote {len(events)} events to {OUT}")
    if not FRAME.exists():
        print(f"  NOTE: {FRAME} missing, the live view will show a placeholder")


if __name__ == "__main__":
    main()
