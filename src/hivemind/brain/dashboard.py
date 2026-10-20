"""Filling every tab of the GUI from real data, or saying why a tab is empty.

THE OWNER ASKED FOR THIS: "can you build every tab in the gui". Nine tabs, and
the panels behind all nine have existed for days -- roughly three thousand lines
of them. What was missing was never the drawing; it was that the live loop
published five of the nine panels' events NOWHERE. `scripts/make_demo.py` drove
them for the `--demo` replay and nothing drove them for real, which is why the
Economy, Fields, Account and Vision tabs were blank during an actual run while
the engines behind them sat idle (docs/GAPS.md §9).

This module is the missing half. It is called on a slow timer from the farm loop
and it does one thing: turn what the bot ACTUALLY knows into the events each
panel reads.

THE RULE IT OBEYS, which is the owner's: "dont add fake things for looks it
needs to work and actaully be useefull to me". So every tab falls into exactly
one of three states, and never a fourth:

  REAL      the number comes from a measurement or from a knowledge file that
            cites its source. Timers, shadow prices, fields, account, vision.
  HONEST    the panel is empty and SAYS WHY, in the panel itself. Planters and
            the Expiry Sentinel are here: the bot has never seen a planter and
            cannot read the inventory, so there is nothing truthful to draw.
  NEVER     a row invented so the tab looks populated. There are none.

WHAT IS GENUINELY NEW HERE, rather than merely wired up: the shadow prices. The
bot measures its own honey per hour and its own pollen-to-honey conversion, and
`data/knowledge` records what a Royal Jelly costs in tickets at the dispenser
and in honey at the shop. Those three facts together price a TICKET in honey --
a number no human player has in front of them, derived from observations rather
than asserted. `economy/prices.PriceGraph` does the deriving; this only feeds it.
"""
from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass
from typing import Callable

from ..economy.prices import HONEY, PriceGraph
from ..telemetry.events import (Belief, FieldStatus, Log, Metric, ShadowPrice,
                                Thought)
from ..telemetry.events import Planter as PlanterEvent
from ..telemetry.events import Timer as TimerEvent
from ..world.timers import TimerBook

# How often the slow panels are refreshed. They show hours and cooldowns, so a
# minute of staleness is invisible, and every refresh is a burst of socket
# traffic the farm loop does not need mid-walk.
EVERY_SECONDS = 60.0

# Resources worth pricing. Each one is either priced from an observation or
# reported as unknown -- there is no third outcome.
WATCHED = ("Ticket", "Royal Jelly", "Pollen", "Treat", "Glitter", "Gumdrop",
           "Stinger", "Field Dice", "Star Treat", "Honeysuckle",
           "Golden Rake", "Bubble Wand", "Porcelain Dipper")


@dataclass
class Gap:
    """A panel that cannot be filled, and the reason, for the panel to show."""
    panel: str
    why: str


# WHY THE TWO EMPTY PANELS ARE EMPTY. Not a excuse: each of these is a specific,
# checkable blocker, and each is the same sentence `world/settings.BLOCKED_BY`
# gives for the switch that would drive it. When one of these becomes false the
# panel fills itself, because the engine behind it already works.
# (THE PLANTERS LEFT THIS LIST 2026-10-21: act/planter has placed and harvested
# them since 7 Oct -- var/planters.json, 9 harvests -- and publish_planters
# shows the ones out; the old sentence told the owner the opposite.)
GAPS = (
    Gap("expiry sentinel",
        "nothing reads the inventory yet, so no decaying item can be tracked "
        "from the game. The 48-hour Beequip Inbox is the one that matters and "
        "the bot cannot see it. Show it the inbox once."),
)


