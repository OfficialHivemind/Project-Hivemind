"""Putting the bot's real state on the wire, so the GUI shows the bot.

WHY THIS EXISTS. The owner, watching the GUI while the bot farmed: no goals,
no tokens seen, and no data in any tab. They were right, and the cause was not the
GUI. A socket sniff of a
live run over thirty seconds carried:

    frame 585      task 3      metric 3      and nothing else

The brain had already worked out which fields were worth going to, what it had
proved about the hive, and why it chose what it chose. None of it was ever
published, so every panel built to show it had nothing to draw. Two specific
misses, both measured rather than guessed:

  * The goal web only redraws when a metric named exactly `honey` arrives
    (`gui/window._metric`). The farm loop emits `honey_earned` and
    `honey_per_hour`, so the web never refreshed once in a whole session.
  * The header's vitals read metrics named `honey`, `pollen` and `bees`. None
    of the three was ever sent.

WHAT THIS IS. One place that translates state the bot already holds into the
events the GUI already understands. It is a translator, not a second source of
truth: every number here is passed in by whoever measured it, and nothing is
computed a second time. If this and the bot ever disagreed, this would be the
lie.

THE RULE THAT MATTERS MOST. A number that was not read is not sent. The HUD is
often unreadable -- mid-jump, mid-transition, during a dialog -- and the
reader reports that honestly as `None`. Publishing `None` as `0` would put a
confident zero on the owner's screen and, worse, into the goal web's idea of
what they can afford. Every entry point here takes `None` to mean "skip this
one", never "zero".

WHY IT IS RATE-LIMITED. The field ranking is seventeen events. Pushing it on
every loop iteration would be a few hundred events a second down a socket that
also carries the live view, to redraw a table that changes every few minutes.
`every` is a floor between full pushes; anything that genuinely changed --
the chosen field, the run state -- goes out immediately regardless.
"""
from __future__ import annotations

import time

from ..telemetry.events import (Autonomy, Belief, Considered, Metric, Option,
                                StatusUpdate, Thought)

# How often the full picture is re-sent when nothing has changed. The panels
# are a dashboard, not an instrument: five seconds is well inside what a human
# reads as live, and it keeps a seventeen-row table off the hot path.
EVERY_SECONDS = 5.0

# How many fields the ranking publishes. All seventeen are ranked; the ones
# below this are zero-scored and unreachable, and a panel that lists every
# place the bot cannot go buries the five it can.
TOP_FIELDS = 8


