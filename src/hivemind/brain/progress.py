"""Wanting something, and knowing what stands between here and it.

THE OWNER ASKED FOR THIS: it should know what it needs to do to get each
thing, what the next item to buy is, want to progress and get better, know how
to go anywhere, and have all that knowledge at its disposal.

Up to now the bot had `world.yaml` -- seventeen places to STAND -- and nothing
at all to AIM AT. It could not want anything because it knew of nothing worth
having. `data/knowledge/progression.yaml` is the other half, and this reads it.

WHAT A GOAL IS HERE. Something worth having, what it costs, and what is true or
untrue right now. Nothing more elaborate: no utility theory, no discounting, no
invented probabilities. Just "you want the Spark Staff, it costs 60,000,000
honey, you have 6,198,839, so you are 53,801,161 short".

IT SAYS WHAT IT DOES NOT KNOW, and that is a feature rather than an apology.
Thirteen of the game's twenty tools have no price in the knowledge base, the
hive slot cost is not on the wiki page, and eggs, quests and items are not
written down at all. A planner that silently skipped those would look like it
had a complete picture of progression and would quietly never suggest buying a
bee. So an unpriced goal is still a goal, reported as `blocked_by: "we do not
know what it costs"`, which is a thing the bot can be asked to go and find out.

WHAT IT DELIBERATELY DOES NOT DO. It does not claim the bot can reach a shop.
`brain/decide` knows there are recorded routes to five places and the Mountain
Top Shop is not one of them. Wanting something you cannot walk to is still
worth knowing -- it is what tells you which route to record next -- but it must
never be reported as an action the bot could take today.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

UNKNOWN = "unknown"


@dataclass
class Goal:
    """Something worth having, and the honest distance to it."""
    name: str
    kind: str                       # "tool" | "field" | "hive"
    why: str = ""
    cost: int | None = None         # honey; None when we do not know
    # SET WHEN `cost` IS ONLY A FLOOR. A Basic Egg costs "from 1,000 up to
    # 10,000,000" and the price of the next one can only be read in the shop.
    # Reporting the floor alone made the goal web draw it as affordable and
    # green -- an instruction to go and buy something whose real price nobody
    # knows. A range that is known to be a range must travel as one.
    cost_to: int | None = None
    have: int | None = None
    where: str | None = None        # shop or place it is obtained
    blocked_by: str = ""

    @property
    def shortfall(self) -> int | None:
        if self.cost is None or self.have is None:
            return None
        if self.cost_to is not None and self.cost_to != self.cost:
            # The distance to a price we do not know is not a number.
            return None
        return max(0, self.cost - self.have)

    @property
    def reachable_now(self) -> bool:
        return self.shortfall == 0

    def describe(self) -> str:
        pretty = self.name.replace("_", " ")
        if self.cost is None:
            return f"{pretty}: {self.blocked_by or 'cost unknown'}"
        if self.cost_to is not None and self.cost_to != self.cost:
            return (f"{pretty}: from {self.cost:,} honey up to "
                    f"{self.cost_to:,} — {self.blocked_by or 'price varies'}")
        if self.shortfall == 0:
            return (f"{pretty}: affordable now — {self.cost:,} honey"
                    + (f", at the {self.where.replace('_', ' ')}" if self.where else ""))
        return (f"{pretty}: {self.cost:,} honey, short by "
                f"{self.shortfall:,}"
                + (f" — {self.blocked_by}" if self.blocked_by else ""))


@dataclass
class Standing:
    """What the account has right now. Unknown is None, never zero."""
    honey: int | None = None
    bees: int | None = None
    tool: str | None = None
    fields_proven: tuple[str, ...] = ()
    # Which colour the hive is built around, if any. Changes which tool is
    # actually the best buy -- see Ladder.rate_for.
    colour: str | None = None


class Ladder:
    """Reads the progression knowledge and says what to work towards."""

    def __init__(self, progression: dict, world: dict | None = None):
        self.data = dict(progression or {})
        self.world = dict(world or {})
        tools = self.data.get("tools") or {}
        self.order: list[str] = list(tools.get("order") or [])
        self.known: dict = dict(tools.get("known") or {})
        self.unpriced: set = set(tools.get("unpriced") or [])
        # Rungs the community says to walk past. THE OWNER CAUGHT THIS: the
        # first version told them to save 60,000,000 honey for the Spark Staff
        # purely because the wiki lists it after the Golden Rake. "spark staff
        # is notoriously bad in the game, do ur research look what players
        # say." Order on a page is not value.
        self.skip: dict = dict(tools.get("skip") or {})
        self.shops: dict = dict(tools.get("shops") or {})
        self.hive: dict = dict(self.data.get("hive") or {})
        self.bees: dict = dict(self.data.get("bees") or {})
        self.gaps: dict = dict(self.data.get("not_yet_known") or {})
        # Things the owner asked for by name. Never reordered by ranking.
        self.wanted: dict = dict(self.data.get("wanted") or {})

    # MEASURED share of flowers of each colour in the fields this hive farms.
    # Not a guess and not a wiki figure: counted off 420 real frames of the
    # Pineapple Patch, which is where the bot gathers. See rate_for.
    MEASURED_COLOUR_SHARE = {"blue": 0.425, "white": 0.468, "red": 0.108}

    # HOW MUCH BETTER A TOOL HAS TO BE BEFORE IT IS WORTH BUYING.
    #
    # "Collects more" is not the same as "worth three and a half million
    # honey". With the colour bonus blended honestly the Bubble Wand comes to
    # 171 pollen/s against the Golden Rake's 167 -- a 1.02x gain, which is
    # inside the error of the flower-share measurement it rests on, for a sum
    # that takes hours to earn. Listing that as "the next item to buy" is how
    # a bot wastes an account's savings on a sidegrade.
    #
    # The owner has now caught this class of mistake twice, and both times they
    # was right: the Spark Staff, and then "isnt bubble wand worse than golden
    # rake". 1.15 is a judgement, not a measurement, and it is deliberately
    # generous: a tool that cannot clear it is not the reason this hive is
    # slow.
    MIN_UPGRADE_RATIO = 1.15

    def colour_share(self, colour: str) -> float:
        """What fraction of flowers are this colour, where we actually farm."""
        return self.MEASURED_COLOUR_SHARE.get(colour, 0.35)

    # ---- tools ------------------------------------------------------------
    def rate_for(self, name: str, colour: str | None = None) -> float | None:
        """A tool's pollen per second FOR THIS HIVE, or None if not recorded.

        A single number hides the whole point of a colour build. The Bubble
        Wand collects 240/s from blue flowers and 120/s from everything else;
        which of those is the real figure depends entirely on what the hive is
        built around. The Golden Rake's every-fifth-scoop supercharge is
        averaged in, because it happens on its own and is not a condition.
        """
        body = self.known.get(name) or {}
        base = body.get("pollen_per_second")
        if base is None:
            return None
        base = float(base)
        if colour:
            special = body.get(f"pollen_per_second_{colour}")
            if special is not None:
                # A COLOUR BONUS APPLIES TO FLOWERS, NOT TO FIELDS, and
                # treating the two as the same thing nearly cost 3,500,000
                # honey. The owner caught it: the Bubble Wand is worse than
                # the Golden Rake. They were right, and they were right about the Spark
                # Staff before it.
                #
                # The old code returned the colour figure whole, as if every
                # flower in a "blue" field were blue. MEASURED over 420 frames
                # of the Pineapple Patch the bot actually farms, the ground is
                # 42.5% blue, 46.8% white and 10.8% red. So the Bubble Wand
                # collects 240/s from two fifths of the flowers and 120/s from
                # the rest -- an effective 171/s against the Golden Rake's
                # 167/s. A 1.02x "upgrade" for three and a half million honey.
                #
                # The blend uses the measured fraction when there is one, and
                # otherwise a deliberately unflattering default: a bonus that
                # has not been measured should not be assumed to apply
                # everywhere.
                share = float(body.get(f"{colour}_flower_share",
                                       self.colour_share(colour)))
                share = min(1.0, max(0.0, share))
                return float(special) * share + base * (1.0 - share)
        super_rate = body.get("pollen_per_second_supercharged")
        if super_rate is not None:
            # One scoop in five, per the wiki's own description.
            return base * 0.8 + float(super_rate) * 0.2
        return base

    def upgrades(self, standing: Standing) -> list[Goal]:
        """Every tool that would actually collect more than the one held.

        Ranked by what it would do FOR THIS HIVE, cheapest-affordable first.
        This is the answer to "next item to buy is this", and it is a different
        answer from "the next one in the list" -- which is what produced the
        Spark Staff recommendation the owner correctly rejected.
        """
        colour = standing.colour
        held = self.rate_for(standing.tool or "", colour) if standing.tool else 0.0
        held = held or 0.0
        out: list[Goal] = []
        for name in self.order:
            if name == standing.tool or name in self.skip:
                continue
            rate = self.rate_for(name, colour)
            body = self.known.get(name) or {}
            cost = body.get("honey")
            if rate is None or cost is None or rate <= held:
                continue
            gain = rate / held if held else float("inf")
            # COLLECTING MORE IS NOT THE SAME AS BEING WORTH BUYING. See
            # MIN_UPGRADE_RATIO: the Bubble Wand clears `rate > held` by two
            # percent and costs 3,500,000 honey, and listing it as "the next
            # item to buy" is exactly the mistake the owner caught.
            if gain < self.MIN_UPGRADE_RATIO:
                continue
            # AND A CHEAPER TOOL IS NOT AN UPGRADE ON A DEARER ONE. This is a
            # sanity check on the data rather than on the game: if something
            # a fraction of the price appears to beat what we hold, the
            # likelier explanation is that its headline figure is conditional
            # -- a colour bonus, a supercharge, a full-backpack clause -- and
            # has been read as if it always applied. Say so instead of
            # spending the honey.
            held_cost = (self.known.get(standing.tool or "") or {}).get("honey")
            if held_cost and cost and int(cost) < int(held_cost):
                out.append(Goal(
                    name=name, kind="tool", cost=int(cost),
                    have=standing.honey, where=body.get("shop"),
                    why=(f"SKIPPED: claims {rate:,.0f} pollen/s for "
                         f"{int(cost):,} honey, but the tool we already hold "
                         f"cost {int(held_cost):,}. A cheaper tool beating a "
                         f"dearer one usually means its headline rate is "
                         f"conditional and has been read as if it always "
                         f"applied. Not recommended without checking."),
                    blocked_by="looks too cheap to be an upgrade"))
                continue
            extra = body.get("also_costs")
            why = (f"{rate:,.0f} pollen/s"
                   + (f" on {colour} flowers" if colour and
                      body.get(f"pollen_per_second_{colour}") is not None else "")
                   + (f", {gain:.2f}x what we hold" if held else ""))
            if body.get("colour") and colour and body["colour"] != colour:
                why += f"; it favours {body['colour']}, not {colour}"
            blocked = ""
            if extra:
                blocked = f"also needs {', '.join(str(x) for x in extra)}"
            out.append(Goal(name=name, kind="tool", cost=int(cost),
                            have=standing.honey, where=body.get("shop"),
                            why=why, blocked_by=blocked))
        out.sort(key=lambda g: (0 if g.shortfall == 0 else 1, g.cost or 0))
        return out

    def next_tool(self, standing: Standing) -> Goal | None:
        """The next rung on the tool ladder above the one held.

        Returns None only when the tool held is the last one in the game --
        an unpriced rung still comes back, saying it cannot be priced.
        """
        if not self.order:
            return None
        if standing.tool in self.order:
            after = self.order.index(standing.tool) + 1
        else:
            after = 0                    # unknown tool: aim at the bottom rung
        # Walk past anything the community says is a trap, and remember why
        # so the bot can say "I skipped the Spark Staff, here is who says so".
        skipped: list[str] = []
        while after < len(self.order) and self.order[after] in self.skip:
            skipped.append(self.order[after])
            after += 1
        if after >= len(self.order):
            return None

        name = self.order[after]
        body = self.known.get(name) or {}
        cost = body.get("honey")
        shop = body.get("shop")
        if cost is None:
            band = ""
            if shop and shop in self.shops:
                low = self.shops[shop].get("honey_from")
                band = f"; its shop starts around {low:,} honey" if low else ""
            return Goal(name=name, kind="tool", where=shop,
                        why=self._why_tool(skipped),
                        have=standing.honey,
                        blocked_by=f"we do not know what it costs{band}")
        return Goal(name=name, kind="tool", cost=int(cost), have=standing.honey,
                    where=shop, why=self._why_tool(skipped))

    def _why_tool(self, skipped: list[str]) -> str:
        why = "the next tool worth buying above the one we hold"
        for name in skipped:
            reason = (self.skip.get(name) or {}).get("reason", "")
            short = " ".join(str(reason).split())
            why += (f"; skipping the {name.replace('_', ' ')}"
                    + (f" — {short[:140]}" if short else ""))
        return why

    # ---- what the owner asked for -----------------------------------------
    def asked_for(self) -> list[Goal]:
        """Goals the owner named themselves. Never dropped for being inefficient."""
        out = []
        for name, body in self.wanted.items():
            body = body or {}
            steps = body.get("do_this") or []
            how = body.get("how")
            if steps:
                # A strategy is not "blocked" -- it is a way of playing, and
                # saying "we do not know how" about one would be nonsense.
                blocked = "; ".join(str(s).rstrip(".") for s in steps[:2])
            elif how and how != UNKNOWN:
                blocked = str(how)
            else:
                blocked = "we do not know how to get one yet"
            out.append(Goal(name=name, kind="wanted",
                            why=f"the owner asked for it: "
                                f"{str(body.get('quote', '')).strip()}",
                            where=body.get("kind"), blocked_by=blocked))
        return out

    # ---- fields -----------------------------------------------------------
    def next_field(self, standing: Standing) -> Goal | None:
        """The cheapest field in bees that we have not proved we can reach."""
        if standing.bees is None:
            return None
        locked = []
        for name, body in (self.world or {}).items():
            required = int((body or {}).get("bees_required", 0) or 0)
            if required > standing.bees and name not in standing.fields_proven:
                locked.append((required, name))
        if not locked:
            return None
        required, name = min(locked)
        return Goal(name=name, kind="field", where=name,
                    why="a field we cannot reach yet",
                    blocked_by=f"needs {required} bees and we have proved "
                               f"{standing.bees}")

    # ---- hive -------------------------------------------------------------
    def next_hive_slot(self, standing: Standing) -> Goal | None:
        """More bees. The thing that unlocks the map as well as the power."""
        if not self.hive:
            # Nothing written down about the hive at all. Wanting a slot we
            # cannot name, price or locate is not a goal, it is a sentence.
            return None
        top = int(self.hive.get("max_slots", 0) or 0)
        if standing.bees is not None and top and standing.bees >= top:
            return None
        cost = self.hive.get("slot_cost")
        where = self.hive.get("slots_bought_at")
        if cost in (None, UNKNOWN):
            return Goal(name="hive_slot", kind="hive", where=where,
                        have=standing.honey,
                        why=("bee count gates most of the map, so slots buy "
                             "places as well as power"),
                        blocked_by=("the wiki does not price hive slots — "
                                    "this has to be read in game at the "
                                    f"{str(where).replace('_', ' ')}"))
        return Goal(name="hive_slot", kind="hive", cost=int(cost),
                    have=standing.honey, where=where,
                    why="bee count gates most of the map")

    # ---- more bees --------------------------------------------------------
    def next_bee(self, standing: Standing) -> Goal | None:
        """Buy an egg. The one action that grows the hive AND opens the map.

        The price is a RANGE, not a number: a Basic Egg starts at 1,000 honey
        and the next one costs more every time, up to a cap of 10,000,000. How
        fast it climbs is not on the wiki, so the goal reports the floor it is
        certain about and says the rest has to be read in the shop.
        """
        egg = self.bees.get("basic_egg") or {}
        if not egg:
            return None
        floor = egg.get("honey_from")
        cap = egg.get("honey_cap")
        where = egg.get("shop")
        near = egg.get("near")
        blocked = ""
        if floor is not None and cap is not None:
            blocked = (f"the price climbs with every egg bought, from "
                       f"{int(floor):,} up to {int(cap):,} — the price of the "
                       "NEXT one has to be read in the shop")
        return Goal(name="basic_egg", kind="bee",
                    cost=int(floor) if floor is not None else None,
                    cost_to=int(cap) if cap is not None else None,
                    have=standing.honey, where=where,
                    why=("a bee is the only thing that raises the bee count, "
                         "and bee count gates most of the map"
                         + (f"; the shop is near the "
                            f"{str(near).replace('_', ' ')}" if near else "")),
                    blocked_by=blocked)

    # ---- the whole picture ------------------------------------------------
    def goals(self, standing: Standing) -> list[Goal]:
        """Everything worth working towards, affordable first, then closest."""
        # Prefer the colour-aware answer, which needs recorded pollen rates.
        # WHERE RATES ARE NOT KNOWN, fall back to the next rung in the list --
        # still skipping anything marked as a trap. Without this a tool whose
        # PRICE is recorded but whose RATE is not could never be recommended
        # at all, which is a silent hole rather than an honest gap.
        best_upgrade = self.upgrades(standing)
        tool_goal = best_upgrade[0] if best_upgrade else self.next_tool(standing)
        found = [g for g in (tool_goal,
                             self.next_bee(standing),
                             self.next_hive_slot(standing),
                             self.next_field(standing)) if g is not None]
        # What they asked for goes at the front, whatever the ranking thinks.
        asked = self.asked_for()

        def rank(goal: Goal):
            short = goal.shortfall
            # Affordable first, then nearest, then the ones we cannot price --
            # unknown last, because it is a research task rather than a plan.
            return (0 if short == 0 else 1 if short is not None else 2,
                    short if short is not None else 0)

        return asked + sorted(found, key=rank)

    def unknowns(self) -> list[str]:
        """The holes in its own knowledge, in words."""
        out = [f"{k}: {v}" for k, v in self.gaps.items()]
        if self.unpriced:
            out.append(f"{len(self.unpriced)} of {len(self.order)} tools have "
                       "no price recorded")
        return out

    def describe(self, standing: Standing) -> str:
        honey = f"{standing.honey:,}" if standing.honey is not None else "unknown"
        lines = [f"honey {honey}"
                 + (f", {standing.bees} bees proved" if standing.bees else "")
                 + (f", holding the {standing.tool.replace('_', ' ')}"
                    if standing.tool else "")]
        goals = self.goals(standing)
        if not goals:
            lines.append("  nothing left on the ladder that is written down")
        for goal in goals:
            lines.append(f"  - {goal.describe()}")
        holes = self.unknowns()
        if holes:
            lines.append("  what it still does not know:")
            lines.extend(f"      {h}" for h in holes)
        return "\n".join(lines)


def load(path: str | Path) -> dict:
    import yaml
    try:
        return yaml.safe_load(Path(path).read_text()) or {}
    except (OSError, ValueError):
        return {}