class Dashboard:
    """Publishes what the slow panels need. Never invents a row."""

    def __init__(self, emit: Callable, *, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time,
                 every: float = EVERY_SECONDS, timers_path=None,
                 knowledge=None, planters_path=None):
        self.emit = emit
        self.clock = clock
        self.wall = wall
        self.every = float(every)
        self.knowledge = knowledge
        self.planters_path = planters_path
        self._last = -1e9
        self._said_gaps = False
        self.prices = PriceGraph()
        try:
            self.book = TimerBook(timers_path) if timers_path else TimerBook()
        except Exception:
            self.book = None
        self._priced_from: list[str] = []

    # ---- pacing -------------------------------------------------------------
    def due(self) -> bool:
        return self.clock() - self._last >= self.every

    def refresh(self, *, standing=None, notes=None, ranked=None,
                honey_per_hour: float | None = None,
                pollen_per_honey: float | None = None,
                detections: dict | None = None, force: bool = False) -> bool:
        """Fill every slow panel. Returns True when it actually published.

        Every argument is optional and a missing one costs only the rows it
        would have produced -- a dashboard that refused to draw the timers
        because the honey rate was unknown would be the wrong trade.
        """
        if not force and not self.due():
            return False
        self._last = self.clock()
        self._safely(self.say_gaps)
        self._safely(self.publish_timers)
        self._safely(self.publish_planters)
        self._safely(lambda: self.publish_prices(honey_per_hour, pollen_per_honey))
        self._safely(lambda: self.publish_fields(ranked, notes))
        self._safely(lambda: self.publish_account(standing))
        self._safely(lambda: self.publish_vision(detections))
        return True

    def _safely(self, work: Callable) -> None:
        """A dashboard must never be able to end a farming run."""
        try:
            work()
        except Exception as exc:
            try:
                self.emit(Log(message=f"dashboard: {exc}", source="dashboard"))
            except Exception:
                pass

    # ---- the tabs -----------------------------------------------------------
    def say_gaps(self) -> None:
        """Tell the GUI why the two unfillable panels are empty. Once."""
        if self._said_gaps:
            return
        self._said_gaps = True
        for gap in GAPS:
            self.emit(Thought(topic="gap", text=f"{gap.panel}: {gap.why}"))

    def publish_planters(self) -> int:
        """The planters out (var/planters.json, act/planter's own record):
        where, how grown, and when the harvest step will call them due."""
        if self.planters_path is None:
            return 0
        from ..act import planter as planter_mod
        state = planter_mod.load(self.planters_path)
        now = self.wall()
        sent = 0
        for key, body in (state.get("out") or {}).items():
            if key not in planter_mod.PLANTERS or not isinstance(body, dict):
                continue
            grow = planter_mod.planter_grow_s(state, key)
            placed = float(body.get("at") or 0.0)
            due, _early = planter_mod.due_at(state, key)
            self.emit(PlanterEvent(id=key, seed=planter_mod.PLANTERS[key][0],
                                   field=str(body.get("field") or ""),
                                   growth=max(0.0, min(1.0, (now - placed) / grow)) if grow else 0.0,
                                   ready_at=float(due), harvest_now=due <= now))
            sent += 1
        return sent

    def publish_timers(self) -> int:
        """Bosses, machines, shrines and events, with their cooldowns.

        Real, and honest about which end is which: `world/timers` prefers a
        cooldown it has OBSERVED over the one in the file, and everything in
        the file is `verified: false`. A timer nobody has ever seen used has no
        deadline at all, and is published with `ready_at = 0` so the panel can
        show it as unknown rather than as due now.
        """
        if self.book is None:
            return 0
        sent = 0
        for state in self.book.states.values():
            kind = state.kind
            ready_at = state.ready_at()
            note = str(getattr(kind, "note", "") or "")
            if ready_at is None:
                note = (note + "; never seen used, so no deadline is offered").strip("; ")
            if not state.cooldown_is_measured:
                note = (note + "; cooldown unverified, from the knowledge base").strip("; ")
            self.emit(TimerEvent(
                id=str(getattr(kind, "id", "")),
                name=str(getattr(kind, "name", "")),
                ready_at=float(ready_at) if ready_at is not None else 0.0,
                category=str(getattr(kind, "category", "")),
                persistent_hp=bool(getattr(kind, "persistent_hp", False)),
                note=note))
            sent += 1
        return sent

    def publish_prices(self, honey_per_hour: float | None,
                       pollen_per_honey: float | None) -> int:
        """Shadow prices, derived from observations only.

        WHAT MAKES THIS REAL rather than a table of wiki numbers: the inputs are
        things the bot measured or the knowledge base cites.

          honey per hour      MEASURED by the farm loop this session
          pollen -> honey     MEASURED: the convert delta over the pollen spent
          Royal Jelly         6 tickets at the dispenser (data/knowledge)
          Royal Jelly         250,000-1,000,000 honey at the shop (same)

        The last two together are what price a TICKET, which is the number that
        matters most on this account: it held 422 of them on 2026-09-20 and the
        guide routes gifting through the Ticket Shop.
        """
        now = self.wall()
        if honey_per_hour:
            self.prices.set_honey_rate(float(honey_per_hour))
        if pollen_per_honey and pollen_per_honey > 0:
            # One pollen becomes this much honey when converted at the hive.
            self.prices.observe_exchange(
                "Pollen", HONEY, float(pollen_per_honey),
                source="measured at the hive", at=now)
        self._observe_knowledge(now)

        sent = 0
        for resource in WATCHED:
            priced = self.prices.price(resource, now=now)
            if priced is None:
                self.emit(ShadowPrice(
                    resource=resource, known=False, honey_value=0.0,
                    basis="no observed path from this to honey"))
            else:
                self.emit(ShadowPrice(
                    resource=resource, known=True,
                    honey_value=float(priced.honey),
                    confidence=float(priced.confidence),
                    basis=str(priced.basis)))
            sent += 1
        if self.prices.honey_per_hour:
            hour = self.prices.price_of_time(3600.0)
            if hour:
                self.emit(Metric(name="price_of_an_hour", value=float(hour),
                                 unit="honey"))
        return sent

    def _observe_knowledge(self, now: float) -> None:
        """Feed the price graph the exchanges the knowledge base can cite.

        Every observation here names its file. Nothing is asserted: if a fact
        is not in the knowledge base the exchange is simply not made, and the
        resource comes out of `publish_prices` as unknown.
        """
        if self.knowledge is None:
            return

        def safely(getter):
            try:
                return getter() or {}
            except Exception:
                return {}

        items = safely(self.knowledge.items)
        jelly_prices = ((items.get("royal_jelly") or {}).get("prices") or {})

        # ROYAL JELLY FOR HONEY, at the shop near the Red HQ. The knowledge
        # base gives a RANGE -- 250,000 rising by 10,000 a purchase to a
        # 1,000,000 cap -- and the LOW end is used. Pricing a resource at its
        # best case is how a valuation model talks itself into a bad purchase.
        shop = jelly_prices.get("royal_jelly_shop") or {}
        floor = shop.get("honey_from")
        if floor:
            self.prices.observe_shop_price(
                "Royal Jelly", float(floor),
                source="shop near the Red HQ, low end of its rising price",
                at=now)

        # ROYAL JELLY FOR TICKETS, at the dispenser. This is the hop that
        # prices a ticket, and a ticket is the live currency on this account:
        # account.yaml recorded 422 of them and the owner's guide routes
        # gifting through the Ticket Shop.
        dispenser = jelly_prices.get("dispenser") or {}
        per_jelly = dispenser.get("tickets")
        if per_jelly:
            self.prices.observe_exchange(
                "Ticket", "Royal Jelly", 1.0 / float(per_jelly),
                source=f"{float(per_jelly):.0f} tickets at the dispenser", at=now)

        # TOOLS, whose shop prices are recorded outright. A tool is not a
        # resource anyone trades, but its price bounds what honey is worth
        # spending on one, and the panel is where the owner sees that.
        tools = (safely(self.knowledge.progression).get("tools") or {}).get("known") or {}
        for name, body in tools.items():
            cost = (body or {}).get("honey")
            if cost:
                self.prices.observe_shop_price(
                    name.replace("_", " ").title(), float(cost),
                    source="tool price in the knowledge base", at=now)

    def publish_fields(self, ranked=None, notes=None) -> int:
        """Every field, its record and whether it is the one to go to.

        The Fields tab used to receive only the fields the planner happened to
        rank in the cycle that just ran. Now every field the world model knows
        is published, so a field with no route or too few bees is VISIBLE as
        such instead of simply absent.
        """
        if not ranked:
            return 0
        sent = 0
        best = next((s for s in ranked if getattr(s, "score", 0) > 0), None)
        for score in ranked:
            name = str(getattr(score, "field", ""))
            if not name:
                continue
            note = getattr(notes, "known", lambda _n: None)(name) if notes else None
            # THE MEASURED RECORD, which was not being sent at all. The tab
            # drew a hardcoded full-health bar and a hardcoded "0 tokens"
            # while these numbers sat in `brain.fieldnotes` unused. Health and
            # the token count stay at -1 because nothing measures either one.
            self.emit(FieldStatus(
                name=name,
                mobs=len(getattr(score, "mobs", ()) or ()),
                # Wall clock, not the notes' monotonic `last_seen`: the
                # panel ages it against time.time() (Note.last_wall).
                last_visited=float(getattr(note, "last_wall", 0.0) or 0.0),
                recommended=(score is best),
                rate=float(getattr(note, "rate", 0.0) or 0.0),
                pollen=int(getattr(note, "pollen", 0) or 0),
                visits=int(getattr(note, "visits", 0) or 0),
                seconds=float(getattr(note, "seconds", 0.0) or 0.0),
                deaths=int(getattr(note, "deaths", 0) or 0),
                note=str(getattr(score, "why", ""))[:200]))
            sent += 1
        return sent

    def publish_account(self, standing=None) -> int:
        """The Account tab: what is true of this account, and how it is known.

        `source` is the point of the panel -- it shows the difference between a
        number the bot measured and one the owner told it, which is the
        difference between a fact and testimony.
        """
        sent = 0
        # WHEN account.yaml WAS TRUE, not when it was re-sent (DESIGN 8du).
        # Every row went out with observed_at=now, so the Account tab showed
        # "26 bees, 0s ago" for a count taken from the owner's screenshot on
        # 2026-09-20 -- the one thing that panel exists to show. The file
        # records its own date (`checked:`); failing that, its mtime.
        try:
            account = (self.knowledge.account() or {}) if self.knowledge else {}
        except Exception:
            account = {}
        written = _account_dated(account)

        def say(name, value, source, confidence=1.0, at=None):
            nonlocal sent
            if value is None:
                return
            self.emit(Belief(name=name, value=value, source=source,
                             confidence=confidence,
                             observed_at=self.wall() if at is None else at))
            sent += 1

        if standing is not None:
            # honey IS read off the HUD, now; the rest is knowledge.standing(),
            # which is account.yaml
            say("honey", getattr(standing, "honey", None), "read from the HUD")
            hive = account.get("hive") or {}
            say("bees", getattr(standing, "bees", None),
                f"account.yaml: {hive.get('source') or 'the owner'}",
                at=written)
            say("tool held", getattr(standing, "tool", None),
                "account.yaml: the owner said so", at=written)
            say("hive colour", getattr(standing, "colour", None),
                "account.yaml: the owner said so", at=written)
            proven = getattr(standing, "fields_proven", ()) or ()
            if proven:
                say("fields gathered in", f"{len(proven)}: " + ", ".join(sorted(proven)),
                    "proved by earning there")

        if self.knowledge is None or not account:
            return sent
        hive = account.get("hive") or {}
        # MEASURED BY THE BOT (act/beemenu's header read) is a fact, dated by
        # its own `measured_at`; the owner's screenshot stays testimony.
        hive_source = str(hive.get("source", "the owner's screenshot"))
        measured = hive_source.startswith("measured")
        say("bee types discovered", hive.get("bee_types_discovered"), hive_source,
            1.0 if measured else 0.7,
            at=(_measured_at(hive.get("measured_at")) or written) if measured
            else written)
        inventory = account.get("inventory") or {}
        for item in ("tickets", "gumdrops", "stinger", "field_dice", "royal_jelly"):
            if item in inventory:
                say(item.replace("_", " "), inventory[item],
                    str(inventory.get("source", "the owner's screenshot")), 0.6,
                    at=written)
        for badge, body in (account.get("badges") or {}).items():
            if isinstance(body, dict) and "tier" in body:
                say(f"badge: {badge}", f"{body.get('tier')} ({body.get('gives', '')})",
                    "the owner's screenshot", 0.6, at=written)
        return sent

    def publish_vision(self, detections: dict | None) -> int:
        """The Vision tab: what the detectors are actually finding, live.

        Counts rather than boxes: the live view already draws the frame, and a
        number per detector is what says whether a detector is working at all.
        """
        if not detections:
            return 0
        sent = 0
        for name, value in detections.items():
            if value is None:
                continue
            self.emit(Metric(name=f"seen_{name}", value=float(value), unit="count"))
            sent += 1
        return sent


def _measured_at(text) -> float | None:
    """account.yaml's "YYYY-MM-DD HH:MM" as local epoch seconds, or None."""
    import datetime as _dt
    try:
        return _dt.datetime.strptime(str(text), "%Y-%m-%d %H:%M").timestamp()
    except (TypeError, ValueError):
        return None


def _account_dated(account: dict) -> float | None:
    """When data/knowledge/account.yaml was last true, as a wall-clock time.

    Its own `checked:` date (local midnight of that day) when it has one,
    else the file's mtime, else None -- and None makes `say` fall back to
    now, which is only ever right for a reading taken now.
    """
    checked = (account or {}).get("checked")
    try:
        if checked is not None:
            day = (checked if hasattr(checked, "timetuple")
                   else _dt.date.fromisoformat(str(checked)))
            return time.mktime(day.timetuple()[:3] + (0, 0, 0, 0, 0, -1))
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        from .knowledge import account_path      # the alt's own; config dir first
        return account_path().stat().st_mtime
    except OSError:
        return None