class Reporter:
    """Publishes what the bot knows, in the events the GUI already reads."""

    def __init__(self, emit, clock=time.monotonic, every: float = EVERY_SECONDS):
        self.emit = emit or (lambda event: None)
        self.clock = clock
        self.every = float(every)
        self.started_at = clock()
        # None rather than 0.0, for the reason in the module docstring: a
        # clock that starts at zero makes `now - last >= every` false on the
        # first call, and the first push is the one that matters most. This
        # exact bug has been shipped twice in this project.
        self._last_full: float | None = None
        self._last_chosen: str | None = None
        self._sent: dict[str, object] = {}

    # ---- vitals -----------------------------------------------------------
    def vitals(self, pollen=None, capacity=None, honey=None,
               bees=None, rate=None) -> None:
        """The header numbers. Anything `None` was not read, so is not sent.

        The names are not free choices -- `gui/window._metric` maps exactly
        `honey`, `pollen`, `bees` and `honey_per_hour`, and refreshes the goal
        web on `honey`. Sending `honey_total` instead would be silently
        ignored, which is what was happening.
        """
        if honey is not None:
            self._metric("honey", float(honey), "honey")
        if pollen is not None:
            self._metric("pollen", float(pollen), "pollen")
        if bees is not None:
            self._metric("bees", float(bees), "bees")
        if rate is not None:
            self._metric("honey_per_hour", float(rate), "honey/hr")
        if pollen is not None and capacity:
            self._metric("backpack_fill", 100.0 * pollen / capacity, "%")

    def _metric(self, name: str, value: float, unit: str) -> None:
        # Identical numbers are dropped. Pollen changes constantly and honey
        # barely ever does; re-sending an unchanged honey figure every five
        # seconds would rebuild the whole goal web for nothing.
        if self._sent.get(name) == value:
            return
        self._sent[name] = value
        self.emit(Metric(name=name, value=value, unit=unit))

    # ---- what it decided, and what it turned down -------------------------
    def plan(self, decision, ranked=None, notes=None) -> None:
        """The decision and the runners-up. `notes` is accepted and unused
        since the per-field rows moved to Dashboard.publish_fields (8du).

        `Thought(topic="plan")` is what makes the goal web mark a node as the
        thing being done now -- `gui/window` listens for exactly that topic.
        `Considered` is the priority list the owner asked to see. Both carry
        the planner's own words, not a summary made
        here.
        """
        if decision is None:
            return
        chosen = getattr(decision, "field", None) or getattr(decision, "action", "")
        text = decision.describe() if hasattr(decision, "describe") else str(decision)
        # The plan thought re-renders the whole web, so it goes out when the
        # decision actually changes rather than on every pass of the loop.
        if chosen != self._last_chosen:
            self._last_chosen = chosen
            self.emit(Thought(topic="plan", text=text,
                              detail=getattr(decision, "why", "")))

        ranked = list(ranked or getattr(decision, "alternatives", []) or [])
        if not ranked:
            return

        options = [Option(label=getattr(item, "pretty", item.field),
                          score=float(item.score), why=item.why,
                          unit="pollen/s" if item.rate else "score")
                   for item in ranked[:TOP_FIELDS]]
        self.emit(Considered(
            question="Which field next?",
            options=options,
            chosen=str(chosen or ""),
            rationale=getattr(decision, "why", ""),
            reversible=True))
        # NO FIELD ROWS FROM HERE (DESIGN 8du). This sent one per ranked field
        # with a hardcoded "0 tokens", no rate and no visits, named "pine
        # tree" where the Fields tab wanted "Pine Tree", so none ever landed.
        # With the names matched it would have overwritten the measured row
        # from Dashboard.publish_fields with zeros on every trip. That row is
        # the one the tab needs, so it is the only one sent.

    # ---- B8: THE ERRAND CHOICE, IN PLAIN ENGLISH ---------------------------
    # The field choice already reached the think pane and the feed (`plan`);
    # the errand after a convert was only Log lines with "Q +5k" in them. The
    # same Considered card now says which errand, what each would pay against
    # the gathering its walk costs, and why this one -- from the numbers
    # brain/value already priced, nothing worked out again here.
    def errand(self, rows, chosen, rate: float = 0.0, picker: str = "fixed") -> None:
        """`rows`: brain/value.Scored; `chosen`: the place it is walking to."""
        if not chosen:
            return
        rows = list(rows or [])
        options = [Option(label=r.name.replace("_", " "),
                          score=float(r.q or 0.0), why=errand_why(r, rate),
                          unit="honey") for r in rows[:TOP_FIELDS]]
        mine = next((r for r in rows if r.name == chosen), None)
        why = errand_why(mine, rate) if mine is not None else "no price for it yet"
        how = {"plan": "the best-paying order of the next few errands",
               "smith": "the most honey for each second away",
               "fallback": "today's fixed order (the priced plan failed)"}.get(
                   picker, "today's fixed order")
        self.emit(Considered(
            question="Which errand next?", options=options,
            chosen=chosen.replace("_", " "),
            rationale=f"{why}; picked by {how}", reversible=True,
            topic="errand"))

    # ---- facts, with where they came from ---------------------------------
    def belief(self, name: str, value, source: str,
               confidence: float = 1.0) -> None:
        """One fact. `source` is how it is known, and it is not decoration.

        The beliefs panel shows it so the owner can tell "the game told us" from
        "we worked it out", which is the difference between a fact and an
        inference on a screen that shows both.
        """
        if value is None:
            return
        if self._sent.get(f"belief:{name}") == value:
            return
        self._sent[f"belief:{name}"] = value
        self.emit(Belief(name=name, value=value, confidence=float(confidence),
                         observed_at=time.time(), source=source))

    # ---- run state --------------------------------------------------------
    def status(self, running: bool, paused: bool = False,
               handed_over: bool = False, note: str = "",
               autonomy: Autonomy | None = None) -> None:
        self.emit(StatusUpdate(running=running, paused=paused,
                               handed_over=handed_over, note=note,
                               autonomy=autonomy,
                               uptime_s=self.clock() - self.started_at))

    # ---- the periodic push ------------------------------------------------
    def due(self) -> bool:
        """True at most once per `every`, and True the very first time."""
        now = self.clock()
        if self._last_full is not None and now - self._last_full < self.every:
            return False
        self._last_full = now
        return True


def errand_why(r, rate: float = 0.0) -> str:
    """One errand's price in plain words (B8): what it pays, what its walk
    costs in gathering, how often it lands. Unpriced says so, never a guess."""
    if r is None or r.v is None:
        return "no measured price yet, so it keeps today's order"
    cost = rate * r.seconds
    text = (f"pays about {r.p * r.v / 1e6:.2f}M honey, its {r.seconds:.0f}s away "
            f"cost about {cost / 1e6:.2f}M of gathering")
    text += f", {r.p:.0%} of trips land"
    if r.ready_in > 0:
        text += f", due in {r.ready_in:.0f}s"
    return text
